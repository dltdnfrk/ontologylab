# OntologyLab 풀스택 구현·리팩터링 로드맵

- 작성일: 2026-09-05
- 상태: **구현 전용 루프 G001-G008 완료 — 배포 제외**
- 조사 기준: `main`, HEAD `7f94879317ae25d956d6ae028587dacd19ff500e`와 현재 작업 트리.
- 요청 해석: 데스크톱 배포에 국한하지 않고 제품 전체를 계층별로 나눠, 구현 공백과 구조 개선을 함께 진행한다.
- 최초 조사 범위: 소스, LSP 정의·참조, 테스트 코드, 기존 계획과 프로젝트 지침.
  이후 사용자의 두 pane 분담 지시에 따라 구현과 테스트·빌드·브라우저 검증을 진행했다.
- 범위 정정: 사용자가 **“배포는 목표가 아님”**이라고 명시했다.
  현재 목표는 애플리케이션 구현·리팩터링·검증이다. 소프트웨어 서명·배포 후보,
  QA Mac 설치·업그레이드 매트릭스, 승격·외부 전달과 배포용 Task 15·16/F1–F4는
  종료 조건에서 제외한다. 지식팩 생성·Method 릴리스·MCP는 앱 내부 기능이므로 유지한다.
- 현재 실행 원장: `.omo/ulw-loop/ontologylab-implementation-only-20260905/ledger.jsonl`.
  이전 배포 포함 루프와 미완료 배포 목표는 이력이며 현재 구현의 선행 조건이 아니다.

## 1. 기준선과 우선순위

조사 시작 시 기존 수정·삭제 항목 99개, 미추적 항목 187개가 있었다. 이 변경을
기준선으로 보존한다. HEAD만으로 현재 구현을 설명하거나, 기존 변경을 되돌려
리팩터링을 시작하지 않는다. 이 문서는 기존 제품 명세나 완료 증거를 대체하지 않는다.

| 확인한 상태 | 로드맵에 반영할 판단 |
|---|---|
| `ontologylab/web/app.js` 6,466줄 | 화면 전체를 재작성하지 않고 기존 통신·렌더링·상태 경계를 정리한다. |
| `ontologylab/server/routes.py` 2,964줄 | HTTP 처리와 여러 진입점이 공유하는 작업을 분리한다. |
| `ontologylab/kgstore.py` 5,592줄 | 연결·트랜잭션 소유권을 먼저 고정하고 읽기 기능부터 점진적으로 분리한다. |
| `ontologylab/main.py` 2,203줄 | CLI 옵션과 종료 코드는 유지하면서 공통 작업의 기존 소유자를 재사용한다. |
| `ontologylab/connectors/paper_api.py` 2,155줄 | 공통 HTTP 경계와 소스별 URL·파서 책임을 구분한다. |
| `collect.py`, `ingestion_service.py`, `research_run.py`에 공통 서비스가 존재 | 같은 역할의 두 번째 수집·Research 서비스를 만들지 않는다. |
| `server/jobs.py:815`가 `run_research()`에 위임 | Research 서비스 추출은 새 작업이 아니라 유지해야 할 기준선이다. |
| `server/routes.py:2442`, `2449`, `2459`에서 채팅이 HTTP 핸들러를 직접 호출 | 검색·강화·팩 작업을 일반 함수 경계로 옮기는 것이 API 리팩터링의 출발점이다. |
| `server/routes.py:2460`에서 팩 생성 거절을 이미 `blocked`로 변환 | 이전 감사의 “거짓 성공”을 미수정 버그로 재등록하지 않는다. |

줄 수는 책임 집중을 찾는 참고값이지 완료 기준이 아니다. 파일을 작게 쪼갠 것만으로
개선했다고 판단하지 않는다.

제품 경계는 **로컬 우선·단일 사용자, Python 표준 라이브러리 코어, SQLite,
FastAPI, 패키지에 포함된 vanilla JS**다. 사람이 승인하는 지식 상태 전이,
verified-only 불변 팩, 읽기 전용 MCP를 모든 단계의 공통 계약으로 유지한다.

## 2. 계층별 구현 로드맵

### A. 프런트엔드·사용자 경험

- **대상:** `ontologylab/web/app.js`, `research-summary.js`, `chat-session.js`,
  `localize.js`, `ui-utils.js`, `index.html`, `style.css`.
- **구현 순서:** Research 계획·수집 결과·부분 실패·검토 대기·팩 생성 결과를
  기존 API 상태와 대조한다. 정상·빈 결과·부분 결과·거절·취소를 각각 사용자가
  구분할 수 있는 흐름으로 연결하고, 실제로 빠진 표시만 보완한다.
- **리팩터링:** `api`, `apiSend`, `errorText`, `throwIfRefused`의 서로 다른
  계약을 명확히 한다. 이미 분리된 요약·채팅·지역화·DOM 도우미를 재사용하고,
  확인된 순수 함수 경계만 이동한다. `app.js`는 화면 조립 진입점으로 유지한다.
  새 프레임워크·번들러나 탭별 전면 분리는 이 계획에 포함하지 않는다.
