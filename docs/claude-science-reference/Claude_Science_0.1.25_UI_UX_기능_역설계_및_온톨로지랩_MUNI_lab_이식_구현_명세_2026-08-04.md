# Claude Science 0.1.25 UI/UX·기능 역설계와 온톨로지랩·MUNI lab 이식 구현 명세

- **작성일**: 2026-08-04
- **선행 문서**: `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md`
- **목적**: 색/버튼 복제가 아니라 **Project → Session → Run → ArtifactVersion → Provenance → Reviewer** 구조와 기능 계약을 두 제품에 바로 반영 가능하게 고정
- **증거 방식**: 라이브 UI snapshot + SQLite 실측 + 런타임 agent YAML + web-dist 문자열 + 앱 코드 라인
- **라벨**: `CS-observed` / `사이트-observed` / `recommendation`

---

## 0. 한 줄 결론

Claude Science의 제품 핵심은 채팅 UI가 아니라 **버전된 산출물 하니스**다.

1. 사용자는 Project 안에서 Session을 연다.
2. Session 안 작업은 셀/자식 frame으로 실행된다.
3. 결과물은 저장 전까지 사용자에게 안 보이며, `save_artifacts`로 **불변 ArtifactVersion**이 된다.
4. 버전은 dependency DAG와 재현 패키지(Code/Exec/Messages/Env/Review)를 가진다.
5. Reviewer는 실행을 다시 하지 않고 transcript·exec log·artifact만 추적해 finding을 남긴다.
6. Human approval(지식 채택/HITL 게이트)은 Reviewer와 **절대 합치지 않는다**.

온톨로지랩은 5를 이미 강하게 갖고 있고 1–4가 약하다.  
MUNI lab은 셸 골격이 가깝지만 3–6이 끊겨 있다(성공 턴도 산출물 승격·Library·HITL 회복이 약함).

---

## 1. 기준축 재검증 (CS-observed, 2026-08-04)

### 1.1 런타임

| 항목 | 실측 |
|---|---|
| 버전 | `0.1.25` (`BUILD.json`, daemon log) |
| 앱 포트 | `http://localhost:8766` |
| 샌드박스/MCP-UI | `8767` — 별도 앱이 아니라 MCP-UI proxy (`/mcp_apps`) |
| 데몬 | `claude-sc` pid 30985 |
| 저장소 | `~/.claude-science/orgs/.../operon-cli.db` |
| 빌드 | Bun daemon + Vite React SPA + SQLite WAL |

### 1.2 DB cardinality (재실측)

| 테이블/개념 | 수 |
|---|---:|
| projects | 3 |
| frames | 92 |
| root sessions (parent null) | 10 (uploads 2 + onboarding hidden 1 + visible agent 7) |
| artifacts | 213 |
| artifact_versions | 234 |
| artifact_dependencies | 391 |
| verification_checks | 62 |
| execution_log | 674 |
| host_call_log | 651 |

**보정 사실**

- CS에 별도 `runs` 테이블은 없다. Session/서브에이전트/Reviewer 실행은 모두 `frames` 트리로 표현된다.
- UI Library “80 artifacts”는 DB 전체 cardinality가 아니다. intermediate 제외·client filter·badge lag가 있다. **badge ≠ source of truth**.
- `lineage_messages` / `environment_snapshot` 컬럼 populated ≈ 0. 현재 경로는 `lineage_snapshot_hash` / `env_snapshot_hash` + content snapshot 쪽이다. 구형 컬럼을 그대로 복제하지 말 것.
- BOOKMARKER agent는 정의되어 있으나 이 설치에서 frame 0건 — 정의≠활성.

### 1.3 에이전트 역할 (runtime YAML)

| Agent | 역할 | 핵심 제약 |
|---|---|---|
| OPERON | 일반 과학 워크벤치 코디네이터 | **artifacts not answers**; plan은 비싼 작업만; `{{artifact:VERSION_ID}}` 임베드 |
| REVIEWER | 독립 사후 감사 | python/bash/save_artifacts/web_search 제외; **trace-only**; claim-level pass/warn/fail/inconclusive |
| BOOKMARKER | transcript 앵커 0–2개 | 정의됨, 이 설치에서 미활성 |
| ONBOARDING | 첫 실행 인터뷰 | 실행 도구 제외, 권한 토글 후 handoff |

