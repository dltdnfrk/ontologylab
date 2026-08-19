# OntologyLab 파이프라인 엔진 적대적 감사

- **감사일:** 2026-08-19
- **대상 저장소:** `/Users/hyunjun/Documents/MUNI/ontologylab`
- **감사 기준 HEAD:** `22c65ddf91857d0f4d64ea970e50919eaadef014`
- **작성자:** Prime Agent 독립 검토
- **범위:** intake → extraction → normalization → review/HITL → retrieval → pack/MCP → `method_*` → server/jobs/web
- **제약 준수:** 소스 수정·커밋 없음, 실데이터 미사용, 포트 8799/PID 55560 미접촉, 실행 fixture는 `/private/tmp` 사용

## 1. 결론

OntologyLab은 전체가 빈 껍데기인 시스템이 아니다. 문서 수집, LLM 호출, chunk checkpoint, SQLite 상태 전이, registry 정규화, lexical/vector 검색, pack 생성, MCP stdio, Method release, background job까지 실제 코드와 실제 데이터 경로가 존재한다. 다만 **“구현되어 있다”와 “주장하는 신뢰 수준을 보장한다”는 다르다.**

특히 다음 표의 THIN 판정은 코드량 부족이 아니라, 핵심 신뢰 경계·통합·품질 증명이 약하다는 뜻이다.

| 단계 | 판정 | 요약 |
|---|---|---|
| 1. Intake / connectors / sources | **REAL** | 실 HTTP connector, allowlist, redirect 재검사, fan-out, partial failure, persistence가 연결됨. 다만 여러 진입점에서 provenance가 소실되고 입력 cardinality가 무제한임. |
| 2. Extraction / engines / chunk / span | **THIN** | 실제 CLI/API engine과 durable checkpoint가 있으나, spanless relation endpoint·substring grounding·약한 property 검증으로 epistemic gate가 얇음. |
| 3. Normalization / entity resolution | **THIN** | registry와 fuzzy merge는 실구현. 그러나 proposed alias가 즉시 식별 권한을 갖고 ambiguous alias를 `LIMIT 1`로 합침. |
| 4. Review / HITL / critic / conformal | **THIN** | proposal persistence와 critic·통계 알고리즘은 실구현. 상태 전이 불변식, reviewer attribution, ontology apply 원자성이 약하며 conformal/calibration의 제품 통합은 사실상 **HOLLOW**. |
| 5. Retrieval | **THIN** | 기본 lexical FTS5/BM25는 **REAL**. embedding/rerank/expansion은 opt-in이고 coverage·score·algorithm provenance가 불완전함. |
| 6. Pack / MCP serving | **THIN** | packbuilder의 snapshot·staging·atomic rename과 MCP happy path는 **REAL**. 그러나 일부 MCP resource read는 integrity gate를 우회하여 해당 무결성 경계는 **HOLLOW**. |
| 7. `method_*` | **THIN** | UoW, compiler artifacts, release, pack copy, read-only MCP는 실구현. 반면 G5 conflict gate와 G7 replay 의미가 주장보다 약하고 지원되는 end-to-end application surface가 빠짐. |
| 8. Server / jobs / web UI | **REAL** | 일반 KG collect→extract→review→pack 경로는 실제 thread/DB/engine을 통과. Job history는 THIN, Method web surface는 **HOLLOW**. |

### 직접 답변

- **실제 엔진이 있는가?** 예. 8개 단계 모두 최소한 핵심 경로에는 실제 구현이 있다.
- **빈껍데기는 없는가?** 단계 전체가 HOLLOW인 곳은 없지만, 다음 하위 주장은 빈껍데기에 가깝다.
  1. MCP의 “모든 named pack read가 검증된다”는 무결성 경계
  2. reviewer가 실제 인간이라는 attribution
  3. conformal/calibration이 review UX를 실제로 제어한다는 제품 통합
  4. Method G7이 행동을 재현한다는 replay 의미
  5. Method를 web에서 조립·release 선택·pack하는 표면

---

## 2. 감사 방법과 테스트 신뢰도

### 2.1 정적 추적

현재 제품 Python은 91개 파일, 약 37.6k LOC이며 테스트는 127개 파일, 약 44.6k LOC다. LOC가 많다는 사실을 REAL 근거로 사용하지 않고, 다음을 추적했다.

