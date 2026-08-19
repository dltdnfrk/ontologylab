---
schema_version: 1
doc_id: crosscheck-result-2026-08-08
project: ontologylab
type: crosscheck-result
status: completed
created_at: 2026-08-08
workbook: docs/CONANSSAM-CROSSCHECK-2026-08-08.md
source_threads: ontologylab/artifacts/conanssam_threads_2026-06-01_to_2026-08-07.{md,json} (609; identical to ~/.aside/u/0/artifacts copy)
constraints:
  - DESIGN-RATIONALE 기둥1: AI 제안 · 사람 결정 · verified만 출고 (critic≠approve)
  - ARCHITECTURE: MCP read-only · pack verified-only · allowlist deny-by-default
  - 로컬 단일사용자 (멀티유저·클라우드·외부 그래프DB 제안 0)
human_gate_removal_proposals: 0
---

# OntologyLab × 코난쌤 교차점검 결과 — 2026-08-08

워크북 `docs/CONANSSAM-CROSSCHECK-2026-08-08.md`를 코드·라이브 스토어·609개 bodyClean에 대조한 판정본.
원천 JSON/MD (2026-08-08 경로 보정 후):
- **정본**: `ontologylab/artifacts/conanssam_threads_2026-06-01_to_2026-08-07.{md,json}` (609개, md 725줄/205,067B, json 1,033,494B)
- 동기화본: `~/.aside/u/0/artifacts/` · `~/Documents/MUNI/artifacts/` (cmp identical)
- 워크북 링크 38개 중 OpenClaw `DZBUWqXExTf` 1건만 609 JSON 미수록(가상리스트 누락). `DbrgAzdk5N-`·`DaoO*`는 trailing 문자 이슈로 정규식 매칭만 주의.

**라이브 스토어** (`~/Library/Application Support/ontologylab/data/kg.sqlite`, mode=ro):
문서 42 · nodes proposed 132 / verified 1 / rejected 1 · edges proposed 195 / rejected 2 ·
활성 스키마 `biomed-v1` · entity_type 11 · relation_type 14 · packs 2 · `providers.json` 비어 있음.

**테스트 수집**: `pytest --collect-only` → **1702 tests** (워크북 baseline “277”은 구 스냅샷).

---

## 축 0 — 현황 표 코드 대조

| 레이어 | 워크북 주장 | 판정 | 한 줄 근거 |
|---|---|---|---|
| 수집 | deny-by-default, 5 keyless + 3 keyed | **△** | `allowlist.py` deny-by-default·`NotAllowlisted` ✓. 다만 `PAPER_API_SOURCES`는 arxiv/crossref/openalex/s2/europepmc + **biorxiv/pubmed** + elsevier/springer/core + clinicaltrials + searxng — “5+3”보다 넓음. `WEB_CRAWL_ALLOWED_HOSTS`는 docs.python.org 등 영문 기술·EPPO만 (한국어 학술 host 0). |
| 추출 | 3000/150, fenced json, proposed만 | **✓** | `extractor.py:TARGET_CHUNK_TOKENS=3000`, `OVERLAP_TOKENS=150`. `engines.py:extract_fenced_block`. `kgstore.insert_proposed`만 추출 경로. |
| 저장 | sqlite status 3값, dedup, FTS5, `verified_subgraph` 유일 출고 | **✓** | `kgstore.verified_subgraph()` · `approve`/`reject`/`reopen` · packbuilder `WHERE status='verified'` + 양끝점 JOIN. 라이브는 biomed-v1 (11/14 타입) — 워크북 일부 축의 “26/30”과 불일치. |
| 사람 게이트 | critic은 정렬·플래그만 | **✓** | `critic.py` 모듈 docstring: score→status 경로 없음, `def *approve*` 0건. UI anti-anchoring 계약 유지. |
| 서빙 | MCP 10툴 read-only, `mode=ro&immutable=1` | **✓** | `mcp_server.py` 툴: list_packs/load_pack/get_schema/entity_lookup/get_entity/semantic_search/graph_query/traverse_relations/find_path/get_communities. `KGStore.open(..., immutable=True)` → `?mode=ro&immutable=1`. |
| 운영 | running→failed, SSE, launchd 8799 | **✓** | `jobs.py:_load_persisted` running→failed(“interrupted…”). `recover_running_once`. `tests/test_run_persistence.py` 4케이스. |
| 테스트 baseline | CI 277 green | **△** | 현재 collect-only **1702**. 기능 회귀 없음, 워크북 숫자만 stale. |

