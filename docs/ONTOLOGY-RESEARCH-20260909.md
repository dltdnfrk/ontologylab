# 온톨로지 대담 키워드 리서치 — ReBAC · 용어 정체성 · 팔란티어 온톨로지

**작성일:** 2026-09-09 · **방법:** ulw-research 8인 팀 / 3축 / 반증검색 및 회의론자 통과 필수

**대상 독자:** OntologyLab 아키텍처 결정자 · **인용 규칙:** `[S<n>]`은 문서 끝 출처표, 모든 접근일자 2026-09-09.

## 1. 요약

대담에서 뽑은 세 축을 각각 1차 출처로 검증한 결과, **대담의 방향은 대체로 옳지만 근거로 인용된 숫자와 단정은 그대로 쓰면 안 된다.**

1. **Zanzibar의 유명한 숫자는 재해석이 필요하다.** ">10M QPS"는 권한 체크만이 아니라 총 클라이언트 질의이고(Check 4.2M / Read 8.2M / Expand 760K / Write 25K), "p95 10ms"는 freshness 조건부다 — Safe Check p95 9.46ms vs Recent Check p95 60.0ms [S4].
2. **ReBAC가 실제로 깨지는 지점은 권한 체크(point check)가 아니라 목록/필터(list)다.** 세 개의 독립 보고자군이 같은 곳에서 무너졌고, AuthZed 자신의 100B 관계 벤치마크는 `LookupResources`를 **0%** 로 제외한 실험이다 [S9][S11][S12].
3. **"Zanzibar 계열"은 일관성 계약을 공유하지 않는다.** zookie(개정 토큰)는 SpiceDB만 4종으로 구현했고, OpenFGA는 future work, Ory Keto는 소스 주석 그대로 "not implemented yet"이다 [S6][S7].
4. **SKOS는 "같은 이름 다른 의미"를 스킴으로 해결하지 않는다.** `prefLabel` 유일성은 **리소스 × 언어태그** 단위이고 `inScheme`은 라벨을 맥락화하지 못한다 [S1]. 실제 출판 어휘는 개념 자체를 쪼갠다 — LCSH는 Java(프로그래밍 언어)와 Java(인도네시아)를 같은 스킴 안의 **별도 concept**으로, 상호 매핑 없이 둔다 [S42][S43].
5. **"정본 모델을 절대 만들지 말라"는 결론은 증거가 지지하지 않는다.** 반대 논거와 찬성 논거가 범위를 한정하면 수렴한다: 경계 안의 교환 포맷은 유효하고, 전사(全社) 강요만 무효다 [S34][S35][S33].
6. **팔란티어 본인 문서는 온톨로지를 "시맨틱 레이어가 아니다"라고 명시한다.** Language + Engine + Toolchain의 multimodal system이라는 정의다 [S44]. "meta-ontology"는 팔란티어 영문 문서 색인에 **0건**이며, 대담자의 신조어도 아니다 — 1998년 문헌에 선행 용례가 있다 [S45][S46].
7. **우리 코드에서 실제로 의미 충돌을 막는 것은 온톨로지 어휘가 아니라 인덱스다.** `idx_nodes_resolve UNIQUE(schema_version_id, entity_type, normalized_name)`이 유일한 강제 지점이고, `ontology_term`에는 라벨 유일성 제약이 **없다**.

## 2. 축 A1 — ReBAC / Zanzibar: 무엇이 실제로 깨지는가

### 2.1 인용되는 숫자의 실제 의미

| 통념 | 원전이 실제로 말한 것 | 출처 |
|---|---|---|
| "10M 권한 체크/s" | 2018-12 피크 기준 **총 클라이언트 질의** 10M+, 그중 Check 4.2M · Read 8.2M · Expand 760K · Write 25K | [S4] §4 |
| "p95 10ms" | **freshness 조건부**. Safe Check p95 9.46ms, Recent Check p95 **60.0ms** | [S4] Table 2 |
| ">99.999% 가용성" | **프로버 재생 기반 한정 지표**(5s Safe / 15s Recent 마감, 이상치 제외). 원시 클라이언트 성공률이 아님 | [S4] §4.3 |
| "external consistency = 최신 읽기" | 노출된 stale-snapshot 읽기 트레이드오프이며, 후속 피어리뷰 문헌(RAMP-TAO, VLDB 2021 §7)도 같은 인식 | [S4][S47] |

