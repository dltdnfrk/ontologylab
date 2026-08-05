# 온톨로지랩(8799) · MUNI lab(5173) UI/UX 분석과 Claude Science 구조 이식 방안

- **작성일**: 2026-08-04
- **분석 대상 (실측, 라이브)**
  - 온톨로지랩: `http://127.0.0.1:8799/` — `~/Documents/MUNI/ontologylab` (Python FastAPI + 순수 JS SPA, venv 3.12)
  - MUNI lab: `http://127.0.0.1:5173/#/scientific` — `~/Documents/MUNI/muni-lab/web/ui` (React 18 + Vite + Tailwind, bun 실행)
  - 기준축: **Claude Science 0.1.25** (`http://localhost:8766/`, `~/.claude-science/runtime/0.1.25-release`, 데몬 30985)
- **증거 방식**: 라이브 브라우저 snapshot/screenshot + 코드 라인 근거 + 서브에이전트 독립 재검수 교차
- **라벨 규약**: `CS-observed`(Claude Science 라이브 관찰) / `사이트-observed` / `recommendation`(제안)

---

## 0. 한 줄 결론

**공통 셸(레일+탭+라이브러리)은 MUNI lab이 Claude Science에 가장 가깝고, 도메인 신뢰·승인 UX(근거→제안→크리틱→인간 승인→팩)는 온톨로지랩이 가장 강하다.** 이식 대상은 Claude의 색·버튼이 아니라 **Project → Session → Run → Versioned Artifact → Provenance → Reviewer**라는 지속성 구조와 "세션 컨텍스트 안에서 도구·산출물·검증이 한 타임라인으로 흐르는" 워크벤치 패턴이다.

| 축 | 온톨로지랩 | MUNI lab |
|---|---|---|
| 정보구조 | 파이프라인 전용 10탭 (평면) | 대화 셸 + 레거시 셸 (이중) |
| Project/Session | **없음** (전역 저장소 느낌) | Session 있음 (Project 없음, 제목 중복) |
| 아티팩트 | 팩(스냅샷)만, 일반 파일 없음 | 실행 결과물 승격 없음 (0 artifacts) |
| 신뢰 UX | **최강** (근거 패널·HITL·운영자 의도) | 정직한 실패 노출, 채택/제외 표시 |
| 최대 결함 | 검토 큐 327건 단일 렌더, 그래프 hairball | 깨진 라우트, 이중 셸, 실행 중단 상태 |
| CS 구조 근접도 | 40% | 65% |

---

## 1. 기준축: Claude Science 0.1.25 라이브 재검증 (이식 대상 명세)

### 1.1 런타임 사실 (CS-observed, 2026-08-04)
- 데몬: `claude-sc` pid 30985, 버전 **0.1.25**, 앱 포트 **8766** / 샌드박스 콘텐츠 8767 (8765는 온톨로지랩 launcher가 점유)
- 로그: `[daemon] listening on 127.0.0.1:8766 (pid 30985, version 0.1.25)`, MCP warmup 9409ms, 24 built-in MCP 커넥터 warm-up, micromamba 발견
- 모델: 새 세션 기본 **Opus 5**, 기존 세션 Haiku 4.5, Reviewer 기본 Sonnet 5 (`claude-sonnet-5` 확인)
- 저장 도메인: Project(3개) → Session(frame) → ArtifactVersion(213/234, 의존 엣지 391) → Review(62 verification checks) — DB 실측은 기존 메모리와 일치

### 1.2 대시보드 (CS-observed)
- `Projects` 섹션: 프로젝트 카드(제목, 세션 수, active 시각, actions) 3개 — 형광 프로브 프로젝트(2 sessions), 온톨로지(1), Example(4)
- `Recent sessions` 섹션: 세션 바로가기 3개
- 상단: `Search`, `New project`, `Customize`, `Account menu`

