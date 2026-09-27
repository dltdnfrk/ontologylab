"""Offline annotation QA; never run an extractor or open a product store.

Run from the repository root:
  uv run --all-extras python tests/gold/agrochem-polarity/annotation_audit.py --check
  uv run --all-extras python tests/gold/agrochem-polarity/annotation_audit.py --compare CORPUS
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypedDict

from ontologylab.kgstore_base import normalize_name
from ontologylab.polarity_eval import POLARITIES, validate_gold
from ontologylab.qualified_polarity_eval import qualifiers_cover
from ontologylab.schemas import AGROCHEM_STATEMENT_QUALIFIERS, preset
from ontologylab.statement_qualifiers import canonical_qualifiers, normalize_statement_qualifiers


class Annotation(TypedDict):
    pmcid: str
    src: str
    src_type: str
    relation: str
    dst: str
    dst_type: str
    polarity: str
    quote: str
    qualifiers: dict[str, str]
    qualifier_quotes: dict[str, str]
    rationale: str


class InvalidAnnotation(ValueError):
    """An annotation failed a source or vocabulary boundary."""


def core(row: Annotation) -> tuple[str, str, str, str]:
    """Preserve document boundaries and the production endpoint normalization."""
    return row["pmcid"], normalize_name(row["src"]), row["relation"], normalize_name(row["dst"])


def covers(predicted: Annotation, expected: Annotation, *, polarity: bool = True) -> bool:
    """Use the existing qualified matcher, not a private semantic alias map."""
    return (
        core(predicted) == core(expected)
        and (not polarity or predicted["polarity"] == expected["polarity"])
        and qualifiers_cover(predicted["qualifiers"], expected["qualifiers"])
    )


def matched_pairs(a: list[Annotation], b: list[Annotation]) -> list[tuple[int, int]]:
    """Maximum one-to-one reciprocal-scope matching independent of polarity."""
    edges = [
        [j for j, right in enumerate(b)
         if covers(left, right, polarity=False) and covers(right, left, polarity=False)]
        for left in a
    ]
    # Prefer the same citation without using the outcome label to select a pair.
    for i, candidates in enumerate(edges):
        candidates.sort(key=lambda j: (a[i]["quote"] != b[j]["quote"], j))
    owner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j in edges[i]:
            if j not in seen:
                seen.add(j)
                if j not in owner or augment(owner[j], seen):
                    owner[j] = i
                    return True
        return False

    for i in range(len(a)):
        augment(i, set())
    return sorted((i, j) for j, i in owner.items())


def agreement(a: list[Annotation], b: list[Annotation]) -> dict:
    """Report both production subset directions and transparent kappa margins."""
    raw_counts = len(a), len(b)
    kept = []
    for rows in (a, b):
        seen = set()
        indexes = []
        for index, row in enumerate(rows):
            identity = (*core(row), row["polarity"],
                        canonical_qualifiers(normalize_statement_qualifiers(row["qualifiers"])))
            if identity not in seen:
                seen.add(identity)
                indexes.append(index)
        kept.append(indexes)
    a = [a[i] for i in kept[0]]
    b = [b[i] for i in kept[1]]
    pairs = matched_pairs(a, b)
    matrix = {p: dict.fromkeys(POLARITIES, 0) for p in POLARITIES}
    for i, j in pairs:
        matrix[a[i]["polarity"]][b[j]["polarity"]] += 1
    n = len(pairs)
    equal = sum(matrix[p][p] for p in POLARITIES)
    left = {p: sum(matrix[p].values()) for p in POLARITIES}
    right = {p: sum(matrix[q][p] for q in POLARITIES) for p in POLARITIES}
    observed = equal / n if n else None
    expected = sum(left[p] * right[p] for p in POLARITIES) / n**2 if n else None
    kappa = ((observed - expected) / (1 - expected)
             if observed is not None and expected is not None and expected < 1 else None)
    a_hits = sum(any(covers(pred, gold) for pred in b) for gold in a)
    b_hits = sum(any(covers(pred, gold) for pred in a) for gold in b)
    return {
        "a_annotation_rows": raw_counts[0], "b_annotation_rows": raw_counts[1],
        "a_statements": len(a), "b_statements": len(b),
        "b_matches_a": {"matched": a_hits, "total": len(a),
                        "rate": a_hits / len(a) if a else None},
        "a_matches_b": {"matched": b_hits, "total": len(b),
                        "rate": b_hits / len(b) if b else None},
        "reciprocal_scope_pairs": n,
        "reciprocal_statement_match_rate": 2 * equal / (len(a) + len(b)) if a or b else None,
        "unmatched_a": len(a) - n, "unmatched_b": len(b) - n,
        "polarity_disagreements": n - equal,
        "kappa": kappa, "observed_polarity_agreement": observed,
        "expected_polarity_agreement": expected,
        "marginal_a": left, "marginal_b": right, "confusion_matrix": matrix,
        "pairs": [[kept[0][i], kept[1][j]] for i, j in pairs],
        "limitation": "Fresh model contexts, not independent humans; selection and within-paper dependence remain.",
    }


def bind_annotation(row: Annotation, text: str) -> dict:
    """Bind literal source and qualifier quotes to character and UTF-8 spans."""
    quote = row["quote"]
    if not quote or quote not in text:
        raise InvalidAnnotation(f"{row['pmcid']}: quote must occur literally")
    claim_names = {
        item["name"] for item in preset("agrochem-v2")["relation_types"]
        if "polarity" in item["qualifiers"]
    }
    entity_names = {item["name"] for item in preset("agrochem-v2")["entity_types"]}
    if row["relation"] not in claim_names or row["polarity"] not in POLARITIES:
        raise InvalidAnnotation("invalid relation or polarity")
    if row["src_type"] not in entity_names or row["dst_type"] not in entity_names:
        raise InvalidAnnotation("invalid entity type")
    if set(row["qualifiers"]) != set(row["qualifier_quotes"]):
        raise InvalidAnnotation("each qualifier needs its own literal quote")
    for key, value in row["qualifiers"].items():
        raw = row["qualifier_quotes"][key]
        if key not in AGROCHEM_STATEMENT_QUALIFIERS:
            raise InvalidAnnotation(f"unknown qualifier: {key}")
        if not isinstance(value, str) or not value.strip() or not raw or raw not in quote:
            raise InvalidAnnotation(f"unbound qualifier: {key}")
        if normalize_statement_qualifiers({key: value}) != normalize_statement_qualifiers({key: raw}):
            raise InvalidAnnotation(f"qualifier changes its source value: {key}")
    lo = text.index(quote)
    start = len(text[:lo].encode("utf-8"))
    return {
        **{key: row[key] for key in ("pmcid", "src", "src_type", "relation", "dst", "dst_type", "polarity")},
        "context": row["rationale"],
        "qualifiers": dict(row["qualifiers"]), "qualifier_quotes": dict(row["qualifier_quotes"]),
        "span": {"start": start, "end": start + len(quote.encode("utf-8")), "quote": quote},
        "char_start": lo, "char_end": lo + len(quote),
        "quote_occurrences": text.count(quote),
    }


def read_annotations(directory: Path, name: str) -> list[Annotation]:
    """Read and validate a recorded annotation without consulting other labels."""
    raw = json.loads((directory / "annotations" / name).read_text(encoding="utf-8"))
    rows = raw["relations"]
    texts = {
        row["pmcid"]: (directory / "sources/full" / f"{row['pmcid']}.txt").read_text(encoding="utf-8")
        for row in rows
    }
    for row in rows:
        bind_annotation(row, texts[row["pmcid"]])
    return rows


def disagreements(a: list[Annotation], b: list[Annotation]) -> list[dict]:
    """Group disagreements by published sentence; never expose reference gold."""
    groups: dict[tuple[str, str], dict] = {}
    for side, rows in (("a", a), ("b", b)):
        for index, row in enumerate(rows):
            group = groups.setdefault((row["pmcid"], row["quote"]), {
                "pmcid": row["pmcid"], "quote": row["quote"], "a": [], "b": [],
            })
            group[side].append({"index": index, "annotation": row})
    result = []
    for group in groups.values():
        left = [item["annotation"] for item in group["a"]]
        right = [item["annotation"] for item in group["b"]]
        pairs = matched_pairs(left, right)
        if (len(pairs) != len(left) or len(pairs) != len(right)
                or any(left[i]["polarity"] != right[j]["polarity"] for i, j in pairs)):
            result.append({"id": f"D{len(result) + 1:03d}", **group})
    return result


def compare(directory: Path) -> dict:
    """Compute the complete pre-adjudication receipt from recorded raw labels."""
    a = read_annotations(directory, "annotator-a.json")
    b = read_annotations(directory, "annotator-b.json")
    return {"agreement": agreement(a, b), "disagreements": disagreements(a, b)}


def adjudication_packets(directory: Path) -> list[dict]:
    """Add reference-conflicting consensus spans without disclosing reference labels."""
    a = read_annotations(directory, "annotator-a.json")
    b = read_annotations(directory, "annotator-b.json")
    packets = disagreements(a, b)
    reference = directory / "gold-aligned-qualified.json"
    if not reference.exists():
        return packets
    known = {(p["pmcid"], p["quote"]) for p in packets}
    number = 0
    for row in json.loads(reference.read_text())["relations"]:
        key = row["pmcid"], row["span"]["quote"]
        if key in known:
            continue
        left = [{"index": i, "annotation": x} for i, x in enumerate(a)
                if (x["pmcid"], x["quote"]) == key]
        right = [{"index": i, "annotation": x} for i, x in enumerate(b)
                 if (x["pmcid"], x["quote"]) == key]
        candidates = [x["annotation"] for x in left + right if core(x["annotation"]) == core(row)]
        if candidates and not any(covers(x, row) and covers(row, x) for x in candidates):
            number += 1
            packets.append({"id": f"G{number:03d}", "pmcid": key[0], "quote": key[1],
                            "a": left, "b": right})
            known.add(key)
    return packets


def accepted_annotations(directory: Path) -> list[dict]:
    """Apply only explicit adjudication choices; retain each choice's provenance."""
    sides = {side: read_annotations(directory, f"annotator-{side}.json") for side in ("a", "b")}
    packets = {p["id"]: p for p in adjudication_packets(directory)}
    decisions = json.loads((directory / "annotations/adjudication.json").read_text())["decisions"]
    if {d["id"] for d in decisions} != set(packets) or len(decisions) != len(packets):
        raise InvalidAnnotation("adjudication must cover every disagreement exactly once")
    disputed_a = {item["index"] for packet in packets.values() for item in packet["a"]}
    accepted = [
        {"annotation": row, "provenance": {"kind": "blind_consensus", "a_index": i}}
        for i, row in enumerate(sides["a"]) if i not in disputed_a
    ]
    for decision in decisions:
        packet = packets[decision["id"]]
        if not decision["rationale"].strip():
            raise InvalidAnnotation("adjudication needs rationale")
        permitted = {(side, item["index"]) for side in ("a", "b") for item in packet[side]}
        for choice in decision["accepted"]:
            identity = choice["side"], choice["index"]
            if identity not in permitted:
                raise InvalidAnnotation("adjudicator selected an unrelated annotation")
            accepted.append({
                "annotation": sides[choice["side"]][choice["index"]],
                "provenance": {"kind": "adjudicated", "decision": decision["id"], **choice},
            })
        for row in decision.get("corrected", []):
            if row["pmcid"] != packet["pmcid"] or row["quote"] != packet["quote"]:
                raise InvalidAnnotation("adjudicator changed the published assertion span")
            text = (directory / "sources/full" / f"{row['pmcid']}.txt").read_text()
            bind_annotation(row, text)
            accepted.append({
                "annotation": row,
                "provenance": {"kind": "adjudicated_correction", "decision": decision["id"]},
            })
    return accepted


