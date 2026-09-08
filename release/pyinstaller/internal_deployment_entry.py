"""Standalone internal deployment entry with an in-bundle preflight subprocess."""

from __future__ import annotations

import importlib.metadata
import json
import stat
import sys
from pathlib import Path

from scripts.internal_deployment_cli import _parser
from scripts.internal_deployment_cli import main as deployment_main


def main(argv: list[str]) -> int:
    """Dispatch operator commands and the installer's private preflight invocation."""
    if argv[:2] == ["-m", "ontologylab.storage_compatibility"]:
        from ontologylab.storage_compatibility import main as preflight_main

        return preflight_main(argv[2:])
    if argv == ["--version"]:
        print(
            json.dumps(
                {
                    "schema": "ontologylab.internal-deployment-version.v1",
                    "version": importlib.metadata.version("ontologylab"),
                },
                sort_keys=True,
            )
        )
        return 0
    if argv and argv[0] == "uninstall":
        parsed = _parser().parse_args(argv)
        if parsed.retain_removals_under is None:
            app = Path(parsed.app or "/Applications/OntologyLab.app")
            if app.is_dir():
                for path in (app, *app.rglob("*")):
                    if path.is_dir():
                        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    return deployment_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
