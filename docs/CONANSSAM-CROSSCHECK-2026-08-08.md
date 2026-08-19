---
schema_version: 1
doc_id: conanssam-crosscheck-2026-08-08
project: ontologylab
type: crosscheck-workbook
status: canonical
created_at: 2026-08-08
source: https://www.threads.com/@conanssam (609 posts, 2026-06-01~08-07, live DOM 611 scrolls, ~263 series)
baseline_commit: ontologylab@8799 shakedown 2026-08-07 (W1-W14+Graph/SSE) + live verify 2026-08-08 (pytest --collect-only 1702, see docs/CROSSCHECK-RESULT-2026-08-08.md)
audience: [human, agent]
agent_usage: |
  이 문서는 에이전트가 ./ontologylab 코드베이스를 직접 열어 대조-판정하는 워크북이다.
  각 축의 [ ] 체크박스를 그대로 체크하고, 각 축 끝에 판정 메모 한 줄을 남겨라.
  DESIGN-RATIONALE 기둥1(AI가 제안·사람이 결정·verified만 출고)을 깨는 제안은 즉시 폐기한다.
---

# OntologyLab × 코난쌤 Threads 교차 점검 가이드 — 에이전트 공유용

> **수집** 2026-08-08, `https://www.threads.com/@conanssam` 라이브 탭 무한스크롤 `time[datetime]` 파싱 611회, 609개 조각 약 263시리즈, 캘린더 2026-08-08 07:19 KST까지. 가상 리스트 특성상 `n/m` 시리즈 뒤쪽은 DOM 누락이 있어 원문 링크에서 확인.
>
> **OntologyLab 스냅샷** `~/Documents/MUNI/ontologylab` @ `127.0.0.1:8799` (`at.ontologylab.server`, 실데이터 `~/Library/Application Support/ontologylab/data`), W1–W14 + Graph Browser + SSE 완료, `docs/DESIGN-RATIONALE.md` 36편 + `docs/ARCHITECTURE.md` canonical, `docs/CHUNK-SWEEP-2026-08.md`에서 `TARGET_CHUNK_TOKENS 1500→3000` 확정.

## 목차

- 축 0 현황 한 장
- 축 1 Nanjing 5통로 자기진화 설문
- 축 2 Loop Engineering + OneDayAgent 롱호라이즌
- 축 3 HarnessOpt-Bench × EvolveNet
- 축 4 CalibForge × GDPevo
- 축 5 AgentOPSD × TCPO 크레딧 할당
- 축 6 Claude Code dynamic workflows
- 축 7 Skill2-Bench / Skill Entropy
- 축 8 OpenClaw resilience & MobileGym
- 축 9 검색 하이브리드와 임베딩 부채
- 축 10 EviGraph typed evidence graph
- 축 11 K-BrowseComp 한국어 연쇄 탐색
- 축 12 RAG 증거-결정 분리 + 풀 컨텍스트 상한
- 축 13 D² hesitation & Glasswing Mythos
- 축 14 Gated DeltaNet-2 간섭과 청킹 메모리
- 축 15 스킬 스캐폴드(PATS/SkillRise/MemHarness) + SAO
- 검증 결과(10→15)
- 통합 우선순위 매트릭스
- 부록 A 전체 목록 읽기 팁 / 부록 B 검증 체크리스트
- 파일 위치와 삭제 이력

## 이 가이드를 어떻게 쓰나

1. 각 축의 **원문 스레드 링크**를 먼저 연다. 이미지는 대개 2페이지 이후에 있다.
2. **OntologyLab 매핑**에 적힌 파일·심볼을 열어 현재 구현을 확인한다.
3. **[ ] 체크박스**를 통과·보류·불가로 체크하고, 각 축 끝에 **판정 메모 한 줄**을 남긴다.
4. 마지막 **우선순위 매트릭스**에서 이번 주와 다음 분기를 나눈다.

> 전제: OntologyLab은 **AI가 제안, 사람이 결정, verified만 출고** + **로컬 단일사용자 읽기전용 MCP**다. 자동진화를 풀로 켜자는 제안은 설계 위반이다.

---

## 축 0 — OntologyLab 현황 한 장

