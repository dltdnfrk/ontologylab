"""Canonical JSON decoding and typed construction for Method IR."""

from __future__ import annotations

from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Any, Callable, Never
import unicodedata


Fail = Callable[[str, str], Never]
Constructor = Callable[..., Any]

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_POINTER = re.compile(r"(?:/(?:[^~/\x00-\x1f]|~[01])*)+\Z")
_UNITS = {
    "degC": "temperature",
    "K": "temperature",
    "s": "time",
    "min": "time",
    "kg": "mass",
    "g": "mass",
    "mL": "volume",
    "L": "volume",
    "%": "dimensionless",
    "1": "dimensionless",
}
_GAP_CLASSES = {
    "required_slot_missing",
    "factual_field_without_evidence",
    "dangling_reference",
    "step_dependency_cycle",
    "unreachable_result",
    "type_discontinuity",
    "unit_dimension_mismatch",
    "unmeasurable_condition",
    "stale_selector",
    "blocked_policy",
    "failed_fixture",
    "explicit_counter_evidence",
    "open_conflict",
}
_GAP_STATUSES = {
    "open",
    "resolved_by_evidence",
    "addressed_by_assumption",
    "waived",
}
_BRIDGE_DECISIONS = {
    "pending",
    "accepted_as_assumption",
    "rejected",
    "superseded",
}
_POLARITIES = {"positive", "negative", "unknown"}
_MODALITIES = {
    "asserted",
    "required",
    "recommended",
    "possible",
    "unknown",
}
_GATES = {f"G{index}" for index in range(9)}


def pointer_tokens(pointer: str) -> tuple[str, ...]:
    """Return RFC 6901 tokens while preserving the required decode order."""
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer.split("/")[1:]
    )


