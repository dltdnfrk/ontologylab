# OntologyLab — 제품 명세서

```yaml
schema_version: 1
doc_id: ontologylab-product-spec-001
project: ontologylab
status: canonical
owner: hyunjun (human-approval-required)
baseline_commit: c6bf0d0860025ad9e49977e1964163c65307cdfb
class: revision
supersedes: ontologylab-product-spec-001 @ baseline d4039a8 (2026-08-01)
created_at: 2026-08-01
revised_at: 2026-08-03
source_interview: interview_20260802_095257
source_seed: seed_80779f6e49b1
seed_lineage: seed_4beda6e95da5 (2026-08-01, 퇴역 — MUNI 첫 도메인 팩 목표)
build_agent: Claude Fable
governance_standard: MUNI/Ouroboros/documentation-governance (2026-08-01 확정)
approvals:
- approved_by: hyunjun
  approved_at: 2026-08-01
  gate: draft-to-canonical
  checks: G0 경계 확인 통과(정본 경로·origin·HEAD·단일 워크트리 일치, 실행 중인 Ouroboros job 없음); G1 완전성 검사 통과(필수 6필드 + AC별 verification_method 존재) 및 충돌 검사 통과(다른 canonical 문서 부재, F2 문서 정합 리뷰 통과)
- approved_by: hyunjun
  approved_at: 2026-08-02
  gate: owner-directed-revision
  checks: 후속 인터뷰(interview_20260802_095257, ambiguity 0.163) 완료 및 후속 Seed(seed_80779f6e49b1) 생성 확인 후 소유자 지시로 도메인 정정 적용
```

> **상태 안내**: 이 문서는 `canonical`이다. 2026-08-01 사람 승인으로 `draft`에서
> 승격됐고(검사 기록은 front matter의 `approvals` 참조), **2026-08-02 소유자 지시로
> 도메인 정정**이 적용됐다 — 첫 도메인이 "MUNI 포트폴리오 자체"에서
> **농화학·식물의학(작물보호)** 으로 바뀌었다. 정정의 근거와 폐기된 조항은
> `### 정정 이력`의 2026-08-02 항목에 기록되어 있다.
> 이 프로젝트는 포트폴리오 거버넌스의 **파일럿 1순위**다.

---

## 1. 존재 이유

**local-first 단일 사용자 지식그래프 파이프라인.**

> **The AI proposes; a human decides; only verified facts ship.**

모든 추출 노드와 엣지는 `proposed` 상태로 태어나 명시적 사람 승인으로만 `verified`가 된다.
**구현 상태(현재)**: 사람은 `approve()` 또는 `reject()`로 제안을 판정하고, `reopen()`으로
승인·거절을 다시 `proposed`로 되돌릴 수 있다(`ontologylab/kgstore.py`). 엣지는 W13 이중시간
필드 `invalidated_ts`로 과거 이력을 보존한 채 현재 유효성을 끝낼 수 있고, 팩에는 빌드 시점에
`verified`이고 `invalidated_ts IS NULL`인 현재 유효 엣지만 출고된다(`ontologylab/packbuilder.py`).
흐름: 수집 → LLM 추출 → 사람 검증 → 불변 지식 팩 → 로컬 MCP 서버(읽기 전용) 노출.

**현재 도메인: 농화학·식물의학(작물보호).** 학술 문헌에서 방제 관계, 작용기작과 저항성,
잔류·안전성, 제형·약효시험 지식을 추출해 사람이 검증하고, 에이전트가 MCP로 쿼리한다.

**빌드 에이전트가 성격을 규정한다.** 이 프로젝트는 Claude Fable로 만드는,
**Claude 가드레일 안에서 만들 수 있는 버전**이다.
규제·이중용도 도메인을 비목표로 두는 경계는 **제품 결정이 아니라 도구 제약에서 왔다.**
다만 실제 커넥터 제약은 도메인·주제 필터가 아니라 `connectors/allowlist.py`의 엔드포인트
**deny-by-default allowlist**다. 기본 허용 대상은 소프트웨어 문서와 공개 학술 메타데이터이며,
`europepmc`와 `clinicaltrials`도 이미 허용되어 있어 주제 수준 차단은 존재하지 않는다.
이 구분을 명시해 두어야 도구 제약에서 온 경계를 제품 결정이나 주제 필터로 오해하지 않는다.

## 2. 대상 사용자 — 사람이 아니라 에이전트

**결정적 차이는 소비자다.** MCP 서버로 지식을 노출하며, MCP의 클라이언트는 사람이 아니라
**에이전트**다. 이것이 이 프로젝트가 포트폴리오의 다른 과학 프로젝트와 근본적으로 다른
지점이며, **MCP 노출이 부가 기능이 아니라 정체성인 이유**다.

- 용도: 연구 목적 및 제품 R&D. 외부 판매 대상이 아니다.
- 전달 형태: 로컬 웹앱 + 로컬 MCP 서버. 클라우드 없음, 멀티유저 없음.
- 품질 기준: 상용화 수준 그 이상.

## 3. 포트폴리오 내 위치 — 정직한 전제