- **완료 기준:** 실제 브라우저에서 폼과 채팅의 성공·거절 결과가 일치하고,
  오류가 성공 표시로 바뀌지 않으며, 탭 이동·키보드 조작·좁은 화면에서도
  검토와 팩 연결을 끝낼 수 있다. 자산 변경 시 manifest 생성·검증도 통과한다.
- **기존 검증 연결:** `tests/test_ui_failure_honesty.py`,
  `tests/test_dashboard_assets.py`, `tests/test_dashboard_load_state.py`,
  `tests/test_research_ui_contract.py`.

### B. HTTP API·CLI·애플리케이션 작업

- **대상:** `ontologylab/server/routes.py`, `schemas.py`, `dependencies.py`,
  `app.py`, `ontologylab/main.py`.
- **구현 순서:** 팩 생성부터 API·채팅의 공통 작업과 각 응답 변환을 구분한다.
  다음으로 검색, 외부 레지스트리 강화 순서로 같은 작업을 적용한다.
  CLI가 이미 공통 함수를 쓰는 경우에는 추가 계층을 만들지 않는다.
- **리팩터링:** HTTP 핸들러끼리의 호출을 없애고, 핸들러는 입력 검증·의존성
  연결·응답 변환을 맡는다. 공유 작업 경계가 정리된 뒤에만 실제 도메인별
  `APIRouter` 분리를 진행한다. 기존 `ingest_routes.py`의 분리 방식을 참고한다.
- **완료 기준:** URL·HTTP 상태·JSON 계약·CLI 옵션과 종료 코드가 유지된다.
  로컬 세션 인증, 확인 전 변경 금지, 422 비밀값 제거, SQLite 잠금의 503
  응답을 실제 HTTP 요청으로 검증한다.
- **기존 검증 연결:** `tests/test_chat.py`, `tests/test_collect_service.py`,
  `tests/test_api_route_inventory.py`, `tests/test_local_api_auth.py`,
  `tests/test_route_error_disclosure.py`.

### C. 논문 수집·Research·LLM 추출

- **대상:** `collect.py`, `connectors/paper_api.py`, `research_run.py`,
  `research_plan.py`, `research_assessment.py`, `extractor.py`,
  `engine_requests.py`.
- **구현 순서:** 기존 ResearchSpec → 계획 → 수집 평가 → 추출 후 평가의
  연결을 기준으로 삼는다. 실문헌 검증에서 드러난 검색축·본문 확보·중복 처리·
  추출 공백을 각각 재현한 다음 보완한다. 평가값만으로 자동 승인하지 않는다.
- **리팩터링:** 소스별 파서를 공통 HTTP 경계와 분리하되 allowlist·오프라인
  차단·키 처리·부분 성공 계약을 유지한다. Research 상태 기계는 이미 공통
  소유자가 있으므로 크기만을 이유로 다시 분산하지 않는다.
- **완료 기준:** 같은 입력의 폼·채팅 실행이 같은 의미 계약을 보존한다.
  사용 가능한 소스 없음, 중복만 있음, 일부 수집·추출 실패, 예산 소진,
  취소가 구별되고 완료된 산출물·영수증이 남는다.
- **기존 검증 연결:** `tests/test_research_run_service.py`,
  `tests/test_research_parity.py`, `tests/test_research_evaluation.py`,
  `tests/test_post_extraction_assessment.py`, `tests/test_partial_chunk_failure.py`.
- **품질 판정:** MockEngine과 구성된 gold 자료는 회귀용이다. 실문헌 품질은
  고정한 원문과 별도로 검토한 기대 근거를 사용하며, 모델 자신의 평가나
  그래프 밀도만으로 “충분한 근거”를 주장하지 않는다.

### D. 데이터·지식그래프·사람 검토

- **대상:** `kgstore.py`, `ingestion_service.py`, `authority_repo.py`,
  `selection*`, `citation*`, `grounded_review*`, `review_decision*`.
- **구현 순서:** Work·Representation·Observation에서 제안·근거·검토까지
  각 쓰기의 소유자와 트랜잭션 범위를 정리한다. 이후 검색·읽기 변환부터
  분리하고, 검토 상태 전이는 별도 검증 단위로 진행한다.
- **리팩터링:** `KGStore`의 공개 진입점을 유지한다. 이미 존재하는 저장소
  모듈을 활용하고, 새 연결이나 이중 커밋 경계를 만들지 않는다. DB 스키마
  변경과 코드 이동을 한 단계에 섞지 않는다.
- **완료 기준:** 중복·식별자 충돌·부분 실패에서 저장 결과가 보존되고,
  검토 전 사실은 verified가 되지 않는다. 철회·재검토·무효화 이력과
  현재 유효한 사실의 구분이 검색·검토·팩에서 일치한다.
