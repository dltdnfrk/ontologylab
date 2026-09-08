# OntologyLab Wave 2.1 수집 파이프라인 재귀 개선 계획 — R10

- **작성일:** 2026-08-20
- **기준 커밋:** `bed13a80b1bdbb9d605b0bc34c42771576ca310e`
- **목적:** Wave 2.1의 DOI/provenance 수렴을 10차례 적대적으로 재검토해 구현 가능한 수정·고도화 계획으로 수렴
- **범위:** ingestion identity, immutable evidence, migration, provenance, extraction, pack/MCP, API/CLI/research, mutation gates
- **현재 상태:** 계획만 작성. 이 문서 작성 시 소스 수정·커밋·실데이터 접근 없음

## 0. 최종 결론

`bed13a8`은 세 주 진입점의 persistence 호출을 하나로 모으고 provenance 필드 손실을 막았다. 그러나 현재 `documents` 한 행은 다음 세 의미를 동시에 갖는다.

1. 논문/저작물의 **Work identity**
2. character span이 좌표를 갖는 정확한 **Representation**
3. connector/source/grade/fetch를 뜻하는 **Acquisition observation**

이 세 축은 수명과 불변식이 다르므로 한 행으로 유지할 수 없다.

### 최종 선택

- **Work:** DOI 등 서지 identity와 merge/redirect lifecycle
- **Representation:** citation과 extraction이 참조하는 불변 원문 좌표
- **Observation:** 언제, 어느 connector/URI/grade/run에서 representation을 관측했는지

Citation은 Work나 “현재 문서”가 아니라 항상 immutable Representation을 가리킨다.

### 필수 truth table

| 입력 | 반드시 나와야 하는 결과 |
|---|---|
| 같은 DOI, 다른 bytes | Work 1개, Representation 2개, Observation 2개 |
| 다른 DOI, 같은 bytes | Work 2개, Representation association 2개. bytes 물리 공유는 선택사항 |
| DOI 없음 → 나중에 DOI 발견 | stable source key가 continuity를 증명할 때만 identifier attach; 아니면 reconciliation candidate |
| 정확한 retry | 동일 Work/Representation, 새 Observation 또는 idempotency-key 기준 동일 Observation |
| 같은 DOI의 full text 도착 | 기존 abstract는 보존, full-text Representation 추가, 이후 extraction은 명시적으로 새 representation 사용 |
| Work merge | citation/document ID를 rewrite하지 않고 audited redirect로 canonicalize |

---

# 1. 10차 재귀 개선 기록

각 차수는 `제안 → 적대적 반례 → 수정된 결정` 순서다.

## R1 — Wave 2.1을 최소 patch로 닫으려는 안

### 제안

- `packbuilder`의 document projection에 `doi` 추가
- DOI가 있으면 DOI로 dedupe, 없으면 content hash 사용
- duplicate provenance에 incoming URI/hash 추가

### 적대적 반례

1. 같은 DOI의 abstract 후 full text가 오면 `kgstore.py:2003-2014`가 오래된 행을 즉시 반환한다.
2. full-text fetch 성공은 `server/jobs.py:874-885`에 기록되지만 extraction은 오래된 doc ID를 사용한다: `server/jobs.py:894-895`, `extractor.py:750-752`.
3. 서로 다른 DOI가 같은 bytes이면 content hash fallback이 두 Work를 합친다: `kgstore.py:2009-2014,2062-2069`.
4. live DB의 DOI는 pack projection에서 빠진다: `packbuilder.py:97-100,472-479`.

### 수정된 결정

단순 field patch는 **즉시 hotfix**로는 필요하지만 최종 모델이 될 수 없다. Wave 2.1은 GREEN이 아니라 “principal-path field preservation”까지만 완료된 것으로 표현한다.

---

## R2 — 기존 document 행을 최신/fullest 본문으로 갱신하는 안

### 제안

같은 DOI의 더 긴 본문이 오면 기존 `raw_text_path`, `content_hash`, source, grade를 update한다.

