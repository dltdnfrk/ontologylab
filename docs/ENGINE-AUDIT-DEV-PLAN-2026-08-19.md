# OntologyLab 개발 계획 — 3-way 적대적 감사 합집합 기반

- 작성: 2026-08-19
- 입력: `docs/ENGINE-PIPELINE-AUDIT-2026-08-19.md` (omo), `...-GJC-...` (GJC), `...-PRIME-AGENT-...` (prime-agent), `evidence/3way-engine-audit-comparison-2026-08-19.md`
- 원칙: 어느 한 보고서만으로는 안 보이는 항목까지 전부 커버한다. 출처 열 = 어느 감사가 잡았는지 (o=omo, g=GJC, p=prime).
- 수용 기준 공통: 이 리포의 검증 표준은 커버리지가 아니라 **뮤테이션**이다. 모든 수정은 (a) 먼저 실패하는 테스트, (b) 뮤턴트로 회귀 증명. prime의 런타임 뮤턴트 기법이 표준 수용 절차다.

## Wave 0 — 당일 quick kills (전부 독립, XS~S)

| # | 항목 | 출처 | 증거 | 수용 |
|---|------|------|------|------|
| 0.1 | `ExtractRequest.engine` 기본값 `"mock"` 제거 — DEFAULT_ENGINE(claude) 또는 필수화 | o,g,p | `server/schemas.py:61` | engine 생략 요청이 mock으로 가던 테스트 RED→GREEN |
| 0.2 | 리서치 전원 실패 = `failed` + UI 배너 정직화 | o | `jobs.py:853`,`:658`, `app.js:2395`; 거짓을 핀 `test_research_source_surface.py:121` 수정 | 뮤턴트(전원실패) 시 UI/상태 테스트 실패 확인 |
| 0.3 | embedder `auto`에 `HF_HUB_OFFLINE=1` 캐시-온리 (reranker와 동일 계약) | o | `embeddings.py:169` vs `rerankers.py:66` | 캐시 없음 → hash-v1 폴백 테스트 |
| 0.4 | 채팅 팩 빌드 `built["ok"]` 검사, 실패 시 `kind:"blocked"` | o | `routes.py:2176`, `app.js:4826` | ok:false 시 성공 말풍선 미표시 테스트 |
| 0.5 | `/api/collect`의 `str(exc)` 와이어 누출 차단 (jobs와 동일 규칙) | o,p | `routes.py:1747` | 오류 본문 타이핑 테스트 |
| 0.6 | 문서 정합: ARCHITECTURE §7/§12 구형 주장(5소스/1500토큰/mock-everywhere/풀텍스트 계획) 갱신 | o,g | `docs/ARCHITECTURE.md:496-542`,`:751-772` | QA-by-read |

## Wave 1 — 신뢰 불변식 (가장 위험, 의존성 없음, 병렬 가능)

| # | 항목 | 출처 | 증거 | 수용 |
|---|------|------|------|------|
| 1.1 | 리뷰 상태 머신: `approve`/`reject`를 conditional UPDATE(`WHERE status='proposed'`)로; cascade가 rejected endpoint 승격 금지; BEGIN IMMEDIATE 트랜잭션 | o,p | `kgstore.py:2723-2824` | 불법 전이 뮤턴트 6종(rejected→verified 등) 전부 실패 |
| 1.2 | 모든 named-pack 읽기를 `_verified_pack` 경유로 통일 (`resource_*`, `get_staleness`) + 무결성 테스트의 resource_* 제외 조항 삭제 | o,p | `mcp_server.py:708`,`:475`, `test_mcp_pack_integrity.py:91` | 변조 팩을 resource가 읽으면 실패(prime이 실연한 반례를 테스트로) |
| 1.3 | 팩 리시트를 트리 다이제스트로 (manifest/schema/provenance 포함), `scan_packs`가 servable만 표시 | o,p | `packbuilder.py:608`,`:857` | manifest 변조 뮤턴트 실패 |
| 1.4 | invalidated-edge 누수 봉쇄: `counts()`, `document_review_context`, `evaluation.py`, `competency.py`에 `_edge_current_sql` | o | `kgstore.py:3988`,`:4061`, `evaluation.py:179` | 무효화 엣지가 카운트/평가에 섞이는 테스트 RED→GREEN |
| 1.5 | 추출 증거 게이트 강화: spanless endpoint 합성 금지 또는 ungrounded 큐 격리, substring grounding을 whole-token으로, entity property type/required/pattern 검증 | p,o | `extractor.py:421-552`,`:241-267`,`:445-467` | prime의 반례(CAT→concatenate 등)를 negative 테스트로 |
| 1.6 | alias 권한: proposed alias는 identity 키로 안 씀; 공유 alias는 `LIMIT 1` 임의 해소 금지 → merge candidate로 | p,o | `kgstore.py:2516`,`:2612` | ambiguous alias 런타임 반례 테스트 |
| 1.7 | ontology apply 원자성 + stale source 재검증 | p | `proposals.py:1001-1158` | mid-apply 실패 롤백 테스트 |

