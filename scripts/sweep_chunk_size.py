"""Manual agrochem chunk-size sweep against the mini gold set.

CI에서는 돌지 않는 수동 스크립트다 (실 Claude 호출/비용 때문). 용도:
청크 기본값을 바꾸기 전에 1,500 vs 3,000 토큰의 품질과 호출 비용을 같은
문서/스키마/평가기로 비교하기.

    .venv/bin/python scripts/sweep_chunk_size.py --engine claude \
        --output-dir /tmp/ontologylab-chunk-sweep

The input fixture is a wrapper: ``documents`` are ingested, while ``gold`` is
written as a plain JSON file and loaded by the production evaluation harness.
The result JSON is checkpointed after each size, so a quota or CLI failure on
the second size does not erase a completed first measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontologylab.engines import EngineError, get_engine
from ontologylab.evaluation import evaluate_store, load_gold
from ontologylab.extractor import (
    PROMPT_VERSION,
    build_extraction_prompt,
    chunk_document,
    estimate_tokens,
    parse_and_validate_extraction,
)
from ontologylab.kgstore import KGStore
from ontologylab.schemas import preset

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = ROOT / "tests/gold/agrochem-mini/docs.json"
CHUNK_SIZES = (1500, 3000)


def load_wrapper(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Split the mini-gold wrapper into ingest documents and plain gold."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    documents = raw.get("documents") if isinstance(raw, dict) else None
    gold = raw.get("gold") if isinstance(raw, dict) else None
    if not isinstance(documents, list) or not documents:
        raise ValueError(f"{path}: 'documents' must be a non-empty list")
    if not isinstance(gold, dict):
        raise ValueError(f"{path}: 'gold' must be an object")
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("text"), str):
            raise ValueError(f"{path}: every document needs string 'text': {document!r}")
    return documents, gold


def install_agrochem(store: KGStore) -> None:
    schema = preset("agrochem")
    store.install_schema(
        **{
            key: schema[key]
            for key in ("label", "description", "entity_types", "relation_types")
        }
    )


def checkpoint(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def sweep_size(
    *,
    size: int,
    documents: list[dict[str, Any]],
    gold_path: Path,
    engine: Any,
    output_dir: Path,
    scaffold_tokens: int,
) -> dict[str, Any]:
    store_dir = output_dir / f"chunk-{size}"
    if store_dir.exists():
        shutil.rmtree(store_dir)
    store_dir.mkdir(parents=True)
    store = KGStore.open(store_dir / "kg.sqlite")
    install_agrochem(store)

    doc_ids: list[str] = []
    for index, item in enumerate(documents):
        text = item["text"]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        document, _ = store.insert_document(
            source_kind="fixture",
            source_uri=str(item.get("source_uri") or f"gold://agrochem-mini/{index}"),
            title=str(item.get("title") or item.get("id") or f"document-{index}"),
            raw_text=text,
            content_hash=digest,
        )
        doc_ids.append(document.id)

    calls = 0
    elapsed = 0.0
    prompt_tokens = 0
    payload_tokens = 0
    chunk_counts: list[int] = []
    parse_rejections: list[dict[str, Any]] = []
    model: str | None = None
    started = time.monotonic()
    try:
        schema = store.get_schema()
        for item, doc_id in zip(documents, doc_ids, strict=True):
            chunks = chunk_document(item["text"], target_tokens=size)
            chunk_counts.append(len(chunks))
            for chunk in chunks:
                prompt = build_extraction_prompt(schema, chunk.text)
                prompt_tokens += estimate_tokens(prompt)
                payload_tokens += estimate_tokens(chunk.text)
                try:
                    raw, usage = await engine.generate(prompt, model=None)
                except EngineError as exc:
                    # A failed live call may have consumed quota. Stop instead of
                    # retrying or producing an asymmetric partial store.
                    raise RuntimeError(
                        f"Claude failed at size={size}, document={item.get('id')}, "
                        f"chunk={chunk.index}: {exc}"
                    ) from exc
                calls += int(usage.get("calls") or 1)
                elapsed += float(usage.get("elapsed") or 0.0)
                model = str(usage.get("model")) if usage.get("model") else model
                try:
                    extracted = parse_and_validate_extraction(raw, schema, chunk)
                except EngineError as exc:
                    parse_rejections.append(
                        {"document": item.get("id"), "chunk": chunk.index, "error": str(exc)}
                    )
                    continue
                store.insert_proposed(
                    extracted.entities,
                    extracted.relations,
                    source_doc_id=doc_id,
                    extractor_engine="claude",
                    extractor_model=model,
                    prompt_version=PROMPT_VERSION,
                    decode_params=usage.get("decode_params"),
                )

        gold = load_gold(gold_path)
        report = evaluate_store(
            store,
            gold,
            engine="claude",
            model=model,
            prompt_version=PROMPT_VERSION,
            decode_params=None,
        )
        return {
            "status": "complete",
            "chunk_size": size,
            "documents": len(documents),
            "chunk_counts": chunk_counts,
            "chunks": sum(chunk_counts),
            "engine_calls": calls,
            "engine_elapsed_seconds": round(elapsed, 3),
            "wall_seconds": round(time.monotonic() - started, 3),
            "model": model,
            "estimated_prompt_tokens": prompt_tokens,
            "estimated_payload_tokens": payload_tokens,
            "estimated_scaffold_tokens_per_call": scaffold_tokens,
            "estimated_scaffold_tokens_total": scaffold_tokens * calls,
            "scaffold_share": round(scaffold_tokens / (scaffold_tokens + size), 4),
            "observed_scaffold_share": round(
                (scaffold_tokens * calls) / prompt_tokens, 4
            ),
            "token_note": (
                "4 chars/token heuristic; scaffold_share is nominal at the target "
                "chunk size, observed_scaffold_share uses this fixture's actual prompts; "
                "ClaudeEngine does not expose CLI token usage"
            ),
            "parse_rejections": parse_rejections,
            "report": report.to_dict(),
        }
    finally:
        store.close()


async def run(args: argparse.Namespace) -> int:
    fixture = args.fixture.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    documents, gold_raw = load_wrapper(fixture)
    gold_path = output_dir / "gold.json"
    gold_path.write_text(json.dumps(gold_raw, indent=2) + "\n", encoding="utf-8")

    # This is measured from the exact active schema and prompt builder rather
    # than copied from a planning estimate that can drift as the prompt changes.
    schema = preset("agrochem")
    scaffold_tokens = estimate_tokens(build_extraction_prompt(schema, ""))
    result: dict[str, Any] = {
        "fixture": str(fixture),
        "engine": args.engine,
        "sizes": {},
        "scaffold_tokens_per_call": scaffold_tokens,
        "token_estimator": "len(text) // 4 (minimum 1)",
    }
    result_path = output_dir / "result.json"
    checkpoint(result_path, result)

    engine = get_engine(args.engine, model=None)
    for size in CHUNK_SIZES:
        try:
            measured = await sweep_size(
                size=size,
                documents=documents,
                gold_path=gold_path,
                engine=engine,
                output_dir=output_dir,
                scaffold_tokens=scaffold_tokens,
            )
        except Exception as exc:
            result["sizes"][str(size)] = {"status": "blocked", "error": str(exc)}
            checkpoint(result_path, result)
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 2
        result["sizes"][str(size)] = measured
        checkpoint(result_path, result)
        print(
            f"{size}: {measured['engine_calls']} calls, {measured['chunks']} chunks, "
            f"triple F1={measured['report']['triple']['f1']:.4f}"
        )

    print(f"result: {result_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("claude",), default="claude")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, required=True)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
