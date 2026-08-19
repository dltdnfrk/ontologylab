# OntologyLab Epistemic Contract v2 구현 명세서

```yaml
schema_version: 1
doc_id: ontologylab-epistemic-contract-v2-spec-ko
project: ontologylab
status: proposal
owner: hyunjun
approval_required: true
baseline_commit: 66481c625eb2bce649171152728e5b899a526540
created_at: 2026-08-13
language: ko
document_class: implementation-specification
supersedes: null
```

> **문서 상태**: 이 문서는 전달·검토를 위한 구현 제안서다. 아직
> `docs/PRODUCT_SPEC.md` 또는 `docs/ARCHITECTURE.md`를 대체하지 않는다.
> 소유자 승인과 실제 구현 검증을 통과한 결정만 정본 문서에 반영한다.
>
> **작업트리 주의**: 기준 커밋은 위 SHA다. Methodology Compiler 관련 파일은
> 기준 커밋 이후 작업트리 구현을 포함할 수 있으므로, 구현자는 정본 HEAD와 작업트리
> 상태를 구분해 영향 범위를 확인해야 한다.

---

## 1. 목적

OntologyLab의 현재 핵심 흐름은 다음과 같다.

```text
collect
→ extract proposals
→ human approve/reject
→ verified knowledge graph
→ immutable pack
→ read-only MCP
```

이 흐름은 유지한다. 본 명세의 목적은 새로운 거대 ontology layer를 추가하는 것이
아니라, 다음 질문에 시스템이 모호하지 않게 답하도록 기존 계약을 강화하는 것이다.

1. 어떤 원문의 어느 구간이 이 주장과 연결되는가?
2. 그 연결을 누가 어떤 축에서 검토했는가?
3. 사람 승인이 실제로 의미하는 것은 무엇인가?
4. 과학적 타당성이나 재현성이 아직 검증되지 않았다는 사실이 보존되는가?
5. 어떤 불변 release가 어떤 응답을 만들었는가?
6. MethodPlan과 실제 수행 결과가 분리되는가?

핵심 원칙은 다음 한 문장이다.

> **사람 승인은 특정 검토 축의 판정이지, provenance만으로 scientific truth를
> 선언하는 행위가 아니다.**

---

## 2. 결정 요약

### 2.1 유지

- local-first, single-user 운영
- deny-by-default source acquisition
- 모든 AI 출력의 `proposed` 시작
- 명시적인 사람 승인만 가능한 trust transition
- working KG와 immutable Pack의 물리적 분리
- Pack만 읽는 MCP surface
- read-only MCP tool contract
- ontology proposal과 extraction review의 분리
- competency Q1/Q2/Q3 회귀 테스트
- MethodPlan의 declarative, non-executing 성격

### 2.2 우선 변경

1. 저장소의 `verified`를 유지하되 외부 의미를 `human-accepted review`로 제한한다.
2. 현재 `citations`를 independently reviewable `ClaimOccurrence`로 승격한다.
3. KG 검토 결과를 overwrite하지 않고 append-only `KGReviewEvent`로 남긴다.
4. Pack의 모든 구성 파일을 manifest inventory와 digest로 묶는다.
5. MCP 응답에 Pack identity와 query execution 정보를 담은 receipt를 붙인다.
6. constructed fixture 외에 real-corpus blinded benchmark를 추가한다.

### 2.3 동결 후 검증

- 현 작업트리의 Methodology Compiler 확장
- G0–G8 gate 추가
- workflow ontology 추가
- GraphRAG 기본 경로 전환

위 기능은 minimal evidence baseline보다 실질적으로 나은 결과를 보일 때만 정식
아키텍처로 승격한다.

### 2.4 보류

- universal MetaOntology
- custom paraconsistent/four-valued reasoner
- 하나의 종합 `trusted` 또는 `confidence` 점수
- AI/crowd/score 기반 자동 승격
- OntologyLab 내부의 물리 실험 또는 workflow execution runtime
- 모든 데이터에 대한 일괄 bitemporal 전환
- GraphRAG를 authoritative graph 또는 기본 retrieval로 사용하는 것