### 적대적 반례

- node/edge/citation은 `documents.id`와 character span을 참조한다: `kgstore.py:230-243,279-292,320-333`.
- review와 extraction은 path의 현재 bytes를 다시 읽는다: `kgstore.py:2115-2117,4113-4147`.
- 기존 본문을 바꾸면 승인 당시 span이 다른 문자열을 가리키거나 범위를 벗어난다.
- 이미 verified/packed된 사실의 source receipt가 사후 변경된다.

### 수정된 결정

**Representation은 한 번 참조되면 절대 갱신하지 않는다.** 새 bytes는 새 representation ID다. “preferred representation”은 future extraction/UI selection pointer일 뿐 기존 evidence를 대체하지 않는다.

---

## R3 — Work / Representation / Observation 3축 도메인 모델

### 제안

기존 `documents.id`를 Representation ID로 보존하고 다음을 추가한다.

```sql
CREATE TABLE works (
    id              TEXT PRIMARY KEY,
    merged_into     TEXT REFERENCES works(id),
    created_ts      REAL NOT NULL,
    CHECK (id <> merged_into)
);

CREATE TABLE work_identifiers (
    id                       TEXT PRIMARY KEY,
    work_id                  TEXT NOT NULL REFERENCES works(id),
    scheme                   TEXT NOT NULL,
    normalized_value         TEXT NOT NULL,
    raw_value                TEXT NOT NULL,
    status                   TEXT NOT NULL,
    asserted_by_observation  TEXT,
    asserted_ts              REAL NOT NULL,
    retracted_ts             REAL
);

CREATE UNIQUE INDEX idx_active_work_identifier
ON work_identifiers(scheme, normalized_value)
WHERE status='accepted' AND retracted_ts IS NULL;

CREATE TABLE document_observations (
    id               TEXT PRIMARY KEY,
    work_id          TEXT REFERENCES works(id),
    document_id      TEXT NOT NULL REFERENCES documents(id),
    run_id           TEXT,
    source_kind      TEXT NOT NULL,
    source_uri       TEXT NOT NULL,
    source           TEXT NOT NULL,
    evidence_grade   TEXT NOT NULL,
    title            TEXT,
    fetched_ts       REAL NOT NULL,
    representation_kind TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);
```

`documents`에는 `work_id`, `coordinate_profile`, `representation_kind`, optional `supersedes_document_id`를 추가한다.

### 적대적 반례

- global `UNIQUE(content_hash)`를 그대로 두면 다른 DOI/같은 bytes가 다시 합쳐진다: `kgstore.py:213-228`.
- `UNIQUE(doi)`를 그대로 두면 같은 DOI의 두 representation을 저장할 수 없다: `kgstore.py:772-775`.
- flat `documents.source/grade/doi`를 authority로 남기면 observation 테이블과 두 개의 진실이 생긴다.
- Work merge 시 모든 `documents.work_id`를 rewrite하면 과거 identity history가 사라진다.

### 수정된 결정

- `documents`의 inline global content uniqueness와 DOI uniqueness를 제거한다.
- Representation dedupe는 `(work_id, content_hash, coordinate_profile)` 범위다.
- Work merge는 `merged_into` redirect이며 document/citation ID를 rewrite하지 않는다.
- 기존 flat DOI/source/grade는 한 release 동안 compatibility projection으로만 유지하고 authority가 아님을 명시한다.
- storage 절약용 global `ContentBlob` 분리는 correctness가 안정된 이후로 미룬다. 초기 구현은 bytes 중복을 허용한다.

---

## R4 — Identifier resolver와 DOI 규칙

### 제안

DOI normalization 후 active identifier unique index로 Work를 찾는다.

### 적대적 반례

- 현재 `normalize_doi()`는 `10.`으로 시작하는 거의 모든 문자열을 받아들인다: `connectors/base.py:38-51`.
- terminal `)`를 무조건 제거하여 합법적인 balanced suffix를 바꿀 수 있다.
- content hash가 같다는 사실만으로 DOI 없는 Work에 DOI를 붙이면 서로 다른 저작물을 false-merge할 수 있다.
- fuzzy title/author matching을 자동 merge에 사용하면 오탐 복구가 어렵다.