Reviewer 실측 lifecycle:

```
verdict: pass | warn | fail | inconclusive
status:  open | claimed | resolved | unaddressed
```

형광 통합보고서 v1 예: fail→resolved (전문 등급 과대주장), warn→resolved (파장 사다리 web-body hedge 누락).  
v2 Review 탭: “No checks run yet” — **finding은 버전 스코프**다.

---

## 2. Claude Science 정보구조·화면 계약 (이식 대상)

### 2.1 화면 계층

```
Dashboard
├─ Projects (카드: 제목 · active · actions)
└─ Recent sessions

Project workspace
├─ Left rail dialog "Sessions"
│  ├─ New / Search / Customize
│  ├─ Files · Compute
│  └─ Sessions (Older 그룹 등)
├─ Top bar
│  ├─ Sessions · Back to dashboard · Project title · Search · Library(badge)
│  └─ Open tabs strip (+ Split / Merge tabs)
├─ Center
│  ├─ Session transcript (+ Reviewer summary chip, subagents, Notebook)
│  ├─ Composer: @artifacts #sessions /skills ⌘K
│  └─ Add & configure · Session options · Model · Dictation
└─ Right / tab content
   ├─ Files / Artifacts library
   ├─ Artifact viewer (version prev/next · Show changes · provenance)
   ├─ Notebook (kernel cells)
   └─ Plan preview
```

### 2.2 Compose 계약 (보정)

기존 요약의 “Compose 한 다이얼로그에 전부”는 과단순화.

| 표면 | 항목 |
|---|---|
| **Add & configure** | Attach files · Your files · Model · Delegation · **(기존 세션)** View plan · Request review · Save as skill |
| **Session options** | Delegation · Auto-review · Reviewer model · Memory · Specialist · Compute |
| **Composer 문법** | `@` artifacts · `#` sessions · `/` skills · `⌘K` search |

새 세션에는 Request review / Save as skill이 약하거나 없고, 작업 이력이 있는 세션에 나타남.

### 2.3 Library / Artifact 계약

- 그룹: Your uploads · session별 산출물 그룹 · Actions for session
- 검색 · Sort(Created ↓) · Grid/List
- 카드 프리뷰: 이미지 썸네일, MD 첫머리, CSV `rows · columns + 표본`, HTML iframe
- 상세 액션: Star / Hide / View in context / Provenance / Copy link / Rename / Download / Export Metadata / Export to Cloud / Delete
- 버전: Previous · `vN` · Next · **Show changes** (`Comparing to vN`) · Show preview
- Open in viewer → 탭 스트립에 파일 탭 추가

### 2.4 Provenance 5탭 계약

| 탭 | 내용 | 다운로드/액션 |
|---|---|---|
| Code | 재구성 스크립트 + Inputs(의존 파일) | Download standalone script + inputs + environment.yml |
| Execution Log | 셀 단위 source/stdout | Download notebook bundle |
| Messages | 생성 시점 대화/도구 타임라인 | — |
| Environment | Python 버전 · packages · install ops | — |
| Review | finding 카드 (claim/evidence/verdict/status/model) | Jump to claim · View reviewer transcript |

### 2.5 Session chrome 계약

- Reviewer chip: `Reviewer N findings · M checks · K fixed` → 펼치면 카드 리스트
- Subagents menu: 이름 + done 상태 → drill-down (Prior Context / Current Task / Plan Steps / tool cards)
- Notebook: Main agent · Python · Agent SDK · ended time · cells view-only after end
- Plan artifact: 단계 리스트 + parallel tracks + confidence note (탭으로 열림)

### 2.6 Settings 이원화

```
Capabilities: Skills · Connectors · Specialists · Memory · Compute · Network
Workspace:    Permissions · Credentials · Storage · Usage · General
```