---

## 3. 현행 구조와 문제 정의

### 3.1 이미 존재하는 기반

| 필요 능력 | 현재 구현 |
| --- | --- |
| immutable source identity | `documents.content_hash` |
| source location | `nodes/edges.source_span`, `citations.source_span` |
| 여러 문서의 동일 사실 언급 | `citations` |
| AI proposal와 사람 승인 | `nodes/edges.status`, `approve()/reject()/reopen()` |
| ontology 변경 별도 검토 | `OntologyProposal`, `HumanVerification` |
| provenance gate | competency Q1 |
| extraction gate | competency Q2 |
| pack query gate | competency Q3 |
| immutable release | `packbuilder.py` |
| read-only consumer | `mcp_server.py` |
| Method source selector | `method_ir.py`의 `SourceSelector` |
| Method gap/bridge/review | `method_*` 작업트리 구현 |

### 3.2 해결할 의미론적 문제

현재 `verified`는 구현상 “명시적인 사람이 이 row를 승인했다”는 뜻이다. 그러나
소비자가 이를 다음 의미로 오해할 수 있다.

- 원문이 해당 claim을 실제로 지지한다.
- entity/relation identity가 정확하다.
- ontology mapping이 적절하다.
- claim이 과학적으로 타당하다.
- claim이 독립적으로 재현됐다.

이 다섯 판정은 서로 다르며 하나의 boolean으로 합치지 않는다.

### 3.3 해결할 구조적 문제

현재 `citations`는 동일 node/edge의 여러 언급을 보존하지만, 각 citation은 독립적인
review identity와 polarity를 갖지 않는다. 이미 승인된 proposition에 새 citation이
추가될 때 새 occurrence까지 자동으로 승인된 것처럼 보일 수 있다.

또한 현재 Pack identity의 핵심 digest는 `pack.sqlite`를 중심으로 한다.
`schema.json`이나 `provenance.jsonl`이 달라져도 동일한 release로 오해할 여지가 있다.

---

## 4. 범위

### 4.1 포함

- epistemic state vocabulary
- ClaimOccurrence 저장 계약
- append-only KG review event
- proposition projection 규칙
- persisted-data migration
- Pack contract MAJOR 2
- MCP query receipt
- real-corpus benchmark
- Method compiler admission gate
- 외부 RunTrace의 미래 경계

### 4.2 비범위

- 새로운 ontology domain 설계
- agrochem-v1 class/relation 확장
- source connector 추가
- hosted service 또는 multi-user 권한 모델
- 자동 실험 실행
- generic workflow engine
- RDF store, Neo4j, external vector DB 도입
- 모든 기존 API의 즉시 제거 또는 일괄 rename

---

## 5. 용어와 인식 상태

### 5.1 SourceSnapshot

수집된 원문의 불변 식별 단위다.

필수 속성:

- `document_id`
- `source_uri`
- `content_hash`
- `retrieved_at`
- `source_kind`
- `license_or_policy_ref`

URL은 위치일 뿐 identity가 아니다. 동일 URL의 bytes가 바뀌면 새 snapshot이다.

### 5.2 ClaimOccurrence

한 source snapshot의 특정 구간에서 관찰된 하나의 주장 발생이다.

동일한 proposition을 두 논문이 말하면 occurrence는 두 개다. 한 occurrence가
철회되거나 stale 상태가 되어도 다른 occurrence는 보존된다.

### 5.3 Proposition

여러 occurrence를 정규화해 소비자가 질의할 수 있게 만든 node/edge 수준의
projection이다. proposition은 source 자체가 아니며, occurrence를 삭제하거나
대체하지 않는다.

### 5.4 ReviewEvent

사람이 특정 subject를 특정 review axis에서 판정한 append-only event다.

### 5.5 MethodPlan

근거, 조건, 입력, 단계, 측정, decision rule, gap, assumption을 담은 declarative
계획이다. 실행 명령이 아니며 physical/biological/chemical step을 수행하지 않는다.

