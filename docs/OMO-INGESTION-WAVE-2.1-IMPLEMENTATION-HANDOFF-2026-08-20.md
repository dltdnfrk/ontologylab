# OMO Handoff — OntologyLab Wave 2.1 재귀 개선 실행

- **작성일:** 2026-08-20
- **저장소:** `/Users/hyunjun/Documents/MUNI/ontologylab`
- **기준 HEAD:** `bed13a80b1bdbb9d605b0bc34c42771576ca310e`
- **상세 설계:** `docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md`

## 가장 중요한 상태 구분

상세 설계서의 `R1`~`R10`은 **한 번의 계획 수립 과정에서 수행한 10개 논리적 적대 검토 단계**다.

다음은 아직 하지 않았다.

- 코드 구현 사이클 10회
- 단계별 RED → GREEN 수정
- 단계별 mutation 실행
- 단계별 커밋
- 최종 제품 GREEN 판정

따라서 이 handoff를 받은 OMO는 “R10까지 구현 완료”로 처리하면 안 된다. 실제 구현은 아래 **Step 1부터 순차 시작**한다.

## 현재 완료된 것

Wave 2.1 `bed13a8`에서 다음은 실제 구현됐다.

- `ontologylab/ingestion.py` 공통 persistence seam
- CLI, `/api/collect`, research worker의 세 주 진입점 공유
- full-text 재구성 시 `dataclasses.replace()`로 metadata 보존
- source/evidence grade/DOI persistence
- CLI connector에 active `data_dir` 전달
- fresh-store same-DOI dedupe 및 동시 writer 방어
- 관련 provenance/data-dir/DOI mutation 테스트 RED 확인

## 현재 재현된 미해결 결함

### P1 — 같은 DOI의 새 full text가 폐기됨

- `ontologylab/kgstore.py:2003-2014`
- 기존 DOI row가 있으면 새 bytes/source/grade를 비교하지 않고 반환
- research가 full-text 성공을 보고해도 오래된 abstract를 extraction에 전달할 수 있음

### P1 — legacy DOI migration이 기존 row를 backfill하지 않음

- `ontologylab/kgstore.py:757-775`
- 기존 `source_uri=https://doi.org/...`, `doi=NULL` row가 유지됨
- 변경된 본문을 재수집하면 동일 Work가 두 document row로 갈라짐

### P1 — 다른 DOI와 동일 bytes가 하나로 합쳐짐

- `ontologylab/kgstore.py:2009-2014,2062-2069`
- DOI miss 후 global content hash fallback
- `UNIQUE(content_hash)`가 서로 다른 Work를 합침

### P1 — Pack에서 DOI가 손실됨

- `ontologylab/packbuilder.py:97-100,472-479`
- live DB의 DOI가 pack row에서는 NULL

### P2 — duplicate provenance가 두 observation을 혼합함

- `ontologylab/ingestion.py:63-70`
- canonical stored URI와 incoming text length가 한 event에 섞임

### P2 — persistence와 provenance가 원자적이지 않음

- document/artifact commit: `ontologylab/kgstore.py:2070-2082`
- JSONL append: `ontologylab/ingestion.py:63-75`
- log 실패 시 API 오류와 durable DB row가 동시에 존재 가능

### P2 — Store transaction composability 위반

- `store.atomic()`: `ontologylab/kgstore.py:594-621`
- `insert_document()`가 자체 unconditional `commit/rollback`: `kgstore.py:2053-2082`

## 승인된 목표 모델

한 `documents` row에 모든 의미를 넣지 않는다.

1. **Work** — DOI/PMID/arXiv 등 서지 identity
2. **Representation** — citation span이 가리키는 immutable exact text
3. **Observation** — connector/source/grade/URI/fetch/run 기록

### 반드시 지킬 truth table

| 입력 | 결과 |
|---|---|
| 같은 DOI, 다른 bytes | Work 1, Representation 2 |
| 다른 DOI, 같은 bytes | Work 2; content hash로 Work merge 금지 |
| DOI 없음 → DOI 발견 | stable source key가 증명할 때 attach, 아니면 reconciliation candidate |
| 같은 bytes exact retry | 같은 Representation, 새/idempotent Observation |
| full text 도착 | 기존 abstract와 citation 유지, 새 Representation 추가 |

### 금지된 quick fix

기존 DOI row의 `raw_text_path/content_hash`를 더 긴 본문으로 overwrite하지 않는다. 기존 verified citation span이 다른 bytes를 가리키게 된다.

## 실제 구현 순서

