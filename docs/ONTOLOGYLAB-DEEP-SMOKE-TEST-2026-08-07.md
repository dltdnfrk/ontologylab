# 온톨로지랩 심층 시운전 — 아키텍처 불변식 검증 (2026-08-07)

기본 시운전(`ONTOLOGYLAB-SMOKE-TEST-REVIEW-GAP-2026-08-06.md`)은 표면 기능이
"동작하는가"를 봤다. 이 심층 시운전은 **설계 계약이 실제로 위반 불가능한가**를
검증한다 — 코드/스키마/런타임 세 층위에서. 기준: `docs/ARCHITECTURE.md` §1~§12.

시나리오마다 **검증 수준**이 붙는다: `C` 코드 확인(정적), `R` 런타임 확인(라이브),
`T` 테스트 확인(기존 테스트가 이미 고정).

---

## S1. verified는 오직 사람만 만들 수 있다 (불변식 1, §3/§4)

**계약**: `status`는 `proposed`로 태어나고, `verified`/`rejected`는 오직
`approve`/`reject`(인간 경로)로만. 파이프라인/엔진/스케줄러는 `verified`를 쓸 수
없다. 쓰기 API가 물리적으로 분리되어 있다.

- [ ] C: `insert_proposed` 경로 어디에도 `status='verified'`를 쓰는 코드가 없는지
      — `kgstore.py`의 `approved`-전용 UPDATE 문과 대조
- [ ] C: `approve` 외에 `UPDATE nodes SET status='verified'`를 실행하는 경로가
      없는지 (`grep` 전면 검색: 서버 라우트·CLI·jobs·engines·스케줄러)
- [ ] T: `tests/` 중 "auto-verify"가 불가능함을 고정하는 테스트 존재 확인
- [ ] R: 라이브 UI에서 **거부된 항목이 재승인 시 `verified`로 되돌아가는지**,
      `rejected → verified` 전이가 가능한지 (되면 안 됨 — 감사 추적)

## S2. 엣지 승인 의존성 — 양쪽 끝점 verified 필수 (§5.3)

**계약**: `approve(edge)`는 양쪽 엔드포인트가 `verified`일 때만. 아니면
`EndpointNotVerified`. 벌크 승인은 노드 먼저, 막힌 엣지는 보고만.

- [ ] T: `tests/` — A(proposed)→B(verified) 엣지 승인이 거부되는지
- [ ] R: 라이브 — **엣지가 `verified`인데 끝점이 `proposed`인 불일치가 존재하는지**
      (데이터베이스 스캔으로 위반 탐지)
- [ ] R: 벌크 승인 → 엣지는 skip 보고, 노드는 승인
- [ ] R: **팩 안에 끝점 미검증 엣지가 들어가는지** (들어가면 안 됨 — 최종 검증)

## S3. 팩은 verified-only + 불변 (§3/§6)

**계약**: 팩 = `verified` 서브그래프 전용 복사본. `proposed`/`rejected`는 절대
팩에 없음. 빌드 후 **불변** (재빌드는 새 pack_id, 같은 파일을 변형하지 않음).

- [ ] C: `packbuilder.py` — `WHERE status='verified'` + 엣지의 양끝점 JOIN 확인
- [ ] R: **팩을 빌드 → 원본 수정 → 팩 재빌드** 시 같은 pack_id로 덮어쓰지 않고
      새 pack_id가 생기는지
- [ ] R: **팩 sqlite를 직접 열어** proposed/rejected 행이 없는지
- [ ] R: **`mode=ro&immutable=1`** — 팩 열기 시 실제로 read-only URI인지, 쓰기 시도가
      실패하는지
- [ ] T: `content_hash` 불변 — 같은 팩 재빌드 시 hash가 달라지는지(내용이 달라졌으므로)

## S4. MCP 서피스는 100% read-only (§9.2)

**계약**: `load_pack` 외 어떤 MCP 툴도 KG를 쓰지 않음. 승인/수정 툴이 **존재하지
않음**.

- [ ] C: `mcp_server.py` — 모든 @mcp.tool 핸들러가 `store` read-only로만 읽는지
- [ ] R: MCP 프로토콜로 직접 `load_pack` 호출 → 그 후 **쓰기 시도** (예:
      `create_entity` 같은 툴이 스키마에 존재하는지 — 없어야 함)
- [ ] R: MCP 서버가 열어놓은 팩 파일에 **외부에서 쓰기 시도** → 실패 확인
      (immutable=1이 실제로 막는지)

## S5. 소스는 deny-by-default (§12)

**계약**: 웹 크롤과 페이퍼 API 모두 **양의 allowlist**만. 허용되지 않은 호스트/소스/
쿼리는 명확한 에러로 거부 (침묵 통과 없음). 리다이렉트마다 호스트 재검증.