### 5.6 RunTrace

외부 실행자가 실제로 수행한 활동, 값, deviation, artifact, error, observation을
기록한 별도 산출물이다. MethodPlan과 합치거나 기존 release를 수정하지 않는다.

---

## 6. 상태 축

상태는 독립 축으로 표현한다.

### 6.1 Review state

```text
proposed
accepted
rejected
deferred
disputed
superseded
```

`reopen`은 과거 event를 변경하는 상태가 아니라 새로운 event다. 현재 projection은
event sequence로 계산한다.

### 6.2 Provenance state

```text
incomplete
complete
stale
unresolvable
```

`complete`는 selector와 source identity가 기계적으로 완결됐다는 뜻이다.
truth 또는 validity를 뜻하지 않는다.

### 6.3 Scientific validity state

초기 구현의 기본값은 다음 하나다.

```text
not_assessed
```

도메인별 validation protocol이 생기기 전에는 범용 `valid=true`를 추가하지 않는다.
향후 domain-specific validation이 추가되더라도 review state와 별도 필드로 둔다.

### 6.4 Reproduction state

초기 구현에서는 다음 둘만 허용한다.

```text
not_attempted
attempt_recorded
```

실제 comparator와 tolerance가 정의되기 전에는 `reproduced=true`를 사용하지 않는다.

---

## 7. 목표 아키텍처

```text
SourceSnapshot
      │
      ▼
ClaimOccurrence ────────────────┐
      │                         │
      ▼                         │
KGReviewEvent                   │
      │                         │
      ▼                         │
Accepted Proposition Projection│
      │                         │
      ├─────────────┐           │
      ▼             ▼           │
Ontology View   MethodPlan Draft│
      │             │           │
      │             ▼           │
      │       Method Review     │
      │             │           │
      └──────┬──────┘           │
             ▼                  │
       Immutable Pack v2        │
             │                  │
             ▼                  │
       Read-only MCP            │
                                │
External RunTrace ──────────────┘
        │        imported as new untrusted evidence
        ▼
Reviewed successor release
```

### 7.1 핵심 불변조건

1. AI, score, scheduled job은 `accepted` projection을 만들 수 없다.
2. occurrence는 proposition과 독립적인 identity를 가진다.
3. review history는 update/delete하지 않는다.
4. provenance completeness는 scientific validity로 승격되지 않는다.
5. Pack build는 accepted projection과 accepted occurrence만 소비한다.
6. MCP는 working DB를 authoritative answer source로 사용하지 않는다.
7. RunTrace는 MethodPlan 또는 기존 Pack을 수정하지 않는다.
8. GraphRAG, embedding, community summary는 derived data로 표시한다.

---

## 8. ClaimOccurrence 계약

### 8.1 제안 schema

```sql
CREATE TABLE claim_occurrence (
    id                    TEXT PRIMARY KEY,
    subject_kind          TEXT NOT NULL
                              CHECK (subject_kind IN ('node','edge')),
    subject_id            TEXT NOT NULL,
    document_id           TEXT NOT NULL REFERENCES documents(id),
    document_content_hash TEXT NOT NULL,
    span_start            INTEGER NOT NULL,
    span_end              INTEGER NOT NULL,
    selected_text_hash    TEXT NOT NULL,
    polarity              TEXT NOT NULL
                              CHECK (polarity IN
                                ('supports','contradicts','qualifies','mentions')),
    scope_json            TEXT NOT NULL DEFAULT '{}',
    valid_from            REAL,
    valid_to              REAL,
    selector_state        TEXT NOT NULL
                              CHECK (selector_state IN
                                ('complete','stale','unresolvable')),
    extractor_engine      TEXT,
    extractor_model       TEXT,
    prompt_version        TEXT,
    decode_params         TEXT,
    created_ts            REAL NOT NULL
);
```

### 8.2 selector 검증

`selected_text_hash`는 다음 bytes의 SHA-256이다.

```text
UTF-8(raw_text[span_start:span_end])
```

다음 중 하나라도 실패하면 `selector_state='complete'`가 될 수 없다.

