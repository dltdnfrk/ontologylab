# 온톨로지랩 × Claude Science 0.1.25 구조 이식 구현 명세

- **작성일**: 2026-08-04
- **대상 앱**: 온톨로지랩 (`~/Documents/MUNI/ontologylab`, 라이브 `http://127.0.0.1:8799`)
- **기준축**: Claude Science 0.1.25 라이브 재검증 (`http://localhost:8766`, runtime `0.1.25-release`)
- **스택**: Python FastAPI + uvicorn · 순수 JS SPA (`web/app.js` ~4417줄, `index.html`, `style.css`)
- **관련 문서**:
  - 통합 역설계: `Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md`
  - 선행 UX 분석: `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md`
- **라벨**: `CS-observed` / `ONTO-observed` / `recommendation`

---

## 0. 한 줄 결론

온톨로지랩의 핵심 자산은 이미 CS보다 강한 부분이 있다.

- **인간만 verified로 승격** (`kgstore.approve`)  
- **근거 패널 상시 노출**  
- **Critic은 advisory only**  
- **팩 불변 + content hash + MCP read-only**  
- 키보드 검토·ARIA·로컬 키체인  

부족한 것은 Claude 색이 아니라 **Project → Session → Run → ArtifactVersion → Provenance → (auto) Reviewer** 지속성 구조다.

```
지금: 전역 KG + 10탭 평면 IA + Job(메모리) + 팩(스냅샷) + 검토 큐 대량 DOM
목표: Project 스코프 워크벤치 + Session 타임라인 + durable Run
      + Artifacts 라이브러리(원문/추출/그래프/팩)
      + 버전·계보
      + 자동 Reviewer ≠ 인간 승인 큐 분리 유지
```

---

## 1. 기준축: Claude Science에서 가져올 것만 (온톨로지 관점)

### 1.1 가져올 것

| CS 패턴 | 온톨로지랩 적용 |
|---|---|
| Project / Session | 전역 저장소 해소, 대화·문서·제안 귀속 |
| Library 그룹·검색·Grid/List | 팩 외 PDF/JSON/그림/추출물 열람 |
| ArtifactVersion + dependency | 추출 재실행·팩 비교의 단위 |
| Provenance 5탭 | 기존 계보(엔진·프롬프트·span) 확장 |
| Reviewer after save | critic(큐 정렬)과 별도, 산출물 claim 감사 |
| Dashboard recent | 홈을 현황판+세션 진입으로 |
| Compose 멘션 문법 | 채팅이 파이프라인 컨텍스트를 쥐게 |
| Settings 이원화 | 엔진/키/스키마 vs 역량 |

### 1.2 가져오지 말 것 · 절대 깨지 말 것

- **자동 verified 금지** (CS Reviewer도 자동 지식 채택 안 함 — 온톨로지는 더 엄격히 유지)  
- Critic 점수로 approve 프리셀렉트 (anchoring 가드)  
- 팩에 chat history 섞기 (`chatstore` 분리 철학 유지)  
- API 키 재노출  
- 단일 `app.js` 전면 재작성 (점진 분해)  

### 1.3 CS 실측 앵커

- Project workspace + Library + version diff + Provenance + Reviewer findings  
- OPERON artifacts-not-answers  
- REVIEWER trace-only  
- Pack ≈ Release snapshot 개념으로 매핑 (CS “export/release” semantics)

---

## 2. 온톨로지랩 현황 (ONTO-observed)

### 2.1 코드 지도

| 영역 | 경로 |
|---|---|
| 도메인 모델 | `ontologylab/models.py` Document/Proposed*/PackManifest |
| KG/승인 | `ontologylab/kgstore.py` |
| 리뷰 큐 | `pending_review`, `pending_review()` limit default 100 |
| HTTP | `ontologylab/server/routes.py` |
| 스키마 | `ontologylab/server/schemas.py` |
| Job/SSE | `server/jobs.py`, `GET /api/jobs/stream` |
| 팩 | `packbuilder.py`, `pack_completeness.py` |
| 계보 로그 | `provenance.py` (run_dir jsonl) |
| 채팅 영속 | `chatstore.py` session_id + job_id |
| 프론트 | `web/app.js`, `chat-session.js`, `index.html` |
| 테스트 | `tests/test_agent_drivable_ui.py`, critic/pack/extract 다수 |

