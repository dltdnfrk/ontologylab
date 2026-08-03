from pathlib import Path
import tomllib


PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _optional_dependencies(extra: str) -> list[str]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return document["project"]["optional-dependencies"][extra]


def test_mcp_extra_excludes_the_incompatible_v2_api() -> None:
    """The server imports FastMCP from the SDK's v1-only module path."""
    assert "mcp>=1.2,<2" in _optional_dependencies("mcp")