**Mucha–Nipo 루프는 OntologyLab 없이도 닫힌다.** 이 프로젝트는 그 루프의 필수
구성요소가 아니다. 없어도 예측→실험→실측→보정 순환은 완결된다.
이 사실을 부정하고 존재 이유를 만들어내는 것이야말로 이 포트폴리오가 경계해 온
근거 없는 주장이 된다.

**대신 다른 층위의 문제를 푼다.** Mucha의 문헌 지식은 Mucha의 계산 파이프라인이 쓰고,
Nipo의 증거는 연구자가 쓴다. OntologyLab의 지식은 **에이전트가 쓴다.**

### Mucha와의 중복은 실제로는 중복이 아니다

두 프로젝트가 "문서에서 지식을 뽑아 사람이 검증하고 축적한다"는 절차는 같고,
도메인 정정 이후 둘 다 농화학 문헌을 다룰 수 있어 겹쳐 보이기 쉽다.
그러나 **대상 지식의 소비자가 다르다** — Mucha는 문헌 지식을 자기 계산 파이프라인의
입력으로 축적하고, OntologyLab은 방제 관계·작용기작·저항성·잔류·시험 지식을
**에이전트가 쿼리할 형태**로 축적한다. 같은 문헌을 읽어도 서로 다른 소비자를 위해
다른 형태로 축적하는 것이지, 같은 일을 두 번 하는 것이 아니다.

구현 코드는 공유하지 않는다. 프로젝트 경계 규칙상 한 세션에서 두 프로젝트를 다루지
않으며, 단일 사용자 도구 두 개에서 코드 공유의 이득보다 결합 비용이 크다.
OntologyLab이 먼저 검증한 제안→검증 상태 전이 패턴을 Mucha가 **참조 모델**로 삼는
것까지가 적정 수준의 관계다.

## 4. 첫 도메인 — 농화학·식물의학(작물보호)

**2026-08-02 후속 인터뷰(`interview_20260802_095257`)로 확정됐다.**
이전 결정("첫 도메인 팩은 MUNI 포트폴리오 자체")은 **폐기**됐다.
폐기 근거는 정직하게 기록한다:

1. **코드 궤적이 반박했다.** 2026-08-01 Seed 확정 후 나흘간 MUNI 팩 관련 코드는 0줄이었고,
   프리셋·커넥터·측정은 전부 생의학/농화학 방향으로 움직였다
   (`biomedical` 프리셋 8/11 타입, 생의학 논문 20편 기준 품질 측정)
2. **실제 전문성이 있는 도메인이다.** 이 도메인의 검토 큐를 소유자가 실제로 판정할 수
   있어야 사람 게이트가 의미를 가진다
3. **벤치마크가 자연스럽다.** "병원체 X를 작물 Y에서 무엇이 방제하는가"는 출처가 검증
   가능한 실제 질문이고, MUNI 고고학 질문 7개보다 반증 가능하다

### 범위 — 네 축 전부 (2026-08-02 확정)

(a) **방제 관계** (병원체·해충·잡초 × 작물 × 유효성분/제품)
(b) **작용기작·저항성** (FRAC/IRAC/HRAC 분류, 표적, 변이, 기작)
(c) **잔류·안전성** (MRL, 수확전 간격(PHI), 독성, 비표적 생물, 규제)
(d) **제형·약효시험** (제형, 살포 방법, 용량, 생육단계, 시험과 결과)

네 축을 한 온톨로지로 둔다 — 한 논문이 여러 축을 동시에 다루므로 나누면 같은 문서를
네 번 추출해야 한다.

### 구축 선행조건 — 충족됨: agrochem-v1 프리셋

**구현 상태(완료, 커밋 `9da8fa4`)**: `agrochem-v1` 프리셋이 엔티티 26종·관계 30종으로
설치 가능하며 `tests/test_agrochem_schema.py` 10개가 불변식을 고정한다
(`ontologylab/schemas.py`). 등록 식별자는 속성으로 박혀 있다 — 생물은 `eppo_code`,
유효성분은 `cas_number`, 작용기작은 `scheme`+`code`(FRAC/IRAC/HRAC), 생육단계는
`bbch_code`. 문자열 유사도는 "Botrytis cinerea"와 "잿빛곰팡이병"을 절대 잇지 못하므로
이 식별자들이 유일하게 신뢰할 수 있는 조인이다(D8 참조).

실측된 대가: agrochem-v1의 스키마 블록은 7,882자(약 1,970토큰)로 1,500토큰 청크
예산보다 크고, 추출 호출의 61%가 스캐폴이다(biomed-v1은 26%). **측정이 먼저**라는
결정이 후속 인터뷰에서 확정됐다 — 설명을 깎기 전에 `TARGET_CHUNK_TOKENS`를 올려
재는 것이 첫 레버다(§11 미결정 사항 참조).

## 5. 성공의 정의 — 출처와 시점이 붙은 답

### 에이전트가 답을 얻어야 하는 질문

> **"병원체 X를 작물 Y에서 무엇이 방제하는가, 어떤 작용기작으로, 저항성이 보고됐는가 —
> 그리고 그 답은 어느 문헌의 어느 시점 기준인가."**

