# 온톨로지랩 시운전 시나리오 — 검수보고서 GAP 기준 (2026-08-06)

기준 문서: `docs/claude-science-reference/온톨로지랩_시운전_버그리포트_재검수_2026-08-05.md`
(GAP-O1~O5 우선순위). 모든 GAP이 수정·커밋된 상태를 검증한다.
시나리오 형식은 `docs/ONTOLOGYLAB-SMOKE-TEST-KO.md`를 따른다.

**시작 전 상태 기록**: 앱 아이콘 클릭 → Aside에 `http://127.0.0.1:8799/` 로드,
시작 상태(문서 · 검토 대기 · 승인 · 팩) 기록.

## 1. 앱 실행·아이콘 (검수보고서: 사용자 환경 재확인 필요)

1. `~/Applications/ontologylab.app` 클릭
2. Aside(기본 브라우저)에 온톨로지랩 탭이 열리는지 확인
3. `Stop ontologylab.command` 실행 → 앱 아이콘 재클릭

### 합격 기준

- 별도 네이티브 창 없이 Aside에서 열린다 (Tauri/웹뷰 아님)
- 주소가 `127.0.0.1:8799/`이고 왼쪽 메뉴·안내가 한국어다
- Stop → 재클릭 시 서버가 launchd로 자동 복구되고 새 세션으로 시작한다

## 2. GAP-O1 — 검토 큐 페이지네이션 (P0)

1. `검토` 탭 진입 (대기 327건 상태)
2. 표의 행 수를 개발자 도구로 측정
3. 스크롤을 바닥까지 내려 추가 로드 확인
4. 키보드 `j`/`k`로 끝까지 이동, `a`/`r`/`u`로 결정·되돌리기

### 합격 기준

- 첫 화면 렌더 행 ≤ 100 (327건이어도 50행만 생성 — DOM 노드·버튼 수 급감)
- 스크롤 또는 `j`/`k`가 바닥에 닿으면 다음 50행이 자동 로드되고 연속 이동이 끊기지 않는다
- 승인/거부 후 대기 건수가 즉시 갱신되고 되돌리기(`u`)가 동작한다

## 3. GAP-O2 — 실행 이력 영속 (P1)

1. 리서치 또는 추출 작업을 하나 실행해 완료시킨다
2. `Stop` → 앱 재실행 (서버 재시작)
3. 홈/작업 목록 확인

### 합격 기준

- 재시작 후 jobs 목록에 방금 실행이 `complete`로 남아 있다 (과거엔 전부 사라짐)
- 재시작 중이던 `running` 행이 있었다면 `failed`(interrupted by server restart)로 표시된다
- 실행 상세(진행 로그·소스 상태)가 열린다

## 4. GAP-O3 — 아티팩트 라이브러리 (P1)

1. `아티팩트` 탭 진입
2. 문서 그룹에서 새로 수집한 문서의 `원문 열기`
3. 팩을 하나 빌드한 뒤 릴리스 그룹 확인
4. 한쪽 그룹만 비어 있는 상태(예: 릴리스 없음)에서 빈 상태 힌트 확인

### 합격 기준

- 문서 그룹: 제목·출처와 함께 나열, `원문 열기`가 기존 문서 패널을 연다
- 릴리스 그룹: 팩 빌드 직후 카드가 나타나고 문서·개념·관계 수와 지문 앞 12자가 보인다
- 한쪽만 비었을 때 "수집한 문서가 없어요 / 빌드한 팩이 없어요" 힌트가 뜬다 (둘 다 비면 전체 빈 상태 카드)
- 기존 문서(기능 이전 수집분)는 목록에 없어도 정상 — 신규 문서부터 등록

## 5. GAP-O4 — 소스 실패 표면화 (P2)

1. `리서치`에서 주제 입력, 실행
2. 실행 중·완료 후 작업 상세의 소스별 상태 확인
3. (가능하면) 소스 일부가 실패하는 상황에서 집계 확인

### 합격 기준

- 소스별 배지: ✓ 응답 / ✕ 실패(종류 표시: 응답 없음·차단됨 등) / • 진행 중
- "소스 N개 중 M개 응답 · 실패 K" 집계가 보인다
- 전부 실패 시 "아무 소스도 응답하지 않았어요" 배너 + 재시도 안내가 뜬다