### 2.2 IA 실측 (10탭)

```
파이프라인: 홈 · 리서치 · 검토 · 팩 · 연결
도구:       병합 · 커뮤니티 · 그래프 · 엔진 · 설정
```

전부 1차 내비 동등 무게. `showTab()` display 토글 — 패널 DOM 상주.

### 2.3 검토 큐 결함

- API: `GET /api/proposals?limit=200&order=...` (최대 1000)  
- UI: `loadProposals`가 items 전부 `forEach` → tr/button/checkbox 생성  
- 라이브 327건 대기 시 DOM 수천 노드, 버튼 수백 (선행 실측)  
- 근거 패널 자체는 강점: excerpt + grade + critic_disagreement  

### 2.4 Session/Run 약점

- `chatstore.session_id` 존재, 홈 진입 시 새 세션 정책 (`chat-session.js`)  
- 그러나 Project 없음, KG 문서/제안이 세션에 안 묶임  
- JobRegistry 메모리 중심 — 서버 재시작 시 실행 이력 UI 공백 (홈 주석도 인정)  
- Run durable 모델 없음 (job_dir + provenance.jsonl은 있음)

### 2.5 아티팩트 vs 팩

| 있는 것 | 없는 것 |
|---|---|
| documents 테이블 + raw_text_path | 범용 Artifact Library UI |
| pack.sqlite immutable + manifest hash | versioned intermediate (추출 JSON, 그림) |
| pack diff | artifact version diff |
| document review panel (원문+span) | CS형 버전 prev/next + provenance 5탭 |
| citations multi-source | dependency DAG UI |

### 2.6 강점 체크리스트 (회귀 금지)

- [x] insert_proposed → status always proposed  
- [x] approve only human path to verified  
- [x] edge approve requires verified endpoints (or cascade)  
- [x] critic_reviews never flips status  
- [x] pack verified-only (+ incompleteness override + intent)  
- [x] MCP serves packs read-only  
- [x] keys in keychain / env name only  
- [x] SSE jobs + poll fallback  
- [x] keyboard j/k/a/r/u/d  
- [x] evidence excerpt on queue payload  

---

## 3. 목표 정보구조 (recommendation)

### 3.1 내비 재편 (10 → 5)

```
Sessions   ← 홈 대화 + 리서치 시작(작업 유형)
Review     ← 검토 큐 + annotations + (auto) Reviewer findings 서브탭
Artifacts  ← 업로드/문서/추출/그래프/팩(release)
Graph      ← 그래프 + 병합 + 커뮤니티 내부 탭
Customize  ← 엔진 + 프로바이더 + 소스 키 + 스키마 + 기본값
```

연결(MCP)은 Artifacts의 release 카드 액션 또는 Customize 하위.

### 3.2 셸 레이아웃

```
┌──────── rail ────────┬──────── center ─────────┬──── right ────┐
│ Projects (optional)  │ Tab: Session | Doc | Art│ Evidence      │
│ Sessions             │ Transcript / Queue      │ Provenance    │
│ Artifacts shortcut   │ Run timeline            │ Reviewer      │
│ Customize            │ Composer                │               │
└──────────────────────┴─────────────────────────┴───────────────┘
```

모바일: 기존 breakpoint 유지, right는 drawer.

---

## 4. 데이터 모델 이식

### 4.1 기존 → CS 프리미티브 매핑