답이 없으면 추측이 아니라 **"모른다"**다. 이 질문 하나에 방제 관계·작용기작·
저항성 세 축이 모두 들어가며, 출처와 기준 시점 요구는 D2를 그대로 물려받는다.

### 판정의 실질적 형태 (후속 Seed의 종료 조건)

1. **Pack serves sourced answers** — 알려진 병원체·작물 조합에 대한 MCP 쿼리가
   출처 문서와 기준 시점이 붙은 엣지를 반환하거나, 입증되지 않은 조합에는
   'unknown'을 반환한다
2. **Staleness observable** — 팩 매니페스트가 `basis_commit`과 생성 시각을 담고,
   MCP live 티어가 쿼리 시점 계산의 `pending_verified_count`를 노출하며,
   문서화된 기본 신선도 정책이 매니페스트에 내장된다
3. **Entity identity canonical** — EPPO 동의어·통용명이 코드로 해소되고 유효성분이
   CAS 번호로 해소되며, 해소 실패는 삭제가 아니라 플래그이고, 캐시 부재는 경고
   하나와 코드 미부착으로 저하한다
4. **Regression guard** — 기존 테스트 전체(1213개)가 계속 통과한다

이전 성공 정의("MUNI 고고학 질문 7개에 팩이 답한다")는 도메인 폐기와 함께 퇴역했다.
정정 이력의 2026-08-02 항목 참조.

## 6. 확정된 결정

### D1. 정확성이 커버리지보다 우선한다

**틀린 답을 하느니 모른다고 답해야 한다.** 에이전트는 받은 지식을 근거로 코드를 작성하므로
잘못된 지식의 피해가 사람이 잘못 읽는 경우보다 크다.
커버리지가 절반이어도 그 절반이 정확하면 유용하지만,
커버리지가 완전해도 일부가 틀리면 전체를 신뢰할 수 없게 된다.

### D2. 답에 반드시 붙어야 하는 두 가지

1. **근거 출처** — 어느 문서에서 나온 답인지 에이전트가 확인할 수 있어야 함
2. **기준 시점** — 팩은 불변이므로 내용이 갱신되지 않고 새 팩이 생성된다.
   따라서 답에 이 팩이 어느 시점·어느 커밋 기준인지가 포함되어야 하고,
   그래야 에이전트가 팩이 낡았을 가능성을 스스로 판단할 수 있다.
   **낡은 지식을 최신인 것처럼 제공하는 것이 이 도구의 가장 위험한 실패 모드다.**

**구현 결정(2026-08-02 후속 인터뷰 R9–R10)**: 매니페스트는 `basis_commit`과 생성 시각을
담는다(미구현, §13 참조). `pending_verified_count`는 **팩 안에 넣지 않는다** — 수동 빌드
직후에는 항상 0이 되어 신호가 죽기 때문이다. MCP live 티어가 쿼리 시점에
(스토어의 verified 수 − 최신 팩 반영 수)를 실시간 계산해 노출한다. 기본 신선도 정책
하나는 매니페스트에 문서화된 기본값으로 내장하되, 소비자가 재정의할 수 있고 강제
불리언 `stale` 플래그는 두지 않는다 — "낡음"은 소비자 상대적이나, 각자 정책을 발명하게
두는 것이 지목된 실패 모드이므로 배포된 기본값이 필요하다.

### D3. 팩이 담지 않는 것

팩은 원본 문서의 대체가 아니다. **문헌의 정본은 문헌이고 명세의 정본은 명세 문서다.**
팩이 담는 것은 **관계·주장·근거·시점**이다.
문헌 본문을 팩에 복제하면 즉시 낡고 두 개의 진실이 생긴다
(문서 거버넌스 표준의 본문 중복 금지 원칙과 동일).

### D4. 권위 — 팩은 파생 뷰다

팩은 생성된 뷰이며 원본 문서를 대체하지 않는다.
**팩과 원본이 다륩면 언제나 원본이 옳고 팩이 낡은 것이다.**

### D5. 시제 충돌은 둘 다 기록한다

2015년 논문의 "보스칼리드가 잿빛곰팡이병에 유효"와 2023년 논문의 "SdhB 변이로 저항성
발생"은 **둘 다 참**이다 — 같은 대상의 다른 시점에 대한 주장이므로.
**기록하고 각각의 기준 시점을 라벨링하며, 새 논문이 이전 주장을 조용히 덮어쓰지
않는다**(2026-08-02 후속 인터뷰 Q2'(a)로 확정). 이중시간 컬럼(`valid_from` /
`invalidated_ts`)이 시점을 지고, `resistant_to` 관계가 이 패턴을 어휘로 옮긴다
(`tests/test_agrochem_schema.py`가 공존과 은퇴 보존을 고정한다).
은퇴는 삭제가 아니며, **사람이 한 번 승인한(verified) 엣지만 은퇴할 수 있다** —
제안 단계에서 틀린 것은 은퇴가 아니라 거절이다.