## 6. 슬라이스 1 — 신규 소스 (bioRxiv·PubMed)

1. `리서치` 화면 소스 목록에 `bioRxiv`·`PubMed`가 있는지 확인
2. 두 소스를 포함해 리서치 실행

### 합격 기준

- 소스 선택기에서 bioRxiv·PubMed가 활성화되어 있다 (키 불필요)
- 실행이 무오류로 끝나고, 응답한 소스에서 문서가 수집된다
- bioRxiv는 최근 4주 창에서 주제어로 필터된 프리프린트, PubMed는 초록·DOI가 담긴 결과가 온다

## 7. 슬라이스 2 — 레지스트리 강화 (advisory)

1. `검토` 탭에서 Gene/Protein/Drug/Variant 제안을 하나 선택
2. 근거 패널의 `레지스트리 확인` → `강화 실행`
3. 결과 확인 후 그 항목을 승인

### 합격 기준

- UniProt(유전자/단백질)·PubChem(약물)·ClinVar(변이) 조회 결과가 식별자·라벨·설명과 함께 표시된다
- 일치 항목 없음/시간 초과 시 "조회 실패 (이유)"로 표시된다
- "참고용이에요 — 승인은 여전히 사람이 합니다" 문구가 보인다
- **강화가 상태를 바꾸지 않는다** — 승인은 여전히 수동 버튼으로만, `verified` 경로 불변
- 종류가 매핑 없는 것(Disease 등)은 조회 없이 건너뛴다

## 8. 회귀 — 핵심 불변식 (검수보고서 §2.6)

1. 제안 승인 → `verified` + 팩 빌드에 반영 확인
2. 크리틱 실행 → 점수만 표시, 자동 승인 없음 확인
3. MCP로 팩 연결 → 읽기 전용 확인

### 합격 기준

- 승인은 `kgstore.approve` 경로로만, 크리틱·강화는 advisory
- 팩은 불변 + content hash 유지, MCP read-only

## 종합 판정 기록 양식

각 시나리오별: `합격 / 부분 합격 / 실패 / 검증 제한` + 실제 결과 + 스크린샷 + 시각.
전부 합격이면 **종합 판정: 합격**으로 기록.

---

# 시운전 실행 결과 기록 — 2026-08-06 (Aside 브라우저 시운전)

- **실행 시각**: 2026-08-06 14:27–15:13 KST
- **실행 방식**: Aside 브라우저로 `http://127.0.0.1:8799/` 라이브 조작 + DOM 계측 + API/DB 대조
- **시작 상태**: 문서 29 · 대기 327 · 승인 0 · 팩 1 (커밋 `8130cc9`)
- **종료 상태**: 문서 38 · 대기 327 · 승인 1 · 팩 2 (시운전 중 승인 1건·리서치 1회·팩 빌드 1건이 정상 산출물로 남음)

## 1. 앱 실행·아이콘 — 검증 제한 (사용자 환경 재확인 필요)

| 항목 | 결과 |
|---|---|
| 별도 네이티브 창 없음 | ✅ `Info.plist` `LSUIElement=true` — 도크 아이콘/네이티브 창 없음 (정적 확인) |
| 앱 아이콘 → Aside에서 열림 | ⚠️ launch 스크립트(`Contents/MacOS/launch`)가 `open -b at.studio.AsideBrowser http://127.0.0.1:8799/`를 수행하도록 구성 확인. 샌드박스 LaunchServices 제한(`LSCopyApplicationURLsForBundleIdentifier failed`)으로 브라우저 오픈 자체는 미검증 |
| 주소·한국어 UI | ✅ `127.0.0.1:8799/` 한국어 메뉴 확인 |
| launchd 자동 복구 | ✅ 에이전트 `at.ontologylab.server` 로드·`KeepAlive=true`·`ThrottleInterval 10` 확인 |
| 앱 아이콘 재사용 경로 | ✅ launch 스크립트 직접 실행: 기존 서버 감지(`is_ours`) → `.launcher.port` 복구 → exit 0 (서버 중복 기동 없음) |
| **Stop → 재클릭 주기** | ❌ 샌드박스에서 실행 불가: `launchctl bootout`·`pkill`·`kill`·`launchctl kickstart` 전부 `Operation not permitted`. **사용자 환경에서 실행 필요** |