class MethodIRCodec:
    """Decode raw JSON using the public types supplied by ``method_ir``."""

    def __init__(
        self,
        *,
        validation_error: type[Exception],
        fail: Fail,
        value_state: type[Enum],
        value_kind: type[Enum],
        epistemic_class: type[Enum],
        fragment_kind: type[Enum],
        evidence_role: type[Enum],
        link_kind: type[Enum],
        source_selector: Constructor,
        unit: Constructor,
        value_range: Constructor,
        typed_value: Constructor,
        statement_occurrence: Constructor,
        method_fragment: Constructor,
        field_evidence: Constructor,
        method_link: Constructor,
        method_gap: Constructor,
        bridge_assumption: Constructor,
        review_receipt: Constructor,
        compiler_gate_result: Constructor,
        source_index_row: Constructor,
        method_release: Constructor,
        method_ir: Constructor,
    ) -> None:
        (
            self._validation_error,
            self._fail,
            self._value_state,
            self._value_kind,
            self._epistemic_class,
            self._fragment_kind,
            self._evidence_role,
            self._link_kind,
            self._source_selector,
            self._unit_type,
            self._value_range,
            self._typed_value,
            self._statement_occurrence,
            self._method_fragment,
            self._field_evidence,
            self._method_link,
            self._method_gap,
            self._bridge_assumption,
            self._review_receipt,
            self._compiler_gate_result,
            self._source_index_row,
            self._method_release,
            self._method_ir,
        ) = (
            validation_error,
            fail,
            value_state,
            value_kind,
            epistemic_class,
            fragment_kind,
            evidence_role,
            link_kind,
            source_selector,
            unit,
            value_range,
            typed_value,
            statement_occurrence,
            method_fragment,
            field_evidence,
            method_link,
            method_gap,
            bridge_assumption,
            review_receipt,
            compiler_gate_result,
            source_index_row,
            method_release,
            method_ir,
        )

    def _obj(
        self,
        value: Any,
        path: str,
        fields: set[str],
        required: set[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            self._fail(path, "must be an object")
        extra = sorted(set(value) - fields)
        missing = sorted((required or fields) - set(value))
        if extra:
            self._fail(f"{path}.{extra[0]}", "unknown field")
        if missing:
            self._fail(
                f"{path}.{missing[0]}",
                "required field is missing",
            )
        return value

    def _text(self, value: Any, path: str) -> str:
        if isinstance(value, str) and value:
            return unicodedata.normalize("NFC", value)
        return self._fail(path, "must be a non-empty string")

    def _int(self, value: Any, path: str, minimum: int = 0) -> int:
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= minimum
        ):
            return value
        return self._fail(
            path,
            f"must be an integer >= {minimum}",
        )

    def _num(self, value: Any, path: str) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._fail(path, "must be a real number")
        if not math.isfinite(value):
            self._fail(path, "must be finite")
        return value

    def _enum(
        self,
        enum_type: type[Enum],
        value: Any,
        path: str,
    ) -> Enum:
        try:
            return enum_type(value)
        except (TypeError, ValueError):
            return self._fail(
                path,
                f"unknown {enum_type.__name__} value",
            )

    def _pointer(self, value: Any, path: str) -> str:
        pointer = self._text(value, path)
        if not _POINTER.fullmatch(pointer):
            self._fail(
                path,
                "must be a valid non-empty JSON Pointer",
            )
        return pointer

    def _hash(self, value: Any, path: str) -> str:
        digest = self._text(value, path)
        if not _HASH.fullmatch(digest):
            self._fail(
                path,
                "must be sha256:<64 lowercase hex>",
            )
        return digest

    def _texts(self, value: Any, path: str) -> tuple[str, ...]:
        if not isinstance(value, list):
            self._fail(path, "must be an array")
        result = tuple(
            self._text(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )
        if len(set(result)) != len(result):
            self._fail(path, "contains duplicate values")
        return result

    def _items(
        self,
        value: Any,
        path: str,
        parse: Callable[[Any, str], Any],
    ) -> tuple[Any, ...]:
        if not isinstance(value, list):
            self._fail(path, "must be an array")
        result = tuple(
            parse(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )
        seen: set[str] = set()
        for index, item in enumerate(result):
            if item.id in seen:
                self._fail(
                    f"{path}[{index}].id",
                    "duplicate ID",
                )
            seen.add(item.id)
        return tuple(sorted(result, key=lambda item: item.id))

    def _unit(self, value: Any, path: str) -> Any:
        obj = self._obj(value, path, {"symbol", "dimension"})
        symbol = self._text(obj["symbol"], f"{path}.symbol")
        dimension = self._text(
            obj["dimension"],
            f"{path}.dimension",
        )
        known_dimension = _UNITS.get(symbol)
        if (
            known_dimension is not None
            and dimension != known_dimension
        ):
            self._fail(
                f"{path}.dimension",
                f"must be {known_dimension!r} for unit {symbol!r}",
            )
        if known_dimension is None and dimension != "unknown":
            self._fail(
                f"{path}.dimension",
                "unknown units require explicit 'unknown' dimension",
            )
        return self._unit_type(
            symbol,
            dimension,
            known_dimension is not None,
        )

    def _value(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {"state", "kind", "value", "unit"},
            {"state", "kind"},
        )
        state = self._enum(
            self._value_state,
            obj["state"],
            f"{path}.state",
        )
        kind = self._enum(
            self._value_kind,
            obj["kind"],
            f"{path}.kind",
        )
        if state.value != "known":
            if "value" in obj or "unit" in obj:
                self._fail(
                    f"{path}.value",
                    "non-known state cannot carry a value or unit",
                )
            return self._typed_value(state, kind)
        if "value" not in obj:
            self._fail(
                f"{path}.value",
                "known state requires an explicit value",
            )
        parsed_value = obj["value"]
        if kind.value == "string":
            parsed_value = self._text(
                parsed_value,
                f"{path}.value",
            )
        elif kind.value == "integer":
            parsed_value = self._int(
                parsed_value,
                f"{path}.value",
                -(2**63),
            )
        elif kind.value == "real":
            parsed_value = self._num(
                parsed_value,
                f"{path}.value",
            )
        elif kind.value == "boolean":
            if not isinstance(parsed_value, bool):
                self._fail(
                    f"{path}.value",
                    "must be a boolean",
                )
        else:
            range_obj = self._obj(
                parsed_value,
                f"{path}.value",
                {
                    "minimum",
                    "maximum",
                    "minimum_inclusive",
                    "maximum_inclusive",
                },
            )
            minimum = self._num(
                range_obj["minimum"],
                f"{path}.value.minimum",
            )
            maximum = self._num(
                range_obj["maximum"],
                f"{path}.value.maximum",
            )
            if minimum > maximum:
                self._fail(
                    f"{path}.value.maximum",
                    "must be >= minimum",
                )
            if (
                not isinstance(
                    range_obj["minimum_inclusive"],
                    bool,
                )
                or not isinstance(
                    range_obj["maximum_inclusive"],
                    bool,
                )
            ):
                self._fail(
                    f"{path}.value",
                    "range inclusivity fields must be booleans",
                )
            parsed_value = self._value_range(
                minimum,
                maximum,
                range_obj["minimum_inclusive"],
                range_obj["maximum_inclusive"],
            )
        if (
            "unit" in obj
            and kind.value in {"string", "boolean"}
        ):
            self._fail(
                f"{path}.unit",
                "units are allowed only for integer, real, or range values",
            )
        parsed_unit = (
            self._unit(obj["unit"], f"{path}.unit")
            if "unit" in obj
            else None
        )
        return self._typed_value(
            state,
            kind,
            parsed_value,
            parsed_unit,
        )

    def _selector(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {
                "document_id",
                "document_content_hash",
                "span_start",
                "span_end",
                "selected_text_hash",
            },
        )
        start = self._int(
            obj["span_start"],
            f"{path}.span_start",
        )
        end = self._int(
            obj["span_end"],
            f"{path}.span_end",
        )
        if end <= start:
            self._fail(
                f"{path}.span_end",
                "must be greater than span_start",
            )
        return self._source_selector(
            self._text(
                obj["document_id"],
                f"{path}.document_id",
            ),
            self._hash(
                obj["document_content_hash"],
                f"{path}.document_content_hash",
            ),
            start,
            end,
            self._hash(
                obj["selected_text_hash"],
                f"{path}.selected_text_hash",
            ),
        )

    def _fragment(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {"id", "kind", "epistemic_class", "payload"},
        )
        if (
            not isinstance(obj["payload"], dict)
            or not obj["payload"]
        ):
            self._fail(
                f"{path}.payload",
                "must be a non-empty object",
            )
        payload: dict[str, Any] = {}
        for raw_key, raw_value in obj["payload"].items():
            key = self._text(raw_key, f"{path}.payload key")
            if key in payload:
                self._fail(
                    f"{path}.payload.{key}",
                    "key normalizes to duplicate",
                )
            payload[key] = self._value(
                raw_value,
                f"{path}.payload.{key}",
            )
        return self._method_fragment(
            self._text(obj["id"], f"{path}.id"),
            self._enum(
                self._fragment_kind,
                obj["kind"],
                f"{path}.kind",
            ),
            self._enum(
                self._epistemic_class,
                obj["epistemic_class"],
                f"{path}.epistemic_class",
            ),
            MappingProxyType(payload),
        )

    def _evidence(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {
                "id",
                "fragment_id",
                "field_path",
                "occurrence_id",
                "role",
            },
        )
        return self._field_evidence(
            self._text(obj["id"], f"{path}.id"),
            self._text(
                obj["fragment_id"],
                f"{path}.fragment_id",
            ),
            self._pointer(
                obj["field_path"],
                f"{path}.field_path",
            ),
            self._text(
                obj["occurrence_id"],
                f"{path}.occurrence_id",
            ),
            self._enum(
                self._evidence_role,
                obj["role"],
                f"{path}.role",
            ),
        )

    def _link(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {"id", "src_fragment_id", "dst_fragment_id", "kind"},
        )
        return self._method_link(
            self._text(obj["id"], f"{path}.id"),
            self._text(
                obj["src_fragment_id"],
                f"{path}.src_fragment_id",
            ),
            self._text(
                obj["dst_fragment_id"],
                f"{path}.dst_fragment_id",
            ),
            self._enum(
                self._link_kind,
                obj["kind"],
                f"{path}.kind",
            ),
        )

    def _gap(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {
                "id",
                "gap_class",
                "status",
                "target_fragment_id",
                "field_path",
            },
        )
        if obj["gap_class"] not in _GAP_CLASSES:
            self._fail(
                f"{path}.gap_class",
                "unknown gap class",
            )
        if obj["status"] not in _GAP_STATUSES:
            self._fail(
                f"{path}.status",
                "unknown gap status",
            )
        target_fragment_id = (
            None
            if obj["target_fragment_id"] is None
            else self._text(
                obj["target_fragment_id"],
                f"{path}.target_fragment_id",
            )
        )
        field_path = (
            None
            if obj["field_path"] is None
            else self._pointer(
                obj["field_path"],
                f"{path}.field_path",
            )
        )
        return self._method_gap(
            self._text(obj["id"], f"{path}.id"),
            self._text(
                obj["gap_class"],
                f"{path}.gap_class",
            ),
            obj["status"],
            target_fragment_id,
            field_path,
        )

    def _bridge(self, value: Any, path: str) -> Any:
        fields = {
            "id",
            "gap_id",
            "hypothesis",
            "assumptions",
            "scope",
            "limits",
            "falsifier",
            "minimum_validation",
            "decision_status",
            "epistemic_class",
        }
        obj = self._obj(value, path, fields)
        epistemic = self._enum(
            self._epistemic_class,
            obj["epistemic_class"],
            f"{path}.epistemic_class",
        )
        if epistemic.value != "bridge_assumption":
            self._fail(
                f"{path}.epistemic_class",
                "bridge must remain bridge_assumption",
            )
        if obj["decision_status"] not in _BRIDGE_DECISIONS:
            self._fail(
                f"{path}.decision_status",
                "unknown bridge decision",
            )
        return self._bridge_assumption(
            self._text(obj["id"], f"{path}.id"),
            self._text(obj["gap_id"], f"{path}.gap_id"),
            self._text(
                obj["hypothesis"],
                f"{path}.hypothesis",
            ),
            self._texts(
                obj["assumptions"],
                f"{path}.assumptions",
            ),
            self._text(obj["scope"], f"{path}.scope"),
            self._texts(obj["limits"], f"{path}.limits"),
            self._text(
                obj["falsifier"],
                f"{path}.falsifier",
            ),
            self._text(
                obj["minimum_validation"],
                f"{path}.minimum_validation",
            ),
            obj["decision_status"],
            epistemic,
        )

    def _review(self, value: Any, path: str) -> Any:
        keys = (
            "id",
            "subject_kind",
            "subject_id",
            "decision",
            "reviewer",
            "note",
        )
        obj = self._obj(value, path, set(keys))
        return self._review_receipt(
            *(
                self._text(obj[key], f"{path}.{key}")
                for key in keys
            )
        )

    def _gate(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {"gate", "passed", "reasons"},
        )
        gate = self._text(obj["gate"], f"{path}.gate")
        if gate not in _GATES:
            self._fail(
                f"{path}.gate",
                "must be G0 through G8",
            )
        if not isinstance(obj["passed"], bool):
            self._fail(
                f"{path}.passed",
                "must be a boolean",
            )
        return self._compiler_gate_result(
            gate,
            gate,
            obj["passed"],
            self._texts(
                obj["reasons"],
                f"{path}.reasons",
            ),
        )

    def _source(self, value: Any, path: str) -> Any:
        fields = {
            "id",
            "method_id",
            "field_path",
            "document_id",
            "document_content_hash",
            "span_start",
            "span_end",
            "selected_text_hash",
            "evidence_role",
            "epistemic_class",
            "occurrence_id",
            "receipt_ref",
        }
        obj = self._obj(value, path, fields)
        start = self._int(
            obj["span_start"],
            f"{path}.span_start",
        )
        end = self._int(
            obj["span_end"],
            f"{path}.span_end",
        )
        if end <= start:
            self._fail(
                f"{path}.span_end",
                "must be greater than span_start",
            )
        epistemic = self._enum(
            self._epistemic_class,
            obj["epistemic_class"],
            f"{path}.epistemic_class",
        )
        if (
            epistemic.value == "bridge_assumption"
            and obj["evidence_role"] == "supports"
        ):
            self._fail(
                f"{path}.evidence_role",
                "bridge assumptions cannot be source-supported",
            )
        return self._source_index_row(
            self._text(obj["id"], f"{path}.id"),
            self._text(
                obj["method_id"],
                f"{path}.method_id",
            ),
            self._pointer(
                obj["field_path"],
                f"{path}.field_path",
            ),
            self._text(
                obj["document_id"],
                f"{path}.document_id",
            ),
            self._hash(
                obj["document_content_hash"],
                f"{path}.document_content_hash",
            ),
            start,
            end,
            self._hash(
                obj["selected_text_hash"],
                f"{path}.selected_text_hash",
            ),
            self._enum(
                self._evidence_role,
                obj["evidence_role"],
                f"{path}.evidence_role",
            ),
            epistemic,
            self._text(
                obj["occurrence_id"],
                f"{path}.occurrence_id",
            ),
            self._text(
                obj["receipt_ref"],
                f"{path}.receipt_ref",
            ),
        )

    def _release(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {
                "id",
                "workspace_id",
                "version",
                "compiler_version",
                "content_hash",
            },
        )
        return self._method_release(
            self._text(obj["id"], f"{path}.id"),
            self._text(
                obj["workspace_id"],
                f"{path}.workspace_id",
            ),
            self._int(
                obj["version"],
                f"{path}.version",
                1,
            ),
            self._text(
                obj["compiler_version"],
                f"{path}.compiler_version",
            ),
            self._hash(
                obj["content_hash"],
                f"{path}.content_hash",
            ),
        )

    def _load(self, raw: Any) -> Any:
        if isinstance(raw, (str, bytes, bytearray)):
            try:
                return json.loads(
                    raw,
                    parse_constant=lambda value: self._fail(
                        "$",
                        f"non-finite JSON constant {value}",
                    ),
                )
            except self._validation_error:
                raise
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                detail = (
                    error.msg
                    if isinstance(error, json.JSONDecodeError)
                    else "invalid UTF-8"
                )
                return self._fail(
                    "$",
                    f"malformed JSON ({detail})",
                )
        return raw

    def _root_ids(self, raw: dict[str, Any]) -> None:
        seen: set[str] = set()
        names = (
            "fragments",
            "field_evidence",
            "links",
            "gaps",
            "bridge_assumptions",
            "review_receipts",
            "gate_results",
            "source_index",
        )
        for name in names:
            for index, item in enumerate(raw[name]):
                ident = self._text(
                    (
                        item["gate"]
                        if name == "gate_results"
                        else item["id"]
                    ),
                    f"$.{name}[{index}].id",
                )
                if ident in seen:
                    self._fail(
                        f"$.{name}[{index}].id",
                        "duplicate root object ID",
                    )
                seen.add(ident)

    def parse_method(self, raw: Any) -> Any:
        fields = {
            "schema_version",
            "id",
            "version",
            "name",
            "fragments",
            "field_evidence",
            "links",
            "gaps",
            "bridge_assumptions",
            "review_receipts",
            "gate_results",
            "source_index",
            "release",
        }
        obj = self._obj(self._load(raw), "$", fields)
        if obj["schema_version"] != "method-v1":
            self._fail(
                "$.schema_version",
                "must be 'method-v1'",
            )
        gates = self._items(
            obj["gate_results"],
            "$.gate_results",
            self._gate,
        )
        if {gate.gate for gate in gates} != _GATES:
            self._fail(
                "$.gate_results",
                "must contain G0 through G8 exactly once",
            )
        method = self._method_ir(
            "method-v1",
            self._text(obj["id"], "$.id"),
            self._int(obj["version"], "$.version", 1),
            self._text(obj["name"], "$.name"),
            self._items(
                obj["fragments"],
                "$.fragments",
                self._fragment,
            ),
            self._items(
                obj["field_evidence"],
                "$.field_evidence",
                self._evidence,
            ),
            self._items(
                obj["links"],
                "$.links",
                self._link,
            ),
            self._items(
                obj["gaps"],
                "$.gaps",
                self._gap,
            ),
            self._items(
                obj["bridge_assumptions"],
                "$.bridge_assumptions",
                self._bridge,
            ),
            self._items(
                obj["review_receipts"],
                "$.review_receipts",
                self._review,
            ),
            gates,
            self._items(
                obj["source_index"],
                "$.source_index",
                self._source,
            ),
            self._release(obj["release"], "$.release"),
        )
        self._root_ids(obj)
        return method

    def _occurrence(self, value: Any, path: str) -> Any:
        obj = self._obj(
            value,
            path,
            {
                "id",
                "selector",
                "statement_text",
                "polarity",
                "modality",
                "temporal_scope",
                "applicability_scope",
            },
        )
        if obj["polarity"] not in _POLARITIES:
            self._fail(
                f"{path}.polarity",
                "unknown polarity",
            )
        if obj["modality"] not in _MODALITIES:
            self._fail(
                f"{path}.modality",
                "unknown modality",
            )
        return self._statement_occurrence(
            self._text(obj["id"], f"{path}.id"),
            self._selector(
                obj["selector"],
                f"{path}.selector",
            ),
            self._text(
                obj["statement_text"],
                f"{path}.statement_text",
            ),
            obj["polarity"],
            obj["modality"],
            self._value(
                obj["temporal_scope"],
                f"{path}.temporal_scope",
            ),
            self._value(
                obj["applicability_scope"],
                f"{path}.applicability_scope",
            ),
        )

    def parse_occurrences(self, raw: Any) -> tuple[Any, ...]:
        obj = self._obj(
            self._load(raw),
            "$",
            {"schema_version", "occurrences"},
        )
        if obj["schema_version"] != "method-occurrence-v1":
            self._fail(
                "$.schema_version",
                "must be 'method-occurrence-v1'",
            )
        return self._items(
            obj["occurrences"],
            "$.occurrences",
            self._occurrence,
        )
