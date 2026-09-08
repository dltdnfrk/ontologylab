# OntologyLab 설계 전면 재검토 (2026-08-26)

기준 원칙 (2026-08-26 확정): **소프트웨어는 개념적으로 단순해야 코드가 단순해진다. 파이프라인은 명시적·선형이어야 하며, 어느 단계에 어느 엔진이 꽂히는지, 입력·출력·책임이 즉시 보여야 한다.** 엔진은 교체 가능한 단계 구현체이지 숨은 오케스트레이션 계층이 아니다. 단계 간 우회, 중복 라우팅, 암묵적 fallback, 범용 메가 엔진은 구조 결함이다.

대상: `/Users/hyunjun/Documents/MUNI/ontologylab` HEAD `7f94879`, tree `306bbb6`. 코드·테스트는 수정하지 않았다.

## 0. 요약 판정

선언된 파이프라인은 6단계 한 줄(`collect -> extract -> verify -> KG -> pack -> MCP`, `docs/ARCHITECTURE.md:6`)이지만, 실제 코드는 **183개 모듈 56,875 LOC** 위에 최소 **4개의 병행 흐름**(legacy collect/shadow 수집, Wave 2.1 v2 수집, Method 컴파일러, H1/cutover 마이그레이션)이 겹쳐 있고, 세 개의 메가 모듈(`kgstore.py` 5,587 LOC, `server/routes.py` 2,875 LOC, `main.py` 2,309 LOC)이 파이프라인 단계 대부분을 내부에 인라인하고 있다.

핵심 수치 (근거: `evidence/design-review-20260826/inventory.json`, `stage-map.json`):

| 지표 | 값 |
|---|---|
| 모듈 수 / LOC | 183 / 56,875 |
| 단일 단계에 귀속되지 않는 모듈 (multi_stage) | 110 / 183 |
| 어떤 진입점(CLI·HTTP·MCP)에서도 import되지 않는 모듈 (orphan) | 14 |
| 숨은 fallback 지점 | 94 |
| 엔진 슬롯(교체 가능 구현체가 꽂히는 지점) | 18 (그중 `get_engine` 호출 14곳) |
| `KGStore` 클래스가 걸치는 단계 | 9 / 11 |
| CLI 서브파서 / HTTP 라우트 | 39 / 85 (+2 별도 라우터) |

판정: **현 구조는 단순성 원칙을 충족하지 않는다.** 원인은 기능 부족이 아니라 흐름의 중첩이다. 아래 편차 18건 중 HIGH 7건은 모두 "같은 일을 하는 경로가 둘 이상 있고, 어느 것이 정준인지 코드가 말하지 않는다"로 요약된다.

## 1. 근거 (evidence)와 방법

- `evidence/design-review-20260826/inventory.json` — 정적 import 그래프. 모듈별 LOC·fan-in·fan-out·진입점 도달 집합. 검증: `inventory-check.txt` (183/183, LOC 합 56,875 일치), `inventory-unreachable-check.txt` (미도달 14개의 importer가 전부 미도달 집합 내부임을 확인 — `cutover_*`·`review_decision*`는 서로만 import하는 고립 군집이다).
- `evidence/design-review-20260826/stage-map.json` — 모듈별 정준 단계 사상, 부차 단계, 중첩 모듈, 숨은 fallback, 엔진 슬롯. 6개 탐색 레인(`stage-lanes/L1..L6.json`)의 합집합, 모든 `path:line`은 파일 존재·행 범위·비공백을 검증했다 (`stage-map-check.txt`, `stage-map-multistage-check.txt`).
- 선행 감사 `docs/ENGINE-PIPELINE-AUDIT-2026-08-19.md`의 우선순위 10건과 대조했다. 그중 3번(named-pack `_verified_pack` 경유)은 MCP 읽기 경로에서 해소되었고, 1·2·9·10번은 미해소로 본 보고서 편차에 재등장한다.
- 이 문서의 모든 `path:line` 인용은 `evidence/design-review-20260826/citation-check.txt`로 존재를 검증한다.
- 한계: `stage-map.json`의 `multi_stage` 110개 중 24개는 같은 `path:line`을 반복해 2개 이상 근거 기준을 채웠다 (예: `ontologylab/method_store.py:631` 4회). 이 24개는 "두 단계를 독립적으로 입증"했다기보다 "한 위치가 두 단계 책임을 동시에 진다"는 뜻이며, 본문 편차 목록(§4)은 이 24개에 의존하지 않고 `kgstore`/`routes`/`main` 등 고유 근거가 2개 이상인 모듈만 인용한다. `secondary_stages[].stage`는 레인 원문 표기(`Verify`, `cross-cutting`)를 그대로 두었고 `stage` 필드만 정준 소문자 어휘로 정규화했다. 적대적 검토 결과는 `evidence/design-review-20260826/review-adversarial.md` (APPROVE, blocker 0, note 58).