**사용자 환경 확인 절차 (아래 체크리스트 참고)**: `~/Applications/Stop ontologylab.command` 실행 → 서버 중단 확인 → `ontologylab.app` 재클릭 → 8799 재기동·탭 오픈 확인.

## 2. GAP-O1 — 검토 큐 페이지네이션: **부분 합격** (스크롤 로드 결함 1건 발견)

| 항목 | 결과 | 근거 |
|---|---|---|
| 초기 렌더 행 ≤ 100 | ✅ **50행** | 327건 대기에서 첫 페이지 50행만 DOM 생성. 버튼 169개·체크박스 53개·전체 노드 1,265 (재검수 당시 200행·버튼 451·노드 4,231 대비 급감) |
| 키보드 `j`/`k` 바닥 → 다음 50행 로드 | ✅ | `j` 연타로 바닥 도달 시 `?cursor=` 요청(200 OK) → 50→100행, 연속 이동 끊김 없음 |
| 승인 후 대기 건수 즉시 갱신 | ✅ | `a` → 개념 승인 0→1, 카운트·배지 즉시 갱신 (POST approve 200) |
| 거부·되돌리기 | ✅ | `r` → 관계 대기 195→194 (POST reject 200), `u` → reopen 200으로 194→195 복원, "되돌렸어요: …" 표시 |
| **스크롤(마우스) 바닥 → 추가 로드** | ❌ **결함** | `reviewMaybeLoadMore()`가 `window` scroll에 바인딩돼 있는데 실제 스크롤 컨테이너는 `main`(`overflow-y:auto`, `body overflow:hidden`). 마우스 휠로 바닥까지 스크롤(실측)해도 cursor 요청 0건, 행 수 50 유지. 키보드 경로만 동작 |

- 재현 방법: 검토 탭 → 마우스 휠로 표 바닥까지 → 추가 50행이 로드되지 않음. `web/app.js:934`의 `window.addEventListener("scroll", …)`가 dead code 상태.
- 영향: 마우스 사용자는 327건 중 50건까지만 볼 수 있음 (키보드 전용 사용자만 전체 접근).
- 권장 수정: 스크롤 리스너를 `main`(스크롤 컨테이너)에 부착하거나 `body`의 `overflow:hidden` 해제.

## 3. GAP-O2 — 실행 이력 영속: **부분 합격** (재시작 검증은 사용자 환경)

| 항목 | 결과 | 근거 |
|---|---|---|
| 작업 실행 → 완료 | ✅ | 리서치 1회 실행(`research-20260806-150614`, mock 엔진) → `complete` (개념 +1) |
| jobs 목록에 complete 유지 | ✅ | `/api/jobs`에 `complete`·`extract`로 표시 |
| 디스크 영속 | ✅ | `runs` 테이블에 `running→complete` 기록(`finished_ts` 포함), `data/jobs/…/provenance.jsonl` 기록 |
| **재시작 후 복원** | ⚠️ 메커니즘 확인 | `server/jobs.py` `_load_persisted()`가 시작 시 `runs` 테이블에서 복원하는 코드 확인. 단 실제 프로세스 재시작은 샌드박스 차단 → **사용자 환경에서 확인 필요** |
| 재시작 중이던 `running` → `failed` 표시 | ⚠️ 미검증 | 서버 재시작 불가로 미검증 (사용자 환경) |

## 4. GAP-O3 — 아티팩트 라이브러리: **합격**