| 기존 | 목표 |
|---|---|
| (없음) | Project |
| chat session_id | Session |
| Job + job_dir | Run (durable) |
| documents | Source Artifact + versions |
| proposed nodes/edges | ReviewItem (큐) + optional CandidateArtifact |
| citations + extractor_* | Provenance domain fields |
| critic_reviews | AutomatedReviewCheck (advisory) |
| human approve/reject | HumanDecision + status flip |
| packs | ReleaseSnapshot ArtifactVersion |
| provenance.jsonl | Run execution log / provenance bundle |

### 4.2 스키마 증분 (P0)

`kgstore._migrate` 패턴으로 추가. 기존 테이블 DROP 금지.

```sql
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  active_schema_version_id INTEGER
);

-- chatstore와 별도 또는 chat.sqlite에 확장
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,           -- job_id와 동일 가능
  project_id TEXT NOT NULL,
  session_id TEXT,
  kind TEXT NOT NULL,            -- research|extract|critic|pack_build|merge_scan|enrich
  status TEXT NOT NULL,          -- running|complete|failed|cancelled
  phase TEXT,
  engine TEXT,
  model TEXT,
  started_ts REAL,
  finished_ts REAL,
  error TEXT,
  totals_json TEXT NOT NULL DEFAULT '{}',
  ask_json TEXT                  -- research topic 등
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  run_id TEXT,
  filename TEXT NOT NULL,
  kind TEXT NOT NULL,            -- upload|source_doc|extract_json|graph|report|pack_release|other
  latest_version_id TEXT,
  source_doc_id TEXT,            -- 기존 documents.id 링크 optional
  is_user_upload INTEGER NOT NULL DEFAULT 0,
  created_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS artifact_versions (
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  run_id TEXT,
  content_type TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  checksum TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_ts REAL NOT NULL,
  parent_version_id TEXT,
  is_intermediate INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(artifact_id, version_number)
);

CREATE TABLE IF NOT EXISTS artifact_dependencies (
  id TEXT PRIMARY KEY,
  artifact_version_id TEXT NOT NULL,
  depends_on_version_id TEXT NOT NULL,
  reference_name TEXT,
  UNIQUE(artifact_version_id, depends_on_version_id)
);

CREATE TABLE IF NOT EXISTS verification_checks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  run_id TEXT,
  artifact_version_id TEXT,
  claim TEXT,
  verdict TEXT NOT NULL,          -- pass|warn|fail|inconclusive
  status TEXT NOT NULL DEFAULT 'open',
  evidence TEXT,
  reviewer_engine TEXT,
  reviewer_model TEXT,
  created_ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS human_decisions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  target_kind TEXT NOT NULL,     -- node|edge|annotation|merge|pack_gate
  target_id TEXT NOT NULL,
  decision TEXT NOT NULL,        -- approved|rejected|reopened|dismissed
  actor TEXT NOT NULL,
  note TEXT,
  created_ts REAL NOT NULL
);
```

**스코프 규칙**

- 기존 nodes/edges/documents에 `project_id` NULL 허용 후 backfill  
- NULL = “legacy global” 프로젝트로 마이그레이션  
- 활성 project 필터 기본 ON  

### 4.3 Pack = Release Snapshot

`build_pack` 성공 시:

1. 기존 packs_dir 동작 유지 (호환)  
2. + `artifacts` row kind=`pack_release`  
3. + version v1 checksum = manifest content_hash  
4. dependencies: 포함된 verified node/edge의 source documents versions  

팩 diff UI는 artifact version diff의 특수형으로 유지.

### 4.4 Reviewer vs Critic vs Human

| 종류 | 시점 | 효과 |
|---|---|---|
| Critic | 큐 상주 제안 | score only, 정렬/배지 |
| Auto Reviewer | artifact/pack 저장 후 | VerificationCheck, 지식 status 불변 |
| HumanDecision | 검토/주석/병합/팩 게이트 | 유일 status→verified 경로 |

세 UI 탭을 합치지 말 것. Review 화면 안에서 서브탭으로 공존은 OK.

---

## 5. API 이식

### 5.1 유지

