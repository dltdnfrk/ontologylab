"""Typed extraction receipt values and refusal codes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn


DOCUMENT_UTF8_V1: Final = "document-utf8-v1"


@unique
class CoordinateProfile(StrEnum):
    DOCUMENT_UTF8_V1 = DOCUMENT_UTF8_V1


@unique
class ExtractionReceiptRefusalCode(StrEnum):
    MISSING_BINDING = "missing_binding"
    INVALID_RANGE = "invalid_range"
    INVALID_HASH = "invalid_hash"
    INVALID_PROFILE = "invalid_profile"
    CONFLICT = "conflict"
    NOT_READY = "not_ready"
    UNKNOWN_REPRESENTATION = "unknown_representation"


@dataclass(frozen=True, slots=True)
class ExtractionReceiptRefused(Exception):
    code: ExtractionReceiptRefusalCode
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class ChunkSpan:
    index: int
    start_offset: int
    end_offset: int
    text: str
    text_hash: str
    coordinate_profile: str


@dataclass(frozen=True, slots=True)
class ExtractionRunBinding:
    representation_id: str
    policy_identity: str
    config_identity: str
    schema_version_id: int
    extractor_engine: str
    extractor_model: str
    prompt_version: str
    decode_params_json: str


@dataclass(frozen=True, slots=True)
class ExtractionRunReceipt:
    receipt_id: str
    representation_id: str
    document_content_hash: str
    policy_identity: str
    config_identity: str
    chunk_plan_receipt_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class ExtractionChunkReceipt:
    receipt_id: str
    run_receipt_id: str
    chunk_index: int
    start_offset: int
    end_offset: int
    coordinate_profile: str
    chunk_text_hash: str
    plan_receipt_id: str


@dataclass(frozen=True, slots=True)
class ExtractionReceiptSet:
    run: ExtractionRunReceipt
    chunks: tuple[ExtractionChunkReceipt, ...]


def refuse(code: ExtractionReceiptRefusalCode, message: str) -> NoReturn:
    raise ExtractionReceiptRefused(code, message)
