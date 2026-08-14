"""Pure canonical Method release-envelope validation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Any, Mapping, Sequence

from ontologylab.method_compiler_contract import (
    CompilerReceipt,
    validate_compiler_receipt,
)
from ontologylab.method_ir import canonical_json_bytes
from ontologylab.method_snapshot import canonical_compiler_receipt
from ontologylab.method_validation import (
    MethodValidationError,
    sha256_hash,
)

@dataclass(frozen=True, slots=True)
class CanonicalReleaseEnvelope:
    method_json: str
    source_index: str
    receipt: CompilerReceipt
    content_hash: str


def canonical_release_envelope(
    method_json: Mapping[str, Any],
    source_index: Sequence[Mapping[str, Any]],
    receipt: CompilerReceipt,
) -> CanonicalReleaseEnvelope:
    """Return the sole canonical Method/source-index/receipt envelope."""
    method_bytes = canonical_json_bytes(method_json)
    source_bytes = canonical_json_bytes(source_index)
    base_receipt = replace(
        validate_compiler_receipt(
            receipt,
            require_content_hash=False,
        ),
        content_hash=None,
    )
    expected_method_hash = (
        "sha256:" + hashlib.sha256(method_bytes).hexdigest()
    )
    if (
        sha256_hash("method_json_hash", receipt.method_json_hash)
        != expected_method_hash
    ):
        raise MethodValidationError(
            "compiler receipt method_json_hash does not match Method JSON"
        )
    expected_source_hash = (
        "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    )
    if (
        sha256_hash("source_index_hash", receipt.source_index_hash)
        != expected_source_hash
    ):
        raise MethodValidationError(
            "compiler receipt source_index_hash does not match source index"
        )
    base_payload = {
        "method_json": method_json,
        "source_index": source_index,
        "receipt": base_receipt,
    }
    content_hash = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(base_payload)
        ).hexdigest()
    )
    if receipt.content_hash not in (None, content_hash):
        raise MethodValidationError(
            "compiler receipt content_hash does not match canonical content hash"
        )
    finalized = replace(receipt, content_hash=content_hash)
    canonical_compiler_receipt(finalized)
    return CanonicalReleaseEnvelope(
        method_bytes.decode("utf-8"),
        source_bytes.decode("utf-8"),
        finalized,
        content_hash,
    )
