"""One-off design-review inventory: static import graph over ontologylab/."""
import ast, json, sys, pathlib
ROOT = pathlib.Path(sys.argv[1]); PKG = ROOT / "ontologylab"
files = sorted(list(PKG.glob("*.py")) + list((PKG/"connectors").glob("*.py")) + list((PKG/"server").glob("*.py")))
def modname(p):  # ontologylab/server/app.py -> ontologylab.server.app
    rel = p.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__": parts = parts[:-1]
    return ".".join(parts)
names = {modname(p): p for p in files}
def resolve(base_pkg, node):
    out = set()
    if isinstance(node, ast.Import):
        for a in node.names:
            if a.name.startswith("ontologylab"):
                out.add(a.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            base = base_pkg.split(".")
            base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
            mod = ".".join(base + ([node.module] if node.module else []))
        else:
            mod = node.module or ""
        if not mod.startswith("ontologylab"): return out
        if mod in names: out.add(mod)
        for a in node.names:
            cand = f"{mod}.{a.name}"
            if cand in names: out.add(cand)
        if mod not in names and not any(f"{mod}.{a.name}" in names for a in node.names):
            # package import like `from ontologylab import x` where x is a name in __init__
            if mod in names: out.add(mod)
    return out
edges = {}
loc = {}
for m, p in names.items():
    src = p.read_text(encoding="utf-8")
    loc[m] = src.count("\n") + (0 if src.endswith("\n") or not src else 1)
    tree = ast.parse(src)
    pkg = m if p.name == "__init__.py" else m.rsplit(".", 1)[0]
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            deps |= resolve(pkg, node)
    deps.discard(m)
    edges[m] = sorted(d for d in deps if d in names)
fan_in = {m: 0 for m in names}
for m, ds in edges.items():
    for d in ds: fan_in[d] += 1
entry = {"main": "ontologylab.main", "server": "ontologylab.server.app", "mcp": "ontologylab.mcp_server"}
reach = {}
for k, e in entry.items():
    seen, stack = set(), [e]
    while stack:
        x = stack.pop()
        if x in seen: continue
        seen.add(x); stack.extend(edges.get(x, []))
    reach[k] = seen
modules = []
for m, p in names.items():
    eps = sorted(k for k, s in reach.items() if m in s)
    modules.append({"module": m, "path": str(p.relative_to(ROOT)), "loc": loc[m],
                    "fan_in": fan_in[m], "fan_out": len(edges[m]), "imports": edges[m], "entrypoints": eps})
unreachable = sorted(m["module"] for m in modules if not m["entrypoints"])
json.dump({"root": str(ROOT), "entrypoints": entry, "closure_sizes": {k: len(v) for k, v in reach.items()},
           "modules": modules, "unreachable": unreachable}, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
print("modules", len(modules), "loc_sum", sum(loc.values()), "unreachable", len(unreachable), "closures", {k: len(v) for k, v in reach.items()})
