import json, pathlib, re, sys

ROOT = pathlib.Path(sys.argv[1])
E = ROOT / "evidence" / "design-review-20260826"
VOCAB = ["source", "acquire", "normalize", "resolve", "extract", "synthesize",
         "verify", "publish", "consume", "infra", "cross_cutting", "orphan"]
REF = re.compile(r"^(ontologylab/[\w/]+\.py):(\d+)$")


def norm(stage: str) -> str:
    s = stage.strip().lower().replace("-", "_").replace(" ", "_")
    if s not in VOCAB:
        raise SystemExit(f"invalid stage {stage!r}")
    return s


inv = json.loads((E / "inventory.json").read_text())
inv_key = "module" if "module" in inv["modules"][0] else "name"
inv_names = {m[inv_key] for m in inv["modules"]}
unreachable = set(inv.get("unreachable", []))

modules, seen, lanes = [], set(), []
for lane_file in sorted((E / "stage-lanes").glob("L*.json")):
    lane = json.loads(lane_file.read_text())
    lanes.append(lane_file.name)
    for m in lane["modules"]:
        name = m.get("name") or m.get("module")
        if name in seen:
            raise SystemExit(f"duplicate module {name}")
        seen.add(name)
        primary = norm(m["stage"])
        secondary = [norm(s["stage"]) for s in m.get("secondary_stages", [])]
        stages = [primary] + [s for s in secondary if s != primary]
        evidence = [m["evidence"]] + [s["evidence"] for s in m.get("secondary_stages", [])]
        modules.append({
            "module": name,
            "stage": primary,
            "stages": stages,
            "multi_stage": len(stages) >= 2,
            "primary_evidence": m["evidence"],
            "evidence": evidence,
            "rationale": m.get("rationale", ""),
            "secondary_stages": m.get("secondary_stages", []),
            "overlaps": m.get("overlaps", []),
            "hidden_fallbacks": m.get("hidden_fallbacks", []),
            "engine_slot": m.get("engine_slot"),
            "unreachable": name in unreachable,
            "lane": lane_file.stem,
        })

missing = inv_names - seen
extra = seen - inv_names
if missing or extra:
    raise SystemExit(f"coverage mismatch missing={sorted(missing)} extra={sorted(extra)}")

by_stage = {s: {"stage": s, "count": 0, "modules": []} for s in VOCAB}
for m in modules:
    by_stage[m["stage"]]["count"] += 1
    by_stage[m["stage"]]["modules"].append(m["module"])

out = {
    "generated_from": lanes,
    "head": "7f94879",
    "stage_vocab": VOCAB,
    "modules": sorted(modules, key=lambda m: m["module"]),
    "by_stage": [by_stage[s] for s in VOCAB],
    "multi_stage": sorted(m["module"] for m in modules if m["multi_stage"]),
    "unreachable": sorted(unreachable),
    "engine_slots": [
        {"module": m["module"], "stage": m["stage"], **m["engine_slot"]}
        for m in sorted(modules, key=lambda m: m["module"]) if m["engine_slot"]
    ],
    "hidden_fallbacks": [
        {"module": m["module"], "stage": m["stage"], **fb}
        for m in sorted(modules, key=lambda m: m["module"]) for fb in m["hidden_fallbacks"]
    ],
}
(E / "stage-map.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
print(f"modules={len(modules)} multi_stage={len(out['multi_stage'])} "
      f"engine_slots={len(out['engine_slots'])} fallbacks={len(out['hidden_fallbacks'])} "
      f"unreachable={len(unreachable)}")