Skills 실측 그룹: Featured / Imported / Personal (Personal 4: Multisource Lit Harvest, Plant Pathogen Detection, Probe Diagnostic Workflow, Source Attribution Reviewer).

### 2.7 기능 불변식 (CS → 이식 필수)

1. **ArtifactVersion은 불변**. 수정 = 새 version_number.
2. **Dependency는 version→version**. artifact id만 가리키면 재현 깨짐.
3. **workspace 파일 ≠ 사용자 가시 산출물**. 승격(save) 전까지 Library에 안 뜸.
4. **실행 성공 ≠ 산출물 성공**. 둘을 별도 상태로 둔다.
5. **Reviewer verdict ≠ HumanDecision**. 자동 승인이 아니다.
6. **Finding은 버전 스코프**가 가능해야 한다 (v1 fail, v2 clean).
7. **raw log는 보존, 대화에는 요약**.
8. **UI badge는 source of truth가 아니다** (API/DB 기준).
9. **Plan 승인과 Reviewer 감사와 HITL 지식 채택은 시점·주체가 다르다**.
10. **플러그인/HTML 프리뷰는 별도 origin 격리** (8767 패턴).

### 2.8 API/이벤트 후보 (web-dist + 라이브)

```
GET  /api/projects/dashboard
GET  /api/projects/:projectId
GET  /api/projects/:projectId/artifacts
GET  /api/frames/:frameId/messages
GET  /api/frames/:frameId/streaming
GET  /api/frames/:frameId/execution-log?versionId=
GET  /api/frames/:frameId/verification
POST /api/frames/:frameId/audit
POST /api/frames/:frameId/approve-plan
PUT  /api/frames/:rootId/session-config
GET  /api/artifacts/:id/versions
GET  /api/artifacts/versions/:versionId
GET  /api/artifacts/versions/:versionId/lineage
GET  /api/artifacts/versions/:versionId/verification
WS   /api/ws
```

이벤트 후보: `frame_update`, `child_message`, `artifact_created`, `execution_cell_update`, `verification_update`.

---

## 3. 공통 Workbench 데이터 프리미티브 (recommendation)

CS에 Run 테이블은 없지만, 두 제품은 파이프라인이 명확하므로 **Run을 1급으로 추가**한다. CS의 frame subtree + execution_log를 Run이 흡수한다.

```
Project
Session
Run
RunEvent / ToolEvent / ExecutionCell
SourceRecord
Artifact
ArtifactVersion
ArtifactDependency
ProvenanceBundle   # Code + ExecLog + Messages + Env + Review 뷰모델
VerificationCheck  # 자동 Reviewer
HumanDecision      # 승인/거부/changes_requested/재개
ComputeEnvironment
CredentialReference
ReleaseSnapshot    # 온톨로지 팩
```

### 3.1 상태기계 (통일)

**Run.status**

```
idle → planning → running → awaiting_human
     ↘ failed
awaiting_human → running (재개) | failed | cancelled
running → reviewing → completed | failed | cancelled
```

**ArtifactVersion.lifecycle**

```
ephemeral (실행 중 임시) → committed (완료 확정) → superseded (새 버전)
```

**VerificationCheck**

```
verdict × status  (곱집합, 합치지 말 것)
```

**HumanDecision**

```
approved | rejected | changes_requested | reopened
+ gate_name + comment + actor + resumable
```

### 3.2 Authority chain (Nipo/CS 정렬)

```
Project
  → Session
    → (optional) PlanApproval
      → Run
        → ExecutionCells / ToolEvents
          → ArtifactVersion(+deps)
            → VerificationCheck
              → HumanDecision / Export / ReleaseSnapshot
```

---

## 4. 온톨로지랩 이식 명세 (사이트-observed + recommendation)

### 4.1 현재 자산 (유지)

