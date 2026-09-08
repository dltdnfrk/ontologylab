#!/bin/bash
# G003 manual QA: SC1/SC2 resolve_engine surface, SC3 decode-params/api-engine regression, SC4 translate rejects auto
set -u
cd "$(dirname "$0")/../../.."
E=evidence/design-impl-wave1-20260827; H=$E/qa-server.sh; PY=.venv/bin/python
fail=0
{ # SC1 + SC2
$PY -P - <<'PY'
from ontologylab.engines import resolve_engine, MockEngine, ClaudeEngine, EngineError
checks = {
    "none_is_claude": isinstance(resolve_engine(None), ClaudeEngine),
    "blank_is_claude": isinstance(resolve_engine(""), ClaudeEngine),
    "mock_is_mock": isinstance(resolve_engine("mock"), MockEngine),
}
for name in ("auto", "nope"):
    try:
        resolve_engine(name); checks[f"{name}_raises"] = False
    except EngineError:
        checks[f"{name}_raises"] = True
print(checks)
print("G003-SC1 OK" if checks["none_is_claude"] and checks["mock_is_mock"] and checks["auto_raises"] else "G003-SC1 FAIL")
print("G003-SC2 OK" if checks["blank_is_claude"] and checks["nope_raises"] else "G003-SC2 FAIL")
PY
} 2>&1 | tee $E/G003/sc1-resolve-engine.txt; cp $E/G003/sc1-resolve-engine.txt $E/G003/sc2-none-auto.txt
grep -q 'G003-SC1 OK' $E/G003/sc1-resolve-engine.txt || fail=1; grep -q 'G003-SC2 OK' $E/G003/sc2-none-auto.txt || fail=1
{ # SC3
uv run --all-extras pytest tests/test_decode_params.py tests/test_api_engine.py tests/test_resolve_engine.py -v 2>&1 | tail -4
uv run --all-extras pytest tests/test_decode_params.py tests/test_api_engine.py tests/test_resolve_engine.py 2>&1 | grep -q -E '^[0-9]+ passed' && ! uv run --all-extras pytest tests/test_decode_params.py tests/test_api_engine.py tests/test_resolve_engine.py 2>&1 | grep -q failed && echo "G003-SC3 OK" || echo "G003-SC3 FAIL"
} 2>&1 | tee $E/G003/sc3-decode-params.txt; grep -q 'G003-SC3 OK' $E/G003/sc3-decode-params.txt || fail=1
{ # SC4
$H start || exit 1; TOK=$($H token); U=$($H url)
curl -si -H "X-OntologyLab-Session: $TOK" -H "Content-Type: application/json" \
  -d '{"texts":["This study investigates breast cancer treatment."],"engine":"auto"}' "$U/api/translate" | tee /tmp/ol-w1-g3sc4.txt | head -1
grep -q -E 'HTTP/1.1 (4[0-9][0-9]|502)' /tmp/ol-w1-g3sc4.txt && ! grep -q '"translations"' /tmp/ol-w1-g3sc4.txt && echo "G003-SC4 OK" || echo "G003-SC4 FAIL"
$H stop; rm -f /tmp/ol-w1-g3sc4.txt
} 2>&1 | tee $E/G003/sc4-translate-no-auto.txt; grep -q 'G003-SC4 OK' $E/G003/sc4-translate-no-auto.txt || fail=1
echo "G003_QA_$([ $fail = 0 ] && echo PASS || echo FAIL)"