**zookie의 한계도 원전이 스스로 한정한다.** zookie는 인가 신선도를 **콘텐츠 버전에 묶을 뿐**, 애플리케이션 쓰기와 인가 쓰기를 원자적으로 커밋하지 않는다. dual-write 문제는 남는다 [S4] §2.2.

**Read/Expand는 "사용자가 볼 수 있는 전체 리소스" API가 아니다.** Read는 저장된 튜플만, Expand는 한 홉 userset 트리만 돌려준다. 논문은 클라이언트가 **인가 인지 검색 색인을 따로 만든다**고 명시한다 [S4] §2.4. 즉 원전 설계에서도 "목록"은 인가 시스템 밖의 문제였다.

### 2.2 다른 선택지: Airbnb Himeji

Airbnb는 Zanzibar를 그대로 따르지 않았다. 1차 수치: **850,000 entities/s**, 가용성 **99.9990%**, **P50 1.8ms / P95 7ms / P99 12ms**, 수백억 관계, 캐시 히트 목표 약 98%, 그리고 Spanner가 아니라 **Aurora** [S48].
설계 차이의 핵심은 **팬아웃을 읽기에서 쓰기로 옮긴 것**, 그리고 정적 설정으로 N×M을 N으로 줄인 것이다.
다만 정확히 기록해 둔다: **Himeji가 zookie를 "생략했다"고 말한 적은 없다.** 공개된 Check API에 일관성 토큰이 없고 캐시 무효화 설계에 zookie 기제가 없다는 것이 관측 사실이다 [S48].

### 2.3 붕괴 지점의 실측

- **역사적 실측:** 499개 교집합 후보(총 999 튜플)에서 PostgreSQL **709ms** → 배치 처리 후 **30ms** [S8]. (로컬 M1 컨테이너·에뮬레이션 환경이라 백엔드 간 순위 비교로 쓰면 안 된다.)
- **현장 보고:** OpenFGA 1.4.2/PG에서 check 10→80ms인데 list는 100–200ms→**3s 타임아웃**(미해결) [S9]. SpiceDB에서 Spanner 커서 인덱스 오선택으로 **2–4s vs <20ms** [S10]. v1.47.1에서 500–1000 동시 `LookupResources`에 pgxpool 고갈 [S11].
- **커뮤니티 실사용:** 권한 약 50개 · 리소스 약 1,000개 · BulkCheck 약 50,000회에서 `LookupResources`가 하나씩 돌려도 DB·CPU·메모리를 압도. 유지보수자가 "최좌측 교집합 분기를 걷고 루트에서 후보를 재검사하는 방식은 non-optimal"이라고 인정 [S49]. (이 스레드에는 **수치 지연이 없다** — 밀리초를 인용하면 안 된다.)
- **운영 대응:** 실제 운영자들이 지연 실패 후 exclusion 정책을 제거하거나 list API 사용을 중단했다 [S9][S10]. 감사된 포스트모템이 아니라 사용자 보고임을 명시한다.

### 2.4 결정 규칙

**가용 여부를 총 노드/튜플 수로 정할 수 없다.** 실제 변수는 **검사되는 후보 수 × 정책 팬아웃/깊이 × 동시성 × 캐시·신선도 체제**다 [S8][S12].
그리고 **비정규화는 비용을 없애지 않고 변경 전파로 옮긴다** — 원전 §3.2.4은 튜플 1건 변경이 Leopard 이벤트 **수만 건**을 유발한다고 보고한다 [S4].

### 2.5 구현체별 계약 차이 (같은 조상, 다른 약속)

