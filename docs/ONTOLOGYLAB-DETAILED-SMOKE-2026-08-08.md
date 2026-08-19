---
schema_version: 1
doc_id: detailed-smoke-2026-08-08
project: ontologylab
type: smoke-scenario
status: draft
created_at: 2026-08-08
baseline: ontologylab@8799 (W1-W14+Graph/SSE, pytest 1702, biomed-v1 11/14)
source_workbook: docs/CONANSSAM-CROSSCHECK-2026-08-08.md
source_result: docs/CROSSCHECK-RESULT-2026-08-08.md
live_store: ~/Library/Application Support/ontologylab/data/kg.sqlite (docs 42 · proposed 132 · verified 1)
web_control: Aside 브라우저 + Orca computer-use (11탭 tab-btn[data-tab] 직접 제어, SSE /api/jobs/stream 관측)
constraints:
  - DESIGN-RATIONALE 기둥1: AI 제안 · 사람 결정 · verified만 출고 (critic≠approve)
  - ARCHITECTURE canonical: MCP read-only · pack verified-only · allowlist deny-by-default
  - 로컬 단일사용자 전제
---

# OntologyLab 상세 시운전 시나리오 — 파이프라인 품질 검증 (2026-08-08)

기본 시운전(`ONTOLOGYLAB-SMOKE-TEST-KO.md`, `ONTOLOGYLAB-SMOKE-TEST-REVIEW-GAP-2026-08-06.md`)이 "화면이 동작하는가"를 봤다면,
이 상세 시운전은 **수집→추출→구축 파이프라인이 제대로 구축되었는가**를 세 질문으로 검증한다.

> **Q1. 실제 API/웹검색이 사용자 의도에 맞는 자료를 잘 수집했는가?** → L1 수집 충실도  
> **Q2. 그 자료로부터 빠짐없이 온톨로지를 추출·구축했는가?** → L2 추출 완전성  
> **Q3. 결과가 단순 구현이 아닌 온톨로지·시멘틱 네트워크·택소노미로서 제대로 구축되었는가?** → L3 구조 품질

검증 층위 기호: `C` 코드 정적 확인 · `R` 라이브 런타임 · `T` 기존 테스트 고정 · `G` gold 기반 채점(`evaluation.py`) · `W` 웹앱 제어(Aside 브라우저, Orca computer-use).

---

## 0. 공통 전제·환경

| 항목 | 값 |
|---|---|
| 실행 위치 | `~/Documents/MUNI/ontologylab` |
| 라이브 데이터 | `~/Library/Application Support/ontologylab/data` (`kg.sqlite` · `documents/` · `jobs/` · `providers.json`) |
| 대시보드 | `127.0.0.1:8799` (`at.ontologylab.server`, `server/jobs.py:_load_persisted` running→failed) |
| 웹앱 제어 | Aside 브라우저 + Orca computer-use — `list apps/windows` → `get app state` → `read visible UI` → `click`/`type`/`press keys`/`scroll` 로 11탭(`tab-btn[data-tab]`)을 직접 제어, SSE 스트림 관측 |
| 활성 스키마 | `biomed-v1` (entity 11 · relation 14 · 라이브 실측) — agrochem-mini는 gold 전용 |
| 엔진 | `mock`(결정론) / `claude`/`codex`/`gemini` (실측) — `engines.py:get_engine` |
| 팩 | `~/Library/Application Support/ontologylab/packs` (verified-only, `file:...?mode=ro&immutable=1`) |
| 평가 하네스 | `ontologylab/evaluation.py` — 정규화 트리플 `(src_norm, relation, dst_norm)` + `normalize_name` + P/R/F1 + bootstrap 95% CI |

gold 파일은 사람이 손으로 쓰는 JSON(`{entities:[{name}], triples:[{src,relation,dst}]}`)이며, 한 저장소에 여러 엔진 출력이 섞이면 점수가 흐려지므로 `evaluation.py:store_view`의 stream 필터(`engine/model/prompt_version/decode_params`)로 분리 채점한다.

---

## L1 — 수집 충실도 (Collection Fidelity): Q1에 답한다