### 수정된 결정

1. DOI canonicalization과 validation을 분리한다.
2. resolver URL/prefix/case는 canonicalize하되 legal suffix punctuation을 임의로 제거하지 않는다.
3. 최소 grammar는 registrant + `/` + non-whitespace suffix를 요구하고 control character를 거부한다.
4. normalization version을 identifier assertion에 기록한다.
5. late DOI 자동 attach는 connector가 제공한 stable key나 exact resolver URI가 continuity를 증명할 때만 허용한다.
6. hash/title/fuzzy match는 `identity_action='merge_candidate'`이며 사람이 판단한다.
7. conflicting accepted DOI는 typed `identifier_conflict`이고 ordinary duplicate로 흡수하지 않는다.

---

## R5 — Extraction lifecycle이 content hash에 전역 결합된 문제

### 제안

Document constraint만 고치고 extraction은 그대로 둔다.

### 적대적 반례

`extraction_runs`의 unique identity와 lookup은 document ID가 아니라 global content hash 중심이다: `extraction_state.py:18-39,254-281`.

서로 다른 Work가 같은 bytes를 가진 경우 두 Representation을 허용해도 두 번째 representation은 첫 run을 재사용해 자기 `source_doc_id` citation을 만들지 못한다.

### 수정된 결정

- lifecycle identity에 `document_id/representation_id`를 포함한다.
- `document_content_hash`는 integrity assertion이지 document identity가 아니다.
- 동일 bytes의 model output 재사용이 필요하면 별도의 optional engine-output cache를 content hash로 두되, proposal/citation materialization은 각 Representation ID에 다시 bind한다.
- existing extraction run ID와 document ID는 migration에서 그대로 보존한다.
- lifecycle migration 뒤 다음 invariant를 검사한다.

```text
run.document_id == cited source_doc_id context
run.document_content_hash == hash(representation bytes)
```

---

## R6 — 실제 legacy migration

### 제안

nullable DOI column과 index만 추가한다.

### 적대적 반례

현재 migration은 column/index만 추가하고 기존 row를 backfill하지 않는다: `kgstore.py:757-775`. 현재 테스트는 빈 DB에서 column을 제거한 뒤 migration 이후에만 데이터를 넣는다: `tests/test_kgstore.py:447-477`.

실제 legacy `source_uri=https://doi.org/...`, `doi=NULL` row는 재수집 시 두 번째 문서가 된다.

### 수정된 결정

#### Migration 입력 fixture

테스트에서 현재 schema를 만든 뒤 column을 drop하지 않는다. Git에 보존한 versioned historical DDL로 다음 DB를 직접 만든다.

- pre-source/evidence/DOI + 실제 기존 row/artifact/node/citation
- source/evidence는 있으나 DOI 없음
- DOI column은 있으나 index 없음
- mixed case/resolver DOI
- normalization 후 collision하는 identifier
- 동일 DOI/다른 hash
- 다른 DOI/동일 hash
- 중간 migration 실패 상태
- legacy read-only pack

#### Migration 순서

1. 단순 파일 copy가 아니라 SQLite backup API로 WAL-consistent backup과 live schema fingerprint 기록
2. 짧은 expand migration: migration ledger와 새 테이블, **non-unique** identifier lookup index만 추가
3. 새 binary가 identifier를 dual-write하되 dedupe는 compare-only telemetry로 시작
4. versioned cursor를 사용해 legacy document마다 Work 생성
5. explicit DOI 또는 정확히 parse 가능한 `doi.org` URI만 identifier assertion으로 backfill
6. DOI collision은 한 Work에 여러 immutable representations로 연결; history 삭제 금지
7. shadow copy에서 documents table rebuild를 rehearsal: ID/path 유지, global hash/DOI uniqueness 제거, `work_id` 추가
8. extraction_runs identity rebuild: representation ID 포함
9. 기존 flat metadata로 `legacy_backfill` Observation 1개 생성
10. old writer를 drain/deny한 maintenance window에서 actual rebuild와 accepted-identifier unique index 활성화
11. `index_list/index_xinfo`, rollback-only duplicate probe, `foreign_key_check`, `integrity_check`, row/file/hash/count 검증

