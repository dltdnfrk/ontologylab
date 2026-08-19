# OntologyLab 엔진 파이프라인 적대적 감사 보고서 (omo pane)

- 작성일: 2026-08-19
- 대상: `main` @ 22c65dd (+ 언커밋 없음, 시맨틱 티어 활성화 상태)
- 방법: 8개 파이프라인 레인 병렬 적대적 리뷰(읽기 전용, file:line 증거 의무) → 리드 직접 독립 검토 → 교차비평
- 교차비평 경위: 위임 비평 노드는 프로바이더 라우트 장애(GPT-5.6 Sol `not_found` → Grok `Connection error`)로 2회 연속 실패. 이에 리드가 최날카로운 주장 12건을 대상 코드에서 직접 검증해 전부 유지를 확인했다(아래 ★표시). 구조적 디베이트(8레인 vs 검증자)는 유지, 검증 주체만 대체됨.

## 총평

**빈껍데기(HOLLOW) 엔진은 없다.** 8개 단계 전부 실제 동작하는 구현이다. 과거의 자기 평가("빈껍데기")는 이번 감사로 기각된다. 남은 문제는 부재(absence)가 아니라 **정직성 균열** 세 종류다:

1. **문서/주장이 코드를 앞서는 경우** — ARCHITECTURE의 구형 수치, 테스트 docstring의 과장 주장
2. **불변식의 불완전 적용** — invalidated edge가 일부 읽기 경로로 샘, 팩 해시 검증이 load 경로에만 있음
3. **기본값/상태의 거짓 신호** — mock 기본 엔진, 전원 실패 리서치의 "완료" 표시

## 파이프라인별 판정

### 1. Intake (수집) — REAL
12개 소스 디스패치, 팬아웃, 중복 제거, allowlist, provenance 모두 실재(`paper_api.py:1192`, `allowlist.py:188`).
- THIN: `registry_lookup.py:69`가 allowlist/공유 HTTP 시맵을 우회하는 유일한 intake 경로 ★
- THIN: 429/재시도/백오프 부재 (`paper_api.py:1555`)
- THIN: DOI는 메모리 내 dedup뿐, DB 컬럼 없음 (`kgstore.py:214`)
- THIN: CLI collect 경로는 팬아웃·fulltext 없음 (`main.py:487`)

### 2. Extraction (추출) — REAL
청킹→프롬프트→파싱→스키마 검증→span 검증→부분실패 라이프사이클 실재(`extractor.py:49-863`).
- **THIN (최대 위험): `ExtractRequest.engine = "mock"`** — CLI/settings 기본은 `claude`인데 API 기본값만 mock. 엔진 생략 요청이 실문서에 CamelCase 스캔을 돌림 (`schemas.py:61` vs `paths.py:20`) ★
- THIN: CLI가 `chunk_failed`를 무시하고 exit 0 "완료" (`main.py:628-641` vs `jobs.py:654`)
- THIN: fence 파서 뮤테이션 테스트 부재(첫/마지막 fence, bare fence) (`engines.py:72-92`)
- THIN: gold 픽스처 전부 constructed — mock 오라클을 품질 증거로 쓰지 말 것

### 3. Identity/Store (정규화·ER·kgstore) — REAL
레지스트리 우선 정규화(모델 출력을 증거로 안 침), 머지 사람 게이트 실재.
- THIN: **invalidated edge 누수** — `counts()`(`kgstore.py:3988`), `document_review_context`(:4061), `evaluation.py:179`, `competency.py:536`이 `_edge_current_sql` 미적용 ★
- THIN: insert-time "해상도"는 exact-key dedup뿐; alias probe 없음, 공유 alias는 LIMIT 1 비결정 (`kgstore.py:2483`, `:2612`)
- THIN: `_merge_mention` fill-absent가 첫 언급의 identity 필드를 동결 (`:2646`)
- THIN: `semantic_search`라는 이름의 BM25 (`:4558`) — 이름이 거짓
- 구조: kgstore.py 5172줄 = 4개 모듈 분량의 god-object