### L1-S01 실제 API 수집이 동작하는가 (R)

| 항목 | 내용 |
|---|---|
| 목적 | paper_api 9+ 소스(arxiv/crossref/openalex/s2/europepmc + biorxiv/pubmed + elsevier/springer/core + clinicaltrials + searxng)가 실측으로 문서를 가져오는지 |
| 사전조건 | keyless 5개는 무키, keyed 3개는 미연결이면 미노출이 정상. `providers.json: {providers:[]}` |
| 절차 | 1) 대시보드 Sources에서 biorxiv/pubmed로 임의 질의 1회 collect → `documents/` 증가 확인. 2) CLI: `python -m ontologylab collect --source biorxiv --query "BRCA1 breast cancer" --limit 5`와 동등 경로. 3) `api/biorxiv`·`pubmed` 파서(`paper_api.py:parse_biorxiv/parse_pubmed`)가 title+abstract를 문서로 만드는지 `documents` 테이블에서 `source_kind` 확인. |
| 기대결과 | keyless 소스는 문서를 반환, keyed 미연결 소스는 UI에서 비활성/미노출. `content_hash`로 dedup. |
| 합격 | 문서 수 증가 + `source_kind`가 요청 소스와 일치. 실패 시 `NotAllowlisted` 또는 소스별 상태 배지와 집계가 노출(GAP-O4). |
| 증거 | `documents` count before/after, `jobs/<id>/status.json`의 source 집계, 스크린샷 1장 |
| 우선순위 | **지금** |

### L1-S02 수집된 자료가 사용자 의도에 맞는가 — 관련성 판정 (R + G)

| 항목 | 내용 |
|---|---|
| 목적 | 수집 결과가 질의 의도와 관련 있는지(관련/부분/무관) 구조화 판정. 자동 관련성 채점은 현재 없음 — 이 시나리오가 최초 계측. |
| 절차 | 1) 테스트 질의 5개를 고정(예: 병원체×작물 2개, 약제×작물 2개, 유전자×질환 1개). 2) 각 질의로 biorxiv+pubmed 각 5건 수집. 3) 수집된 문서 10건을 사람이 **관련(직접 답) / 부분(주변) / 무관** 3단계로 라벨. 4) 관련+부분 비율 = 관련성@k. |
| 합격 | 관련성@10 ≥ 70% 를 목표치로 기록(최초 측정치는 기준선). 무관은 원인 분류(allowlist/쿼리검증/소스미지원 중 무엇인지). |
| 증거 | 질의 목록 + 문서 제목/초록 1줄 + 판정 표(10행). 재현을 위해 질의·limit 고정. |
| 우선순위 | **지금+1** — L2 gold 작성 전 선행 |

### L1-S03 allowlist deny-by-default가 뚫리지 않는가 (C + R)

| 항목 | 내용 |
|---|---|
| 목적 | `allowlist.py`가 두 커넥터 모두에서 deny-by-default + `NotAllowlisted` + 리다이렉트 재검증하는지 |
| 절차 | C: `allowlist.py:WEB_CRAWL_ALLOWED_HOSTS`가 exact-host, `PAPER_API_SOURCES`가 고정 상수, `paper_api.py:PAPER_API_HOSTS`·`check_paper_host`가 매 hop 재검증하는지 코드 확인. R: 허용 외 host URL 크롤 시도 → `NotAllowlisted`. 빈 질의/제어문자/임베드 URL 질의 → 거부. |
| 합격 | 허용 외 host·소스·형식 불량 질의가 명확한 에러로 거부(침묵 통과 0). |
| 증거 | C: grep 결과 3줄. R: 거부 에러 로그 캡처. |
| 우선순위 | 지금 |

### L1-S04 provenance가 수집 입력을 재현 가능하게 남기는가 (R)