## 2. 정준 파이프라인과 현재 코드의 사상

정준 8단계(2026-08-26 확정)와 인프라·횡단·고아 분류에 183개 모듈을 하나씩 귀속시켰다. 아래 표의 개수는 `stage-map.json` `by_stage`와 동일하다.

| 단계 | 책임 (입력 -> 출력) | 모듈 수 | 대표 모듈 | 주요 문제 |
|---|---|---|---|---|
| Source | 허용된 출처·쿼리 정의 | 2 | `sources.py`, `connectors/allowlist.py` | `registry_lookup`이 allowlist 밖에서 직접 HTTP (`ontologylab/connectors/registry_lookup.py:66`) |
| Acquire | 출처 -> 원문 바이트·메타 | 15 | `ingestion_service.py`, `connectors/paper_api.py`, `file_lifecycle.py` | 수집 파이프라인이 둘 (`ontologylab/ingestion.py:110`, `ontologylab/ingestion_shadow.py:33`) |
| Normalize | 바이트 -> Work/Representation/Observation 신원 | 12 | `authority_repo.py`, `selection*.py`, `preferred.py` | `selection_*` 6파일 684 LOC 기계적 분할 |
| Resolve | 엔티티·식별자 정합 | 8 | `normalization.py`, `registry.py`, `merge.py`, `reconciliation.py` | `registry.py` 758 LOC가 설치+캐시+HTTP 검증 혼합 |
| Extract | 문서 -> 제안(proposed) + span | 11 | `extractor.py`, `research_extract.py`, `server/jobs.py` | Extract 안에서 citation 영속 (`ontologylab/extractor.py:898`) |
| Synthesize | 제안 -> 커뮤니티·확장·메소드 IR | 9 | `communities.py`, `expansion.py`, `method_compiler*.py` | Method가 자체 SQL·팩·MCP를 가진 제2 파이프라인 |
| Verify | 인간 결정·근거 영수증 | 21 | `grounded_review*.py`, `citation*.py`, `critic.py` | 8+7파일 분할, 자문 수학(critic/calibration/conformal) 미연결 |
| Publish | 검증된 사실 -> 불변 팩 | 19 | `packbuilder.py`, `pack_v2_*.py`, `pack_verifier.py` | v1/v2 빌더 포크 (`ontologylab/packbuilder.py:365`) |
| Consume | 팩 -> MCP·HTTP·CLI 읽기 | 14 | `mcp_server.py`, `server/routes.py`, `main.py` | `routes.py`/`main.py`가 8·7단계에 걸침 |
| infra | 저장소·설정·보안·모델 | 35 | `kgstore.py`, `engines.py`, `models.py`, `server/app.py` | `KGStore` 9단계 god object (`ontologylab/kgstore.py:603`) |
| cross_cutting | 마이그레이션·프로비넌스 | 23 | `h1_*.py`(18), `migration*.py`, `provenance.py` | H1이 live Verify에 누수 (`ontologylab/grounded_review_members.py:11`) |
| orphan | 진입점 미도달 | 14 | `cutover_*`(6), `review_decision_*`(5), `review_grounding.py`, `serve.py`, `tui.py` | `serve.py`·`tui.py`는 콘솔 스크립트 진입점이라 실제 고아는 12 |