### 1.3 프로젝트 워크벤치 (CS-observed)
- 좌측 레일 = Sessions 다이얼로그: `New / Search / Customize`, 하단 `Files / Compute` 토글, 세션 목록(그룹: Older)
- 상단 바: `Sessions · Back to dashboard · 프로젝트명 · Search · Library(배지=80) · New session · Close session`
- 컴포저: `@ artifacts, # sessions, / skills, ⌘K to search` + `Add & configure` + `Session options` + 모델 선택 + 받아쓰기
- **열린 세션·파일이 탭 스트립으로 유지**: `New session | Files | claude_science_architecture.md`, `Split view`, `Merge tabs — back to a single strip` (CS-observed, 실제 UI 존재)
- `Add & configure`(Compose 다이얼로그): `Attach files(이미지·PDF·데이터) / Your files(호스트 파일시스템) / Model / Delegation(서브에이전트) / Request review(세션 감사) / Save as skill(세션 증류)`

### 1.4 아티팩트 라이브러리 (CS-observed, 형광 프로젝트)
- **80 artifacts**, 그룹: `Your uploads 8 · 4w ago`, 세션별 산출물 그룹(접기 가능, 예: Ontology Construction Papers Collection 42), `Actions for session`
- 카드 미리보기: 이미지 썸네일, Markdown 첫머리, CSV는 **행·열 수 + 컬럼 표본**(`~730 rows · 15 columns abc title 123 year abc authors …`), HTML iframe 썸네일
- 도구: `Search artifacts`, `Sort(Created ↓)`, Grid/List 라디오, Library actions
- 파일 형식 다양성: PNG, MD, CSV, JSON, PDF, HTML, TTL, OWL, JPEG

### 1.5 아티팩트 상세 (CS-observed)
- 버전 컨트롤: `Previous version | v2 (현재) | Next version`, `Show changes`, `Show preview`
- **버전 diff UX**: `Comparing to v1` 상태에서 inline diff(추가/삭제 라인 마크) + `Show preview`로 토글
- 액션 메뉴: `Star / Hide / View in context / Provenance / Copy link / Rename / Download .md / Export Metadata / Export to Cloud / Delete`
- **Provenance 뷰** (breadcrumb: 파일명 > Provenance): 탭 `Code / Execution Log / Messages / Environment / Review1 open finding`
  - Code: 생성 재구성 스크립트 + Inputs(사용된 입력 파일 리스트) + `Download standalone script + inputs + environment.yml`
  - Environment: 파이썬 버전·패키지·설치 이력 (서브에이전트 실측 94개 패키지)
  - Review: finding 카드 — `fail → resolved` 상태, 주장 원문 위치(`Jump to claim`), `View reviewer transcript`, 사용 모델 `claude-sonnet-5`

### 1.6 Reviewer 패턴 (CS-observed, 실제 finding)
- 인용부족·도구 검증 없는 서지정보 기입을 잡아 `fail`, 후속 정정으로 `resolved`
- **Reviewer는 실행을 다시 하지 않고 원본 실행 로그·아티팩트 추적으로만 판정** (agents/reviewer/metadata.yaml: python/bash/save_artifacts/web_search 제외)

### 1.7 설정 분류 (CS-observed, 라이브 재확인)
```
Capabilities: Skills · Connectors · Specialists · Memory · Compute · Network
Workspace:    Permissions · Credentials · Storage · Usage · General
```
- Skills 화면: `Search skills…`, `Add skill`, 그룹 `Featured Research skills from Anthropic`(19) / `Imported`(0, GitHub import) / `Personal Your custom skills`(4: Multisource Lit Harvest, Plant Pathogen Detection, Probe Diagnostic Workflow, Source Attribution Reviewer) → 총 24
- 각 스킬 행: `View 이름` + `Remove from all agents` switch
- (이전 실측 유지) Connectors 30, Specialists 3, Network = 도메인 번들(NCBI/Genomics/Proteomics/Literature/Clinical 등) + 사용자 허용 도메인 분리, Credentials는 커넥터와 별개(Literature Access 독립)

### 1.8 이식 대상 요약 (recommendation)
1. **Dashboard = Projects + Recent sessions** 2단 분리
2. **Project 컨텍스트의 좌측 레일**: New / Search / Sessions / Files·Artifacts / Compute / Customize
3. **세션·파일 탭 스트립 + Split view + Merge tabs**
4. **컴포저 멘션 문법**: `@ 아티팩트 / # 세션 / / 스킬 / ⌘K`
5. **아티팩트 라이브러리**: 그룹(업로드/세션별), 검색·정렬·Grid/List, 형식별 카드 프리뷰(CSV 행열 등)
6. **버전 + diff**: Previous/Next, Show changes(Comparing to vN), Show preview
7. **Provenance**: Code / Execution Log / Messages / Environment / Review 5탭 + standalone 재현 패키지 다운로드
8. **Reviewer finding 카드**: fail/warn/pass/inconclusive → resolved, jump-to-claim, transcript
9. **Settings 이원화**: Capabilities 6 + Workspace 5
10. **컴포즈 다이얼로그**: 첨부·모델·Delegation·Request review·Save as skill