## Wave 2 — 수렴 (Wave 1 완료 후; 1.1/1.4와 코드 영역 겹침 주의)

| # | 항목 | 출처 | 증거 | 수용 |
|---|------|------|------|------|
| 2.1 | 단일 ingestion 서비스: CLI/route/research job이 한 함수 공유. fulltext 재작성 시 `source`/`evidence_grade` 보존, DOI 컬럼 + dedupe, collect route provenance, CLI `data_dir` 전달 | o,p,g | `fulltext.py:176-188`, `routes.py:1777`, `main.py:487`, `base.py:94` | provenance 손실 뮤턴트 실패 |
| 2.2 | 리뷰 큐 critic join 스트림 스코핑 + `(engine, model, prompt_version)`을 재채점 PK에 | o | `kgstore.py:3584`, `critic.py:173` | critic 스위치 후 옛 점수 정렬 금지 테스트 |
| 2.3 | conformal/calibration 제품 연결 또는 API 강등 (큐 배지/정렬 컬럼) | o,g,p | `routes.py:380`,`:398`; UI 미호출 | 연결 시 UI가 τ를 렌더, 강등 시 주석/문서 정합 |
| 2.4 | retrieval capability receipt: 팩 매니페스트에 coverage·모델 동질성·rerank/커뮤니티 알고리즘 기록; `embedding_model()` LIMIT-1 제거, cosine 차원 가드 | o,p | `kgstore.py:4680`, `packbuilder.py:633-650` | 부분 커버리지 팩이 hybrid로 표시되지 않음 테스트 |
| 2.5 | `GET /api/communities`를 팩 읽기로 바꾸거나 탭 제거 | o | `routes.py:1092` (주석이 스스로 인정) | 빌드 후 탭이 데이터 표시, 또는 탭 삭제 |
| 2.6 | settings `data_dir`/`packs_dir`를 읽기 전용 echo로 (또는 실제 재배치 구현) | o | `schemas.py:146-148`, `app.js:5178` | 저장해도 라이브 경로 안 바뀜을 명시 테스트 |
| 2.7 | `<query-expansion>` 마커 충돌 해소 (searchquery 전용 마커 + mock formulator) | o | `searchquery.py:64`, `engines.py:511` | mock이 검색어 구성 반환 테스트 |
| 2.8 | `_merge_mention`에서 registry 소유 키는 setdefault 대신 교체 | o | `kgstore.py:2646` | 나중 캐시 히트가 `no_eppo_match`를 정정 테스트 |

## Wave 3 — method 서브시스템 정리 (독립 진행 가능)

