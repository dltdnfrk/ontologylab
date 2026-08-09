"""Deterministic extraction-to-ontology proposal artifacts.

Extraction rows are evidence, not ontology changes.  This module turns them
into typed, content-addressed proposals and applies one only after a caller
supplies explicit human verification metadata.  Identity matching is local
label/alias matching only: SKOS-like xref predicates, including ``close``, are
never instructions to merge local term identities.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, replace
import hashlib
import json
import math
import time
import unicodedata
from typing import Any

from ontologylab.kgstore import (
    KGStore,
    OntologyTermValidationError,
    UnknownItem,
    XrefValidationError,
)
from ontologylab.models import (
    HumanVerification,
    OntologyCandidate,
    OntologyProposal,
    OntologySourceVerification,
    OntologyXrefCandidate,
    SourceSpan,
)
from ontologylab.ontology_schema import (
    TERM_LIFECYCLES,
    XREF_LICENSE_GATES,
    XREF_MAPPING_PREDICATES,
)

_SOURCE_KINDS = ("entity", "relation")
_SOURCE_STATUSES = ("proposed", "verified")
_PROPOSAL_ACTIONS = ("create", "augment")

_CANDIDATE_FIELDS = {
    "id",
    "source_kind",
    "source_id",
    "source_status",
    "source_verified_by",
    "source_verified_at",
    "schema_version_id",
    "type_name",
    "preferred_label",
    "language",
    "definition",
    "aliases",
    "qualifiers",
    "lifecycle",
    "replacement_term_id",
    "change_reason",
    "xrefs",
    "source_doc_id",
    "source_span",
}
_XREF_FIELDS = {
    "authority",
    "external_id",
    "mapping_predicate",
    "source_uri",
    "source_version",
    "valid_from",
    "valid_to",
    "retrieved_at",
    "confidence",
    "license_gate",
    "lifecycle",
    "replacement_xref_id",
    "change_reason",
}
_PROPOSAL_FIELDS = {
    "id",
    "action",
    "target_term_id",
    "schema_version_id",
    "source_kind",
    "type_name",
    "preferred_label",
    "language",
    "definition",
    "aliases",
    "qualifiers",
    "lifecycle",
    "replacement_term_id",
    "change_reason",
    "xrefs",
    "source_candidate_ids",
    "source_verifications",
    "requires_human_verification",
    "verification",
}


class OntologyProposalError(ValueError):
    """A caller-correctable proposal error with a stable HTTP representation."""

    def __init__(
        self,
        error_kind: str,
        field: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.field = field
        self.message = message
        self.status_code = status_code


def _error(
    error_kind: str,
    field: str,
    message: str,
    *,
    status_code: int = 400,
) -> OntologyProposalError:
    return OntologyProposalError(
        error_kind, field, message, status_code=status_code
    )


def _mapping(value: Any, field: str, kind: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(kind, field, "must be an object")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: set[str], field: str, kind: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _error(kind, field, f"unknown field(s): {unknown}")


def _text(value: Any, field: str, kind: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(kind, field, "must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, field: str, kind: str) -> str | None:
    if value is None:
        return None
    return _text(value, field, kind)


def _integer(value: Any, field: str, kind: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(kind, field, "must be a positive integer")
    return value


def _number(value: Any, field: str, kind: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(kind, field, "must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _error(kind, field, "must be a finite number")
    return parsed


def _json_value(value: Any, field: str, kind: str) -> Any:
    """Return a detached JSON value in canonical key order."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _error(kind, field, "must contain only finite JSON values") from exc
    return json.loads(encoded)