---

## 2. 사이트 A: 온톨로지랩 (127.0.0.1:8799)

### 2.1 기술·구조 (사이트-observed)
- Python FastAPI + uvicorn(pid 95336, cwd=ontologylab) 서빙, 프론트는 **순수 JS SPA 1파일**: `web/app.js` 4,417줄 / `web/style.css` 2,650줄 / `web/index.html` 779줄 / `chat-session.js`·`localize.js`·`ui-utils.js`
- 탭 전환은 `showTab()`이 `display` 토글(모든 패널이 DOM에 상주) — `body[data-active-tab]`, CSS `@media(max-width:860px/1100px)` + `prefers-reduced-motion`
- 디자인 토큰: shadcn/ui 의미쌍 기반, 근사 블랙 캔버스(#262624) + 상태 3색(호박=제안/초록=검증/진홍=거부) + 상호작용 단일색(#c96442), Pretendard 단일 서체, 4px 그리드
- 접근성: `role=tablist/tab/tabpanel`, `aria-live`, `aria-describedby`, 화면별 단축키(`⌘K`·j/k/a/r/u/d)를 상태바에 노출 — `tests/test_agent_drivable_ui.py`가 "접근성 트리는 부가가 아니라 하중 지지 인터페이스"로 명문화

### 2.2 정보구조 (10개 1차 탭)
```
홈(대화) · 리서치 · 검토(327) · 팩 · 연결 · 병합 · 커뮤니티 · 그래프 · 엔진 · 설정
```
- 파이프라인 그룹(홈/리서치/검토/팩/연결) + 도구 그룹(병합/커뮤니티/그래프/엔진/설정) — 화면 주석에 "파이프라인" "도구" 구분 라벨 존재

### 2.3 화면별 실측
- **홈(대화)**: "무엇을 알아볼까요?" + 4개 칩(주제 리서치/검토 큐 보기/저장소 상태/할 수 있는 것) + 엔진 select(mock/claude/codex/gemini) + 보내기. 세션은 sessionStorage 기반(`chat-session.js`, 홈 진입 시 새 세션)
- **리서치**: 주제 입력 + 소스당 상한(1–25) + 엔진 + **전문까지 읽기 체크박스** (비용/근거 트레이드오프 사전 설명), `직접 넣기`(URL/파일/논문 검색어/소스/최대 개수), `추출만 다시 돌리기`, 샘플 문서(오프라인), 실행 테이블(작업/엔진/상태/결과/시작/종료, SSE 실시간+폴링 폴백), 문서 목록
- **검토(327)**: 집계(개념 대기 132 / 관계 대기 195 / 승인 0 / 문서 29), 정렬(확신도/크리틱/오래된 순), 선택 승인·거부, **크리틱 밴드**(엔진 선택 + 실행, "자동 승인되지 않아요 · 결정은 항상 사용자"), 테이블(종류/이름/확신도/작업) — **실측 DOM 약 4,262개, main scrollHeight 약 7,818px, 버튼 약 457개, 체크박스 약 201개** (서브에이전트 실측)
- **근거 패널(검토 옆)**: 항목 선택 시 추출 근거(본문 강조), 계보(추출 엔진·프롬프트 버전·시각·출처 문서), 추출기-크리틱 충돌 경고, "제안 2개는 본문에 근거 문장이 없음" 경고 — **이 앱의 최고 자산**
- **외부 레코드(주석 큐)**: 승인된 개념 이름으로 유전자·단백질·화합물 조회(UniProt 등) → 레코드 매칭 여부 재승인 — "사실 여부가 아니라 맞는 레코드인가"를 구분
- **팩**: 빌드(이름 + **미완료 허용 시 운영자 의도 필수**), 빌드된 팩 테이블(문서/개념/관계/검색 방식/**지문**/번들), 팩 비교(diff)
- **연결(MCP)**: 팩 카드 JSON 복사 → Claude Desktop 붙여넣기, "인공지능은 읽기만"
- **병합**: 중복 스캔 → 후보 카드, "스캐너는 제안만 · 합칠지는 직접 결정 · 거절한 쌍은 다시 안 물음"
- **커뮤니티**: 그래프 클러스터 테이블(ID/구성원/요약/방식)
- **그래프**: force-layout(클릭 요약·더블클릭 이웃), 보기(제안/검증)/타입 필터/강조 검색 — 실측 132 노드·191 엣지에서 이미 hairball (서브에이전트 실측)
- **엔진**: 프로바이더 등록(mock/claude/codex/gemini + `api:<id>` 커스텀, **키는 환경변수 이름만 저장**), 비용 요약(엔진 호출 257회: claude 71회·1:49, mock 186회)
- **설정**: 논문 소스 API 키(키체인 저장, 값 재노출 안 함, 연결 여부만), 기본값(엔진/모델/데이터 디렉터리/팩 디렉터리/SearXNG), 온톨로지 스키마 전환(agrochem-v1 개체 26 / biomed-v1 / software-docs-v1 — "바꿔도 이미 쌓인 제안은 그대로, 어휘는 새 추출부터")

### 2.4 강점 (보존 필수)
1. **인간 통제 메시지의 일관성**: "승인한 것만 지식이 됩니다 — 제가 대신 결정하지 않아요", "크리틱은 참고, 결정은 사용자" — 홈/검토/팩/연결 모든 화면에서 동일 언어
2. **근거 패널이 상시 노출**: "근거는 열어보는 게 아니라 늘 떠 있어야 한다" (index.html 주석)
3. **실행 전 비용·품질 트레이드오프 설명**(소스당 상한·전문까지 읽기·엔진)
4. **팩 불변성**: 승인분만 + 지문 + 운영자 의도 + MCP는 팩만 읽음
5. **정직한 보안**: 키체인 저장·환경변수 이름만·로컬 전용 문구
6. **키보드 우선 검토 UX**(j/k/a/r/u/d)와 에이전트 구동 가능한 ARIA (test_agent_drivable_ui.py)

### 2.5 문제 (이식 시 해결 대상)
1. **Project/Session 개념 없음** — 문서·제안·팩이 전역 저장소처럼 보임
2. **평면 IA**: 10개 기능이 전부 1차 내비게이션 → 핵심 흐름(리서치→검토→팩)과 보조 도구(병합/커뮤니티)가 동등한 무게
3. **검토 큐 무한 렌더**: 327건 전체 DOM (4,262 노드) — 가상화/페이지네이션 필수
4. **팩 ≠ 아티팩트 라이브러리**: 중간 산출물(원문 PDF, 추출 JSON, 그림)이 일반 파일로 조회·버전 관리되지 않음
5. **홈 대화가 파이프라인과 느슨**: 채팅은 답을 화면으로 데려다줄 뿐 실행 컨텍스트가 아님 (주석이 스스로 인정)
6. 크리틱이 수동 일괄 실행형 — CS의 "완료 후 자동 독립 Reviewer"와 역할·시점이 다름
7. 그래프 스케일링 한계, 단일 페이지 DOM 상주 구조

---

## 3. 사이트 B: MUNI lab (127.0.0.1:5173/#/scientific)

### 3.1 기술·구조 (사이트-observed)
- React 18 + Vite 5 + Tailwind 3 + react-router-dom 6 (HashRouter), bun dev(pid 71196, cwd=muni-lab/web/ui)
- **이중 셸 공존**:
  - `AiScientistWorkspace` (연구 대화 셸): `ResearchConversationRail`(좌) + `ResearchWorkspaceHeader`(상) + `ResearchConversationPage`(중앙) + `ResearchOutputPanel`(우측 서랍, sources/validation/summary 모드)
  - `AppRoutes` 레거시 셸(Sidebar + BackButton): `/settings`, `/muni`, `/browser/:runId`, `/report/:runId`
- 라우트 계약(`App.tsx`): `/scientific`(chat) · `/scientific/sources` · `/scientific/validation` → AiScientistWorkspace; `/studio/*`·`/browser` → **scientific으로 redirect**; `/muni`(MuniStudy, 라이브 `Failed to fetch`), `/settings`(606줄)
- 상태: `useResearchConversation`(localStorage 요약 + sessionStorage 자격증명 + WebSocket 이벤트 브리지), 턴/런/품질 상태기계(`runProgressStages.ts` 등 다수)
- 접근성: `aria-labelledby/current/pressed/live`, `prefers-reduced-motion`, `forced-colors`, 반응형 breakpoint 다수(48rem/32rem/20rem) — **셋 중 CSS 접근성 규칙 최다**

### 3.2 라이브 실행 실측 (가장 중요한 결함)
- 실행 중이던 세션: "최근 5년간 장내 미생물과 우울증…" — **8분 3초 동안 작업 · 39개 로그 · 출처 6 · 산출물 0**
- 결과: `MUNI lab · 실행 중단 — live mode requires approved HITL gate 'evidence'; got 'changes_requested'`
- **즉: 수집 근거 승인 게이트(HITL)가 'changes_requested'로 응답받아 파이프라인이 중단** — 대화에는 오류 문장만, 검증 레코드에는 "품질 판정 미확인"만 기록
- 실행 상세(접힘): 검색 경로 기록(검색어 10개) → 출처 발견·평가 12건 → 근거 요약 → 출처 감사 → 채택/제외 판단 6건 — **좋은 구조지만 raw 이벤트를 긴 accordion으로 전부 노출**
- 세션 목록: 9개 세션 중 고유 제목 2개뿐(프롬프트 전체가 제목) — 탐색성 낮음
- 사이드 레일: 새 대화(실행 중 잠금), 저장된 연구 대화, 연구 도구(출처 설정 · 3 / 검증 기록 / 실행 설정)
- 출처 설정(우측 패널): OpenAlex·Crossref·PubMed(공개, 사용 설정) / Semantic Scholar·Springer·Elsevier(API 키, 세션 한정) / OASIS(사용자 설정) / 직접 추가(이름·접근방식·주소·설명 — "출처 정보만 저장, 키는 저장 안 함")
- 검증 기록: 턴별 "작업 상태 / 품질 준비 / 판정 사유" 요약 + "최종 보고서를 대신하지 않습니다" 명시
- 실행 설정(/settings): Backend(로컬 CLI/API Keys), Provider(MiMo/OpenCode Go/폴백), MiMo Key/BaseURL/Model, OpenCode Go Key, Council visualization, Research effort(Quick/Deep/Max/Superdeep) — **이 화면은 Claude형 셸**

### 3.3 강점 (보존)
1. **실행 타임라인 카드**: "N초 동안 작업 · X 로그 · 출처 Y · 산출물 Z"를 대화에 요약
2. **채택/제외 출처 + DOI 인라인 표시**
3. **정직한 실패**: "실행 중단" 문구와 사유를 숨기지 않음; API 키 없으면 전송 버튼 비활성 + 사유 설명
4. **인간 승인 게이트 존재**: "수집된 근거를 승인해야 심의와 보고서 작성으로 넘어갑니다" (approve/changes)
5. **검색 경로 기록**: 어떤 검색어로 무엇을 찾았는지 전 과정 보존
6. 접근성·반응형 CSS 품질

### 3.4 문제 (이식 시 해결 대상)
1. **이중 셸**: Scientific(연구 셸) ↔ Settings/MUNI(레거시 셸)가 다른 제품처럼 전환 — 사용자 이동감 상실
2. **깨진/의미중복 라우트**: `/browser`·`/studio`가 scientific으로 redirect, Projects/Live artifacts가 모두 `/browser` → 실제 아티팩트 라이브러리 없음
3. **산출물 0**: 실행은 로그만 남기고 보고서·표·데이터를 아티팩트로 승격하지 않음 → `Live artifacts`가 빈 껍데기
4. **세션 제목 = 프롬프트 전체** (중복 다수)
5. **raw 이벤트 과다 노출**: 39개 로그를 접이식 목록으로 — 구조화된 Execution Log 필요
6. HITL 게이트 불일치로 **실행 중단 시 사용자 회복 경로 없음**(재시도·재승인 버튼 부재)
7. API 키가 세션 전용(sessionStorage) → 반복 설정 피로

---

## 4. 이식 설계: 공통 Workbench Shell + 데이터 프리미티브

### 4.1 공통 셸 (recommendation — CS-observed 구조를 정본으로)
```
Dashboard
├─ Projects (카드: 제목·세션 수·active)
└─ Recent sessions

Project (좌측 레일)
├─ New session · Search · Customize
├─ Sessions (그룹: Today/Yesterday/Older)
├─ Files / Artifacts · Compute
└─ (하단) Settings

Center workspace
├─ 탭 스트립: Session · Files · Artifact (Split view / Merge tabs)
├─ 대화 + 실행 타임라인 (단계별 접힘·상태·아티팩트 트레이)
└─ 컴포저: @ 아티팩트 / # 세션 / / 스킬 / ⌘K

Right pane (문맥 유지)
├─ Artifact (미리보기 + 버전 diff)
├─ Sources · Review · Run · Provenance
└─ Compute / Environment
```

### 4.2 공통 데이터 프리미티브 (recommendation)
`Project · Session · Run · ToolEvent · SourceRecord · Artifact · ArtifactVersion · ArtifactDependency · ReviewCheck · HumanDecision · ComputeEnvironment · CredentialReference · ReleaseSnapshot`
→ **Nipo Science SPEC-v0.6의 authority chain**(Project→Session→ActionPlan/approval→Run→Execution→ArtifactVersion→Review→Export)과 1:1로 정렬 가능. SPEC §6은 v0.6에서 UI 작업을 금지하므로 이 이식은 **차기 스펙(0.7)의 product-shell increment로 정의**할 것.

### 4.3 온톨로지랩 매핑
| 온톨로지랩 | 공통 프리미티브 |
|---|---|
| 수집 문서 | SourceArtifact |
| 개념·관계 제안 | CandidateArtifact + ReviewItem |
| 크리틱 점수 | AutomatedReviewCheck |
| 승인/거부 | HumanDecision |
| 그래프 | GraphArtifact |
| 팩 | ReleaseSnapshotArtifact |
| 계보(엔진·프롬프트·시각·문서) | Provenance 도메인 요약 탭 |

### 4.4 MUNI lab 매핑
| MUNI lab | 공통 프리미티브 |
|---|---|
| 연구 실행 | Run |
| 검색·평가 로그 | ToolEvent / ExecutionLog |
| 채택 출처 | SourceRecord |
| 보고서·표·요약 | ArtifactVersion (실행 완료 시 확정) |
| 검증 기록 | ReviewerRun |
| 수집 근거 승인 | HumanDecision |
| Study | Project template 또는 Skill |

---

## 5. 앱별 구체 이식안

### 5.1 온톨로지랩 (10탭 → 5메뉴 수준으로 재편)
1. **Sessions** — 홈 대화를 세션 타임라인으로; 리서치는 "새 세션의 작업 유형"
2. **Review** — 인간 승인 큐 유지 + **가상 스크롤/페이지네이션** (327건 전체 렌더 제거)
3. **Artifacts** — CS형 라이브러리: 업로드/세션별 그룹, 검색·정렬·Grid/List, 원문·추출 JSON·그림 카드
4. **Graph** — 병합·커뮤니티를 내부 탭으로 흡수
5. **Customize** — 엔진·API 키(키체인)·스키마·기본값 통합
- 팩은 Artifact의 "Release snapshot" 동작으로, 근거 패널은 Provenance의 Evidence 탭으로 확장
- **자동 Reviewer(오류 발견)와 인간 승인 큐(지식 채택)를 절대 합치지 않는다** — CS-observed의 역할 분리 유지

### 5.2 MUNI lab (이중 셸 → 단일 셸)
1. `/settings`에 이미 있는 Claude형 셸을 **전체 앱의 유일한 셸**로 승격, Scientific을 center workspace로 이식
2. `/browser`·`/studio` 가짜 라우트 제거, `/muni`를 Project template으로 재정의
3. **세션 자동 제목**(LLM 또는 규칙 기반 — 프롬프트 첫 40자 + 주제 압축)
4. 실행 산출물을 **즉시 임시 Artifact로 승격 → 완료 시 버전 확정** (39 logs · 6 sources · 0 artifacts 해소)
5. raw accordion → 구조화 Execution Log(단계·도구·성공/실패), 대화에는 현재 단계 + 핵심 3~5 이벤트만
6. HITL 게이트 중단 시 **재승인/재시도 회복 UI** (현재 "실행 중단" 표시만 존재)
7. 우측 Output 패널을 `Artifacts / Sources / Review / Run` 탭으로 전환
8. API 키: 암호화 자격증명 저장소 + 세션 임시 옵션 이원화

### 5.3 두 앱 공통 (P0→P1→P2)
- **P0**: 단일 셸 확정 · 라우트 계약 테스트 · Project/Session/Run/Artifact 기본 모델 · 세션 자동 제목 · 아티팩트 라이브러리+미리보기 · MUNI 산출물→Artifact 저장 · 온톨로지 검토 큐 가상화 · 통일된 run 상태기계(idle/planning/searching/awaiting_approval/synthesizing/reviewing/completed/failed/cancelled)
- **P1**: ArtifactVersion + dependency edge · Provenance 5탭(Code/Execution Log/Messages/Environment/Review) · 자동 Reviewer finding 카드 · split view + 탭 스트립 · 전역 검색 + `@/#//` · 통합 우측 패널 · 팩→Release Snapshot
- **P2**: Skills/Connectors/Specialists · Compute 모니터 + 환경 이력 · Network allowlist · Permissions/Credentials/Storage/Usage · 온보딩(4질문→파일→3작업→권한→세션 handoff) · 대형 그래프 클러스터링

---

## 6. 검증·증거 요약

| 항목 | 근거 |
|---|---|
| CS 버전/포트 | `~/.claude-science/logs/server-20260804.log` (`version 0.1.25`, 8766/8767) |
| CS 80 artifacts/버전 diff/Provenance/Reviewer | 라이브 snapshot (`claude-fluorescence-library.txt`, `claude-version-diff.txt`, `claude-provenance-panel.txt`) |
| CS 설정 분류 | `claude-customize.txt` (Capabilities 6 + Workspace 5), `claude-skills-settings.txt` (Skills 24) |
| 온톨로지랩 327건 큐 DOM 규모 | 서브에이전트 실측(4,262 노드 / 7,818px / 버튼 457) |
| MUNI 실행 중단 | 라이브 `muni-live-raw-events.txt` (`HITL gate 'evidence' got 'changes_requested'`, 39 logs·0 artifacts) |
| MUNI 이중 셸/라우트 | `App.tsx:67-110`, `AiScientistWorkspace.tsx:69-109`, `Sidebar.tsx:153-166` |
| 온톨로지랩 구조 | `web/index.html`(779줄), `web/app.js`(4,417줄), `tests/test_agent_drivable_ui.py` |
| Nipo 연결 | `nipo-science/docs/spec/SPEC-v0.6.md` §0/§6 (authority chain, UI 비목표) |

### 스크린샷 (세션 tmp, 참고용)
- 온톨로지랩: `tmp/ontology-1-검토.png`(검토 큐), `tmp/ontology-6-그래프.png`, `tmp/ontology-8-설정.png`, `tmp/ontology-evidence-detail.png`
- MUNI lab: `tmp/muni-scientific.png`, `tmp/muni-sources.png`, `tmp/muni-settings.png`, `tmp/muni-live-activity-open.png`
- Claude Science: `tmp/claude-dashboard.png`, `tmp/claude-fluorescence-library.png`(80 artifacts), `tmp/claude-version-diff.png`, `tmp/claude-provenance-panel.png`, `tmp/claude-reviewer-panel.png`, `tmp/claude-customize.png`, `tmp/claude-skills-settings.png`

---

## 7. 다음 단계 제안 (작업 지시서 후보)

1. 이 문서를 바탕으로 **"CS 3-패널 워크벤치 이식 작업 지시서"** 작성 (MUNI lab 단일 셸 우선, 온톨로지랩 Review/Artifacts 모듈 흡수)
2. Nipo Science는 SPEC-v0.7 초안에 product-shell increment 항목 추가 (kernel 계약 변경 없음)
3. MUNI lab: HITL 게이트 회복 UI + 세션 자동 제목 + 산출물→Artifact 승격을 첫 커밋으로
4. 온톨로지랩: 검토 큐 가상화 + Artifacts 라이브러리(파일 그룹/버전)를 첫 커밋으로