def silver_bundle(directory: Path) -> dict:
    """Build source-valued/canonical fixtures without writing or inventing scope."""
    manifest = json.loads((directory / "sources/full/manifest.json").read_text())
    texts = {p["pmcid"]: (directory / p["source"]).read_text() for p in manifest["papers"]}
    rows = []
    provenance = []
    duplicates = []
    seen: dict[tuple, int] = {}
    for accepted in accepted_annotations(directory):
        annotation = accepted["annotation"]
        row = bind_annotation(annotation, texts[annotation["pmcid"]])
        identity = (*core(annotation)[1:], row["polarity"],
                    canonical_qualifiers(normalize_statement_qualifiers(row["qualifiers"])))
        if identity in seen:
            duplicates.append({"retained_row": seen[identity], **accepted})
        else:
            seen[identity] = len(rows)
            provenance.append(accepted["provenance"])
            rows.append(row)
    if {row["pmcid"] for row in rows} != set(texts):
        raise InvalidAnnotation("every included silver paper needs a retained assertion")
    base = {
        "schema": "agrochem-v2", "format_version": 2,
        "silver": "model-annotated, not human ground truth",
        "annotation_version": "published-silver-v1",
        "offset_convention": "span.start/end: zero-based half-open UTF-8 bytes; char_start/end: Unicode characters.",
        "papers": manifest["papers"],
    }
    return {
        "gold-silver.json": {**base, "relations": rows},
        "gold-silver-qualified.json": {
            **base, "statement_model": "biolink-qualified-v1",
            "relations": [{**row, "qualifiers": normalize_statement_qualifiers(row["qualifiers"])}
                          for row in rows],
        },
        "build-receipt.json": {"row_provenance": provenance, "deduplicated_evidence": duplicates},
    }