| | 일관성 토큰 | 깊이/상한 |
|---|---|---|
| SpiceDB | ZedToken 4종 모드. `fully_consistent`에 CockroachDB 예외 [S5] | 설정 가능 |
| OpenFGA | `MINIMIZE_LATENCY` / `HIGHER_CONSISTENCY` 2종, **토큰 미도입**(future work) [S6] | 설정 가능 |
| Ory Keto v26.2.0 | snaptoken **미구현**(proto 주석) [S7] | `max_read_depth` 기본 5. **깊이 소진이 별도 오류가 아니라 비허용(false)으로 나타난다** [S50] |

Keto는 master 브랜치에서 Expand의 교집합/부정을 구현했지만 **릴리스 v26.2.0에는 없다** [S50]. 버전별 unknown/error 동작을 모델에 명시해야 하는 이유다.

## 3. 축 A2 — 용어 정체성: 같은 이름, 다른 의미

### 3.1 SKOS가 실제로 보장하는 것

- `prefLabel` 유일성의 단위는 **리소스 × 언어태그**다. 스킴 단위도, 팀 단위도 아니다 [S1] §5.4/§4.6.1.
- `inScheme`은 **팀 로컬 라벨 선호나 주장의 진리값을 표현할 수 없다** [S1] §4.6. "스킴을 나누면 팀 스코프가 생긴다"는 통념의 정면 반증이다.
- **매핑은 함의 약속이다.** `exactMatch`는 전이적이고 `closeMatch`는 아니다 — 잘못된 사슬은 원래 쌍을 넘어 번진다 [S1] §10.
- 같은 철자라는 사실만으로는 `exactMatch`/`closeMatch`/`relatedMatch` **어떤 간선도 정당화되지 않는다** [S1].

### 3.2 실제 출판 어휘는 어떻게 하는가

- **LCSH:** Java(Computer program language) `sh95008574` vs Java(Indonesia) `sh85069786` — **같은 스킴, 별도 concept, 상호 매핑 없음** [S42][S43].
- **MeSH:** concept이 의미 단위이고 descriptor 아래 다수 concept이 붙는다 [S15].
- **반대 방향도 있다.** AGROVOC은 의미가 같으면 URI를 스킴을 넘어 재사용한다 [S40] — 따라서 "팀마다 항상 별도 concept"은 과잉 일반화다.
- **정규화의 위험:** EuroVoc는 digital/data/technological/tech/cyber sovereignty를 한 concept의 `altLabel`로 묶는다 [S51]. 검색 정규화가 다른 팀에 필요한 구분을 지울 수 있다는 실증이다. (단 이것은 `altLabel`일 뿐 `exactMatch`나 OWL 동치가 아니다.)

한 가지 시간 오류를 자체 교정했다: SKOS Primer의 "개념을 OWL 클래스로 쓰지 말라"는 **OWL 1 시기 서술**이며, OWL 2는 punning을 허용한다 [S2][S3].

### 3.3 조직 실무: 카탈로그·계약·시맨틱 레이어의 한계

19개 호스트 29개 출처를 훑은 결과는 하나로 모인다: **이 도구들은 스코프된 정의를 허용할 뿐, 어느 정의가 옳은지 결정하지 못한다** [S18][S20][S22][S23][S29].
Purview는 동명 용어에 **경고 후 허용**이고 [S18], LookML `extends`는 다중 버전과 충돌 우선순위를 노출하며 [S23], 데이터 계약은 **소유권 분쟁을 해결하지 못한다**고 실무자가 1인칭으로 쓴다 [S27].

**정본 모델 논쟁의 실제 결론:** 반대(INNOQ [S34])와 찬성(Hughson [S35])은 범위를 한정하면 수렴한다 — **경계 안의 교환 포맷은 유효, 전사 강요는 무효**. Fowler의 "중첩 정본 모델 수확" [S33]과 같은 자리다. (InfoQ 재게재본은 INNOQ와 독립 출처가 아니므로 세지 않았다.)

### 3.4 결정 규칙

> 정체성·포함규칙·입도·시간기준·결정목적을 **진짜로 공유하는 최소 의미만** 통일하고, 나머지는 도메인별로 스코프한 뒤 **실제 교환이 필요한 곳에만** 매핑을 발행한다.