- `/api/proposals/approve|reject|reopen`  
- `/api/document/{id}/review`  
- `/api/provenance/{kind}/{id}` (노드/엣지 계보)  
- `/api/packs/*`  
- `/api/jobs`, `/api/jobs/stream`  
- `/api/chat`  

### 5.2 추가/변경

| Method | Path | 설명 |
|---|---|---|
| GET/POST | `/api/projects` | 프로젝트 |
| GET/PATCH | `/api/projects/{id}` | |
| GET/POST | `/api/projects/{id}/sessions` | |
| GET | `/api/projects/{id}/artifacts` | search, sort, kind, cursor |
| GET | `/api/artifacts/{id}` | |
| GET | `/api/artifacts/{id}/versions` | |
| GET | `/api/artifacts/versions/{vid}` | bytes or json |
| GET | `/api/artifacts/versions/{vid}/provenance` | 5탭 DTO |
| GET | `/api/proposals?cursor=&limit=` | **limit 기본 50, max 100** (200 전체 렌더 유도 제거) |
| GET | `/api/runs` | durable jobs list |
| GET | `/api/runs/{id}` | |
| POST | `/api/artifacts/versions/{vid}/review` | auto reviewer |
| GET | `/api/verification-checks` | filter by project/artifact |

SSE: `/api/jobs/stream` 유지 + payload에 `project_id`, `session_id`, `artifact_ids` 필드 추가.

---

## 6. 프론트 이식

### 6.1 `loadProposals` 가상화 (P0)

현재:

```js
// app.js loadProposals
var data = await api("/api/proposals?limit=200&order=" + reviewOrder);
items.forEach(... create tr ...)
```

목표:

1. `limit=50` + `cursor`  
2. 스크롤 시 fetch next  
3. 또는 windowed render (DOM에 보이는 행 + overscan만)  
4. 키보드 j/k는 **데이터 인덱스** 기준, DOM 존재 여부와 분리  
5. 선택 체크셋은 id Set으로  

수락: 1,000 proposed에서도 초기 tr 수 ≤ 100.

### 6.2 app.js 분해 경계 (점진)

```
web/
  app.js                 # bootstrap only
  js/shell.js            # tab→route, project switch
  js/review-queue.js
  js/evidence-pane.js    # 기존 renderEvidence
  js/artifacts-library.js
  js/provenance-pane.js
  js/runs.js             # jobs
  js/packs.js
  js/graph.js
  js/chat.js
  js/settings.js
```

테스트: `test_agent_drivable_ui`가 깨지지 않게 role/tab 계약 유지.

### 6.3 Sessions 화면

- 홈 대화를 Session timeline으로  
- 칩: 리서치 시작 / 검토 열기 / 저장소 상태  
- 각 턴에 Run chip + 결과 artifact tray  
- `sessionStorage` only 의존 축소 → chatstore history API 강화  

### 6.4 Artifacts 화면

그룹:

- Uploads  
- Documents (수집)  
- Extractions (run outputs)  
- Graphs  
- Releases (packs)  

카드 프리뷰:

- md/txt 첫 줄  
- csv 행·열 (가능하면)  
- pack: counts + fingerprint short  

상세:

- open document panel (기존 doc-panel 재사용)  
- provenance  
- download  
- (pack) MCP 연결 지시  

### 6.5 Provenance 매핑

| CS 탭 | 온톨로지 소스 |
|---|---|
| Code | extract prompt + engine (재구성 가능하면) / 없으면 정직히 부재 |
| Execution Log | job steps + provenance.jsonl |
| Messages | chat turns linked by job_id |
| Environment | engine/model/prompt_version/decode_params/schema_label |
| Review | verification_checks + critic latest + human_decisions |

기존 `/api/provenance/node|edge`는 Review 큐 우측 빠른 계보로 유지.

### 6.6 Customize 이원화