**진짜 모순**(같은 시제, 같은 대상에 대한 상반된 주장)의 자동 감지는 **후속 웨이브로
유예**됐다. 정확성 요구는 위 기록 방식으로 이미 충족되며, 없는 것은 감지뿐이고
그것은 리뷰어 편의지 팩의 정확성 요소가 아니다. 구현 시에는 온톨로지 스키마에
`conflicts_with` 선언이 필요하다(§11 참조).

### D6. 생성 차단 대신 안전한 실패

- **팩 생성 자체는 차단하지 않는다.** 미해소 항목은 상시 존재하므로 하나라도 있으면
  만들지 않는 규칙은 팩이 영원히 나오지 않는다는 뜻이 된다
- **쿼리 시점에는 경고 대신 "모른다"고 답한다.** 팩에 없으면 없다고 말하고 에이전트가
  원본을 보러 가게 한다. **경고는 무시되지만 답이 없으면 에이전트는 원본을 확인할 수밖에 없다**
- **제외된 미검증 항목 목록이 곧 사람의 작업 큐가 된다.**
  커버리지 압박이 정확성을 침식하지 않는 구조다

라이프사이클 상태가 `rejected`인 항목과 미검증 상태로 남은 `proposed` 항목은 모두 팩에
들어가지 않으며, **"팩에서 제외"는 상태명이 아니라 팩 미포함 결과를 서술하는 표현**이다.
**구현 상태(현재)**: `reopen()`은 `verified` 또는 `rejected` 판정을 `proposed`로 되돌리고,
엣지의 `invalidated_ts`는 이중시간 이력을 보존하면서 현재 유효성만 끝낸다
(`ontologylab/kgstore.py`). 팩은 빌드 시점의 verified-only 스냅샷이므로, 검증 후 다시 열린
항목도 이미 출고된 불변 팩에는 남고 다음 팩에서 빠진다(D4와 일치).

### D7. 갱신 — 팩 생성은 수동, 낡음은 관측한다

1. **수집·추출**: 사람이 시작한다(HTTP `POST /collect` 또는 CLI `collect`)
2. **검증**: 사람이 한다. 자동화하지 않는다
3. **팩 생성**: 사람이 자른다 — 승인이 쌓인 뒤 명시적 빌드 명령

**갱신 주기보다 낡음의 관측 가능성이 중요하다**는 결정이 2026-08-02에 구체화됐다:
팩 생성을 수동으로 두는 대신, MCP가 live 계산의 `pending_verified_count`를 노출해
"언제 잘라야 하는가"를 일정이 아니라 관측된 상태로 판단한다(D2 참조).
스케줄 트리거는 두지 않는다.

### D8. 식별자 정규화 — 코드는 기계가, 이름은 모델이 (2026-08-02 신규)

**LLM 추출기는 표면 이름만 내고 식별자 코드는 절대 내지 않는다.**
모델이 만든 EPPO/CAS 코드는 검증 불가한 환각 미끼다.
코드 부착은 추출과 검토 사이의 **별도 정규화 단계**가 한다:

- **생물**(Crop·Pathogen·Pest·Weed): EPPO 코드가 정본 키. 동의어·통용명 테이블을
  포함한 스냅샷으로 해소한다 — 선호 학명만 매핑하면 모든 통용명이 "미해소" 플래그가
  되어 리뷰어를 물리게 만든다
- **유효성분**: CAS 번호가 정본 키. PubChem 동의어 테이블(퍼블릭 도메인)로 해소.
  FRAC/IRAC/HRAC 분류표에서 유효성분 → 작용기작 군을 해소(군 번호는 사실, 문서는
  저작권 대상이므로 추출된 사실만 로컬 캐시에 둔다)
- **라이선스**: EPPO Global Database 등 레지스트리 데이터는 **저장소에 재배포하지
  않는다.** 로컬 gitignored 캐시를 명시적 fetch 명령으로 만들고 출처와 취득일을
  provenance에 기록한다. 저장소는 코드와 스키마만 담는다
- **미해소**: 삭제하지 않는다. "no EPPO match" 플래그를 붙여 검토 큐로 본내고,
  리뷰어는 예외만 본다(모든 승인을 검사하지 않는다)
- **캐시 부재**: 하드 실패도 항목당 예외 폭주도 아니다. 실행 시작에 provenance 경고
  하나("EPPO cache absent")를 남기고 코드 없이 진행한다. 테스트 스위트는 캐시를
  요구하지 않는다(다른 오프라인 테스트와 같은 fixture 방식)

### D9. MCP 읽기 범위 — 팩 전용에서 라이브 읽기 티어 추가 (2026-08-02 신규)

MCP 표면은 **접하는 모든 시스템 상태에 대해 읽기 전용**이며 쓰기 경로는 노출하지
않는다. 현재 MCP 서버는 불변 팩만 서빙하고(`mcp_server.py`는 `pack.sqlite`만
읽기 전용으로 연다), `test_mcp_two_tier.py`의 "two-tier"는 live/pack이 아니라
**응답 세분도 티어**(compact 목록 행 vs `get_entity`의 full 레코드)를 가리킨다.
따라서 D2의 낡음 신호를 위해서는 **라이브 읽기 티어를 새로 추가**해야 한다:
MCP가 작업 스토어(kg.sqlite)를 읽기 전용으로 함께 열어, `pending_verified_count`를
쿼리 시점에 (스토어의 verified 수 − 최신 팩 반영 수)로 계산해 노출한다.
pack 티어는 verified-only·불변을 유지한다.