그리고 "정의할 수 없다"는 대담의 강한 주장에는 직접 반례가 있다: **OBO Foundry 원칙 6은 대다수 클래스에 텍스트 정의를 둘 것을 요구한다** [S52].

## 4. 축 A3 — 팔란티어 온톨로지

### 4.1 벤더 1차 정의

팔란티어 문서는 **"The Ontology is not a semantic layer"** 라고 명시하고, **Language + Engine + Toolchain**의 multimodal system으로 정의한다 [S44].
- **보안:** 객체/속성 보안 정책이 행·열·셀 가시성을 **읽기 시점에, 백킹 데이터소스 권한과 독립적으로** 강제한다. 액션 제출자도 대상 조회 권한이 필요하다 [S53].
- **경계:** Pipeline Builder는 온톨로지 **상류의 통합·저작 도구**이지 런타임이 아니다. 객체/링크 타입을 출력할 수는 있지만 질의/런타임은 온톨로지 백엔드다 [S54].

### 4.2 "그래프다 / 그래프가 아니다"

Pagefind 색인 직접 질의 결과: `"ontology is a graph"` **0건**, `"ontology graph"` 2건(**둘 다 Pilot의 UI 시각화**), `"semantic layer"` 2건(**둘 다 명시적 부정**), `"operational layer"` 4건 [S44][S55].
→ 교정판 표현: **"그래프만이 아니라, 그것을 사용·변경하는 운영 시스템과의 결합"**. "그래프가 아니다"는 과도한 단정이다 — 객체·관계 모델은 온톨로지의 일부다.

### 4.3 "meta-ontology"

- 팔란티어의 **라이브 영문 문서 색인에 0건**이다(2026-09-09 기준). meta-ontology / metaontology / metaontolog 어간 4가지 질의 모두 0건, 퍼지 후보는 전수 반증 [S55].
- **대담자의 신조어도 아니다.** 1998년 문헌에 선행 용례가 있다 — Crossref DOI `10.1023/A:1005323618026` [S46].
- 인터뷰 외부 사용례가 하나 존재하지만(제3자 GitHub PR 2건) **독립성과 선후 관계는 미해결**이다 [S56]. 보편적 부재로 일반화하지 않는다.

### 4.4 이탈 가능성 (lock-in 반증)

- **완료된 이탈 사례가 있다.** Homes for Ukraine: 연 £4.5M/£5.5M 계약 → 2025-09 대체 시스템 가동, 연 수백만 파운드 절감 보고 [S57][S58][S59]. 단 **하나의 서비스 대체이지 제품군 전체가 아니다.**
- **NHS FDP 실명 계정:** 운영 앱은 작동했으나 탐색적 분석·데이터 반출·개발환경 분리·EPR write-back은 마찰이 컸고 **총소유비용은 미상**(독립 평가 결과 2029 예정) [S60]. 편익 수치는 NHS England 출처이며 독립 검증이 아니다.

## 5. 우리 코드에 대한 함의

### 5.1 관측된 사실 (코드 직접 확인)

| 발견 | 위치 |
|---|---|
| 두 팀이 한 이름에 두 의미를 주는 것을 **실제로 막는 유일한 것**은 `idx_nodes_resolve UNIQUE(schema_version_id, entity_type, normalized_name)`이다. `ontology_term`에는 라벨 유일성 제약이 **없다** | `kgstore.py:306-312` |
| 우리 시스템에는 **사용자/관계 기반 권한이 전혀 없다.** API는 단일 세션 토큰, KGStore는 status 필터, 팩·MCP는 호출자 신원이 없다 | `app.py:76-289`, `kgstore.py:556-567` |
| **MCP 표면은 신뢰 경계를 강제하지 않는다.** 클라이언트가 `packs_dir`의 **어떤 팩이든** 열거·전환할 수 있고 런타임에 호출자 맥락이 없다. `--pack`은 인가 경계가 아니며, **팩 불변성은 기밀성이 아니라 무결성만 보호한다** | `mcp_server.py:477-503,1053-1068`, `mcp_runtime.py:224-314` |