- **기존 검증 연결:** `tests/test_kgstore.py`,
  `tests/test_ingestion_service.py`, `tests/test_work_view.py`,
  `tests/test_grounded_review.py`, `tests/test_grounded_review_identity.py`.

### E. 팩·검색 제공·MCP

- **대상:** `packbuilder.py`, `pack_readiness.py`, `verified_pack_reader.py`,
  `pack_verifier.py`, `mcp_server.py`, `semantic_staleness.py`.
- **구현 순서:** 기존 `build_pack_release()`와 검증된 팩 읽기 경계를 재사용한다.
  API·채팅·CLI의 빌드 결과 처리부터 정리한 뒤, MCP 쿼리와 프로토콜 연결을
  구분하고 출처·기준 시점·변경 신호의 응답 계약을 확인한다.
- **리팩터링:** 빌드 권한, 직렬화·봉인, 읽기 검증, 전달 형식의 책임을
  구분한다. 이미 있는 검증기를 대체하거나 별도의 팩 성공 경로를 만들지 않는다.
- **완료 기준:** 미검증 사실 제외, 불완전 추출 거절과 명시적 예외 의도,
  변조 팩 거절, 읽기 중 무변경, 근거 추적이 실제 생성 팩과 MCP 표면에서
  확인된다. 모듈 import 성공을 MCP 프로토콜 검증으로 대신하지 않는다.
- **기존 검증 연결:** `tests/test_pack_completeness.py`,
  `tests/test_mcp_pack_integrity.py`,
  `tests/test_pack_authority_refusal_surface.py`,
  `tests/test_pack_v2_publication_surface.py`.

### F. Method 컴파일·릴리스

- **대상:** `method_store.py`, `method_compiler*`, `method_release*`,
  `method_pack*`, `method_mcp*`.
- **구현 순서:** 컴파일 → 사람의 릴리스 결정 → 팩 포함 → MCP 추적의
  기존 계약을 확인한다. 이 경로에서 재현된 중복·불일치만 별도 작업으로 고친다.
- **리팩터링:** 이미 분리된 SQL·저장·컴파일·전달 책임을 유지한다.
  일반 KG 리팩터링에 Method의 연결·트랜잭션 소유권 변경을 끼워 넣지 않는다.
- **완료 기준:** 컴파일 재현성, 승인된 릴리스만 출판, 원자적 실패,
  팩에서 원근거까지 추적이 유지된다.
- **기존 검증 연결:** `tests/test_method_store.py`,
  `tests/test_method_compiler.py`, `tests/test_method_release.py`,
  `tests/test_method_pack_atomicity.py`, `tests/test_method_mcp_surface.py`.

### G. 소프트웨어 배포 — 현재 범위에서 제외

사용자의 명시적 정정에 따라 macOS 배포·설치·업그레이드·승격·전달 작업은
이 구현 로드맵의 목표가 아니다. 기존 코드와 증거는 보존하되 배포 작업을
구현 완료의 선행 조건으로 삼거나, 배포가 완료됐다고 표시하지 않는다.

### H. 테스트·빌드·운영 관측

- **대상:** `tests/`, `.github/workflows/ci.yml`, `scripts/check_product_status.py`,
  애플리케이션·자산 manifest와 구현 검증 증거.
- **구현 순서:** 각 단계에 관련 회귀 테스트와 실제 진입점 시험을 연결한다.
  통합 지점에서 전체 suite·설치 패키지·제품 상태 검증을 실행한다.
  작업 ID에서 입력·상태 전이·산출물·오류로 이어지는 기존 추적을 유지한다.
- **리팩터링:** 고정 sleep 기반 검증은 사건 구독과 제한 시간으로 바꾼다.
  실제 저장소·HTTP·출고 JS를 시험하고, 구현 함수명이나 문구만 검사하는
  새 테스트는 만들지 않는다. 실패 테스트를 지우거나 완화하지 않는다.
- **완료 기준:** 바뀐 동작에 대한 고의 오류를 테스트가 잡고, 복원 후
  관련 명령이 한 번에 통과한다. 기존 실패와 이번 변경의 실패를 구분한다.
  증거 테스트를 수정하면 함수 AST와 모듈 SHA-256 두 연결을 함께 갱신한다.
- **주요 명령:** `uv run --all-extras pytest`,
  `python -P scripts/check_product_status.py --root . --document docs/PRODUCT_SPEC.md`,
  `node --check ontologylab/web/app.js`.
  자산 변경에는 `uv run python -m ontologylab.web_assets write-manifest`와
  `uv run python -m ontologylab.web_assets check`를 추가한다.
  이 목록은 실행 계획이며 통과 영수증이 아니다.

## 3. 실행 순서와 의존성