| 항목 | 내용 |
|---|---|
| 목적 | `jobs/<id>/provenance.jsonl` + `status.json:last_payload`가 질의·URL·파일 경로를 남겨 재현 가능한지, 입력은 `MAX_PAPER_QUERY_LEN`·`MAX_LOGGED_VALUES`로 클리핑되는지 |
| 절차 | collect 1회 후 `jobs/<id>/provenance.jsonl`에서 `collect.start` 페이로드 확인. 긴 질의로 클리핑 동작 확인. |
| 합격 | 입력이 잘림 표기와 함께 보존, 경로 컴포넌트가 아닌 stage 토큰으로 job dir 생성. |
| 증거 | provenance 1개 파일 캡처 |
| 우선순위 | 다음 |

### L1-S05 실패가 드러나는가 (R) — GAP-O4 회귀

소스 일부 실패 시 배지(✓/✕+종류) + "N개 중 M개 응답 · 실패 K" 집계, 전체 실패 시 배너 + 재시도 안내가 노출되는지 라이브 리서치 1회로 확인.

---

## L2 — 추출 완전성 (Extraction Completeness): Q2에 답한다

### L2-S01 gold 기반 추출 품질 — agrochem-mini 기준선 (G)

| 항목 | 내용 |
|---|---|
| 목적 | 추출 하네스가 gold에 대해 실제로 몇 점을 내는지 기준 F1 확보 |
| 절차 | 1) `tests/gold/agrochem-mini/docs.json`(구성 문서, CLAUDE.md 경고) 로드. 2) `python -m ontologylab eval --gold tests/gold/agrochem-mini/docs.json` 실행 — 기본은 proposed+verified, stream 필터로 `mock` 분리. 3) 출력: entity P/R/F1 + triple P/R/F1 + bootstrap 95% CI + missing/spurious 20개. |
| 합격 | 점수를 **기준선으로 기록**(최초 측정). 이후 변경은 **CI 겹침 여부**로 판정(겹치면 개선 아님 — `evaluation.py:bootstrap_f1_interval` 2000 resamples, seed 7). |
| 증거 | `ontologylab eval` 전체 출력 + `evaluation.py:store_view`의 `include_proposed` 의미 메모 |
| 우선순위 | **지금** — 파이프라인 품질의 첫 숫자 |

### L2-S02 라이브 도메인 추출 완전성 — 진짜 “빠짐없이” (G) ★ 핵심

| 항목 | 내용 |
|---|---|
| 목적 | 실제 수집 문서(라이브 도메인)에서 빠짐없이 추출했는지. agrochem-mini는 구성 데이터라 대표성 없음 — 이 시나리오가 Q2의 정답. |
| 절차 | 1) 라이브 문서 중 2~3개를 표본으로, 사람이 **정답 트리플을 손으로 작성**(gold). 스키마는 `biomed-v1` 11/14에 맞춘다. 2) 같은 문서를 `mock`(또는 `claude`)으로 extract → `ontologylab eval --gold <손작성 gold> --engine mock` 분리 채점. 3) triple F1 + CI + missing/spurious로 누락 원인 분류(span/alias/스키마 중 무엇인지). |
| 합격 | 최초 측정치를 기준선으로 기록. 이후 스위프는 CI 미겹침으로만 “개선” 인정. |
| 증거 | 손작성 gold JSON 1개 + eval 출력. gold는 `tests/gold/`에 보존. |
| 우선순위 | **다음 2주** — L2-S01 이후. 이게 없으면 Q2는 답 없음. |

### L2-S03 스팬·인용 무결성 — 추출이 원문을 가리키는가 (T + R)

모든 저장 노드/엣지의 `source_span`을 `chunk char_offset`에서 문서 좌표로 **rebase**한 뒤, `raw_text[start:end]`가 실제 표면 형태를 포함하는지. 코드상 `extractor.py:chunk_document(3000,150)` + `parse_and_validate_extraction`의 repair-then-reject(못 찾으면 재배치, 없으면 drop). 라이브에서 무작위 5건 표본으로 `raw_text` 대조.

### L2-S04 스트림 분리 채점 — 엔진이 섞이지 않는가 (T)

한 저장소에 mock+claude 출력이 섞이면 한쪽의 적중이 다른 쪽의 탈락을 가린다. `evaluation.py`의 `engine/model/prompt_version/decode_params` 필터로 **분리 채점**하는지, `tests/test_stream_identity.py` 유사 경로로 확인.