def reference_coverage(directory: Path) -> int:
    """Require source-bound, independently reviewed dispositions for every row."""
    reference = json.loads((directory / "gold-aligned.json").read_text())["relations"]
    record = json.loads((directory / "annotations/reference-review.json").read_text())
    rows = record["rows"]
    if [row["source_row"] for row in rows] != list(range(len(reference))):
        raise InvalidAnnotation("reference review must cover every row exactly once")
    adjudication_inputs = {
        item["id"]: item for item in json.loads(
            (directory / "annotations/reference-adjudication-inputs.json").read_text()
        )["packets"]
    }
    decisions = json.loads(
        (directory / "annotations/reference-adjudication.json").read_text()
    )["decisions"]
    if (len(decisions) != len(adjudication_inputs)
            or {item["id"] for item in decisions} != set(adjudication_inputs)):
        raise InvalidAnnotation("reference adjudication must cover every packet exactly once")
    changes = {
        item["source_row"]: item for item in json.loads(
            (directory / "gold-change-record.json").read_text()
        )["changes"]
    }
    inputs = {
        item["id"]: item for item in json.loads(
            (directory / "annotations/reference-inputs.json").read_text()
        )["packets"]
    }
    for review, original in zip(rows, reference, strict=True):
        quote = original["span"]["quote"]
        text = (directory / "sources/full" / f"{original['pmcid']}.txt").read_text()
        if review["disposition"] not in {"reviewed_two_annotators", "reviewed_adjudicated"}:
            raise InvalidAnnotation(f"reference row {review['source_row'] + 1}: not reviewed")
        if (review["pmcid"] != original["pmcid"]
                or review["span"] != {k: original["span"][k] for k in ("start", "end")}
                or text[review["char_start"]:review["char_end"]] != quote
                or text.encode()[review["span"]["start"]:review["span"]["end"]] != quote.encode()
                or not review["citation"] or review["citation"] not in quote
                or review["citation"] not in review["rationale"]):
            raise InvalidAnnotation("reference disposition needs its exact asserting span")
        refs = review["reviews"]
        sides = {item["annotator"] for item in refs}
        two_reviews = len(refs) == 2 and sides == {"a", "b"}
        adjudicated_single = (
            review["disposition"] == "reviewed_adjudicated"
            and len(refs) == 1 and sides <= {"a", "b"}
        )
        if not (two_reviews or adjudicated_single):
            raise InvalidAnnotation("reference row needs independent reviews or adjudication")
        for ref in refs:
            side = ref["annotator"]
            if ref["file"] not in {f"annotator-{side}.json", f"reference-annotator-{side}.json"}:
                raise InvalidAnnotation("reference review points outside its blinded lane")
            submission = json.loads((directory / "annotations" / ref["file"]).read_text())
            if "packet_id" in ref:
                packet = inputs[ref["packet_id"]]
                if (packet["pmcid"] != original["pmcid"] or packet["span"] != review["span"]
                        or packet["quote_sha256"] != hashlib.sha256(quote.encode()).hexdigest()):
                    raise InvalidAnnotation("reference annotation belongs to another assertion")
                matches = [item for item in submission["reviews"] if item["id"] == packet["id"]]
                if len(matches) != 1:
                    raise InvalidAnnotation("reference packet needs exactly one submitted review")
                submitted = matches[0]
                annotations = [
                    {**item, "pmcid": original["pmcid"], "quote": quote,
                     "rationale": submitted["rationale"]}
                    for item in submitted["statements"]
                ]
            else:
                annotations = submission["relations"]
            if not ref["indices"] or len(set(ref["indices"])) != len(ref["indices"]):
                raise InvalidAnnotation("reference review needs explicit annotation arms")
            for index in ref["indices"]:
                annotation = annotations[index]
                if (annotation["pmcid"] != original["pmcid"]
                        or not (quote in annotation["quote"] or annotation["quote"] in quote)):
                    raise InvalidAnnotation("reference arm does not cite the asserting sentence")
                bind_annotation(annotation, text)
        if review["disposition"] == "reviewed_adjudicated":
            decision_ref = review["adjudication"]
            if decision_ref["file"] not in {"adjudication.json", "reference-adjudication.json"}:
                raise InvalidAnnotation("unknown reference adjudication record")
            if decision_ref["file"] == "reference-adjudication.json":
                packet = adjudication_inputs.get(decision_ref["id"])
                if (packet is None or packet["pmcid"] != original["pmcid"]
                        or packet["span"] != review["span"]
                        or packet["quote_sha256"] != hashlib.sha256(quote.encode()).hexdigest()):
                    raise InvalidAnnotation("reference adjudication belongs to another assertion")
            else:
                packets = {item["id"]: item for item in adjudication_packets(directory)}
                packet = packets.get(decision_ref["id"])
                if (packet is None or packet["pmcid"] != original["pmcid"]
                        or not (quote in packet["quote"] or packet["quote"] in quote)):
                    raise InvalidAnnotation("existing adjudication belongs to another assertion")
            decisions = json.loads(
                (directory / "annotations" / decision_ref["file"]).read_text()
            )["decisions"]
            matching = [item for item in decisions if item["id"] == decision_ref["id"]]
            if len(matching) != 1 or not matching[0]["rationale"].strip():
                raise InvalidAnnotation("reference adjudication needs a recorded decision")
            selection = review["adjudicated_selection"]
            decision = matching[0]
            if selection["kind"] == "rejected":
                change = changes.get(review["source_row"])
                if change is not None and (
                    change.get("applied", True) or change["review_rationale"] != decision["rationale"]
                ):
                    raise InvalidAnnotation("rejected reference row cannot change the gold")
                if decision_ref["id"].startswith("E") and (
                    decision["accepted"] or decision["corrected"]
                ):
                    raise InvalidAnnotation("rejected reference packet contains accepted arms")
            elif decision_ref["id"].startswith("E"):
                if selection["index"] >= len(decision[selection["kind"]]):
                    raise InvalidAnnotation("reference row selects a missing adjudicated arm")
                selected = decision[selection["kind"]][selection["index"]]
                if selection["kind"] == "corrected":
                    change = changes.get(review["source_row"])
                    if (change is None or change["decision"] != decision_ref["id"]
                            or change["selection"] != selection
                            or change.get("applied", True) is False
                            or selected["polarity"] != change["annotation"]["annotation"]["polarity"]):
                        raise InvalidAnnotation("corrected reference row lacks its recorded change")
                elif not any(
                    ref["annotator"] == selected["side"]
                    and selected["index"] in ref["indices"] for ref in refs
                ):
                    raise InvalidAnnotation("adjudicated arm is not linked to its blind review")
    return len(rows)