| 단계 | 산출물 | 선행 조건·종료 기준 |
|---|---|---|
| R0. 기준선 확보 | 기존 변경 목록, 관련 테스트 기준선, 보존할 외부 계약 | 첫 변경 대상이 정해지고 기존 실패가 분리돼야 다음 단계로 간다. |
| R1. 팩 생성 호출 경계 | 채팅과 폼이 공유하는 일반 작업 함수, 동작 보존 증거 | R0 후 진행. 아래 첫 실행 범위의 모든 검증을 통과한다. |
| R2. API·UI 경계 정리 | 검색·강화의 핸들러 간 호출 제거, 도메인 router와 기존 UI 도우미 책임 정리 | 작업 하나씩 닫는다. UI는 확정된 응답 계약을 사용한다. |
| R3. 데이터·팩·Method 내부 정리 | 읽기 경계, 트랜잭션 소유권, 출판·조회 계약 | R1–R2의 외부 동작을 기준으로 각 도메인을 따로 검증한다. |
| R4. 측정된 제품 공백 보완 | 실문헌에서 재현한 수집·추출·근거 표시 개선 | C의 독립적인 품질 판정과 비용·취소 계약을 통과한다. |
| R5. 구현 통합 검증 | 전체 구현 회귀, 로컬 빌드, 임시 환경 패키지 검증, 실제 기능 증거 | 최종 소스의 테스트·실사용·품질·범위·정리 증거가 일치하면 완료한다. 배포나 전달은 요구하지 않는다. |

H는 모든 구현 단계에 적용한다. 동일 파일의 리팩터링을 병렬로 진행하지 않고,
한 단계의 결과를 검증한 후 다음으로 간다. 빌드·임시 환경 패키지 확인은 구현
검증이며 사용자 환경에 설치하거나 배포하기 위한 작업이 아니다.

## 4. 첫 실행 범위 제안

**R0–R1: 팩 생성의 HTTP 핸들러 직접 호출 제거와 동작 보존.**

1. `server/routes.py:2459`의 채팅 → `packs_build()` 직접 호출을 일반 작업
   함수 경계로 바꾼다. 폼의 HTTP 핸들러와 채팅은 그 경계를 공유한다.
2. 기존 `packbuilder.py:853`의 `build_pack_release()`를 실제 빌드의
   공통 소유자로 유지한다. CLI는 이미 이를 호출하므로 CLI 전체 이동이나
   두 번째 팩 서비스를 만들지 않는다.
3. 응답의 `manifest`, `error_code`, `extraction_completeness`, 채팅의
   `kind=confirm/blocked/pack`, provenance와 아티팩트 등록을 보존한다.
4. 실제 임시 SQLite와 팩 디렉터리로 정상 생성·불완전 추출 거절·이름 충돌을
   HTTP 폼과 채팅 양쪽에서 확인한다. 미확인 채팅은 어떤 팩도 만들지 않아야 한다.
5. 관련 테스트, 변경 파일 진단, 실제 CLI·HTTP·브라우저 팩 생성 흐름을
   검증한다. 다중 파일 실행 코드 변경이면 패키지 빌드도 확인한다.
   새 동작 수정이 필요해지면 그 회귀의 RED를 먼저 관측하고 별도 변경으로 다룬다.

예상 변경은 `ontologylab/server/routes.py`, 필요한 공통 작업 경계와 관련
테스트로 한정한다. 이 단계에서는 KG 스키마·Method 상태 기계·Research
오케스트레이터·데스크톱 후보 바이트를 바꾸지 않는다. 사용자가 두 pane에 나눠
진행하도록 승인했으며, 실제 분담과 검증 상태는 아래 실행 기록에 남긴다.

## 5. 기존 계획과의 연결

- [제품 명세](PRODUCT_SPEC.md): 승인 권한·근거·시점·팩과 MCP의 제품 계약.
- [기존 M0–M8 로드맵](ROADMAP.md): 초기 구현의 이력. 미완료 작업 목록으로 재사용하지 않는다.
- [Research 서비스 구조 개선](../.omo/plans/ontologylab-architecture-hardening-roadmap.md):
  완료 표시와 현재 `run_research()` 위임을 확인했다.
- [의도에서 근거까지의 Research 계획](../.omo/plans/ontologylab-intent-to-evidence.md):
  기존 ResearchSpec·평가·산출물 계약의 기준이다.
- [온톨로지 플랫폼 계획](../.omo/plans/ontology-platform-roadmap.md):
  기존 의미·출판·검증 경계를 보존한다.
- [macOS 배포 계획](../.omo/plans/mac-desktop-deployment-roadmap.md):
  별도 이력으로 보존한다. 현재 구현 루프는 이 계획의 완료를 요구하지 않는다.

오래된 감사나 지침의 버그 설명은 현재 소스·테스트와 다시 대조해야 한다.
예를 들어 채팅 팩 생성 거절은 이미 처리되고, Research 서비스도 이미 분리돼 있다.
다음 구현은 새 완료 주장을 늘리기보다 남은 결합과 재현된 공백을 줄이는 데 집중한다.

## 6. 첫 병렬 실행 기록