| 자산 | 근거 |
|---|---|
| Human-only verified 게이트 | `kgstore.approve` — proposed만 자동 삽입, verified는 인간만 |
| Evidence 상시 패널 | `app.js` `renderEvidence` + queue 응답에 excerpt 포함 |
| Critic advisory only | `critic_reviews` + “승인 경로가 읽지 않음” 주석 |
| Pack immutability + fingerprint | `packbuilder.build_pack` verified subgraph + content_hash |
| SSE jobs stream | `GET /api/jobs/stream` + EventSource fallback poll |
| Chat session_id + job_id 연결 | `chatstore.turns` |
| 키보드 검토 j/k/a/r/u/d | `app.js` keydown |
| Agent-drivable ARIA | `tests/test_agent_drivable_ui.py` |

### 4.2 현재 결함 → CS 계약 매핑

| 결함 | CS 대응 | 구현 방향 |
|---|---|---|
| Project 없음 | projects | `projects` 테이블 + 전역 store를 project scope |
| Session 약함 | frames root | `chatstore.session_id`를 1급 Session으로 승격, 홈 진입 시 무조건 새 세션 정책 재검토 |
| Run이 메모리 JobRegistry | frames+execution_log | Job을 durable Run으로 영속화 |
| 검토 큐 전체 렌더 (limit 200 DOM) | virtualization | cursor/offset API + windowed render |
| 팩만 있고 일반 아티팩트 라이브러리 없음 | artifacts library | documents/raw/extract JSON/graph/export를 ArtifactVersion화 |
| Critic ≠ Reviewer 시점 | auto reviewer after save | 팩/리포트 저장 후 trace-only Reviewer 추가, critic는 큐 정렬용 유지 |
| 10탭 평면 IA | project shell | 5영역: Sessions / Review / Artifacts / Graph / Customize |

### 4.3 스키마 증분 (P0)

```sql
-- 개념만. 실제 migration은 kgstore._migrate 패턴 따를 것
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  active_schema_version_id INTEGER
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  title TEXT NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  status TEXT NOT NULL
);

-- 기존 jobs/* 디렉터리와 병행 후 이관
CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  kind TEXT NOT NULL, -- research|extract|critic|pack_build|merge_scan
  status TEXT NOT NULL,
  phase TEXT,
  engine TEXT,
  model TEXT,
  started_ts REAL,
  finished_ts REAL,
  error TEXT,
  totals_json TEXT
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  run_id TEXT,
  filename TEXT NOT NULL,
  kind TEXT NOT NULL, -- source_doc|extract_json|graph|pack|report|upload
  latest_version_id TEXT,
  is_user_upload INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE artifact_versions (
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
  UNIQUE(artifact_id, version_number)
);

CREATE TABLE artifact_dependencies (
  id TEXT PRIMARY KEY,
  artifact_version_id TEXT NOT NULL,
  depends_on_version_id TEXT NOT NULL,
  reference_name TEXT,
  UNIQUE(artifact_version_id, depends_on_version_id)
);

CREATE TABLE verification_checks (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  artifact_version_id TEXT,
  claim TEXT,
  verdict TEXT NOT NULL, -- pass|warn|fail|inconclusive
  status TEXT NOT NULL DEFAULT 'open', -- open|resolved|unaddressed
  evidence TEXT,
  reviewer_model TEXT,
  created_ts REAL NOT NULL
);

-- 기존 nodes/edges status 전이는 HumanDecision 로그로도 남김
CREATE TABLE human_decisions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  target_kind TEXT NOT NULL, -- node|edge|annotation|pack_gate|run_gate
  target_id TEXT NOT NULL,
  decision TEXT NOT NULL, -- approved|rejected|changes_requested|reopened
  actor TEXT NOT NULL,
  note TEXT,
  created_ts REAL NOT NULL
);
```

기존 `documents/nodes/edges/citations/critic_reviews/packs`는 폐기하지 말고:

- Document → SourceArtifact + version
- Proposed node/edge → CandidateArtifact 또는 ReviewItem 뷰
- Pack → ReleaseSnapshot ArtifactVersion
- Critic score → AutomatedReviewCheck (advisory)

### 4.4 API 증분