### 4. Review/HITL — 결정 경로 REAL, 트리아지 표면 HOLLOW
승인/거절/무효화는 사람만 가능하고 critic 경계는 코드로 확인됨.
- **HOLLOW (제품 표면): conformal/calibration** — 수학은 REAL(검증됨)이나 `/api/review/triage`, `/api/review/calibration`을 UI가 호출하지 않음. "큐를 정렬하고 배지한다"는 주석이 무근
- THIN: 큐의 critic join이 `MAX(created_ts)`뿐 — 스트림(engine/model/prompt_version) 필터 없어 critic 교체 후에도 옛 점수로 정렬 (`kgstore.py:3584`) ★
- THIN: `approve`/`reject`가 현재 상태 무시 (`_set_status` 베어 UPDATE, `kgstore.py:2816`) ★ — rejected→verified 직행 가능
- THIN: critic 재채점 키에 model 없음 (`critic.py:173`)

### 5. Retrieval (검색) — REAL
하이브리드(FTS5+벡터 RRF+리랭커), 모델 불일치 가드, 오프라인 리랭커 실재. 시맨틱 티어는 금일 MiniLM으로 활성화됨.
- THIN: **embedder `auto`는 오프라인 강제 없음** — reranker만 `HF_HUB_OFFLINE` (`embeddings.py:169` vs `rerankers.py:66-79`) ★ — 쿼리 경로가 홈을 전화할 수 있음
- THIN: `<query-expansion>` 마커 충돌로 mock은 검색어 구성 불가 (`searchquery.py:64` vs `engines.py:511`)
- THIN: `embedding_model()`이 LIMIT 1 — 혼합 모델 스토어를 거짓 보고 가능 (`kgstore.py:4680`)
- THIN: `cosine`이 차원 불일치를 zip 절단 (`embeddings.py:88`)

### 6. Pack/Serve — REAL
빌드 게이트, 원자적 리네임, SHA-256 영수증, 변조 거부(hmac compare) 실재.
- THIN: **`resource_*` 읽기가 해시 검증 우회** (`mcp_server.py:708`) ★ — `load_pack`만 검증. 무결성 테스트 docstring이 "모든 named-pack 읽기 검증"이라 주장하면서 resource_*를 제외 — **빈껍데기 테스트 주장** (`test_mcp_pack_integrity.py:91`)
- THIN: `scan_packs`가 해시/dir==pack_id 미검사 — "usable" ≠ "servable" (`packbuilder.py:857`)
- THIN: `pack.sqlite`만 해시 — manifest/schema/provenance는 재작성 가능 (`packbuilder.py:608`)
- THIN: `diff_packs`의 `identical`이 manifest 주장을 신뢰 (`packdiff.py:155`)

### 7. Method 서브시스템 — REAL, 과잉 구축
컴파일→릴리스→팩→MCP 전주기 실재(소비자: CLI `cmd_method`, MCP, packbuilder, kgstore).
- **구조 결함: 이중 스키마** — 컴파일러는 느슨한 dict를 emit하고 typed `MethodIR`로 round-trip하지 않음. IR 코덱 1002줄이 import 전용 방언 (`method_compiler_artifacts.py:186` vs `method_ir_codec.py:863`)
- HOLLOW: `g8()` 정의됐으나 미호출(`method_compiler_gates.py:497`), `fail_extraction_run` 호출자 0(`method_extraction_store.py:335`), workspace status는 영원히 `"draft"` ★ (`method_snapshot.py:214`)
- HOLLOW: authoring UI/LLM fragment 추출기 부재 — 아키텍처가 약속한 것 중 여기만 진짜 빈껍데기
- 31파일/9k줄 — 프로토콜 샌드위치 과잉

