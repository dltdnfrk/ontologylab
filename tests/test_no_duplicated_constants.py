"""Constants that exist must actually be the only spelling.

A named constant that some call sites ignore is worse than no constant: it
reads as a single source of truth, so changing it looks safe, and the sites
that re-typed the value drift away in silence. Nothing fails — the system
just becomes internally inconsistent.

Each test here corresponds to a place that had already drifted.
"""

from __future__ import annotations

import re
from pathlib import Path

from ontologylab.connectors import resources
from ontologylab.connectors.paper_api import DEFAULT_PAPER_SOURCE
from ontologylab.paths import DEFAULT_ENGINE
from ontologylab.server.app import WEB_DIR

REPO = Path(__file__).resolve().parent.parent
APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
MAIN_PY = (REPO / "ontologylab" / "main.py").read_text(encoding="utf-8")
RESOURCES_PY = Path(resources.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# One organism, three spellings, one place
# --------------------------------------------------------------------------


def test_every_gene_lookup_narrows_to_the_same_organism() -> None:
    """The drift that mattered most, because it produces wrong matches.

    Each resource names the organism differently — a taxon id, `human`,
    `homo_sapiens`. They used to be a constant plus two inline literals, so
    moving the constant moved UniProt alone: it would have answered about
    mouse Trp53 while MyGene and Ensembl answered about human TP53, and all
    three would land on one node as agreeing evidence.
    """
    urls = [
        resources.build_uniprot_url("TP53"),
        resources.build_mygene_url("TP53"),
        resources.build_ensembl_url("TP53"),
    ]
    spellings = [
        resources.ORGANISM["taxon_id"],
        resources.ORGANISM["mygene_species"],
        resources.ORGANISM["ensembl_species"],
    ]

    for url, spelling in zip(urls, spellings, strict=True):
        assert spelling in url


def test_no_organism_spelling_is_written_inline() -> None:
    """Grep-level, because a future resource is the likely re-offender.

    The values are only checked outside the ORGANISM block: inside it they
    are the definition.
    """
    body = RESOURCES_PY.split("ORGANISM = {", 1)[1].split("}", 1)[1]

    # Matched as they appear in a URL, not as quoted Python literals: the
    # spellings live inside f-strings, so `"human"` never occurs while
    # `&species=human&` does. An earlier version of this test looked for the
    # quoted form and let the MyGene regression through.
    for literal in ("9606", "species=human", "homo_sapiens", "mus_musculus"):
        assert literal not in body, (
            f"{literal!r} is written inline; it belongs in ORGANISM"
        )


# --------------------------------------------------------------------------
# Defaults the server owns
# --------------------------------------------------------------------------


def test_the_cli_default_source_comes_from_the_constant() -> None:
    """`--paper-source` had "arxiv" typed twice — value and help text —
    while `DEFAULT_PAPER_SOURCE` was already used elsewhere in the file."""
    assert 'default="arxiv"' not in MAIN_PY
    assert "default=DEFAULT_PAPER_SOURCE" in MAIN_PY
    assert "default: {DEFAULT_PAPER_SOURCE}" in MAIN_PY


def test_the_cli_help_reports_the_real_default(capsys) -> None:
    """The help text is what a user believes. Deriving the value but hard
    coding the sentence would leave the lie in place."""
    import argparse

    from ontologylab.main import build_arg_parser

    parser = build_arg_parser()
    collect = next(
        action.choices["collect"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    help_text = next(
        a.help for a in collect._actions if a.dest == "paper_source"
    )

    assert DEFAULT_PAPER_SOURCE in help_text


def test_the_browser_does_not_re_type_the_engine_budgets() -> None:
    """The subtlest of the four.

    `max_engine_calls` and `time_budget` have schema defaults from
    `paths.DEFAULT_*`, but the browser sent explicit values, so those
    defaults never applied to a browser-started run. A comment said "change
    there first, then here" — which documents the coupling without
    preventing the drift, and nothing fails when someone forgets.
    """
    assert "time_budget: 7200" not in APP_JS
    assert "max_engine_calls: 500" not in APP_JS
    # And the fields are genuinely omitted, not renamed.
    assert not re.search(r"time_budget:\s*\d", APP_JS)


def test_the_settings_placeholder_shows_the_real_default() -> None:
    """A placeholder is a claim about what happens if you leave it blank.
    It said `mock` while the default was `claude`."""
    match = re.search(
        r'<input[^>]*id="settings-default-engine"[^>]*>', INDEX_HTML
    )
    assert match, "the default-engine field is gone"
    assert f'placeholder="{DEFAULT_ENGINE}"' in match.group(0)


# --------------------------------------------------------------------------
# What must stay hard coded
# --------------------------------------------------------------------------


def test_endpoint_constants_stay_literal() -> None:
    """Not every literal is a defect.

    The endpoint URLs must be constants precisely because the host
    allowlist is derived from them — a URL assembled at runtime could not
    be exact-matched ahead of the request, which is the property the whole
    allowlist rests on.
    """
    for url in (
        resources.UNIPROT_API_URL,
        resources.MYGENE_API_URL,
        resources.ENSEMBL_API_URL,
        resources.CHEMBL_API_URL,
    ):
        assert url.startswith("https://")

    hosts = {u.split("/")[2] for u in (
        resources.UNIPROT_API_URL,
        resources.MYGENE_API_URL,
        resources.ENSEMBL_API_URL,
        resources.CHEMBL_API_URL,
    )}
    assert hosts == set(resources.RESOURCE_HOSTS), (
        "RESOURCE_HOSTS must stay derived from the endpoints, not re-typed"
    )