```
Capabilities: Engines · Providers · Paper sources · Schema · (future) Reviewer
Workspace:    Defaults · Paths · Keys/Keychain · Cost/Usage · Safety copy
```

---

## 7. 백엔드 Job → Run 영속화

### 7.1 현재

- `JobRegistry` in-memory  
- `paths.new_job_dir` + provenance.jsonl  
- recover_running_once on boot (extraction_state)  

### 7.2 목표

1. create job 시 `runs` INSERT  
2. phase/status/totals 갱신마다 UPDATE  
3. list_jobs = DB + memory merge  
4. 완료 시 artifacts 생성 (research → source docs already; + extract json export optional)  
5. SSE는 DB version counter 또는 기존 touch() 유지  

### 7.3 Research Run 산출물 규칙

| phase | artifact |
|---|---|
| collect complete | source_doc versions (documents와 링크) |
| extract complete | extract_summary.md / candidates.json (optional intermediate) |
| critic complete | checks only |
| pack complete | pack_release |

---

## 8. 구현 로드맵 (온톨로지 only)

### P0

1. proposals cursor + UI virtualize  
2. projects + legacy backfill  
3. sessions API 강화 + 홈 타임라인  
4. artifacts table + documents 라이브러리 노출  
5. pack_release 등록  
6. runs 테이블 + job 영속  

### P1

1. artifact_versions + dependencies  
2. provenance 5탭 DTO + UI  
3. auto reviewer v0 (pack/report claims)  
4. app.js 모듈 분해 1차  
5. Graph 하위로 merge/communities  

### P2

1. split view  
2. composer @/#//  
3. reviewer model settings  
4. 대형 그래프 clustering 이미 communities — UX 연결 강화  

---

## 9. 테스트 계획 기준

### P0 자동화

- [ ] `test_proposals_cursor_stable_order`  
- [ ] `test_review_ui_row_cap` (jsdom or playwright 상한)  
- [ ] `test_project_scope_filters_documents_proposals`  
- [ ] `test_legacy_null_project_backfill`  
- [ ] `test_pack_build_registers_release_artifact`  
- [ ] `test_run_row_survives_registry_recreation`  
- [ ] 기존 `test_approve`/`critic cannot verify`/`pack immutability` 회귀  

### 수동 QA

- [ ] 프로젝트 A/B 전환 시 큐·문서 분리  
- [ ] 500+ proposed에서 스크롤·키보드 정상  
- [ ] 팩 빌드 후 Artifacts에 release 카드  
- [ ] 문서 패널 + evidence 패널 동시  
- [ ] 서버 restart 후 runs 목록 잔존  

---

## 10. 수락 기준 (DoD)

1. Project 없이 “전역 한 덩어리” 느낌이 해소  
2. 검토 큐 대량에서도 UI 응답성 확보 (초기 DOM 상한)  
3. Artifacts에서 원문·팩·(가능하면) 추출물 열람  
4. Pack = release snapshot으로 Library에 보임 + 기존 fingerprint/MCP 유지  
5. verified 경로는 여전히 인간만  
6. Critic/AutoReviewer/Human UI·데이터 분리  
7. Job/Run이 서버 재시작 후에도 조회 가능  

---

## 11. 명시적 비범위

- MUNI lab 코드 변경 (형제 문서)  
- CS 데스크톱 런타임 임베드  
- OWL 편집기 고도화  
- 멀티유저 서버  

---

## 12. 증거 인덱스

| 주장 | 근거 |
|---|---|
| 승인 유일 경로 | `kgstore.approve` / insert_proposed |
| 큐 대량 렌더 | `app.js` loadProposals limit=200 forEach |
| 팩 불변 | `packbuilder.build_pack` |
| chat/session | `chatstore.py` |
| SSE | `routes.py` `/jobs/stream` |
| 10탭 IA | `web/index.html` tablist |
| CS 기준 | 라이브 8766 + DB + agents YAML |

---

*온톨로지랩 전용. MUNI lab은 형제 문서를 본다.*