SQLite에는 truly concurrent index build가 없다. Startup의 일반 `KGStore.open()`에서 대형 unique index/backfill을 암묵적으로 실행하지 말고 schema readiness를 노출한다. Migration은 두 번 실행해도 동일해야 하고 failpoint에서 전부 rollback되어야 한다. Read-only pack은 in-place migrate하지 않는다.

이미 기존 코드가 버린 full text나 두 번째 DOI는 복구할 수 없다. 로그에 없는 history를 만들어내지 말고 재수집/reconciliation 대상으로 표시한다.

---

## R7 — DB와 JSON provenance의 원자성

### 제안

`insert_document()` 후 `provenance.log()`를 호출한다.

### 적대적 반례

- document/artifact는 `kgstore.py:2070-2082`에서 commit된다.
- 그 뒤 `ingestion.py:63-75`가 JSONL을 쓴다.
- JSONL write가 실패하면 API는 오류지만 DB row와 raw file은 남는다.
- duplicate event는 stored URI와 incoming char count를 혼합한다.
- batch k번째 실패 시 앞 문서는 이미 commit됐는데 `IngestionResult`는 “Complete result”라고 부른다.
- `insert_document()`의 성공은 무조건 `commit()`, duplicate recovery는 connection-wide `rollback()`을 호출한다: `kgstore.py:2053-2082`. 따라서 `store.atomic()` 안에서 caller의 이후 실패가 document를 되돌리지 못하거나 duplicate가 앞선 unrelated write를 rollback할 수 있다: `kgstore.py:594-621`.

### 수정된 결정

#### SQLite가 audit truth

`document_observations`와 `provenance_outbox`를 document/work/artifact와 같은 transaction에 기록한다. JSONL은 outbox mirror다. Store method는 method-owned SAVEPOINT 또는 outer UoW를 따르며 자체 unconditional commit/rollback을 하지 않는다.

```text
owner-only staging file write + fsync
→ BEGIN IMMEDIATE / caller-owned SAVEPOINT
→ resolve Work/identifier
→ insert/reuse Representation(state='staged', staging_path)
→ insert Observation
→ insert source_doc artifact
→ insert provenance_outbox event
→ COMMIT
→ atomic rename to final path + parent-directory fsync
→ short transaction: Representation state='ready'
→ JSONL mirror + outbox delivered mark
```

Reader/extractor/pack은 `state='ready'`만 사용한다. Commit 후 rename 전에 crash해도 startup reconciler가 durable staging row/file을 finalize할 수 있다. Filesystem과 SQLite의 완전한 atomic commit은 불가능하므로 상태 기계와 startup reconciliation을 명시한다.

- DB에 없는 staging/final file: quarantine 후 age-based cleanup
- staged DB row와 staging file: finalize/retry
- ready DB row인데 file 없음/hash mismatch: integrity failure, 자동 성공 금지
- commit됐으나 JSONL mirror 실패: API 데이터 성공은 유지하고 `audit_mirror_pending=true`, background/reopen 시 retry

Batch는 per-document atomic으로 유지하되 `status=complete|partial|failed`, item별 outcome을 반환한다. `collect.end`는 모든 item outcome이 durable해진 뒤 한 번만 생성한다.

---

## R8 — 모든 entrypoint와 public result contract

### 제안

현재 `(Document, created: bool)`를 계속 사용한다.

### 적대적 반례

이 boolean은 다음을 구분하지 못한다.

- exact retry
- same Work / new Representation
- late identifier attach
- new Observation only
- identifier conflict
- reconciliation candidate