각 Step은 **별도 세션과 별도 commit**으로 수행한다. 한 세션에서 다음 Step까지 넘어가지 않는다.

### Step 1 — Characterization freeze

현재 다섯 반례를 실패하는 테스트로 고정한다.

1. abstract 후 full text가 새 Representation이 되어야 함
2. populated legacy row가 DOI Work로 backfill되어야 함
3. 다른 DOI/같은 bytes가 서로 다른 Work여야 함
4. duplicate provenance가 incoming/canonical을 구분해야 함
5. DOI가 pack round-trip에서 보존돼야 함

**Exit:** 현 HEAD에서 의도한 이유로 RED. 제품 코드는 아직 수정하지 않는다.

### Step 2 — Pack DOI hotfix

- document pack projection에 DOI 추가
- live → pack → read-only store → MCP round trip
- projection drift gate 추가

### Step 3 — Additive identity schema

- `works`
- `work_identifiers`
- `document_observations`
- migration ledger/outbox
- cycle-free canonical Work resolver

### Step 4 — Historical migration

- versioned historical DDL fixture
- SQLite backup API shadow rehearsal
- document ID/path/FK 보존
- documents/extraction_runs constraint migration
- old writer drain과 schema readiness

### Step 5 — Atomic ingestion service v2

- Work resolve
- Representation create/reuse
- Observation/artifact/outbox
- caller-owned transaction/SAVEPOINT
- staged/ready raw-file 상태와 reconciler

### Step 6 — Entrypoint convergence v2

CLI, `/api/collect`, research, `/collect/sample`이 v2 service를 공유한다. `collapse_duplicates`는 observation을 삭제하지 않고 extraction selection만 결정한다.

### Step 7 — Extraction/citation identity

- lifecycle identity에 Representation ID 포함
- citation에 document hash/selected-text hash/coordinate profile
- 기존 citation이 가리키는 bytes 불변

### Step 8 — Pack/MCP identity closure v2

- Work/identifier/redirect/Observation/Representation closure
- graph 및 Method source closure 모두 포함
- source-material licensing policy
- actual stdio MCP receipt와 tamper gate

### Step 9 — Reconciliation/operator surface

- identifier conflict와 merge candidate
- attach/retract/redirect CLI/API
- legacy unrecoverable history와 re-fetch 상태

### Step 10 — Final mutation/release gate

- critical mutation kill 100%
- 전체 suite
- concurrency/process race
- migration/failpoint
- pack/MCP stdio
- 성능/EXPLAIN receipt

## OMO 세션 운영 규칙

```text
한 세션에서 Step 하나만 수행한다.
구현 전 의도한 이유로 실패하는 테스트를 먼저 만든다.
표적 테스트와 대응 mutant를 먼저 실행한다.
전체 suite는 Step 완료 직전 또는 Step 10에서 실행한다.
범위 밖 결함은 기록만 하고 즉흥 수정하지 않는다.
실데이터와 포트 8799/PID 55560을 건드리지 않는다.
모든 runtime fixture와 mutant는 /private/tmp에 둔다.
기존 untracked/dirty 파일을 수정하거나 정리하지 않는다.
완료 시 변경 파일, 테스트, mutant, commit, 남은 위험을 기록한다.
```

## Step 1용 시작 프롬프트

```text
OntologyLab Wave 2.1 recursive remediation Step 1만 수행하라.
기준은 bed13a8 및
`docs/INGESTION-WAVE-2.1-RECURSIVE-PLAN-R10-2026-08-20.md`다.

이번 세션은 characterization test만 추가한다. 제품 코드는 수정하지 않는다.
다섯 반례(fulltext discard, populated legacy DOI, distinct DOI/same bytes,
hybrid provenance, pack DOI loss)가 현 코드에서 의도한 이유로 RED임을 증명하라.
테스트는 실데이터/8799를 사용하지 않고 tmp_path 또는 /private/tmp만 사용한다.
각 실패가 환경 문제가 아니라 해당 invariant 위반인지 출력으로 확인한다.
완료 후 테스트 파일, 정확한 명령/결과, 다음 Step의 blocker만 보고하고 멈춰라.
```

## Release 문구 제한

Step 10까지 완료되기 전에는 다음 표현을 사용하지 않는다.

- lossless ingestion
- 완전한 DOI identity migration
- 모든 entrypoint 수렴
- pack이 source identity를 완전히 보존
- 10차 구현 완료

현재 허용되는 표현은 다음뿐이다.

> Wave 2.1 principal entrypoint field preservation은 구현됐다. Work/Representation/Observation identity migration과 pack publication contract는 계획 및 구현 대기 상태다.