**정정 기록**: 이 조항의 첫 판(2026-08-02, 커밋 `67fdf96`)은 "코드베이스가 이미
live+pack 2티어를 결정필놨다"고 `test_mcp_two_tier.py`를 근거로 썼으나,
구현 착수 직전 확인에서 그 테스트는 응답 세분도 티어를 검증하는 것이었고
라이브 티어는 존재하지 않는 것으로 드러났다. 인터뷰 라운드 11의 같은 진술도
같은 오류다. 결정 자체(라이브 읽기 티어를 둔다)는 유지하되, 그것은 기존 구조의
인용이 아니라 이번에 새로 만드는 표면이다.

### D10. 제안 원자성 — 엣지 단위 (2026-08-02 신규)

사람이 한 번에 승인하는 단위는 **개별 노드/엣지**다. 이는 새 결정이 아니라 코드베이스의
기존 구조를 명문화한 것이다: `approve()`/`reject()`는 개별 id에 작용하고, 검토 큐는
항목 단위이며, conformal 트리아지는 항목 단위로 채점하고, `invalidate_edge()`는 정확히
한 엣지를 은퇴한다. 따라서 **부분 승인**(방제 관계는 받고 저항성 주장은 제2 출처를
기다리며 보류)과 **사실 단위 철회**가 구조적으로 가능하고,
`pending_verified_count`는 문서가 아니라 항목(노드+엣지)을 센다.

## 7. 수락기준

후속 Seed(`seed_80779f6e49b1`)의 수락기준을 따른다. 아래 marked table이 현재 상태의
단일 정본이다. `python scripts/check_product_status.py`가 필수 ID, 상태, 근거 경로,
그리고 blocking/non-blocking 후속 단계의 모순을 검사한다.

<!-- product-status:v1:start -->
| ID | Status | Evidence | Follow-up |
|---|---|---|---|
| AC-01 | COMPLETE | `tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy`, `tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness`, `tests/test_staleness.py::test_same_stable_id_material_change_is_replacement`, `tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store` | NONE |
| AC-02 | COMPLETE | `tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once`, `tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively`, `tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier`, `tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped`, `tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties`, `tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas`, `tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped` | NONE |
| AC-03 | COMPLETE | `docs/FIRST-PACK-EVIDENCE.md`, `tests/test_mcp_two_tier.py::test_get_entity_full_record`, `tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface` | NONE |
| CHUNK-SWEEP | COMPLETE | `docs/CHUNK-SWEEP-2026-08.md`, `scripts/sweep_chunk_size.py` | NON-BLOCKING: 대표 실제 corpus에서 3,000-token 결정을 재검증 |
<!-- product-status:v1:end -->

- **AC-01** (`ac_2a92f910cec12ead`): `basis_commit`, 생성 시각, 기본 정책,
  live `pending_verified_count`, 그리고 semantic additions/invalidation/replacement까지
  구현·검증됐다.
- **AC-02** (`ac_467f41806cb0cf7c`): EPPO 코드와 CAS/MoA 정규화, 미해소 플래그,
  import-first cache 및 honest absence가 구현·검증됐다.
- **AC-03** (`ac_b957dcaa757af568`): 읽기 전용 MCP 2-tier 도구와 첫 agrochem
  pack의 출처 기반 응답 증거가 있으며, 신선도 결과도 함께 노출된다.
- **AC-04 회귀 가드**: 전체 suite가 계속 통과해야 한다. 개수는 기능 추가 때마다
  변하므로 명세에 고정하지 않고 CI/검증 출력으로 증명한다.

2026-08-03 아키텍처 무결성 근거: durable extraction `5b93f94`, incomplete-pack
gate `31deb06`, semantic staleness `7248024`, FastAPI app-state isolation
`eedb3d5`. 이 커밋들은 제품 수락기준을 바꾸지 않고, 그 기준을 부분 상태나
process-global leakage 없이 지키게 한다.

**퇴역**: 2026-08-01 표의 AC-03(MUNI 팩 7개 질문 응답)과 AC-04(고고학 벤치마크)는
도메인 폐기와 함께 퇴역했다. `tests/test_portfolio_benchmark.py`는 만들어지지 않으며
만들 계획도 없다. 나머지 2026-08-01 AC(게이트·불변·읽기 전용·안전 실패)는 새 AC에
흡수되거나 기존 테스트로 계속 충족된다.

**공통 증거 요구 4속성**(거버넌스 유지): `target_commit`, 불변 `evidence_ref`,
`verified_by`, `verified_at`.

### 7.1 증거 게이트의 위협 모델 — 무엇을 막고 무엇을 막지 않는가