Herdr workspace `wD`의 기존 두 pane만 사용했다. 같은 정본 작업 트리에서
파일 소유권을 분리하고, 자산을 읽는 백엔드 테스트는 프런트엔드의
`ASSETS_STABLE` 신호 이후에 실행했다.

| pane | 소유한 변경 |
|---|---|
| `wD:p18` | `server/routes.py`의 팩 생성 일반 작업 경계, `tests/test_chat.py`, 이 로드맵과 통합 검증 |
| `wD:p19` | `web/app.js`, `web/ui-utils.js`, 두 자산의 `index.html` 해시 URL, 자산 manifest, 관련 프런트엔드 테스트·바이트 해시 |

확인된 결과:

- 백엔드 기준선 56개 통과. 실제 SQLite를 사용하는 팩 생성·거절 회귀 2개를
  먼저 통과시킨 뒤, HTTP 핸들러와 채팅이 `_build_pack_result()`를 공유하도록
  분리했다. 실제 빌드는 기존 `build_pack_release()`가 맡는다.
- 백엔드 관련 검사에서 59개 통과, 기존 API 개수 단언 1개 실패.
  `tests/test_api_route_inventory.py:37`은 87개를 기대하지만 실제 등록은 88개다.
  이번 변경 전후 주 router의 86개 등록 문자열은 동일하다.
- 위 개수 단언은 변경하지 않았다. 실제 격리 HTTP 서버의 88개 등록 API와
  83개 고유 경로의 HEAD·OPTIONS 166요청이 모두 비인증 요청을 401로 거절했다.
- 팩 거절 분기를 고의로 반전시키자 실제 저장소 회귀가 `pack != blocked`로
  실패했다. 원상 복원 후 팩 회귀와 로컬 인증 테스트 12개가 통과했다.
- 프런트엔드 오류 처리 함수 분리는 최초 조합 189개 테스트를 통과했다.
  `ok:false`를 통과시키는 고의 오류는 실제 UI 쓰기와 브라우저/CommonJS 오류
  검사 7개가 검출했고, 복원 뒤 통과했다.
- 실제 브라우저에서 폼 팩 생성, 잘못된 이름의 필드 오류 표시,
  채팅 확인 전 무변경과 확인 후 팩 생성을 관측했다.
  추가로 채팅 성공 메시지가 `manifest.pack_id`를 읽지 않아 ID를 비워 두는
  오류를 재현했고, 같은 프런트엔드 pane에서 수정했다. 새 렌더링 회귀는
  수정 전 3개 실패·4개 통과, 수정 후 7개 통과였고 최종 프런트엔드 조합은
  196개 통과했다. 최종 서버에서 저장된 응답의
  `chat-pack-20260905-223532`가 실제 화면에 표시되는 것을 확인했다.
- 375·768·1280px 실제 브라우저에서 오류와 채팅 결과를 확인했다.
  좁은 두 화면의 문서 폭은 viewport와 같았으며 오류가 `[object Object]`로
  표시되지 않았다. 캡처는 이 세션의 브라우저 검증 출력에 첨부했다.
- CLI도 같은 격리 저장소에 `cli-two-pane-20260905-224000`을 생성했다.
  최종 소스로 wheel과 sdist를 다시 빌드해 모두 종료 코드 0을 확인했다.

검증 격리:

- QA 서버는 `127.0.0.1:18773`, 데이터는
  `/private/tmp/ontologylab-fullstack-20260905-p18` 아래에 둔다.
  저장소 아래 런타임 경로는 iCloud 경계 검사에 의해 거절돼 사용하지 않았다.
- 제품 증거 검사의 첫 실행은 고의 오류 주입과 겹쳐 `routes.py` 변경을 감지하고
  실패했다. 유효한 영수증으로 계산하지 않는다. 모든 수정이 끝난 뒤 단독
  재실행한 `uv run --frozen --all-extras python -P scripts/check_product_status.py
  --root . --document docs/PRODUCT_SPEC.md`는 canonical pytest 13개 통과,
  `PASS: 4 statuses, 9 paths`, 종료 코드 0으로 완료됐다.
- 이전 릴리스의 `release/source-snapshot.json`과 서명 후보는 갱신하지 않는다.
  배포는 현재 목표에서 제외됐으며, 해당 이력을 구현 완료의 게이트로 사용하지 않는다.
- QA 브라우저 3개와 소유한 QA 서버를 종료했다. 임시 데이터는 위의 명시적
  경로에 보존했으며, 라이브 서버나 기존 데이터·릴리스 바이트를 삭제하지 않았다.
- 전체 구현 R2–R5는 이 첫 실행 이후 계속 진행한다. 데스크톱 Task 15 이후는 제외한다.

최종 개발 빌드(`artifacts/fullstack-refactor-20260905/dist/`):