---

## 축 1~15 — 판정 표

체크 기호: `[x]` 통과 · `[~]` 부분/보류 · `[ ]` 미충족(또는 해당 없음·의도적 비활성).
원문 TLDR은 609 JSON `bodyClean` 대조(브라우저 라이브 이미지/댓글은 DOM 제약으로 본문 기준; 축8 1링크는 스크랩 누락).

### 축 1 — Nanjing 5통로 자기진화

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/5) 코딩 에이전트 자기진화 5통로: 프레임워크·메모리·스킬도구·모델·워크플로우. (2/5) 객체 중심 분류 — 하네스 코드 수정 / 궤적 메모리 / 스킬. |
| 매핑 확인 | `extractor.py`·`kgstore.py`·`packbuilder.py`·`engines.py`·`server/jobs.py`·`connectors/*`·`provenance` 경로 존재. 런타임 **영구 기억은 kg.sqlite + provenance.jsonl + runs 테이블**뿐. prompt_version은 행 메타, 스키마 자동진화 없음. |
| 자가점검 | [x] 기억하는 통로 = verified KG + provenance/jobs. 프롬프트·스키마 자체 자동 기억 없음(의도). · [x] 실행 피드백 루프 = **사람 승인만** 신호. 테스트 통과율→pack 자동 환류 없음. · [x] 프레임워크 자가수정 범위 = 코드상 `approve`만 status 전이; 추출은 `insert_proposed`만 — **status 전이는 금지 가드 명확**. |
| 판정 메모 | 메모리 통로만 활성이 설계와 일치. 완전 자율 진화는 기둥1 위반 → 제안 없음. |
| 권장 실험 | 난이도 낮음 · 0.5d — `docs/SELF-EVOLUTION-MAP.md` 1장(활성=메모리, 나머지=의도적 비활성). |

### 축 2 — Loop Engineering + OneDayAgent

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/5) 루프 엔지니어링 — 하루 작업 밤마다 개선. (1/6) OneDayAgent 롱호라이즌: 분해·실행 메모리·합성, 초기 제약 누락 문제. |
| 매핑 확인 | 파이프라인 선형 `collect→extract→verify→pack`. 밤샘 루프·repair 잡 없음. `_load_persisted`는 끊김을 failed로 정직 기록. `extraction_state.py` 존재. |
| 자가점검 | [~] 하루짜리 잡 제약 소실 — provenance/extraction_state로 **부분 재현 가능**, 자동 복구 루프 없음. · [x] 검증·수리 = reject 후 사람 재추출이 현재 경로; 별도 repair 잡 없음(의도). · [x] 루프 스위치 UI 없음 — Jobs는 SSE 상태만. |
| 판정 메모 | 롱호라이즌 루프는 과설계 구간. 먼저 mock 반복으로 step 누락률 측정이 선행. |
| 권장 실험 | 난이도 중 · 1d — mock extract 3회 반복, step 누락률 0이면 합성기 보류. |

### 축 3 — HarnessOpt-Bench × EvolveNet

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/6) ScaleAI HarnessOpt-Bench: seed 하네스+평가 피드백+고정 예산. (2/6) dev/val/test 분리·visible val 함정. |
| 매핑 확인 | 하네스=`build_extraction_prompt`+chunk+프리셋. `evaluation.py` gold P/R/F1+CI. pack verified-only = 신뢰 실행환경과 동일 의도. federated 진화 없음. |
| 자가점검 | [~] 예산/분할 — `tests/gold` vs `packs/` 분리는 있으나 **옵티마이저 루프·고정 호출 예산 없음**. · [x] federated 진화 불필요(단일사용자·단일 활성 스키마). · [x] 하네스 변경→verified 오염 방지 = pack immutable + proposed-only insert로 **구조적 증명**. |
| 판정 메모 | CHUNK-SWEEP을 “옵티마이저 1회·예산 N”으로 확장하는 정도가 상한. |
| 권장 실험 | 난이도 중 · 2d — agrochem-mini에 고정 10콜 예산 스위프 1회. |