### L2-S05 추출 완전성 정책 — 팩 빌드가 스트림을 빠짐없이 반영하는가 (T)

`pack_completeness.py`가 cited stream을 집계해 누락 스트림을 탐지하는지. `tests/test_pack_completeness.py` 통과.

---

## L3 — 구조 품질 (Structure Quality): Q3에 답한다 — 단순 구현이 아닌 파이프라인

### L3-S01 온톨로지 스키마 충실도 (R + C)

추출 결과가 활성 스키마(`biomed-v1` 11/14)에 없는 entity/relation을 만들지 않는지. `kgstore.insert_proposed`의 스키마 검증 + `ontology_schema.py` 프리셋. 라이브에서 off-schema 0건.

### L3-S02 택소노미·타입 커버리지 (R)

11 entity / 14 relation이 실제로 쓰이는지(분포 0인 타입 = 사각). 라이브 `nodes GROUP BY entity_type`, `edges GROUP BY relation_type`으로 분포 표. 특정 타입만 0이면 프리셋/프롬프트 원인 분류.

### L3-S03 시멘틱 네트워크 연결성 (R + C)

엔티티 해상도(`kgstore.py:normalize_name` → `remove_non_alphanumerics(casefold)`)가 청크·문서 간 멘션을 같은 노드로 합쳐 그래프를 연결하는지.

- 코드: `idx_nodes_resolve` on `(schema_version_id, entity_type, normalized_name)`, `insert_proposed` dedup.
- 라이브: 고아 노드 비율(`degree 0` 노드 / 전체), 연결 성분 수, `traverse_relations`·`find_path`가 문서 간 경로를 찾는지 2건 시연.
- 합격: 고아 ≤ 10% 를 목표(최초 측정 후 조정), 문서 간 2-hop 경로 1건 이상 존재.

### L3-S04 커뮤니티·군집 구조 (R)

`communities.py` Leiden(연결 보장) vs label-propagation fallback. 라이브 팩에서 `get_communities`가 주제 군집을 반환하는지, 군집 내부 노드가 실제로 같은 문서군에서 왔는지 1건 표본.

### L3-S05 FTS+벡터 하이브리드 가중치 (C + R)

`searchquery.py` expand, `embeddings.py`, `rerankers.py`. `providers.json:[]`면 FTS-only가 정상. FTS-only와 embedding tier의 RRF 가중치가 문서화됐는지, `--expand` fail-open이 로그에 남는지 코드 확인. 라이브 5질의 재현율.

### L3-S06 팩 구조·불변성 (R + T)

- 코드: `packbuilder.py` verified-only (`WHERE status='verified'` + 양끝점 JOIN), FTS rebuild, WAL off, `PRAGMA optimize; VACUUM`.
- 라이브: 팩 빌드 1회 → `pack.sqlite`에 proposed/rejected 0건, `content_hash` 불변, `file:...?mode=ro&immutable=1`로 열림, `packs/<id>/` 디렉터리가 유일 진실(테이블 없음).

### L3-S07 MCP read-only 서피스 (R + C)

`mcp_server.py` 10툴(read-only) + `load_pack`만 세션 포인터 변경. `critic.py`는 점수만 — `approve` 경로 0건. 라이브 MCP 1회 호출로 쓰기 툴 존재 여부·pack 불변 확인.

---

## L4 — 운영·불변식 회귀 (기존 시운전 회귀)

| ID | 시나리오 | 검증 |
|---|---|---|
| L4-S01 | 영속·재시작 | `server/jobs.py:_load_persisted` running→failed relabel, Stop→재클릭 사용자 체크리스트 |
| L4-S02 | 사람 게이트 | critic 정렬 전용 가드(W8 anti-anchoring), 점수→승인 미리체크 경로 없음 |
| L4-S03 | Safety | `safety.py` Caps/KillSwitch, provenance, allowlist — 자동 차단이 `approve()` 대체 0건 |
| L4-S04 | 청킹 | `extractor.py:TARGET_CHUNK_TOKENS=3000`, `OVERLAP_TOKENS=150` (`CHUNK-SWEEP-2026-08.md` 채택) |