| 항목 | 결과 |
|---|---|
| 문서 그룹: 제목·출처·원문 열기 | ✅ 신규 수집 문서 9건이 제목+출처(URL/DOI)와 함께 나열. `원문 열기` → 기존 문서 패널(`doc-panel`)에 제목·출처·본문 로드 확인 |
| 릴리스 그룹: 팩 빌드 직후 카드 | ✅ `smoke-test-20260806-20260806-150312` 카드 — 문서 1 · 개념 1 · 관계 0 + 지문 `sha256:2d014…` |
| 한쪽만 비었을 때 힌트 | ✅ 릴리스 그룹만 비운 상태(테스트 팩 임시 이동 후 복원)에서 **"빌드한 팩이 없어요 — ③ 팩을 빌드하면 여기에 나타나요"** 라이브 확인 |
| 문서 빈 상태·전체 빈 상태 | ⚠️ 코드 확인만 가능 (`수집한 문서가 없어요 — ① 리서치로 문서를 모아 보세요` / `아직 아티팩트가 없어요 — …`) — 라이브는 양쪽 모두 채워진 상태라 미발생 |
| 기존 문서 미등록 허용 | ✅ 문서 그룹에는 신규 수집분 9건만 표시 (기존 29건 미표시 — 허용 기준) |
| 부수 확인 | 팩 빌드 가드 동작: 미완료 추출 1건 시 "pack build refused …" 거부 → 운영자 판단 오버라이드(체크박스+의도 입력)로 빌드 성공 |

## 5. GAP-O4 — 소스 실패 표면화: **합격**

리서치 실행(소스 9곳) 후 작업 상세 실측:

- ✅ 소스별 배지: `✓ Crossref 2 · ✓ OpenAlex 2 · ✓ bioRxiv 2 · ✓ PubMed 2 · ✓ ClinicalTrials.gov 2` / `✕ arXiv · ✕ Semantic Scholar · ✕ Europe PMC · ✕ SearXNG` (각각 **"응답 없음"**)
- ✅ 집계: **"소스 9개 중 5개 응답 · 실패 4"**
- ✅ 진행 중 표시: `답함 5/9` + 소스 목록별 `답하지 않음` 표기 (완료 후 상태 기준)
- ⚠️ 전부 실패 배너: 코드 확인 (`"아무 소스도 응답하지 않았어요."` + 재시도 안내, `web/app.js:1962`) — 이번 실행에서 5개가 응답해 라이브 미발생

## 6. 슬라이스 1 — bioRxiv·PubMed 신규 소스: **합격**

| 항목 | 결과 |
|---|---|
| 소스 선택기에 bioRxiv·PubMed 활성 | ✅ (`Europe PMC (PubMed)` 포함 9개 소스 표시, 키 연결 불필요) |
| 두 소스 포함 실행 → 무오류·문서 수집 | ✅ bioRxiv 2건 · PubMed 2건 응답, 문서 29→38, 개념 +1 |
| bioRxiv 최근 4주 창 + 주제어 필터 | ✅ 코드 확인: `BIORXIV_WINDOW_DAYS=28` 창 브라우즈 + 로컬 term 필터 (`paper_api.py:781-799, 1452-1470`) |
| PubMed 초록·DOI | ✅ esearch→efetch 파이프라인, 수집 문서 원문에 초록 포함·DOI 확인 |
| 관찰 사항 | bioRxiv 수집 2건 중 1건(`Ustilago maydis` 논문)은 주제 정합성이 약함 — 공통 term(예: cancer) 매치로 통과. 품질 관찰로 기록 |

## 7. 슬라이스 2 — 레지스트리 강화: **실패** (P1: UniProt 강화 크래시)

| 항목 | 결과 |
|---|---|
| 레지스트리 확인 패널·문구 | ✅ "UniProt·PubChem·ClinVar 조회 결과는 참고용이에요 — 승인은 여전히 사람이 합니다" |
| Drug → PubChem | ✅ "PubChem 조회 실패 (일치 항목 없음)" — not_found 경로 정상 렌더 |
| 비매핑 종류(Assay 등) 조회 스킵 | ✅ 서버가 조회 없이 건너뜀 (라이브: 즉시 "아직 조회한 답이 없어요") — 단 UI에는 강화 버튼이 노출됨(코드상 kind=node 조건) |
| **Gene/Protein → UniProt 강화** | ❌ **크래시**: ~25초 후 "내부 서버 오류" (HTTP 500) |
| 강화가 상태를 바꾸지 않음 | ✅ 크래시로 저장 0건 — verified 경로 불변 유지 |

**크래시 원인 (완전 재현)**: UniProt REST API가 `proteinDescription.recommendedName.fullName`을 `{"value": "…"}` 구조로 반환(신규 형식). `registry_lookup.lookup_uniprot`이 이를 그대로 `label`로 전달 → `kgstore.upsert_enrichment` SQLite 바인딩에서 `sqlite3.ProgrammingError: Error binding parameter 4: type 'dict' is not supported` (현재 코드로 in-memory 재현, 동일 에러 메시지 확인).