def reference_annotations(directory: Path, side: str) -> list[Annotation]:
    """Rehydrate blinded labels from their existing source-coordinate packets."""
    inputs = {
        item["id"]: item for item in json.loads(
            (directory / "annotations/reference-inputs.json").read_text()
        )["packets"]
    }
    submission = json.loads(
        (directory / f"annotations/reference-annotator-{side}.json").read_text()
    )
    blinding = json.loads((directory / "annotations/reference-blinding.json").read_text())
    allowed = {str(Path(blinding["work_root"]) / name) for name in blinding["inputs"]}
    if set(submission["files_read"]) != allowed:
        raise InvalidAnnotation("targeted annotator read outside the blinded input contract")
    if sorted(item["id"] for item in submission["reviews"]) != sorted(inputs):
        raise InvalidAnnotation("every targeted assertion needs one independent review")
    rows: list[Annotation] = []
    for review in submission["reviews"]:
        if (not review["statements"]
                or review["granularity"] != ("one" if len(review["statements"]) == 1 else "several")):
            raise InvalidAnnotation("targeted review must identify its statement granularity")
        packet = inputs[review["id"]]
        text = (directory / packet["source"]).read_text()
        quote = text[packet["char_start"]:packet["char_end"]]
        if (hashlib.sha256(quote.encode()).hexdigest() != packet["quote_sha256"]
                or text.encode()[packet["span"]["start"]:packet["span"]["end"]] != quote.encode()
                or not review["citation"] or review["citation"] not in quote):
            raise InvalidAnnotation("targeted review needs its literal source citation")
        for statement in review["statements"]:
            annotation: Annotation = {
                "src": statement["src"], "src_type": statement["src_type"],
                "relation": statement["relation"],
                "dst": statement["dst"], "dst_type": statement["dst_type"],
                "polarity": statement["polarity"], "qualifiers": statement["qualifiers"],
                "qualifier_quotes": statement["qualifier_quotes"],
                "pmcid": packet["pmcid"], "quote": quote,
                "rationale": review["rationale"],
            }
            bind_annotation(annotation, text)
            rows.append(annotation)
    return rows


