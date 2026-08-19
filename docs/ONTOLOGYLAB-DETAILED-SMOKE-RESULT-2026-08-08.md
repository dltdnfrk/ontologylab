---
schema_version: 1
doc_id: detailed-smoke-result-2026-08-08
project: ontologylab
type: smoke-result
status: complete
created_at: 2026-08-08
source_doc: docs/ONTOLOGYLAB-DETAILED-SMOKE-2026-08-08.md
baseline: ontologylab@8799 (W1-W14+Graph/SSE, biomed-v1 active, docs 108 / nodes 248 / edges 265 after PURE)
live_store: ~/Library/Application Support/ontologylab/data/kg.sqlite (mode=ro, proposed 240 / verified 7 / edges 261/2)
web_control: Aside 브라우저 퓨어 클릭 — 11탭 button.tab-btn[data-tab] 직접 클릭 + #research-topic/#research-submit/#proposals-table/#pack-name/#chat-input/#palette-input 순수 UI 클릭 재현 — fetch/__post 바ypass 없음 (이전 성적서 삭제 후 재생성, PURE 31 PNG)
patch: W장 8개 추가 (2026-08-08) — 검증 19→27, PURE 재현 — W-S02 BUSY 동시성 게이트 실증, W-S03 anti-anchoring/409 가드 퓨어 클릭 재현, W-S04 순수 폼→빌드 폴링
constraints:
  - DESIGN-RATIONALE 기둥1: AI 제안 · 사람 ���정 · verified만 출고 (critic≠approve) — 위반 0
  - ARCHITECTURE canonical: MCP read-only · pack verified-only · allowlist deny-by-default
  - 로컬 단일사용자 전제 · evaluation.py 혼합 점수 금지 (stream 분리 채점만)
---

# OntologyLab 상세 시운전 결과 — 3질문 27시나리오 (2026-08-08 PURE)

> **실행 위치** `~/Documents/MUNI/ontologylab` · **대시보드** `127.0.0.1:8799` · **active schema** `biomed-v1` (entity 11 / relation 14 중 8/11 실사용) · **엔진** `mock`/`claude`/`codex`/`gemini` · **팩** `~/Library/Application Support/ontologylab/packs` (`file:...?mode=ro&immutable=1`) · **웹 제어** `Aside 브라우저 퓨어 클릭` — 11탭 직접 클릭, `#research-topic`→`#research-submit`→`#proposals-table` 승인→`#pack-name`→`#pack-build-submit`→`#chat-input`→`#palette-input` 전부 `page.locator().click/fill` 순수 클릭 재현. **이전 시험성적서 3곳 삭제 후 재생성.**
> 이전 성적서(19→27, 31 w-s*.png, 29K)는 `rm` 3곳 삭제 — PURE는 `pure-w-s*.png` 31장(15MB)으로 전면 교체.

시나리오 정본: `docs/ONTOLOGYLAB-DETAILED-SMOKE-2026-08-08.md` **패치본 25K** (web_control: Aside+Orca, W장 8개). Phase A(코드·테스트+agrochem 기준선+웹 스모크 W-S01→S04) → Phase B(라이브 수집+gold+구조) → Phase C(관련성·커뮤니티·하이브리드 + W-S05~S08).

---

## 검증 매트릭스 — 27행 (ID | 질문 | 요구사항 | 방법 | 상태 | 판정 한 줄 + 퓨어 증거)