파이프라인이 선언과 다른 지점:

1. 선언은 한 줄이지만 Acquire 단계 진입이 두 개다: `POST /collect` (`ontologylab/server/routes.py:1893`)와 `POST /ingest` (`ontologylab/server/ingest_routes.py:24`), CLI `collect` (`ontologylab/main.py:483`).
2. Extract 이후 흐름이 KG 노드/엣지 경로와 Method IR 경로로 갈라지고, 두 경로가 각각 저장·검증·팩·MCP를 따로 가진다 (`ontologylab/method_store.py:631`, `ontologylab/method_pack_sql.py:16`, `ontologylab/method_mcp_sql.py:15`).
3. Publish가 `evidence_mode` 유무로 v1/v2로 갈라지는데 CLI(`ontologylab/main.py:1287`)와 HTTP(`ontologylab/server/routes.py:2715`)는 v2에 도달하지 못하고, v2는 `pack_readiness.py`의 별도 `main`(`ontologylab/pack_readiness.py:176`)에서만 나온다.

## 3. 엔진 슬롯 표

원칙상 엔진 슬롯은 "단계가 소유하는 하나의 계약 + 교체 가능한 구현체 목록 + 꽂히는 지점 하나"여야 한다. 현재 18개 슬롯을 정리하면 다음과 같다.

| 단계 | 인터페이스 | 구현체 | 삽입 지점 | 평가 |
|---|---|---|---|---|
| (공통) | `Engine` Protocol `generate(prompt, *, model)` (`ontologylab/models.py:285`) | `MockEngine`/`ClaudeEngine`/`CodexEngine`/`GeminiEngine`/`ApiEngine` (`ontologylab/engines.py:483`, `:534`, `:566`, `:594`, `:706`) | `get_engine` (`ontologylab/engines.py:890`) | 계약은 깨끗함. 문제는 해석 지점이 하나가 아니라 14곳 |
| Acquire | `engine.generate` -> 쿼리 목록 | 위 5종 | `ontologylab/literature.py:146`, `ontologylab/searchquery.py:174` | 엔진 부재·오류 시 raw topic으로 fail-open (`ontologylab/literature.py:154`, `ontologylab/searchquery.py:184`) |
| Extract | `Engine.generate` (주입) | 위 5종 | `ontologylab/extractor.py:822`, `ontologylab/research_extract.py:159`, `ontologylab/method_extract.py:220` | 슬롯은 주입형으로 올바름. 그러나 호출자가 각자 `get_engine` |
| Synthesize | summarizer 콜러블 + 알고리즘 선택 | `extractive_summary` / `llm_summarizer(engine)` / `leiden` / `label_propagation` | `ontologylab/communities.py:314`, `ontologylab/packbuilder.py:573` | `auto`가 라이브러리 유무로 알고리즘을 바꿈 (`ontologylab/communities.py:57`) |
| Synthesize | `Engine.generate` (확장 쿼리) | 위 5종 | `ontologylab/expansion.py:99` | CLI 기본 mock (`ontologylab/main.py:2165`) |
| Resolve | `lookup_fn(resource, name)` | 로컬 레지스트리 캐시 | `ontologylab/enrichment.py:135`, `ontologylab/connectors/resources.py:371` | 같은 조회가 `registry_lookup.py`에도 병렬 존재 |
| Verify | `Engine.generate` (critic) | 위 5종 | `ontologylab/critic.py:266` | 상태를 바꾸지 않는 자문 (`ontologylab/critic.py:11`), CLI 기본 mock (`ontologylab/main.py:1999`) |
| Verify | `MockEngine` 고정 | Mock만 | `ontologylab/competency.py:142` | `get_engine`을 우회한 하드코딩 |
| Publish | `verify_pack(pack_dir)` | `_verify_v1` / `_verify_v2` | `ontologylab/pack_verifier.py:525` | v1/v2 이중 구현 |
| Consume | `Embedder.embed` | `SentenceTransformerEmbedder` / `HashingEmbedder` | `ontologylab/embeddings.py:219`, 배선 `ontologylab/mcp_server.py:1375` | `auto`가 설치 여부로 모델을 바꿈 (`ontologylab/embeddings.py:233`) |
| Consume | `Reranker.score` | CrossEncoder / None | `ontologylab/rerankers.py:91`, 배선 `ontologylab/mcp_server.py:715` | MCP에서 `"auto"` 하드코딩 (`ontologylab/rerankers.py:103`) |
| Consume | `Engine.generate` (intent/chat) | 위 5종 | `ontologylab/intent.py:200` | 설정 부재 시 mock으로 fall-through (`ontologylab/server/settings.py:135`) |
| (orphan) | `ReaderKind` + `observe_*` | 6 reader | `ontologylab/cutover_readers.py:280` | 진입점 없음 |

