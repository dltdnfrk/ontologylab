"""Controlled Apple-Silicon candidate build orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Final

from ontologylab.release_policy import load_policy
from ontologylab.release_policy_types import JsonValue, ReleasePolicyRefused

from .candidate_build import (
    BuildMetadata,
    CandidateRefused,
    HostProbe,
    TreeEntry,
    seal_candidate,
    verify_event,
    verify_host,
    verify_normalized_match,
    verify_source,
)
from .candidate_execution import BuildRequest, PayloadRun, run_payload, sign_payload
from .candidate_licenses import apply_official_override, verify_license_completeness
from .candidate_stage import build_input_payload, prepare_stage, verify_overlay

_TOOL_COMMANDS: Final = (
    ("uv", "--version"),
    ("swiftc", "--version"),
    ("clang", "--version"),
    ("node", "--version"),
    ("/usr/bin/what", "/usr/bin/codesign"),
)


def _canonical_sha(payload: JsonValue | dict[str, str | list[TreeEntry]]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _run_text(args: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True, timeout=20
    )
    return (completed.stdout + completed.stderr).strip()


def _host_probe(root: Path) -> HostProbe:
    architecture = _run_text(("/usr/bin/uname", "-m"), cwd=root)
    product = _run_text(("/usr/bin/sw_vers", "-productVersion"), cwd=root)
    try:
        major = int(product.split(".", 1)[0])
    except ValueError as error:
        raise CandidateRefused("host_macos", product) from error
    return HostProbe(architecture, major, product)


def _git(
    root: Path, args: tuple[str, ...], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(root), *args),
        check=check,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _metadata(root: Path, metadata_dir: Path) -> BuildMetadata:
    staged = _git(root, ("diff", "--cached", "--quiet"), check=False)
    if staged.returncode not in {0, 1}:
        raise CandidateRefused("git_index", staged.stderr.strip())
    if staged.returncode == 1:
        raise CandidateRefused("staged_changes", "git-index")
    head = _git(root, ("rev-parse", "HEAD")).stdout.strip()
    head_ref = _git(root, ("symbolic-ref", "-q", "HEAD"), check=False).stdout.strip()
    status = _git(root, ("status", "--porcelain=v1", "--untracked-files=all")).stdout
    diff = _git(root, ("diff", "--binary", "HEAD")).stdout
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "git-status.txt").write_text(status, encoding="utf-8")
    (metadata_dir / "git-diff.patch").write_text(diff, encoding="utf-8")
    status_sha = hashlib.sha256((status + "\0" + diff).encode()).hexdigest()

    tools: dict[str, JsonValue] = {"python": sys.version}
    for command in _TOOL_COMMANDS:
        tools[command[0]] = _run_text(command, cwd=root)
    tools["host"] = asdict(_host_probe(root))
    tools["environment"] = {
        "SOURCE_DATE_EPOCH": "0",
        "PYTHONHASHSEED": "0",
        "UV_FROZEN": "1",
        "UV_OFFLINE": "1",
    }
    toolchain_path = metadata_dir / "host-toolchain.json"
    toolchain_path.write_text(
        json.dumps(tools, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    build_inputs = build_input_payload(root)
    (metadata_dir / "build-inputs.json").write_text(
        json.dumps(build_inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return BuildMetadata(
        head=head,
        head_ref=head_ref,
        status_diff_sha256=status_sha,
        toolchain_sha256=_canonical_sha(tools),
        build_inputs_sha256=_canonical_sha(build_inputs),
    )


def _venv_leaks(root: Path) -> list[str]:
    leaks: list[str] = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or path.name == "METADATA"
            and path.parent.name.endswith(".dist-info")
        ):
            continue
        if b"/.venv/" in path.read_bytes():
            leaks.append(path.relative_to(root).as_posix())
    return leaks


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        path.chmod(path.stat().st_mode | 0o700)
    root.chmod(root.stat().st_mode | 0o700)


def build(request: BuildRequest) -> Path:
    """Build once, revalidate every input, seal, compare, and atomically receive."""
    root = request.root.resolve()
    output = request.output.resolve()
    if output.exists():
        raise CandidateRefused("output_exists", str(output))
    verify_event(os.environ.get("GITHUB_EVENT_NAME"))
    policy = load_policy(root)
    verify_host(policy, _host_probe(root))
    source_before = verify_source(root)
    work = Path(tempfile.mkdtemp(prefix="ontologylab-candidate."))
    candidate = work / "candidate"
    runtime_output = work / "runtime-output"
    logs = candidate / "logs"
    metadata_dir = candidate / "metadata"
    logs.mkdir(parents=True)
    complete = False
    metadata_before = _metadata(root, metadata_dir)
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": "0",
            "UV_FROZEN": "1",
            "UV_OFFLINE": "1",
            "UV_PROJECT_ENVIRONMENT": str(work / "uv-environment"),
        }
    )
    environment.pop("VIRTUAL_ENV", None)
    layout = prepare_stage(root, work / "stage")
    verify_overlay(layout)
    overlay_sha256 = hashlib.sha256(
        layout.overlay_manifest_path.read_bytes()
    ).hexdigest()
    metadata_before = replace(metadata_before, overlay_manifest_sha256=overlay_sha256)
    shutil.copy2(
        layout.overlay_manifest_path, metadata_dir / "build-overlay-manifest.json"
    )
    shutil.copy2(layout.overlay_manifest_path, logs / "build-overlay-manifest.json")
    command = (
        "bash",
        str(layout.builder),
        "--out",
        str(runtime_output),
    )
    try:
        completed = run_payload(
            PayloadRun(
                command=command,
                cwd=layout.build_root,
                environment=environment,
                timeout_seconds=request.timeout_seconds,
            )
        )
        try:
            source_after = verify_source(root)
        except ReleasePolicyRefused as drift:
            raise CandidateRefused("build_context_changed", str(drift)) from drift
        metadata_after = _metadata(root, work / "metadata-after")
        expected_after = replace(metadata_before, overlay_manifest_sha256="")
        if source_after != source_before or metadata_after != expected_after:
            raise CandidateRefused(
                "build_context_changed", "source-status-or-toolchain"
            )
        if completed.returncode != 0:
            print(completed.stderr[-8_000:], file=sys.stderr)
            raise CandidateRefused("payload_build", str(completed.returncode))
        app = runtime_output / "OntologyLab.app"
        runtime = app / "Contents" / "Resources" / "runtime"
        apply_official_override(
            runtime,
            layout.build_root / "release" / "licenses" / "sqlite-vec" / "0.1.9",
        )
        verify_license_completeness(runtime)
        sign_payload(app)
        (logs / "build.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (logs / "build.stderr.log").write_text(completed.stderr, encoding="utf-8")
        leaked = _venv_leaks(runtime_output)
        if leaked:
            raise CandidateRefused("venv_path", leaked[0])
        destination = candidate / "payload" / "OntologyLab.app"
        destination.parent.mkdir(parents=True)
        shutil.move(app, destination)
        shutil.move(candidate, output)
        receipt = seal_candidate(output, source_before, metadata_before)
        normalized = output / "inventories" / "normalized-unsigned-manifest.json"
        if request.compare is not None:
            verify_normalized_match(normalized, request.compare)
        complete = True
        return receipt
    except subprocess.TimeoutExpired as error:
        raise CandidateRefused(
            "payload_build_timeout", str(request.timeout_seconds)
        ) from error
    finally:
        _make_writable(work)
        shutil.rmtree(work, ignore_errors=True)
        if not complete:
            _make_writable(output)
            shutil.rmtree(output, ignore_errors=True)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-macos-candidate")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--compare-normalized", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = build(
            BuildRequest(
                root=args.root,
                output=args.out,
                timeout_seconds=args.timeout_seconds,
                compare=args.compare_normalized,
            )
        )
    except (CandidateRefused, ReleasePolicyRefused) as refusal:
        print(str(refusal), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as error:
        print(
            f"candidate_build_refused member=operation detail={error}", file=sys.stderr
        )
        return 1
    print(json.dumps({"status": "complete", "receipt": str(receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