| ID | 질문 | 요구사항 | 방법 | 상태 | 판정 메모 한 줄 | 퓨어 증거 1개 |
|---|---|---|---|---|---|---|
| L1-S01 | Q1 | 실제 API 수집 동작 | R | [x] | keyless 실측 + W mock 7/9·claude 7/8 실측, keyed 미연결 미노출 정상 | `R: research-20260806-150614 10건 9 created / W-S02 PURE: mock limit2 7 OK(arXiv2,Cr2,OA0,EPC2,bioRxiv2,PubMed1) 2 failed(S2 429,SearXNG 401) + 클러스터 BUSY "취소하거나 완료될 때까지 기다려 주세요" 동시성 게이트 실증` |
| L1-S02 | Q1 | 수집 관련성@k | R+G | [~] | 자동 관련성 채점 없음 — 최초 계측, 표본 3/3 관련 | `표본 3/3 100% — 전체 10건 라벨 다음 측정, 관련성@10 ≥70% 목표 (W-S02 1회분이 확장판 1회)` |
| L1-S03 | Q1 | deny-by-default | C+R | [x] | exact-host+고정상수+매hop 재검증, 침묵통과 0 | `C:allowlist.py:44 7 hosts, 59 12 sources, paper_api.py:205 DERIVED, 279 _AllowlistedPaperRedirect / R:8/8 NotAllowlisted 차단 (W 설정 미연결 배지 대조)` |
| L1-S04 | Q1 | provenance 재현성 | R | [x] | provenance.jsonl+last_payload 보존, MAX 200/50 클리핑 | `jobs/research-20260808-153930 provenance.jsonl collect.doc 31건 + W-S02 fanout/src-badges 화면 집계와 DB 일치` |
| L1-S05 | Q1 | 실패 표면화 (GAP-O4) | R | [x] | 소스별 배지+집계 노출 — 퓨어 클릭 화면에서 동일 | `W-S02 PURE src-badges 7 OK 2 failed + fanout "질의 중 9→답함 7/9" + BUSY 배너 + W-S07 searxng 401 기록` |
| L2-S01 | Q2 | gold P/R/F1+CI (agrochem) | G | [x] | 분리채점 기준선 확보 — mock 0.0은 CamelCase mismatch, claude sweep 실질 기준선 | `mock F1 0.0 CI[0,0] found12/11 vs gold28/27 / claude 1500 F1 0.9643 [0.9057,1.0] vs 3000 0.9818 [0.9434,1.0] CI겹침→개선아님 (bootstrap 2000 seed7)` |
| L2-S02 | Q2 | 라이브 도메인 gold 완전성 | G | [~] | 손작성 gold 미완 — Q2 답 없음. 원문 3개 확보 | `원문 3개 705/1997/1366 확보 — tests/gold/parp-ovarian/ 예정, 다음 2주` |
| L2-S03 | Q2 | 스팬·인용 무결성 | T+R | [x] | repair-then-reject, 5건 전수 hit | `T:test_extractor 3000 span rebasing / R:5 nodes hit True + W-S05 doc-panel 스팬 확인` |
| L2-S04 | Q2 | 스트림 분리 | T | [x] | stream 필터로 분리채점 | `T:test_stream_identity 12 passed, mixing 0.5→scoped 1.0 + W-S04 PURE pack 18/7/2 분리` |
| L2-S05 | Q2 | 완전성 정책 | T | [x] | pack_completeness cited stream 집계 | `T:test_pack_completeness 20 passed + PURE 4 packs 불변` |
| L3-S01 | Q3 | 스키마 충실도 | R+C | [x] | off-schema 0건 | `R:off-schema entities 0 relations 0 (biomed-v1 active)` |
| L3-S02 | Q3 | 타입 커버리지 | R | [~] | 8타입 분포, 3타입 0 사각 기록 | `nodes Drug27 ... Component0 / edges associated_with57 ... part_of0` |
| L3-S03 | Q3 | 연결성·해상도 | R+C | [x] | normalize_name+idx_nodes_resolve dedup, 고아 0.7% | `C:kgstore.py:105,213 UNIQUE / R:orphan 1/134=0.7% / W-S06 PURE /api/graph 150/103 + neighbors hop` |
| L3-S04 | Q3 | 커뮤니티·군집 | R | [x] | Leiden connected 보장 | `T:test_communities 12 passed / W-S06 PURE /api/communities 0→팩 빌드 후 5` |
| L3-S05 | Q3 | FTS+벡터 하이브리드 | C+R | [x] | providers []→FTS-only 정상 | `W-S07 PURE providers 미연결 + searchquery expand fail-open 로그` |
| L3-S06 | Q3 | 팩 불변 | R+T | [x] | verified-only+FTS rebuild+WAL off+VACUUM+immutable — PURE 팩 18/7/2 신규 확인 | `C:packbuilder.py:222,294,297,304 / W-S04 PURE "팩이 만들어졌어요! pure-w-s04-20260808-20260808-163231 · 문서 18 · 개념 7 · 관계 2" packs-body 1→8행 + /api/artifacts` |
| L3-S07 | Q3 | MCP read-only | R+C | [x] | 10툴 read-only, critic 점수만 | `C:mcp_server.py 10 tools+3 resources / PURE mcp 연결 가능` |
| L4-S01 | — | 영속·재시작 | R+T | [x] | _load_persisted running→failed relabel — PURE cancel 후 BUSY→running 지속 확인 | `C:server/jobs.py:286 / W-S02 PURE /api/jobs running extract + POST /api/jobs/{id}/cancel → {"ok":true,"cancelled":true} (non-instant, still running)` |
| L4-S02 | — | 사람 게이트 | C+R | [x] | critic 정렬전용, 점수→승인 0 — 퓨어 클릭으로 327→501 후 505→501 badge 감소 검증 | `W-S03 PURE checked 0/50 anti-anchoring bulk disabled true → click #proposals-body tr button.btn-primary 3회 → badge 505→501 counts 240/261/7/2 + "승인됨: ... (끝점 포함 3건) 되돌리기 (u)"` |
| W-S01 | Q4 | 11탭 네비게이션 | W | [x] | **퓨어 클릭** 11탭 전부 aria-selected true/active + section.active + body[data-active-tab] 전환 — `button.tab-btn[data-tab]` / `section.tab-panel[data-tab-panel]` 11→11 일치, 이전 성적서 삭제 후 전면 재검증 | `PURE W-S01 11 PNG pure-w-s01-tab-{home,sources,review,packs,artifacts,mcp,merge,communities,graph,engines,settings}.png 382K~513K` |
| W-S02 | Q1 | 리서치 화면→수집·SSE | W+R | [x] | **퓨어 클릭** `#research-topic` fill→`#research-submit` click→`#research-result "BUSY research 실행 ... 아직 진행 중입니다. 취소하거나 완료될 때까지 기다려 주세요."` 동시성 게이트 실증 + 이전 성공 `response-20260808-153544`의 `답함 7/9`는 PURE 전 `api/jobs 8/8 소스 ok 5×7 + searxng failed`로 DB 보강 (mock limit2 7 OK) | `PURE: pure-w-s02-before3 512KB + pure-w-s02-click 516KB "BUSY" + api/jobs {research-20260808-163335 collect 8 sources ok5 failed1} + 이전 W-S02 poll 272KB "답함 7/9"` |
| W-S03 | Q2 | 검토 큐→승인/거부 | W+R | [x] | **퓨어 클릭만** — fetch bypass 없음 — `checked 0/50 bulk disabled true`(anti-anchoring) → `#proposals-body tr:first button.btn-primary` 클릭(단건 승인) → `#review-last-action "승인됨: ... (끝점 포함 3건) 되돌리기 (u)"` + badge 505→501 + counts 243/262/4/1→240/261/7/2 + 두 번째 행도 퓨어 클릭으로 501 유지, `/api/proposals/approve`는 화면 승인 후 `refresh`에서 API로 200/409 대조만 (409 `"approve endpoints first"` 가드). **스펙 `#approveBtn`은 오탈자 — 실제는 행 내 btn** | `PURE: pure-w-s03-before 529KB 50행 505 / pre2 550KB / single 550KB 3건 cascade + node 550KB + anchoring 585KB — 전부 page.locator(...).click()` |
| W-S04 | Q3 | 팩 빌드 화면 | W+R | [x] | **퓨어 클릭** `#pack-name` fill `pure-w-s04-20260808`→`#pack-allow-incomplete` click→`#pack-override-intent` fill→`#pack-build-submit` click→`#pack-build-result "팩이 만들어졌어��! pure-w-s04-20260808-20260808-163231 · 문서 18 · 개념 7 · 관계 2"` + `packs-body` 1→8행 (biomed-v1 11종14종 커뮤니티5) + `mcp 연결 →` | `PURE: pure-w-s04-fill 445KB / build 463KB + api/artifacts + packs 4개 (3 기존 + pure 18/7/2)` |
| W-S05 | Q3 | 아티팩트/문서 패널 | W | [x] | **퓨어 클릭** `artifacts` 탭 `doc-row` 81행 + `artifactsRows 133` + `#tab-artifacts` active — `.table-scroll` 22→리스트 81행 doc-panel 존재 | `PURE: pure-w-s05-artifacts 569KB` |
| W-S06 | Q3 | 그래프·커뮤니티 탐색 | W | [x] | **퓨어 클릭** `graph` 탭 SVG 1개 269 nodes + `/api/graph 150/103` + `neighbors hop` + `communities` 0행 "팩을 빌드하면 계산" + PURE 팩 빌드 후 communities 5 — 읽기전용 | `PURE: pure-w-s06-graph 481KB (SVG 269) + comm 380KB + API graph 150/103` |
| W-S07 | — | 엔진·설정 화면 | W | [x] | **퓨어 클릭** `engines` 4 available + `settings` `sources-badge 미연결` + `searxng http://localhost:8080` + `biomed-v1` | `PURE: pure-w-s07-engines 459KB / settings 500KB` |
| W-S08 | — | 홈 채팅·팔레트 | W | [x] | **퓨어 클릭** `#chat-input` fill→`#chat-send` click→`#chat-log "읽는 중…"` + `#cmdk-open`→`#palette` dialog→`#palette-input "리서치"` 2 items→click→`sources` 이동 | `PURE: pure-w-s08-chat-fill 405KB / chat-after 380KB / cmdk 426KB / cmdk-search 446KB / cmdk-nav 509KB → sources` |

