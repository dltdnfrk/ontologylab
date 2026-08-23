"""Deterministic citation receipt identities."""

from __future__ import annotations

from ontologylab.citation_types import CitationBinding, CitationReceipt
from ontologylab.extraction_receipt_ids import digest


def citation_receipt_id(binding: CitationBinding) -> str:
    return digest((
        "citation-receipt-v1",
        binding.representation_id,
        binding.representation_content_hash,
        binding.run_receipt_id,
        binding.chunk_receipt_id,
        str(binding.chunk_start_offset),
        str(binding.chunk_end_offset),
        binding.coordinate_profile,
        binding.chunk_text_hash,
        binding.chunk_plan_receipt_id,
        binding.selection_receipt_id or "",
        binding.policy_identity or "",
        binding.fact_kind,
        binding.fact_id,
        str(binding.start_offset),
        str(binding.end_offset),
        binding.selected_text_hash,
    ))


def fact_revision_id(fact_kind: str, fact_id: str) -> str:
    return digest(("fact-revision-v1", fact_kind, fact_id))


def receipt_from_binding(
    binding: CitationBinding, *, created: bool,
) -> CitationReceipt:
    return CitationReceipt(
        receipt_id=citation_receipt_id(binding),
        representation_id=binding.representation_id,
        representation_content_hash=binding.representation_content_hash,
        run_receipt_id=binding.run_receipt_id,
        chunk_receipt_id=binding.chunk_receipt_id,
        chunk_start_offset=binding.chunk_start_offset,
        chunk_end_offset=binding.chunk_end_offset,
        coordinate_profile=binding.coordinate_profile,
        chunk_text_hash=binding.chunk_text_hash,
        chunk_plan_receipt_id=binding.chunk_plan_receipt_id,
        selection_receipt_id=binding.selection_receipt_id,
        policy_identity=binding.policy_identity,
        fact_kind=binding.fact_kind,
        fact_id=binding.fact_id,
        proposal_id=binding.proposal_id,
        fact_revision=binding.fact_revision,
        start_offset=binding.start_offset,
        end_offset=binding.end_offset,
        selected_text=binding.selected_text,
        selected_text_hash=binding.selected_text_hash,
        created=created,
    )