| # | 항목 | 출처 | 증거 | 수용 |
|---|------|------|------|------|
| 3.1 | 이중 스키마 해소: 컴파일러가 `MethodIR`을 emit해 `parse_method` round-trip, 또는 typed IR을 릴리스 경로에서 제거(택일을 기록) | o | `method_compiler_artifacts.py:186`, `method_ir_codec.py:863` | round-trip 테스트 |
| 3.2 | 게이트 의미 정직화: G5가 실제 contradiction을 검사, G7은 "static competency"로 개명하거나 실 replay로 | p | `method_compiler_gates.py:415-427`, `method_compiler_replay.py:101-125` | prime의 G5/G7 반례를 테스트로 |
| 3.3 | dead code 삭제: `g8()`, `fail_extraction_run` 3계층, workspace status 미사용 값, `gate-g8-integrity.json` | o(2개 에이전트가 독립 확인) | `method_compiler_gates.py:497`, `method_extraction_store.py:335`, `method_snapshot.py:214` | 삭제 후 스위트 그린 |
| 3.4 | method 애플리케이션 서비스 + 웹 표면(릴리스 선택, `/api/method/*`) 구축 또는 제품 서사에서 명시적 제외 | o,g,p | `routes.py`/`app.js`에 부재 | 구축 시 e2e; 제외 시 문서 정합 |
| 3.5 | `test_method_pack_mutation_contract.py` 문자열 pin → 동작 뮤턴트로 교체 | g | 테스트 파일 자체 | 뮤턴트에 실패 확인 |
| 3.6 | gap-class 어휘 정합 (`unreachable_result` vs `unreachable_step_or_result`), 두 `MethodPackSql` 개명 | o | `method_gaps.py:308`, `method_ir_codec.py:36` | re-parse 테스트 |

## Wave 4 — 구조 (기능 정리 후; 대형)

| # | 항목 | 출처 | 수용 |
|---|------|------|------|
| 4.1 | `kgstore.py` 분할 — 배너 시맴대로 ontology-terms/review-presentation/panels/embed-search를 모듈로, KGStore는 파사드 | o, explore | 스위트 그린 + 회귀 없음 |
| 4.2 | `_run_intent` 서비스 함수 분리 후 `routes.py`를 배너대로 라우터 분할 | o | AST 가드 테스트 유지 |
| 4.3 | `web/app.js` 모듈 분할 (기존 심: chat-session/localize/ui-utils) | o | `node --check` + 시각 QA |
| 4.4 | `main.py` 커맨드 모듈 분할, `paper_api.py` 소스 어댑터/HTTP 시맵 분리 | explore | CLI 스모크 |

## Wave 5 — 상설 게이트: 뮤테이션 매트릭스 (prime의 12종을 CI 아티팩트로)

provenance 누락, DOI 중복, spanless endpoint, wrong property type, substring grounding, CAS 오류 체크섬, 공유/proposed alias 권한, 불법 리뷰 전이, stale ontology source + mid-apply, node/edge 단독 conformal·calibration, 부분 임베딩 커버리지, MCP resource 해시 우회, G5 contradiction-only, G7 static-only, SSE source 갱신 누락.

각 Wave 항목 머지 조건: 대응 뮤턴트가 RED를 보인 뒤 GREEN.

## 의존성/순서 근거

- Wave 0는 전부 독립 — 즉시 착수, 병렬 가능.
- Wave 1이 불변식이라 최우선. 1.2↔1.3(팩 경계), 1.5↔1.6(추출 신원)은 같은 파일이라 순차.
- Wave 2.1은 Wave 1.5/1.6 이후(추출 게이트가 단일 서비스의 출력 계약을 결정).
- Wave 3은 본선과 무관해 병렬 가능하나 3.1(스키마 택일)이 3.4(표면)를 선행.
- Wave 4는 기능이 안정된 뒤에 — 먼저 쪼개면 Wave 1-3의 뮤테이션 증명이 재작성됨.

## 결정됨 (2026-08-19, 사용자 승인)

1. **3.1 → B**: typed IR을 릴리스 경로에서 제거(또는 import 전용으로 강등). 컴파일러 출력이 곧 계약.
2. **2.3 → 자동 승격**: conformal/calibration을 UI에 수동 배선하지 않는다. 대신 큐 로드 시 `/api/review/triage`·`/api/review/calibration`을 읽고 `available`(거절 ≥19건 / 리뷰 ≥20건)이 되는 순간 배지·정렬이 자동으로 켜지는 데이터 임계값 스위치로 구현한다. 수학이 보장을 만들 수 있을 때만 표시되는 것이 정직한 형태.
3. **3.4 → B**: method는 CLI/MCP 전용으로 명시. 웹 표면은 실사용 corpus가 생기면 승격.
4. **추출 기본 엔진 → 4-A**: mock는 dev/test 전용. API 기본값은 settings의 `default_engine`(=claude)을 따른다.

이 결정으로 Wave 3의 대형 항목(3.1-A, 3.4-A)은 보류되고, Wave 3는 3.1-B(IR 정리), 3.2, 3.3, 3.5, 3.6으로 얇아진다.
