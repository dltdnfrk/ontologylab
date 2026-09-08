import re, sys, pathlib
root = pathlib.Path(sys.argv[1]); cited = set(); unresolved = []
pat = re.compile(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.(?:py|js|md|yaml|toml|html)):([0-9]+)")
for f in sys.argv[2:]:
    for m in pat.finditer(pathlib.Path(f).read_text(encoding="utf-8")):
        cited.add((m.group(1), int(m.group(2))))
for path, line in sorted(cited):
    p = root / path
    if not p.is_file(): unresolved.append(f"{path}:{line} MISSING_FILE"); continue
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not (1 <= line <= len(lines)): unresolved.append(f"{path}:{line} BAD_LINE(max {len(lines)})"); continue
    if not lines[line-1].strip(): unresolved.append(f"{path}:{line} BLANK_LINE")
print(f"cited={len(cited)} unresolved={len(unresolved)}")
for u in unresolved: print("UNRESOLVED", u)
ok = len(cited) >= 40 and not unresolved
print(f"CITATIONS_{'OK' if ok else 'FAIL'} unresolved={len(unresolved)}")
sys.exit(0 if ok else 1)
