# OntologyLab 파이프라인 엔진 적대적 감사

- 대상: `/Users/hyunjun/Documents/MUNI/ontologylab` (`origin` `dltdnfrk/ontologylab`, 브랜치 `main`, HEAD `22c65dd`)
- 질문: 각 단계에 **제대로 된 엔진**이 있는가, 빈껍데기인가?
- 판정: `REAL` / `THIN` / `HOLLOW`
- 범위: 소스·테스트 읽기. 라이브 데이터(`~/Library/Application Support/ontologylab/data`)와 포트 `8799`는 열지 않았다.
- 검증: 격리 pytest 31건 통과 (`test_extractor`, `test_full_mvp_loop`, MCP 변조 거부, method pack mutant, conformal, hybrid search).

## 1. 총평

본선(수집→추출→정규화→사람 승인→팩/MCP)은 엔진이 있다. 빈 디렉터리나 TODO 더미가 아니다. 다만 **제품이 실제로 돌리는 기본 지능은 MockEngine + HashingEmbedder**이고, 의미 임베딩·교차인코더·Leiden은 선택 의존성이다. conformal/calibration은 서버 API만 있고 UI가 호출하지 않는다. `method_*`(31파일, 8,983줄)는 CLI·팩 복사 경로의 **병렬 서브시스템**이며 `/api`와 `web/app.js`에 라우트가 없다. 테스트 품질은 이원화되어 있다: extractor/MCP/method-pack-mutants는 바이트·동작을 깨면 실패하고, `test_method_pack_mutation_contract.py`는 소스 문자열 고정이다.

## 2. 단계별 판정

### (1) intake 수집 — **REAL**

**근거**

- 커넥터 프로토콜과 DOI 중복 축약: `ontologylab/connectors/base.py:133-141`, `94-130`.
- deny-by-default 호스트/소스 게이트: `ontologylab/connectors/allowlist.py:43-84`, `99-116`, `181-208`.
- 논문 API 디스패치가 구현 레지스트리 자체: `ontologylab/connectors/paper_api.py:183-194`, `1191-1241`, `1362+`. arXiv/Crossref/OpenAlex/S2/EuropePMC/bioRxiv/PubMed/Elsevier/Springer/CORE/ClinicalTrials/SearXNG 파서가 파일 안에 있다(약 1,646줄).
- 명시 URL만 가져오는 크롤러(링크 추종 없음): `ontologylab/connectors/web_crawl.py:118-149`.
- 공개전문은 허용 목록을 넓히지 않는 EuropePMC JATS 경로: `ontologylab/connectors/fulltext.py:121-189`.
- CLI `collect`와 웹 `/api/collect`, `/api/research`: `ontologylab/main.py:412-544`, `web/app.js:2037`, `2741`.
- E2E가 로컬 파일 collect의 내용 해시 중복을 실제로 돈다: `tests/test_pipeline_e2e.py:39-42`.

**갭**

- `WEB_CRAWL_ALLOWED_HOSTS`는 문서/표준 호스트 + EPPO뿐이라(`allowlist.py:44-55`) 일반 웹 수집은 사실상 막혀 있다. 의도에 가깝지만 “웹 크롤 엔진”은 아니다.
- 자격 증명 필요 소스는 키가 없으면 사용 불가다(`paper_api.py:1338-1359`). 빈 구현이 아니라 운영 전제다.
- `sources.py`는 퍼블리셔 키 레지스트리지 수집기 본체가 아니다.

**테스트**

- allowlist 거부는 E2E가 잡는다: `tests/test_pipeline_e2e.py:142-148`.
- 논문 소스·리다이렉트·풀텍스트 전용 테스트가 `tests/test_paper_api.py`, `test_fulltext.py`, `test_allowlist.py`에 있다.

**권고**: 유지. “크롤” 명칭을 허용 호스트 fetch로 문서화.

---

### (2) extraction 추출 — **REAL** (기본 엔진은 결정론 mock)

**근거**

- 청킹·프롬프트·스팬 재배치·스키마 검증: `ontologylab/extractor.py:89-130`, `179-207`, `215-238`, `379-628`, `671-863`.
- 청크에 없는 surface는 거절, 관계 끝점은 플래그된 placeholder: `extractor.py:517-552`; 테스트 `tests/test_extractor.py:106-117`, `229-278`.
- 엔진 어댑터: Mock / Claude / Codex / Gemini / `api:<provider>` (`engines.py:483-518`, `534-619`, `707-848`, `857-931`).
- 서버 추출 워커가 같은 `run_extraction`을 호출: `ontologylab/server/jobs.py:721-734`.

**갭**