`scripts/check_product_status.py`는 위 표의 주장을 실제 실행으로 뒷받침한다. 그 게이트가
막도록 설계된 것과 **설계상 막지 않는 것**을 여기에 명시한다. 경계를 문서에 적지 않으면
다음 검토자에게는 결함으로, 다음 관리자에게는 보장으로 읽힌다. 둘 다 틀리다.

**막는 것 — 사고(accident)의 형태.** 아래 각 항목은 이 커밋 시점에 재현된 뒤 회귀
테스트로 고정됐다.

- 같은 이름의 정의가 파일에 둘 이상 있거나(잘못된 병합), 이름이 나중에 다른 객체로
  재바인딩된 경우
- 클래스가 통째로 재바인딩되어 속이 빈 메서드를 가리는 경우
- 함수가 **같은 파일의 다른 함수**로 재바인딩된 경우
- 모듈 수준 상수·조회표가 파일이 선언한 값과 다른 값을 들고 있는 경우
- 디스크의 소스와 실제로 실행되는 코드 객체가 다른 경우
- 존재하지 않는 파일명으로 코드가 실행되는 경우(예: 원본 `.py`가 사라진 낡은 `.pyc`)
- `sys.modules`에 등록되지 않고 실행되는 모듈
- 출처(origin)를 선언하지 않는 모듈
- 자식 프로세스에서 site 디렉터리의 시작 코드(`.pth`, `sitecustomize`)가 실행되는 경우
- 감사 대상 트리 자체가 라이브러리 면제 목록에 올라가는 경우
- 감사 실행이 감사 대상 트리에 쓰기를 하는 경우

즉 **잘못된 병합, 낡은 바이트코드, 리팩터링 잔재** — 실제로 일어나는 실패들이다.

**막지 않는 것 — 이 체커를 겨냥해 작성되어 추적 파일로 커밋된 코드.** 알려진 사례
셋을 구체적으로 적는다.

1. 실행 비밀키(run secret)는 자식 프로그램 `__main__`의 전역으로 접근 가능하다.
   제품 코드에서 읽어 위조 보고서에 서명할 수 있다.
2. 첫 부모 프로세스에서 비밀키 배출 이전에 실행되는 시작 코드·표준 라이브러리 가림.
   `python scripts/check_product_status.py`는 호출에 `-P`가 없으면 실제 모듈보다
   `scripts/subprocess.py`를 먼저 가져온다.
3. `LIBRARY_ROOTS`에 있는, 해시되지 않은 설치 의존성(pytest, pluggy 등)의 변조.

**경계가 여기 있는 이유.** 그런 파일을 커밋할 수 있는 사람은 위의 수락기준 표를 직접
고칠 수도 있다. 저장소 안에 있는 체커는 저장소를 이길 수 없다. 이것은 변명이 아니라
정직한 논거이며, 그래서 게이트의 목표를 "적대적 커밋 방지"가 아니라 **"사고 저항"**으로
정의한다.

**운영상 귀결 하나.** 첫 부모의 가림(2번)은 체커 내부에서 닫을 수 없다. CI는 체커를
`-P`와 함께 호출하거나, 체커를 `scripts/` 바깥으로 옮겨야 한다.


## 8. 비목표

- 멀티유저·클라우드 배포
- 물리 하드웨어
- **규제·이중용도 도메인** (커넥터 deny-by-default allowlist) —
  **도구(가드레일) 제약에서 온 경계이며 제품 결정이 아니다**
- **국내(한국어) 문헌·국내 등록DB** — 2026-08-02 확정, 국제 소스 우선. 재검토 시
  한국어 청킹(`CHARS_PER_TOKEN = 4`의 영어 편향)이 선행 과제다
- **PPDB 등 레지스트리 전면 수집** — EPPO부터, 나머지는 후속 웨이브
- **교차 문서 모순 자동 감지** — D5의 유예 결정 참조
- **MUNI 포트폴리오 팩** — 첫 도메인 결정 폐기에 따라 무기한 유예
- **데스크톱 셸(Tauri·Electron 등) 패키징** — 2026-08-02 확정. UI는 브라우저에서
  도는 웹앱이다. FastAPI가 `web/`을 `/static`에 마운트하고 `/`에서 대시보드를
  서빙하는 지금 구조가 최종 형태이며, 로컬 단일 사용자라는 제약이 네이티브
  셸을 요구하지 않는다. 배포 편의를 이유로 셸을 씌우면 브라우저에서 열던
  워크플로가 앱 실행에 묶이고, MCP·서버와 별개의 업데이트 경로가 하나 더 생긴다.
- 후보 코드 실행
- 문헌·명세 본문의 팩 복제
- 팩이 원본 문서의 권위를 대체하는 것
- 판매용 상용 기능

## 9. 운영 부담의 상한

팩 생성이 사람에게 부담이 되면 갱신이 밀리고 팩은 낡는다.
따라서 **검증 큐 검토가 짧게 끝나야 한다.** 추출 후보에 근거 링크가 붙어 있어
사람이 원문을 다시 찾지 않아도 되는 것이 그 조건이다.
**우회 신호로 관측**한다 — 검증 큐가 계속 쌓이기만 하고 처리되지 않으면
그것이 부담 과다의 신호다. 승인 처리량의 명시적 상한은 두지 않는다(2026-08-02 확정).

