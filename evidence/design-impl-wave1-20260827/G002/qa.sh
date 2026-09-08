#!/bin/bash
# G002 manual QA: SC1 CLI engine default None, SC2 explicit mock works, SC3 HTTP extract default, SC4 no UI/settings mock fallback
set -u
cd "$(dirname "$0")/../../.."
E=evidence/design-impl-wave1-20260827; H=$E/qa-server.sh; PY=.venv/bin/python
fail=0
{ # SC1
$PY -P -m ontologylab.main critic --help | sed -n '/--engine/,+2p'
$PY -P - <<'PY'
from ontologylab.main import build_arg_parser
p = build_arg_parser()
vals = {n: p.parse_args(a).engine for n, a in {"critic": ["critic"], "extract": ["extract"], "search": ["search", "q"]}.items()}
print(vals)
print("G002-SC1 OK" if all(v is None for v in vals.values()) else "G002-SC1 FAIL")
PY
} 2>&1 | tee $E/G002/sc1-cli-defaults.txt; grep -q 'G002-SC1 OK' $E/G002/sc1-cli-defaults.txt || fail=1
{ # SC2
DATA=$(mktemp -d /tmp/ol-w1-g2sc2-XXXXXX); FIX=$(mktemp -d /tmp/ol-w1-g2fix-XXXXXX)
printf '%s\n' "OrderApp talks to KitchenDisplay and PaymentGateway." > "$FIX/s.md"
$PY -P -m ontologylab.main collect --file "$FIX/s.md" --data-dir "$DATA"; echo "collect_exit=$?"
$PY -P -m ontologylab.main extract --engine mock --data-dir "$DATA"; echo "extract_exit=$?"
$PY -P - "$DATA" <<'PY'
import sys; from pathlib import Path
from ontologylab.kgstore import KGStore; from ontologylab.paths import kg_db_path
s = KGStore.open(kg_db_path(Path(sys.argv[1])), read_only=True)
names = {r[0] for r in s.conn.execute("SELECT name FROM nodes")}
print("nodes=", sorted(names))
print("G002-SC2 OK" if {"OrderApp", "KitchenDisplay", "PaymentGateway"} <= names else "G002-SC2 FAIL")
s.close()
PY
rm -rf "$DATA" "$FIX"; echo "cleanup: rm -rf $DATA $FIX"
} 2>&1 | tee $E/G002/sc2-explicit-mock.txt; grep -q 'G002-SC2 OK' $E/G002/sc2-explicit-mock.txt || fail=1
{ # SC3 + SC4 (HTTP)
$H start || exit 1; TOK=$($H token); U=$($H url)
echo "--- SC3 POST /api/extract default engine"
curl -si -H "X-OntologyLab-Session: $TOK" -H "Content-Type: application/json" -d '{}' "$U/api/extract" | tee /tmp/ol-w1-g2sc3.txt | head -1
JOB=$(grep -o -E '"job_id": ?"[^"]+"' /tmp/ol-w1-g2sc3.txt | head -1 | sed -E 's/.*: ?"//; s/"$//')
ENG=$(curl -s -H "X-OntologyLab-Session: $TOK" "$U/api/jobs" | jq -r --arg j "$JOB" '.jobs[]|select(.job_id==$j)|.engine')
echo "job_id=$JOB engine=$ENG"
grep -q 'HTTP/1.1 202' /tmp/ol-w1-g2sc3.txt && [ "$ENG" = "claude" ] && echo "G002-SC3 OK" || echo "G002-SC3 FAIL"
} 2>&1 | tee $E/G002/sc3-http-extract-default.txt; grep -q 'G002-SC3 OK' $E/G002/sc3-http-extract-default.txt || fail=1
{
TOK=$($H token); U=$($H url)
echo "--- SC4 /api/engines order + dashboard tokens"
curl -s -H "X-OntologyLab-Session: $TOK" "$U/api/engines" | tee /tmp/ol-w1-g2sc4.txt | jq -c '[.[]?|.name]'
first=$(jq -r '.[0].name' /tmp/ol-w1-g2sc4.txt)
grep -n -E '\|\| *"mock"|value=.mock' web/app.js; rg_exit=$?
echo "first_engine=$first rg_exit=$rg_exit"
[ "$first" != "mock" ] && [ "$rg_exit" = 1 ] && echo "G002-SC4 OK" || echo "G002-SC4 FAIL"
$H stop; rm -f /tmp/ol-w1-g2sc3.txt /tmp/ol-w1-g2sc4.txt
} 2>&1 | tee $E/G002/sc4-no-ui-mock-fallback.txt; grep -q 'G002-SC4 OK' $E/G002/sc4-no-ui-mock-fallback.txt || fail=1
echo "G002_QA_$([ $fail = 0 ] && echo PASS || echo FAIL)"