- 기본·CI 경로는 `MockEngine`이다. CamelCase 휴리스틱(`engines.py:222-338`)이라 생물/농약 산문에서는 추출이 빈약하다. `docs/PRODUCT_SPEC.md`도 이를 인정한다.
- CLI 엔진은 샘플링 파라미터를 거절한다(`engines.py:909-913`). 라이브 추출의 재현 손잡이가 API 엔진에만 있다.
- 토큰 추정은 `len/4` (`extractor.py:49-90`).

**테스트**

- `tests/test_extractor.py`는 잘못된 JSON, 미지 타입, 청크 부재, 스팬 rebase, domain/range, mock↔실프롬프트 왕복을 직접 깨뜨린다.
- `test_full_mvp_loop`가 mock 추출 후 노드 6 / 엣지 5를 단언한다(`tests/test_pipeline_e2e.py:44-74`).

**권고**: 추출 *파이프*는 REAL. 제품 기본을 mock에 두면 라이브 품질은 THIN으로 남는다. 라이브 경로 스모크를 mock과 분리하라.

---

### (3) normalization / 엔티티 해상도 — **THIN**

**근거**

- 제안 정규화는 생물·원제 두 갈래뿐이다: `ontologylab/normalization.py:8-114`.
- 레지스트리는 import-first 캐시(EPPO/PubChem/MoA): `ontologylab/registry.py:218-316`, `395-546`, `549-709`.
- 병합은 사람 큐용 퍼지 스캔이지 자동 병합이 아니다: `ontologylab/merge.py:48-54`, `197-263`.
- 온톨로지 제안은 내용주소 접기 + 검증 시 적용: `ontologylab/proposals.py:724-835`, `1085-1189`.

**갭**

- 일반 `Component` 추출(기본 스키마/MVP)은 CAS/EPPO 정규화를 타지 않는다.
- 레지스트리 미설치 시 캐시는 명시적 부재를 반환한다(`registry.py:603`, `709`). 해상도 엔진이 꺼진 것과 같다.
- 자동 엔티티 해상도( transitivity, 교차문서 coref)는 없다. 점수 임계값만 있는 후보 생성기다.

**테스트**

- `tests/test_normalization.py`, `test_cas_normalization.py`, `test_registry.py`, `test_merge.py`가 해당 분기를 친다. 교차 스키마 해상도 E2E는 없다.

**권고**: 농약 트랙은 완성, 범용 KG는 정규화 레이어를 스키마 플러그인으로 두거나 “사람 병합이 해상도”라고 제품을 정직하게 좁혀라.

---

### (4) review / HITL — **REAL** (통계 보조는 서버-only)

**근거**

- 승인/거절/재오픈이 저장소 불변식이다. 엣지는 양 끝점 verified 필수, cascade만 명시적 예외: `ontologylab/kgstore.py:2723-2768`.
- critic은 advisory only: `ontologylab/critic.py:222-292`.
- split conformal triage, 데이터 부족 시 `None`: `ontologylab/conformal.py:75-153`.
- isotonic + ECE, `n<20`이면 거부: `ontologylab/calibration.py:46`, `181-193`.
- 웹 검토 큐·승인/거절: `web/app.js:781`, `263`, `1114`; 탭 `web/index.html:38`.
- API: `GET /api/review/triage`, `GET /api/review/calibration` (`server/routes.py:380-410`).

**갭**

- `web/app.js`에 `conformal`/`calibration`/`/review/triage` 호출이 **없다**. 통계 엔진은 구현됐지만 대시보드 미배선.
- critic 기본은 claude 값싼 모델(`critic.py:46-48`). mock도 점수만 낸다(`engines.py:395-427`). 사람 결정을 대체하지 않는다 — 설계상 맞다.

**테스트**

- conformal은 스트림 분리·제안 제외·임계값 공식을 깨면 실패한다: `tests/test_conformal.py:55-129`.
- 승인 없이 팩에 proposed가 못 들어가는지는 E2E가 증명한다: `tests/test_pipeline_e2e.py:107-139`.

**권고**: triage/calibration을 검토 UI에 붙이거나 API를 내부용으로 강등하라. 미배선 기능이 “가드가 있다”는 서사를 만든다.

---

### (5) retrieval — **THIN** (기본은 어휘 + 해시벡터)

**근거**

- hybrid = BM25 + (옵션) 확장 질의 + 벡터, RRF, 선택적 재랭크: `ontologylab/kgstore.py:4787-4894`.
- `HashingEmbedder`는 문서에 **NOT semantic**이라고 적혀 있다: `ontologylab/embeddings.py:110-146`.
- `auto`는 sentence-transformers가 있을 때만 MiniLM: `embeddings.py:192-208`.
- 재랭커는 오프라인 미다운로드가 기본: `ontologylab/rerankers.py:11-15`, `91-108`.
- 질의 확장·토픽→검색어는 fail-open: `expansion.py:88-108`, `searchquery.py:115-142`.
- 커뮤니티는 팩 빌드 시 1회. Leiden 없으면 label propagation: `communities.py:48-59`, `66-128`, `224-276`.