| Method | Path | 역할 |
|---|---|---|
| GET/POST | `/api/projects` | 프로젝트 CRUD |
| GET/POST | `/api/projects/{id}/sessions` | 세션 |
| GET | `/api/projects/{id}/artifacts` | 라이브러리 (search/sort/group) |
| GET | `/api/artifacts/{id}/versions` | 버전 목록 |
| GET | `/api/artifacts/versions/{vid}/provenance` | 5탭 데이터 |
| GET | `/api/proposals?cursor=&limit=` | **페이지/커서 필수** (현 limit 200 제거 방향) |
| POST | `/api/runs/{id}/resume` | 실패/중단 재개 |
| POST | `/api/artifacts/versions/{vid}/review` | auto reviewer 트리거 |
| SSE | `/api/jobs/stream` 유지 → `/api/runs/stream` alias | 기존 클라이언트 호환 |

### 4.5 프론트 분해 경계 (`web/app.js` 4417줄)

추천 모듈 (IIFE 점진 분해, 한 번에 rewrite 금지):

```
web/js/
  shell.js          # showTab → router, project/session chrome
  review-queue.js   # virtualized table, keyboard, bulk
  evidence-pane.js  # 기존 renderEvidence 이관
  artifacts.js      # library grid/list/version/diff
  provenance.js     # 5탭
  runs.js           # jobs table + SSE
  packs.js          # release snapshot UX
  graph.js
  settings.js
  chat.js
```

**P0 UX 변경**

1. 내비 10탭 → 5: Sessions / Review / Artifacts / Graph / Customize  
   (Merge·Communities는 Graph 내부 탭, Engines·Settings는 Customize)
2. `loadProposals`: DOM 전체 items.forEach 제거 → 가상 스크롤 또는 window+cursor
3. 홈 대화를 Session timeline으로: 턴마다 Run chip + artifact tray
4. 팩 빌드 성공 시 Artifacts 라이브러리에 Release card 자동 등록
5. 근거 패널 유지 + Provenance 버튼으로 확장

### 4.6 온톨로지랩 테스트 P0

- `test_proposals_cursor_pagination`
- `test_review_queue_does_not_render_all_rows` (DOM upper bound)
- `test_approve_only_path_to_verified` (회귀)
- `test_pack_is_release_snapshot_artifact`
- `test_project_scopes_documents_and_proposals`
- `test_run_persisted_across_server_restart`

---

## 5. MUNI lab 이식 명세 (사이트-observed + recommendation)

### 5.1 현재 자산 (유지)

| 자산 | 근거 |
|---|---|
| 연구 셸 3패널 골격 | `AiScientistWorkspace` rail + main + output panel |
| Run/Turn 이벤트 모델 | `researchConversation.ts` turns/progress/sourceIds/artifactIds |
| WebSocket pipeline protocol | `mucha-science.web.v1` start/subscribe/action/cancel |
| HITL 카드 UI | `ResearchInteractionCard` + `hitl_gate` options |
| Source connections | OpenAlex/Crossref/PubMed 등 |
| 정직한 실패 표시 | assistant meta “실행 중단” |
| 성공 턴 보고서 렌더 | `SafeReportMarkdown` + quality readiness |
| createThreadLabel 유틸 존재 | `researchConversationPresentation.ts` — **아직 제목에 미연결** |

### 5.2 라이브 결함 재실측 (localStorage)

9개 세션 중 고유 프롬프트 변형 소수, 제목=프롬프트 전체.

| session | status | logs | sources | artifacts | final |
|---|---|---:|---:|---:|---|
| …b459… | error | 63 | 12 | 0 | N |
| …b88d… (3 turns) | error×3 | 0/0/44 | 0/0/7 | 0 | N |
| …bae4… | **complete** | 42 | 4 | **2** | **Y** |
| …717d… / …7257… | error | 39 | 6 | 0 | N |

실패 메시지 패턴:

```
live mode requires approved HITL gate 'evidence'; got 'changes_requested'
```

코드 경로:

1. UI가 `hitl_decision{status:changes_requested, comment}` 전송 (`useResearchPipelineBridge`)
2. 파이프라인은 evidence gate에서 **한 번** revision 후 재게이트 (`idea_to_council.py` 509–548)
3. 재게이트도 approved가 아니면 `assert_live_hitl`이 **예외로 종료** (`live_mode.py`)
4. UI는 error 텍스트만 남기고 **재승인/재개 버튼 없음**
5. Plannotator artifact 계약상 `changes_requested`는 resumable인데, scientific chat 경로가 resume를 연결하지 않음

추가:

- 이중 셸: scientific 셸 vs `/settings`·`/muni` Sidebar 셸 (`App.tsx`)
- `/browser`·`/studio` → scientific redirect, Sidebar “Live artifacts”는 빈 약속
- 산출물 ID는 있어도 Library/버전/프로비넌스 UI 없음 (`formatResearchArtifactLabel`만 존재)
- `createThreadLabel` 미사용 → 레일 제목 중복

### 5.3 목표 IA (단일 셸)

```
Dashboard (optional later)
Project (or default single project "Personal Lab")
└─ Workbench shell (settings 포함 유일 셸)
   ├─ Rail: New · Sessions(제목 압축) · Library · Sources · Validation · Settings
   ├─ Center: Session transcript + Run timeline + HITL recovery
   └─ Right tabs: Artifacts | Sources | Review | Run/Provenance
```

`/settings`의 Claude형 레이아웃을 **유일 셸**로 승격하고 Scientific을 center로 이식.  
레거시 Sidebar 셸은 read-only archive 또는 제거.

### 5.4 데이터 모델 증분

현재: `session → turns[]` in localStorage.  
목표:

```
Project (local or server)
  Session { id, projectId, title, createdAt, updatedAt }
    Run { id, sessionId, status, generation, startedAt, completedAt, error, hitlState }
      Turn (UI 메시지 단위; 1 Turn : 1 Run 유지 가능)
      Events[]
      SourceRecords[]
      ArtifactRefs[] → ArtifactVersion
      VerificationChecks[]
      HumanDecisions[]
```

최소 변경 전략:

1. `ResearchConversationTurn`에 `runStatus`, `hitlGate`, `recoveryActions` 필드 추가
2. `artifactIds: string[]`를 `artifacts: {id, kind, version, label, uri}[]`로 확장
3. localStorage workspace 스키마 버전 bump (`v1` → `v2`) + migrate
4. 서버 측 `PipelineRuntime` 이벤트에 `artifact_created` / `run_resumable` 명시 이벤트 추가

### 5.5 HITL 회복 UX (P0 최우선)

**상태 머신**

```
awaiting_hitl(gate=evidence)
  ├─ approved → continue pipeline
  ├─ changes_requested + comment → one automatic research revision (existing)
  │     ├─ approved → continue
  │     └─ changes_requested/pending → status=awaiting_hitl_resume (NOT hard fail)
  └─ abort → cancelled
```

**UI 필수 버튼**

- 다시 승인 요청 (같은 gate 재제시)
- 수정 의견 보내며 재개
- Run 새로 시작 (fork)
- 여기까지의 출처/로그를 Artifact로 저장

**금지**

- `changes_requested`를 최종 error 문자열로만 남기기
- live mode violation을 사용자 회복 불가능한 종료로 처리

코드 앵커:

- `src/runtime/live_mode.py` `assert_live_hitl`
- `src/pipeline/idea_to_council.py` evidence re-gate loop
- `web/ui/src/hooks/useResearchPipelineBridge.ts` decision send
- `web/ui/src/components/ai-scientist/ResearchConversationTurn.tsx` error rendering

### 5.6 Artifact 승격 규칙 (P0)

실행 중:

| 이벤트 | 임시 Artifact |
|---|---|
| source accepted | `source-card` |
| source audit summary | `source-audit` |
| report_chunk | `report-draft` (ephemeral) |
| final_report | `report` v1 committed |
| quality | `quality-summary` |

완료 시:

- ephemeral → committed version
- Output panel Artifacts 탭 + Library 레일 갱신
- 성공 턴 `bae4…`처럼 artifacts=2여도 **열 수 있는 뷰어**가 있어야 함 (현재 라벨만)

### 5.7 라우트 계약

| 경로 | 동작 |
|---|---|
| `#/scientific` | chat |
| `#/scientific/library` | **신규** artifact library |
| `#/scientific/library/:artifactId` | version viewer + provenance |
| `#/scientific/sources` | sources panel |
| `#/scientific/validation` | validation |
| `#/scientific/settings` | settings inside same shell |
| `#/browser`, `#/studio` | 제거 또는 library로 301 |
| `#/muni` | Project template / Study — fetch 실패 수정 또는 숨김 |

### 5.8 세션 제목

`createThreadLabel(prompt)`를 `listResearchConversationSummaries`와 rail 버튼 라벨에 연결.  
규칙: 32자 말줄임 + 동일 제목 다수 시 `· 2` suffix.

### 5.9 MUNI lab 테스트 P0

- `test_changes_requested_does_not_hard_fail_without_recovery_ui`
- `test_hitl_resume_roundtrip`
- `test_turn_promotes_report_and_sources_to_artifacts`
- `test_session_title_uses_createThreadLabel`
- `test_routes_library_not_browser_redirect`
- `test_single_shell_settings_inside_scientific`
- 기존 `ResearchInteractionCard` changes_requested comment 테스트 유지

---

## 6. 공통 UI 컴포넌트 스펙 (양쪽 공유 개념)

구현 언어는 달라도 **props 계약**을 맞춘다.

### 6.1 `<WorkbenchShell>`

```
props:
  project
  sessions
  activeSessionId
  libraryBadgeCount
  rightTabs: Artifacts|Sources|Review|Run
  onNewSession
  onOpenLibrary
```

### 6.2 `<ArtifactLibrary>`

```
props:
  groups: [{id, title, count, items}]
  layout: grid|list
  sort
  query
  onOpen(artifactId)
```

### 6.3 `<ArtifactViewer>`

```
props:
  filename
  version
  versions[]
  onPrev/onNext
  diffMode
  actions[]
  onOpenProvenance
```

### 6.4 `<ProvenancePane>`

```
tabs: code|execution|messages|environment|review
downloadStandalone
downloadNotebook
findings[]
```

### 6.5 `<ReviewerFindingCard>`

```
claim
evidence
verdict
status
model
onJumpToClaim
onOpenTranscript
```

### 6.6 `<HumanDecisionBar>`

```
gateName
options: approved|changes_requested|reject
requireCommentWhen: changes_requested
resumable
onSubmit
```

### 6.7 `<RunTimeline>`

```
stages[] {id, label, status, startedAt, summary, artifactIds}
compact vs raw events disclosure
```

---

## 7. 구현 로드맵

### P0 (1–2주, 각각 독립 머지 가능)

**공통**

1. 프리미티브 타입/JSON schema 고정 (이 문서 §3)
2. Run 상태기계 + HumanDecision/VerificationCheck 분리 문서화 테스트

**MUNI lab**

1. HITL recovery UI + soft-fail (`awaiting_hitl_resume`)
2. `createThreadLabel` 연결
3. artifact 승격 + Library 라우트 + viewer 최소판
4. 단일 셸로 settings 편입, 깨진 browser/studio 링크 제거

**온톨로지랩**

1. projects/sessions 테이블 + API
2. proposals cursor pagination + 가상 스크롤
3. artifacts 테이블 + documents를 라이브러리로 노출
4. pack을 release snapshot으로 라이브러리 등록

### P1

1. ArtifactVersion + dependency edges
2. Provenance 5탭
3. Auto Reviewer finding cards (trace-only)
4. Split tabs / Merge tabs
5. `@/#//` composer grammar
6. 버전 diff

### P2

1. Skills/Connectors/Specialists
2. Compute environment history
3. Network allowlist UX
4. Credentials vault 이원화
5. Onboarding handoff
6. 대형 그래프 클러스터링

---