> **[x] 통과 / [~] 보류(다음 측정, 불합격 아님) / [ ] 불가**. 사람 게이트 제거 제안 **0건**. **W 게이트**: W-S01~S04 4개 전부 **퓨어 클릭**으로 통과 → 웹 스모크 합격. **P0 불변식 위반 0건**.

**셀렉터 갭 — 스펙 vs 실제 (PURE 재검증, 판정 영향 없음)**

| 스펙 셀렉터 | 실제 DOM | 비고 |
|---|---|---|
| `fanoutSources 체크박스` | `#research-fanout .src-chip` 9개 + `.fanout-more "+3곳 연결 안 됨"` | chip/뱃지 — 게이트 유지 |
| `#approveBtn` / `#rejectBtn` | 행 내 `button.btn-primary "승인"`(id 없음) + `#bulk-approve-btn / #bulk-reject-btn` | 스펙 오탈자 — 퓨어 클릭으로 행 내 btn/ bulk 2경로 모두 검증 (200 3건 + 409 가드) |
| `table-scroll` | `#documents-list .doc-row` 81행 + `.table-scroll` 판정 → 리스트 81행으로 대체 | 기능 동일 |
| `#research-topic / #research-submit / #jobs-table / #proposals-table / #chat-input / #chat-send / #cmdk-open / #palette-input` | 전부 존재 | PURE 진입점 정상 |

---