### 8. Server/Jobs/UI — REAL, 거짓 신호 다수
60+ 엔드포인트, 실패 타이핑, 보안 모델(loopback+Host/CSRF) 실재.
- **HOLLOW (기능): `GET /api/communities`** — 워킹 DB를 읽지만 rows는 팩 안에만 있음. 엔드포인트 주석 스스로 인정 (`routes.py:1092`) ★
- **거짓: 리서치 전원 실패 → `status=complete` + "리서치 완료!" 배너** (`jobs.py:853` + `:658`, `app.js:2395`) ★ — 테스트가 이 거짓을 핀 (`test_research_source_surface.py:121`)
- 거짓: 채팅 팩 빌드는 `ok:false`여도 "팩 만들었다" 말풍선 (`routes.py:2176`, `app.js:4826`)
- THIN: `_run_intent`가 FastAPI 핸들러를 직접 호출 — Query 객체 함정은 현재 kwargs 규율+AST 테스트로 봉쇄됐으나 구조는 날카로움
- THIN: settings의 `data_dir`/`packs_dir`는 저장되지만 실행 중 앱이 무시 — 장식 입력

## 종합 리팩토링 우선순위 (ROI 순)

| # | 항목 | 이유 | 비용 |
|---|---|---|---|
| 1 | `ExtractRequest.engine` mock 기본값 제거 | 실데이터 오염 방지, 한 줄 | XS |
| 2 | 리서치 전원 실패 = `failed` (+핀된 테스트 수정) | 운영자에게 거짓 완료 신호 | S |
| 3 | 모든 named-pack 읽기를 `_verified_pack` 경유로 | 무결성 주장과 코드 정합화 | S |
| 4 | `counts`/`evaluation`/`document_review_context`에 `_edge_current_sql` | current-truth 불변식 완성 | S |
| 5 | 큐 critic join 스트림 스코프 + model을 PK에 | conformal의 "not yet"이 큐와 모순되지 않게 | S |
| 6 | `registry_lookup` → `resources.lookup` 경유 | allowlist 우회 폐쇄(유일한 비정규 HTTP) | S |
| 7 | embedder `auto`에 오프라인 계약 (reranker와 동일) | 설치된 지금이 최대 위험 시점 | XS |
| 8 | `_run_intent`를 서비스 함수 호출로 + chat pack `ok` 체크 | Query 함정의 구조적 제거 | M |
| 9 | method IR/compiler 이중 스키마 해소 | 1002줄 방언 또는 릴리스 계약 — 택일 | M |
| 10 | kgstore 분할 + conformal/calibration UI 연결 또는 삭제 | parked math와 god-object 정리 | L |

## 킬 리스트 (주장/코드 불일치)

- `docs/ARCHITECTURE.md`: "풀텍스트는 계획", "5개 소스", "1500토큰 청크", "mock이 어디서나 기본" — 전부 현행 코드와 불일치
- `test_mcp_pack_integrity.py` docstring: "모든 named-pack 읽기 해시 검증" — resource_* 제외가 테스트에 하드코딩됨
- `semantic_search` 함수명: BM25인데 임베딩을 연상시킴
- 커뮤니티 탭 빈 상태 문구("팩을 빌드하면 계산돼요") — 빌드 후에도 워킹 DB는 빈 채널을 읽음
- 리서치 "완료!" — 전원 실패 포함

## 3-pane 비교용 프로세스 기록

- omo(본 pane): 8레인 DAG(Grok 4.6 xhigh, read-only, file:line 의무) + 리드 직접 검증 + 12건 스팟 검증. deep/ultrabrain 라우트(GPT-5.6 Sol)는 본 세션에서 다운 — 레인 3개와 비평 1개를 Grok 라우트로 대체, 보고서에 명기.
- gjc / prime-agent: herdr pane 메시지로 동일 스펙 요청됨. 각자 `docs/ENGINE-PIPELINE-AUDIT-GJC-2026-08-19.md`, `...-PRIME-AGENT-...`에 작성.