- document content hash 일치
- `0 <= span_start < span_end <= len(raw_text)`
- 선택 구간이 비어 있지 않음
- selected text hash 일치

원문이 없거나 span을 복원할 수 없으면 추정해 채우지 않는다.
`unresolvable`로 남기고 Pack 출고를 막는다.

### 8.3 proposition과의 관계

- node/edge는 정규화된 proposition projection이다.
- occurrence는 node/edge를 support, contradict, qualify, mention할 수 있다.
- 하나의 proposition에 occurrence가 0개이면 evidence-backed Pack에 출고할 수 없다.
- `mentions`만 있는 proposition은 scientific claim으로 출고할 수 없다.
- contradiction은 삭제하지 않고 polarity로 보존한다.

### 8.4 기존 `citations` 마이그레이션

persisted data와 기존 Pack 소비자를 보호하기 위해 단계적으로 전환한다.

1. 새 `claim_occurrence` table을 추가한다.
2. 기존 `citations`를 row 순서까지 보존해 backfill한다.
3. 원문과 span을 읽어 `document_content_hash`와 `selected_text_hash`를 계산한다.
4. 복원 실패 row는 `unresolvable`로 기록하고 release를 막는다.
5. 한 release 동안 `citations`와 `claim_occurrence`를 dual-write한다.
6. parity test가 통과하면 read path를 `claim_occurrence`로 전환한다.
7. Pack v2에는 legacy consumer를 위한 read-only `citations` compatibility view를
   제공할 수 있다. 새 write path는 `claim_occurrence`만 사용한다.

기존 row를 삭제하거나 새 의미로 조용히 재해석하지 않는다.

---

## 9. KGReviewEvent 계약

### 9.1 제안 schema

```sql
CREATE TABLE kg_review_event (
    id            TEXT PRIMARY KEY,
    subject_kind  TEXT NOT NULL
                      CHECK (subject_kind IN
                        ('claim_occurrence','node','edge')),
    subject_id    TEXT NOT NULL,
    review_axis   TEXT NOT NULL
                      CHECK (review_axis IN
                        ('entailment','identity','ontology_fit','applicability')),
    decision      TEXT NOT NULL
                      CHECK (decision IN
                        ('accept','reject','defer','dispute','supersede','reopen')),
    reviewer      TEXT NOT NULL,
    rationale     TEXT NOT NULL,
    created_ts    REAL NOT NULL
);
```

### 9.2 append-only 규칙

DB trigger로 `UPDATE`와 `DELETE`를 거부한다.

```text
BEFORE UPDATE → ABORT
BEFORE DELETE → ABORT
```

현재 review state는 마지막 event 하나만 읽어 결정하지 않는다. 다음 규칙으로
projection한다.

- 동일 axis의 `reopen` 이후에는 새 accept/reject가 있기 전까지 `proposed`
- 서로 독립적인 reviewer의 accept/reject 충돌은 `disputed`
- `supersede`는 predecessor를 보존하고 successor identity를 명시
- review axis가 다르면 서로를 덮어쓰지 않음

### 9.3 기존 review field

`nodes/edges.verified_by`, `verified_ts`, `review_note`는 persisted compatibility를
위해 유지한다. v2 write path는 event를 먼저 append하고 current projection을 기존
column에 반영한다. projection과 event가 불일치하면 Pack build를 거부한다.

### 9.4 자동화 금지

다음 actor는 `accept` event를 만들 수 없다.

- extractor engine
- critic model
- calibration job
- scheduled process
- MCP client

critic score와 confidence는 review queue 정렬에만 사용할 수 있다.

---

## 10. 외부 API와 UI 의미

### 10.1 호환성 원칙

DB의 `verified` 값은 즉시 rename하지 않는다. 외부 response에는 v2 의미를 추가한다.

```json
{
  "legacy_status": "verified",
  "review": {
    "state": "accepted",
    "axis": "identity",
    "reviewer": "local-user"
  },
  "provenance_state": "complete",
  "scientific_validity": "not_assessed",
  "reproduction_state": "not_attempted"
}
```