| 산출물 | SHA-256 |
|---|---|
| `ontologylab-0.1.0.tar.gz` | `ec41268ac7c31f08af46c78a1faa36f3201512719080a59103e2d7b7ebb6d9f2` |
| `ontologylab-0.1.0-py3-none-any.whl` | `d4a3580d3e415c9b398aacadce05ca32d390137140aaceba7b6b2766d6eca133` |

이 빌드는 개발 검증 산출물이며 내부 macOS 릴리스 승격을 뜻하지 않는다.

## 7. 구현 전용 루프 진행 기록

2026-09-06 기준 원장의 G001-G007의 21개 기준이 완료됐다. 첫 실행 기록과
그 당시 빌드는 위에 그대로 보존하며, 현재 증거는 다음 경로에 구분한다.

| 목표 | 완료한 범위 | 증거 |
|---|---|---|
| G001 | API 인벤토리 88개 기준선 수정, 인증 거절과 기존 팩 동작 검증 | [G001 증거](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G001-establish-a-faithful-current-baselin/) |
| G002 | 검색·강화의 공통 작업과 HTTP router 경계, 실제 HTTP·채팅 동작 보존 | [G002 증거](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G002-complete-r2-http-cli-action-boundari/) |
| G003 | 취소 거절과 부분 결과 표시, 검토 요청의 오래된 응답 차단, 키보드·좁은 화면·팩 연결 검증 | [G003 최종 영수증](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G003-complete-r2-frontend-state-boundarie/lead-final-browser-outcomes.json) |
| G004 | 기존 facade를 유지한 순수 SQLite 행 변환 분리, 중복·충돌·롤백·현재 사실·레거시 읽기 검증 | [G004 최종 영수증](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G004-complete-r3-data-kg-boundaries-map-a/lead-verification.json) |
| G005 | 기존 팩 책임 유지, MCP 문자열 배열 항목 검증, 실제 CLI·stdio·출처·변조·staleness 검증 | [G005 최종 영수증](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G005-complete-r3-pack-mcp-boundaries-reus/lead-verification.json) |
| G006 | CLI evidence 보존, 실패 COMMIT 정리, 실제 Method release·replay·팩·MCP 추적 검증 | [G006 최종 영수증](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G006-complete-r3-method-contract-checks-a/lead-verification.json) |
| G007 | 12개 source URL/parser 분리, 실제 문헌 연도·XML 후반·본문 재사용·query gate 수정, 14개 HTTP/채팅 경로 검증 | [G007 최종 영수증](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G007-complete-r4-acquisition-research-ext/lead-verification.json) |
| G008 | 회귀·설치 검증 통과, 375px 검토표 이름 가림(FI-001) 수정 후 재검증 완료 | [C001 회귀](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/C001-final-regression.json), [C002 설치](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/C002-installed-product-status.json), [최종 검토 판정](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/20-final-review-outcome.json), [FI-001 수정](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/22-identity-repair.json) |

G003에서는 실제 17개 검토 항목이 겹친 요청 뒤 `34 / 17`로 표시되는 오류를
재현했다. 요청별 세대와 지역 advisory 결과를 사용한 수정 후 같은 실 HTTP
재현은 `17 / 17`을 유지했다. 최종 프런트엔드 회귀 238개, 자산 9개 검증,
진단과 개발 빌드가 통과했다. 375·768·1280px 키보드 검증, 확인 전 무변경,
확인 후 실제 팩 ID·승인된 항목 수 표시도 확인했다.

검증용 브라우저와 서버는 종료했고 임시 데이터는 보존했다. 기존 dirty
트리의 선행 도우미가 HEAD에 없어 독립적으로 빌드 가능한 변경만 커밋할 수
없었으므로, 관련 없는 선행 변경을 섞어 커밋하지 않았다.

G004는 세 행 변환만 `kg_records.py`로 옮겼다. 역변환한 전체 `kgstore.py`
바이트와 원본이 일치했고 보호 파일 25개도 그대로였다. 외부 `ingestion.py`
호출 때문에 정적 facade를 유지했다. 최종 154개 회귀, 실제 SQLite의 식별자
충돌·호출자 롤백·명시적 승인·무효화와 레거시 읽기 무변경, 실제 HTTP 검색·
검토 일치를 검증했다. 개발 빌드도 통과했고 검증 서버는 종료했다.

G005는 이미 분리된 출판·검증·스냅샷 책임을 유지했다. 실제 MCP에서 잘못된
배열 항목 18건이 사전 거절되지 않는 것을 확인하고 기존 스키마·검증 함수만
보완했다. 수정 후 모두 `-32602`로 거절됐으며 정상 호출은 유지됐다. 실제
CLI의 미완료 추출 거절·명시적 override, 변조 팩 거절과 기존 활성 팩 보존,
출처 ID·span 연결, 승인된 사실 추가에 따른 staleness 변화도 검증했다.
392개 회귀와 개발 빌드가 통과했고 원본 팩 바이트는 그대로였다.
변경하지 않은 MCP 반환 타입 지점의 worker/lead 진단 차이는 별도로 기록했다.