---

## W — 웹앱 제어 검증 (Aside 브라우저, Orca computer-use)

L1-L4가 DB/API로 파이프라인 품질을 검증한다면, W는 **사람이 실제로 보는 11개 탭 화면을 Aside 브라우저에서 직접 제어**하며 검증한다. 실행 도구는 `computer-use` 스킬(Orca CLI)이며, 별도 Playwright/Selenium 스택을 도입하지 않는다. 모든 시나리오는 `W`로 표기하고, 명세의 셀렉터·기대 UI 상태를 그대로 따른다.

공통 진입점: `web/index.html` 11탭 — `home(채팅) / sources(리서치) / review(검토) / packs(팩) / artifacts(아티팩트) / mcp(연결) / merge(병합) / communities(커뮤니티) / graph(그래프) / engines(엔진) / settings(설정)` — 진입은 `button.tab-btn[data-tab]` 클릭 → `section.tab-panel[data-tab-panel]` 활성 → `fetch(/api/…)` + `SSE /api/jobs/stream` 관측.

### W-S01 탭 네비게이션 — 11탭이 모두 도달 가능한가 (W)

| 항목 | 내용 |
|---|---|
| 목적 | 11탭이 Orca 접근성 트리에서 이름 있게 보이고, 클릭 시 해당 패널이 활성화되는지 |
| 절차 | Orca: `list apps/windows` → Aside 창 선택 → `get app state`/`read visible UI`로 `tab-btn[data-tab=home|sources|review|packs|artifacts|mcp|merge|communities|graph|engines|settings]` 11개 존재 확인. 각 탭을 `click` → `section.tab-panel.active`가 해당 `data-tab-panel`로 바뀌는지, `aria-selected="true"` 토글 확인. |
| 합격 | 11탭 모두 접근성 이름(`aria-label`: 홈/리서치/검토/팩/아티팩트/연결/병합/커뮤니티/그래프/엔진/설정) 노출 + 클릭 시 패널 전환. 누락 시 `test_agent_drivable_ui.py` 회귀. |
| 증거 | Orca `read visible UI` 캡처 + 탭 순회 스크린샷 1장 |
| 우선순위 | **지금** |

### W-S02 리서치 — 소스 선택부터 collect 실행·SSE 관측까지 (W + R)

| 항목 | 내용 |
|---|---|
| 목적 | `sources(리서치)` 탭에서 실제 API 수집을 화면 흐름으로 끝까지 가는지 |
| 절차 | 1) `click [data-tab=sources]` → 2) `fanoutSources` 체크박스(`biorxiv`/`pubmed` 등) `click` → 3) `#research-topic`에 `type "BRCA1 breast cancer"` → 4) `#research-submit` `click` → 5) Orca `read visible UI`로 진행 배지·집계 텍스트 관측 + 브라우저 네트워크/SSE `/api/jobs/stream` 이벤트 확인 → 6) 완료 후 `jobs-table` 행 증가 확인. |
| 합격 | 선택한 소스가 `available`일 때 문서가 수집되고, 실패 시 소스별 배지(✓/✕)와 집계가 화면에 노출(GAP-O4). 선택자는 `#research-topic`, `#research-submit`, `#jobs-table` 고정. |
| 증거 | 입력→실행→SSE 관측 스크린샷 2장 + `jobs/<id>/status.json` 대조 |
| 우선순위 | **지금** |

### W-S03 검토 — 제안 확인부터 승인/거부까지 (W + R)