UI에는 `검증됨` 하나 대신 최소한 다음을 구분해 표시한다.

- 원문 연결 검토
- entity/relation 판정
- ontology mapping 판정
- 과학적 타당성: 미평가

### 10.2 금지 표현

다음 조건에서는 `scientifically verified`, `validated truth`,
`reproduced knowledge`를 출력하지 않는다.

- citation/hash만 존재
- 사람 승인만 존재
- Pack integrity만 통과
- CQ만 통과
- Method compiler gate만 통과

---

## 11. Pack Contract MAJOR 2

### 11.1 물리 구조

```text
packs/<pack_id>/
├── manifest.json
├── pack.sqlite
├── schema.json
└── provenance.jsonl
```

선택된 Method release는 `pack.sqlite` 내부의 compiled Method table과 manifest의
methodology receipt로 식별한다.

### 11.2 artifact descriptor

`manifest.json`은 자신을 제외한 모든 release artifact를 정렬된 descriptor로 담는다.

```json
{
  "contract_major": 2,
  "pack_id": "example-20260813-001",
  "artifacts": [
    {
      "path": "pack.sqlite",
      "media_type": "application/vnd.sqlite3",
      "bytes": 123456,
      "sha256": "sha256:..."
    },
    {
      "path": "provenance.jsonl",
      "media_type": "application/x-ndjson",
      "bytes": 3456,
      "sha256": "sha256:..."
    },
    {
      "path": "schema.json",
      "media_type": "application/json",
      "bytes": 5678,
      "sha256": "sha256:..."
    }
  ]
}
```

`artifacts`는 path 기준 오름차순이며 duplicate, absolute path, `..`, symlink를
허용하지 않는다.

### 11.3 release identity

```text
release_id = sha256(canonical_manifest_bytes)
```

canonical manifest에는 `release_id` 자체를 넣지 않는다. self-reference를 피하기 위해
외부 pack directory name 또는 별도 receipt에서 manifest hash를 release identity로
사용한다.

### 11.4 load-time 검증 순서

MCP는 active pack을 바꾸기 전에 다음 순서로 검증한다.

1. manifest JSON parse와 contract major
2. path safety와 duplicate 검사
3. missing/unlisted artifact 검사
4. bytes와 SHA-256 검사
5. SQLite `integrity_check`
6. expected table과 schema version 검사
7. accepted proposition/occurrence consistency
8. review event projection consistency
9. Method release receipt consistency

모든 검사가 통과한 뒤에만 기존 active connection을 닫고 새 Pack으로 atomic switch한다.

### 11.5 legacy Pack

Pack v1은 불변 상태로 보존한다. v2 loader는 v1을 목록에 표시할 수 있지만, load에는
명시적인 legacy opt-in을 요구한다. 응답에는 다음 warning을 포함한다.

```json
{
  "integrity_scope": "pack_sqlite_only",
  "warning": "legacy pack does not bind every release artifact"
}
```

legacy Pack을 v2라고 재표시하거나 기존 bytes를 수정하지 않는다.

---

## 12. MCP QueryReceipt

모든 knowledge query 응답에 다음 envelope를 붙인다.

```json
{
  "result": {},
  "pack_receipt": {
    "pack_id": "...",
    "release_id": "sha256:...",
    "contract_major": 2,
    "schema_version_ids": [1, 2]
  },
  "query_receipt": {
    "operation": "entity_lookup-v2",
    "compiled_query": {},
    "result_count": 3,
    "truncated": false,
    "warnings": []
  }
}
```

### 12.1 필수 규칙

- compact response에서도 pack identity를 제거하지 않는다.
- source document identity와 accepted occurrence identity를 반환한다.
- asserted relation과 derived summary를 구분한다.
- truncation, pagination, unsupported filter를 숨기지 않는다.
- natural-language query가 deterministic operation으로 변환되면 compiled query를
  receipt에 포함한다.
- GraphRAG/community summary/embedding 결과는 `derived=true`와 생성 방법을 표시한다.
- MCP tool은 working KG를 변경할 수 없다.