## 10. 운영 전제

1. **실데이터 경로**: 이 설치의 live data dir은 `~/Library/Application Support/ontologylab/data`다.
   `./data/kg.sqlite`는 **STALE**이며, iCloud 동기화 경로가 감지되면
   `paths.icloud_refusal`이 동기화하지 않고 서버를 종료한다(`ontologylab/paths.py`).
2. **추출 테스트 엔진**: `MockEngine`은 CamelCase 토큰 기반이라 실제 산문에서는 추출
   결과가 0건이다(`ontologylab/engines.py`). 농화학 텍스트는 라틴 이명과 소문자
   유효성분이 주라 특히 그렇다. 추출 품질 검증에는 `--engine claude` 또는
   `api:<provider-id>` 엔진을 사용한다.
3. **pytest 출력**: `pyproject.toml`이 이미 `pytest -q`를 설정한다. `verify_command`에
   `-q`를 더하면 `-qq`가 되어 요약이 숨으므로 추가하지 않는다.
4. **샘플러 선택**: 추출 샘플링 파라미터는 `extract --temperature/--top-p`로 선택
   가능하며(기본: 고정 0.0), 공급자 종류별 허용 키가 다르다(Anthropic은 `top_k`,
   OpenAI 호환은 `seed`). 선택값은 매 행의 `decode_params`에 기록되고
   `eval --engine/--model/--prompt-version/--decode-params`로 스트림별 채점이
   가능하다(커밋 `ab6e183`).

## 11. 미결정 사항

1. **대표 실제 corpus 재검증** — 1,500 대 3,000 synthetic sweep는 완료됐다.
   첫 대표 실제 corpus에서 품질 비열화와 비용 절감을 다시 확인하기 전에는
   3,000을 도메인 독립 최적값으로 일반화하지 않는다
2. **축별 추출 품질** — agrochem-v1의 네 축이 골고루 추출되는지, 스트림 필터가
   붙은 평가 하니스로 골드 세트 기준 측정. 골드 세트 자체가 미래 산출물
3. **모순 감지 웨이브** — `conflicts_with` 스키마 선언 + clash 스캐너(D5 유예분)
4. **국내 소스 재검토 시점** — 한국어 청킹 수정과 국내 커넥터가 세트
5. **레지스트리 확대 순서** — EPPO 이후 PPDB, EU Pesticides DB, FRAC 분류표 갱신 절차

## 12. 관련 문서와 추적

- 인터뷰: `interview_20260802_095257` (도메인 확정·후속 요구사항, ambiguity 0.163)
- Seed(현행): `seed_80779f6e49b1` — 스냅샷 `docs/ouroboros-seed-agrochem.yaml`
- Seed(퇴역): `seed_4beda6e95da5` — 스냅샷 `docs/ouroboros-seed.yaml`.
  **계보**: 새 Seed 파일의 `parent_seed_id`는 생성기가 null로 기록했으므로,
  계보는 이 문서가 기록한다 — seed_4beda6e95da5(2026-08-01, MUNI 목표) →
  seed_80779f6e49b1(2026-08-02, 농화학 목표). 퇴역 스냅샷은 불변이므로 편집하지 않는다