| 항목 | 내용 |
|---|---|
| 목적 | `review` 탭에서 제안 큐를 보고 사람 게이트(승인/거부)가 화면에서 동작하는지 |
| 절차 | 1) `click [data-tab=review]` → 2) `#proposals-table` 행 존재 확인 → 3) 행 `click` → 상세 패널(스팬 하이라이트, `critic` 점수) 확인 → 4) `#approveBtn` 또는 `#rejectBtn` `click` → 5) 행 상태 `verified`/`rejected` 전환 + `review-badge` 카운트 감소 확인. `critic` 점수가 버튼을 미리 체크하지 않는지(anti-anchoring) 확인. |
| 합격 | 승인/거부 후 상태 전이 + 배지 갱신. 점수→자동 승인 경로 없음(기둥1). |
| 증거 | 승인 전/후 테이블 캡처 + `kg.sqlite nodes status` 대조 |
| 우선순위 | 지금 |

### W-S04 팩 — 빌드 트리거부터 아티팩트 반영까지 (W + R)

| 항목 | 내용 |
|---|---|
| 목적 | `packs` 탭에서 verified-only 팩 빌드가 화면에서 완주하는지 |
| 절차 | 1) `click [data-tab=packs]` → 2) 팩 빌드 버튼 `click` → 3) SSE `pack` 잡 진행 관측 → 4) 완료 후 `packs/<id>/pack.sqlite`가 화면 목록에 노출 + `content_hash` 표시 확인 → 5) `click [data-tab=artifacts]`에서 동일 팩 카드 확인. |
| 합격 | 빌드된 팩이 목록에 나타나고, `artifacts` 탭과 일치. 팩은 `mode=ro&immutable=1`로 열림. |
| 증거 | 빌드 전/후 packs 목록 캡처 + `pack.sqlite` hash |
| 우선순위 | 지금 |

### W-S05 아티팩트/문서 패널 (W)

| 항목 | 내용 |
|---|---|
| 목적 | `artifacts` 탭의 문서/팩 열람이 동작하는지 |
| 절차 | `click [data-tab=artifacts]` → 문서 카드 `click` → 문서 패널(원문·스팬 하이라이트) 열림 확인 → `table-scroll` 내 스크롤 동작 확인. |
| 합격 | 문서 패널이 열리고, 스팬이 원문에서 하이라이트. |
| 증거 | 문서 패널 캡처 1장 |
| 우선순위 | 다음 |

### W-S06 그래프·커뮤니티 자유 탐색 (W)

| 항목 | 내용 |
|---|---|
| 목적 | `graph`/`communities` 탭이 읽기 전용 탐색 뷰로 동작하는지 |
| 절차 | 1) `click [data-tab=graph]` → SVG 그래프 렌더 확인 → 노드 `click` → 이웃 확장(`GET /api/graph/neighbors/{id}`) 확인. 2) `click [data-tab=communities]` → 커뮤니티 목록 `click` → 멤버 노드 확인. |
| 합격 | 그래프가 렌더되고, 클릭으로 이웃이 확장됨. 쓰기 동작 없음(MCP read-only와 동일). |
| 증거 | 그래프 탐색 캡처 1장 |
| 우선순위 | 다음 |

### W-S07 엔진·설정·프로바이더 (W)

| 항목 | 내용 |
|---|---|
| 목적 | `engines`/`settings` 탭에서 엔진 목록과 설정이 화면에 반영되는지 |
| 절차 | 1) `click [data-tab=engines]` → 엔진 목록(`mock`/`claude`/`codex`/`gemini` + `api:<id>`) 표시 확인. 2) `click [data-tab=settings]` → 기본값·프로바이더 키 상태(`key: set|MISSING`) 표시 확인. 3) 설정 변경 입력 → `PUT /api/settings` 후 화면 갱신 확인. |
| 합격 | 엔진 목록과 설정이 화면에 노출되고, 변경이 저장 후 반영됨. |
| 증거 | engines/settings 캡처 |
| 우선순위 | 다음 |

### W-S08 홈 채팅 + 커맨드 팔레트 (W)

| 항목 | 내용 |
|---|---|
| 목적 | `home` 채팅과 `⌘K` 팔레트가 화면 진입점으로 동작하는지 |
| 절차 | 1) `click [data-tab=home]` → `#chat-input`에 `type "CRISPR off-target 찾아줘"` → `#chat-send` `click` → 채팅 로그에 리서치 진행/결과 카드 관측. 2) `#cmdk-open` `click` 또는 `press keys ["cmd+k"]` → 팔레트 열림 → 입력 `type "리서치"` → 결과 `click`으로 탭 이동 확인. |
| 합격 | 채팅 입력→로그 반영, 팔레트 열림→검색→이동이 모두 화면에서 동작. |
| 증거 | 채팅/팔레트 캡처 1장 |
| 우선순위 | 다음 |