- 수정 방향: `label` 추출 시 `fullName.get("value") or fullName` 폴백, 또는 `_enrichment_payload`에서 형식 정규화. (조회 자체는 성공 — `Fanconi → PALB2(Q86YC2)`, `spliceosome → PRPF8(Q6P2Q9)` 식별)

## 8. 회귀 — 핵심 불변식: **합격**

| 항목 | 결과 | 근거 |
|---|---|---|
| 승인 → `verified` (승인 경로 유일) | ✅ | UI `a` → `POST /api/proposals/approve` 200 → DB `nodes.status=verified` 1건 (`ovarian tumor tissue`, `verified_ts` 기록) |
| 팩 빌드 반영 | ✅ | 새 팩 `smoke-test-20260806-…` `nodes_verified=1` — 승인한 노드만 포함 (pack.sqlite 확인) |
| 크리틱 → 점수만·자동 승인 없음 | ✅ | `POST /api/critic/run` 200, 상태 분포 불변(proposed 131/195, verified 1), `critic_reviews` 378건 점수·근거 기록 |
| 팩 불변 + content hash | ✅ | manifest `content_hash: sha256:2d014…` + `basis_commit: 8130cc9` |
| MCP read-only | ✅ | `mcp_server.py`: "eight read-only tools", `pack.sqlite`을 `mode=ro&immutable=1`로 오픈, `KGStore.open(read_only=True)` 전 구간. UI 문구 "인공지능은 읽기만" |

## 종합 판정

**부분 합격** — 8개 시나리오 중 4개 합격(4·5·6·8), 2개 부분 합격(2·3), 1개 실패(7), 1개 검증 제한(1).

| 시나리오 | 판정 | 핵심 |
|---|---|---|
| 1 앱 실행·아이콘 | 검증 제한 | Stop→재클릭은 사용자 환경 필요 (샌드박스 launchctl/kill 차단) |
| 2 GAP-O1 페이지네이션 | **부분 합격** | 초기 50행·키보드 로드·a/r/u 정상. **마우스 스크롤 로드 결함** (`window` 리스너 vs `main` 스크롤) |
| 3 GAP-O2 영속 | 부분 합격 | runs 테이블 영속·복원 코드 확인. 재시작 실증은 사용자 환경 |
| 4 GAP-O3 아티팩트 | 합격 | 문서/릴리스 그룹·원문 열기·빈 상태 힌트 전부 동작 |
| 5 GAP-O4 실패 표면화 | 합격 | 배지·"5/9 응답 · 실패 4" 집계 확인 |
| 6 슬라이스 1 (bioRxiv·PubMed) | 합격 | 두 소스 응답·수집, 28일 창+필터, 초록·DOI |
| 7 슬라이스 2 (레지스트리) | **실패** | UniProt 강화 500 크래시 (label dict 바인딩). Drug/스킵/문구는 정상 |
| 8 회귀 불변식 | 합격 | 승인 경로·크리틱 advisory·팩 hash·MCP read-only |

**시운전으로 새로 발견한 결함 2건**:
1. **P1** 검토 큐 마우스 스크롤 추가 로드 미동작 (GAP-O1의 절반 — 키보드 경로만 동작)
2. **P1** 레지스트리 강화 UniProt 경로 500 크래시 (UniProt 응답 형식 변경 미대응)

**사용자 환경 재확인 체크리스트** (이 샌드박스에서 실행 불가 — 직접 확인 필요):
1. `~/Applications/Stop ontologylab.command` 실행 → 서버 중단 확인 (웹 탭 새로고침 시 연결 실패)
2. `ontologylab.app` 아이콘 클릭 → `127.0.0.1:8799` 탭이 Aside에 열리고 한국어 화면 확인
3. 위 리서치(`research-20260806-150614`)가 재시작 후에도 `완료`로 남아 있는지 홈/리서치 실행 이력에서 확인
4. (선택) 재시작 직전 `running` 작업이 있었다면 `failed (interrupted by server restart)` 표시 확인

**증거**: `docs/images/smoke-2026-08-06-{review-queue,sources,artifacts,packs}.png` (라이브 화면 캡처)