def _text_tuple(value: Any, field: str, kind: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _error(kind, field, "must be an array of strings")
    parsed = [_text(item, f"{field}[{index}]", kind) for index, item in enumerate(value)]
    by_key: dict[str, str] = {}
    for item in parsed:
        key = _normalized_text(item)
        previous = by_key.get(key)
        if previous is None or (item.casefold(), item) < (previous.casefold(), previous):
            by_key[key] = item
    return tuple(sorted(by_key.values(), key=lambda item: (_normalized_text(item), item)))


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _id_tuple(value: Any, field: str, kind: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _error(kind, field, "must be an array of strings")
    parsed = [_text(item, f"{field}[{index}]", kind) for index, item in enumerate(value)]
    if len(set(parsed)) != len(parsed):
        raise _error(kind, field, "must not contain duplicate ids")
    return tuple(sorted(parsed))


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_term_lifecycle(
    lifecycle_value: Any,
    replacement_value: Any,
    reason_value: Any,
    *,
    kind: str,
) -> tuple[str, str | None, str | None]:
    lifecycle = _text(lifecycle_value, "lifecycle", kind)
    if lifecycle not in TERM_LIFECYCLES:
        raise _error(kind, "lifecycle", f"unsupported value {lifecycle!r}")
    replacement_id = _optional_text(
        replacement_value, "replacement_term_id", kind
    )
    reason = _optional_text(reason_value, "change_reason", kind)
    if lifecycle == "active":
        if replacement_id is not None:
            raise _error(
                kind,
                "replacement_term_id",
                "an active term cannot have a replacement",
            )
        if reason is not None:
            raise _error(kind, "change_reason", "an active term has no retirement reason")
    else:
        if reason is None:
            raise _error(kind, "change_reason", "a retired term needs a reason")
        if lifecycle == "replaced" and replacement_id is None:
            raise _error(
                kind,
                "replacement_term_id",
                "a replaced term needs a replacement",
            )
    return lifecycle, replacement_id, reason


def _xref_from_dict(
    raw: Any, *, field: str, kind: str
) -> OntologyXrefCandidate:
    value = _mapping(raw, field, kind)
    _known_fields(value, _XREF_FIELDS, field, kind)
    authority = _text(value.get("authority"), f"{field}.authority", kind)
    external_id = _text(value.get("external_id"), f"{field}.external_id", kind)
    predicate = _text(
        value.get("mapping_predicate"), f"{field}.mapping_predicate", kind
    )
    if predicate not in XREF_MAPPING_PREDICATES:
        raise _error(
            kind,
            f"{field}.mapping_predicate",
            f"unsupported value {predicate!r}",
        )
    source_uri = _text(value.get("source_uri"), f"{field}.source_uri", kind)
    source_version = _optional_text(
        value.get("source_version"), f"{field}.source_version", kind
    )
    valid_from = (
        _number(value.get("valid_from"), f"{field}.valid_from", kind)
        if value.get("valid_from") is not None
        else None
    )
    valid_to = (
        _number(value.get("valid_to"), f"{field}.valid_to", kind)
        if value.get("valid_to") is not None
        else None
    )
    if source_version is None and valid_from is None and valid_to is None:
        raise _error(
            kind,
            f"{field}.source_version_or_valid_time",
            "source_version or a valid-time bound is required",
        )
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise _error(kind, f"{field}.valid_to", "must not precede valid_from")
    retrieved_at = _number(
        value.get("retrieved_at"), f"{field}.retrieved_at", kind
    )
    confidence = _number(value.get("confidence"), f"{field}.confidence", kind)
    if not 0.0 <= confidence <= 1.0:
        raise _error(kind, f"{field}.confidence", "must be between 0 and 1")
    license_gate = _text(
        value.get("license_gate"), f"{field}.license_gate", kind
    )
    if license_gate not in XREF_LICENSE_GATES:
        raise _error(
            kind,
            f"{field}.license_gate",
            f"unsupported value {license_gate!r}",
        )
    lifecycle = _text(value.get("lifecycle", "active"), f"{field}.lifecycle", kind)
    if lifecycle not in TERM_LIFECYCLES:
        raise _error(
            kind, f"{field}.lifecycle", f"unsupported value {lifecycle!r}"
        )
    replacement = _optional_text(
        value.get("replacement_xref_id"), f"{field}.replacement_xref_id", kind
    )
    reason = _optional_text(
        value.get("change_reason"), f"{field}.change_reason", kind
    )
    if lifecycle == "active":
        if replacement is not None:
            raise _error(
                kind,
                f"{field}.replacement_xref_id",
                "an active xref cannot have a replacement",
            )
        if reason is not None:
            raise _error(
                kind,
                f"{field}.change_reason",
                "an active xref has no retirement reason",
            )
    else:
        if reason is None:
            raise _error(kind, f"{field}.change_reason", "a retired xref needs a reason")
        if lifecycle == "replaced" and replacement is None:
            raise _error(
                kind,
                f"{field}.replacement_xref_id",
                "a replaced xref needs a replacement",
            )
    return OntologyXrefCandidate(
        authority=authority,
        external_id=external_id,
        mapping_predicate=predicate,
        source_uri=source_uri,
        source_version=source_version,
        valid_from=valid_from,
        valid_to=valid_to,
        retrieved_at=retrieved_at,
        confidence=confidence,
        license_gate=license_gate,
        lifecycle=lifecycle,
        replacement_xref_id=replacement,
        change_reason=reason,
    )


def candidate_from_dict(raw: Any) -> OntologyCandidate:
    """Validate one JSON-shaped candidate into the public typed contract."""
    kind = "ontology_candidate_invalid"
    value = _mapping(raw, "candidate", kind)
    _known_fields(value, _CANDIDATE_FIELDS, "candidate", kind)
    candidate_id = _text(value.get("id"), "id", kind)
    source_kind = _text(value.get("source_kind"), "source_kind", kind)
    if source_kind not in _SOURCE_KINDS:
        raise _error(kind, "source_kind", f"unsupported value {source_kind!r}")
    source_id = _text(value.get("source_id"), "source_id", kind)
    source_status = _text(value.get("source_status"), "source_status", kind)
    if source_status not in _SOURCE_STATUSES:
        raise _error(kind, "source_status", f"unsupported value {source_status!r}")
    verified_by = _optional_text(
        value.get("source_verified_by"), "source_verified_by", kind
    )
    verified_at = (
        _number(value.get("source_verified_at"), "source_verified_at", kind)
        if value.get("source_verified_at") is not None
        else None
    )
    if source_status == "verified":
        if verified_by is None:
            raise _error(
                kind,
                "source_verified_by",
                "a verified source must name its reviewer",
            )
        if verified_at is None:
            raise _error(
                kind,
                "source_verified_at",
                "a verified source must carry its review time",
            )
    elif verified_by is not None or verified_at is not None:
        raise _error(
            kind,
            "source_status",
            "a proposed source cannot carry verification metadata",
        )
    schema_version_id = _integer(
        value.get("schema_version_id"), "schema_version_id", kind
    )
    aliases = _text_tuple(value.get("aliases", []), "aliases", kind)
    qualifiers = _json_value(value.get("qualifiers", {}), "qualifiers", kind)
    if not isinstance(qualifiers, dict):
        raise _error(kind, "qualifiers", "must be an object")
    lifecycle, replacement_id, reason = _validate_term_lifecycle(
        value.get("lifecycle", "active"),
        value.get("replacement_term_id"),
        value.get("change_reason"),
        kind=kind,
    )
    raw_xrefs = value.get("xrefs", [])
    if not isinstance(raw_xrefs, (list, tuple)):
        raise _error(kind, "xrefs", "must be an array")
    xrefs_by_value: dict[str, OntologyXrefCandidate] = {}
    for index, item in enumerate(raw_xrefs):
        parsed = _xref_from_dict(item, field=f"xrefs[{index}]", kind=kind)
        xrefs_by_value[_canonical(asdict(parsed))] = parsed
    source_doc_id = _optional_text(
        value.get("source_doc_id"), "source_doc_id", kind
    )
    span_value = value.get("source_span")
    span = None
    if span_value is not None:
        span_object = _mapping(span_value, "source_span", kind)
        _known_fields(span_object, {"start", "end"}, "source_span", kind)
        start = span_object.get("start")
        end = span_object.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise _error(
                kind,
                "source_span",
                "must have integer offsets with 0 <= start < end",
            )
        span = SourceSpan(start=start, end=end)
    return OntologyCandidate(
        id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        source_status=source_status,
        source_verified_by=verified_by,
        source_verified_at=verified_at,
        schema_version_id=schema_version_id,
        type_name=_text(value.get("type_name"), "type_name", kind),
        preferred_label=_text(
            value.get("preferred_label"), "preferred_label", kind
        ),
        language=_text(value.get("language"), "language", kind),
        definition=_text(value.get("definition"), "definition", kind),
        aliases=aliases,
        qualifiers=qualifiers,
        lifecycle=lifecycle,
        replacement_term_id=replacement_id,
        change_reason=reason,
        xrefs=tuple(xrefs_by_value[key] for key in sorted(xrefs_by_value)),
        source_doc_id=source_doc_id,
        source_span=span,
    )


def _proposal_options(properties: dict[str, Any]) -> dict[str, Any]:
    raw = properties.get("ontology_proposal", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _error(
            "ontology_candidate_invalid",
            "properties.ontology_proposal",
            "must be an object",
        )
    return raw


def _candidate_body_from_row(
    row: Mapping[str, Any],
    *,
    source_kind: str,
    type_name: str,
    preferred_label: str,
    definition: str,
    aliases: list[str],
    qualifiers: dict[str, Any],
) -> dict[str, Any]:
    properties = json.loads(row["properties_json"] or "{}")
    options = _proposal_options(properties)
    option_aliases = options.get("aliases", [])
    if not isinstance(option_aliases, list):
        raise _error(
            "ontology_candidate_invalid",
            "properties.ontology_proposal.aliases",
            "must be an array",
        )
    span = json.loads(row["source_span"]) if row["source_span"] else None
    return {
        "id": row["id"],
        "source_kind": source_kind,
        "source_id": row["id"],
        "source_status": row["status"],
        "source_verified_by": row["verified_by"],
        "source_verified_at": row["verified_ts"],
        "schema_version_id": row["schema_version_id"],
        "type_name": type_name,
        "preferred_label": options.get("preferred_label", preferred_label),
        "language": options.get("language", "en"),
        "definition": options.get(
            "definition", properties.get("definition", definition)
        ),
        "aliases": [*aliases, *option_aliases],
        "qualifiers": qualifiers,
        "lifecycle": options.get("lifecycle", "active"),
        "replacement_term_id": options.get("replacement_term_id"),
        "change_reason": options.get("change_reason"),
        "xrefs": options.get("xrefs", []),
        "source_doc_id": row["source_doc_id"],
        "source_span": span,
    }


def candidates_from_extractions(
    store: KGStore, source_ids: Iterable[str]
) -> list[OntologyCandidate]:
    """Hydrate real node/edge rows into candidates in stable source-id order."""
    kind = "ontology_candidate_invalid"
    parsed_ids = sorted({_text(item, "source_ids", kind) for item in source_ids})
    candidates: list[OntologyCandidate] = []
    for source_id in parsed_ids:
        node = store.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (source_id,)
        ).fetchone()
        if node is not None:
            if node["status"] not in _SOURCE_STATUSES:
                raise _error(
                    "ontology_candidate_conflict",
                    "source_status",
                    f"source {source_id!r} is {node['status']!r}",
                    status_code=409,
                )
            aliases = json.loads(node["aliases_json"] or "[]")
            body = _candidate_body_from_row(
                node,
                source_kind="entity",
                type_name=node["entity_type"],
                preferred_label=node["name"],
                definition=(
                    f"{node['name']} is an extracted {node['entity_type']} candidate."
                ),
                aliases=aliases,
                qualifiers={},
            )
            candidates.append(candidate_from_dict(body))
            continue

        edge = store.conn.execute(
            "SELECT e.*, s.name AS src_name, d.name AS dst_name, "
            "rt.description AS type_description FROM edges e "
            "JOIN nodes s ON s.id = e.src_node_id "
            "JOIN nodes d ON d.id = e.dst_node_id "
            "LEFT JOIN relation_type rt ON rt.schema_version_id = e.schema_version_id "
            "AND rt.name = e.relation_type WHERE e.id = ?",
            (source_id,),
        ).fetchone()
        if edge is None:
            raise _error(
                "unknown_extraction_artifact",
                "source_ids",
                f"unknown extraction artifact {source_id!r}",
                status_code=404,
            )
        if edge["status"] not in _SOURCE_STATUSES:
            raise _error(
                "ontology_candidate_conflict",
                "source_status",
                f"source {source_id!r} is {edge['status']!r}",
                status_code=409,
            )
        qualifiers = (
            json.loads(edge["qualifiers_json"] or "{}")
            if "qualifiers_json" in edge.keys()
            else {}
        )
        body = _candidate_body_from_row(
            edge,
            source_kind="relation",
            type_name=edge["relation_type"],
            preferred_label=edge["relation_type"],
            definition=(
                edge["type_description"]
                or f"{edge['src_name']} {edge['relation_type']} {edge['dst_name']}."
            ),
            aliases=[],
            qualifiers=qualifiers,
        )
        candidates.append(candidate_from_dict(body))
    return candidates


def candidates_from_preview_request(
    store: KGStore, raw: Any
) -> list[OntologyCandidate]:
    """Parse the two API request forms: real source ids or typed artifacts."""
    kind = "ontology_candidate_invalid"
    value = _mapping(raw, "body", kind)
    _known_fields(value, {"source_ids", "candidates"}, "body", kind)
    has_sources = "source_ids" in value
    has_candidates = "candidates" in value
    if has_sources == has_candidates:
        raise _error(
            kind,
            "body",
            "pass exactly one of source_ids or candidates",
        )
    if has_sources:
        source_ids = value["source_ids"]
        if not isinstance(source_ids, (list, tuple)) or not source_ids:
            raise _error(kind, "source_ids", "must be a non-empty array")
        if len(source_ids) > 100:
            raise _error(kind, "source_ids", "must contain at most 100 ids")
        return candidates_from_extractions(store, source_ids)
    raw_candidates = value["candidates"]
    if not isinstance(raw_candidates, (list, tuple)) or not raw_candidates:
        raise _error(kind, "candidates", "must be a non-empty array")
    if len(raw_candidates) > 100:
        raise _error(kind, "candidates", "must contain at most 100 artifacts")
    candidates = [candidate_from_dict(item) for item in raw_candidates]
    return sorted(candidates, key=lambda item: (_canonical(asdict(item)), item.id))


def _candidate_group_key(candidate: OntologyCandidate) -> tuple[Any, ...]:
    return (
        candidate.schema_version_id,
        candidate.source_kind,
        _normalized_text(candidate.type_name),
        _normalized_text(candidate.preferred_label),
        _normalized_text(candidate.language),
        _normalized_text(candidate.definition),
        candidate.lifecycle,
        candidate.replacement_term_id,
        _normalized_text(candidate.change_reason or ""),
        _canonical(candidate.qualifiers),
    )


def _matching_term_ids(
    store: KGStore,
    *,
    schema_version_id: int,
    preferred_label: str,
    language: str,
) -> list[str]:
    """Match local labels only; xref rows intentionally never enter this query."""
    wanted_label = _normalized_text(preferred_label)
    wanted_language = _normalized_text(language)
    matched: set[str] = set()
    terms = store.conn.execute(
        "SELECT id, preferred_label, language FROM ontology_term "
        "WHERE schema_version_id = ?",
        (schema_version_id,),
    ).fetchall()
    for term in terms:
        if (
            _normalized_text(term["preferred_label"]) == wanted_label
            and _normalized_text(term["language"]) == wanted_language
        ):
            matched.add(term["id"])
    aliases = store.conn.execute(
        "SELECT a.term_id, a.label, a.language FROM term_alias a "
        "JOIN ontology_term t ON t.id = a.term_id "
        "WHERE t.schema_version_id = ?",
        (schema_version_id,),
    ).fetchall()
    for alias in aliases:
        if (
            _normalized_text(alias["label"]) == wanted_label
            and _normalized_text(alias["language"]) == wanted_language
        ):
            matched.add(alias["term_id"])
    return sorted(matched)


def _proposal_content(proposal: OntologyProposal) -> dict[str, Any]:
    content = asdict(proposal)
    content.pop("id", None)
    content.pop("requires_human_verification", None)
    content.pop("verification", None)
    return content


def _proposal_id(proposal: OntologyProposal) -> str:
    digest = hashlib.sha256(_canonical(_proposal_content(proposal)).encode()).hexdigest()
    return f"ontology-proposal:{digest}"


def _dedup_aliases(values: Iterable[str], preferred_label: str) -> tuple[str, ...]:
    preferred_key = _normalized_text(preferred_label)
    by_key: dict[str, str] = {}
    for value in values:
        key = _normalized_text(value)
        if key == preferred_key:
            continue
        previous = by_key.get(key)
        if previous is None or (value.casefold(), value) < (
            previous.casefold(),
            previous,
        ):
            by_key[key] = value
    return tuple(sorted(by_key.values(), key=lambda item: (_normalized_text(item), item)))


def build_ontology_proposals(
    store: KGStore, candidates: Iterable[OntologyCandidate]
) -> list[OntologyProposal]:
    """Collapse compatible candidates and return content-addressed proposals."""
    rows = list(candidates)
    if not rows:
        raise _error(
            "ontology_candidate_invalid", "candidates", "must not be empty"
        )
    by_id: dict[str, OntologyCandidate] = {}
    for candidate in rows:
        if not isinstance(candidate, OntologyCandidate):
            raise _error(
                "ontology_candidate_invalid",
                "candidates",
                "must contain OntologyCandidate artifacts",
            )
        previous = by_id.get(candidate.id)
        if previous is not None and _canonical(asdict(previous)) != _canonical(
            asdict(candidate)
        ):
            raise _error(
                "ontology_candidate_conflict",
                "id",
                f"candidate id {candidate.id!r} has conflicting content",
                status_code=409,
            )
        by_id[candidate.id] = candidate

    groups: dict[tuple[Any, ...], list[OntologyCandidate]] = {}
    for candidate in by_id.values():
        if store.conn.execute(
            "SELECT 1 FROM schema_version WHERE id = ?",
            (candidate.schema_version_id,),
        ).fetchone() is None:
            raise _error(
                "ontology_candidate_invalid",
                "schema_version_id",
                f"unknown schema version {candidate.schema_version_id!r}",
            )
        groups.setdefault(_candidate_group_key(candidate), []).append(candidate)

    proposals: list[OntologyProposal] = []
    for key in sorted(groups, key=_canonical):
        group = sorted(groups[key], key=lambda item: (_canonical(asdict(item)), item.id))
        representative = group[0]
        label = min(
            (item.preferred_label for item in group),
            key=lambda item: (item.casefold(), item),
        )
        aliases = _dedup_aliases(
            [
                alias
                for item in group
                for alias in (*item.aliases, item.preferred_label)
            ],
            label,
        )
        xrefs_by_value = {
            _canonical(asdict(xref)): xref
            for item in group
            for xref in item.xrefs
        }
        matches = _matching_term_ids(
            store,
            schema_version_id=representative.schema_version_id,
            preferred_label=label,
            language=representative.language,
        )
        if len(matches) > 1:
            raise _error(
                "ontology_identity_ambiguous",
                "preferred_label",
                f"local label matches multiple terms: {matches}",
                status_code=409,
            )
        source_verifications = tuple(
            OntologySourceVerification(
                candidate_id=item.id,
                status=item.source_status,
                verified_by=item.source_verified_by,
                verified_at=item.source_verified_at,
            )
            for item in sorted(group, key=lambda item: item.id)
        )
        proposal = OntologyProposal(
            id="",
            action="augment" if matches else "create",
            target_term_id=matches[0] if matches else None,
            schema_version_id=representative.schema_version_id,
            source_kind=representative.source_kind,
            type_name=representative.type_name,
            preferred_label=label,
            language=representative.language,
            definition=representative.definition,
            aliases=aliases,
            qualifiers=_json_value(
                representative.qualifiers,
                "qualifiers",
                "ontology_candidate_invalid",
            ),
            lifecycle=representative.lifecycle,
            replacement_term_id=representative.replacement_term_id,
            change_reason=representative.change_reason,
            xrefs=tuple(xrefs_by_value[value] for value in sorted(xrefs_by_value)),
            source_candidate_ids=tuple(sorted(item.id for item in group)),
            source_verifications=source_verifications,
            requires_human_verification=True,
            verification=None,
        )
        proposals.append(replace(proposal, id=_proposal_id(proposal)))
    return sorted(proposals, key=lambda item: item.id)


def proposal_to_dict(proposal: OntologyProposal) -> dict[str, Any]:
    """Serialize an artifact without adding presentation-only fields."""
    return asdict(proposal)


def proposal_from_dict(raw: Any) -> OntologyProposal:
    """Validate an unverified proposal and re-check its content address."""
    kind = "ontology_proposal_invalid"
    value = _mapping(raw, "proposal", kind)
    _known_fields(value, _PROPOSAL_FIELDS, "proposal", kind)
    action = _text(value.get("action"), "action", kind)
    if action not in _PROPOSAL_ACTIONS:
        raise _error(kind, "action", f"unsupported value {action!r}")
    target_term_id = _optional_text(
        value.get("target_term_id"), "target_term_id", kind
    )
    if (action == "create") != (target_term_id is None):
        raise _error(
            kind,
            "target_term_id",
            "create requires no target; augment requires one target",
        )
    source_kind = _text(value.get("source_kind"), "source_kind", kind)
    if source_kind not in _SOURCE_KINDS:
        raise _error(kind, "source_kind", f"unsupported value {source_kind!r}")
    aliases = _text_tuple(value.get("aliases", []), "aliases", kind)
    qualifiers = _json_value(value.get("qualifiers", {}), "qualifiers", kind)
    if not isinstance(qualifiers, dict):
        raise _error(kind, "qualifiers", "must be an object")
    lifecycle, replacement_id, reason = _validate_term_lifecycle(
        value.get("lifecycle"),
        value.get("replacement_term_id"),
        value.get("change_reason"),
        kind=kind,
    )
    raw_xrefs = value.get("xrefs", [])
    if not isinstance(raw_xrefs, (list, tuple)):
        raise _error(kind, "xrefs", "must be an array")
    xrefs = tuple(
        _xref_from_dict(item, field=f"xrefs[{index}]", kind=kind)
        for index, item in enumerate(raw_xrefs)
    )
    source_ids = _id_tuple(
        value.get("source_candidate_ids"), "source_candidate_ids", kind
    )
    if not source_ids:
        raise _error(kind, "source_candidate_ids", "must not be empty")
    raw_verifications = value.get("source_verifications")
    if not isinstance(raw_verifications, (list, tuple)):
        raise _error(kind, "source_verifications", "must be an array")
    source_verifications: list[OntologySourceVerification] = []
    for index, raw_verification in enumerate(raw_verifications):
        field = f"source_verifications[{index}]"
        item = _mapping(raw_verification, field, kind)
        _known_fields(
            item, {"candidate_id", "status", "verified_by", "verified_at"}, field, kind
        )
        candidate_id = _text(item.get("candidate_id"), f"{field}.candidate_id", kind)
        status = _text(item.get("status"), f"{field}.status", kind)
        if status not in _SOURCE_STATUSES:
            raise _error(kind, f"{field}.status", f"unsupported value {status!r}")
        verified_by = _optional_text(
            item.get("verified_by"), f"{field}.verified_by", kind
        )
        verified_at = (
            _number(item.get("verified_at"), f"{field}.verified_at", kind)
            if item.get("verified_at") is not None
            else None
        )
        if status == "verified" and (verified_by is None or verified_at is None):
            raise _error(kind, field, "verified source metadata is incomplete")
        if status == "proposed" and (verified_by is not None or verified_at is not None):
            raise _error(kind, field, "proposed source carries verification metadata")
        source_verifications.append(
            OntologySourceVerification(candidate_id, status, verified_by, verified_at)
        )
    if tuple(sorted(item.candidate_id for item in source_verifications)) != source_ids:
        raise _error(
            kind,
            "source_verifications",
            "must describe every source candidate exactly once",
        )
    if value.get("requires_human_verification") is not True:
        raise _error(
            kind,
            "requires_human_verification",
            "an unapplied proposal must require human verification",
        )
    if value.get("verification") is not None:
        raise _error(kind, "verification", "proposal has already been verified")
    proposal = OntologyProposal(
        id=_text(value.get("id"), "id", kind),
        action=action,
        target_term_id=target_term_id,
        schema_version_id=_integer(
            value.get("schema_version_id"), "schema_version_id", kind
        ),
        source_kind=source_kind,
        type_name=_text(value.get("type_name"), "type_name", kind),
        preferred_label=_text(
            value.get("preferred_label"), "preferred_label", kind
        ),
        language=_text(value.get("language"), "language", kind),
        definition=_text(value.get("definition"), "definition", kind),
        aliases=aliases,
        qualifiers=qualifiers,
        lifecycle=lifecycle,
        replacement_term_id=replacement_id,
        change_reason=reason,
        xrefs=xrefs,
        source_candidate_ids=source_ids,
        source_verifications=tuple(
            sorted(source_verifications, key=lambda item: item.candidate_id)
        ),
        requires_human_verification=True,
        verification=None,
    )
    expected_id = _proposal_id(replace(proposal, id=""))
    if proposal.id != expected_id:
        raise _error(kind, "id", "does not match the proposal content")
    return proposal


def verification_from_dict(raw: Any) -> tuple[str, str, str | None]:
    kind = "ontology_verification_invalid"
    value = _mapping(raw, "verification", kind)
    _known_fields(value, {"reviewer", "provenance", "note"}, "verification", kind)
    return (
        _text(value.get("reviewer"), "reviewer", kind),
        _text(value.get("provenance"), "provenance", kind),
        _optional_text(value.get("note"), "note", kind),
    )


def verify_request_from_dict(
    raw: Any,
) -> tuple[OntologyProposal, tuple[str, str, str | None]]:
    kind = "ontology_proposal_invalid"
    value = _mapping(raw, "body", kind)
    _known_fields(value, {"proposal", "verification"}, "body", kind)
    return proposal_from_dict(value.get("proposal")), verification_from_dict(
        value.get("verification")
    )


def _xref_key(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value.get(field) for field in (
        "authority",
        "external_id",
        "mapping_predicate",
        "source_uri",
        "source_version",
        "valid_from",
        "valid_to",
        "retrieved_at",
        "confidence",
        "lifecycle",
        "replacement_xref_id",
        "change_reason",
        "license_gate",
    ))


def _preflight_proposal(store: KGStore, proposal: OntologyProposal) -> None:
    if store.conn.execute(
        "SELECT 1 FROM schema_version WHERE id = ?", (proposal.schema_version_id,)
    ).fetchone() is None:
        raise _error(
            "ontology_proposal_invalid",
            "schema_version_id",
            f"unknown schema version {proposal.schema_version_id!r}",
        )
    matches = _matching_term_ids(
        store,
        schema_version_id=proposal.schema_version_id,
        preferred_label=proposal.preferred_label,
        language=proposal.language,
    )
    if proposal.action == "create" and matches:
        raise _error(
            "ontology_proposal_stale",
            "action",
            "a matching local term now exists; preview the proposal again",
            status_code=409,
        )
    if proposal.action == "augment" and matches != [proposal.target_term_id]:
        raise _error(
            "ontology_proposal_stale",
            "target_term_id",
            "the local label match changed; preview the proposal again",
            status_code=409,
        )
    if proposal.replacement_term_id is not None:
        replacement = store.conn.execute(
            "SELECT id FROM ontology_term WHERE id = ?",
            (proposal.replacement_term_id,),
        ).fetchone()
        if replacement is None:
            raise _error(
                "ontology_proposal_invalid",
                "replacement_term_id",
                f"unknown ontology term {proposal.replacement_term_id!r}",
            )
        if proposal.replacement_term_id == proposal.target_term_id:
            raise _error(
                "ontology_proposal_invalid",
                "replacement_term_id",
                "a term cannot replace itself",
            )
    if proposal.action == "augment":
        target = store.get_ontology_term(proposal.target_term_id or "")
        if target["lifecycle"] == "replaced" and (
            proposal.lifecycle,
            proposal.replacement_term_id,
            proposal.change_reason,
        ) != (
            target["lifecycle"],
            target["replacement_term_id"],
            target["change_reason"],
        ):
            raise _error(
                "ontology_proposal_conflict",
                "lifecycle",
                "a replaced target term is terminal",
                status_code=409,
            )
        for xref in proposal.xrefs:
            if xref.replacement_xref_id is None:
                continue
            replacement = store.conn.execute(
                "SELECT term_id FROM term_xref WHERE id = ?",
                (xref.replacement_xref_id,),
            ).fetchone()
            if replacement is None or replacement["term_id"] != proposal.target_term_id:
                raise _error(
                    "ontology_proposal_invalid",
                    "replacement_xref_id",
                    "replacement xref must already belong to the target term",
                )
    elif any(xref.replacement_xref_id is not None for xref in proposal.xrefs):
        raise _error(
            "ontology_proposal_invalid",
            "replacement_xref_id",
            "a new term cannot replace an xref belonging to another term",
        )


def verify_ontology_proposal(
    store: KGStore,
    proposal: OntologyProposal,
    verification: tuple[str, str, str | None],
) -> tuple[OntologyProposal, dict[str, Any], bool]:
    """Apply one validated proposal and return its human verification receipt."""
    _preflight_proposal(store, proposal)
    reviewer, provenance, note = verification
    created = proposal.action == "create"
    try:
        if created:
            term_id = store.create_ontology_term(
                preferred_label=proposal.preferred_label,
                language=proposal.language,
                definition=proposal.definition,
                schema_version_id=proposal.schema_version_id,
                reviewer=reviewer,
                provenance=provenance,
            )
        else:
            term_id = proposal.target_term_id or ""

        existing_aliases = {
            (_normalized_text(alias["label"]), _normalized_text(alias["language"]))
            for alias in store.list_term_aliases(term_id)
        }
        existing_aliases.add(
            (_normalized_text(proposal.preferred_label), _normalized_text(proposal.language))
        )
        for alias in proposal.aliases:
            key = (_normalized_text(alias), _normalized_text(proposal.language))
            if key in existing_aliases:
                continue
            store.add_term_alias(
                term_id=term_id,
                label=alias,
                language=proposal.language,
                reviewer=reviewer,
                provenance=provenance,
            )
            existing_aliases.add(key)

        existing_xrefs = {
            _xref_key(row) for row in store.list_term_xrefs(term_id)
        }
        for xref in proposal.xrefs:
            xref_data = asdict(xref)
            if _xref_key(xref_data) in existing_xrefs:
                continue
            store.add_term_xref(
                term_id=term_id,
                reviewer=reviewer,
                **xref_data,
            )
            existing_xrefs.add(_xref_key(xref_data))

        current_term = store.get_ontology_term(term_id)
        if (
            proposal.lifecycle,
            proposal.replacement_term_id,
            proposal.change_reason,
        ) != (
            current_term["lifecycle"],
            current_term["replacement_term_id"],
            current_term["change_reason"],
        ):
            store.set_ontology_term_lifecycle(
                term_id,
                lifecycle=proposal.lifecycle,
                replacement_term_id=proposal.replacement_term_id,
                change_reason=proposal.change_reason,
                reviewer=reviewer,
                provenance=provenance,
            )
        term = store.get_ontology_term(term_id)
    except OntologyTermValidationError as exc:
        raise _error(
            "ontology_proposal_invalid", exc.field, exc.message
        ) from exc
    except XrefValidationError as exc:
        raise _error("ontology_proposal_invalid", exc.field, exc.message) from exc
    except UnknownItem as exc:
        raise _error(
            "ontology_proposal_stale",
            "target_term_id",
            str(exc),
            status_code=409,
        ) from exc

    receipt = HumanVerification(
        decision="approved",
        reviewer=reviewer,
        provenance=provenance,
        verified_at=time.time(),
        note=note,
    )
    return (
        replace(
            proposal,
            requires_human_verification=False,
            verification=receipt,
        ),
        term,
        created,
    )


__all__ = [
    "OntologyProposalError",
    "candidate_from_dict",
    "candidates_from_extractions",
    "candidates_from_preview_request",
    "build_ontology_proposals",
    "proposal_to_dict",
    "proposal_from_dict",
    "verification_from_dict",
    "verify_request_from_dict",
    "verify_ontology_proposal",
]