G006은 fragment-import가 전달된 evidence를 버리던 오류와 COMMIT 실패 뒤
연결에 트랜잭션이 남던 오류만 기존 소유자 안에서 수정했다. 실제 CLI의
RED/GREEN, 동일 입력 DB 두 개의 독립 replay, 선택된 Method 릴리스의 팩 게시와
실제 MCP 도구·resource의 원문 span·승인 영수증 연결을 검증했다.
9개 컴파일 게이트, 330개 최종 회귀와 개발 빌드가 통과했으며 사람 결정과
원본 팩 바이트는 그대로였다. MCP는 종료했고 소유한 임시 데이터는 보존했다.
기존 테스트 함수 21개와 보호 항목 593개의 원문·해시·부재 상태를 보존했다.
CLI 패치는 HEAD 문맥에 적용되지 않으며 UoW 패치는 적용되지만 독립 HEAD
빌드·테스트는 검증하지 않았으므로, 선행 dirty 변경을 섞거나 커밋하지 않았다.

G007은 12개 source family의 URL/parser를 7개 leaf로 분리하고 기존 HTTP·인증·
registry·harvest·Research 소유자를 유지했다. 실제 문헌의 EPMC 연도 누락,
특수 harvest의 빈 query 통과, 새로 생긴 본문 링크의 cache 누락, PubMed inline
태그 뒤 초록 손실을 각각 RED/GREEN과 변이로 검증해 수정했다.
527개 회귀와 빌드, 7가지 상황의 direct/chat 14개 실제 HTTP·SSE·브라우저 경로,
16개 캡처가 통과했다. 소유한 서버·포트·탭은 종료했고 실패한 QA 시도도 보존했다.

G008은 SVG 패키징 누락, 활성 WAL을 읽는 앱 시작 경계, frozen 예외의 traceback
손실과 child 진단 누락을 수정했다. 구식 구조·문구 단언은 실제 팩 생성,
온톨로지 전환, 엔진 선택, 명시적 페이지네이션 계약으로 바꿨다.
Research의 비기본값 테스트 두 개는 현재 오프라인 기본값과 같던 `mock` 대신
다른 명시 입력을 사용하며 기존 12개 값의 전달 단언을 유지한다.

최종 native pytest는 **4,050개 통과, 기존 skip 2개·xfail 2개, 배포 범위 제외
6개**로 종료됐다. JUnit 결과 4,054개를 수집 목록과 정확히 대조했고 테스트·빌드·
제품 상태 검사 중 소스 변경은 없었다. 제품 상태 검사는
`PASS: 4 statuses, 9 paths`와 종료 코드 0을 기록했다.

격리 wheel의 CLI 수집·추출·사람 승인·팩 생성, 88개 API의 비인증 254요청,
활성 WAL 시작의 DB 내용 보존, 실제 graph/Method MCP의 출처·잘못된 입력 거절·
팩 무변경을 검증했다. Research 7상황의 direct/chat 14경로와 설치 UI의
375·768·1280px 키보드 페이지네이션을 재검증하고 실제 PNG 29장을 보존했다.
기존 상태바 요약은 30초 주기 표본이며, 모든 조작 직후 동기 갱신된다고
주장하지 않는다.

| 최종 개발 검증 산출물 | SHA-256 |
|---|---|
| `artifacts/impl-g008-final-20260906/dist/ontologylab-0.1.0-py3-none-any.whl` | `5d4dadea896be97a48722d8860a524e9d757e4bc4c8f6c6fd4f20937f5779404` |
| `artifacts/impl-g008-final-20260906/dist/ontologylab-0.1.0.tar.gz` | `f9cf495c9a77380bd30b20e53bd40367f3edefe4664bb703c12050ec655b7c5d` |

검증 서버·브라우저·MCP·DB 연결은 닫았고 임시 데이터와 실패한 검증 시도는
보존했다. 라이브 서버·Application Support 데이터·기존 릴리스 영수증은
변경하지 않았으며 커밋·배포·전달은 수행하지 않았다.

실제 native aggregate `1573f620266450d6`은 사용자에 의해 `paused` 상태다.
이를 재개하거나 완료로 바꾸지 않았다.

최종 독립 검토가 지적한 `FI-001`은 실제 브라우저 측정으로 확인하고 수정했다.
`table-layout: fixed`에서 폭이 지정된 열은 1·2·4·5뿐이어서 이름·등록·작업이
남은 폭을 3등분했고, 좁은 컨테이너에서는 그 나머지가 0에 수렴했다. 실측값은
375px에서 이름 열 **0px**(내용 269px), 768px 121px, 1280px 인스펙터 58px이었다 —
사람이 승인 대상을 목록에서 식별할 수 없는 상태다.