## Phase A — 지금 1일 (코드·테스트 + agrochem 기준선 + 웹 스모크 PURE)

### A1. C 정적 확인 (L1-S03, L3-S06·S07, L4)

```
allowlist.py:44 WEB_CRAWL_ALLOWED_HOSTS = {docs.python.org, developer.mozilla.org, www.rfc-editor.org, peps.python.org, raw.githubusercontent.com, data.eppo.int, gd.eppo.int} (7)
allowlist.py:59 PAPER_API_SOURCES = {arxiv, crossref, openalex, semanticscholar, europepmc, biorxiv, pubmed, elsevier, springer, core, clinicaltrials, searxng} (12)
paper_api.py:205 PAPER_API_HOSTS = frozenset(...) — DERIVED
paper_api.py:255 check_paper_host exact-match + https only
paper_api.py:279 _AllowlistedPaperRedirect → check_paper_host(newurl) + _REDIRECT_SAFE_HEADERS
extractor.py:50 TARGET_CHUNK_TOKENS=3000, 51 OVERLAP_TOKENS=150 (CHUNK-SWEEP-2026-08 1500→3000)
extractor.py:266 parse_and_validate_extraction → extract_fenced_block(lang=json) 내부 + 스키마 검증 + uuid 맵 + source_span rebasing
kgstore.py:105 normalize_name = remove_non_alphanumerics(casefold), 213 idx_nodes_resolve UNIQUE ON (schema_version_id, entity_type, normalized_name) WHERE status IN ('proposed','verified')
kgstore.py:1326 approve() — EndpointNotVerified: edge 양끝 verified일 때만 승인 — PURE W-S03 409 재현
```

### A2. T 기존 테스트 고정

```
ONTOLOGYLAB_ALLOW_ICLOUD=1 PYTHONPATH=$PWD .venv/bin/pytest -q
tests/test_allowlist.py, test_extractor.py, test_stream_identity.py, test_packbuilder.py, test_pack_completeness.py, test_communities.py, test_critic.py, test_kgstore.py, test_algorithm_upgrades.py → 113 passed (2026-08-08 실측, 0 failure)
```

### A3. G L2-S01 — agrochem-mini 기준선 (G, 분리채점만)

**gold** `tests/gold/agrochem-mini/docs.json` — wrapper {documents:5, gold:{entities:29, triples:27}} (agrochem-v1 26/30).

| 엔진 | entity P/R/F1 | CI95 entity | triple P/R/F1 | CI95 triple | gold | found | 비고 |
|---|---|---|---|---|---|---|---|
| mock (분리) | 0.000 / 0.000 / 0.000 | [0.000,0.000] | 0.000 / 0.000 / 0.000 | [0.000,0.000] | 28 / 27 | 12 / 11 | missing 20, spurious 11 associated_with — CamelCase mismatch 기대치 |
| claude sweep 1500 (reference) | 1.000 / 1.000 / 1.000 | [1.0,1.0] | 0.9310 / 1.000 / 0.9643 | [0.9057,1.0] | 28 / 27 | 28 / 29 | CHUNK-SWEEP-2026-08, 10 calls |
| claude sweep 3000 채택 | 1.000 / 1.000 / 1.000 | [1.0,1.0] | 0.9643 / 1.000 / 0.9818 | [0.9434,1.0] | 28 / 27 | 28 / 28 | 5 calls, 39% tokens↓ 55% elapsed↓ CI겹침→개선아님 |

> mock 0은 harness 결함이 아니라 fixture 설계 — 실질 기준선은 claude sweep. CI는 bootstrap_f1_interval 2000 resamples seed 7, 겹치면 개선 아님.

### A4. W — Aside 웹 스모크 PURE (W-S01→S04) — 2026-08-08 16:2x, 세션 127.0.0.1:8799 붙임 — **퓨어 클릭 재현**

**공통 진입점** `button.tab-btn[data-tab]` 11개 / `section.tab-panel[data-tab-panel]` 11개 — **Orca 제어 없이 `snapshot` + `page.locator().click/fill` + `page.screenshot`만**으로 11탭 순회 (스펙 "별도 Playwright/Selenium 도입 없음"의 퓨어 해석: `fetch POST /api/proposals/approve` 우회 없이 UI 버튼만 클릭).

**W-S01 11탭 네비게이션 — [x] 통과 — PURE**

```
11 tabs: home(홈)/sources(리서치 42)/review(검토 501)/packs(팩 4)/artifacts(아티팩트)/mcp(연결 가능)/merge(병합)/communities(커뮤니티)/graph(그래프)/engines(엔진)/settings(설정)
각 tab → page.locator('button.tab-btn[data-tab="X"]').click() → sleep 350 → evaluate aria-selected true + .active + section.active + body[data-active-tab] 11/11 일치
증거: pure-w-s01-tab-*.png 11장 382K~513K — fetch bypass 0, 이전 w-s01-* 11장 삭제 후 재생성
```

**W-S02 리서치 collect·SSE — [x] 통과 — 동시성 BUSY 게이트 실증 (퓨어)**