def check() -> dict:
    """Verify committed receipts and both new fixture loader surfaces."""
    gold = Path(__file__).resolve().parent
    silver = gold.with_name("agrochem-polarity-silver")
    result = {}
    for directory in (gold, silver):
        recorded = json.loads((directory / "annotations/agreement.json").read_text())
        calculated = compare(directory)
        if recorded != calculated:
            raise InvalidAnnotation(f"{directory.name}: stale agreement receipt")
        decisions = json.loads((directory / "annotations/adjudication.json").read_text())["decisions"]
        packets = adjudication_packets(directory)
        if json.loads((directory / "annotations/disagreements.json").read_text()) != {"disagreements": packets}:
            raise InvalidAnnotation("adjudication packet differs from its blind inputs")
        expected_ids = {item["id"] for item in packets}
        if {item["id"] for item in decisions} != expected_ids or len(decisions) != len(expected_ids):
            raise InvalidAnnotation("adjudication must cover every disagreement exactly once")
        if any(not item["rationale"].strip() for item in decisions):
            raise InvalidAnnotation("adjudication needs rationale")
        result[directory.name] = {
            "agreement": calculated["agreement"],
            "disagreement_sentences": len(expected_ids),
        }
    for path in (silver / "gold-silver.json", silver / "gold-silver-qualified.json"):
        raw = json.loads(path.read_text())
        if raw.get("silver") != "model-annotated, not human ground truth":
            raise InvalidAnnotation("silver must disclose its provenance")
        result[path.name] = validate_gold(path, qualified=True)
    for filename, expected in silver_bundle(silver).items():
        if json.loads((silver / filename).read_text()) != expected:
            raise InvalidAnnotation(f"fixture is not the adjudicated derivation: {filename}")
    for filename, digest in json.loads((gold / "annotations/frozen-inputs.json").read_text()).items():
        if hashlib.sha256((gold / filename).read_bytes()).hexdigest() != digest:
            raise InvalidAnnotation(f"historical input changed: {filename}")
    reviewed = reference_coverage(gold)
    inputs = json.loads((gold / "annotations/reference-inputs.json").read_text())
    targeted = {
        "design": "targeted_reference_review",
        "reference_rows": len(inputs["previously_uncovered_rows"]),
        "distinct_asserting_sentences": len(inputs["packets"]),
        "agreement": agreement(reference_annotations(gold, "a"), reference_annotations(gold, "b")),
    }
    if json.loads((gold / "annotations/reference-agreement.json").read_text()) != targeted:
        raise InvalidAnnotation("targeted reference agreement must be separate and reproducible")
    result["reference_review"] = {"rows_reviewed": reviewed, "agreement": targeted}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    result = check() if args.check else (
        silver_bundle(args.bundle) if args.bundle else compare(args.compare)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
