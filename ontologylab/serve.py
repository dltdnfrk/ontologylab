"""Local serve entry point for the ontologylab web layer.

Runnable as: python -m ontologylab.serve [--host 127.0.0.1] [--port 8765]

Binds to 127.0.0.1 only. Session auth covers /api; remote binds are refused.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ontologylab.paths import default_data_dir, default_packs_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ontologylab.serve",
        description="Serve the ontologylab local web layer (FastAPI + static frontend).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1, local-only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port (default: 8765)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(default_data_dir()),
        help="Working data directory (default: ROOT/data)",
    )
    parser.add_argument(
        "--packs-dir",
        default=str(default_packs_dir()),
        help="Knowledge-pack output directory (default: ROOT/packs)",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Legacy flag. Non-loopback binds are refused even when this is "
            "passed; the server is local-only."
        ),
    )
    args = parser.parse_args()

    from ontologylab.paths import icloud_refusal

    # Same shape as the --allow-remote refusal below, for the same reason:
    # a default that quietly publishes the knowledge graph. That one puts it
    # on the network; this one puts it on Apple's servers.
    synced = icloud_refusal(
        {"--data-dir": args.data_dir, "--packs-dir": args.packs_dir}
    )
    if synced:
        parser.error(synced)

    from ontologylab.server.security import is_local_hostname

    if not is_local_hostname(args.host):
        parser.error(
            f"refusing to bind non-loopback host {args.host!r}: "
            "the server is local-only and will not expose the knowledge graph "
            "on the network. --allow-remote is ignored and no longer permits "
            "a remote bind. Keep 127.0.0.1."
        )

    import uvicorn

    from ontologylab.server.app import create_app

    # Saved settings that connectors read from the environment. Applied
    # here rather than in `create_app`: this is where a process starts,
    # and `create_app` is called by every test — putting it there made
    # each test inherit whichever SearXNG this machine has configured.
    from ontologylab.server import settings as settings_mod

    settings_mod.apply_to_environment(
        settings_mod.load_settings(Path(args.data_dir))
    )

    uvicorn.run(
        create_app(data_dir=Path(args.data_dir), packs_dir=Path(args.packs_dir)),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