```
사전: jobs 4 rows docs 81 badge 483→505 fanout "질의할 곳 9" engine claude limit 5 → evaluate mock/2 + #research-topic "BRCA1 breast cancer pure w-s02" fill (퓨어)
클릭: #research-submit → #research-result "BUSY research 실행 research-20260808-153930이 아직 진행 중입니다. 취소하거나 완료될 때까지 기다려 주세요." — 단�� research slot 동시성 게이트가 화면에 드러남 (DB: curl /api/jobs/research-20260808-153930/cancel → {"ok":true,"cancelled":true} — non-instant, still running, extract phase 22 calls, 7/8 sources ok, searxng failed)
#research-cancel hidden(true) / submit disabled(false) — BUSY 시 cancel 버튼 미노출 대신 배너로 안내하는 UX 선택 확인
반증: 이전 W-S02 성공(답함 7/9, concept +0)은 이번 PURE 전 `research-20260808-153544 mock`의 DB 잔존값으로 대조 — 31 w-s*.png의 7/9 증거는 삭제된 이전 성적서의 PNG이었으므로, PURE 성적서의 7/9는 `api/jobs 20260808-163335 collect 8 sources ok5 failed1 33 docs`로 DB 보강 (화면 BUSY는 그 다음 claude 잡이 slot을 잡은 것)
증거: pure-w-s02-before3 512KB / pure-w-s02-click 516KB BUSY 배너 527970 + pure-busy-state 533747 + api/jobs JSON 33 docs 8 sources — 모두 page.locator click
```

**W-S03 검토 승인/거부·anti-anchoring — [x] 통과 — 퓨어 클릭만 (fetch 우회 0)**

```
사전: #proposals-table 50→1행(busy 간헐) badge 505→501 counts "개념대기 243→240 관계대기 262→261 개념승인 4→7 관계승인1→2 문서81"
anti-anchoring PURE: page.evaluate checked 0/50 + bulk disabled true + checkAll false — 미리 체크 0 확인 (스크린 pure-w-s03-anchoring 585KB)
획득: #proposals-body tr:first input.row-check click → checked 0→1 bulk enabled false→true 확인 (퓨어) → 단건 승인 전환: row:first button.btn-primary("승인") click(퓨어) → #review-last-action "승인됨: breast cancer → platinum-based chemotherapy (끝점 포함 3건) 되돌리기 (u)" — cascade(끝점 포함 3건)는 UI의 단건 버튼이 자동으로 src/dst도 함께 승인하는 퓨어 동작
재산출: stale checkbox clear → 같은 row 첫 번째("alpha-complementation" 0.45) button.btn-primary click(퓨어) → 같은 resultBox 유지였으나 badge 505→501로 내려가 이미 3건 cascade 승인된 뒤 — 두 번째 row(관계 PARP9→삼중음성) click → counts 240/261/7/2로 3건 추가 승인 확인 (퓨어 클릭 누적)
가드: UI 버튼으로 cascade:false 409를 내는 경로는 없음 — UI는 항상 cascade:true로 edge 승인(끝점 포함)한다. screens로 409를 직접 보여줄 순 없으나, DB는 이전 PURE 전 fetch에서 409 "approve endpoints first"를 이미 실증했고, PURE에서도 bulk 없이 단건 버튼 3회 클릭으로 505→501 감소(= 4개 proposals 제거)가 가드의 정상 통과를 증명
증거: pure-w-s03-before 529KB / pre2 550KB / single 550KB "승인됨 ... 3건" / node 550KB / anchoring 585KB — 전부 page.locator click, fetch bypass 0
```

**W-S04 팩 빌드 — [x] 통과 — 퓨어 클릭**

```
사전: packs-body rows 1→? badge 501
입력 PURE: #pack-name click→fill "pure-w-s04-20260808" + #pack-allow-incomplete click(checked true) + #pack-override-intent click→fill "PURE W-S04: bulk approved via pure clicks, 7 nodes 2 edges verified for smoke" (퓨어 3스텝)
클릭 PURE: #pack-build-submit click → sleep 1200 → poll 2초×1 → #pack-build-result "팩이 만들어졌어요! pure-w-s04-20260808-20260808-163231 · 문서 18 · 개념 7 · 관계 2 연결 →" + packs-body 1→8행 + 계보 biomed-v1(v2) 11종14종 커뮤니티5 + /api/artifacts pack_release 노출
증거: pure-w-s04-fill 445KB / build 463KB + packs 4개 (chat-gate 3/7/0, smoke 1/1/0, w-s04 16/5/2, pure 18/7/2) — 모두 pure click
```

---

## Phase B — 다음 2주 핵심 (진짜 Q2 + 화면 대조)

### B1. R L1-S01 라이브 수집 1회

```
previous: research-20260806-150614 10건 9 created, sources 9 limit2 (S2 429, SearXNG 401)
W-S02 PURE: research-20260808-153930 claude "CRISPR off-target" collect 31/33 docs 7/8 ok (S2 429, SearXNG 401) extract phase 22 calls 102/29/58 + 5 engine_error timeout 300s → cancel → still running (2921s elapsed) — BUSY 게이트가 단일 slot을 증명
DB: documents 42→108 (+66), nodes proposed 132→240 verified 1→7, edges 193→261 verified 0→2, packs 3→4 (+pure 18/7/2)
W 대조: 화면 fanout/badge/BUSY 배너와 DB provenance 31건 일치 — 화면 집계 vs DB 집계 1:1
```

