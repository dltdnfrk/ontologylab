#!/bin/bash
# G001 manual QA: SC1 CLI collect, SC2 typed conflict, SC3 /api/ingest unchanged, SC4 no shadow + no leak (A1: shadow only; ingestion.py kept)
set -u
cd "$(dirname "$0")/../../.."
E=evidence/design-impl-wave1-20260827; H=$E/qa-server.sh; PY=.venv/bin/python
fail=0
{ # SC1
DATA=$(mktemp -d /tmp/ol-w1-sc1-XXXXXX); FIX=$(mktemp -d /tmp/ol-w1-sc1fix-XXXXXX)
printf '%s\n' "The PaymentGateway validates cards through the FraudDetector." > "$FIX/notes.md"
$PY -P -m ontologylab.main collect --file "$FIX/notes.md" --data-dir "$DATA"; echo "cli_exit=$?"
$PY -P - "$DATA" <<'PY'
import sys; from pathlib import Path
from ontologylab.kgstore import KGStore; from ontologylab.paths import kg_db_path
s = KGStore.open(kg_db_path(Path(sys.argv[1])), read_only=True)
c = lambda t: s.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
print(f"documents={len(s.list_documents())} document_observations={c('document_observations')} provenance_outbox={c('provenance_outbox')} works={c('works')}")
ok = len(s.list_documents()) == 1 and c('document_observations') == 1 and c('provenance_outbox') == 1
s.close(); print("G001-SC1 OK" if ok else "G001-SC1 FAIL")
PY
rm -rf "$DATA" "$FIX"; echo "cleanup: rm -rf $DATA $FIX"
} 2>&1 | tee $E/G001/sc1-cli-collect.txt; grep -q 'G001-SC1 OK' $E/G001/sc1-cli-collect.txt || fail=1
{ # SC2
DATA=$(mktemp -d /tmp/ol-w1-sc2-XXXXXX)
$PY -P - "$DATA" <<'PY'
import sys; from pathlib import Path
from ontologylab.connectors.base import RawDocument
from ontologylab.ingestion import ingest_raw_documents_and_finalize
from ontologylab.kgstore import KGStore; from ontologylab.paths import kg_db_path; from ontologylab.provenance import Provenance
data = Path(sys.argv[1]); store = KGStore.open(kg_db_path(data))
shared = "Identical body shared by two distinct registered works."
docs = [RawDocument(source_kind="paper_api", source_uri="https://doi.org/10.1000/seam.a", title="A", raw_text=shared, doi="10.1000/seam.a", source="crossref"),
        RawDocument(source_kind="paper_api", source_uri="https://doi.org/10.1000/seam.b", title="B", raw_text=shared, doi="10.1000/seam.b", source="crossref"),
        RawDocument(source_kind="paper_api", source_uri="https://doi.org/10.1000/seam.c", title="C", raw_text="A different body entirely.", doi="10.1000/seam.c", source="crossref")]
r = ingest_raw_documents_and_finalize(store, docs, Provenance(str(data / "jobs"), seed=1))
tables = {t[0] for t in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print(f"created={r.created_count} conflicts={len(r.conflicts)} failures={len(r.failures)} documents={len(store.list_documents())} shadow_queue_table={'shadow_ingest_queue' in tables}")
ok = r.created_count == 2 and len(r.conflicts) == 1 and r.conflicts[0].incoming_doi == "10.1000/seam.b" and len(store.list_documents()) == 2 and 'shadow_ingest_queue' not in tables and '/secret/' not in repr(r.failures)
store.close(); print("G001-SC2 OK" if ok else "G001-SC2 FAIL")
PY
rm -rf "$DATA"; echo "cleanup: rm -rf $DATA"
} 2>&1 | tee $E/G001/sc2-typed-failure.txt; grep -q 'G001-SC2 OK' $E/G001/sc2-typed-failure.txt || fail=1
{ # SC3 + SC4 (HTTP, isolated server)
$H start || exit 1; TOK=$($H token); U=$($H url)
echo "--- SC3 POST /api/ingest"
PAYLOAD=$($PY -P - <<'PY2'
import json
from ontologylab.file_lifecycle import content_hash_for
text = "OrderApp talks to KitchenDisplay."
print(json.dumps({"items": [{"idempotency_key": "qa-g001", "scheme": "doi", "normalized_value": "10.1000/qa.g001",
  "source": "crossref", "evidence_grade": "A", "stage": "version_of_record", "content_kind": "abstract",
  "representation": {"source_kind": "paper_api", "source_uri": "qa://g001", "title": "QA",
                     "content_hash": content_hash_for(text.encode()), "raw_text": text}}]}))
PY2
)
curl -si -H "X-OntologyLab-Session: $TOK" -H "Content-Type: application/json" -d "$PAYLOAD" \
  "$U/api/ingest" | tee /tmp/ol-w1-sc3.txt | head -1
grep -q 'HTTP/1.1 200' /tmp/ol-w1-sc3.txt && grep -q -E '"status": ?"(created|staged)"' /tmp/ol-w1-sc3.txt && echo "G001-SC3 OK" || echo "G001-SC3 FAIL"
} 2>&1 | tee $E/G001/sc3-ingest-route.txt; grep -q 'G001-SC3 OK' $E/G001/sc3-ingest-route.txt || fail=1
{
TOK=$($H token); U=$($H url)
echo "--- SC4 POST /api/collect bogus secret path"
curl -si -H "X-OntologyLab-Session: $TOK" -H "Content-Type: application/json" -d '{"files":["/no/such/secret-dir-ELS-9f3a/notes.txt"]}' "$U/api/collect" | tee /tmp/ol-w1-sc4.txt | tail -1; echo
body_ok=1; grep -q -E 'ELS-9f3a|/no/such|Traceback|OperationalError|No such file or directory' /tmp/ol-w1-sc4.txt && body_ok=0
grep -q -E '"ok": ?false' /tmp/ol-w1-sc4.txt && grep -q 'error_kind' /tmp/ol-w1-sc4.txt || body_ok=0
$PY -P - <<'PY'
import importlib.util
print("shadow_spec_none=", importlib.util.find_spec("ontologylab.ingestion_shadow") is None)
PY
grep -q 'shadow_spec_none= True' <($PY -P -c 'import importlib.util;print("shadow_spec_none=", importlib.util.find_spec("ontologylab.ingestion_shadow") is None)') && [ $body_ok = 1 ] && echo "G001-SC4 OK" || echo "G001-SC4 FAIL"
$H stop; rm -f /tmp/ol-w1-sc3.txt /tmp/ol-w1-sc4.txt
} 2>&1 | tee $E/G001/sc4-no-shadow.txt; grep -q 'G001-SC4 OK' $E/G001/sc4-no-shadow.txt || fail=1
echo "G001_QA_$([ $fail = 0 ] && echo PASS || echo FAIL)"
