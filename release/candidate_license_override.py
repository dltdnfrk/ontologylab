"""Strict offline parser for the approved sqlite-vec upstream license override."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ontologylab.release_policy_types import JsonValue

from .candidate_tree import sha256_file
from .candidate_types import CandidateRefused

_SCHEMA: Final = "ontologylab.official-upstream-license-override.v1"
_PACKAGE: Final = "sqlite-vec"
_VERSION: Final = "0.1.9"
_EXPRESSION: Final = "MIT OR Apache-2.0"
_REPOSITORY: Final = "https://github.com/asg017/sqlite-vec"
_TAG: Final = "v0.1.9"
_TAG_API: Final = "https://api.github.com/repos/asg017/sqlite-vec/git/ref/tags/v0.1.9"
_COMMIT: Final = "e9f598abfa0c06b328d8fe5da9c3760cce74be10"
_VERSION_URL: Final = (
    f"https://raw.githubusercontent.com/asg017/sqlite-vec/{_COMMIT}/VERSION"
)
_VERSION_CONTENT: Final = "0.1.9\n"
_VERSION_SHA256: Final = (
    "e358d84552808a5c0bd6679d690c283b938ebe15c2bd843c898681d093213107"
)


@dataclass(frozen=True, slots=True)
class OverrideLicense:
    """One exact official upstream license text."""

    identifier: str
    path: str
    url: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OfficialOverride:
    """Parsed immutable official upstream package license evidence."""

    package: str
    version: str
    expression: str
    tag: str
    commit: str
    tag_api_url: str
    licenses: tuple[OverrideLicense, ...]
    root: Path


def _object(value: JsonValue, member: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise CandidateRefused("license_override_malformed", member)
    return value


def _string(obj: dict[str, JsonValue], key: str, member: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise CandidateRefused("license_override_malformed", member)
    return value


def _integer(obj: dict[str, JsonValue], key: str, member: str) -> int:
    value = obj.get(key)
    if type(value) is not int:
        raise CandidateRefused("license_override_malformed", member)
    return value


def _exact(member: str, actual: str | int | bool, expected: str | int | bool) -> None:
    if type(actual) is not type(expected) or actual != expected:
        raise CandidateRefused("license_override_unapproved", member)


def _license(item: JsonValue, root: Path) -> OverrideLicense:
    obj = _object(item, "licenses")
    identifier = _string(obj, "id", "licenses.id")
    expected = {
        "MIT": (
            "LICENSE-MIT",
            f"https://raw.githubusercontent.com/asg017/sqlite-vec/{_COMMIT}/LICENSE-MIT",
            1068,
            "6ce72bbe12d975bd5286e5ab0a064c069693300c47bccbc57bec18485f1621ea",
        ),
        "Apache-2.0": (
            "LICENSE-APACHE",
            f"https://raw.githubusercontent.com/asg017/sqlite-vec/{_COMMIT}/LICENSE-APACHE",
            10931,
            "a38070a94d4afd9cd710e3ce67bd1de78097cfe1784c1f0109ac95d3c196bfdc",
        ),
    }.get(identifier)
    if expected is None:
        raise CandidateRefused("license_override_unapproved", "licenses.id")
    path = _string(obj, "path", f"licenses.{identifier}.path")
    url = _string(obj, "url", f"licenses.{identifier}.url")
    size = _integer(obj, "bytes", f"licenses.{identifier}.bytes")
    sha256 = _string(obj, "sha256", f"licenses.{identifier}.sha256")
    for member, actual, wanted in zip(
        ("path", "url", "bytes", "sha256"),
        (path, url, size, sha256),
        expected,
        strict=True,
    ):
        _exact(f"licenses.{identifier}.{member}", actual, wanted)
    source = root / path
    if source.is_symlink() or not source.is_file():
        raise CandidateRefused("license_override_missing", path)
    _exact(f"licenses.{identifier}.actual_bytes", source.stat().st_size, size)
    _exact(f"licenses.{identifier}.actual_sha256", sha256_file(source), sha256)
    return OverrideLicense(identifier, path, url, size, sha256)


def load_official_override(root: Path) -> OfficialOverride:
    """Parse and verify every approved provenance field and local source byte."""
    provenance = root / "provenance.json"
    if provenance.is_symlink() or not provenance.is_file():
        raise CandidateRefused("license_override_missing", "provenance.json")
    raw: JsonValue = json.loads(provenance.read_text(encoding="utf-8"))
    obj = _object(raw, "provenance")
    expected_fields = (
        ("schema", _SCHEMA),
        ("package", _PACKAGE),
        ("package_version", _VERSION),
        ("license_expression", _EXPRESSION),
        ("repository", _REPOSITORY),
        ("tag", _TAG),
        ("tag_api_url", _TAG_API),
        ("commit", _COMMIT),
    )
    for member, wanted in expected_fields:
        _exact(member, _string(obj, member, member), wanted)
    network_at_build = obj.get("network_at_build")
    if type(network_at_build) is not bool or network_at_build:
        raise CandidateRefused("license_override_unapproved", "network_at_build")
    version = _object(obj.get("version_file"), "version_file")
    content = _string(version, "content", "version_file.content")
    for member, actual, wanted in (
        ("url", _string(version, "url", "version_file.url"), _VERSION_URL),
        ("content", content, _VERSION_CONTENT),
        ("bytes", _integer(version, "bytes", "version_file.bytes"), 6),
        ("sha256", _string(version, "sha256", "version_file.sha256"), _VERSION_SHA256),
        ("content_bytes", len(content.encode()), 6),
        (
            "content_sha256",
            hashlib.sha256(content.encode()).hexdigest(),
            _VERSION_SHA256,
        ),
    ):
        _exact(f"version_file.{member}", actual, wanted)
    listed = obj.get("licenses")
    if not isinstance(listed, list) or len(listed) != 2:
        raise CandidateRefused("license_override_unapproved", "licenses")
    licenses = tuple(
        sorted(
            (_license(item, root) for item in listed), key=lambda item: item.identifier
        )
    )
    if tuple(item.identifier for item in licenses) != ("Apache-2.0", "MIT"):
        raise CandidateRefused("license_override_unapproved", "licenses.ids")
    return OfficialOverride(
        _PACKAGE, _VERSION, _EXPRESSION, _TAG, _COMMIT, _TAG_API, licenses, root
    )