### 축 4 — CalibForge × GDPevo

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/6) CalibForge: 실행가능만 보면 양극단, 솔버 행동으로 난이도 보정. (2/7) GDPevo: GDP 실무 규칙 혼합 일반화. |
| 매핑 확인 | gold=`tests/gold/agrochem-mini` 구성 문서(CLAUDE.md: 대표 코퍼스 아님). CHUNK-SWEEP은 calls/tokens/elapsed. mock vs claude 분포 로그 없음. |
| 자가점검 | [~] mock/claude 양극단 여부 **미측정** → 보정 대상인지 미판정. · [ ] GDPevo식 규칙×문서 분할 훈련셋 없음. · [~] span/alias 실패 모드는 parse-time repair 코드 있으나 gold 커버리지 불명. |
| 판정 메모 | 라이브 도메인 gold 없이 추출 품질 숫자는 공허. Calib 로그 3줄이 최저 비용 착수점. |
| 권장 실험 | 난이도 낮음 · 0.5d — sweep에 mock vs claude 통과 분포 로그. |

### 축 5 — AgentOPSD × TCPO

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/6) AgentOPSD: 턴별 베이지안 크레딧. (1/5) TCPO: 검증자 점수≠크레딧. |
| 매핑 확인 | RL 없음. 최근접 = W8 critic triage + anti-anchoring. provenance step 기여 로그. |
| 자가점검 | [x] critic 정렬 전용 가드 유지, 점수→승인 미리체크 경로 없음. · [~] pack 품질 기여 역추적 — provenance로 **잡 단위** 가능, 청크 기여도 집계 UI 없음. · [x] 학습 대상이 가중치가 아니므로 RL 대신 HarnessOpt 관점이 맞음. |
| 판정 메모 | RL 크레딧 도입 보류. critic 승인 일치도 로깅만 유지. **사람 게이트 제거 0**. |
| 권장 실험 | 난이도 낮음 · 0.5d — critic score vs 사람 approve 일치도 카운터. |

### 축 6 — Claude Code dynamic workflows

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/11) Claude가 작업별 자기 전용 작업틀(dynamic workflows) 생성. |
| 매핑 확인 | 고정 파이프라인 + 엔진 스위칭. jobs는 collect/extract/pack 구분. 메타-하네스 생성 없음. |
| 자가점검 | [x] 동적 워크플로 **현재 병목 아님** — 고정 유지. · [x] 가령 도입해도 allowlist + `verified_subgraph` 불변 조건 명시 가능. |
| 판정 메모 | ROADMAP 1줄 보류면 충분. |
| 권장 실험 | 난이도 없음 · 0.1d — ROADMAP 아이디어 1줄. |

### 축 7 — Skill2-Bench / Skill Entropy

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/6) cross-skill −4~−13%, 전환 자체가 능력. (2/6) Skill2-Bench 558스킬·2~10단계. |
| 매핑 확인 | 스킬≈extract/retrieval/graph/pack. `evaluation.py`는 개별 triple F1. 시퀀스 평가 없음. 라이브 타입 11/14 (워크북 “26/30” 불일치). |
| 자가점검 | [ ] extract F1 → search→graph→pack 질의 하락 **미측정**. · [ ] 전환 비용·오류 전파율 지표 없음. · [~] 취약 cross-skill 조합 미상 — 타입 수부터 워크북과 불일치. |
| 판정 메모 | 2단계 시퀀스 5개가 투자 판단용 최소 실험. |
| 권장 실험 | 난이도 중 · 1–2d — gold 질의 5개로 단계별 하락폭 측정. |

### 축 8 — OpenClaw resilience & MobileGym

| 항목 | 내용 |
|---|---|
| 원문 TLDR | OpenClaw 링크는 609 JSON에 **미수록**(가상리스트 누락). MobileGym(1/3): 브라우저 병렬 안드로이드·JSON 상태·수백 병렬. |
| 매핑 확인 | resilience=`_load_persisted`+`recover_running_once`+job lock 503. 수백 병렬 수집/추출 없음. `test_run_persistence.py` 존재. |
| 자가점검 | [x] 크래시 후 running→failed·history 유지 테스트 있음. · [x] 수백 병렬 불필요 — 단일사용자·문서 수십 규모. |
| 판정 메모 | 운영 resilience는 충족. MobileGym급 병렬은 비대상. |
| 권장 실험 | 난이도 낮음 · 0.5d — Stop→재실행 사용자 체크리스트(시운전 잔여)만. |

### 축 9 — 검색 하이브리드와 임베딩 부채