`get_engine` 호출 14곳: `ontologylab/main.py:130`, `:644`, `:1052`, `:1312`, `:1507`, `:1792`; `ontologylab/mcp_server.py:821`; `ontologylab/server/jobs.py:731`, `:851`, `:1094`; `ontologylab/server/routes.py:213`, `:393`, `:1301`, `:2345`. 즉 "어느 엔진이 어디에 들어가는가"는 단계가 아니라 **표면(CLI/HTTP/MCP)마다** 결정된다. 이것이 엔진 배치를 한눈에 볼 수 없게 만드는 직접 원인이다.

## 4. 편차 목록

심각도: HIGH = 정준 흐름이 둘 이상이거나 단계 경계가 없음 / MED = 단일 흐름이나 숨은 fallback·누수·중복 / LOW = 정리 대상.

| ID | 심각도 | 편차 | 근거 | 단순화 제안 |
|---|---|---|---|---|
| D01 | HIGH | 엔진 해석이 단계가 아니라 소비자(CLI/HTTP/MCP)마다 반복됨 | `ontologylab/main.py:644`, `ontologylab/server/jobs.py:731`, `ontologylab/server/routes.py:2345`, `ontologylab/mcp_server.py:821` | `resolve_engine(stage, settings)` 하나만 두고 단계 함수는 `Engine`을 인자로 받는다. 14곳 -> 1곳 |
| D02 | HIGH | 기본 엔진이 세 곳에서 다르게 선언됨 (CLI mock, paths claude, HTTP 금지) | `ontologylab/main.py:398`, `ontologylab/main.py:1999`, `ontologylab/main.py:2165`, `ontologylab/paths.py:20`, `ontologylab/server/schemas.py:80`, `ontologylab/competency.py:142` | CLI 기본값 제거(필수 인자) 또는 `DEFAULT_ENGINE` 단일 소스. `competency.py`의 하드코딩 Mock 제거. 감사 1번 미해소 |
| D03 | HIGH | Acquire 파이프라인이 둘: legacy collect/shadow 와 v2 `ingest_item`; shadow는 슬롯이 아니라 하드코딩 import | `ontologylab/ingestion.py:110`, `ontologylab/ingestion_shadow.py:33`, `ontologylab/ingestion_service.py:300`, `ontologylab/server/routes.py:1893`, `ontologylab/server/ingest_routes.py:24` | `ingest_item` 하나를 정준으로 확정하고 `ingestion.py`/`ingestion_shadow.py`/`/collect` 경로 제거. 라우터 하나 |
| D04 | HIGH | shadow 영속이 항목 단위로 예외를 삼키고 계속 진행 (영수증 없음) | `ontologylab/ingestion_shadow.py:414` | 항목별 typed failure receipt. D03 해소 시 함께 사라짐 |
| D05 | HIGH | `KGStore` 한 클래스가 9단계(DDL·문서·제안·검증·병합·합성·팩 뷰·조회)를 소유 | `ontologylab/kgstore.py:603`, `:791`, `:2029`, `:2593`, `:2937`, `:3657`, `:4352`, `:4751`, `:4926` | 단계가 소유하는 저장 모듈로 분할 (schema / documents / proposals / review / merge / synth / publish-view / query). 감사 10번 미해소 |
| D06 | HIGH | CLI와 HTTP가 같은 단계 로직을 각자 인라인 구현 (collect·extract·critic·merge-scan·build-pack) | `ontologylab/main.py:483` vs `ontologylab/server/routes.py:1894`; `ontologylab/main.py:619` vs `ontologylab/server/jobs.py:707`; `ontologylab/main.py:1048` vs `ontologylab/server/routes.py:1296`; `ontologylab/main.py:1195` vs `ontologylab/server/routes.py:1378`; `ontologylab/main.py:1287` vs `ontologylab/server/routes.py:2715` | 단계 함수(순수 서비스)를 하나 두고 CLI/HTTP/MCP는 얇은 어댑터로. `main.py` 39 파서·38 지연 import, `routes.py` 85 라우트는 그 결과로 줄어든다 |
| D07 | HIGH | Method 서브시스템이 자체 SQL·게이트·팩·MCP를 가진 제2 파이프라인 (31파일 8,983 LOC); G8 게이트는 항상 통과, IR 코덱은 이중 스키마 | `ontologylab/method_compiler.py:212`, `ontologylab/method_compiler_gates.py:497`, `ontologylab/method_ir_codec.py:863`, `ontologylab/method_pack_sql.py:16`, `ontologylab/method_mcp_sql.py:15`, `ontologylab/method_store.py:631`, `ontologylab/method_snapshot.py:214` | 결정 필요(§6-1). 정준 파이프라인의 Synthesize 슬롯 구현체로 재정의하고 저장·팩·MCP는 공용 단계를 재사용하거나, 별도 패키지로 격리해 live 흐름에서 뺀다. 빈 G8과 중복 `MethodPackSql`은 어느 쪽이든 제거. 감사 9번 미해소 |
| D08 | MED | 진입점 미도달 모듈 12개: `cutover_*` 6 (Step 9C 미배선), `review_decision_*` 5 (`grounded_review*`의 중복), `review_grounding` | `ontologylab/cutover_rehearsal.py:20`, `ontologylab/review_decision.py:1`, `ontologylab/review_grounding.py:1` | 삭제 또는 `archive/`로 이동. 테스트만 남는 코드는 제품이 아니다 |
| D09 | MED | 일회성 H1 마이그레이션(18파일 2,435 LOC)이 live Verify 경로에 import됨 | `ontologylab/grounded_review_members.py:11`, `ontologylab/h1_cli.py:15`, `ontologylab/main.py:2285` | 마이그레이션은 `migrations/` 하위 패키지로 격리하고 live 모듈에서 import 금지 |
| D10 | MED | Publish 빌더가 `evidence_mode`로 v1/v2 포크; 정규 진입(CLI·HTTP)은 v1만, v2는 별도 `main` | `ontologylab/packbuilder.py:365`, `ontologylab/packbuilder.py:377`, `ontologylab/packbuilder.py:801`, `ontologylab/pack_readiness.py:176` | v2 하나로 통일하고 v1 분기·`_verify_v1` 제거. `packbuilder.py`(1,002 LOC)의 커뮤니티 합성(`ontologylab/packbuilder.py:573`)은 Synthesize로 이동 |
| D11 | MED | Source allowlist 우회: `registry_lookup`이 `check_url` 없이 직접 `urlopen`, 병렬 조회가 `resources.py`에도 존재 | `ontologylab/connectors/registry_lookup.py:66`, `ontologylab/connectors/allowlist.py:112`, `ontologylab/connectors/resources.py:371`, `ontologylab/server/routes.py:1859` | 모든 outbound를 allowlist 게이트 하나로. 감사 6번 미해소 |
| D12 | MED | 숨은 fallback 94곳: 엔진 부재 시 raw topic, citation 컨텍스트 없으면 빈 튜플, `auto`가 설치 여부로 알고리즘·모델 선택 | `ontologylab/literature.py:154`, `ontologylab/searchquery.py:184`, `ontologylab/citation_bind.py:38`, `ontologylab/communities.py:57`, `ontologylab/embeddings.py:233`, `ontologylab/rerankers.py:103`, `ontologylab/mcp_server.py:715`, `ontologylab/alias_authority.py:37`, `ontologylab/chatstore.py:221` | `auto` 제거. 선택은 설정에서 명시하고, 부재는 typed unavailable로 반환. 감사 7번 부분 해소 |
| D13 | MED | 단계 경계 우회: Extract 쓰기 안에서 Verify 영수증(citation) 영속, `research_extract`가 Acquire+Normalize+Extract를 한 함수에 접음 | `ontologylab/extractor.py:898`, `ontologylab/research_extract.py:133` | citation 영속은 Verify 단계 입력으로 분리, research 경로는 단계 함수 3개의 합성으로 |
| D14 | MED | 마이그레이션 상태 원장이 셋 (v2 ledger, H1 ledger, cutover_state)이며 Publish가 그중 하나를 읽어 거부 | `ontologylab/pack_readiness.py:218`, `ontologylab/cutover_rehearsal.py:20`, `ontologylab/authority.py:24` | 원장 하나. Publish 준비도는 그 하나만 본다 |
| D15 | LOW | 250 LOC 상한을 맞추기 위한 기계적 분할 (`grounded_review` 8, `citation` 7, `selection` 6, `extraction_receipt` 5 파일)이 단계 경계를 흐림 | `ontologylab/grounded_review.py:1`, `ontologylab/citation_bind.py:33`, `ontologylab/selection_policy.py:1` | 단계 단위로 재결합. LOC 상한은 단순화의 결과이지 목적이 아니다 |
| D16 | LOW | Verify 자문 수학(critic/calibration/conformal/evaluation)이 상태를 바꾸지 않는 GET/CLI에만 노출 | `ontologylab/critic.py:11`, `ontologylab/server/routes.py:410`, `ontologylab/server/routes.py:428`, `ontologylab/main.py:1083` | 리뷰 큐 정렬에 연결하거나 삭제. 감사 10번 |
| D17 | LOW | 검증 안 된 manifest 읽기 경로 두 곳 잔존 | `ontologylab/mcpb.py:55`, `ontologylab/packbuilder.py:904` | `inspect_verified_manifest` 경유로 통일. 감사 3번 잔여 |
| D18 | LOW | 진입점 세 개(`main`, `server/app`, `mcp_server`)의 import 폐쇄가 139/146/90 모듈로 거의 겹침 | `ontologylab/server/jobs.py:707` `_extract_async`가 `ontologylab/main.py:619`를 미러링; `evidence/design-review-20260826/inventory.json` `closure_sizes` | 단계 패키지화(§5) 후 Consume 어댑터만 남으면 폐쇄가 자연히 분리된다 |

