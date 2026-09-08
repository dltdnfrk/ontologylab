"""CLI facade: load the frozen policy, derive versions, gate production eligibility."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, TextIO, assert_never

from ontologylab.release_eligibility import verify_eligibility
from ontologylab.release_eligibility_types import parse_eligibility_claim
from ontologylab.release_policy_types import (
    FROZEN_FLAG,
    FROZEN_TEXT,
    LOCK_PATH,
    POLICY_PATH,
    VERSION_FILE,
    JsonValue,
    ReleasePolicy,
    ReleasePolicyCode,
    ReleasePolicyRefused,
    as_object,
    parse_qa_targets,
    path_field,
    read_json,
    refuse,
    rel_path,
    str_tuple,
    walk,
)
from ontologylab.release_snapshot import (
    diff_manifest,
    hash_tree,
    read_manifest,
    write_snapshot,
)
from ontologylab.release_task10_authority import parse_task10_policy

_FIXTURE_PATH: Final = "tests/fixtures/wave21/perf-v1.json"
_PROTOCOL_PATH: Final = "release/ingestion-performance-protocol.json"
_REQUIRED_INPUTS: Final = frozenset(
    {VERSION_FILE, LOCK_PATH, POLICY_PATH, "ontologylab", "web", "launcher"}
    | {"release/licenses", _FIXTURE_PATH, _PROTOCOL_PATH}
)
_REQUIRED_ROLES: Final = frozenset(
    {"release-authorization", "migration-approval", "security-exception", "qa-signoff"}
)
_SEMVER: Final = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True, slots=True)
class ReleaseAcceptance:
    """Machine-readable GO: version bound to the exact source snapshot."""

    version: str
    snapshot_sha256: str
    policy_sha256: str
    qa_aliases: tuple[str, ...]


def load_policy(root: Path) -> ReleasePolicy:
    """Parse the policy file; refuse drift from the frozen owner decisions."""
    raw = read_json(
        root,
        POLICY_PATH,
        ReleasePolicyCode.POLICY_MISSING,
        ReleasePolicyCode.POLICY_MALFORMED,
    )
    as_object(raw, POLICY_PATH, ReleasePolicyCode.POLICY_INVALID)
    frozen = {**FROZEN_TEXT, **FROZEN_FLAG, "approval.owners": 1}
    for dotted, expected in frozen.items():
        value = walk(raw, dotted, ReleasePolicyCode.POLICY_INVALID)
        if type(value) is not type(expected) or value != expected:
            refuse(ReleasePolicyCode.POLICY_INVALID, dotted)
    inputs = str_tuple(raw, "source_inputs")
    for item in inputs:
        rel_path(item, f"source_inputs.{item}")
    missing_input = sorted(_REQUIRED_INPUTS - set(inputs))
    if missing_input:
        refuse(ReleasePolicyCode.POLICY_INVALID, f"source_inputs.{missing_input[0]}")
    roles = str_tuple(raw, "approval.roles")
    if not _REQUIRED_ROLES <= set(roles):
        refuse(ReleasePolicyCode.POLICY_INVALID, "approval.roles")
    text = FROZEN_TEXT
    return ReleasePolicy(
        channel=text["distribution.channel"],
        public_release=False,
        delivery=text["distribution.delivery"],
        arch=text["platform.arch"],
        min_macos=text["platform.min_macos"],
        signing_identity=text["signing.identity"],
        developer_id=False,
        notarization=False,
        updates_mechanism=text["updates.mechanism"],
        updates_automatic=False,
        browser_preferred=text["browser.preferred"],
        browser_fallback=text["browser.fallback"],
        mcp_bundled=True,
        mcp_external_python=False,
        migration_scope=text["migration.scope"],
        migration_auto_discovery=False,
        approval_owners=1,
        approval_roles=roles,
        qa_targets=parse_qa_targets(raw),
        source_inputs=inputs,
        version_source_file=VERSION_FILE,
        snapshot_manifest_path=path_field(raw, "snapshot_manifest_path"),
        eligibility_receipt_path=path_field(raw, "eligibility_receipt_path"),
        fixture_manifest_path=path_field(
            raw, "performance_contract.fixture_manifest_path"
        ),
        benchmark_protocol_path=path_field(
            raw, "performance_contract.benchmark_protocol_path"
        ),
        performance_evidence_path=path_field(
            raw, "performance_contract.performance_evidence_path"
        ),
        mutation_receipt_path=path_field(
            raw, "performance_contract.mutation_receipt_path"
        ),
        task10_authority=parse_task10_policy(walk(raw, "task10_authority", ReleasePolicyCode.POLICY_INVALID)),
    )


def read_version(root: Path, policy: ReleasePolicy) -> str:
    """Read the single semantic-version source: pyproject `[project].version`."""
    rel = policy.version_source_file
    path = root / rel
    if not path.is_file():
        refuse(ReleasePolicyCode.VERSION_SOURCE_MISSING, rel)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        refuse(ReleasePolicyCode.VERSION_INVALID, rel)
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not _SEMVER.match(version):
        refuse(ReleasePolicyCode.VERSION_INVALID, f"{rel}:project.version")
    return version


def check(root: Path) -> ReleaseAcceptance:
    """Evaluate production eligibility; refuse typed at the first violation."""
    root = root.resolve()
    policy = load_policy(root)
    version = read_version(root, policy)
    if not (root / LOCK_PATH).is_file():
        refuse(ReleasePolicyCode.LOCK_MISSING, LOCK_PATH)
    claim = parse_eligibility_claim(root, policy.eligibility_receipt_path, version)
    if not claim.go:
        reason = claim.reasons[0] if claim.reasons else "release.go=false"
        refuse(ReleasePolicyCode.RELEASE_NO_GO, reason)
    if not claim.production_authorized:
        refuse(
            ReleasePolicyCode.PRODUCTION_NOT_AUTHORIZED,
            "release.production_authorized",
        )
    if claim.reasons:
        refuse(ReleasePolicyCode.RECEIPT_MALFORMED, "release.reasons")
    manifest = read_manifest(root, policy)
    if manifest.version != version:
        refuse(ReleasePolicyCode.VERSION_DRIFT, "snapshot.version")
    recomputed = hash_tree(root, policy, version)
    diff_manifest(manifest, recomputed)
    if claim.source_snapshot_sha256 != recomputed.snapshot_sha256:
        refuse(
            ReleasePolicyCode.STALE_SNAPSHOT_EVIDENCE,
            "receipt.source_snapshot_sha256",
        )
    verify_eligibility(root, policy, recomputed, claim)
    return ReleaseAcceptance(
        version,
        recomputed.snapshot_sha256,
        recomputed.policy_sha256,
        tuple(target.alias for target in policy.qa_targets),
    )


@unique
class _Command(StrEnum):
    CHECK = "check"
    SNAPSHOT = "snapshot"
    VERSION = "version"


def _emit(payload: dict[str, JsonValue], *, stream: TextIO) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), file=stream)


def main(argv: list[str] | None = None) -> int:
    """CLI: `check` eligibility, `snapshot` source inputs, `version` receipt."""
    parser = argparse.ArgumentParser(
        prog="ontologylab.release_policy",
        description="Release policy, version source, snapshot, and eligibility gate.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in _Command:
        subparsers.add_parser(command.value).add_argument(
            "--root", type=Path, default=Path(".")
        )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        match _Command(args.command):
            case _Command.CHECK:
                ok = check(root)
                _emit(
                    {
                        "schema": "ontologylab.release.acceptance.v1",
                        "status": "accepted",
                        "version": ok.version,
                        "snapshot_sha256": ok.snapshot_sha256,
                        "policy_sha256": ok.policy_sha256,
                        "qa_targets": list(ok.qa_aliases),
                    },
                    stream=sys.stdout,
                )
            case _Command.SNAPSHOT:
                policy = load_policy(root)
                manifest = write_snapshot(root, policy, read_version(root, policy))
                _emit(
                    {
                        "schema": "ontologylab.release.snapshot-written.v1",
                        "status": "written",
                        "manifest": policy.snapshot_manifest_path,
                        "snapshot_sha256": manifest.snapshot_sha256,
                        "files": len(manifest.files) + 1,
                    },
                    stream=sys.stdout,
                )
            case _Command.VERSION:
                policy = load_policy(root)
                version = read_version(root, policy)
                _emit(
                    {
                        "schema": "ontologylab.release.version-receipt.v1",
                        "source": f"{policy.version_source_file}:project.version",
                        "version": version,
                        "app": {
                            "CFBundleShortVersionString": version,
                            "CFBundleVersion": version,
                        },
                        "build": {"package_version": version},
                    },
                    stream=sys.stdout,
                )
            case unreachable:
                assert_never(unreachable)
    except ReleasePolicyRefused as refusal:
        _emit(
            {
                "schema": "ontologylab.release.refusal.v1",
                "status": "refused",
                "code": str(refusal.code),
                "member": refusal.member,
            },
            stream=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