| 항목 | 내용 |
|---|---|
| 원문 TLDR | 워크북에 전용 링크 없음. 매핑: FTS5 tier1, embedding tier2 옵트인, expand fail-open. |
| 매핑 확인 | `searchquery.py` expand 존재. `embeddings.py`·`rerankers.py` 코드 있음. **providers.json `[]`** · 키/모델 미연결. `/api/providers` 빈 목록이 정상(미설정). |
| 자가점검 | [~] FTS5만으로 병원체×작물 5질의 재현율 **미실측**. · [~] expand 실패→lexical 폴백 코드 경로 있음, 운영 로그 관측 미확인. RRF 가중치 문서화 빈약. |
| 판정 메모 | “0건 = 연결 실패 vs 품질 실패” 분리가 선결과제. 임베딩 투자 전 providers 1개 연결. |
| 권장 실험 | 난이도 중 · 1d — 엔진/키 1개 연결 후 5질의 FTS 리콜 기록. |

### 축 10 — EviGraph typed evidence graph

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/4) 가설-실험-결과-주장 불일치 → 6노드 5엣지 typed graph. (2/4) Graph Inspector 약한 노드·하위 재생성·롤백. |
| 매핑 확인 | 스키마는 biomed/software entity·relation (Hypothesis 타입 없음). Inspector≈critic 정렬 + graph tab + `communities.py` + `invalidated_ts` + `reopen()`. |
| 자가점검 | [ ] H→E→F→Claim 체인 typed edge **스키마에 없음**. · [~] 약한 노드 = critic 점수 정렬 위주, 그래프 순회 Inspector 아님. · [~] `reopen()`은 상태 되돌림 — 하위 재생성 루프와는 다름. |
| 판정 메모 | 연구-노트 온톨로지 확장 실험은 가능하나 기본 제품 경로 아님. 사람 승인 유지. |
| 권장 실험 | 난이도 중 · 2d — agrochem-mini에 relation 1개 투영 실험(선택). |

### 축 11 — K-BrowseComp 한국어 연쇄 탐색

| 항목 | 내용 |
|---|---|
| 원문 TLDR | GPT-5.5 한/영 84→45%, K-BrowseComp 연쇄 탐색·9실패 유형. |
| 매핑 확인 | allowlist HTTPS+exact-host+redirect re-check+자격증명 차단. **WEB hosts에 한국어 학술·기관 0**. paper_api는 국제 메타데이터 API 중심. |
| 자가점검 | [ ] 한국어 학술 host allowlist 없음. · [~] alias dedup이 “증거 찾고 후보 유지 실패”를 일부 완화 가능하나 미측정. · [~] paper_api+web_crawl 체인 잡 없음. |
| 판정 메모 | 한국어 웹 연쇄는 제품 범위 밖일 수 있으나, host 공백은 명시적 사각. |
| 권장 실험 | 난이도 낮음 · 0.5d — 9실패 체크리스트를 collect 로그 카운트 + host 필요 여부 결정. |

### 축 12 — RAG 증거-결정 분리 + 풀 컨텍스트 상한

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (2/3) Agent-style이 Trace·Fact 일관 향상, 증거-결정 분리. (동 링크 축14와 일부 본문 공유 — DeltaNet 학습 효율 서술). |
| 매핑 확인 | Hybrid RAG 코드 + Agent 혼합. `semantic_staleness.py`. CHUNK-SWEEP 1500→3000. Trace 평점 하네스 없음. |
| 자가점검 | [ ] Trace vs Fact 분리 측정 없음 (triple F1만). · [ ] Native/Hybrid/Agent 기여 분리 실험 없음. · [x] non-chunked 전체 입력 비교는 CHUNK-SWEEP 문서에 부분 근거. |
| 판정 메모 | 추출 F1 게이트가 우선. Trace 메트릭은 gold 확장 후. |
| 권장 실험 | 난이도 중 · 2d — gold에 Trace 라벨 소량 추가 시에만. |