## 5. 목표 구조 (제안)

원칙을 코드 배치로 옮기면 다음 한 그림이다. 각 단계는 **함수 하나, 입력 타입 하나, 출력 타입 하나**를 가지며, 엔진은 인자로 들어온다.

```text
ontologylab/
  pipeline/                # 정준 8단계. 각 파일 = run(input, deps) -> output
    source.py              # SourceSpec (allowlist가 유일한 outbound 게이트)
    acquire.py             # SourceSpec -> RawDocument[]        (ingest_item 하나)
    normalize.py           # RawDocument -> Work/Representation/Observation
    resolve.py             # Representation -> ResolvedEntities   (registry cache)
    extract.py             # Representation + Engine -> Proposal[] (+ span)
    synthesize.py          # Proposal[] + Engine -> Community/Expansion/MethodIR
    verify.py              # Proposal + HumanDecision -> Verified (+ receipts)
    publish.py             # Verified -> ImmutablePack (v2만)
  store/                   # 단계가 소유하는 테이블별 모듈 (KGStore 분할)
  engines/                 # Engine Protocol + 5 구현체 + resolve_engine() 하나
  consume/                 # 얇은 어댑터: cli.py, http/, mcp.py  (파이프라인 로직 없음)
  migrations/              # h1, v2 backfill. live 코드에서 import 금지
```

