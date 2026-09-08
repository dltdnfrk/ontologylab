"""CLI remains explicit while the bundled dashboard starts on offline mock."""

from __future__ import annotations

from ontologylab import web_assets
from ontologylab.main import build_arg_parser
from ontologylab.server.settings import engines

_METHOD_EXTRACT = (
    "method",
    "extract",
    "--workspace-id",
    "ws",
    "--document-id",
    "doc",
    "--policy-snapshot-id",
    "snap",
    "--processor",
    "proc",
    "--region",
    "kr",
    "--owner-token",
    "tok",
)


def test_cli_omitted_engine_is_none_for_critic_search_method_extract() -> None:
    # Given: the four consume-layer parsers that currently invent a default engine
    parser = build_arg_parser()

    # When: --engine is omitted
    critic = parser.parse_args(["critic"])
    search = parser.parse_args(["search", "q"])
    extract = parser.parse_args(["extract"])
    method_extract = parser.parse_args(list(_METHOD_EXTRACT))

    # Then: the parsed value is None so resolve_engine can apply DEFAULT_ENGINE
    assert critic.engine is None
    assert search.engine is None
    assert extract.engine is None
    assert method_extract.engine is None


def test_explicit_mock_flag_is_accepted() -> None:
    # Given: the same four parsers
    parser = build_arg_parser()

    # When: the operator names mock
    critic = parser.parse_args(["critic", "--engine", "mock"])
    search = parser.parse_args(["search", "q", "--engine", "mock"])
    extract = parser.parse_args(["extract", "--engine", "mock"])
    method_extract = parser.parse_args([*_METHOD_EXTRACT, "--engine", "mock"])

    # Then: mock is the parsed engine, not rewritten
    assert critic.engine == "mock"
    assert search.engine == "mock"
    assert extract.engine == "mock"
    assert method_extract.engine == "mock"


def test_settings_engines_lists_offline_mock_first() -> None:
    # Given: the settings engine catalog operators see on a fresh install
    # When: the list is built
    infos = engines()
    names = [info.name for info in infos]

    # Then: the first available choice cannot spawn a CLI or provider
    assert names[0] == "mock"
    assert infos[0].available is True
    assert names.count("mock") == 1


def test_dashboard_source_has_no_mock_fallback_tokens() -> None:
    # Given: the dashboard script operators load
    source = web_assets.read_asset_text("app.js")

    # When: the file is scanned for silent-mock machine tokens
    # Then: none remain — empty/omit must reach the server default instead
    assert "|| \"mock\"" not in source
    assert "|| 'mock'" not in source
    assert "value='mock'" not in source