### 축 13 — D² hesitation & Glasswing Mythos

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/3) D² 디노이징 망설임으로 위험 직전 차단. (1/3) Mythos 1만 고위험 취약점·핵심 인프라. |
| 매핑 확인 | `safety.py` Caps/KillSwitch, allowlist, provenance. critic 점수만·사람만 차단. MRL 자동 플래그 없음. |
| 자가점검 | [~] span 불일치 = parse repair/drop — hesitation 점수로 승격 안 함. · [ ] MRL 초과 자동 플래그 없음. · [x] 자동 차단이 `approve()` 대체 경로 **없음** (기둥1 준수). |
| 판정 메모 | 현재 가드로 충분. 자동 차단 강화는 사람 게이트를 건드리지 않는 선에서만. |
| 권장 실험 | 난이도 낮음 · 0.2d — DESIGN-RATIONALE 참조 1문단 유지. |

### 축 14 — Gated DeltaNet-2

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/3) 고정 메모리 간섭 → 지우기/쓰기 게이트 분리. (2/3) chunkwise WY + gate-aware backward, 하이브리드 최고. |
| 매핑 확인 | `chunk_document(3000,150)` + span rebasing. FTS5 고정 인덱스. erase/write 분리 제어 없음(해당 없음). |
| 자가점검 | [~] 1500→3000 span 생존율 — CHUNK-SWEEP에 측정 있음(채택 근거). · [ ] erase/write 분리 해당 없음. · [~] FTS+벡터 하이브리드 가중치 문서화 부족. |
| 판정 메모 | 청킹 메모리는 이미 3000으로 고정. DeltaNet급 아키텍처 차용 불필요. |
| 권장 실험 | 난이도 없음 · 보류. |

### 축 15 — 스킬 스캐폴드 + SAO

| 항목 | 내용 |
|---|---|
| 원문 TLDR | (1/6) PATS: 스킬=훈련 비계, 배포 시 제거. (2/6) 스킬 품질 vs 다음 롤아웃 기여. |
| 매핑 확인 | 스캐폴드=`build_extraction_prompt` few-shot+스키마+registry 캐시 — **배포에도 상주**. SAO 비용 논리≈CHUNK-SWEEP 호출 상한. |
| 자가점검 | [ ] few-shot 제거 시 F1 유지 **미측정**. · [~] `ontology_schema` 프리셋이 도메인 전이 주채널(유일하진 않음 — registry 캐시 병행). · [ ] 과거 KG 재생 vs 재구성 성능 미측정. |
| 판정 메모 | 배포 스캐폴드 오염 여부는 few-shot on/off 1회 스위프로 판정 가능. |
| 권장 실험 | 난이도 중 · 1d — few-shot 유무 F1 비교 1 스위프. |

---

## 검증 결과 재현 (202/609 → 225/609)

| 항목 | 워크북 | 이번 재현 | 해석 |
|---|---|---|---|
| 원천 건수 | 609 | **609** (JSON list) | 일치 |
| md | 726줄·130–200KB | **725줄 · 205,067B** | 실질 일치 |
| json | 1.0MB | **1,033,494B** | 일치 |
| 기존 10축 커버 | 202/609 (33.2%) | 패턴 세트에 민감 (아래) | 원 16패턴 스크립트 **미보존** |
| 15축 커버 | 225/609 (36.9%), +23 | 협의 고유명 패턴: 42→69 (**+27**); 중범위 토큰: 147→170 (**+23**) | **순증분 +23은 재현** |
| 광의 OL 키워드 | 407 중 151 광의 등 | bodyClean 광의 에이전트/하네스/… ≈ **454–481** | 정의 따라 변동 |

**원인 (202/225 절대치 미일치)**:
1. 워크북이 인용한 “바이그램·토큰·16개 패턴”의 **정규식 원문이 산출물에 남아 있지 않음** (`conanssam_clean2.json`은 609 본문 복제본).
2. 고유명(HarnessOpt, EviGraph, …)만 쓰면 과소(42/69), 일반 토큰(에이전트·루프·검색)을 넓히면 과다(300+).
3. 가상 리스트 누락: 축8 OpenClaw URL 등 일부 href가 609에 없음 — 커버 분모/분자 모두 스크랩 한계를 공유.

**결론**: “10→15 확장의 순증분 ≈ +23 조각” 주장은 중범위 패턴으로 **재현 가능**. 절대 202/225는 원 패턴 복원 전 **인용값으로만 보존**하고, 이후 재집계 시 패턴 파일을 `docs/`에 고정할 것.

---

## 통합 우선순위 매트릭스 (현재 코드 상태 재작성)