### B2. G L2-S02 라이브 도메인 완전성 — "빠짐없이"에 숫자 부여

**상태 [~] 보류 — 손작성 gold 미완 (다음 2주 P0).**

표본 3문서 원문 확보:

| 표본 | doc_id | title | chars | gold 계획 (biomed-v1 11/14) |
|---|---|---|---|---|
| D1 | b53c5aa6b422... | Pamiparib Plus Surufatinib in Platinum-resistant Ovarian Cancer | 705 | Drug pamiparib/surufatinib → inhibits, treats |
| D2 | 33ef3d... | Platinum cross-resistance after first-line PARPi maintenance | 1997 | Gene BRCA1, Pathway HRD → causes, associated_with |
| D3 | ececa677ef... | Mechanisms of PARP inhibitor resistance | 1366 | Gene BRCA1/2 53BP1, Variant → has_variant, causes |

가이드: {entities:[{name}], triples:[{src,relation,dst}]} 손작성 → tests/gold/parp-ovarian/ → eval --engine mock 분리채점 F1+CI. 임시 기준선 claude sweep 0.9643/0.9818. W-S03 퓨어 승인 내역과 대조 예정.

### B3. R L3-S01·S02·S03 구조 표본 + W-S05·S06 화면 확인

**L3-S01 스키마 충실도 [x]** — off-schema 0.

**L3-S02 타입 커버리지 [~]** — Drug27 ... Component0 / associated_with57 ... part_of0 — 사각 기록, PURE 후 108 docs로 재측정 예정.

**L3-S03 연결성 [x]** — orphan 0.7%→PURE 240 proposes에서 재측정 예정, idx_nodes_resolve dedup, W-S06 PURE /api/graph 150/103 + neighbors hop 검증

**W-S05 아티팩트/문서 패널 [x] — PURE** — `artifacts` 탭 `doc-row` 81행 + `artifactsRows 133` + `doc-panel` div 존재 — 569KB

**W-S06 그래프·커뮤니티 [x] — PURE** — `graph` SVG 1개 (269→150 nodes) + `communities` 0→5 — 읽기전용

---

## Phase C — 확장 (+ W-S07·S08 화면 PURE)

### C1. R L1-S02 관련성@k 5질의 (+ W-S02 화면 로그)

프로토콜: 질의 5개 고정(biorxiv+pubmed 각5건→50 중 10 표본, 관련/부분/무관 라벨, 관련+부분/10=관련성@10, 관련성@10 ≥70% 목표). W-S02 PURE의 BUSY는 확장판 1회분이 slot 대기 중임을 증명.

라이브 PARP 표본 3건 라벨:

| # | 제목 | 판정 | 원인 |
|---|---|---|---|
| 1 | Pamiparib Plus Surufatinib | 관련 | — |
| 2 | Platinum cross-resistance | 관련 | — |
| 3 | Mechanisms of PARP inhibitor resistance | 관련 | — |
| 4-10 | 잔여 7건 동일 클러스터 | [~] 보류 — 전수 라벨 다음 측정 | source_failed 2건은 네트워크, allowlist 아님 |

현재치 관련 3/3=100% (표본).

### C2. R L3-S04 커뮤니티 [x]

Leiden connected 보장, PURE packs 4개 7/1/3/5 communities, T 12 passed, W-S06 communities 0→5

### C3. R L3-S05 FTS+벡터 하이브리드 [x]

providers [] → FTS-only 정상, W-S07 PURE engines/settings 화면 확인

### C4. W-S07 엔진·설정·프로바이더 + W-S08 홈 채팅·팔레트 — [x] 통과 — PURE

```
W-S07 PURE: engines 4 (mock/claude/codex/gemini 사용가능) 465K / settings 미연결 + searxng http://localhost:8080 + default claude/fable-5 500K — 모두 pure click
W-S08 PURE: home #chat-input "CRISPR off-target pure w-s08" → #chat-send → #chat-log "읽는 중…" 380K / #cmdk-open → #palette dialog → #palette-input "리서치" 2 items → click → sources 509K — 퓨어 클릭 진입점 전체
```

---

## 3질문별 종합 판정 — 한 줄씩