또한 `/collect/sample`은 shared seam을 우회한다: `server/routes.py:1819-1836`. Research만 `collapse_duplicates()`로 longest winner를 고르고 CLI/API는 순서상 첫 문서를 고른다: `server/jobs.py:868`, `connectors/base.py:94-130`, `main.py:480-523`, `server/routes.py:1736-1797`.

### 수정된 결정

새 contract:

```text
IngestOutcome(
  work_id,
  canonical_work_id,
  representation_id,
  observation_id,
  work_created,
  representation_created,
  observation_created,
  identity_action = matched_identifier | attached_identifier |
                    provisional | merge_candidate | identifier_conflict,
  extraction_action = new_representation | already_extracted | queued
)
```

한 compatibility release 동안:

- `.document` → Representation projection
- `.created` → `representation_created`
- 기존 `documents/created/duplicates` 유지하되 deprecated 표시
- 새 counters: `works_created`, `representations_created`, `observations_recorded`, `identity_conflicts`

CLI, `/api/collect`, research, `/collect/sample`은 같은 application service를 호출한다. Competency fixture seed는 production ingestion이 아니라는 점을 명시하거나 별도 fixture helper로 이름을 분리한다.

`collapse_duplicates`는 비승자 observation을 삭제하지 않는다. 모든 observation을 저장한 뒤 preferred representation/extraction selection만 결정한다.

---

## R9 — Pack / MCP publication contract

### 제안

새 live schema만 고치고 pack은 기존 document row를 복사한다.

### 적대적 반례

- 현재 pack projection은 DOI도 누락한다: `packbuilder.py:97-100,472-479`.
- Work/identifier/observation/redirect closure가 없으면 pack의 document ID가 어떤 저작물인지 독립적으로 판별할 수 없다.
- `raw_text_path`는 복사하지만 source bytes를 pack에 넣는 경로가 확인되지 않는다. 경로만 남기면 독립 pack에서 evidence text를 열 수 없다.
- source full text는 라이선스상 pack에 포함할 수 없을 수 있다.
- old read-only packs는 migrate하지 않는다: `kgstore.py:748-755`.

### 수정된 결정

Pack schema MAJOR 또는 capability version을 올리고 다음 closure를 고정한다.

1. verified node/edge가 참조하는 Representation
2. selected Method release가 참조하는 source Representation
3. 해당 Representation의 Work
4. active identifier와 relevant historical assertion
5. canonical redirect chain
6. 해당 Representation을 설명하는 Observation
7. citation document hash, selected-text hash, coordinate profile
8. semantic-staleness fingerprint에 occurrence/representation hash/state

Graph document copy와 Method selection은 현재 서로 다른 시점에 수행된다: `packbuilder.py:472-520,562-590`. 두 closure 중 하나라도 빠지면 pack build가 실패해야 한다.

Pack manifest에 다음 counts/receipt를 추가한다.

```text
works
representations
observations
identifier_assertions
identity_conflicts_excluded
source_material_policy
pack_schema_version
```

Source bytes 정책:

- 배포 허용: pack 내부 immutable source snapshot/excerpt와 hash 포함
- 배포 불가: bytes 미포함을 명시하고 URI, hash, selected excerpt policy/receipt만 포함
- 어떤 경우에도 존재하지 않는 `raw_text_path`를 usable source처럼 노출하지 않음

Pack build, scan, load, MCP resource/tool이 동일한 verified opener를 사용한다. 현재 tree receipt는 정적 세 파일만 열거한다: `packbuilder.py:917-936`. Source snapshot/excerpt payload를 추가할 때는 manifest의 정렬된 artifact inventory가 모든 payload의 path/size/hash/policy를 bind해야 하며, **미등록 파일 추가도** 검증 실패여야 한다. Existing tree receipt(`pack.sqlite`, `schema.json`, `provenance.jsonl`)와 새 identity/source payload 모두 mutation으로 검증한다.

