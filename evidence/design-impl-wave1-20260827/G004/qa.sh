#!/bin/bash
# G004 manual QA: SC1 CLI+HTTP share collect, SC2 CLI offline/unreadable typed, SC3 stage functions via CLI, SC4 CLI never calls the route handler
set -u
cd "$(dirname "$0")/../../.."
E=evidence/design-impl-wave1-20260827; H=$E/qa-server.sh; PY=.venv/bin/python
fail=0
{ # SC1
DATA=$(mktemp -d /tmp/ol-w1-g4sc1-XXXXXX); FIX=$(mktemp -d /tmp/ol-w1-g4fix-XXXXXX)
printf '%s\n' "The RateLimiter implements the TokenBucketAlgorithm." > "$FIX/n.md"
$PY -P -m ontologylab.main collect --file "$FIX/n.md" --data-dir "$DATA"; echo "cli_exit=$?"
$H start "$DATA" || exit 1; TOK=$($H token); U=$($H url)
curl -si -H "X-OntologyLab-Session: $TOK" -H "Content-Type: application/json" -d "{\"files\":[\"$FIX/n.md\"]}" "$U/api/collect" | tee /tmp/ol-w1-g4sc1.txt | tail -1; echo
grep -q 'HTTP/1.1 200' /tmp/ol-w1-g4sc1.txt && grep -q -E '"created": ?0' /tmp/ol-w1-g4sc1.txt && grep -q -E '"duplicates": ?1' /tmp/ol-w1-g4sc1.txt && echo "G004-SC1 OK" || echo "G004-SC1 FAIL"
$H stop; rm -rf "$FIX" /tmp/ol-w1-g4sc1.txt; echo "cleanup: rm -rf $FIX"
} 2>&1 | tee $E/G004/sc1-shared-collect.txt; grep -q 'G004-SC1 OK' $E/G004/sc1-shared-collect.txt || fail=1
{ # SC2
DATA=$(mktemp -d /tmp/ol-w1-g4sc2-XXXXXX)
ONTOLOGYLAB_OFFLINE=1 $PY -P -m ontologylab.main collect --url https://example.com/ --data-dir "$DATA" 2>/tmp/ol-w1-g4sc2.err; code=$?; echo "offline_exit=$code"; cat /tmp/ol-w1-g4sc2.err | head -3
$PY -P -m ontologylab.main collect --file /no/such/dir/missing.md --data-dir "$DATA" 2>/tmp/ol-w1-g4sc2b.err; code2=$?; echo "unreadable_exit=$code2"; head -3 /tmp/ol-w1-g4sc2b.err
[ "$code" = 2 ] && grep -q -i -E 'offline|rejected' /tmp/ol-w1-g4sc2.err && ! grep -q Traceback /tmp/ol-w1-g4sc2.err && [ "$code2" = 2 ] && ! grep -q Traceback /tmp/ol-w1-g4sc2b.err && echo "G004-SC2 OK" || echo "G004-SC2 FAIL"
rm -rf "$DATA" /tmp/ol-w1-g4sc2.err /tmp/ol-w1-g4sc2b.err; echo "cleanup: rm -rf $DATA"
} 2>&1 | tee $E/G004/sc2-cli-offline.txt; grep -q 'G004-SC2 OK' $E/G004/sc2-cli-offline.txt || fail=1
{ # SC3
DATA=$(mktemp -d /tmp/ol-w1-g4sc3-XXXXXX)
$PY -P -m ontologylab.main merge-scan --data-dir "$DATA" | tee /tmp/ol-w1-g4sc3a.txt | tail -2; a=${PIPESTATUS[0]}
$PY -P -m ontologylab.main critic --engine mock --data-dir "$DATA" | tee /tmp/ol-w1-g4sc3b.txt | tail -2; b=${PIPESTATUS[0]}
echo "merge_exit=$a critic_exit=$b"
[ "$a" = 0 ] && [ "$b" = 0 ] && grep -q -i 'scanned' /tmp/ol-w1-g4sc3a.txt && grep -q -i 'scored' /tmp/ol-w1-g4sc3b.txt && echo "G004-SC3 OK" || echo "G004-SC3 FAIL"
rm -rf "$DATA" /tmp/ol-w1-g4sc3a.txt /tmp/ol-w1-g4sc3b.txt; echo "cleanup: rm -rf $DATA"
} 2>&1 | tee $E/G004/sc3-stage-functions.txt; grep -q 'G004-SC3 OK' $E/G004/sc3-stage-functions.txt || fail=1
{ # SC4
rg -n 'routes\.collect|from ontologylab\.server' ontologylab/main.py; r=$?
rg -n 'check_url\(|check_collect_file\(' ontologylab/main.py ontologylab/server/routes.py; g=$?
echo "route_call_rg_exit=$r gate_inline_rg_exit=$g"
[ "$r" = 1 ] && [ "$g" = 1 ] && echo "G004-SC4 OK" || echo "G004-SC4 FAIL"
} 2>&1 | tee $E/G004/sc4-no-route-call.txt; grep -q 'G004-SC4 OK' $E/G004/sc4-no-route-call.txt || fail=1
echo "G004_QA_$([ $fail = 0 ] && echo PASS || echo FAIL)"
