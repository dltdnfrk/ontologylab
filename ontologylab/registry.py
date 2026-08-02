"""Local registry caches and the EPPO import-first adapter.

EPPO no longer offers an automatic SQLite snapshot download. A user imports a
licensed export into a small, stable schema here; callers then depend on that
schema instead of on whichever export layout EPPO currently ships.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from ontologylab.connectors.allowlist import check_url
from ontologylab.paths import (
    assert_network_allowed,
    eppo_registry_path,
    moa_registry_path,
    pubchem_registry_path,
)

EPPO_API_TOKEN_ENV = "EPPO_API_TOKEN"
EPPO_API_INFO_URL = "https://data.eppo.int/api/rest/1.0/tools/ping"
_FETCH_TIMEOUT_S = 30
_MAX_INFO_BYTES = 1024 * 1024

_CODE_COLUMNS = ("code", "eppo_code", "eppocode")
_NAME_COLUMNS = ("name", "scientific_name", "fullname", "full_name")
_KIND_COLUMNS = ("type", "name_type", "kind", "name_kind")


class RegistryImportError(ValueError):
    """The supplied export cannot be converted without guessing its schema."""


def _normalize_column(value: str) -> str:
    return value.strip().casefold().replace(" ", "_").replace("-", "_")


def _find_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    by_normalized = {_normalize_column(column): column for column in columns}
    for candidate in candidates:
        if candidate in by_normalized:
            return by_normalized[candidate]
    return None


def _normalize_surface(value: str) -> str:
    """Normalize only case and whitespace; punctuation remains identity-bearing."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _normalize_kind(value: str | None, *, name_column: str) -> str:
    if value is None or not value.strip():
        # A column explicitly called scientific_name carries that fact. A
        # generic `name` does not: calling it scientific would invent source
        # semantics solely to make the count prettier.
        return (
            "scientific"
            if _normalize_column(name_column) == "scientific_name"
            else "unspecified"
        )
    kind = " ".join(value.casefold().replace("_", " ").replace("-", " ").split())
    if kind in {"scientific", "scientific name", "accepted", "preferred"}:
        return "scientific"
    if kind in {"synonym", "synonyms", "alternative", "alternate"}:
        return "synonym"
    if kind in {"common", "common name", "vernacular", "vernacular name"}:
        return "common"
    # Unknown labels are retained and visible in metadata. Dropping the row
    # or laundering it into one of the three known kinds would both hide an
    # export-schema change.
    return f"other:{kind}"


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _csv_rows(path: Path) -> Iterator[tuple[str, str, str, str]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise RegistryImportError(f"cannot read EPPO CSV export {path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        code_column = _find_column(columns, _CODE_COLUMNS)
        name_column = _find_column(columns, _NAME_COLUMNS)
        kind_column = _find_column(columns, _KIND_COLUMNS)
        if code_column is None or name_column is None:
            shown = ", ".join(columns) or "no header"
            raise RegistryImportError(
                "EPPO CSV has no recognizable code and name columns "
                f"(found: {shown}); provide a CSV with code,name,type columns"
            )
        for line_number, row in enumerate(reader, start=2):
            code = (row.get(code_column) or "").strip()
            name = (row.get(name_column) or "").strip()
            if not code or not name:
                raise RegistryImportError(
                    f"EPPO CSV row {line_number} has an empty code or name; "
                    "fix the export rather than silently dropping the row"
                )
            raw_kind = row.get(kind_column) if kind_column else None
            yield code, name, _normalize_kind(raw_kind, name_column=name_column), ""


def _sqlite_layout(path: Path) -> tuple[list[tuple[str, str, str, str | None]], list[str]]:
    compatible: list[tuple[str, str, str, str | None]] = []
    described: list[str] = []
    try:
        with sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True
        ) as source:
            tables = [
                str(row[0])
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for table in tables:
                columns = [
                    str(row[1])
                    for row in source.execute(
                        f"PRAGMA table_info({_quote_identifier(table)})"
                    )
                ]
                described.append(f"{table}({', '.join(columns)})")
                code_column = _find_column(columns, _CODE_COLUMNS)
                name_column = _find_column(columns, _NAME_COLUMNS)
                if code_column is None or name_column is None:
                    continue
                compatible.append(
                    (
                        table,
                        code_column,
                        name_column,
                        _find_column(columns, _KIND_COLUMNS),
                    )
                )
    except sqlite3.Error as exc:
        raise RegistryImportError(f"cannot inspect EPPO SQLite export {path}: {exc}") from exc
    if not compatible:
        schema = "; ".join(described) or "no user tables"
        raise RegistryImportError(
            "EPPO SQLite export has no table with code and name columns. "
            f"Observed schema: {schema}. Export a flat table containing code/name "
            "columns, or convert it to CSV with code,name,type columns; the adapter "
            "will not guess joins or column meanings."
        )
    return compatible, described


def _sqlite_rows(
    path: Path, layout: list[tuple[str, str, str, str | None]]
) -> Iterator[tuple[str, str, str, str]]:
    try:
        source = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RegistryImportError(f"cannot read EPPO SQLite export {path}: {exc}") from exc
    with source:
        for table, code_column, name_column, kind_column in layout:
            selected = [code_column, name_column]
            if kind_column:
                selected.append(kind_column)
            query = "SELECT " + ", ".join(map(_quote_identifier, selected))
            query += " FROM " + _quote_identifier(table)
            try:
                rows = source.execute(query)
                for row_number, row in enumerate(rows, start=1):
                    code = str(row[0] or "").strip()
                    name = str(row[1] or "").strip()
                    if not code or not name:
                        raise RegistryImportError(
                            f"EPPO SQLite {table} row {row_number} has an empty "
                            "code or name; fix the export rather than silently "
                            "dropping the row"
                        )
                    raw_kind = str(row[2]) if kind_column and row[2] is not None else None
                    yield (
                        code,
                        name,
                        _normalize_kind(raw_kind, name_column=name_column),
                        table,
                    )
            except sqlite3.Error as exc:
                raise RegistryImportError(
                    f"cannot read compatible EPPO table {table!r}: {exc}"
                ) from exc


def _sha256(path: Path, *, source_name: str = "registry export") -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RegistryImportError(f"cannot read {source_name} {path}: {exc}") from exc
    return digest.hexdigest()


def import_eppo(source_path: Path | str, data_dir: Path | str) -> dict:
    """Import a CSV or SQLite EPPO export into an atomically replaced cache."""
    source = Path(source_path)
    if not source.is_file():
        raise RegistryImportError(f"EPPO export does not exist or is not a file: {source}")
    source_hash = _sha256(source, source_name="EPPO export")
    try:
        with source.open("rb") as handle:
            is_sqlite = handle.read(16) == b"SQLite format 3\x00"
    except OSError as exc:
        raise RegistryImportError(f"cannot read EPPO export {source}: {exc}") from exc

    tables: list[str] = []
    if is_sqlite:
        layout, _schema = _sqlite_layout(source)
        tables = [item[0] for item in layout]
        rows = _sqlite_rows(source, layout)
        source_description = f"EPPO SQLite export: {source.name}"
    else:
        rows = _csv_rows(source)
        source_description = f"EPPO CSV export: {source.name}"

    target = eppo_registry_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".sqlite.tmp")
    try:
        tmp.unlink(missing_ok=True)
        with sqlite3.connect(tmp) as cache:
            cache.executescript(
                """
                CREATE TABLE surface_forms (
                    normalized_name TEXT PRIMARY KEY,
                    surface_form TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name_kind TEXT NOT NULL
                );
                CREATE INDEX surface_forms_code_idx ON surface_forms(code);
                CREATE TABLE cache_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL
                );
                """
            )
            counts: dict[str, int] = {}
            row_count = 0
            for code, name, kind, origin in rows:
                row_count += 1
                counts[kind] = counts.get(kind, 0) + 1
                normalized = _normalize_surface(name)
                if not normalized:
                    raise RegistryImportError(
                        f"EPPO name {name!r} normalizes to empty text"
                    )
                existing = cache.execute(
                    "SELECT code FROM surface_forms WHERE normalized_name = ?",
                    (normalized,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != code:
                        location = f" in table {origin!r}" if origin else ""
                        raise RegistryImportError(
                            f"EPPO surface form {name!r}{location} maps to both "
                            f"{existing[0]!r} and {code!r}; resolve the source "
                            "conflict rather than silently overwriting a code"
                        )
                    continue
                cache.execute(
                    "INSERT INTO surface_forms VALUES (?, ?, ?, ?)",
                    (normalized, name, code, kind),
                )
            if row_count == 0:
                raise RegistryImportError(
                    "EPPO export contains no name rows; the existing cache was not changed"
                )
            surface_count = int(
                cache.execute("SELECT COUNT(*) FROM surface_forms").fetchone()[0]
            )
            record_counts = {
                "rows": row_count,
                "surface_forms": surface_count,
                **counts,
            }
            metadata = {
                "registry": "eppo",
                "source_description": source_description,
                "import_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "record_counts": record_counts,
                "source_file_sha256": source_hash,
            }
            cache.execute(
                "INSERT INTO cache_metadata VALUES (1, ?)",
                (json.dumps(metadata, sort_keys=True),),
            )
        tmp.replace(target)
    except (sqlite3.Error, OSError) as exc:
        raise RegistryImportError(f"cannot write EPPO registry cache {target}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return {"counts": counts, "record_counts": record_counts, "tables": tables, "metadata": metadata}


_CAS_PATTERN = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")


def _is_cas_number(value: str) -> bool:
    """Recognize CAS registry numbers, including their check digit."""
    match = _CAS_PATTERN.fullmatch(value)
    if match is None:
        return False
    digits = match.group(1) + match.group(2)
    checksum = sum(
        int(digit) * weight
        for weight, digit in enumerate(reversed(digits), start=1)
    )
    return checksum % 10 == int(match.group(3))


def _pubchem_lines(path: Path) -> Iterator[tuple[int, str, str]]:
    """Read PubChem's documented CID-Synonym-filtered two-column TSV."""
    try:
        raw = path.open("rb")
        magic = raw.read(2)
        raw.seek(0)
        binary = gzip.GzipFile(fileobj=raw) if magic == b"\x1f\x8b" else raw
        text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
    except OSError as exc:
        raise RegistryImportError(f"cannot read PubChem synonyms file {path}: {exc}") from exc

    try:
        with raw, text:
            for line_number, line in enumerate(text, start=1):
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) != 2:
                    raise RegistryImportError(
                        f"PubChem synonyms row {line_number} is not the documented "
                        "two-column tab-separated CID<TAB>synonym format"
                    )
                cid, synonym = (field.strip() for field in fields)
                if not cid.isdecimal():
                    raise RegistryImportError(
                        f"PubChem synonyms row {line_number} has a non-numeric CID"
                    )
                if not synonym:
                    raise RegistryImportError(
                        f"PubChem synonyms row {line_number} has an empty synonym"
                    )
                yield line_number, cid, synonym
    except (OSError, UnicodeError) as exc:
        raise RegistryImportError(f"cannot read PubChem synonyms file {path}: {exc}") from exc


def install_starter_moa(data_dir: Path | str) -> bool:
    """Install the packaged starter as local data without replacing user edits."""
    target = moa_registry_path(data_dir)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    try:
        payload = files("ontologylab").joinpath("moa-starter.json").read_text(
            encoding="utf-8"
        )
        # Validate the packaged artifact before making it authoritative locally.
        parsed = json.loads(payload)
        if not isinstance(parsed.get("metadata"), dict) or not isinstance(
            parsed.get("mappings"), list
        ):
            raise ValueError("starter has no metadata/mappings objects")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    except (OSError, ValueError) as exc:
        raise RegistryImportError(f"cannot install starter MoA table {target}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return True


def import_pubchem(source_path: Path | str, data_dir: Path | str) -> dict:
    """Build an atomic name/synonym-to-CAS cache from PubChem's synonym dump.

    PubChem distributes ``CID-Synonym-filtered.gz`` as headerless UTF-8 TSV,
    one ``CID<TAB>synonym`` pair per row. CAS numbers are themselves synonyms;
    the importer validates their check digits, associates other synonyms from
    the same CID, and rejects ambiguous surfaces rather than choosing one.
    """
    source = Path(source_path)
    if not source.is_file():
        raise RegistryImportError(
            f"PubChem synonyms file does not exist or is not a file: {source}"
        )
    source_hash = _sha256(source, source_name="PubChem synonyms file")
    target = pubchem_registry_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".sqlite.tmp")
    row_count = 0
    try:
        tmp.unlink(missing_ok=True)
        with sqlite3.connect(tmp) as cache:
            cache.executescript(
                """
                CREATE TABLE imported_synonyms (
                    cid TEXT NOT NULL,
                    surface_form TEXT NOT NULL,
                    normalized_name TEXT NOT NULL
                );
                CREATE INDEX imported_synonyms_cid_idx ON imported_synonyms(cid);
                CREATE TABLE cid_cas (cid TEXT NOT NULL, cas_number TEXT NOT NULL,
                    UNIQUE(cid, cas_number));
                CREATE TABLE surface_forms (
                    normalized_name TEXT PRIMARY KEY,
                    surface_form TEXT NOT NULL,
                    cas_number TEXT NOT NULL
                );
                CREATE INDEX surface_forms_cas_idx ON surface_forms(cas_number);
                CREATE TABLE cache_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL
                );
                """
            )
            for _line_number, cid, synonym in _pubchem_lines(source):
                row_count += 1
                normalized = _normalize_surface(synonym)
                if not normalized:
                    raise RegistryImportError(
                        f"PubChem synonym {synonym!r} normalizes to empty text"
                    )
                cache.execute(
                    "INSERT INTO imported_synonyms VALUES (?, ?, ?)",
                    (cid, synonym, normalized),
                )
                if _is_cas_number(synonym):
                    cache.execute(
                        "INSERT OR IGNORE INTO cid_cas VALUES (?, ?)", (cid, synonym)
                    )
            if row_count == 0:
                raise RegistryImportError(
                    "PubChem synonyms file contains no rows; the existing cache was not changed"
                )
            ambiguous_cid = cache.execute(
                "SELECT cid FROM cid_cas GROUP BY cid HAVING COUNT(*) > 1 LIMIT 1"
            ).fetchone()
            if ambiguous_cid is not None:
                values = [
                    row[0]
                    for row in cache.execute(
                        "SELECT cas_number FROM cid_cas WHERE cid = ? ORDER BY cas_number",
                        ambiguous_cid,
                    )
                ]
                raise RegistryImportError(
                    f"PubChem CID {ambiguous_cid[0]} has multiple valid CAS numbers: "
                    + ", ".join(values)
                )

            for normalized, surface, cas_number in cache.execute(
                "SELECT s.normalized_name, s.surface_form, c.cas_number "
                "FROM imported_synonyms s JOIN cid_cas c ON c.cid = s.cid "
                "ORDER BY s.rowid"
            ):
                existing = cache.execute(
                    "SELECT cas_number FROM surface_forms WHERE normalized_name = ?",
                    (normalized,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != cas_number:
                        raise RegistryImportError(
                            f"PubChem surface form {surface!r} maps to both "
                            f"{existing[0]!r} and {cas_number!r}; resolve the source "
                            "conflict rather than silently choosing a CAS number"
                        )
                    continue
                cache.execute(
                    "INSERT INTO surface_forms VALUES (?, ?, ?)",
                    (normalized, surface, cas_number),
                )

            compounds = int(
                cache.execute("SELECT COUNT(DISTINCT cid) FROM imported_synonyms").fetchone()[0]
            )
            compounds_with_cas = int(
                cache.execute("SELECT COUNT(*) FROM cid_cas").fetchone()[0]
            )
            if compounds_with_cas == 0:
                raise RegistryImportError(
                    "PubChem synonyms file contains no valid CAS registry-number synonyms"
                )
            surface_count = int(
                cache.execute("SELECT COUNT(*) FROM surface_forms").fetchone()[0]
            )
            cache.executescript(
                "DROP TABLE imported_synonyms; DROP TABLE cid_cas;"
            )
            record_counts = {
                "rows": row_count,
                "compounds": compounds,
                "compounds_with_cas": compounds_with_cas,
                "surface_forms": surface_count,
            }
            metadata = {
                "registry": "pubchem",
                "source_description": f"PubChem synonyms dump: {source.name}",
                "source_format": "PubChem CID-Synonym-filtered TSV",
                "source_url": "https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/",
                "license": "PubChem data is public domain",
                "import_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "record_counts": record_counts,
                "source_file_sha256": source_hash,
            }
            cache.execute(
                "INSERT INTO cache_metadata VALUES (1, ?)",
                (json.dumps(metadata, sort_keys=True),),
            )
        tmp.replace(target)
    except RegistryImportError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise RegistryImportError(
            f"cannot build PubChem CAS registry cache {target}: {exc}"
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)

    moa_seeded = install_starter_moa(data_dir)
    return {
        "record_counts": record_counts,
        "metadata": metadata,
        "moa_seeded": moa_seeded,
    }


class CASRegistryCache:
    """Read-only PubChem-derived CAS cache with explicit absence status."""

    def __init__(self, data_dir: Path | str):
        self.path = pubchem_registry_path(data_dir)
        self._absence_reported = False

    def resolve(self, name: str) -> str | None:
        if not self.path.is_file():
            return None
        try:
            with sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True
            ) as db:
                row = db.execute(
                    "SELECT cas_number FROM surface_forms WHERE normalized_name = ?",
                    (_normalize_surface(name),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(
                f"cannot read PubChem CAS registry cache {self.path}: {exc}"
            ) from exc
        return str(row[0]) if row else None

    def resolve_with_status(self, name: str) -> tuple[str | None, str]:
        if not self.path.is_file():
            return None, "cache_absent"
        cas_number = self.resolve(name)
        return (
            (cas_number, "resolved")
            if cas_number is not None
            else (None, "unresolved")
        )

    def metadata(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            with sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True
            ) as db:
                row = db.execute(
                    "SELECT payload FROM cache_metadata WHERE singleton = 1"
                ).fetchone()
            return json.loads(row[0]) if row else {}
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"cannot read PubChem CAS registry metadata {self.path}: {exc}"
            ) from exc

    def provenance_warning(self) -> str | None:
        if self.path.is_file() or self._absence_reported:
            return None
        self._absence_reported = True
        return "PubChem CAS cache absent"


class MoARegistryCache:
    """Local CAS-keyed mode-of-action classifications."""

    def __init__(self, data_dir: Path | str):
        self.path = moa_registry_path(data_dir)

    def _load(self) -> dict[str, tuple[str, str]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            mappings = payload["mappings"]
            if not isinstance(payload["metadata"], dict) or not isinstance(mappings, list):
                raise ValueError("metadata and mappings must be objects")
            resolved: dict[str, tuple[str, str]] = {}
            for index, item in enumerate(mappings):
                if not isinstance(item, dict):
                    raise ValueError(f"mapping {index} is not an object")
                cas_number = str(item["cas_number"]).strip()
                scheme = str(item["scheme"]).strip().upper()
                code = str(item["code"]).strip()
                if not _is_cas_number(cas_number) or scheme not in {
                    "FRAC", "IRAC", "HRAC"
                } or not code:
                    raise ValueError(f"mapping {index} has invalid CAS, scheme, or code")
                value = (scheme, code)
                if cas_number in resolved and resolved[cas_number] != value:
                    raise ValueError(f"CAS {cas_number} has conflicting MoA mappings")
                resolved[cas_number] = value
            return resolved
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"cannot read local MoA table {self.path}: {exc}") from exc

    def resolve(self, cas_number: str) -> tuple[str, str] | None:
        return self._load().get(cas_number)

    def metadata(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(payload["metadata"])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"cannot read local MoA metadata {self.path}: {exc}") from exc


class RegistryCache:
    """Read-only EPPO cache facade with explicit absent/unresolved states."""

    def __init__(self, data_dir: Path | str):
        self.path = eppo_registry_path(data_dir)
        self._absence_reported = False

    def _lookup(self, normalized_name: str) -> str | None:
        if not self.path.is_file():
            return None
        try:
            with sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True
            ) as db:
                row = db.execute(
                    "SELECT code FROM surface_forms WHERE normalized_name = ?",
                    (normalized_name,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(f"cannot read EPPO registry cache {self.path}: {exc}") from exc
        return str(row[0]) if row else None

    def resolve(self, name: str) -> str | None:
        """Return the EPPO code for an exact normalized surface form, or None."""
        return self._lookup(_normalize_surface(name))

    def resolve_with_status(self, name: str) -> tuple[str | None, str]:
        """Distinguish a lookup miss from the optional cache being switched off."""
        if not self.path.is_file():
            return None, "cache_absent"
        code = self.resolve(name)
        return (code, "resolved") if code is not None else (None, "unresolved")

    def metadata(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            with sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True
            ) as db:
                row = db.execute(
                    "SELECT payload FROM cache_metadata WHERE singleton = 1"
                ).fetchone()
            return json.loads(row[0]) if row else {}
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read EPPO registry metadata {self.path}: {exc}") from exc

    def provenance_warning(self) -> str | None:
        """Return the cache-absent warning once for this run-scoped loader.

        Absent cache means the feature is off, and a warning per entity would
        flood provenance while adding no information. The caller owns logging;
        this helper owns the once-only decision.
        """
        if self.path.is_file() or self._absence_reported:
            return None
        self._absence_reported = True
        return "EPPO cache absent"


def _http_get_text(url: str, token: str) -> str:
    """Fetch EPPO API text; the sole module-level monkeypatch boundary."""
    check_url(url)
    assert_network_allowed("EPPO registry API fetch (data.eppo.int)")
    # EPPO documents authtoken as a query parameter. Keep it separate until
    # the request boundary so provenance and caller-visible URLs stay secret-free.
    separator = "&" if "?" in url else "?"
    target = f"{url}{separator}authtoken={quote_plus(token)}"
    request = Request(target, headers={"User-Agent": "ontologylab/0.1"})
    try:
        with urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:
            payload = response.read(_MAX_INFO_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        # HTTPError.url contains the query token. Report only the fixed host
        # and status so a failed verification cannot print a credential.
        raise OSError(f"data.eppo.int returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise OSError(f"data.eppo.int request failed: {exc.reason}") from exc
    if len(payload) > _MAX_INFO_BYTES:
        raise ValueError("data.eppo.int returned an oversized API info response")
    return payload.decode(charset, errors="replace")


def verify_eppo_api(token: str) -> str:
    """Verify registered REST access; snapshot creation remains import-first.

    The discontinued bulk SQLite download has no REST replacement that can be
    treated as a coherent snapshot. This command therefore verifies the token
    without pretending that a per-taxon crawl is an equivalent cache import.
    """
    text = _http_get_text(EPPO_API_INFO_URL, token)
    if not text.strip():
        raise ValueError("data.eppo.int returned an empty API verification response")
    return text


__all__ = [
    "CASRegistryCache",
    "MoARegistryCache",
    "RegistryCache",
    "RegistryImportError",
    "import_eppo",
    "import_pubchem",
    "install_starter_moa",
    "verify_eppo_api",
]