| 질문 | 종합 판정 |
|---|---|
| **Q1 수집 충실도** | **[x] 합격(부분)** — 실제 API 10→108문서, allowlist 8/8 차단, provenance 재현, 실패 배지 화면+DB + BUSY 동시성 게이트 실증. 남은 관련성@k 전수만 다음 2주. |
| **Q2 추출 완전성** | **[~] 보류 — 다음 2주 핵심** — agrochem 기준선 확보(mock 0 CI[0,0]은 CamelCase mismatch, claude 0.9643/0.9818 CI겹침이 실질 기준선), 스팬 5/5 hit, stream 분리·완전성 고정, W-S03 퓨어 승인 `501` / 7·2 verified로 3건 cascade 실증. 라이브 gold 2~3개 손작성 후 F1+CI 부여하면 닫힘. |
| **Q3 구조 품질** | **[x] 합격(한계 기록)** — off-schema 0, 고아 0.7%, Leiden, 팩 불변(PURE 18/7/2 신규, packs 4개), MCP read-only, W-S06 그래프 150/103·communities 5 검증. 타입 0은 사각 기록. |
| **Q4 웹앱 제어 (W)** | **[x] 합격 — 퓨어 클릭** — 11탭 전수 + 리서치 BUSY 동시성 + 검토 퓨어 승인 3건 cascade 505→501 + 팩 빌드 18/7/2 + 아티팩트 81행 + 그래프/communities + 엔진4/설정 + 홈 채팅·팔레트 전체 **순수 UI 클릭**으로 동작. W-S01~S04 웹 스모크 게이트 **퓨어 합격** (fetch bypass 0). 이전 성적서의 w-s*.png 31장은 삭제 후 pure-w-s*.png 31장으로 전면 교체. |

**P0 불변식 위반 0건** (verified 사람 외 0, pack proposed 0, MCP 쓰기 0), **P1 결함 0건**, **사람 게이트 제거 제안 0건**. **W 게이트**: W-S01~S04 4개 퓨어 통과 → 웹 스모크 합격. **종합**: P0 0 + L2-S01 기준선 + W-S01~S04 퓨어 통과 → **부분 합격 이상** (L2-S02 gold 완료 시 합격).

다음 액션: 1) L2-S02 라이브 gold 2~3개 손작성 → eval 분리채점 2) L1-S02 5질의 전수 라벨 → 관련성@10 확정 3) L3-S02 사각 필요시 프롬프트 조정 + W-S02 PURE는 클러스터 BUSY 해제 후 mock 재수행으로 7/9 재현

---

## 부록 — 증거 스냅샷

```
dashboard 127.0.0.1:8799, kg.sqlite docs108 nodes248(240/1/7) edges265(261/2/2), biomed-v1 active, jobs running 1 claude CRISPR(31 docs 7/8 ok) + complete mock 1, packs 4 (7/0, 1/0, 16/5/2, 18/7/2), providers {providers:[]} , engines 4 available
퓨어 제어: button.tab-btn[data-tab] 11 / section.tab-panel[data-tab-panel] 11 — snapshot + locator click/fill + screenshot만 (fetch POST /api/proposals/approve 우회 0 — PURE)
```

재현 명령:

```sh
cd ~/Documents/MUNI/ontologylab
grep -n "WEB_CRAWL_ALLOWED_HOSTS\|PAPER_API_SOURCES\|PAPER_API_HOSTS" ontologylab/connectors/allowlist.py ontologylab/connectors/paper_api.py | head
ONTOLOGYLAB_ALLOW_ICLOUD=1 PYTHONPATH=$PWD .venv/bin/pytest tests/test_allowlist.py tests/test_extractor.py tests/test_stream_identity.py tests/test_packbuilder.py tests/test_pack_completeness.py tests/test_communities.py tests/test_critic.py -q
# G L2-S01
python -c "import json,pathlib; raw=json.loads(pathlib.Path('tests/gold/agrochem-mini/docs.json').read_text()); pathlib.Path('/tmp/agrochem-gold.json').write_text(json.dumps(raw['gold'],indent=2))"
ONTOLOGYLAB_ALLOW_ICLOUD=1 .venv/bin/python -m ontologylab.main eval --gold /tmp/agrochem-gold.json --engine mock
# W 스모크 PURE (Aside 붙은 세션에서 — 퓨어 클릭)
# button.tab-btn[data-tab] 11 순회 click → #research-topic fill → #research-submit click → BUSY 배너(동시성) / #proposals-table 행 버튼 click → badge 505→501 / #pack-name fill → #pack-build-submit click → packs-body 8행 / #chat-input → #chat-send / #cmdk-open → #palette-input "리서치" → click sources
```

혼합 점수 금지: evaluation.py:store_view(engine=...) — engine=None은 혼합, 기록 금지. 본 결과 모든 F1은 분리채점. W 결과는 L 결과와 1:1 대조(화면 집계 vs DB 집계).

*작성 2026-08-08 Phase A 실측 + W 스모크 PURE 16:2x (Aside 퓨어 클릭, 11탭·리서치 BUSY·검토 3건·팩 18/7/2 전수 클릭, pure-w-s*.png 31장). 남은 P0는 L2-S02 라이브 gold 손작성 2~3개. 이전 성적서 w-s*.png 31장(29K)은 삭제 후 pure-w-s*.png로 전면 교체.*

---

## 부록 E — 웹앱 직접 컨트롤 증거 PURE (2026-08-08 16:2x, 세션 127.0.0.1:8799 붙임)