API의 `/documents`, `/artifacts`, review context와 semantic staleness도 동일 typed serializer/representation selector를 사용한다. Hand-written projection을 각각 유지하면 다음 additive field가 다시 누락된다: `server/routes.py:1455-1520`, `kgstore.py:4113-4220`, `semantic_staleness.py:33-101`.

MCP response는 최소 다음을 반환한다.

```text
work_id
accepted identifiers (DOI 등)
representation_id
representation_content_hash
source_document_ids
observation/source/grade summary
pack_id + pack content hash
```

Old pack은 compatibility reader로 읽고 절대 rewrite하지 않는다.

---

## R10 — 테스트가 계획을 속이지 못하게 하는 최종 gate

### 제안

전체 suite GREEN과 몇 개의 example test로 완료한다.

### 적대적 반례

`2315 passed` 상태에서도 다음 현행 결함이 존재했다.

- 같은 DOI의 full text 폐기
- legacy DOI 미backfill
- 다른 DOI/같은 bytes false merge
- duplicate provenance hybrid event
- pack DOI 누락
- sample entrypoint seam 우회

따라서 coverage나 전체 count는 release gate가 아니다.

### 수정된 결정

#### Property/state model

```text
ABSENT
→ WORK_IDENTIFIED/PROVISIONAL
→ REPRESENTATION_DURABLE
→ OBSERVATION_AUDITED
→ EXTRACTED
→ CITED/REVIEWED
→ PACKED
→ MCP_SERVED
```

각 prefix에서 row/file/hash/artifact/outbox/citation/pack identity가 일치해야 한다.

#### 필수 mutation matrix

| Mutant/현재 반례 | 반드시 RED가 되는 gate |
|---|---|
| source/grade/DOI 필드 하나 제거 | CLI/API/research/sample canonical receipt |
| fulltext `replace()`를 수동 재구성으로 회귀 | fulltext property + research extraction hash |
| DOI normalize/query/identifier unique 제거 | DOI corpus + concurrency |
| different DOI/same bytes를 hash merge | Work truth-table test |
| same DOI/new bytes를 old row 반환 | two Representation test |
| legacy backfill 제거 | populated historical DB replay |
| extraction identity에서 representation ID 제거 | same bytes/different Work citation test |
| Observation/outbox insert 제거 | DB/JSON audit reconciliation test |
| `collect.end` 조기 기록 | batch failpoint state-machine test |
| unrelated IntegrityError를 duplicate로 삼킴 | typed constraint fault test |
| entrypoint가 service 우회 | behavioral spy + receipt matrix |
| pack DOI/work/observation projection 누락 | pack DB + real stdio MCP receipt |
| source file/path/hash tamper | build/load/resource fail-closed test |
| migration 중간 실패 commit | before/after DB checksum test |

#### Cross-entrypoint receipt

한 fixture를 direct service, real CLI, TestClient API, real JobRegistry research worker, pack, actual stdio MCP까지 통과시킨다. Random ID/timestamp를 제외한 canonical receipt를 비교한다.

#### Concurrency/faults

- 2/8 thread 및 process, connection per writer
- same DOI/different bytes
- different DOI/same bytes
- late DOI attach와 conflict
- raw write, DB insert, artifact, observation, commit, JSON mirror, pack copy/rename 단계별 failpoint
- crash/reopen 후 rollback 또는 typed recoverable state

#### 성능 구조 gate

- identifier lookup은 index 사용
- SQL/file operation O(N)
- duplicate-only replay가 raw disk를 증가시키지 않음
- `T(2N)/T(N) <= 2.5` at 100/1,000/10,000
- 8-way local collision은 외부 lock이 없을 때 bounded completion

---

# 2. 최종 target architecture

## 2.1 Authority matrix

| 속성 | Authority | 변경 규칙 |
|---|---|---|
| DOI/PMID/arXiv ID | WorkIdentifier | assertion lifecycle/redirect로 변경, 파괴적 overwrite 금지 |
| canonical Work | Works redirect resolver | cycle-free, audited |
| raw bytes/path/hash | Representation(Document) | 한 번 참조되면 immutable |
| coordinate profile | Representation | versioned, immutable |
| source URI/connector/grade/fetch time | Observation | append-only |
| preferred text | Work pointer/policy | future extraction에만 영향 |
| source span | Citation → Representation | 기존 좌표 영구 유지 |
| collection event | Observation + DB outbox | JSONL은 mirror |
| published identity | Pack closure | build 시점 frozen |