---

## 13. MethodPlan 계약

### 13.1 유지할 핵심

- immutable SourceSelector
- `source_supported`, `deterministic_derivation`, `bridge_assumption`,
  `operator_constraint` 구분
- gap inventory
- contradiction과 qualification
- human review receipt
- immutable Method release
- Pack에 명시적으로 선택된 release만 포함

### 13.2 G0–G8의 의미

G0–G8은 contract conformance gate다. 다음을 증명하지 않는다.

- 방법의 과학적 효과
- 실제 실험 성공
- 독립 재현
- 안전성
- 규제 적합성

특히 현행 G7 declarative fixture 검사는 physical execution replay가 아니다.
외부 문서와 UI에서는 `method fixture contract check`로 설명하고, 실제 RunTrace
reproduction과 구분한다.

### 13.3 compiler freeze

real-corpus benchmark 전에는 다음을 추가하지 않는다.

- 새 gate
- 새 epistemic status
- 새 reasoning engine
- workflow execution backend
- 범용 domain ontology

기존 component는 삭제하지 않고 ablation 대상으로 고정한다.

---

## 14. RunTrace 경계

RunTrace는 외부 시스템 또는 사람이 실행한 결과다.

최소 미래 contract:

```json
{
  "run_id": "...",
  "method_release_id": "...",
  "started_at": "...",
  "finished_at": "...",
  "actor": "...",
  "inputs": [],
  "activities": [],
  "outputs": [],
  "deviations": [],
  "errors": [],
  "observations": []
}
```

### 14.1 불변조건

- RunTrace가 MethodPlan bytes를 바꾸지 않는다.
- RunTrace가 current Pack을 수정하지 않는다.
- observation은 새 untrusted ClaimOccurrence 또는 별도 observation proposal로 수입한다.
- failure, null result, deviation도 삭제하지 않는다.
- 사람 검토 후 successor release에만 반영한다.
- OntologyLab은 physical step을 실행하지 않는다.

`ontologylab/trace.py`의 job progress log는 RunTrace가 아니다. 이름이나 문서에서 두
개념을 혼동하지 않는다.

---

## 15. 단계별 구현

### Phase A — Epistemic vocabulary

변경:

- API/MCP response에 분리된 state 추가
- UI label 수정
- `verified`의 정확한 의미 문서화

종료 조건:

- provenance 또는 사람 승인만으로 scientific validity를 표시하는 surface가 없음
- 기존 DB와 Pack bytes는 변경하지 않음

### Phase B — Occurrence and review ledger

변경:

- `claim_occurrence`
- `kg_review_event`
- 기존 citations backfill
- dual-write와 parity receipt

종료 조건:

- independent occurrence, retraction, disagreement, reopen mutation test 통과
- live 사용자 DB가 아닌 fixture/copy에서 migration 검증
- unresolved selector가 Pack build를 fail-closed

### Phase C — Pack v2 and MCP receipt

변경:

- full artifact inventory
- canonical manifest receipt
- atomic load verification
- QueryReceipt

종료 조건:

- 각 artifact byte flip/add/delete mutation이 load 실패를 유발
- failed Pack이 active Pack을 대체하지 않음
- 모든 MCP query가 release identity를 반환

### Phase D — Real-corpus benchmark

변경:

- minimal baseline 구현
- blind task dataset
- reviewer-time 측정
- component ablation

종료 조건:

- preregistered report 생성
- compiler 승격/축소/보류 결정

### Phase E — Method admission

benchmark를 통과한 component만 정식 제품 계약과 Pack capability에 포함한다.

### Phase F — External RunTrace

실제 downstream consumer가 생기고 observation contract가 합의된 뒤 시작한다.

---

## 16. 검증 계획

### 16.1 단위·통합 mutation