---

## 검증 매트릭스 (요구사항 추적)

| ID | 질문 | 요구사항 | 방법 | 우선순위 | 상태 |
|---|---|---|---|---|---|
| L1-S01 | Q1 | 실제 API 수집 동작 | R | 지금 | ☐ |
| L1-S02 | Q1 | 수집 관련성@k | R+G | 지금+1 | ☐ |
| L1-S03 | Q1 | deny-by-default | C+R | 지금 | ☐ |
| L1-S04 | Q1 | provenance 재현성 | R | 다음 | ☐ |
| L1-S05 | Q1 | 실패 표면화 | R | 지금 | ☐ |
| L2-S01 | Q2 | gold P/R/F1 + CI (agrochem) | G | **지금** | ☐ |
| L2-S02 | Q2 | 라이브 도메인 gold 완전성 | G | 다음 2주 | ☐ |
| L2-S03 | Q2 | 스팬·인용 무결성 | T+R | 다음 | ☐ |
| L2-S04 | Q2 | 스트림 분리 | T | 지금 | ☐ |
| L2-S05 | Q2 | 완전성 정책 | T | 다음 | ☐ |
| L3-S01 | Q3 | 스키마 충실도 | R+C | 지금 | ☐ |
| L3-S02 | Q3 | 타입 커버리지 | R | 다음 | ☐ |
| L3-S03 | Q3 | 연결성·해상도 | R+C | 다음 | ☐ |
| L3-S04 | Q3 | 커뮤니티 | R | 다음 | ☐ |
| L3-S05 | Q3 | FTS+벡터 하이브리드 | C+R | 다음 | ☐ |
| L3-S06 | Q3 | 팩 불변 | R+T | 지금 | ☐ |
| L3-S07 | Q3 | MCP read-only | R+C | 지금 | ☐ |
| L4-S01 | — | 영속·재시작 | R+T | 지금 | ☐ |
| L4-S02 | — | 사람 게이트 | C+R | 지금 | ☐ |
| W-S01 | Q4 | 11탭 네비게이션 | W | **지금** | ☐ |
| W-S02 | Q1 | 리서치 화면→수집·SSE | W+R | **지금** | ☐ |
| W-S03 | Q2 | 검토 큐→승인/거부 | W+R | 지금 | ☐ |
| W-S04 | Q3 | 팩 빌드 화면 | W+R | 지금 | ☐ |
| W-S05 | Q3 | 아티팩트/문서 패널 | W | 다음 | ☐ |
| W-S06 | Q3 | 그래프·커뮤니티 탐색 | W | 다음 | ☐ |
| W-S07 | — | 엔진·설정 화면 | W | 다음 | ☐ |
| W-S08 | — | 홈 채팅·팔레트 | W | 다음 | ☐ |

---

## 실행 절차 (권장 순서)

**Phase A — 지금 1일 (코드·테스트 + agrochem 기준선 + 웹 스모크)**
1. C: L1-S03, L3-S06·S07, L4-S02 코드 확인 (allowlist·packbuilder·critic·MCP)
2. T: L2-S04·S05, L3 관련 테스트 통과
3. G: **L2-S01 실행** — `ontologylab eval --gold tests/gold/agrochem-mini/docs.json` 분리 채점(mock) → 기준 F1+CI 기록
4. **W: Aside 스모크** — W-S01(11탭 순회) → W-S02(리서치 1회, SSE 관측) → W-S03(검토 1건 승인/거부) → W-S04(팩 빌드) — Orca `list apps` → `get app state` → `click`/`type`/`read visible UI` 흐름. Playwright/Selenium 도입 없음.