`등록 72px`·`작업 160px`을 명시해 이름 열만 유연하게 남기고
`#proposals-table`에 `min-width: 780px`을 주어 이름 열이 어느 폭에서도 **218px**을
유지한다. 넘치는 가로 폭은 기존 `#tab-review .table-scroll`이 그대로 소유하며,
JS·검토 상태·페이지네이션 소유자와 HTML 구조는 바꾸지 않았다. 자산 manifest와
`index.html` 해시 URL, 고정 자산 항목을 함께 갱신했다.

수정 후 같은 드라이버 재측정에서 375·768·1280px 모두 이름 열 218px,
문서 폭은 viewport와 동일, 50→100→120 고유 ID와 소진된 `더 보기` 숨김이
유지됐다. 실제 PNG 12장(수정 전 6·후 6)을 보존했다. 새 계약 테스트
`test_review_identity_column_keeps_a_readable_floor_at_every_width`는 수정 전
스타일시트를 자산 seam에 주입하면 실패한다(검출 1건).

재검증: native pytest **4,051개 통과**, 기존 skip 2·xfail 2, 범위 제외 6,
수집 4,061 − 제외 6 = 선택 4,055가 JUnit 4,055와 정확히 일치했다. 빌드는
봉인된 20260906 산출물을 그대로 둔 새 경로에 만들었고, 직렬화된 제품 상태
검사는 다시 `PASS: 4 statuses, 9 paths`와 종료 코드 0을 기록했다. 검증 중
소스 변경은 없었다.

| 재검증 산출물 (`artifacts/impl-g008-final-20260907-r2/dist`) | SHA-256 |
|---|---|
| `ontologylab-0.1.0-py3-none-any.whl` | `b9cb7346da607d176ad431a7f7ef911ca687c843ca2ce91f58276763488ecb60` |
| `ontologylab-0.1.0.tar.gz` | `22f014e8d0ff624cac4825d7d004124afc4f99586bdf15aff147ec791ec02814` |

이전 /private/tmp의 G008 fixture 경로가 더 이상 존재하지 않아
설치 여정을 그 자리에서 다시 열 수는 없었다. 삭제 원인은 확인하지 않았으며,
운영체제 정리라는 기존 설명은 확정 사실로 사용하지 않는다. 자산 관련 주장은 suite 자체가
독립 환경에 wheel을 설치해 검증하는 테스트로 다시 확인했다. 검증 서버·브라우저는
종료했고 임시 데이터와 실패한 검증 시도는 보존했다. 라이브 서버(8799)와
Application Support 데이터는 건드리지 않았다.

후속 검토의 `FI-001-R1`은 가로 스크롤의 실제 조작 증거가 없다는 지적이었다.
제품 소스 변경 없이 native 휠로 초기 관계 행과 완료된 개념 행에서 각각
375px은 `0→479→0`, 768px은 `0→86→0`, 1280px은 `0→275→0` 이동을 검증했다.
오른쪽 끝 열·버튼의 가시 영역과 hit-test, 돌아온 이름의 텍스트 영역, 문서 폭,
50→100→120 페이지네이션을 확인하고 PNG 12장을 추가했다. 버튼 클릭이나 모든
스크롤바 상태의 마지막 행 접근까지 검증한 것으로 확대하지 않는다.
보완 검토는 **APPROVE**로 마지막 기술 지적을 닫았다:
[가로 스크롤 증거](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/26-horizontal-scroll-acceptance.json),
[독립 검토](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/worker-horizontal-scroll-review.json),
[기술 승인 기록](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/27-final-technical-acceptance.json).

native `1573f620266450d6`의 일시정지는 이전 피어 세션의 이력이다. 사용자가
피어를 재시작한 뒤 직접 조회에서는 현재 목표가 없었고, 동일한 기존 계획의
목표 내용으로 native 추적을 재연결했다. 이전 기록을 재작성하거나 새 작업
계획·에이전트·세션을 만들지는 않았다:
[목표 연결 기록](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/28-native-goal-binding.json).

문서 정정을 반영한 실제 native 완료 감사가 통과했고, 현재 연결된 목표는
`complete`가 됐다. 최종 품질 게이트를 제출한 G008 체크포인트도 종료 코드 0으로
완료돼 **8개 목표와 24개 기준이 모두 완료**됐다. 첫 문서 감사 차단과 증거 경로
검증 거절은 이력으로 보존했으며, 후자는 같은 attempt의 요구 경로에 증거 20개를
동일 바이트로 배치해 해결했다. 재실행한 것처럼 실행 시점이나 내용을 바꾸지 않았다.

- [실제 native 완료](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/native-goal-complete-r1.json)
- [최종 체크포인트](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/30-final-checkpoint.json)
- [전체 구현·검증 보고서](../.omo/ulw-loop/ontologylab-implementation-only-20260905/evidence/G008-finish-implementation-only-integrati/lead-verification.json)

native 도구가 반환한 사용량은 재연결된 목표 기준 158,382토큰이다. 목표 ID와
경과시간은 반환되지 않아 만들지 않았다. 소프트웨어 배포·승격·전달은 이 완료에
포함하지 않는다.