## 2.2 Citation receipt 강화

Core citation에 Method subsystem의 더 강한 선례를 적용한다: `method_store.py:59-72`.

필수 필드:

```text
representation_id
representation_content_hash
span_start
span_end
selected_text_hash
coordinate_profile
```

검증 시점:

1. citation write
2. review presentation
3. pack build
4. pack open/resource read

조건:

```text
0 <= start < end <= len(text)
hash(text) == representation_content_hash
hash(text[start:end]) == selected_text_hash
```

Bad legacy span은 추측해 고치지 않고 `invalid_legacy_evidence`로 격리한다.

## 2.3 Merge와 split

- Work merge: `merged_into` redirect + actor/reason/timestamp
- identifier retraction/reattach 가능
- representation/citation ID rewrite 금지
- redirect cycle 차단
- false merge 복구를 위해 identifier assertion history 보존
- bytes/hash는 Work merge 근거가 아님

---

# 3. 최종 10단계 구현 순서

각 단계는 독립 commit과 RED→GREEN mutation receipt를 가진다.

## Step 1 — Characterization freeze

- 현재 다섯 반례를 테스트로 고정: fulltext discard, legacy late DOI, distinct DOI/same bytes, hybrid provenance, pack DOI loss
- current behavior를 원하는 값으로 pin하지 말고 새 truth table을 pin
- 제품 문구를 `principal entrypoint field preservation`으로 일시 강등

**Exit:** 새 테스트가 현재 `bed13a8`에서 예상대로 RED.

## Step 2 — Pack DOI hotfix

- `_PACK_COPY_COLUMNS['documents']`에 DOI 추가
- working→pack→read-only KGStore→MCP metadata round trip
- pack schema/index 차이를 명시

**Exit:** DOI omission mutant RED. 이 단계는 target model 이전의 즉시 손실 방지다.

## Step 3 — Additive identity schema

- works, work_identifiers, observations, migration ledger/outbox 추가
- resolver와 cycle-free canonical Work helper
- old callers는 아직 기존 path 유지

**Exit:** 새 schema 두 번 open idempotent, foreign key/integrity GREEN.

## Step 4 — Historical migration and document rebuild

- versioned historical fixtures와 SQLite backup API shadow rehearsal
- expand/dual-write/backfill/validate/enforce 단계 분리
- old writer drain/deny와 schema readiness
- documents ID/path 유지
- global content/DOI uniqueness 제거 및 work-scoped representation identity
- populated legacy row backfill
- extraction_runs representation identity migration

**Exit:** failpoint rollback, idempotent resume, index definition/probe, row/file/hash parity, real legacy replay GREEN.

## Step 5 — Atomic ingestion service v2

- Work resolve → Representation create/reuse → Observation → artifact → outbox를 한 caller-owned transaction/SAVEPOINT으로
- store method의 unconditional commit/rollback 제거
- raw staged/ready state + fsync/rename/reconciler
- typed conflict/partial outcomes

**Exit:** outer `store.atomic()` rollback을 포함한 모든 DB/file/provenance failpoint GREEN.

## Step 6 — Entrypoint convergence v2

- CLI, `/api/collect`, research, sample이 v2 service 사용
- `collapse_duplicates`를 lossy deletion이 아닌 selection policy로 변경
- compatibility counters와 새 counters 동시 제공

**Exit:** 모든 순서 permutation의 canonical receipt 일치.

## Step 7 — Extraction/citation identity

- lifecycle key에 representation ID 포함
- citation hash receipt와 immutable guard
- preferred representation은 future extraction만 선택

**Exit:** same Work/two representations 및 different Work/same bytes 모두 올바른 citation을 가짐.

