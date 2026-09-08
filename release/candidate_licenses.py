"""Map every bundled SBOM component to exact shipped local license evidence."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Final, TypedDict

from ontologylab.release_policy_types import JsonValue

from .candidate_license_override import OfficialOverride, load_official_override
from .candidate_tree import sha256_file
from .candidate_types import CandidateRefused

_LICENSE_NAMES: Final = ("license", "copying", "notice")
_NORMALIZE: Final = re.compile(r"[-_.]+")


class Component(TypedDict):
    name: str
    version: str
    declared_license: str


def _as_object(value: JsonValue, member: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise CandidateRefused("license_inventory_malformed", member)
    return value


def _as_string(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise CandidateRefused("license_inventory_malformed", member)
    return value


def _normalize(value: str) -> str:
    return _NORMALIZE.sub("-", value.casefold())


def _components(raw: JsonValue) -> list[Component]:
    obj = _as_object(raw, "sbom")
    listed = obj.get("components")
    if not isinstance(listed, list):
        raise CandidateRefused("license_inventory_malformed", "components")
    components: list[Component] = []
    for index, item in enumerate(listed):
        component = _as_object(item, f"components[{index}]")
        components.append(
            {
                "name": _as_string(component, "name", f"components[{index}].name"),
                "version": _as_string(
                    component, "version", f"components[{index}].version"
                ),
                "declared_license": _as_string(
                    component, "license", f"components[{index}].license"
                ),
            }
        )
    return components


def _copy_dist_info_licenses(runtime: Path) -> dict[str, str]:
    license_root = runtime / "licenses"
    license_root.mkdir(parents=True, exist_ok=True)
    sources: dict[str, str] = {}
    for metadata_dir in sorted((runtime / "_internal").glob("*.dist-info")):
        metadata = metadata_dir / "METADATA"
        if not metadata.is_file():
            continue
        fields: dict[str, str] = {}
        for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                fields.setdefault(key, value)
        name = fields.get("Name", metadata_dir.name.rsplit("-", 1)[0])
        version = fields.get("Version", "unknown")
        for source in sorted(
            path for path in metadata_dir.rglob("*") if path.is_file()
        ):
            if not source.name.casefold().startswith(_LICENSE_NAMES):
                continue
            destination = license_root / f"{name}-{version}-{source.name}"
            if not destination.exists():
                shutil.copy2(source, destination)
            sources[destination.relative_to(runtime).as_posix()] = source.relative_to(
                runtime
            ).as_posix()
    return sources


def apply_official_override(runtime: Path, override_root: Path) -> None:
    """Copy one exact approved upstream override into the offline payload."""
    sbom = runtime / "sbom.json"
    if not sbom.is_file():
        raise CandidateRefused("license_inventory_missing", "sbom.json")
    raw: JsonValue = json.loads(sbom.read_text(encoding="utf-8"))
    official = load_official_override(override_root)
    matching = [item for item in _components(raw) if item["name"] == official.package]
    if len(matching) != 1 or matching[0]["version"] != official.version:
        raise CandidateRefused(
            "license_override_package",
            f"{official.package}=={official.version}",
        )
    destination = (
        runtime / "licenses" / "official-upstream" / official.package / official.version
    )
    if destination.exists():
        raise CandidateRefused("license_override_destination", str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(override_root, destination)
    load_official_override(destination)


def _payload_overrides(runtime: Path) -> dict[tuple[str, str], OfficialOverride]:
    root = runtime / "licenses" / "official-upstream"
    found: dict[tuple[str, str], OfficialOverride] = {}
    for provenance in sorted(root.glob("*/*/provenance.json")):
        official = load_official_override(provenance.parent)
        key = (official.package, official.version)
        if key in found:
            raise CandidateRefused("license_override_duplicate", "==".join(key))
        found[key] = official
    return found


def verify_license_completeness(runtime: Path) -> dict[str, JsonValue]:
    """Copy local package evidence and refuse every unmapped SBOM component."""
    sbom = runtime / "sbom.json"
    if not sbom.is_file():
        raise CandidateRefused("license_inventory_missing", "sbom.json")
    raw: JsonValue = json.loads(sbom.read_text(encoding="utf-8"))
    components = _components(raw)
    copied_sources = _copy_dist_info_licenses(runtime)
    overrides = _payload_overrides(runtime)
    license_files = sorted(
        path for path in (runtime / "licenses").glob("*") if path.is_file()
    )
    records: list[JsonValue] = []
    for component in components:
        prefix = _normalize(f"{component['name']}-{component['version']}-")
        matched = [
            path
            for path in license_files
            if _normalize(path.name).startswith(prefix)
            and path.relative_to(runtime).as_posix() in copied_sources
        ]
        official = overrides.get((component["name"], component["version"]))
        official_sources: dict[str, str] = {}
        if official is not None:
            matched.extend(official.root / item.path for item in official.licenses)
            official_sources.update(
                {
                    (official.root / item.path)
                    .relative_to(runtime)
                    .as_posix(): item.url
                    for item in official.licenses
                }
            )
        if not matched:
            raise CandidateRefused(
                "license_evidence_missing",
                f"{component['name']}=={component['version']}",
            )
        evidence: list[JsonValue] = []
        for path in matched:
            rel = path.relative_to(runtime).as_posix()
            evidence.append(
                {
                    "path": rel,
                    "source": (
                        f"official-upstream-override:{official_sources[rel]}"
                        if rel in official_sources
                        else copied_sources.get(rel, f"payload:{rel}")
                    ),
                    "sha256": sha256_file(path),
                }
            )
        declared = component["declared_license"]
        record: dict[str, JsonValue] = {
            "name": component["name"],
            "version": component["version"],
            "declared_license": declared,
            "declared_license_ambiguous": (
                declared in {"declared-in-metadata", "unknown"}
                or "," in declared
                or "License" in declared
            ),
            "resolved_license_expression": (
                official.expression if official is not None else declared
            ),
            "evidence": evidence,
            "official_upstream_override": (
                {
                    "tag": official.tag,
                    "commit": official.commit,
                    "tag_api_url": official.tag_api_url,
                    "license_expression": official.expression,
                }
                if official is not None
                else None
            ),
            "exception": None,
        }
        records.append(record)
    return {
        "schema": "ontologylab.macos-candidate.license-evidence.v1",
        "components": records,
        "component_count": len(records),
        "policy_exceptions": [],
    }