## 8. 앱별 “하지 말 것”

| 금지 | 이유 |
|---|---|
| CS 색/타이포 복제에 공수 투입 | 하니스 계약이 가치 |
| Reviewer와 인간 승인 큐 통합 | 역할·시점·책임 붕괴 |
| badge count를 DB truth로 사용 | CS 80 vs 81/130 불일치 재발 |
| `lineage_messages` 컬럼 맹복제 | 현재 설치에서 비활성 |
| changes_requested → 하드 실패만 | MUNI 라이브 치명 결함 |
| 검토 큐 전체 DOM 렌더 | 온톨로지 327건 장애 |
| Bun/SQLite monorepo shape 강제 | Nipo/제품 권장: 하니스 semantics only |
| academic seat/CS 런타임을 상업 경로에 편입 | NeoBio 정책 |

---

## 9. 수락 기준 (Definition of Done)

### MUNI lab

- [ ] evidence `changes_requested` 후에도 사용자가 재승인/재개/포크 가능
- [ ] 완료 Run의 sources·report가 Library에서 열림
- [ ] 세션 레일 제목이 32자 압축 + 중복 구분
- [ ] scientific 단일 셸에서 settings 도달
- [ ] `/browser` 허상 링크 없음
- [ ] 회귀: 기존 HITL approve 경로·성공 보고서 렌더 유지

### 온톨로지랩

- [ ] Project 전환 시 documents/proposals/packs 스코프 분리
- [ ] Review 큐 1,000건에서도 초기 DOM 행 수 상한 (예: ≤100)
- [ ] Artifacts 탭에서 원문·추출물·팩 열람
- [ ] 팩 빌드 = release snapshot artifact + 기존 fingerprint 유지
- [ ] verified는 인간 승인만 (기존 불변식 테스트 통과)
- [ ] critic는 여전히 자동 verified 불가

### 공통

- [ ] VerificationCheck와 HumanDecision 타입/테이블/API 분리
- [ ] ArtifactVersion immutable + checksum
- [ ] Provenance 최소 3탭(Code/Exec/Review) 동작
- [ ] 이 문서의 P0 테스트 목록 자동화

---

## 10. 증거 인덱스

| 주장 | 근거 |
|---|---|
| CS 0.1.25 / 8766/8767 | daemon log, BUILD.json, live tabs |
| CS UI shell / library / provenance / reviewer | live snapshots 2026-08-04 |
| CS DB counts / review lifecycle | `operon-cli.db` sqlite |
| OPERON/REVIEWER 계약 | `runtime/0.1.25-release/agents/*/metadata.yaml` |
| Compose 분리 표면 | live Add & configure + Session options |
| 온톨로지 큐/승인/팩 | `kgstore.py`, `routes.py`, `packbuilder.py`, `app.js` |
| 온톨로지 SSE jobs | `routes.py` `/jobs/stream`, `app.js` EventSource |
| MUNI 이중 셸/redirect | `web/ui/src/App.tsx` |
| MUNI HITL hard-fail | `live_mode.py`, `idea_to_council.py`, live error string |
| MUNI artifacts 0 vs success 2 | localStorage session audit |
| MUNI title helper unused | `createThreadLabel` in presentation.ts vs rail titles |
| 선행 UX 분석 | `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md` |

---

## 11. 다음 실행 커밋 슬라이스 (추천 순서)

1. **MUNI**: HITL resume soft-state + recovery buttons (사용자 고통 최대)
2. **MUNI**: session title + library route skeleton
3. **온톨로지**: proposals cursor + virtualize
4. **온톨로지**: projects/sessions scope
5. **양쪽**: ArtifactVersion + provenance Review tab
6. **양쪽**: auto Reviewer v0 (trace-only, optional model)

---

*이 문서는 Claude Science 구현 shape(Bun/SQLite)를 복제하라는 뜻이 아니라, 라이브 0.1.25에서 검증된 **워크벤치 하니스 semantics**를 온톨로지랩·MUNI lab 코드베이스에 이식하기 위한 구현 명세다.*