| ID | Mutation | 기대 결과 |
| --- | --- | --- |
| M-01 | source bytes 변경 | selector stale, 자동 re-anchor 금지 |
| M-02 | span 1자 이동 | selected text hash mismatch |
| M-03 | 두 source 중 하나 철회 | 다른 occurrence support 유지 |
| M-04 | support와 contradiction 동시 입력 | 둘 다 보존, 단일 truth로 축약 금지 |
| M-05 | review event update/delete | DB abort |
| M-06 | AI actor의 accept event | write 거부 |
| M-07 | occurrence 없이 accepted proposition 출고 | Pack build 거부 |
| M-08 | `schema.json` byte flip | Pack load 거부 |
| M-09 | `provenance.jsonl` 삭제 | Pack load 거부 |
| M-10 | unlisted file 추가 | Pack load 거부 |
| M-11 | 실패 Pack load | 기존 active Pack 유지 |
| M-12 | RunTrace import | current MethodPlan/Pack bytes 불변 |

### 16.2 기존 회귀

- competency Q1/Q2/Q3
- pack build/query
- ontology proposal lifecycle
- MCP pack integrity
- bitemporal edge behavior
- full existing test suite

테스트는 실제 사용자 데이터 경로를 사용하지 않는다. 모든 migration과 Pack test는
`tmp_path` 또는 명시적인 throwaway copy만 사용한다.

---

## 17. Real-corpus falsification benchmark

### 17.1 비교군

**Minimal evidence spine**

```text
document store
+ exact source spans
+ append-only reviewer decisions
+ versioned releases
+ BM25/vector retrieval
```

**Full candidate**

```text
minimal evidence spine
+ ontology/KG projection
+ Method compiler
+ gap/bridge model
+ G0–G8
+ graph retrieval/derived summaries
```

### 17.2 dataset

- 서로 다른 실제 corpus 최소 3개
- blind task 최소 100개
- task family:
  - fact retrieval
  - method reconstruction
  - conflict detection
- gold answer와 source span을 독립적으로 확정

constructed agrochem fixture는 regression에는 사용하지만 representative benchmark
결론에는 사용하지 않는다.

### 17.3 초기 admission threshold

Full candidate는 lower 95% confidence bound 기준으로 다음 중 하나를 만족해야 한다.

1. correctness가 minimal baseline보다 5 percentage points 이상 개선
2. correctness가 2 points 이상 나빠지지 않으면서 reviewer time 30% 이상 감소

공통 조건:

- total latency와 비용이 baseline의 2배 이하
- source-supported answer precision이 저하되지 않음
- unsupported claim rate가 증가하지 않음

이 수치는 보편적인 학술 기준이 아니라 이번 architecture를 공격하기 위한 초기
preregistered kill threshold다. 실험 시작 전에 owner와 evaluator가 확정한다.

### 17.4 component ablation

각 compiler component는 제거 전후를 비교한다.

다음 둘 모두에 미달하면 optional/deferred 후보로 이동한다.

- correctness 변화 2 percentage points
- reviewer time 변화 10%

---

## 18. 인수 기준

### AC-01 — 의미 분리

사람 승인, provenance completeness, scientific validity, reproduction state가
독립 필드로 노출된다.

### AC-02 — 독립 occurrence

동일 proposition의 여러 source occurrence가 각각 독립 identity와 review history를
가진다.

### AC-03 — 사람 전용 transition

AI, score, batch job, MCP가 accept event를 만들 수 없다.

### AC-04 — append-only governance

review event와 release는 update/delete할 수 없으며 reopen/supersede는 새 event다.

### AC-05 — contradiction preservation

support, contradiction, qualification이 serialization과 Pack을 거친 뒤에도 보존된다.

### AC-06 — Pack 전체 무결성

`pack.sqlite`, `schema.json`, `provenance.jsonl` 중 어느 하나의 bytes가 바뀌어도
load가 실패한다.

### AC-07 — atomic Pack switch

새 Pack 검증 실패 시 기존 active Pack과 connection이 유지된다.

### AC-08 — query traceability

모든 MCP knowledge response가 Pack release identity, operation, truncation,
source occurrence를 반환한다.

### AC-09 — declarative Method

Method compiler, replay, MCP 어느 경로도 physical step을 실행하지 않는다.

