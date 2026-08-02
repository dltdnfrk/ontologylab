"""PubChem CAS cache and canonical-identity mode-of-action normalization.

Fixtures use PubChem's CID-Synonym-filtered tab-separated shape. No test
contacts PubChem or depends on a machine-global data directory.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from ontologylab.main import main
from ontologylab.models import ProposedEntity
from ontologylab.normalization import normalize_proposal
from ontologylab.paths import moa_registry_path, pubchem_registry_path
from ontologylab.registry import (
    CASRegistryCache,
    MoARegistryCache,
    RegistryImportError,
    import_pubchem,
)


def _source(path: Path, *, compressed: bool = False) -> Path:
    payload = (
        "14710509\tBoscalid\n"
        "14710509\tEndura active ingredient\n"
        "14710509\t188425-85-6\n"
        "3034285\tAzoxystrobin\n"
        "3034285\t131860-33-8\n"
        "999\tCompound without a CAS\n"
    )
    if compressed:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            handle.write(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def _entity(
    name: str,
    *,
    entity_type: str = "ActiveIngredient",
    aliases: list[str] | None = None,
    properties: dict | None = None,
) -> ProposedEntity:
    return ProposedEntity(
        id=uuid.uuid4().hex,
        entity_type=entity_type,
        name=name,
        aliases=list(aliases or []),
        properties=dict(properties or {}),
    )


def _caches(tmp_path: Path) -> tuple[CASRegistryCache, MoARegistryCache]:
    data_dir = tmp_path / "data"
    import_pubchem(_source(tmp_path / "CID-Synonym-filtered.gz", compressed=True), data_dir)
    return CASRegistryCache(data_dir), MoARegistryCache(data_dir)


def _run_cli(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return int(exc.value.code or 0)


def test_pubchem_import_resolves_names_synonyms_and_records_provenance(tmp_path) -> None:
    source = _source(tmp_path / "CID-Synonym-filtered.gz", compressed=True)
    report = import_pubchem(source, tmp_path / "data")
    cache = CASRegistryCache(tmp_path / "data")

    assert cache.resolve("  BOSCALID ") == "188425-85-6"
    assert cache.resolve("endura ACTIVE ingredient") == "188425-85-6"
    assert cache.resolve_with_status("unknown") == (None, "unresolved")
    assert report["record_counts"] == {
        "rows": 6,
        "compounds": 3,
        "compounds_with_cas": 2,
        "surface_forms": 5,
    }
    assert cache.metadata() == report["metadata"]
    assert report["metadata"]["registry"] == "pubchem"
    assert report["metadata"]["source_format"] == "PubChem CID-Synonym-filtered TSV"
    assert report["metadata"]["source_file_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert report["metadata"]["import_date"].endswith("Z")
    assert report["moa_seeded"] is True
    assert moa_registry_path(tmp_path / "data").is_file()


def test_pubchem_import_rejects_unknown_shape_without_replacing_cache(tmp_path) -> None:
    data_dir = tmp_path / "data"
    import_pubchem(_source(tmp_path / "good.tsv"), data_dir)
    bad = tmp_path / "bad.csv"
    bad.write_text("cid,synonym\n14710509,Boscalid\n", encoding="utf-8")

    with pytest.raises(RegistryImportError, match="tab-separated"):
        import_pubchem(bad, data_dir)

    assert CASRegistryCache(data_dir).resolve("Boscalid") == "188425-85-6"


def test_pubchem_import_rejects_ambiguous_surface_and_invalid_rows(tmp_path) -> None:
    conflict = tmp_path / "conflict.tsv"
    conflict.write_text(
        "1\tShared name\n1\t58-08-2\n2\tShared name\n2\t50-00-0\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryImportError, match="maps to both"):
        import_pubchem(conflict, tmp_path / "conflict-data")

    invalid = tmp_path / "invalid.tsv"
    invalid.write_text("not-a-cid\tBoscalid\n", encoding="utf-8")
    with pytest.raises(RegistryImportError, match="numeric CID"):
        import_pubchem(invalid, tmp_path / "invalid-data")


def test_alias_resolution_cache_authority_and_moa_follow_canonical_cas(tmp_path) -> None:
    cas_cache, moa_cache = _caches(tmp_path)
    proposal = _entity(
        "Product label active",
        aliases=["Endura active ingredient", "Boscalid"],
        properties={"cas_number": "WRONG", "chemical_group": "SDHI"},
    )

    assert normalize_proposal(proposal, cas_cache, moa_cache) is proposal
    assert proposal.properties == {
        "chemical_group": "SDHI",
        "cas_number": "188425-85-6",
        "cas_matched_surface": "Endura active ingredient",
        "cas_number_dropped": "WRONG",
        "moa_scheme": "FRAC",
        "moa_code": "7",
    }


def test_matching_model_cas_is_kept_without_a_dropped_marker(tmp_path) -> None:
    cas_cache, moa_cache = _caches(tmp_path)
    proposal = _entity("Boscalid", properties={"cas_number": "188425-85-6"})

    normalize_proposal(proposal, cas_cache, moa_cache)

    assert proposal.properties["cas_number"] == "188425-85-6"
    assert "cas_number_dropped" not in proposal.properties


def test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped(tmp_path) -> None:
    cas_cache, moa_cache = _caches(tmp_path)
    proposal = _entity("Imaginary active", properties={"cas_number": "50-00-0"})

    normalize_proposal(proposal, cas_cache, moa_cache)

    assert proposal.properties == {
        "cas_number_dropped": "50-00-0",
        "normalization": "no_cas_match",
    }


def test_moa_is_not_guessed_from_name_when_cas_cache_is_absent(tmp_path) -> None:
    data_dir = tmp_path / "data"
    import_pubchem(_source(tmp_path / "source.tsv"), data_dir)
    pubchem_registry_path(data_dir).unlink()
    proposal = _entity("Boscalid", properties={"cas_number": "MODEL"})
    cache = CASRegistryCache(data_dir)

    normalize_proposal(proposal, cache, MoARegistryCache(data_dir))

    assert proposal.properties == {}
    assert cache.provenance_warning() == "PubChem CAS cache absent"
    assert cache.provenance_warning() is None


def test_non_active_type_is_untouched(tmp_path) -> None:
    cas_cache, moa_cache = _caches(tmp_path)
    proposal = _entity(
        "Boscalid", entity_type="Product", properties={"cas_number": "MODEL"}
    )
    before = dict(proposal.properties)

    normalize_proposal(proposal, cas_cache, moa_cache)

    assert proposal.properties == before


def test_starter_moa_table_is_data_with_provenance_and_expected_groups(tmp_path) -> None:
    _caches(tmp_path)
    raw = json.loads(moa_registry_path(tmp_path / "data").read_text(encoding="utf-8"))
    cache = MoARegistryCache(tmp_path / "data")

    assert raw["metadata"]["source"] == "hand-seeded starter set"
    assert raw["metadata"]["seed_date"]
    assert raw["metadata"]["expandable"] is True
    assert cache.resolve("188425-85-6") == ("FRAC", "7")
    assert cache.resolve("131860-33-8") == ("FRAC", "11")
    assert cache.resolve("500008-45-7") == ("IRAC", "28")
    assert cache.resolve("1071-83-6") == ("HRAC", "9")
    assert cache.resolve("50-00-0") is None


def test_cli_import_pubchem_builds_selected_cache_and_documents_counts(
    tmp_path, capsys
) -> None:
    source = _source(tmp_path / "CID-Synonym-filtered")
    data_dir = tmp_path / "data"

    code = _run_cli(
        "registry", "import", "pubchem", str(source), "--data-dir", str(data_dir)
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "imported PubChem CAS registry" in output
    assert "2 compound(s) with CAS" in output
    assert "5 surface form(s)" in output
    assert CASRegistryCache(data_dir).resolve("Boscalid") == "188425-85-6"
