"""Installed CLI surface for H1 backup-copy rehearsal."""

from __future__ import annotations

import argparse
import json
from typing import TextIO

from ontologylab.h1 import run_h1_operator
from ontologylab.h1_types import H1Receipt, H1SourceRefused


def add_h1_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "migrate-h1",
        help="Rehearse historical receipt migration on a backup-API copy.",
    )
    parser.add_argument("--source", required=True, help="Historical source SQLite path.")
    parser.add_argument("--dest", required=True, help="Caller-owned destination directory.")
    parser.set_defaults(func=cmd_migrate_h1)


def cmd_migrate_h1(args: argparse.Namespace) -> int:
    return emit_h1(args.source, args.dest)


def emit_h1(source: str, dest: str, *, out: TextIO | None = None) -> int:
    import sys

    stream = sys.stdout if out is None else out
    try:
        receipt = run_h1_operator(source, dest)
    except H1SourceRefused as refused:
        stream.write(_dumps({"code": refused.code.value, "message": str(refused)}))
        stream.write("\n")
        return 2
    stream.write(_dumps(_payload(receipt)))
    stream.write("\n")
    return 0


def _payload(receipt: H1Receipt) -> dict[str, object]:  # noqa: DICT_OK
    return {
        "complete": receipt.complete,
        "dump_sha256": receipt.dump_sha256,
        "families": {
            item.family.value: {
                "anchor_count": item.anchor_count,
                "pending": item.pending,
                "quarantined": item.quarantined,
                "verified": item.verified,
            }
            for item in receipt.inventory.families
        },
        "pending": receipt.inventory.pending,
        "quarantined": receipt.inventory.quarantined,
        "receipt_sha256": receipt.receipt_sha256,
        "verified": receipt.inventory.verified,
    }


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