규칙:

1. `consume/` 밖의 어떤 모듈도 `get_engine`/`resolve_engine`을 호출하지 않는다. 엔진은 항상 인자다.
2. 단계 함수는 다른 단계 함수를 호출하지 않는다. 합성은 `pipeline/__init__.py`의 한 선형 함수에서만 한다.
3. `auto`라는 설정값은 없다. 부재는 typed unavailable이다.
4. `migrations/`와 `archive/`는 `pipeline/`·`store/`·`consume/`에서 import되지 않는다 (import-linter 규칙으로 고정).
5. 새 모듈은 위 디렉터리 중 정확히 하나에 놓이고, 그 단계의 입력·출력 타입을 바꾸지 않는 한 파이프라인 도식을 수정하지 않는다.

이 구조에서 §3의 슬롯 표는 `pipeline/<stage>.py`의 시그니처 자체가 된다: `extract.run(rep, engine=...)`, `synthesize.run(proposals, engine=..., algorithm=...)`, `publish.run(verified)`. "어디에 어느 엔진이 들어가는가"는 파일 목록으로 답해진다.

## 6. 결정 목록 (사용자 결정 필요)

| # | 결정 | 선택지 | 권고 |
|---|---|---|---|
| 1 | Method 서브시스템의 위치 | (a) Synthesize 슬롯 구현체로 흡수, 저장·팩·MCP는 공용 단계 재사용 (b) 별도 패키지로 격리·동결 (c) 현행 유지 | (a). 제2 파이프라인을 남기면 원칙이 성립하지 않는다. 다만 8,983 LOC이므로 D03·D05 이후에 착수 |
| 2 | legacy collect/shadow 경로 제거 시점 | `FULL_V2_AUTHORITY=True` 전환 후 즉시 / 다음 릴리스 | 즉시. Wave 2.1 Step 10까지 닫힌 상태에서 shadow는 이미 이중 쓰기다 |
| 3 | CLI `--engine` 기본값 | mock 유지 / 필수 인자 / `DEFAULT_ENGINE` | 필수 인자. mock은 명시적으로만 |
| 4 | orphan 12모듈 처리 | 삭제 / `archive/` / 유지 | 삭제. git 이력이 보존한다 |
| 5 | Pack v1 폐기 | 즉시 / v2 cutover 검증 후 | 즉시. 정규 진입이 v1만 만드는 현 상태가 더 위험하다 |
| 6 | `auto` fallback 정책 | 전면 제거 / embed·rerank만 유지 | 전면 제거 |
| 7 | `KGStore` 분할 순서 | Verify 먼저 / Publish 먼저 / 테이블 소유권 기준 일괄 | 테이블 소유권 기준으로 단계별 분할. 인터페이스는 유지하고 파일만 나누는 1차, 호출자를 단계로 옮기는 2차 |
| 8 | CLI/HTTP 공용 서비스 계층 도입 | 도입 / 현행 | 도입. D06 5쌍의 중복이 첫 대상 |

권고 착수 순서: D03(D04 포함) -> D02 -> D01 -> D06 -> D05 -> D10 -> D07 -> 나머지. 앞 넷은 흐름을 하나로 만드는 작업이고, 뒤는 그 위에서 모듈을 옮기는 작업이다. 순서를 바꾸면 분할한 모듈을 다시 옮기게 된다.

## 7. 본 문서는 제안이며 결정이 아니다

- 코드·테스트를 수정하지 않았다 (`evidence/design-review-20260826/no-code-change-G001.txt`, 최종 `no-code-change-final.txt`).
- 단계 귀속은 정적 import 그래프와 코드 읽기로 정했으며, 런타임 호출 빈도는 반영하지 않았다. 귀속 이견은 `stage-map.json`을 고치면 된다.
- "미도달"은 `main.py`·`server/app.py`·`mcp_server.py`의 정적 import 폐쇄 기준이다. `serve.py`·`tui.py`는 콘솔 스크립트 진입점이라 고아가 아니다.
- 선행 감사(2026-08-19)와 겹치는 항목은 그 번호를 병기했다. 본 보고서는 그 감사를 대체하지 않고, 단순성 원칙 기준으로 재정렬한 것이다.