### AC-10 — evidence-bound admission

Method compiler의 정식 승격은 real-corpus benchmark 결과와 component ablation
receipt 없이는 허용되지 않는다.

---

## 19. 예상 파일 영향도

| 파일/영역 | 예상 변경 |
| --- | --- |
| `ontologylab/kgstore.py` | occurrence/review schema, migration, projection |
| `ontologylab/models.py` | SourceSelector, occurrence/review DTO |
| `ontologylab/proposals.py` | occurrence 생성과 review binding |
| `ontologylab/packbuilder.py` | Pack v2 inventory, accepted occurrence export |
| `ontologylab/mcp_server.py` | full Pack verification, QueryReceipt |
| `ontologylab/server/schemas.py` | v2 API response model |
| `ontologylab/server/routes.py` | explicit review-axis commands |
| `ontologylab/competency.py` | v2 provenance/pack CQ |
| `ontologylab/method_*` | freeze, terminology clarification, ablation hooks |
| `tests/` | migration, mutation, benchmark contract |
| `docs/ARCHITECTURE.md` | 승인 후 target architecture 반영 |
| `docs/PRODUCT_SPEC.md` | 승인 후 `verified` 의미 정정 |

대규모 동시 rewrite를 금지한다. Phase별로 기존 동작을 고정하는 테스트를 먼저 만들고
작은 migration 단위로 진행한다.

---

## 20. 구현자가 지켜야 할 운영 제약

1. 정본 프로젝트 경로는 `/Users/hyunjun/Documents/MUNI/ontologylab`이다.
2. live data는 `./data`가 아니라 Application Support 경로에 있을 수 있다.
3. 테스트와 migration rehearsal은 live data를 열지 않는다.
4. 기존 Pack bytes를 수정하지 않는다.
5. Method 작업트리 파일을 canonical HEAD 기능으로 오인하지 않는다.
6. source가 없는 값을 backfill 과정에서 추정하거나 생성하지 않는다.
7. type/lint/test 실패를 suppress하지 않는다.
8. destructive Git command를 사용하지 않는다.

---

## 21. 전달 체크리스트

- [ ] owner가 `verified`의 v2 외부 의미를 승인했다.
- [ ] ClaimOccurrence schema와 polarity vocabulary가 승인됐다.
- [ ] KGReviewEvent axis와 decision vocabulary가 승인됐다.
- [ ] Pack contract MAJOR 2 migration 정책이 승인됐다.
- [ ] legacy Pack load 정책이 승인됐다.
- [ ] Method compiler freeze 범위가 승인됐다.
- [ ] benchmark corpus와 evaluator가 지정됐다.
- [ ] preregistered threshold가 실험 전에 고정됐다.
- [ ] Phase A–F가 각각 독립 PR/작업 단위로 나뉘었다.
- [ ] 각 Phase에 mutation proof와 manual QA가 배정됐다.

---

## 22. 관련 문서

- [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`DESIGN-RATIONALE.md`](DESIGN-RATIONALE.md)
- [`ROADMAP.md`](ROADMAP.md)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- [W3C SHACL](https://www.w3.org/TR/shacl/)
- [OWL 2 Open World Reasoning](https://www.w3.org/TR/owl2-primer/#Open_World_Reasoning)
- [FAIR Guiding Principles](https://doi.org/10.1038/sdata.2016.18)
- [RO-Crate](https://www.researchobject.org/ro-crate/)

---

## 23. 최종 구현 판단

OntologyLab의 다음 진화는 ontology class와 compiler gate를 더 많이 만드는 방향이
아니다. 먼저 다음 사실을 기계적으로 증명할 수 있어야 한다.

```text
어떤 source bytes의 어느 span에서
어떤 occurrence가 만들어졌고,
누가 어떤 축에서 무엇을 판정했으며,
어떤 immutable release가
어떤 query 결과를 반환했는가.
```

이 evidence spine이 real-corpus benchmark에서 확인된 뒤에만 Methodology Compiler의
추가 복잡성을 정식 제품 구조로 인정한다.