### 5.2 권고

1. **ReBAC를 도입하지 않는다.** 우리는 단일 사용자 로컬 우선 제품이고, ReBAC가 값을 하는 지점(다중 주체 × 관계 파생 권한)이 없다. NIST SP 800-162도 ReBAC를 유일 기반으로 규정하지 않는다 [S61].
2. **대신 A1에서 배운 것을 그대로 가져온다.** 우리의 `_edge_current_sql()` / `invalidated_ts` 비시간적 읽기가 Zanzibar의 freshness 계약과 같은 종류의 문제다 — **"어느 시점의 진실인가"를 API 표면에 명시**하고, 목록/필터 경로의 후보 수를 성능 지표로 삼는다(총 노드 수가 아니라).
3. **용어 정체성은 SKOS의 답을 따른다.** 의미가 진짜 다르면 **개념 정체성을 쪼개고**, 같은 철자라는 이유만으로 매핑 간선을 만들지 않는다. `ontology_term`에 라벨 유일성 제약이 없는 것은 SKOS 관점에서 **버그가 아니라 정확한 모델링**이다 — 유일해야 하는 것은 라벨이 아니라 개념 해소(resolve) 키다.
4. **MCP 팩 열거는 실제 결함이므로 별도 이슈로 잡는다.** "단일 사용자니까 괜찮다"는 프레이밍은 회의론자 검사에서 반증됐다. 팩이 여러 개일 때 세션이 시작 팩 밖으로 나갈 수 있다는 것은 설계 의도와 다르다.
5. **팔란티어 어휘를 빌리되 정의를 빌리지 않는다.** 우리 `docs/ARCHITECTURE.md`에서 "온톨로지"를 쓸 때는 **그래프 구조 + 그것을 변경하는 운영 경로(리뷰 · 팩 빌드 · MCP)** 를 함께 가리키는 것으로 못 박는다. "시맨틱 레이어"라는 표현은 쓰지 않는다.

## 6. 반론과 미해결

| 항목 | 상태 |
|---|---|
| 대담의 "GraphRAG가 온톨로지 기반층" | **범주 오류.** GraphRAG는 MS가 **사설 텍스트 코퍼스 QA 기법**으로 정의한 것이다 [S62]. |
| 대담의 "ReBAC가 유일 기반" | **반증.** NIST SP 800-162가 ABAC를 일반 방법론으로 규정한다 [S61]. Cedar는 RBAC+ABAC+ReBAC를 결합한다 [S17]. |
| "정본 정의를 시도했다가 포기한 명명된 사례" | **미확인.** 26회 탐색에도 나오지 않았다. **검색 실패를 부재의 증거로 쓰지 않으므로** 서술로 쓰지 않는다. |
| "meta-ontology" 외부 사용례의 독립성/선후 | **미해결** [S56]. |
| 부재 증명 방법론 | **중요한 교정.** 팔란티어의 **렌더된 검색 UI는 모든 철자에 퍼지 비영 결과를 반환**하므로 그 자체로는 부재를 증명하지 못한다. 부재 근거는 **Pagefind 색인 직접 질의 + 후보 문서 정확 리터럴 스캔**이며, **두 워커가 독립적으로 같은 방법으로 0건**을 확인했다(퍼지 후보 39/39/248건 전수 스캔) [S55]. |
| Zanzibar 원전 수치 | **1차 단일 출처**다. 재현 독립 측정이 없어 예외로 통과시켰다. |
| SpiceDB 커뮤니티 스레드 | **수치 지연이 없다.** 정성 보고로만 인용했다. |
| Keto 관측 | **릴리스 v26.2.0 태그 기준**이다. master 동작과 다르다. |

## 7. 출처