## Step 8 — Pack/MCP identity closure v2

- Work/identifier/redirect/observation/representation/citation receipt copy
- source material licensing policy
- pack schema version + old reader compatibility
- actual stdio MCP receipt

**Exit:** pack 독립 상태에서 work/representation/source receipt가 resolve되고 tamper mutant가 RED.

## Step 9 — Reconciliation and operator surface

- identity conflict/merge candidate 목록
- accepted identifier attach/retract/merge redirect CLI
- legacy unrecoverable history와 re-fetch 필요 상태 표시
- `/api/documents` compatibility projection 및 `/works`, `/representations` API

**Exit:** destructive auto-merge 없음, 모든 결정에 actor/reason/audit event 존재.

## Step 10 — Mutation/release gate

- critical mutation 100%, total target ≥90%
- full suite + property + concurrency + migration + pack/MCP stdio
- performance bounds/EXPLAIN receipt
- before/after Git and real-data isolation receipt
- claim 문구를 실제 보장 수준과 다시 대조

**Exit:** 반례·mutant·migration·actual transport가 모두 GREEN일 때만 Wave 2.1 lineage를 “lossless/converged”로 승격.

---

# 4. 비범위와 과설계 방지

이번 개선에서 하지 않는다.

- fuzzy automatic work merge
- external graph DB/RDF migration
- hosted multi-user identity/auth
- global blob GC 최적화
- 모든 source metadata를 canonical Work 속성으로 승격
- 기존 pack in-place rewrite
- 과거에 버린 full text/DOI history의 추정 복원

Global `ContentBlob` 물리 dedupe는 두 Work/같은 bytes correctness가 먼저 안정된 뒤 별도 성능 evidence가 있을 때만 도입한다.

---

# 5. 롤백과 운영 원칙

1. Migration 전에 SQLite backup API로 WAL-consistent DB backup과 schema fingerprint를 남긴다. `kg.sqlite` 파일만 복사하지 않는다.
2. raw files는 migration에서 rewrite하지 않는다.
3. 기존 document/citation/node/edge ID는 유지한다.
4. 새 reader 배포 전 old field를 제거하지 않는다.
5. 새 pack은 versioned schema, old pack은 read-only compatibility reader로만 처리한다.
6. migration conflict는 typed report로 중단하며 임의 winner를 고르지 않는다.
7. outbox pending은 데이터 손실이 아니라 observable degraded state로 표시한다.
8. 실제 Application Support DB에 적용하기 전 representative copy에서 dry-run report를 생성한다.
9. rollback은 DB backup restore + 새 orphan temp cleanup만 수행한다.
10. 각 단계는 단독 revert 가능해야 하며 다음 단계와 한 commit에 섞지 않는다.

---

# 6. 완료 정의

다음 문장이 모두 참일 때만 완료다.

- DOI는 Work identity이며 content hash가 Work equality를 결정하지 않는다.
- 같은 DOI의 새 full text는 사라지지 않고 새 immutable Representation이 된다.
- 과거 citation의 bytes/span/hash는 영구히 동일하다.
- 모든 fetch attempt는 Observation으로 감사 가능하다.
- DB commit과 audit truth가 분리되지 않는다.
- 기존 실제 row가 migration 후 동일 Work로 수렴한다.
- distinct DOI/same bytes가 합쳐지지 않는다.
- extraction lifecycle과 citation이 정확한 Representation을 가리킨다.
- pack과 MCP가 동일 identity/evidence closure를 독립적으로 검증한다.
- 이 모든 보장이 의도적으로 깨진 mutant에서 RED가 된다.

## 최종 release verdict

현재 `bed13a8`은 **유효한 Wave 2.1 기반 commit**이지만 최종 수렴점은 아니다. 즉시 DOI pack loss를 막고, 이후 Work/Representation/Observation 분리를 단계적으로 구현한다. 한 행을 mutable “최신 문서”로 바꾸는 빠른 수정은 citation 신뢰를 깨므로 금지한다.