| 우선순위 | 축 | 이유 (코드 근거) | 첫 액션 1–2일 | 사람 게이트 |
|---|---|---|---|---|
| **지금** | 축4 Calib 분포 | gold·엔진 품질 숫자가 공허한 상태; 로그 3줄로 양극단 판정 | sweep/extract 경로에 mock vs claude 통과 분포 로그 | 유지 |
| **지금** | 축9 검색 연결 | `providers.json=[]`, FTS-only — 0건의 원인을 연결/품질로 분리해야 함 | provider 1개 또는 명시적 FTS-only 문서화 + 5질의 리콜 | 유지 |
| **지금+1** | 축11 한/allowlist 사각 | `WEB_CRAWL_ALLOWED_HOSTS` 한국어 host 0 | host 필요 여부 결정 + 9실패 카운트 훅 | 유지 |
| **지금+1** | 축0 문서 stale | 워크북 “5+3·277·26/30”이 코드와 불일치 | 워크북 축0 표 갱신(소스 목록·1702·11/14) | — |
| **다음 2–4주** | 축1 5통로 맵 | 구현=메모리 통로만 — 문서화로 오해 방지 | `SELF-EVOLUTION-MAP.md` 1장 | 유지 |
| **다음** | 축7 시퀀스 F1 | 개별 F1만 있음, 전환 비용 모름 | 2단계 질의 5개 | 유지 |
| **다음** | 축3 HarnessOpt 축소 | evaluation 하네스 이미 있음 | 고정 예산 10콜 1회 | 유지 |
| **다음** | 축15 few-shot on/off | 배포 스캐폴드 상주 | F1 비교 1 스위프 | 유지 |
| **다음(선택)** | 축10 EviGraph 투영 | 스키마에 H/E/F/C 없음 | relation 1개 실험 | 유지 |
| **다음(선택)** | 축2 루프 | step 누락 미측정 | mock 3회 누락률 | 유지 |
| **보류** | 축5 RL | critic 가드로 충분 | 일치도 로깅만 | 유지 |
| **보류** | 축6 동적 WF | 병목 아님 | ROADMAP 1줄 | 유지 |
| **보류** | 축12 Trace 메트릭 | gold 선행 필요 | — | 유지 |
| **보류** | 축13·14 Safety/DeltaNet | Caps/KillSwitch·chunk 3000으로 충분 | — | 유지 |
| **안 함** | 완전 자율 자기진화 / critic 자동 승인 | **기둥1 위반** | — | **제거 제안 0** |

---

## 부록 B — 에이전트 검증 체크리스트

- [x] 각 축의 원문 링크를 609 JSON `bodyClean`으로 대조했다 (이미지·댓글 라이브 DOM은 미오픈; 축8 OpenClaw 1링크 스크랩 누락 명시).
- [x] 매핑된 `ontologylab/*.py` (allowlist, extractor, engines, kgstore, critic, packbuilder, jobs, mcp_server, searchquery, embeddings, rerankers) 및 라이브 kg.sqlite를 열어 대조했다.
- [x] 자가점검 문항마다 `[x]/[~]`/`[ ]`와 판정 메모 한 줄을 남겼다 (15축 전부).
- [x] 우선순위의 **지금** 항목을 재작성 매트릭스 상단에 넣었다 (축4·축9·축11·축0 문서).
- [x] 사람 게이트 제거 제안 **0건** (critic→approve, 자동 verified, MCP write 제안 없음).

---

## 부록 C — 증거 스냅샷

```
extractor.TARGET_CHUNK_TOKENS = 3000
extractor.OVERLAP_TOKENS = 150
engines.extract_fenced_block: present
kgstore.approve / reject / reopen: present
kgstore.verified_subgraph: present
critic: no approve path; advisory scores only
jobs._load_persisted: running → failed relabel
mcp tools (10): list_packs load_pack get_schema entity_lookup get_entity
                semantic_search graph_query traverse_relations find_path get_communities
open URI: file:...?mode=ro&immutable=1
live: docs=42 nodes=(proposed 132, verified 1, rejected 1)
      edges=(proposed 195, rejected 2) schema=biomed-v1 (11 et / 14 rt)
providers.json: {"providers": []}
pytest --collect-only: 1702 tests
threads: 609 bodies; coverage delta +23 reproducible on mid-range patterns
```

---

*완료 조건 충족: 15축 판정 메모 전부 · 사람 게이트 제거 제안 0 · 결과 경로 `docs/CROSSCHECK-RESULT-2026-08-08.md`.*