- **[S1]** <https://www.w3.org/TR/skos-reference/> — SKOS 표준(라벨 무결성 S14, 스킴, 매핑 §10) — 1차/표준
- **[S2]** <https://www.w3.org/TR/2009/NOTE-skos-primer-20090818/> — SKOS Primer — 1차/표준
- **[S3]** <https://www.w3.org/TR/2012/REC-owl2-primer-20121211/> — OWL 2 Primer(punning §9) — 1차/표준
- **[S4]** <https://www.usenix.org/system/files/atc19-pang.pdf> — Zanzibar 원전(§2.2 zookie, §2.4 Read/Expand, §3.2.4 Leopard, §4 Table 2, §4.3 가용성 측정법) — 1차/논문
- **[S5]** <https://authzed.com/docs/spicedb/concepts/consistency> — SpiceDB 일관성 4종과 CockroachDB 예외 — 1차/벤더
- **[S6]** <https://openfga.dev/docs/interacting/consistency> — MINIMIZE_LATENCY/HIGHER_CONSISTENCY, zookie는 future work — 1차/벤더
- **[S7]** <https://github.com/ory/keto> — `check_service.proto`의 snaptoken "not implemented yet"(커밋 f50b489 기준) — 1차/소스
- **[S8]** <https://github.com/authzed/spicedb/pull/843> — 499 교집합 후보 PG 709ms→30ms — 1차/유지보수자 벤치
- **[S9]** <https://github.com/openfga/openfga/issues/1338> — check 10→80ms, list 100–200ms→3s 타임아웃 — 1차/사용자 보고
- **[S10]** <https://github.com/authzed/spicedb/issues/1687> — Spanner 커서 인덱스 오선택 2–4s vs <20ms — 1차/사용자 보고
- **[S11]** <https://github.com/authzed/spicedb/issues/2788> — 500–1000 동시 LookupResources에서 pgxpool 고갈 — 1차/사용자 보고
- **[S12]** <https://authzed.com/blog/google-scale-authorization> — 100B 관계/1M QPS, p95 5.76ms, **LookupResources 0%**, 캐시 95.9% — 1차/벤더 벤치
- **[S15]** <https://hhs.github.io/meshrdf/concepts> — MeSH concept 모델 — 1차/기관
- **[S17]** <https://arxiv.org/pdf/2403.04651> — Cedar: RBAC+ABAC+ReBAC 결합 정책 언어 — 1차/논문
- **[S18]** <https://learn.microsoft.com/en-us/purview/unified-catalog-glossary-terms-create-manage> — 동명 용어 경고 후 허용 — 1차/벤더
- **[S20]** <https://docs.getdbt.com/docs/build/semantic-models> — 엔티티 한정 차원 — 1차/제품
- **[S22]** <https://docs.cube.dev/docs/data-modeling/views> — 도메인별 큐레이션 뷰 — 1차/제품
- **[S23]** <https://docs.cloud.google.com/looker/docs/reusing-code-with-extends> — LookML extends 충돌 우선순위 — 1차/제품
- **[S27]** <https://andrew-jones.com/daily/2024-10-08-data-contracts-cannot-assign-ownership/> — 계약은 소유권 분쟁을 해결하지 못한다 — 2차/실무
- **[S29]** <https://docs.reltio.com/> — MDM 생존 규칙과 자동 언머지의 한계 — 1차/제품
- **[S33]** <https://martinfowler.com/bliki/MultipleCanonicalModels.html> — 중첩 정본 모델 수확 — 2차/저자
- **[S34]** <https://www.innoq.com/en/blog/2015/03/thoughts-on-a-canonical-data-model/> — 전사 정본 모델 비판 — 2차/실무
- **[S35]** <https://genehughson.wordpress.com/2013/03/25/canonical-data-models-esbs-and-a-reuse-trap/> — 경계 내 정본 교환 옹호(반증 검색으로 확보) — 2차/실무
- **[S40]** <https://www.fao.org/agrovoc/linked-data> — AGROVOC 외부 어휘 정렬 — 1차/기관
- **[S42]** <https://id.loc.gov/authorities/subjects/sh95008574> — LCSH: Java (Computer program language) — 1차/기관
- **[S43]** <https://id.loc.gov/authorities/subjects/sh85069786> — LCSH: Java (Indonesia) — 1차/기관
- **[S44]** <https://www.palantir.com/docs/foundry/architecture-center/ontology-system/> — "The Ontology is not a semantic layer", Language+Engine+Toolchain — 1차/벤더
- **[S45]** <https://www.palantir.com/docs/sitemap.xml> — Foundry 문서 인벤토리(954KB) — 1차/벤더
- **[S46]** <https://doi.org/10.1023/A:1005323618026> — "meta-ontology" 1998년 선행 용례(Crossref) — 1차/학술
- **[S47]** <https://vldb.org/pvldb/vol14/p3014-cheng.pdf> — RAMP-TAO (VLDB 2021) §7: stale-snapshot 트레이드오프 인식 — 1차/논문
- **[S48]** <https://medium.com/airbnb-engineering> — Himeji: 850,000 entities/s, 99.9990%, P50 1.8ms/P95 7ms/P99 12ms, Aurora — 1차/기업
- **[S49]** <https://linen.authzed.com/> — SpiceDB 커뮤니티: 권한 ~50 · 리소스 ~1,000에서 LookupResources가 DB·CPU·메모리 압도, 유지보수자 "non-optimal" 인정 — 1차/커뮤니티
- **[S50]** <https://github.com/ory/keto> — v26.2.0 태그: `max_read_depth` 기본 5, 깊이 소진이 false로 표현, Expand 교집합/부정 미포함 — 1차/소스
- **[S51]** <https://eurovoc.europa.eu/> — concept 31800: digital/data/technological/tech/cyber sovereignty를 altLabel로 통합 — 1차/기관
- **[S52]** <https://obofoundry.org/principles/fp-006-textual-definitions.html> — 원칙 6: 대다수 클래스에 텍스트 정의 요구 — 1차/표준 기구
- **[S53]** <https://www.palantir.com/docs/foundry/object-permissioning/> — 읽기 시점 행·열·셀 정책 — 1차/벤더
- **[S54]** <https://www.palantir.com/docs/foundry/pipeline-builder/core-concepts/> — PB는 상류 저작 도구 — 1차/벤더
- **[S55]** <https://www.palantir.com/docs/pagefind/pagefind.js> — 색인 직접 질의(부재 증명의 실제 근거) — 1차/벤더 색인
- **[S56]** <https://github.com/park-kyungchan/palantir-mini-marketplace> — PR #17, #29의 "메타온톨로지" 외부 사용례 — 1차/제3자
- **[S57]** <https://www.nao.org.uk/> — Homes for Ukraine 감사 — 1차/정부감사
- **[S58]** <https://mhclgdigital.blog.gov.uk/> — 대체 시스템 이관 보고 — 1차/부처
- **[S59]** <https://www.bbc.com/> — Homes for Ukraine 계약 보도 — 2차/언론
- **[S60]** <https://www.computerweekly.com/> — Bartlett의 NHS FDP 1인칭 실명 계정(2편) — 2차/언론·1인칭
- **[S61]** <https://csrc.nist.gov/pubs/sp/800/162/final> — NIST SP 800-162: ABAC를 일반 방법론으로 규정 — 1차/표준
- **[S62]** <https://www.microsoft.com/en-us/research/project/graphrag/> — GraphRAG의 정의 범위(사설 텍스트 코퍼스 QA) — 1차/연구

---

### 방법 노트

- 3축 / 8 멤버 / 반증검색·회의론자 통과를 합성 인용의 전제 조건으로 걸었다.
- 단일 1차 출처만 있는 주장(원전 수치, 표준 조문, 벤더 문서, 코드 직접 관측)은 **예외로 표시하고 예외임을 본문에 남겼다.**
- **부재 주장**은 두 워커의 독립 관측과 정확 리터럴 스캔이 있을 때만 서술했고, 없을 때는 미해결로 남겼다(§6).
- 세션 원장: `.omo/ulw-research/20260909-094426/` (claim-graph 48개 노드, sources-ledger, debate-log R1–R5, 스크린샷 20장).