1. public entrypoint가 실제 구현까지 연결되는가
2. 입력·오류·취소·재시작이 durable state와 일치하는가
3. optional dependency가 없을 때 무엇이 실제 기본 동작인가
4. 검토·pack·MCP가 동일한 trust boundary를 공유하는가
5. 테스트가 결과가 아니라 불변식을 assertion하는가
6. 의도적으로 동작을 깨뜨렸을 때 테스트가 실패하는가

### 2.2 실행 증거

전체 suite를 cache·bytecode 없이 격리 실행했다.

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/private/tmp/... \
ONTOLOGYLAB_OFFLINE=1 \
.venv/bin/python -B -m pytest -p no:cacheprovider
```

결과:

```text
2236 passed, 57 failed, 1 skipped in 713.43s
```

57개 실패는 제품 회귀가 아니라, 테스트가 fake HTTP transport를 monkeypatch하더라도 전역 `ONTOLOGYLAB_OFFLINE=1`이 그 이전에 차단한 harness 충돌이었다. 해당 파일들을 offline 강제 없이 재실행했다.

```text
228 passed in 6.07s
```

추가 표적 결과:

| 범위 | 결과 |
|---|---:|
| intake/extraction 핵심 | 70 passed |
| registry/normalization/merge/review | 143 passed |
| retrieval/pack/MCP | 183 passed |
| Method subsystem | 372 passed |
| server/jobs/UI 관련 | 983 passed |

이 수치는 서로 겹치므로 합산하지 않는다.

### 2.3 테스트에 대한 총평

테스트 양과 happy-path coverage는 강하다. checkpoint 원자성, pack staging, merge signal, critic fail-open, Method relational tamper 등은 실동작을 검증한다. 그러나 mutation standard는 단계별로 불균일하다. 실제로 다음 변경 또는 현재 결함이 표적 suite를 통과했다.

- CAS checksum 검사를 항상 참으로 바꿔도 관련 29개 테스트 통과
- calibration에서 edge를 제외해도 39개 테스트 통과
- conformal에서 edge calibration을 제거해도 46개 테스트 통과
- MCP `resource_*`가 pack hash 검증을 우회해도 integrity 테스트 통과
- full-text 재구성이 `source/evidence_grade`를 버려도 intake 테스트 통과
- synchronous collect route가 provenance를 버려도 server 관련 983개 테스트 통과
- Method contradiction evidence가 있어도 G5가 통과
- G7이 실제 입력을 재생하지 않고 JSON field만 비교해도 전체 Method suite 통과

즉 테스트는 “많다”. 하지만 가장 중요한 신뢰 경계 일부는 mutation-sensitive하지 않다.

---

## 3. 단계별 감사

## 3.1 Intake — **REAL**

### 실제 구현 증거

- URL/host allowlist를 I/O 전에 검사한다: `ontologylab/connectors/allowlist.py:99-116,181-208`.
- web crawl은 redirect마다 재검사하고 응답 크기를 제한한다: `ontologylab/connectors/web_crawl.py:88-149`.
- paper connector는 HTTPS/host/credential redirect 및 5 MiB cap을 구현한다: `ontologylab/connectors/paper_api.py:255-393`.
- 실제 source dispatch와 implemented source 집합이 있다: `ontologylab/connectors/paper_api.py:1191-1246`.
- 다중 source를 병렬 호출하고 source별 partial failure를 유지한다: `ontologylab/connectors/paper_api.py:1563-1646`.
- research job이 dedupe, full-text enrichment, persistence 후 해당 문서만 extraction으로 넘긴다: `ontologylab/server/jobs.py:835-905`.

이는 connector 이름만 나열한 facade가 아니다. 외부 API와 key가 필요한 source는 실제 외부 의존성을 가지며, 실패도 대부분 typed partial failure로 처리한다.

### 얇거나 잘못된 경계

1. **Full-text enrichment가 provenance를 지운다.** `RawDocument` 재구성 시 `source`와 `evidence_grade`를 전달하지 않아 빈 값으로 되돌아간다: `ontologylab/connectors/fulltext.py:176-188`. 이 경로는 기본 활성화된 research path에서 사용된다: `ontologylab/server/jobs.py:864-895`.
2. **동기 `/api/collect`도 provenance를 누락한다.** route는 `kind/uri/title/raw_text/content_hash`만 저장한다: `ontologylab/server/routes.py:1777-1784`. CLI와 research job은 해당 필드를 전달한다: `ontologylab/main.py:516-525`, `ontologylab/server/jobs.py:886-895`.
3. **CLI publisher credential 연결이 끊긴다.** `cmd_collect`가 `data_dir`를 넘기지 않지만 credential resolver는 `data_dir is None`이면 빈 결과를 낸다: `ontologylab/main.py:485-493`, `ontologylab/connectors/paper_api.py:1277-1305`.
4. **DOI는 run 내부에서만 dedupe된다.** connector dedupe는 DOI를 사용하지만 DB는 `UNIQUE(content_hash)`만 가진다: `ontologylab/connectors/base.py:82-130`, `ontologylab/kgstore.py:201-215,1928-1958`. 같은 DOI의 본문이 바뀌면 다른 문서가 생긴다.
5. **요청 cardinality와 로컬 파일 크기가 무제한이다.** request list max/uniqueness가 없고 각 입력별 task를 만든다: `ontologylab/server/schemas.py:24-45`, `ontologylab/connectors/paper_api.py:1594-1628`. 파일은 regular-file/byte cap 없이 전부 읽는다: `ontologylab/server/routes.py:1754-1767`.
6. `fetch_sources`가 `BaseException`을 일반 source failure로 흡수해 cancellation까지 삼킬 수 있다: `ontologylab/connectors/paper_api.py:1615-1644`.

### 테스트 판정

REAL 판정은 유지한다. 다만 `tests/test_evidence_grade.py:248-274`의 AST guard가 jobs/main만 보고 route를 누락하며, full-text identity test도 source/grade를 assertion하지 않는다. 현재 테스트는 provenance 보존을 증명하지 않는다.

---

## 3.2 Extraction — **THIN**

### 실제 구현 증거

- chunking, overlap, prompt 구성, parse, schema filter, evidence rebasing 경로가 있다: `ontologylab/extractor.py:93-130,179-207,379-628`.
- engine 호출, budget, cancel, chunk lifecycle, atomic proposal/checkpoint commit이 연결된다: `ontologylab/extractor.py:671-863`.
- extraction identity와 pending/failed resume를 durable하게 관리한다: `ontologylab/extraction_state.py:17-59,243-373`.
- Claude/Codex/API adapter는 실제 process/HTTP 경로를 가진다: `ontologylab/engines.py:534-619,707-848`.

따라서 구현 자체는 가짜가 아니다. THIN 판정 이유는 **추출 결과를 지식 후보로 받아들이는 epistemic validator가 약하기 때문**이다.

### 핵심 결함

1. **관측되지 않은 relation endpoint를 합성한다.** 독립 entity라면 text에 없을 때 거부하지만 relation endpoint면 `source_span=None` node를 만들고 relation도 유지한다: `ontologylab/extractor.py:421-435,517-552,589-625`. 테스트가 이 동작을 명시적으로 승인한다: `tests/test_extractor.py:241-278`.
2. **substring false grounding.** `_locate_skeleton`이 token boundary 없이 `.find()`를 사용해 `CAT`을 `concatenate` 내부에 grounding할 수 있다: `ontologylab/extractor.py:241-267`.
3. **Entity attribute schema가 거의 강제되지 않는다.** undeclared key와 enum은 보지만 type, required, pattern, length, numeric range는 검사하지 않는다: `ontologylab/extractor.py:445-467`.
4. **Relation evidence는 predicate를 검증하지 않는다.** span 안에 endpoint 문자열 두 개가 있으면 되고, 실패하면 두 endpoint의 최소/최대 범위를 새 span으로 합성한다: `ontologylab/extractor.py:589-608`.
5. **API 기본 engine이 synthetic mock이다.** request schema가 `engine="mock"`을 기본값으로 둔다: `ontologylab/server/schemas.py:34-63`. Mock은 연속 CamelCase mention을 schema-compatible relation으로 연결한다: `ontologylab/engines.py:285-338`.
6. subprocess output과 API response body가 memory bounded가 아니다: `ontologylab/engines.py:135-158,689-704`.
7. chunk marker가 untrusted text에 대해 escape되지 않는다: `ontologylab/extractor.py:205-207`.

### 테스트 판정

checkpoint/budget/cancel 테스트는 강하다. 반면 extraction quality fixture는 deterministic MockEngine의 연속 mention 규칙을 그대로 gold로 만들고 0.99를 요구한다: `tests/test_extraction_quality.py:9-11,40-58,100-110`. 이는 real LLM extraction 품질을 증명하지 않는다. Wrong attribute type, required 누락, substring grounding, spanless endpoint를 거부하는 negative mutation test가 필요하다.

---

## 3.3 Normalization / entity resolution — **THIN**

### 실제 구현 증거

- registry importer는 shape/ambiguity를 검증하고 provenance hash를 기록하며 temp DB를 atomic replace한다: `ontologylab/registry.py:218-316,395-546`.
- CAS check digit이 실제 구현돼 있다: `ontologylab/registry.py:319-332`.
- EPPO/CAS resolution은 absent/unresolved/resolved를 구분한다: `ontologylab/registry.py:549-603,652-709`.
- model이 준 code보다 local registry authority를 우선하고 CAS에서 MoA를 유도한다: `ontologylab/normalization.py:13-91`.
- 이 정규화는 extraction storage 직전에 실제 호출된다: `ontologylab/extractor.py:705-726,826-845`.
- fuzzy merge scanner는 trigram/exact blocking, vector neighbor, 네 signal과 candidate persistence를 구현한다: `ontologylab/merge.py:66-263`.
- merge apply는 citation/edge 재지정, source tombstone, queue update를 수행한다: `ontologylab/kgstore.py:3257-3492`.

### 핵심 결함

1. **Alias ambiguity를 임의로 해소한다.** alias lookup이 다중 후보를 감지하지 않고 `LIMIT 1`을 사용한다: `ontologylab/kgstore.py:2600-2619`.
2. **Proposed alias가 즉시 grounding authority가 된다.** unreviewed model alias가 바로 `node_aliases`에 들어가 이후 mention을 기존 node로 합친다: `ontologylab/kgstore.py:2412-2431,2516-2517,2654-2662`.
3. DB uniqueness는 `(node_id, normalized_alias)`뿐이라 동일 alias가 여러 node에 존재할 수 있다: `ontologylab/kgstore.py:258-264`.
4. merge scanner는 `entity_type`만 grouping하며 schema version을 고려하지 않는다: `ontologylab/merge.py:223-248`. `merge_nodes` 역시 초기에는 type만 확인한다: `ontologylab/kgstore.py:3293-3302`.

Runtime counterexample에서는 두 proposed node가 같은 alias를 가졌고, 세 번째 mention이 임의로 첫 node에 merge됐다. Entity resolution 알고리즘은 존재하지만 identity trust model이 얇다.

### 테스트 판정

Registry/merge 신호 테스트는 강하지만 CAS checksum을 무력화한 mutant가 관련 29개 테스트를 통과했다. Wrong-check-digit fixture와 ambiguous alias, proposed-vs-verified alias authority, cross-schema merge negative test가 필요하다.

---

## 3.4 Review / HITL — **THIN**

### 실제 구현 증거

- node/edge는 proposed 상태로 생성되고 verified query와 pending queue가 구분된다: `ontologylab/kgstore.py:217-305,2412-2598,3541-3815`.
- critic은 evidence-only prompt, strict ID parsing, batching/fail-open을 구현하고 status를 바꾸지 않은 채 advisory row만 기록한다: `ontologylab/critic.py:67-292`, `ontologylab/kgstore.py:3817-3843`.
- queue가 critic score와 disagreement를 실제 join/order한다: `ontologylab/kgstore.py:3503-3539,3580-3617`.
- conformal quantile과 scarce-data refusal은 실제 수학이다: `ontologylab/conformal.py:75-77,125-153`.
- calibration의 ECE와 tie-aware PAVA도 실제 구현이다: `ontologylab/calibration.py:70-108,139-193`.
- ontology proposal parsing/content addressing/local match/apply가 구현돼 있다: `ontologylab/proposals.py:534-705,724-958,1001-1189`.

### 핵심 결함

1. **상태 전이 그래프가 강제되지 않는다.** `approve()`와 `reject()`는 current status가 proposed인지 확인하지 않고 unconditional `_set_status`를 사용한다: `ontologylab/kgstore.py:2723-2768,2816-2824`. Verified edge가 있는 node를 직접 reject하거나 rejected node를 직접 approve할 수 있다.
2. **“Human approved” attribution은 보안 경계가 아니다.** API가 caller의 `body.by`를 그대로 신뢰한다: `ontologylab/server/routes.py:481-519,1289-1307`. 서버 자체도 local single-user/no-auth임을 선언한다: `ontologylab/server/security.py:1-18,107-131`.
3. **Ontology apply가 source artifact를 재검증하지 않는다.** verify 시 `source_candidate_ids`의 현재 status/content를 재확인하지 않는다: `ontologylab/proposals.py:1001-1083`. Preview 후 source를 reject해도 오래된 proposal을 적용할 수 있다.
4. **Ontology apply가 원자적이지 않다.** term/alias/xref store method가 각자 commit하여 중간 실패 시 부분 term이 남을 수 있다: `ontologylab/proposals.py:1091-1158`, `ontologylab/kgstore.py:1408-1485,1747-1842`.
5. **Conformal product integration은 HOLLOW에 가깝다.** read-only endpoint만 있고 queue/web가 threshold를 소비하지 않는다: `ontologylab/server/routes.py:380-395`. Kind별로 최신 stream을 따로 고른 뒤 node/edge를 한 calibration set으로 합친다: `ontologylab/conformal.py:39-68,111-122`.
6. **Calibration도 제품 통합이 없다.** endpoint 외 consumer가 없으며 engine/model/prompt/type이 다른 confidence를 합친다: `ontologylab/calibration.py:48-67`, `ontologylab/server/routes.py:398-410`.

### 테스트 판정

Critic fail-open과 수학 hand calculation은 강하다. 그러나 edge 데이터를 제거한 conformal/calibration mutant가 각각 46개/39개 테스트를 통과했다. Illegal re-decision, verified-edge/rejected-endpoint, stale source proposal, mid-apply rollback, mixed stream fixture가 필요하다.

---

## 3.5 Retrieval — **THIN**

### 실제 구현 증거

- 기본 검색은 verified-only FTS5/BM25를 실제 수행한다: `ontologylab/kgstore.py:4558-4606`.
- embedding storage, cosine/vector retrieval, RRF가 구현돼 있다: `ontologylab/kgstore.py:4656-4785`, `ontologylab/embeddings.py:218-241`.
- real MiniLM embedder와 optional sqlite-vec가 있다: `ontologylab/embeddings.py:75-92,154-208`.
- cached cross-encoder reranker를 실제 호출하며 없으면 RRF로 fail-open한다: `ontologylab/rerankers.py:91-108`, `ontologylab/mcp_server.py:785-830`.
- expansion은 engine을 호출해 bounded variant를 parse하고 fail-open한다: `ontologylab/expansion.py:56-108`.
- community build/materialization/MCP serving이 연결된다: `ontologylab/communities.py:224-276`, `ontologylab/packbuilder.py:524-561`, `ontologylab/mcp_server.py:678-702`.

### 왜 THIN인가

1. **기본은 lexical이다.** CLI/MCP embedder default는 None이다: `ontologylab/main.py:1860-1866`, `ontologylab/mcp_server.py:1411-1418`.
2. `ontologylab embed` 기본 `hash-v1`은 재현 가능한 lexical hash이지 semantic model이 아니다: `ontologylab/main.py:1870-1883`, `ontologylab/embeddings.py:110-146`.
3. **Partial/mixed embedding coverage를 hybrid로 과장할 수 있다.** `embedding_model()`이 첫 non-null model만 반환하고, packbuilder는 하나라도 있으면 `fts5+vec-rrf`로 표시한다: `ontologylab/kgstore.py:4680-4686`, `ontologylab/packbuilder.py:633-650`.
4. **실제 reranker가 실행돼도 tier label에 기록되지 않는다:** `ontologylab/mcp_server.py:785-830,1181-1187`.
5. Community algorithm이 Leiden인지 label propagation인지 manifest에 남지 않는다: `ontologylab/communities.py:48-59,106-127`, `ontologylab/packbuilder.py:642-669`.
6. BM25 normalization, cosine 변환, RRF, sigmoid score를 모두 0..1처럼 노출하지만 의미가 달라 `min_score`가 tier마다 다르다: `ontologylab/kgstore.py:4558-4606,4764-4785,4884-4893`.
7. sqlite-vec shortlist 후 status/type filter를 적용해 제외 row가 많으면 유효 결과가 starvation될 수 있다: `ontologylab/kgstore.py:4697-4755`.
8. expansion은 default off이고 lexical mode에서 variant를 넓은 OR로 결합한다: `ontologylab/main.py:1852-1858`, `ontologylab/mcp_server.py:905,923-930`.

따라서 lexical core는 REAL이지만 “semantic hybrid retrieval stack” 전체를 기본 제품 능력으로 부르기에는 THIN하다.

---

## 3.6 Pack / MCP — **THIN**

### 실제 구현 증거

- SQLite consistent backup을 사용한다: `ontologylab/packbuilder.py:337-350`.
- verified/current subgraph만 export한다: `ontologylab/packbuilder.py:472-519`.
- staging을 discovery 밖에 만들고 same-filesystem atomic rename한다: `ontologylab/packbuilder.py:402-411,720-743`.
- `load_pack`은 current SQLite bytes와 receipt hash를 검증한 후에만 session을 바꾼다: `ontologylab/mcp_server.py:237-289,336-356,579-604`.
- MCP stdio happy path와 scalar type/range validation은 실제다: `ontologylab/mcp_runtime.py:51-140`.

### 무결성 경계 결함

1. **MCP resource read가 verified opener를 우회한다.** `_store_for`가 raw path를 `KGStore.open`하며 manifest도 raw JSON으로 읽는다: `ontologylab/mcp_server.py:708-723`. Schema/entity/term/xref resource가 이 경로를 사용한다: `ontologylab/mcp_server.py:725-747`.
2. 실제 temp pack의 DB byte를 동일 길이로 변조했을 때 `load_pack`은 `PackIntegrityError`였지만 `resource_entity`는 변조된 이름을 반환했다.
3. Integrity test는 `resource_*`를 coverage 대상에서 제외한다: `tests/test_mcp_pack_integrity.py:37-41,94-104`.
4. `get_staleness`도 shallow discovery 결과의 DB를 verified opener 없이 연다: `ontologylab/mcp_server.py:410-428,472-483`.
5. Receipt는 SQLite만 hash한다. schema, provenance, counts, capabilities, methodology metadata는 receipt-bound가 아니다: `ontologylab/packbuilder.py:608-719`.
6. Discovery와 serveability가 다르다. `scan_packs`는 directory name과 pack_id 일치, hash, symlink/hardlink policy까지 검증하지 않는다: `ontologylab/packbuilder.py:840-896`.
7. MCP nested array/object validation은 container type만 확인한다: `ontologylab/mcp_runtime.py:87-102`. Protocol version negotiation도 사실상 echo다: `ontologylab/mcp_runtime.py:252-275`.

Packbuilder 자체는 REAL이다. 하지만 pack이 신뢰 경계라는 제품 주장에서는 **모든 read surface가 동일한 verified opener를 쓰지 않는 한 단계 전체를 REAL로 판정할 수 없다.**

---

## 3.7 `method_*` subsystem — **THIN**

### 실제 구현 증거

- `MethodUnitOfWork`가 `BEGIN IMMEDIATE`, busy mapping, commit/rollback ownership을 가진다: `ontologylab/method_store.py:599-645`.
- release insertion이 attempt identity, 9개 hash-bound gate row, reviewer hash를 재검증한다: `ontologylab/method_release_store.py:194-258`.
- occurrence extraction이 real Engine을 호출하고 strict fence parse, exact span/hash rebase, chunk checkpoint/resume/cancel을 구현한다: `ontologylab/method_extract.py:51-91,122-266`.
- selected release는 attempt/gates/source/policy/snapshot을 재검증한 후 pack으로 복사된다: `ontologylab/method_pack.py:131-333`.
- packbuilder가 Method selection을 pre/post build에 검사한다: `ontologylab/packbuilder.py:361-380,563-590,723-740`.
- MCP method tool은 pack-only/read-only이며 publication receipt와 copied-row hash를 매 query에서 검증한다: `ontologylab/method_mcp.py:72-229`, `ontologylab/mcp_server.py:1275-1302`.

### 핵심 결함

1. **G5 conflict gate가 contradiction을 놓친다.** gap detection은 `contradicts` evidence를 `explicit_counter_evidence`로 바꾸지만 G5는 이미 저장된 `gap_class == "open_conflict"`만 거부한다: `ontologylab/method_gaps.py:196-207`, `ontologylab/method_compiler_gates.py:415-427`. 실제 contradiction row를 추가해도 compile과 G5가 통과했다.
2. **G7은 행동 replay가 아니다.** fixture가 compiled Method JSON의 field value/presence만 비교한다: `ontologylab/method_compiler_replay.py:101-125,276-297`. 입력, simulator output, external execution receipt가 없다.
3. **Processor/region provenance가 저장되지 않는다.** authorization 입력에는 있지만 `ExtractionRunWrite`와 resume identity에는 없다: `ontologylab/method_extraction_store.py:23-36,206-262`, `ontologylab/method_extract.py:173-185`.
4. **지원되는 end-to-end application service가 없다.** CLI는 import/decision/gap/compile을 제공하지만 fragment evidence, bridge evidence, counter-search write를 노출하지 않는다: `ontologylab/main.py:355-404`. QA script가 이 틈을 `MethodStore` 직접 호출로 우회한다: `scripts/qa_methodology_compiler.py:915-978`.
5. QA proof는 live extraction/assembly가 아니라 frozen JSON으로 occurrence/fragment/link를 만든다: `scripts/qa_methodology_compiler.py:886-912,1047-1075`.
6. Web pack request는 Method release ID를 선택할 수 없다: `ontologylab/server/schemas.py:101-106`, `ontologylab/server/routes.py:2411-2419`.

### 테스트 판정

372개 Method 표적 테스트는 통과했고 relational tamper/transaction 테스트는 강하다. 그러나 G5/G7 반례가 모두 suite를 통과한다. “real e2e”가 직접 store 호출로 결손 adapter를 우회하므로 제품 경로를 증명하지 않는다. Method는 연구/컴파일 기반으로는 실체가 있지만 아직 supported product workflow로는 THIN하다.

---

## 3.8 Server / jobs / web UI — **REAL**

### 실제 구현 증거

- Job은 실제 daemon thread를 만들고 thread-owned store에서 shared extraction을 호출한다: `ontologylab/server/jobs.py:375-438,663-755`.
- research job이 query formulation, fan-out, dedupe/full-text, exact doc extraction을 수행한다: `ontologylab/server/jobs.py:757-988`.
- job summary를 durable `runs`에 mirror하고 startup zombie를 복구한다: `ontologylab/server/jobs.py:276-357`.
- SSE는 immediate snapshot, change-driven update, bounded keepalive를 구현한다: `ontologylab/server/routes.py:2291-2344`.
- UI는 EventSource와 polling fallback을 실제 사용한다: `web/app.js:2466,2479-2480`.
- app은 host/DNS-rebinding/cross-site mutation guard와 redacted validation/storage handler를 가진다: `ontologylab/server/app.py:64-129,150-186`.
- frontend helper가 throwing GET과 shaped write failure를 구분한다: `web/app.js:97-114,1731-1761`.

Temp TestClient에서 sample collect → mock extraction → 8 node/7 edge → 15 proposals → approval → pack build → `/api/mcp/status` 노출까지 실제 경로가 통과했다.

### 얇은 부분

1. **동기 collect provenance 누락:** `ontologylab/server/routes.py:1774-1784`.
2. **Source SSE가 한 mutation 늦다.** `_source_event`가 먼저 `record/touch`하고 이후 `job.sources`를 갱신하지만 다시 touch하지 않는다: `ontologylab/server/jobs.py:188-199,587-604`.
3. **Durable job history는 summary뿐이다.** progress, steps, source statuses는 저장하지 않고 restart 후 empty trace로 복원한다: `ontologylab/server/jobs.py:142-146,288-355`.
4. **Method web surface는 HOLLOW다.** `/api/method*`도 release 선택 UI/API도 없다.
5. UI contract test 일부는 여전히 `app.js` 문자열/regex 검사다. selected function을 Node로 실행하는 테스트는 개선됐지만 full DOM integration mutation에는 약하다: `tests/test_ui_failure_honesty.py:41-72,170-215`.

일반 KG 경로는 REAL이다. 다만 “durable job”은 durable trace/resume가 아니라 summary persistence라는 좁은 의미로 읽어야 한다.

---

## 4. 우선순위별 리팩터링 권고

## P0 — 신뢰 불변식부터 닫기

### P0-1. Review 상태 전이를 하나의 transactional state machine으로 통합

- conditional update: `WHERE status='proposed'`
- verified edge를 지지하는 node reject/reopen 차단 또는 명시적 cascade
- approve/reject/reopen/merge/ontology apply를 `BEGIN IMMEDIATE` 한 transaction으로 처리
- stale source proposal과 mid-apply failure를 rollback
- reviewer attribution을 보안 주장으로 쓸 경우 local capability/session principal 도입

**이유:** 현재 verified graph가 rejected endpoint를 갖거나 부분 ontology term을 남길 수 있어 KG 신뢰의 중심 불변식이 깨진다.

### P0-2. 모든 pack read를 하나의 verified opener로 통일

- load, resource, schema, staleness, discovery, Method query가 같은 validation primitive 사용
- SQLite뿐 아니라 manifest/schema/provenance를 묶는 umbrella receipt 도입
- directory name/pack_id/hash/symlink 정책과 serveability를 discovery 시 검증
- verify-then-open race를 줄이기 위해 검증한 file descriptor 또는 immutable snapshot 사용

**이유:** pack load가 막는 tamper를 MCP resource가 읽을 수 있으면 immutable pack 신뢰 경계가 성립하지 않는다.

### P0-3. 추출 evidence gate와 alias authority를 엄격화

- spanless synthesized node/relation을 reject 또는 명시적 ungrounded queue로 격리
- whole-token/nearest-span grounding
- entity property에 required/type/pattern/range 적용
- predicate를 포함한 relation evidence span 요구
- proposed alias는 identity resolution authority로 사용하지 않음
- ambiguous alias는 merge candidate로 보내고 자동 `LIMIT 1` 금지
- production API에서 implicit mock 기본값 제거

**이유:** reviewer 이전 단계에서 invented/ambiguous identity가 다른 사실을 흡수한다.

### P0-4. Method compiler gate 의미를 정직하게 재정의

- accepted evidence에서 conflict를 canonical derivation하고 G5가 직접 검사
- 현 G7은 “static competency assertion”으로 이름을 바꾸거나, frozen input/output와 external replay receipt를 hash-bind
- processor/region/adapter/policy decision을 run/chunk identity에 저장

**이유:** non-compensatory gate와 replay라는 명칭이 실제 검사보다 강하다.

## P1 — 파이프라인 수렴과 제품 통합

### P1-1. 단일 ingestion application service

CLI, synchronous route, research job이 같은 함수를 사용하도록 하여 source, evidence grade, DOI, full-text metadata, typed error를 동일하게 보존한다. `dataclasses.replace()` 등으로 document 재구성 시 필드 손실을 방지한다. 입력 list/file/response 크기도 한곳에서 제한한다.

### P1-2. Retrieval capability receipt

Pack에 다음을 기록한다.

- verified entity 수 / embedding 보유 수 / coverage 비율
- model별 count와 homogeneous 여부
- lexical/vector/RRF/reranker의 실제 실행 신호
- reranker model/applied 여부
- community algorithm/seed/resolution
- score kind와 raw/calibrated semantics

Coverage가 100%가 아니면 `hybrid`라고 단순 표시하지 않는다.

### P1-3. Method application service와 web surface

Occurrence → fragment assembly → evidence recovery → bridge/counter-search → decision → compile을 하나의 supported command/service로 제공한다. QA script의 직접 `MethodStore` 호출을 제거한 뒤 real engine→release→pack→stdio MCP acceptance를 추가한다. 그 후 server/API/UI에 Method release selection을 노출한다.

### P1-4. Job/event contract 강화

- source state update와 notification을 atomic하게 수행
- durable history에 bounded steps/source states를 포함할지 명시
- summary-only라면 UI와 문서에서 “resumable trace”처럼 표현하지 않기
- executable DOM/API contract test로 path/listener/rendering mutation 검증

## P2 — 테스트 mutation matrix 고정

각 단계별로 최소 다음 mutant를 CI artifact로 남긴다.

1. source/evidence_grade 누락
2. DOI 동일·본문 변경 중복
3. spanless endpoint 허용, wrong property type, substring grounding
4. CAS wrong check digit
5. shared alias와 proposed alias authority
6. 모든 illegal review transition
7. stale ontology source와 mid-apply failure
8. node-only/edge-only conformal·calibration, mixed stream
9. partial/mixed embedding coverage
10. MCP resource hash bypass, manifest metadata tamper
11. Method contradiction-only G5, static-only G7
12. source update without SSE touch, Method web selection 누락

---

## 5. 최종 판단

OntologyLab의 문제는 “아무것도 구현되지 않았다”가 아니다. 오히려 많은 실구현과 테스트가 존재한다. 현재의 가장 큰 위험은 **실제 구현의 존재가 더 강한 제품 주장으로 확대되는 것**이다.

- Intake와 일반 server workflow는 REAL이다.
- Extraction, normalization, review, retrieval, pack/MCP, Method는 핵심 알고리즘이 존재하지만 신뢰 경계 또는 product integration 때문에 THIN이다.
- HOLLOW는 단계 전체가 아니라 특정 주장에 집중돼 있다: human attribution, conformal/calibration UX, MCP named-resource integrity, Method behavioral replay, Method web workflow.

출시 판정은 기능 수가 아니라 다음 네 gate로 해야 한다.

1. review state와 evidence가 transactionally 일관적인가
2. 어떤 pack read도 receipt 검증을 우회하지 않는가
3. grounded/verified라는 단어가 실제 validator보다 강하지 않은가
4. advanced capability가 실제 기본 동작·coverage·algorithm receipt와 함께 보고되는가

이 네 가지를 닫기 전에는 “파이프라인 엔진이 모두 구현됐다”는 말은 코드 존재 관점에서는 참이지만, 신뢰 가능한 지식 생산 시스템이라는 관점에서는 아직 과장이다.