- 인터뷰(2026-08-01): `interview_20260801_062141`, `interview_20260801_022908`
- 기존 문서: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/DESIGN-RATIONALE.md`
  (36편 논문 근거)
- ouroboros 게이트: `.ouroboros/mechanical.toml` (`test = "pytest"`)

**거버넌스 파일럿 관련(2026-08-01 확정, 유효)**:
- baseline 이원화 — as-planned 원점은 최초 커밋 `fd511f7`, 거버넌스
  `baseline_commit`은 정본화 시점 HEAD
- 저장소 밖 거버넌스 handoff/index 기록은 historical context이며 이 저장소의
  local evidence path로 취급하지 않는다

## 13. 다음 단계

1. **대표 실제 corpus + 축별 품질 측정** — synthetic chunk sweep의 결정을
   대표 실제 초록에서 재검증하고, 네 농화학 축의 스트림별 F1을 측정
2. **모순 감지 웨이브** — `conflicts_with` 스키마 선언과 clash scanner(D5 유예분)
3. **레지스트리 확대** — 현재 EPPO·CAS/MoA 이후 PPDB, EU Pesticides DB,
   PubChem/FRAC 갱신 절차
4. **국내 소스 재검토** — 한국어 청킹 수정과 국내 커넥터를 한 묶음으로 평가

### 정정 이력

- **2026-08-03 증거 게이트 위협 모델 선언** — §7.1 신설. 게이트가 막는 사고 형태와
  **설계상 막지 않는 것**(이 체커를 겨냥해 작성되어 추적 파일로 커밋된 코드, 알려진 사례
  셋)을 명시했다. 계기: 네 번째 검토에서 `ontologylab/**` 면제가 문서에 없다는 이유만으로
  실제 우회가 통과했다. 면제를 없앤 것이 아니라 계약으로 바꾼 것이며, 기존 검사는 하나도
  약화되지 않았고 digest도 갱신하지 않았다. 수락기준 표·상태·근거 경로는 그대로다.

- **2026-08-01 검수 기반 정정** — ① 상태 용어를 구현 용어 `rejected`로 통일 ② Seed 재생성
  (새 `seed_id` `seed_4beda6e95da5`, 인터뷰 `interview_20260801_062141` 재개) ③ "커넥터
  차단 목록" 서사를 엔드포인트 allowlist 실체로 정정 ④ MUNI 팩 온톨로지 프리셋 선행조건
  명시 ⑤ AC-05/AC-06/AC-08 실현 조건·미구현 표기 ⑥ 운영 전제(데이터 디렉터리·
  MockEngine·`pytest -q`) 추가. 근거: 검수 보고와 코드 인용(`kgstore.py`, `allowlist.py`,
  `models.py`, `schemas.py`, `mcp_server.py`, `paths.py`, `engines.py`).

- **2026-08-01 승격**: 사람 승인으로 `draft`에서 `canonical`으로 승격됐다.
  G0 경계 확인과 G1 완전성·충돌 검사를 통과했고(기록은 front matter `approvals`),
  거버넌스 규칙에 따라 `baseline_commit`이 정본화 시점 HEAD(`d4039a8`)로 갱신됐다.

- **2026-08-02 도메인 정정(소유자 지시)** — 후속 인터뷰 `interview_20260802_095257`
  (ambiguity 0.163)와 후속 Seed `seed_80779f6e49b1`에 기반.
  **폐기**: ① §4 "첫 도메인 팩 — MUNI 포트폴리오 자체"와 그 선행조건 ② §5 "고고학
  질문 7개 + 2026-08-01 세션 벤치마크" 성공 정의 ③ 구 AC-03/AC-04와 종료 조건
  `benchmark_pass` ④ Seed goal의 MUNI 조항 전부.
  **유지**: D1–D7의 원칙(정확성 우선, 출처+시점, 팩은 파생 뷰, 안전한 실패),
  라이프사이클·불변 팩·읽기 전용 MCP·운영 전제.
  **갱신**: D5(시제 충돌은 둘 다 기록, 모순 감지 유예), D7(팩 생성 수동 + 낡음 관측).
  **신규**: D8(식별자 정규화), D9(MCP 2티어 읽기), D10(엣지 원자성), §4/§5 교체,
  AC 표 교체, Seed 계보 기록(§12). 확인 수단: 후속 인터뷰 라운드 8–11의 확정 답변과
  `seed_80779f6e49b1.yaml`.

---

## 커밋 지침 — 경로를 명시해서 스테이징할 것

**2026-08-01 실행 완료**: 이 문서와 `docs/ouroboros-seed.yaml`은 커밋 `d4039a8`으로
경로 명시 스테이징(`git add docs/PRODUCT_SPEC.md docs/ouroboros-seed.yaml`)을 거쳐
커밋됐다. 아래는 당시 적용된 절차의 기록이며, 이후 이 파일들을 수정해 커밋할 때도
같은 규칙이 적용된다.

**반드시 경로를 명시해서 스테이징한다:**

```bash
git add docs/PRODUCT_SPEC.md docs/ouroboros-seed-agrochem.yaml
```

**`git add -A`, `git add .`, `git add docs/`를 쓰지 않는다.**
일괄 스테이징하면 소유자와 완료 상태가 확인되지 않은 기존 변경까지 함께 커밋되어,
2026-08-01에 확정한 귀속·서명 게이트를 걸너뛰게 된다.

기존 미커밋 변경의 처리 절차는 별도로 확정되어 있다 — 귀속 3등급
(ledger 지목 / 증거 2개 수렴 추론 / ownership-unknown), 등급별 허용 행위,
동일 세션 묶음 일괄 서명과 개별 서명 예외. 상세는
`MUNI/Ouroboros/documentation-governance/SESSION_HANDOFF.md` 참조.

---

## 부록 A — Ouroboros Seed

**현행 Seed: `seed_80779f6e49b1`** (2026-08-02, 인터뷰 `interview_20260802_095257`,
ambiguity 0.163).

정본 스냅샷은 **`docs/ouroboros-seed-agrochem.yaml`** 이다. 본문 중복 금지 원칙(D3과
같은 거버넌스 원칙)에 따라 여기에 전문을 다시 인라인하지 않고, goal만 인용한다:

> Build a local-first agrochemistry knowledge graph where LLM-extracted proposals
> from scholarly literature are human-approved into verified immutable packs served
> read-only to agents over MCP, covering control relations, mode of action and
> resistance, residue and safety, and formulation and efficacy trials across
> international sources.

**계보**: `seed_4beda6e95da5`(2026-08-01, MUNI 첫 도메인 팩 목표) →
`seed_80779f6e49b1`(2026-08-02, 농화학·식물의학). 생성기가 `parent_seed_id`를 null로
기록했으므로 계보의 정본은 이 문서의 §12다.
퇴역 Seed의 스냅샷 `docs/ouroboros-seed.yaml`은 불변 스냅샷이므로 편집하지 않고
보존한다.