**갭**

- 기본 설치(`pyproject.toml` optional `embed`/`graph`/`vec`)에서 “의미 검색 엔진”은 해시 n-gram이다.
- `SentenceTransformerEmbedder.embed`는 `pragma: no cover` (`embeddings.py:180`).
- 웹 `/api/search`는 팔레트 8건 조회(`web/app.js:683`). MCP `search`가 하이브리드의 본 표면이다.

**테스트**

- `tests/test_embeddings.py`는 해시 결정성, RRF, 백필, 3신호 extra-lexical을 **hash embedder로** 증명한다. 실 MiniLM 순서는 증명하지 않는다.

**권고**: UI/문서에 검색 티어를 표시. `embed` extra를 제품 기본으로 올릴지, hash를 “어휘 보조”로 부를지 택일.

---

### (6) pack / MCP 서빙 — **REAL**

**근거**

- verified subgraph만 불변 디렉터리로 스냅샷. 경로 탈출 방지, 컬럼 명시 복사: `ontologylab/packbuilder.py:78-82`, `232-243`, `294-330`, `747-793`.
- 로드 시 현재 바이트 SHA-256 vs manifest, 심볼릭/하드링크 거부: `ontologylab/mcp_server.py:237-356`.
- 도구는 compact-first: `mcp_server.py:82-88`, `1097-1365`.
- 자체 stdio 레지스트리: `mcp_runtime.py:152-303`.
- CLI `build-pack` / 웹 `/api/packs/build`: `main.py:1126-1188`, `web/app.js:3171`.

**갭**

- 불완전 추출 팩은 연산자 intent가 있으면 허용된다(`packbuilder.py:327-330`). 가드가 우회 가능하다 — 숨긴 구멍이라기보다 명시 탈출구.
- MCP는 읽기 전용 팩 서버다. 라이브 KG를 직접 쓰지 않는다.

**테스트**

- `tests/test_mcp_pack_integrity.py`는 바이트 1개 flip으로 named-pack 읽기를 거절한다 (`_flip_one_byte`, `test_named_pack_read_surface_rejects_current_tampered_bytes`).
- E2E가 팩 빌드 + `PackSession.entity_lookup("RateLimiter")`를 돈다 (`test_pipeline_e2e.py:55-83`).
- 이번 세션에서 해당 테스트를 재실행해 통과를 확인했다.

**권고**: 유지. 본선에서 가장 엔진다운 출고 경계다.

---

### (7) method_* 서브시스템 — **REAL** (본선과 **미배선**)

**근거**

- 31파일 / **8,983줄**. 컴파일러 게이트 G0–G6, G8: `method_compiler_gates.py:137-530`.
- 순수 compile + persist: `method_compiler.py:189-280`.
- occurrence 추출은 별 프롬프트/재개 체크포인트: `method_extract.py:35-48`, `122-266`.
- CLI만 진입: `ontologylab/main.py:120-180` (`method extract|workspace-create|…|compile`).
- `server/routes.py`와 `web/app.js`에 method 워크스페이스 라우트 **없음** (HTTP `method:` 키만 존재).

**갭**

- 대시보드 사용자는 method 엔진을 볼 수 없다. 팩에 `method_release_ids`를 넣을 수는 있다(`packbuilder.py:305`).
- `tests/test_method_pack_mutation_contract.py:14-99`는 `"validate_method_pack" in source` 같은 **소스 문자열 pin**이다. 동작을 뮤테이션하지 않는다.
- 반대로 `tests/test_method_pack_mutants.py:16-75`는 DB 행을 실제로 깨고 `copy_method_releases`가 fail-closed인지 본다. 이쪽이 진짜 증명이다.

**테스트**

- pack/atomic/compiler/gaps/IR 스위트가 두껍다. 웹/서버 결합 테스트는 없다.

**권고**: 제품에 넣을 거면 `/api/method/*`와 UI를 붙이거나, 본선 서사에서 method를 빼라. 문자열 pin 테스트는 동작 뮤턴트로 교체.

---

### (8) server / jobs / web UI — **REAL**

**근거**