| 레이어 | 현재 구현 | 핵심 파일 | 검증 상태 |
|---|---|---|---|
| 수집 | deny-by-default allowlist, paper_api는 실측 9+ 소스(arxiv/crossref/openalex/s2/europepmc+biorxiv/pubmed+elsevier/springer/core+clinicaltrials+searxng) △ | `ontologylab/connectors/allowlist.py`, `ontologylab/connectors/paper_api.py` | key 없으면 미노출이 정상 |
| 추출 | 3000토큰 청킹 150 overlap, fenced ```json 파싱, span rebasing, proposed만 쓰기 | `ontologylab/extractor.py:TARGET_CHUNK_TOKENS`, `ontologylab/engines.py:extract_fenced_block` | `docs/CHUNK-SWEEP-2026-08.md`에서 3000 채택 |
| 저장 | sqlite nodes/edges(status=proposed/verified/rejected), (schema,entity_type,normalized_name) dedup, FTS5 lexical tier1 | `ontologylab/kgstore.py`, `ontologylab/ontology_schema.py` | `verified_subgraph()`가 유일 출고 경로 |
| 사람 게이트 | approve/reject/reopen, verified-only pack, critic은 정렬·플래그만 | `ontologylab/kgstore.py`, `ontologylab/critic.py`, `ontologylab/packbuilder.py`, `ontologylab/server/jobs.py` | W8 anti-anchoring 가드 통과 |
| 서빙 | 로컬 MCP 10툴 read-only, file:...?mode=ro&immutable=1 | `ontologylab/mcp_server.py` | pytest --collect-only 1702 (2026-08-08 실측, 워크북 277은 stale) |
| 운영 | launchd 8799, running→failed relabel on restart, SSE job stream | `ontologylab/server/jobs.py:_load_persisted()` | shakedown 11탭 GO, mock은 nodes_new=0 정상 |

---

## 축 1 — 자기진화 에이전트의 5가지 통로

**원문** 프레임워크·메모리·스킬도구·모델·워크플로우, SE 실행 피드백을 영구 개선 신호로 — 2026-08-06 Nanjing 설문
- 1/5 https://www.threads.com/@conanssam/post/DbseTFGkwTp
- 2/5 https://www.threads.com/@conanssam/post/DbseUIgk2mf

**매핑** 프레임워크 `extractor.py`·`kgstore.py`·`packbuilder.py`, 메모리 `kgstore.py` verified KG + `provenance.jsonl`, 스킬 `connectors/*`·`rerankers.py`·`searchquery.py`, 모델 `engines.py` claude/codex/gemini, 워크플로우 `server/jobs.py`·`tui.py`

**자가점검**
- [ ] 5통로 중 우리 하네스가 런타임에 기억하는 것은 무엇인가. `kg.sqlite`와 `provenance.jsonl` 외에 프롬프트·스킴 자체를 기억하는가.
- [ ] 실행 피드백 루프가 있는가. 테스트 통과율 같은 자동 신호가 extraction→approval→pack으로 돌아오는가, 사람 승인만 신호인가.
- [ ] 프레임워크를 스스로 수정하는 범위를 어디까지 허용하는가. prompt_version 자동 갱신은 허용, status 전이는 금지 — 코드상 가드는 어디인가.

**권장** `docs/SELF-EVOLUTION-MAP.md` 1장, 현재 메모리 통로만 활성으로 명시, 나머지는 의도적 비활성

---

## 축 2 — 루프 엔지니어링 + OneDayAgent

**원문** Loop 고정 — 에이전트가 하루 종일 한 일을 밤마다 개선. OneDayAgent 분해→실행→합성→검증→수리, AgentIF-OneDay 0.821
- https://www.threads.com/@conanssam/post/DbCfXQgESq2
- 1/6 https://www.threads.com/@conanssam/post/Dbr03IIk3GK
- 2/6 https://www.threads.com/@conanssam/post/Dbr04Q4EwZy

**매핑** 현재 선형 `collect→extract→verify→pack→MCP`, 밤샘 루프 없음. `server/jobs.py:_load_persisted()`는 끊김을 실패로 기록

**자가점검**
- [ ] 하루짜리 잡에서 초기 제약이 소실되는가. `extraction_state.py`·`provenance.jsonl`에서 재현되는가.
- [ ] 검증·수리를 추가한다면 reject를 `extract --retry`로 돌리는가, 별도 repair 잡인가.
- [ ] 루프 스위치를 대시보드 어디에 두겠는가. Jobs 탭은 SSE만, 토글 UI 없음

**권장** `research-20260807-160310` 4-doc mock 3회 반복, step 누락률 0이면 합성기는 과설계

---

## 축 3 — HarnessOpt-Bench × EvolveNet

**원문** ScaleAI HarnessOpt-Bench seed 하네스+평가 피드백+고정 예산, 신뢰 실행환경 dev/val/test 분리. EvolveNet scope-typed aggregation 5벤치 +8~33%
- 1/6 https://www.threads.com/@conanssam/post/DbvXfTfk1UK
- 2/6 https://www.threads.com/@conanssam/post/DbvXgUek5l2
- 1/3 https://www.threads.com/@conanssam/post/DbuuUiZk5sM
- 구조 https://www.threads.com/@conanssam/post/DbuuN2vE0AR

**매핑** 하네스=`build_extraction_prompt`+프리셋+`chunk_document`, 현재 결정론적+사람 리뷰. Pack verified-only는 HarnessOpt 신뢰 실행환경과 동일 의도

**자가점검**
- [ ] 예산과 dev/val/test를 어디에 고정하는가. `tests/` gold와 `packs/` 분리로 충분한가.
- [ ] federated 진화가 필요한가. 농화학·식물의학 프리셋을 따로 진화할 시나리오는 무엇인가.
- [ ] 하네스 변경이 verified KG를 오염시키지 않음을 어떻게 증명하는가.

**권장** CHUNK-SWEEP을 옵티마이저 1회 개입·고정 예산 10회 호출 버전으로 확장

---

## 축 4 — CalibForge × GDPevo

**원문** CalibForge 실행 가능만 보면 양극단 태스크가 쌓임, 솔버 행동으로 난이도 보정. GDPevo GDP 실무 규칙 혼합 일반화 측정
- 1/6 https://www.threads.com/@conanssam/post/DbwU8nAE63K
- 2/7 https://www.threads.com/@conanssam/post/DbwWIxyEz0g
- 1/7 https://www.threads.com/@conanssam/post/DbwWIBLE961

**매핑** gold `tests/gold/agrochem-mini` 5문서, CalibForge 실행 가능 편향은 우리 파싱 가능 편향. CHUNK-SWEEP은 calls/tokens/elapsed만 측정

**자가점검**
- [ ] mock vs claude 통과율이 둘 다 100% 또는 0%에 몰리면 보정 대상인가.
- [ ] GDPevo처럼 병원체×작물 방제 문항을 규칙·문서 조합으로 훈련→테스트 분할할 수 있는가.
- [ ] span 불일치·alias 충돌 같은 실패 모드를 gold가 커버하는가.

**권장** `sweep_chunk_size.py`에 mock vs claude 분포 로그 3줄 추가, 양극단이면 보류 표기

---

## 축 5 — AgentOPSD × TCPO

**원문** GRPO 전체 동일 어드밴티지 문제, AgentOPSD privileged self-distillation·재귀 베이지안, TCPO 검증자 점수≠크레딧 3비교·surprisal 3~5%
- 1/6 https://www.threads.com/@conanssam/post/DbuZp9Ek8wE
- 1/5 https://www.threads.com/@conanssam/post/DbrgAzdk5N-
- 2/5 https://www.threads.com/@conanssam/post/DbrgBrnk1PA

**매핑** RL 없음, 가장 가까운 것은 critic triage W8. 검증자 점수≠크레딧 구분은 우리 anti-anchoring과 동일 철학. `provenance.jsonl` step 기여도로 환원

**자가점검**
- [ ] critic 정렬 전용 가드를 유지할 수 있는가. 점수가 승인 버튼을 미리 체크하는 경로가 생기지 않는가.
- [ ] 어떤 청크·툴 호출이 pack 품질에 기여했는지 `provenance.jsonl`로 역추적되는가.
- [ ] 학습 대상이 모델 가중치가 아니라 하네스 파라미터라면 RL이 아니라 HarnessOpt인가.

**권장** 보류, critic 승인 일치도 로깅만 유지

---

## 축 6 — Claude Code dynamic workflows

**원문** Claude가 작업에 맞춰 자기 전용 작업틀을 직접 짠다
- 1/11 https://www.threads.com/@conanssam/post/DZHI7vlE7c3

**매핑** 우리 작업틀은 고정 파이프라인+4엔진 스위칭, 하네스가 하네스를 생성하는 메타 없음. `server/jobs.py`는 collect/extract/pack만 구분

**자가점검**
- [ ] 동적 워크플로가 필요한가. 요약 후 추출이 유리한 문서 뭉치 같은 검증 가능한 질문에서만 이득인가.
- [ ] 동적 그래프에서도 allowlist와 `verified_subgraph()`가 불변인가.

**권장** 고정 유지, `docs/ROADMAP.md`에 아이디어 1줄 보류

---

## 축 7 — Skill2-Bench / Skill Entropy

**원문** 개별 스킬 잘해도 cross-skill -4~-13%, 558스킬 9도메인 2~10단계, 앞 단계 정답 의존, 전환 자체가 능력
- 1/6 https://www.threads.com/@conanssam/post/DbsJzYbE5BI
- 2/6 https://www.threads.com/@conanssam/post/DbsJ0kEkyGi

**매핑** 우리 스킬=extraction·retrieval·graph·pack, 현재 개별 F1만 있고 시퀀스 평가 없음

**자가점검**
- [ ] 추출 0.98이 `semantic_search→graph_query→pack` 질의에서 0.85로 떨어지는가.
- [ ] 전환 비용 지표가 있는가. 앞 단계 오류 전파율은 얼마인가.
- [ ] 26 entity 30 relation에서 가장 취약한 cross-skill 조합은 무엇인가.

**권장** 2단계 시퀀스 태스크 5개로 하락폭 측정

---

## 축 8 — OpenClaw resilience & MobileGym

**원문** OpenClaw 2026-05-28 resilience 연쇄장애 차단, MobileGym 브라우저 병렬 안드로이드 JSON 직렬화 수백 병렬
- https://www.threads.com/@conanssam/post/DZBUWqXExTf
- https://www.threads.com/@conanssam/post/DZGZlCdEwsJ

**매핑** resilience는 running→failed relabel+`recover_running_once()`+락 503. 병렬 수백은 없음

**자가점검**
- [ ] 잡 크래시 후 `kg.sqlite-wal`·`jobs/<id>/status.json`이 일관되는가. `test_run_persistence.py` 통과인가.
- [ ] 수백 병렬이 필요한 순간은 언제인가. 100문서 스위프에서 선형 증가를 병렬로 줄일 이득은 얼마인가.

---

## 축 9 — 검색 하이브리드와 임베딩 부채

**매핑** tier1 FTS5 lexical `1/(1+BM25)`, tier2 embedding+cosine+sqlite-vec 옵트인+`--expand` fail-open, 코드는 있으나 키·모델 미연결 시 빈 결과. `/api/sources`·`/api/providers` 비어 있음은 연결 이슈

**자가점검**
- [ ] FTS5만으로 병원체×작물 방제 5질의 재현율 0건 비율은 얼마인가.
- [ ] `--expand` 실패 시 lexical 폴백이 로그에 남는가. BM25+cosine RRF 가중치는 문서화됐는가.

---

## 축 10 — EviGraph: typed evidence graph

**원문** 자율 연구 에이전트의 가설-실험-결과-주장 불일치가 최대 신뢰성 문제, 6노드 5엣지 typed graph, Graph Inspector 약한 노드 순회·하위 재생성·체크포인트 롤백
- 1/4 https://www.threads.com/@conanssam/post/DbuE5XXE1JE
- 2/4 https://www.threads.com/@conanssam/post/DbuE6WDk8so

**매핑** 우리 스키마는 라이브 기준 biomed-v1 11 entity / 14 relation(워크북 일부 축의 “26/30”은 구 스키마/타 문서 인용 — docs/CROSSCHECK-RESULT 축0 참조), Inspector=`critic.py`+`entity_review_context`+`communities.py`+bitemporal `invalidated_ts`, 롤백=`_load_persisted()`+`provenance.jsonl`+`reopen()`

**자가점검**
- [ ] Hypothesis→Experiment→Finding→Claim 체인을 typed edge로 표현할 수 있는가.
- [ ] 약한 노드 탐지가 그래프 순회인가, critic 점수 정렬에만 의존하는가.
- [ ] `reopen()`이 EviGraph 하위 재생성+롤백과 의미적으로 같은가.

**권장** agrochem-mini 5문서에 EviGraph 6+5 투영, 약한 엣지 1개 인위 파손 탐지 실험

---

## 축 11 — K-BrowseComp: 한국어 연쇄 탐색

**원문** GPT-5.5 영어 84%→한국어 45%, DeepSeek 83→30%, K-BrowseComp 다중 한국 사이트 A→B→C 연쇄 탐색, 9실패 유형, AI 생성 100문항 26%
- https://www.threads.com/@conanssam/post/DZGjY1jE7QC
- 1/3 https://www.threads.com/@conanssam/post/DZGjd6Dk9WP
- 2/3 https://www.threads.com/@conanssam/post/DZGjetYE3qu

**매핑** `allowlist.py` deny-by-default+HTTPS+exact-host+리다이렉트 검증+자격증명 차단, `paper_api.py` PAPER_API_HOSTS, SearXNG down 관측

**자가점검**
- [ ] `WEB_CRAWL_ALLOWED_HOSTS`에 한국어 학술·기관 도메인이 있는가.
- [ ] 9실패 중 증거 찾고도 후보 유지 실패를 alias dedup이 해결하는가.
- [ ] 연쇄 탐색에 paper_api+web_crawl 체인 잡이 필요한가.

**권장** 9실패 체크리스트를 collect 로그에 그대로 카운트

---

## 축 12 — RAG 증거-결정 분리 + 풀 컨텍스트 상한

**원문** Agent-style가 Native/Hybrid RAG보다 Trace·Fact 일관 향상, 증거-결정 분리, 풀 컨텍스트 어텐션이 상한
- 2/3 https://www.threads.com/@conanssam/post/DZQsCvgk61j
- 2/3 https://www.threads.com/@conanssam/post/DZKX1UkmAXh

**매핑** 우리 Hybrid RAG+Agent 혼합, `semantic_staleness.py`, CHUNK-SWEEP 1500 vs 3000

**자가점검**
- [ ] Trace vs Fact를 분리 측정하는가. triple F1 외 Trace 평가는 있는가.
- [ ] Native/Hybrid/Agent 기여를 분리해 본 적 있는가.
- [ ] non-chunked 전체 문서 입력과 비교했는가.

---

## 축 13 — D² hesitation & Glasswing Mythos

**원문** D² 디노이징 망설임으로 위험 실시간 차단, Mythos 1만 고위험 취약점 150개 핵심 인프라
- 1/3 https://www.threads.com/@conanssam/post/DZGaRqdE7vg
- 1/3 https://www.threads.com/@conanssam/post/DZGbIozk4Px
- 2/3 https://www.threads.com/@conanssam/post/DZGbJsoE_GG

**매핑** `safety.py` Caps/KillSwitch, allowlist, provenance, critic은 점수만 사람만 차단, Mythos는 잔류·독성 MRL 초과 플래그 유사

**자가점검**
- [ ] span 불일치 경고를 hesitation으로 해석하는가.
- [ ] 농화학 pack에서 MRL 초과 관계를 자동 플래그하는가.
- [ ] 자동 차단이 `approve()`를 대체하는 경로는 없는가.

---

## 축 14 — Gated DeltaNet-2

**원문** 고정 크기 메모리 간섭을 지우기·쓰기 분리 bt/wt 독립, chunkwise WY+gate-aware backward, 하이브리드 최고치
- 1/3 https://www.threads.com/@conanssam/post/DZKX0XSGJ29
- 2/3 https://www.threads.com/@conanssam/post/DZKX1UkmAXh

**매핑** `chunk_document(target=3000, overlap=150)`+span rebasing, 1500→3000은 더 큰 메모리에 덜 압축, FTS5는 고정 크기 인덱스

**자가점검**
- [ ] 1500에서 잘리던 span이 3000에서 살아나는 비율을 측정했는가.
- [ ] erase와 write를 분리 제어하는가. alias 충돌이 줄어드는가.
- [ ] FTS5+벡터 하이브리드 가중치를 문서화했는가.

---

## 축 15 — 스킬 스캐폴드 + SAO

**원문** PATS 훈련용 비계로 재정의 배포 때 제거, SkillRise 스킬 문서가 작업 간 유일 채널, MemHarness 검색→비판→재구성, SAO 단일 롤아웃 비동기 1000스텝 안정
- 1/6 https://www.threads.com/@conanssam/post/DbMR6tRkyzd
- 2/6 https://www.threads.com/@conanssam/post/DbMR7tdk_zT
- 1/6 https://www.threads.com/@conanssam/post/DbaIDqHk9Ef
- 1/8 https://www.threads.com/@conanssam/post/DbdBAG4Ez6g
- 1/3 https://www.threads.com/@conanssam/post/DaoO9cDE65k
- 2/3 https://www.threads.com/@conanssam/post/DaoO-jxE879

**매핑** 스캐폴드=`build_extraction_prompt` few-shot+스키마+`registry.py` MoA/CAS 캐시, 현재 배포용 스캐폴드. SAO 비용 논리는 CHUNK-SWEEP 5→10 호출과 동일

**자가점검**
- [ ] few-shot을 훈련 때 넣고 배포 때 빼면 F1이 유지되는가.
- [ ] `ontology_schema.py` 프리셋이 도메인 전이의 유일 채널인가.
- [ ] 과거 KG 그대로 재생 vs 현재 질의 재구성 성능 차이를 측정했는가.

---

## 검증 결과 — 왜 10개가 아니라 15개인가

- 방법: 609개 bodyClean 전수 바이그램·토큰·16개 패턴 정규식·기존 10축 커버율
- 기존 10축: 202/609 33.2%
- 15축: 225/609 36.9% +23개 +3.8pp, 신규 6축이 43개 스레드 조각 중 23개의 순증분을 제공
- 나머지 407개 중 151개가 광의 OntologyLab 키워드에 걸리나, 42개는 행사·투자 단신으로 의도적 비대상, 349개는 애플리케이션 단신으로 제외 정당
- 결론: 10축은 핵심을 잡았으나 EviGraph·KBrowse·RAG 분리·Safety·DeltaNet·Scaffold 6축이 누락돼 15축이 완전 커버

---

## 통합 우선순위 매트릭스

| 우선순위 | 축 | 이유 | 첫 액션 1~2일 |
|---|---|---|---|
| 지금 | 축4 CalibForge 난이도 보정 | 3줄 로그로 양극단 판정, 비용 0 | `sweep_chunk_size.py`에 mock vs claude 분포 로그 |
| 지금 | 축9 검색 하이브리드 연결 | 0건이 연결 실패인지 품질 실패인지 구분해야 투자 결정 | SearXNG 기동+키 1개 연결 후 5질의 리콜 |
| 지금+1 | 축11 K-BrowseComp 9실패 | 한국어·연쇄 탐색 사각지대 1시간 안에 판단 | `allowlist.py` 한국어 host 점검+9실패 체크리스트를 collect 로그에 |
| 다음 2~4주 | 축1 5통로 맵 + 축2 루프 스위치 | 기억은 문서로, 루프는 스위치로 — 코드 변경 최소 | `docs/SELF-EVOLUTION-MAP.md` 1장+Jobs 탭 repair 스케치 |
| 다음 | 축3 HarnessOpt 축소 복제 | CHUNK-SWEEP 자연 확장, 고정 예산 10회 안 개선 측정 | agrochem-mini 옵티마이저 1회 개입 |
| 다음 | 축7 Skill2 시퀀스 | 전환 비용을 알아야 투자 결정 | 2단계 시퀀스 5개 오류 전파 측정 |
| 다음 | 축10 EviGraph typed graph | 스키마 1줄 추가로 끝나기도 함 | Hypothesis→Finding 체인 relation 1개 실험 |
| 다음 | 축15 스킬 비계 분리 | 배포 스캐폴드 오염 여부 분리 실험 | few-shot 유무 F1 비교 1회 스위프 |
| 보류 | 축5 RL 크레딧 | critic 정렬로 충분, 과설계 | 승인 일치도 로깅만 |
| 보류 | 축6 동적 워크플로 | 고정 파이프라인 아직 병목 아님 | ROADMAP 1줄 |
| 보류 | 축13 Safety, 축14 DeltaNet | 현재 가드로 충분, 아이디어 보관 | DESIGN-RATIONALE 1문단 참조 |
| 안 함 | 완전 자율 자기진화 | 기둥1 위반 | — |

---

## 부록 A — 코난쌤 609개 전체 목록과 읽기 팁

- 전체 목록 609개, 최신순 KST·pagination·120자 미리보기·원문 링크: `artifacts/conanssam_threads_2026-06-01_to_2026-08-07.md` 726줄 130KB 200KB — 실제는 `~/.aside/u/0/artifacts/` 원본(725줄/205,067B) + `~/Documents/MUNI/artifacts/` 동기화본 + 세션 artifacts 동일본 · 워크북 `artifacts/` 상대경로는 세션 밖에서 미존재할 수 있어 절대경로 우선
- 원천 JSON 609개 본문·datetime·pagination·hasImage: `artifacts/conanssam_threads_2026-06-01_to_2026-08-07.json` 1.0MB 1033494 bytes — 동일 3곳 동기화
- `n/m`에서 1/m만 보여도 원문 들어가면 2/m~m/m 이미지를 연속으로 볼 수 있다. `jkf87.github.io` 블로그 링크는 대개 2페이지 이후에 있다
- 좋아요·답글 수는 DOM 꼬리 파싱이라 제외, 원문에서 확인
- 수집 품질 고지: 가상 리스트라 뒤쪽 페이지는 스크롤 윈도우 밖이면 누락, 좋아요 수치는 신뢰 낮음

## 부록 B — 에이전트 검증 체크리스트
> 본 가이드 단독으로 검증 가능 — 타 프로젝트 문서를 열 필요가 없다. 각 체크는 아래 매핑 파일만으로 수행한다.

- [ ] 각 축의 원문 링크 2개를 직접 열어 이미지·댓글까지 확인했다
- [ ] 매핑된 `ontologylab/*.py` 파일을 열어 현재 코드와 대조했다
- [ ] 자가점검 3문항마다 판정 메모 한 줄을 남겼다
- [ ] 우선순위의 지금 3건을 이번 주 백로그에 넣었다
- [ ] 사람 게이트 제거 제안을 했다면 즉시 폐기했다

## 부록 C — 파일 위치와 이전본 삭제 이력

- 정본 1: `~/Documents/MUNI/ontologylab/docs/CONANSSAM-CROSSCHECK-2026-08-08.md` — 에이전트가 코드 옆에서 바로 여는 위치
- 정본 2: `~/Documents/MUNI/artifacts/ontologylab-conanssam-crosscheck-2026-08-08.md` — 외부 공유·Finder 가시 위치
- 정본 3: `~/.aside/u/0/sessions/2026-08-08_klf5SkDhuxS0fFv2/artifacts/ontologylab-conanssam-crosscheck-2026-08-08.md` — 세션 아티팩트 패널
- 원천 데이터: `conanssam_threads_2026-06-01_to_2026-08-07.md` + `.json` — `~/.aside/u/0/artifacts/` 원본 + `~/Documents/MUNI/artifacts/` + 세션 artifacts 3곳 동기화(부록 A 경로 불일치 패치 2026-08-08), 삭제 대상 아님
- 삭제된 초안: `ontologylab_conanssam_selfcheck_guide_2026-08-08.md` 계열 4개(v1·v2·원본 중복) — 2026-08-08 09시 정리에서 제거
- 삭제된 중간물: `~/.aside/u/0/tmp/conanssam_cats2.json` 등 스위프 중간 JSON 5개 — 정리에서 제거

---

*작성 2026-08-08, 브라우저 실측 611 스크롤+코드베이스 대조. 에이전트는 이 문서를 체크리스트로 실행하고, 사람은 판정 메모를 남긴다.*