- [ ] C: `allowlist.py` — 두 커넥터가 같은 모듈을 import하는지
- [ ] R: **허용되지 않은 URL 호스트 크롤 시도 → 거부 에러** 확인
- [ ] R: **허용된 호스트의 리다이렉트가 다른 호스트로 → 차단**되는지 (실제 리다이렉트
      사이트로 시험)
- [ ] R: 페이퍼 쿼리에 제어 문자/임베드 URL → 거부 확인
- [ ] T: `tests/` allowlist 거부 테스트 존재 확인

## S6. 실패는 드러난다 — 실패 표면화 (§10, 시운전 GAP-O4 회귀)

**계약**: 소스 일부 실패 시, 실행 상세가 소스별 상태(✓/✕+종류)와 집계를 보인다.
전체 실패 시 배너 + 재시도 안내.

- [ ] R: 리서치 실행 — 부분 실패(소스 1~2개만 응답) 상황에서 배지·집계 표시
- [ ] R: **전체 실패** 상황 — 배너 표시
- [ ] R: 실패 소스에 재시도 경로가 있는지

## S7. 연관 관계가 끊기지 않는다 — 연결성 (§5.5)

**계약**: 엔티티 해상도가 insert-proposed 시점에 실행되어, 서로 다른 청크/문서의
멘션이 **같은 노드로 합쳐짐**. `find_path`가 청크 간 경로를 찾을 수 있음.

- [ ] T: `tests/` — 두 문서에서 "RateLimiter"/"rate-limiter"가 한 노드로 합쳐지는
      테스트 존재 확인
- [ ] R: **라이브 그래프에서 2홉 경로** — 다른 문서에서 온 노드가 연결되어 있는지
- [ ] R: 같은 이름이 두 번 등장할 때 같은 node_id로 해상도되는지
- [ ] C: `normalized_name` — `remove_non_alphanumerics(casefold())`가 실제 구현인지

## S8. 청크·스팬·인용 무결성 (§7)

**계약**: 모델이 반환한 스팬은 청크 로컬 좌표 → **문서 좌표로 재베이스**. 저장된
스팬은 원문에서 표면 형태를 포함해야 함 (찾을 수 없으면 drop, 조작된 오프셋 저장
금지).

- [ ] T: `tests/` — 스팬 재베이스/표면 형태 검증 테스트 존재
- [ ] R: **라이브** — 저장된 node의 `source_span`을 열어 `raw_text[start:end]`가
      실제로 그 이름을 포함하는지 무작위 표본 5건

## S9. 영속·재시작 무결성 (§3, 시운전 GAP-O2 회귀)

**계약**: jobs 이력은 재시작 후에도 남는다. 재시작 중이던 `running`은
`failed (interrupted by server restart)`.

- [ ] R: 실행 하나 완료 → 서버 재시작 → jobs 목록에 남아있는지
- [ ] R: running 상태로 재시작 → failed 표시
- [ ] C: `_load_persisted`가 jobs 이력을 복원하는 코드 존재

## S10. 검색 점수 계약 — 0..1 higher-is-better (§5.4)

**계약**: `semantic_search`의 `match_score`는 백엔드(FTS5 BM25 vs 임베딩)와 무관하게
0..1, 높을수록 좋음. FTS5면 `1/(1+bm25)`, 임베딩이면 `(cos+1)/2`.

- [ ] C: `semantic_search` — 두 백엔드 모두 같은 정규화인지
- [ ] R: 라이브 검색 — 반환된 score가 전부 0..1 범위인지
- [ ] T: `tests/` — 정규화 계약 테스트 존재

---

## 검증 매트릭스

| 시나리오 | 불변식 | 코드(C) | 런타임(R) | 테스트(T) | 상태 |
|---|---|---|---|---|---|
| S1 | verified는 인간만 | ☐ | ☐ | ☐ | |
| S2 | 엣지 끝점 의존성 | ☐ | ☐ | ☐ | |
| S3 | 팩 verified-only+불변 | ☐ | ☐ | ☐ | |
| S4 | MCP read-only | ☐ | ☐ | ☐ | |
| S5 | deny-by-default | ☐ | ☐ | ☐ | |
| S6 | 실패 표면화 | ☐ | ☐ | — | |
| S7 | 연결성·해상도 | ☐ | ☐ | ☐ | |
| S8 | 스팬·인용 무결성 | ☐ | ☐ | ☐ | |
| S9 | 영속·재시작 | ☐ | ☐ | — | |
| S10 | 검색 점수 계약 | ☐ | ☐ | ☐ | |

**종합 판정 규칙**: 모든 ☐가 채워지고 위반이 0건이면 **합격**. C/R 단계에서 위반
탐지 시 즉시 버그 리포트(우선순위: 불변식 위반 = P0, 기능 결함 = P1).

**증거 규칙**: R 항목마다 라이브 화면/터미널 캡처, C 항목마다 코드 위치(grep 결과),
T 항목마다 테스트 파일명.