- FastAPI 팩토리, 정적 `web/index.html`, `/api` 라우터: `server/app.py:38-62`, `134-136`.
- JobRegistry: 디스크 복구, running→failed 재기입, exclusive check-and-register, SSE: `server/jobs.py:255-438`.
- 기본 포트 **8765**, data-dir 기본 `ROOT/data`, iCloud 거부, non-loopback은 `--allow-remote` 필요: `serve.py:26-92`.
- UI는 수집·추출·검토·팩·MCP·병합·그래프·채팅을 `/api/*`에 직접 붙인다 (`web/app.js` 전역; 탭 `web/index.html:34-47`).
- 기본 `create_app()`은 `default_data_dir()` = 저장소 `./data` (`paths.py:40-42`, `app.py:47`). 라이브 설치는 런처가 Application Support를 넘긴다. 이 감사는 그 경로를 열지 않았다.

**갭**

- method·conformal UI 공백은 위와 같다.
- `JobRegistry.persist` 실패는 삼킨다 (`jobs.py:350-357`). 히스토리만 stale, 잡은 계속 — 의도된 fail-open.
- 인증 없음(`serve.py:46-48`). 로컬 단일 사용자 전제.

**테스트**

- `tests/test_server.py`, `test_job_cancel.py`, `test_ui_failure_honesty.py`, `test_agent_drivable_ui.py`가 HTTP/UI 계약을 친다. 라이브 8799는 사용하지 않았다.

**권고**: 유지. 새 서버를 띄울 때는 `--data-dir $(mktemp -d)`만 사용.

## 3. 테스트가 실동작을 증명하는가?

| 영역 | 뮤테이션에 잡히는가 | 메모 |
| --- | --- | --- |
| extractor 스팬/그라운딩 | 예 | 청크 부재·합성 endpoint 침묵을 직접 단언 |
| collect→extract→approve→pack→MCP | 예 | mock E2E, 카운트·해시·lookup |
| MCP 무결성 | 예 | sqlite 1바이트 flip 거부 |
| method pack 관계 뮤턴트 | 예 | 행 UPDATE/DELETE 후 복사 거절 |
| method mutation *contract* | 아니오 | 소스 부분문자열 pin |
| conformal | 예 | 공식·스트림 분리 |
| hybrid search | 부분 | hash 티어만. MiniLM 미커버 |
| critic/calibration UI | 아니오 | API 테스트와 UI 호출이 분리 |

이번 세션 실행(저장소 루트, 라이브 data 미사용):

```
PYTHONPATH=. .venv/bin/pytest \
  tests/test_extractor.py \
  tests/test_pipeline_e2e.py::test_full_mvp_loop \
  tests/test_mcp_pack_integrity.py::test_named_pack_read_surface_rejects_current_tampered_bytes \
  tests/test_method_pack_mutants.py \
  tests/test_conformal.py \
  tests/test_embeddings.py::test_embed_backfill_and_hybrid_search -q
→ 31 passed
```

## 4. 리팩토링 백로그

1. **P0** — 검색/추출 “엔진” 레이블을 런타임 티어와 일치시켜라. 기본은 mock + hash이지 MiniLM/Claude가 아니다.
2. **P0** — method를 본선에 붙이거나(라우트+UI) 제품 파이프라인 설명에서 빼라. 8.9k줄이 대시보드와 무관하다.
3. **P1** — `/api/review/triage`·`/calibration`을 검토 화면에 연결하거나 숨겨라.
4. **P1** — `test_method_pack_mutation_contract.py`를 `test_method_pack_mutants.py` 스타일의 동작 뮤턴트로 교체.
5. **P1** — `embed` extra 없이 hybrid가 의미 검색처럼 보이지 않게 팩/UI에 `embedding_model`을 노출.
6. **P2** — `WEB_CRAWL` 이름을 allowlisted-fetch로. 정규화를 스키마별 플러그인으로 분리.
7. **P2** — CLI 엔진 샘플링 거절을 UI 설정에 반영해 죽은 손잡이를 만들지 마라.

## 5. 가장 위험한 발견 Top 3

1. **기본 지능이 데모 엔진이다.** 파이프는 REAL이지만 기본 generate/embed는 mock CamelCase와 해시 n-gram이다. 라이브 산문 품질을 파이프 존재와 혼동하면 안 된다.
2. **method_*는 두 번째 제품이다.** 컴파일러·게이트·팩 복사는 실구현이나 웹 컨트롤플레인과 단절. 운영자가 “온톨로지랩 = method 계약”으로 읽으면 빈 화면을 본다.
3. **가드 서사와 UI가 어긋난다.** conformal/calibration은 코드·API·단위테스트가 있고 브라우저가 안 부른다. MCP 무결성·HITL approve는 반대로 진짜로 막는다.

## 6. 사전 제약 준수

- 코드 수정·커밋 없음. 산출물은 이 파일뿐이다.
- `~/Library/Application Support/ontologylab/data` 미사용.
- 포트 8799 / PID 55560 미접촉. 서버를 띄우지 않았다.
- 형제 프로젝트(`muni-lab`, `muni-lab-wip` 등) 미접근.
