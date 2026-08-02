"""EPPO registry cache: offline import, lookup, provenance, and CLI tests.

The source export is user-acquired. Tests construct both accepted formats and
monkeypatch the one HTTP seam; no EPPO endpoint is contacted.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

import pytest

from ontologylab.connectors.allowlist import (
    NotAllowlisted,
    WEB_CRAWL_ALLOWED_HOSTS,
    check_url,
)
from ontologylab.main import main
from ontologylab.paths import eppo_registry_path
from ontologylab.registry import (
    RegistryCache,
    RegistryImportError,
    import_eppo,
)


def _run_cli(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return int(exc.value.code or 0)


def _csv(path: Path) -> Path:
    path.write_text(
        "code,name,type\n"
        "BOTRCI,Botrytis cinerea,scientific\n"
        "BOTRCI,Botryotinia fuckeliana,synonym\n"
        "BOTRCI,grey mould,common name\n",
        encoding="utf-8",
    )
    return path


def test_absent_cache_is_off_not_an_error_and_warns_once(tmp_path):
    cache = RegistryCache(tmp_path)

    assert cache.resolve("Botrytis cinerea") is None
    assert cache.resolve_with_status("Botrytis cinerea") == (
        None,
        "cache_absent",
    )
    assert cache.metadata() == {}
    assert cache.provenance_warning() == "EPPO cache absent"
    assert cache.provenance_warning() is None


def test_csv_import_resolves_scientific_synonym_and_common_case_insensitively(
    tmp_path,
):
    source = _csv(tmp_path / "eppo.csv")
    report = import_eppo(source, tmp_path / "data")
    cache = RegistryCache(tmp_path / "data")

    assert report["counts"] == {
        "scientific": 1,
        "synonym": 1,
        "common": 1,
    }
    assert cache.resolve("  BOTRYTIS   CINEREA ") == "BOTRCI"
    assert cache.resolve("botryotinia FUCKELIANA") == "BOTRCI"
    assert cache.resolve("Grey Mould") == "BOTRCI"
    assert cache.resolve_with_status("not in EPPO") == (None, "unresolved")
    assert cache.provenance_warning() is None


def test_import_metadata_records_source_counts_date_and_sha256(tmp_path):
    source = _csv(tmp_path / "eppo.csv")
    import_eppo(source, tmp_path / "data")

    metadata = RegistryCache(tmp_path / "data").metadata()
    assert metadata["registry"] == "eppo"
    assert metadata["source_description"] == "EPPO CSV export: eppo.csv"
    assert metadata["import_date"].endswith("Z")
    assert metadata["record_counts"] == {
        "rows": 3,
        "surface_forms": 3,
        "scientific": 1,
        "synonym": 1,
        "common": 1,
    }
    assert metadata["source_file_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()


def test_sqlite_adapter_introspects_compatible_tables(tmp_path):
    source = tmp_path / "eppo.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE preferred (eppo_code TEXT, scientific_name TEXT)")
        db.execute("INSERT INTO preferred VALUES ('BOTRCI', 'Botrytis cinerea')")
        db.execute("CREATE TABLE alternate (code TEXT, name TEXT, name_type TEXT)")
        db.executemany(
            "INSERT INTO alternate VALUES (?, ?, ?)",
            [
                ("BOTRCI", "Botryotinia fuckeliana", "synonym"),
                ("BOTRCI", "grey mould", "common"),
            ],
        )
        db.execute("CREATE TABLE unrelated (thing TEXT)")

    report = import_eppo(source, tmp_path / "data")
    cache = RegistryCache(tmp_path / "data")
    assert report["tables"] == ["alternate", "preferred"]
    assert cache.resolve("Botrytis cinerea") == "BOTRCI"
    assert cache.resolve("Botryotinia fuckeliana") == "BOTRCI"
    assert cache.resolve("grey mould") == "BOTRCI"


def test_sqlite_adapter_fails_actionably_instead_of_guessing_schema(tmp_path):
    source = tmp_path / "unknown.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE organisms (identifier TEXT, label TEXT)")

    with pytest.raises(RegistryImportError) as exc:
        import_eppo(source, tmp_path / "data")
    message = str(exc.value)
    assert "no table with code and name columns" in message
    assert "organisms(identifier, label)" in message
    assert "CSV with code,name,type" in message
    assert not eppo_registry_path(tmp_path / "data").exists()


def test_csv_adapter_fails_actionably_for_missing_columns(tmp_path):
    source = tmp_path / "unknown.csv"
    source.write_text("identifier,label\nBOTRCI,Botrytis cinerea\n", encoding="utf-8")

    with pytest.raises(RegistryImportError, match="code and name columns"):
        import_eppo(source, tmp_path / "data")


def test_failed_reimport_is_atomic_and_does_not_replace_good_cache(tmp_path):
    data = tmp_path / "data"
    import_eppo(_csv(tmp_path / "good.csv"), data)
    source = tmp_path / "conflict.csv"
    source.write_text(
        "code,name,type\nBOTRCI,grey mould,common\nOTHER,grey mould,common\n",
        encoding="utf-8",
    )

    with pytest.raises(RegistryImportError, match="maps to both"):
        import_eppo(source, data)

    assert eppo_registry_path(data).is_file()
    assert RegistryCache(data).resolve("grey mould") == "BOTRCI"


def test_cli_import_prints_counts_and_writes_selected_data_dir(tmp_path, capsys):
    source = _csv(tmp_path / "eppo.csv")
    data = tmp_path / "data"

    code = _run_cli(
        "registry",
        "import",
        "eppo",
        str(source),
        "--data-dir",
        str(data),
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "imported EPPO registry" in output
    assert "scientific=1" in output
    assert "synonym=1" in output
    assert "common=1" in output
    assert RegistryCache(data).resolve("grey mould") == "BOTRCI"


def test_cli_import_reports_bad_schema_without_traceback(tmp_path, capsys):
    source = tmp_path / "bad.csv"
    source.write_text("wrong,columns\nx,y\n", encoding="utf-8")

    code = _run_cli(
        "registry", "import", "eppo", str(source),
        "--data-dir", str(tmp_path / "data"),
    )

    assert code == 2
    assert "code and name columns" in capsys.readouterr().err


def test_cli_fetch_without_token_explains_both_supported_routes(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("EPPO_API_TOKEN", raising=False)

    code = _run_cli(
        "registry", "fetch", "eppo", "--data-dir", str(tmp_path / "data")
    )

    assert code != 0
    error = capsys.readouterr().err
    assert "EPPO_API_TOKEN" in error
    assert "registry import eppo" in error
    assert "manually downloaded" in error


def test_cli_fetch_with_token_uses_monkeypatchable_http_boundary(
    tmp_path, monkeypatch, capsys
):
    import ontologylab.registry as registry

    seen = {}

    def fake_get(url: str, token: str) -> str:
        seen.update(url=url, token=token)
        return '{"success": true}'

    monkeypatch.setenv("EPPO_API_TOKEN", "free-registration-token")
    monkeypatch.setattr(registry, "_http_get_text", fake_get)

    code = _run_cli(
        "registry", "fetch", "eppo", "--data-dir", str(tmp_path / "data")
    )

    assert code == 0
    assert seen["url"].startswith("https://data.eppo.int/")
    assert seen["token"] == "free-registration-token"
    assert "API access verified" in capsys.readouterr().out


def test_eppo_hosts_are_exact_match_allowlisted():
    for host in ("data.eppo.int", "gd.eppo.int"):
        assert host in WEB_CRAWL_ALLOWED_HOSTS
        assert check_url(f"https://{host}/") == f"https://{host}/"
    with pytest.raises(NotAllowlisted):
        check_url("https://data.eppo.int.evil.example/")