**Phase B — 다음 2주 (진짜 Q2 + 화면 대조)**
5. R: L1-S01 라이브 수집 1회 (W-S02 결과와 대조)
6. G: **L2-S02** 라이브 문서 2~3개 손작성 gold → 분리 채점 → “빠짐없이”에 숫자 부여 (W-S03 승인 내역과 대조)
7. R: L3-S01·S02·S03 구조 표본 (타입 분포·고아율·문서 간 경로) + W-S05·S06 화면 확인

**Phase C — 확장**
8. R: L1-S02 관련성@k 5질의 (+ W-S02 5질의 화면 로그)
9. R: L3-S04·S05 커뮤니티·하이브리드 5질의 (+ W-S06·S07 화면)

각 Phase 결과는 이 문서 하단에 **실행 결과 기록** 절을 추가해 누적한다(기존 시운전 문서와 동일 형식). W는 `computer-use` 스킬(Orca CLI)로 수행하며 별도 자동화 스택을 도입하지 않는다.

---

## 판정 규칙

- **P0 불변식 위반**: verified를 사람 외 경로가 쓰거나, pack에 proposed가 있거나, MCP가 쓰면 즉시 불합격. W에서 `critic` 점수가 버튼을 미리 체크해도 P0.
- **P1 기능 결함**: 수집 0건·스팬 불일치·고아 과다·탭 도달 불가 등 — 원인 분류 후 수정.
- **게이트**: gold 기반 F1은 **CI 겹침**으로만 개선 판정. 점수 단독 상승은 “개선” 아님(`evaluation.py:bootstrap_f1_interval` 2000 resamples).
- **W 게이트**: W-S01~S04 중 1개라도 화면에서 막히면 **웹 스모크 불합격**(백엔드 합의와 분리 판정).
- **종합**: P0 0건 + P1 수정 + L2-S01·S02 기준선 기록 + W-S01~S04 통과이면 **부분 합격 이상**. 4개 질문(Q1~Q4)에 모두 숫자가 있으면 **합격**.

---

## 증거 규칙

- R마다 라이브 캡처(터미널/`provenance.jsonl`/팩 hash) 또는 코드 위치(grep).
- G마다 `ontologylab eval` 전체 출력 + gold 파일 경로.
- T마다 테스트 파일명 + 통과 로그.
- **W마다 Aside 캡처** — Orca `read visible UI` + 탭 순회/입력/승인 전후 스크린샷(`docs/images/`).
- 모든 수치는 **분리 채점**(엔진별)으로 기록 — 혼합 수치는 금지. W 결과는 L 결과와 1:1 대조(화면 집계 vs DB 집계).

---

## 부록 — Gold 작성 가이드 (L2-S02)

1. 문서 원문을 읽고, `biomed-v1` 스키마(11 entity / 14 relation)에 맞는 엔티티를 모두 적는다.
2. 트리플은 `(src_norm, relation, dst_norm)` — `normalize_name` 기준으로 정규화됨을 기억.
3. 파일 형식: `{\"entities\":[{\"name\":\"...\"}], \"triples\":[{\"src\":\"...\",\"relation\":\"...\",\"dst\":\"...\"}]}` (plain JSON).
4. `MAX_EXAMPLES=20` — missing/spurious는 20개까지만 리포트에 담김( actionable).
5. 저장: `tests/gold/<도메인>/docs.json` — `evaluation.py:load_gold`가 읽음.

## 부록 — 관련성 판정 가이드 (L1-S02)

- **관련**: 질의 의도에 직접 답하는 문서(제목·초록에 핵심 키워드와 맥락 일치).
- **부분**: 주변·간접 관련(같은 질환/약제군의 다른 문맥).
- **무관**: 질의와 무관. 무관은 allowlist/쿼리검증/소스미지원 중 원인 분류.

---

*작성 2026-08-08 · 패치 2026-08-08 W장(Aside+Orca, Playwright 미도입). 실행은 Phase A부터. 이 문서는 `docs/CONANSSAM-CROSSCHECK-2026-08-08.md`의 15축 판정과 `docs/ARCHITECTURE.md` canonical을 시나리오로 구체화한 것이다.*