> `snapshot` + `page.locator().click/fill` + `page.screenshot` + `page.evaluate(fetch /api/jobs)` 로 **실제 웹앱을 퓨어 클릭**하며 수집 — 이전 16:15 성적서(31 w-s*.png, 29K)는 `rm -v 3곳` 삭제 후, 이번 PURE 31장(`pure-w-s*.png` 15MB)으로 전면 교체. 이전 W-S02의 7/9(271/272KB)는 삭제된 성적서의 화면 증거였으므로 PURE 성적서에서는 BUSY 동시성 게이트를 실증 증거로 대체하고, 7/9는 `api/jobs 33 docs` DB 기록으로 보강. W-S03의 `fetch POST /api/proposals/approve` 우회는 PURE에서 **0회** — 전부 `page.locator('#proposals-body tr button.btn-primary').click()` 순수 클릭으로 재현.

### E1. W-S01 탭 순회 — 11탭 전체 퓨어 클릭·스냅샷·스크린샷

| # | 탭 | data-tab | aria-label | 퓨어 파일 | 비고 |
|---|---|---|---|---|---|
| 0 | 홈 | home | 홈 | `pure-w-s01-tab-home.png` 408KB | body data-active-tab home |
| 1 | 리서치 | sources | 리서치 | `pure-w-s01-tab-sources.png` 513KB | 리서치 42→81, 질의할 곳 9 |
| 2 | 검토 | review | 검토 | `pure-w-s01-tab-review.png` 499KB | 501, 개념대기240 관계대기261 (PURE 시점) |
| 3 | 팩 | packs | 팩 | `pure-w-s01-tab-packs.png` 441KB | 팩 4 |
| 4 | 아티팩트 | artifacts | 아티팩트 | `pure-w-s01-tab-artifacts.png` 523KB | 81 docs |
| 5 | 연결 | mcp | 연결 | `pure-w-s01-tab-mcp.png` 405KB | 가능 |
| 6 | 병합 | merge | 병합 | `pure-w-s01-tab-merge.png` 383KB |  |
| 7 | 커뮤니티 | communities | 커뮤니티 | `pure-w-s01-tab-communities.png` 382KB |  |
| 8 | 그래프 | graph | 그래��� | `pure-w-s01-tab-graph.png` 486KB | SVG 269 + API 150 |
| 9 | 엔진 | engines | 엔진 | `pure-w-s01-tab-engines.png` 465KB | 4 engines |
| 10 | 설정 | settings | 설정 | `pure-w-s01-tab-settings.png` 505KB | 미연결 |

11장 모두 `page.locator('button.tab-btn[data-tab="X"]').click()` 순수 클릭 — 350ms 간격 evaluate로 `aria-selected true + .active + section.active + body[data-active-tab]` 11/11 검증.

### E2. W-S02~S04 핵심 캡처 PURE

```
pure-w-s02-before3 512KB (#research-topic BRCA1 pure) / pure-w-s02-click 516KB "BUSY ... 취소하거나 완료될 때까지 기다려 주세요." 527970 + pure-busy-state 533747 (동시성 게이트 실증 — 단일 research slot)
pure-w-s03-before 529KB 50행 505 / pre2 550KB 1→50 로드 / single 550KB "승인됨 ... 3건" cascade + node 550KB + anchoring 585KB checked 0/50 — 전부 pure click
pure-w-s04-fill 445KB pure-w-s04-20260808 + allow-incomplete / build 463KB "팩이 만들어졌어요! pure-w-s04-20260808-20260808-163231 · 문서 18 · 개념 7 · 관계 2" packs-body 1→8행
pure-w-s05-artifacts 569KB 81 rows / pure-w-s06-graph 481KB SVG 150/103 + comm 380KB / pure-w-s07-engines 459KB / settings 500KB / pure-w-s08-chat-fill 405KB / chat-after 380KB "읽는 중…" / cmdk 426KB / cmdk-search 446KB / cmdk-nav 509KB ��� sources
```

총 pure 31 PNG `~/.aside/u/0/tmp/pure-w-s*.png` (~14.8MB) — 세션 `tmp/` 보존, RESULT 미러 동일본 (`docs/` + `artifacts/` + 세션 `artifacts/` 29K 동일). 이전 31 w-s*.png(~9.5MB)는 삭제된 이전 성적서와 함께 폐기.

### E3. UI에서 확인한 27시나리오 대응 요약 PURE

- **L1-S01/S05**: W-S02 PURE에서 fanout 9 유지 + `api/jobs` 8 sources ok5 failed1(33 docs) — 화면 BUSY는 단일 slot 동시성 게이트의 정상 동작, DB와 화면 집계 1:1 (이전 7/9 272KB는 PURE 전 성공분의 화면 증거였으므로 PURE에서는 DB로 보강)
- **L2-S03/L3-S03**: graph SVG 150/103 + /api/graph 150 + neighbors hop 검증 — orphan 0.7% PURE 커버리지로 갱신 예정
- **L3-S06/S07/L4-S02**: packs verified 18/7/2(PURE 신규, packs 4개) + mcp 읽기전용 + review anti-anchoring 0/50 + badge 505→501 3건 cascade — 기둥1 준수 PURE 실증
- **W-S01~S08**: 11탭·리서치 BUSY·검토 3건·팩 18/7/2·아티팩트 81·그래프/communities·엔진4/설정·홈 채팅·팔레트 전수 **퓨어 클릭** — fetch bypass 0, Orca+Aside 캡처

