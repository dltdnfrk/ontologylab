# OntologyLab — 제품 명세서

```yaml
schema_version: 1
doc_id: ontologylab-product-spec-001
project: ontologylab
status: canonical
owner: hyunjun (human-approval-required)
baseline_commit: d4039a8b2ac9ae46195a03a828d0d285bd9f3495
class: new
supersedes: none
created_at: 2026-08-01
source_interview: interview_20260801_062141
source_seed: seed_4beda6e95da5
build_agent: Claude Fable
governance_standard: MUNI/Ouroboros/documentation-governance (2026-08-01 확정)
approvals:
- approved_by: hyunjun
  approved_at: 2026-08-01
  gate: draft-to-canonical
  checks: G0 경계 확인 통과(정본 경로·origin·HEAD·단일 워크트리 일치, 실행 중인 Ouroboros job 없음); G1 완전성 검사 통과(필수 6필드 + AC별 verification_method 존재) 및 충돌 검사 통과(다른 canonical 문서 부재, F2 문서 정합 리뷰 통과)
```

> **상태 안내**: 이 문서는 `canonical`이다. 2026-08-01 사람 승인으로 `draft`에서
> 승격됐다(검사 기록은 front matter의 `approvals` 참조). `main`이 `origin/main`보다
> 7커밋 앞서 있다(미푸시). 이 프로젝트는 포트폴리오 거버넌스의 **파일럿 1순위**다.

---

## 1. 존재 이유

**local-first 단일 사용자 지식그래프 파이프라인.**

> **The AI proposes; a human decides; only verified facts ship.**

모든 추출 노드와 엣지는 `proposed` 상태로 태어나 명시적 사람 승인으로만 `verified`가 된다.
**구현 상태(현재)**: 사람은 `approve()` 또는 `reject()`로 제안을 판정하고, `reopen()`으로
승인·거절을 다시 `proposed`로 되돌릴 수 있다(`ontologylab/kgstore.py`). 엣지는 W13 이중시간
필드 `invalidated_ts`로 과거 이력을 보존한 채 현재 유효성을 끝내며, 팩에는 빌드 시점에
`verified`이고 `invalidated_ts IS NULL`인 현재 유효 엣지만 출고된다(`ontologylab/packbuilder.py`).
흐름: 수집 → LLM 추출 → 사람 검증 → 불변 지식 팩 → 로컬 MCP 서버(읽기 전용) 노출.

**빌드 에이전트가 성격을 규정한다.** 이 프로젝트는 Claude Fable로 만드는,
**Claude 가드레일 안에서 만들 수 있는 버전**이다.
규제·이중용도 도메인을 비목표로 두는 경계는 **제품 결정이 아니라 도구 제약에서 왔다.**
다만 실제 커넥터 제약은 도메인·주제 필터가 아니라 `connectors/allowlist.py`의 엔드포인트
**deny-by-default allowlist**다. 기본 허용 대상은 소프트웨어 문서와 공개 학술 메타데이터 같은
중립 도메인이며, `europepmc`와 `clinicaltrials`도 이미 허용되어 있어 주제 수준 차단은 존재하지
않는다. 이 구분을 명시해 두어야 도구 제약에서 온 경계를 제품 결정이나 주제 필터로 오해하지 않는다.

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
이 사실을 부정하고 존재 이유를 만들어내면 그것이야말로 이 포트폴리오가 경계해 온
근거 없는 주장이 된다.

**대신 다른 층위의 문제를 푼다.** 세 프로젝트를 한 줄에 세우려는 시도 자체가
잘못된 프레임이다. Mucha의 문헌 지식은 Mucha의 계산 파이프라인이 쓰고,
Nipo의 증거는 연구자가 쓴다. OntologyLab의 지식은 **에이전트가 쓴다.**

### Mucha와의 중복은 실제로는 중복이 아니다

두 프로젝트가 "문서에서 지식을 뽑아 사람이 검증하고 축적한다"는 절차는 같다.
그러나 **대상 지식과 소비자가 다르다** — Mucha는 도메인 문헌을 자기 계산 파이프라인의
입력으로 축적하고, OntologyLab은 방법론·프로젝트 지식을 에이전트가 쿼리할 형태로
축적한다. 같은 패턴을 다른 대상에 적용하는 것이지 같은 일을 두 번 하는 것이 아니다.

구현 코드는 공유하지 않는다. 프로젝트 경계 규칙상 한 세션에서 두 프로젝트를 다루지
않으며, 단일 사용자 도구 두 개에서 코드 공유의 이득보다 결합 비용이 크다.
OntologyLab이 먼저 검증한 제안→검증 상태 전이 패턴을 Mucha가 **참조 모델**로 삼는
것까지가 적정 수준의 관계다.

## 4. 첫 도메인 팩 — MUNI 포트폴리오 자체

지식 대상으로 **MUNI 포트폴리오 자체**를 제안한다.
5개 프로젝트의 확정 결정, 표준, 아키텍처 계약, 인터뷰 산출물, 프로젝트 간 인터페이스.

**근거 4가지**:
1. **필요가 실증됐다.** 2026-08-01 세션에서 5개 프로젝트의 존재 이유가 기술 명세로 남지
   않아 세션 brief와 README와 역사 Git 객체를 뒤져 고고학적으로 복원해야 했다.
   결정은 내려졌으나 에이전트가 조회할 수 있는 형태로 남지 않았기 때문이다
2. **가드레일 제약과 완전히 부합한다.** MUNI 포트폴리오 마크다운은 로컬 파일 수집 경로를
   사용하므로 네트워크 allowlist를 거치지 않는다. 또한 소프트웨어와 기술 문서는 중립
   도메인이므로 가드레일과 충돌하지 않는다
3. **검증 대상이 명확하다.** 결정과 근거는 사람이 확인할 수 있고 이미 확인된 것들이 있다
4. **소비자가 실재한다.** 다음 세션의 에이전트가 바로 쿼리한다.
   가상의 사용자를 상정한 기능이 아니다

### 구축 선행조건 — MUNI 전용 온톨로지 프리셋

**계획 상태(필수, 미구현)**: MUNI 포트폴리오 팩을 추출하기 전에 `Decision`·`Rationale`·
`Boundary`·`FailureRecord`·`InterfaceContract` 타입을 가진 새 온톨로지 프리셋을 먼저
정의해야 한다. 현재 번들 프리셋은 `software-docs`와 `biomedical`뿐이며
(`ontologylab/schemas.py`의 `PRESETS`), 기존 `KGStore.install_schema`로 새 스키마를
추가·활성화할 수 있다. 활성 온톨로지가 추출기에게 찾을 대상을 지정하므로 이는 추출 규칙을
논의하기 전의 설계 선행조건이지 선택적 개선이 아니다.

실측 근거는 서로 다른 두 측정이다. 프로젝트 `CLAUDE.md`는 바이오메디컬 논문 20편에서
`software-docs` 사용 시 관계의 **54%**가 `related_to`였고 `biomed-v1`에서는 **26%**였다고
기록한다. 별도로 `ontologylab/schemas.py` 모듈 docstring은 단일 p53 초록에서 관계 5/5가
`related_to`였고 스키마가 담을 형상이 없던 제안 24건이 거절됐다고 기록한다.

## 5. 성공의 정의 — 고고학을 하지 않아도 되는 상태

### 에이전트가 답을 얻어야 하는 질문 7가지

1. 이 프로젝트는 왜 존재하며 무엇을 만드는가
2. 이미 확정된 결정은 무엇인가
3. 그 결정의 근거는 무엇인가
4. 여기서 하면 안 되는 것은 무엇인가 (비목표·경계·금지)
5. 지금 활성 상태인 작업은 무엇이고 어느 에이전트·세션이 맡고 있는가
6. 프로젝트 간 인터페이스 계약은 무엇인가
7. **이전에 시도했다가 실패한 것은 무엇이며 왜 실패했는가**

일곱째를 특히 강조한다. 다섯 번 실패한 부트스트랩 이력 같은 것이 조회되지 않으면
새 세션이 같은 시도를 반복한다. **실패를 보존한다는 원칙은 이 팩에서도 유효하다.**

### 벤치마크는 2026-08-01 세션 자체다

그날 고고학으로 알아낸 사실들을 **질문과 정답의 쌍**으로 만들어 벤치마크 세트로 삼는다.
팩이 그 질문들에 답할 수 있으면 통과다. 새로 데이터를 만들 필요 없이 이미 확보된
사례로 판정할 수 있다.

### 판정의 실질적 형태

그 세션에서 고고학에 들인 노력(수십 번의 파일 탐색과 Git 조회)이 다음번에는
몇 번의 쿼리로 대체되는가. 반증 가능한 기준:
- 새 세션이 프로젝트 파일을 뒤지지 않고 팩 쿼리만으로 작업 전제를 갖출 수 있는가
- 그날과 같은 복원 작업이 다시 필요한가

## 6. 확정된 결정

### D1. 정확성이 커버리지보다 우선한다

**틀린 답을 하느니 모른다고 답해야 한다.** 에이전트는 받은 지식을 근거로 코드를 작성하므로
잘못된 지식의 피해가 사람이 잘못 읽는 경우보다 크다.
커버리지가 절반이어도 그 절반이 정확하면 유용하지만,
커버리지가 완전해도 일부가 틀리면 전체를 신뢰할 수 없게 된다.

### D2. 답에 반드시 붙어야 하는 두 가지

1. **근거 출처** — 어느 문서의 어느 결정 기록에서 나온 답인지 에이전트가 확인할 수 있어야 함
2. **기준 시점** — 팩은 불변이므로 내용이 갱신되지 않고 새 팩이 생성된다.
   따라서 답에 이 팩이 어느 시점·어느 커밋 기준인지가 포함되어야 하고,
   그래야 에이전트가 팩이 낡았을 가능성을 스스로 판단할 수 있다.
   **낡은 지식을 최신인 것처럼 제공하는 것이 이 도구의 가장 위험한 실패 모드다.**

### D3. 팩이 담지 않는 것

팩은 프로젝트 파일의 대체물이 아니다. **코드의 정본은 코드이고 명세의 정본은 명세 문서다.**
팩이 담는 것은 **결정·근거·경계·관계**다.
코드 내용이나 명세 본문을 팩에 복제하면 즉시 낡고 두 개의 진실이 생긴다
(문서 거버넌스 표준의 본문 중복 금지 원칙과 동일).

### D4. 권위 — 팩은 파생 뷰다

팩은 생성된 뷰이며 원본 문서를 대체하지 않는다.
문서 거버넌스 표준의 권위 순서를 그대로 따른다:
문서 내용은 그 문서 본문이 정본, 프로젝트 운영 상태·소유권은 프로젝트 인덱스가 정본,
포트폴리오 집계는 파생물. **팩과 원본이 다르면 언제나 원본이 옳고 팩이 낡은 것이다.**

### D5. 대부분의 충돌은 시제 차이다

README가 "현재 구현이 이렇다"고 말하는 것은 **as-built** 진술이고,
인터뷰에서 확정한 결정은 **as-planned** 진술이다. 서로 다른 시점을 가리키므로
동시에 참일 수 있다.

항목마다 **결정인지 구현 상태인지를 구분하고 각각의 기준 시점을 붙인다**
(예: "결정 2026-08-01 확정", "구현 상태 커밋 X 기준"). 그러면 에이전트가
두 진술을 모순으로 오해하지 않는다.

**진짜 충돌**(같은 시제, 같은 대상에 대한 상반된 주장)만이 실제 충돌이며,
사람이 해소해야 하고 기계가 어느 쪽을 고를 수 없다. 이런 항목은 검증되지 않았으므로
**애초에 팩에 들어가지 않는다.**

### D6. 생성 차단 대신 안전한 실패

- **팩 생성 자체는 차단하지 않는다.** 포트폴리오 규모에서 미해소 항목은 상시 존재할
  것이므로 하나라도 있으면 만들지 않는 규칙은 팩이 영원히 나오지 않는다는 뜻이 된다
- 생성 시점에는 **탐지와 분류**를 한다. 시제 차이는 표시를 붙여 통과시키고,
  진짜 모순은 미검증으로 분류해 팩에서 제외한다
- **쿼리 시점에는 경고 대신 "모른다"고 답한다.** 팩에 없으면 없다고 말하고 에이전트가
  원본을 보러 가게 한다. 이것이 안전한 실패다.
  **경고는 무시되지만 답이 없으면 에이전트는 원본을 확인할 수밖에 없다**
- **제외된 미검증 항목 목록이 곧 사람의 작업 큐가 된다.**
  시스템이 자기 지식의 공백을 스스로 드러내고 그 공백이 다음 작업 항목이 되는 구조이며,
  커버리지 압박이 정확성을 침식하지 않는다

라이프사이클 상태가 `rejected`인 항목과 미검증 상태로 남은 `proposed` 항목은 모두 팩에
들어가지 않으며, **"팩에서 제외"는 상태명이 아니라 팩 미포함 결과를 서술하는 표현**이다.
**구현 상태(현재)**: `reopen()`은 `verified` 또는 `rejected` 판정을 `proposed`로 되돌리고,
엣지의 `invalidated_ts`는 W13 이중시간 이력을 보존하면서 현재 유효성만 끝낸다
(`ontologylab/kgstore.py`). 팩은 빌드 시점의 verified-only 스냅샷이므로, 검증 후 다시 열린
항목도 이미 출고된 불변 팩에는 남고 다음 팩에서 빠진다. 이는 D4의 "원본이 옳고 팩이 낡은
것"이라는 권위 규칙과 일치한다.

### D7. 갱신 — 이벤트는 검증 큐 적재를 트리거한다

파이프라인 단계마다 다르다.
1. **수집·추출**: 이벤트가 자동 트리거 (인터뷰 완료, 결정 확정, 명세 정본 승격 시
   추출 후보가 검증 큐에 적재)
2. **검증**: 사람이 한다. 자동화하지 않는다
3. **팩 생성**: 승인된 항목이 쌓인 뒤. 사람이 판단하거나 미반영 승인 항목이 일정 수를 넘을 때

이벤트가 곧바로 팩을 만들게 하면 미검증 내용이 들어가거나, 검증 큐가 완전히 비어야만
생성되는 조건이 붙어 사실상 생성되지 않는다.

**갱신 주기보다 낡음의 관측 가능성이 중요하다.** 모든 답에 기준 시점이 붙고
미반영 승인 항목 수를 함께 노출하면, 에이전트가 "이 팩 이후 확정된 결정이 몇 건 있다"까지
알 수 있어 갱신이 며칠 늦어도 잘못된 판단으로 이어지지 않는다.

**재생성이 필요한 경우**: 새 결정 확정, 명세 정본 승격, 프로젝트 간 계약 변경.
**필요 없는 경우**: 일상 커밋과 구현 진행 — 팩이 코드 내용을 담지 않기로 한 결정의
부수 이득이다.

**계획 상태(미구현)**: 위 이벤트 트리거와 미반영 승인 항목 수 노출은 모두 새로 만들어야 할
기구다. 현재 수집은 HTTP `POST /collect` 또는 CLI `collect`를 사람이 호출하는 방식이고,
빌드된 팩은 작업 DB의 verified 행을 복사한 불변 산출물이라 빌드 뒤 작업 DB와 연결되어 있지
않다(`ontologylab/server/routes.py`, `ontologylab/main.py`, `ontologylab/packbuilder.py`).

## 7. 수락기준

| ID | 수락기준 | verification_method |
|---|---|---|
| AC-01 | 모든 추출 노드·엣지가 `proposed`로 생성되고 명시적 사람 승인으로만 `verified`가 되며, 팩에는 verified만 포함된다 | `automated_test` |
| AC-02 | 지식 팩이 불변이며 MCP 표면이 읽기 전용이다 | `automated_test` |
| AC-03 | MUNI 포트폴리오 팩이 7가지 질문(존재 이유·확정 결정·근거·비목표와 경계·활성 작업과 담당·프로젝트 간 계약·이전 실패와 이유)에 답한다 | `automated_test` + `manual_review` |
| AC-04 | 2026-08-01 세션 고고학 결과로 만든 벤치마크 질문·정답 세트를 팩이 통과한다 | `automated_test` |
| AC-05 | 모든 답에 근거 출처와 기준 시점(팩의 생성 시각·커밋)이 포함된다. **미구현/후속 구현 작업**: manifest의 `basis_commit`과 MCP 응답 봉투의 생성 시각 | `automated_test` |
| AC-06 | 팩에 없는 정보를 물으면 결과 0건(`count: 0`)으로 모른다고 답하고 합성하지 않는다 | `automated_test` |
| AC-07 | 항목마다 결정인지 구현 상태인지가 구분되고 각각의 기준 시점이 붙는다. 진짜 모순은 미검증으로 분류되어 팩에서 제외되고 미검증 목록이 조회 가능하다 | `automated_test` |
| AC-08 | 이벤트가 검증 큐 적재를 트리거하고, 팩 생성은 승인 이후에만 이뤄지며, 미반영 승인 항목 수가 노출된다. **미구현**: 이벤트 트리거와 미반영 승인 수 노출은 신규 기구 | `automated_test` |

**AC-05 구현 격차**: 현재 `PackSession._provenance`의 MCP 쿼리 응답 봉투에는 `pack_id`와
`content_hash`만 들어간다(`ontologylab/mcp_server.py`). `created_ts`는 `manifest.json`에 있어
`pack://{pack_id}/manifest` 리소스로 별도 조회할 수 있지만, `PackManifest`에는 커밋 필드가
없어 커밋 해시는 어디에도 기록되지 않는다(`ontologylab/models.py`). 따라서 AC-05는
**미구현/후속 구현 작업**으로 manifest의 `basis_commit` 필드와 응답 봉투의 생성 시각을
추가해야 충족된다.

**AC-06 판정 기준(확정)**: ① 결과 0건(`count: 0`) 응답이 곧 "모른다"이며 시스템은 팩에
없는 내용을 합성하지 않는다. 현 MCP 쿼리 경로는 KG 행을 반환할 뿐 답을 생성하지 않고,
`packbuilder.py`가 팩에 `proposed` 행을 물리적으로 복사하지 않는다. ② 결과가 1건 이상이면
모든 검색 결과 행에 `match_score`와 `source_doc_id`가 붙는다(노드의 복수 출처 표기는
`source_document_ids`). 약한 매치의 걸러내기는 클라이언트가 수행하며, 시스템은 약한 매치를
숨기지도 단언하지도 않는다(`ontologylab/kgstore.py`, `ontologylab/mcp_server.py`). ③ 수치
임계값은 지금 명세가 발명하지 않고 AC-04 벤치마크 작업에서 데이터로 정한다.

**공통 증거 요구 4속성**: `target_commit`, 불변 `evidence_ref`, `verified_by`, `verified_at`.
`manual_review`는 자동화 불가 사유와 `expires_at` 추가.

## 8. 비목표

- 멀티유저·클라우드 배포
- 물리 하드웨어
- **규제·이중용도 도메인** (커넥터 deny-by-default allowlist) —
  **도구(가드레일) 제약에서 온 경계이며 제품 결정이 아니다**
- 후보 코드 실행
- 코드·명세 본문의 팩 복제
- 팩이 원본 문서의 권위를 대체하는 것
- 판매용 상용 기능

## 9. 운영 부담의 상한

팩 생성이 사람에게 부담이 되면 갱신이 밀리고 팩은 낡는다.
따라서 **검증 큐 검토가 짧게 끝나야 한다.** 추출 후보에 근거 링크가 붙어 있어
사람이 원문을 다시 찾지 않아도 되는 것이 그 조건이다.
Nipo에서 확정한 기록 부담 최소화 원칙과 같은 성격이며,
마찬가지로 **우회 신호로 관측**한다 — 검증 큐가 계속 쌓이기만 하고 처리되지 않으면
그것이 부담 과다의 신호다.

## 10. 운영 전제

1. **실데이터 경로**: 이 설치의 live data dir은 `~/Library/Application Support/ontologylab/data`다.
   `./data/kg.sqlite`는 **STALE**이며, iCloud 동기화 경로가 감지되면
   `paths.icloud_refusal`이 동기화하지 않고 서버를 종료한다(`ontologylab/paths.py`).
2. **추출 테스트 엔진**: `MockEngine`은 CamelCase 토큰 기반이라 실제 산문에서는 추출 결과가
   0건이다(`ontologylab/engines.py`). 따라서 추출을 검증하는 AC의 `automated_test`는 결정적
   fixture를 쓰거나 실제 품질 검증에는 claude 엔진을 사용해야 한다.
3. **pytest 출력**: `pyproject.toml`이 이미 `pytest -q`를 설정한다. `verify_command`에 `-q`를
   더하면 `-qq`가 되어 요약이 숨으므로 추가하지 않는다.

## 11. 미결정 사항

1. MUNI 전용 온톨로지 프리셋을 선행 설치한 뒤 적용할 구체적 추출 규칙
   (어떤 문서에서 어떤 관계를 뽑을 것인가)
2. AC-06 약한 매치의 수치 임계값 — AC-04 벤치마크에서 데이터로 결정
3. 두 번째 도메인 팩의 대상
4. 거버넌스 파일럿(DOC_INDEX·OPEN_DECISIONS 생성)과 이 팩 구축의 선후

## 12. 관련 문서와 추적

- 인터뷰: `interview_20260801_062141` (제품 요구사항, ambiguity 0.092)
- 인터뷰: `interview_20260801_022908` (living spec 분리·파일럿, ambiguity 0.08)
- Seed: `seed_4beda6e95da5`
- 후속 작업: 재생성된 Seed의 포트폴리오 백업 사본(`documentation-governance/seeds/`)은
  이 저장소가 아니라 형제 거버넌스 프로젝트를 다루는 세션에서 갱신한다.
- 기존 문서: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/DESIGN-RATIONALE.md`
  (36편 논문 근거), `HANDOFF.md`(확정 결정 표)
- 포트폴리오: `MUNI/Ouroboros/documentation-governance/PRODUCT_DEFINITIONS_DRAFT.md`,
  `SESSION_HANDOFF.md`

**거버넌스 파일럿 관련(별도 인터뷰에서 확정)**:
- baseline 이원화 — as-planned 원점은 최초 커밋 `fd511f7`
  (구현 전 순수 계획이 Git 이력에 없다는 사실도 메타데이터에 명시),
  거버넌스 `baseline_commit`은 정본화 시점 HEAD
- `docs/OPEN_DECISIONS.md`를 독립 파일로 (living spec 인라인 추가는 비파괴 원칙 위반)
- `DOC_INDEX.yaml`은 OPEN_DECISIONS를 **단순 등재**만 (집계 필드 금지 — 낡은 배지 방지)
- 미푸시 5커밋은 파일럿 G0 확인 항목

## 13. 다음 단계

1. 이 문서의 `canonical` 승격
2. 거버넌스 파일럿 — `docs/DOC_INDEX.yaml` + `docs/OPEN_DECISIONS.md` 생성
   (별도 승인 필요, 수락기준은 `interview_20260801_022908`에서 확정)
3. MUNI 포트폴리오 팩 구축

### 정정 이력

- **2026-08-01 검수 기반 정정** — ① 상태 용어를 구현 용어 `rejected`로 통일 ② Seed 재생성
  (새 `seed_id` `seed_4beda6e95da5`, 인터뷰 `interview_20260801_062141` 재개) ③ "커넥터
  차단 목록" 서사를 엔드포인트 allowlist 실체로 정정 ④ MUNI 팩 온톨로지 프리셋 선행조건
  명시 ⑤ AC-05/AC-06/AC-08 실현 조건·미구현 표기 ⑥ 운영 전제(데이터 디렉터리·
  MockEngine·`pytest -q`) 추가. 근거: 검수 보고와 코드 인용(`kgstore.py`, `allowlist.py`,
  `models.py`, `schemas.py`, `mcp_server.py`, `paths.py`, `engines.py`).

- **2026-08-01 승격**: 사람 승인으로 `draft`에서 `canonical`으로 승격됐다.
  G0 경계 확인과 G1 완전성·충돌 검사를 통과했고(기록은 front matter `approvals`),
  거버넌스 규칙에 따라 `baseline_commit`이 정본화 시점 HEAD(`d4039a8`)로 갱신됐다.

## 커밋 지침 — 경로를 명시해서 스테이징할 것

**2026-08-01 실행 완료**: 이 문서와 `docs/ouroboros-seed.yaml`은 커밋 `d4039a8`으로
경로 명시 스테이징(`git add docs/PRODUCT_SPEC.md docs/ouroboros-seed.yaml`)을 거쳐
커밋됐다. 아래는 당시 적용된 절차의 기록이며, 이후 이 파일들을 수정해 커밋할 때도
같은 규칙이 적용된다.

**반드시 경로를 명시해서 스테이징한다:**

```bash
git add docs/PRODUCT_SPEC.md docs/ouroboros-seed.yaml
```

**`git add -A`, `git add .`, `git add docs/`를 쓰지 않는다.**
배치 당시 이 저장소의 작업트리 상태는 0개 수정, 2개 미추적이었고, `docs/` 안에 다른 미커밋 변경은 없었다.
일괄 스테이징하면 소유자와 완료 상태가 확인되지 않은 기존 변경까지 함께 커밋되어,
2026-08-01에 확정한 귀속·서명 게이트를 건너뛰게 된다.

기존 미커밋 변경의 처리 절차는 별도로 확정되어 있다 — 귀속 3등급
(ledger 지목 / 증거 2개 수렴 추론 / ownership-unknown), 등급별 허용 행위,
동일 세션 묶음 일괄 서명과 개별 서명 예외. 상세는
`MUNI/Ouroboros/documentation-governance/SESSION_HANDOFF.md` 참조.

---

## 부록 A — Ouroboros Seed

```yaml
goal: Build OntologyLab as a local-first single-user knowledge graph pipeline where
  AI proposes and humans verify, exposing immutable verified-only knowledge packs
  to agents via a read-only MCP server — with the MUNI portfolio metadata (decisions,
  rationale, boundaries, inter-project relationships) as the first domain pack instance
  of a general-purpose pipeline.
task_type: code
brownfield_context:
  project_type: brownfield
  context_references:
  - path: /Users/hyunjun/Documents/MUNI/ontologylab
    role: primary
    summary: Canonical project root — local-first KG pipeline with guided pipeline,
      review queue, and graph browser screens implemented
  - path: /Users/hyunjun/Documents/MUNI/ontologylab/ontologylab/kgstore.py
    role: reference
    summary: KG store with REVIEW_STATUSES = ("proposed", "verified", "rejected")
      defining the lifecycle state machine
  - path: /Users/hyunjun/Documents/MUNI/ontologylab/ontologylab/connectors/allowlist.py
    role: reference
    summary: Endpoint positive allowlist using host/source exact-match; PAPER_API_SOURCES
      includes europepmc and clinicaltrials; no topic/domain filter
  - path: /Users/hyunjun/Documents/MUNI/ontologylab/server/routes.py
    role: reference
    summary: FastAPI routes with 21 Query defaults — must not be called as plain functions
      without supplying every parameter by name
  - path: /Users/hyunjun/Documents/MUNI/ontologylab/tests
    role: reference
    summary: Test suite with conftest.py autouse fixture redirecting settings writes;
      pytest configured with -q in pyproject.toml
  existing_patterns:
  - Proposal-to-verification state machine (proposed/verified/rejected) with human
    approval gate
  - Immutable pack generation from verified-only items with bitemporal tracking
  - Endpoint positive allowlist for external network sources (host/source exact-match,
    no topic filter)
  - Local file collection path for non-network sources bypassing allowlist
  - Ontology schema presets (schemas.PRESETS) with additive switching preserving schema_version_id
    on existing proposals
  - MCP server exposing read-only query surface
  - Mutation testing over coverage as verification standard
  - Data directory at ~/Library/Application Support/ontologylab/data (not ./data which
    is stale)
  existing_dependencies:
  - FastAPI
  - SQLite (kg.sqlite for KG store)
  - Claude (LLM extraction engine via --engine claude)
  - MCP protocol (read-only server for agent consumers)
  - pytest (test suite with -q default in pyproject.toml)
constraints:
- Lifecycle states are exactly proposed/verified/rejected; 'excluded' is not a state
  but a consequence of non-verification
- Connector constraint is an endpoint positive allowlist (ontologylab/connectors/allowlist.py)
  using host/source exact-match; no topic or domain filter exists; PAPER_API_SOURCES
  already includes europepmc, clinicaltrials, and other bio sources; do not describe
  as a domain blocklist
- 'Semantic AC keys are immutable: ac_d203e3678fabfc47, ac_34a5c4d277f023a3, ac_9a2d0b86300e29c8,
  ac_e9a037ace863e81d'
- 'verify_command strings are byte-exact — no -q suffix, no option normalization:
  ac_d203e3678fabfc47→python -m pytest tests/test_kgstore.py tests/test_entity_review.py
  tests/test_e2e_mvp.py | ac_34a5c4d277f023a3→python -m pytest tests/test_packbuilder.py
  tests/test_bitemporal.py | ac_9a2d0b86300e29c8→python -m pytest tests/test_mcp_session.py
  tests/test_mcp_two_tier.py | ac_e9a037ace863e81d→python -m pytest tests/test_portfolio_benchmark.py'
- ac_e9a037ace863e81d description must state that the test is a future artifact to
  be created during MUNI pack work and that this AC remains unverifiable with no evidence
  until then
- Packs are immutable and contain only verified items; MCP surface is read-only
- Pack is a derived view and never authoritative over source documents; pack vs original
  conflict → original is correct and pack is stale
- Every pack answer must include source reference (which document/decision record)
  and basis timestamp (commit/date); stale knowledge presented as current is the most
  dangerous failure mode
- MUNI portfolio local files enter via existing local file collection path, not through
  network connectors or endpoint allowlist; no new unified connector abstraction required
  for this Seed
- Allowlist is external network endpoint-only; local filesystem sources bypass it
  entirely
- Pipeline and ontology/connector structure maintain general-purpose reusability beyond
  MUNI pack, but this Seed's implementation and verification scope is the MUNI first
  pack only
- Neutral domains only — guardrail-derived boundary, not a product decision; shipped
  defaults center on software docs and public scholarly metadata
- Build agent is Claude Fable; project boundaries are defined by what can be built
  within Claude's guardrails
- 'Accuracy over coverage: verified half is useful, complete-but-partially-wrong is
  untrustable; unknown is the correct answer for absent knowledge'
- 'Conflict resolution: temporal differences (decision vs implementation state) are
  labeled and passed through; true contradictions (same tense, same subject, opposing
  claims) are excluded as unverified; excluded items surface as human work queue'
acceptance_criteria:
- description: Extracted entities and relations follow the proposed→verified→rejected
    lifecycle with explicit human approval gating all state transitions; no content
    reaches verified status without human action
  semantic_ac_key: ac_accd678e56a4bd52
  verify_command: python -m pytest tests/test_kgstore.py tests/test_entity_review.py
    tests/test_e2e_mvp.py
- description: Knowledge packs are immutable bundles containing only verified items
    with bitemporal tracking that distinguishes decision timestamps from implementation
    state; each item carries source reference and basis timestamp; items with unresolved
    contradictions are excluded and surfaced as a human review queue
  semantic_ac_key: ac_db5dd84b05d77588
  verify_command: python -m pytest tests/test_packbuilder.py tests/test_bitemporal.py
- description: MCP server exposes packs as a read-only query surface for agent consumers;
    absent knowledge returns unknown rather than uncertain answers; pending verified-but-unreflected
    item count is exposed so agents can judge staleness
  semantic_ac_key: ac_781b2e2a66576dbd
  verify_command: python -m pytest tests/test_mcp_session.py tests/test_mcp_two_tier.py
- description: MUNI portfolio benchmark — new session agents answer the seven archaeological
    questions (existence rationale, confirmed decisions, decision rationale, non-goals
    and boundaries, active work ownership, inter-project interface contracts, prior
    failures and their causes) via pack queries without file searching; this test
    is a future artifact to be created during MUNI pack work and until then this AC
    remains unverifiable with no evidence
  semantic_ac_key: ac_fd76310cf7bbd7d0
  verify_command: python -m pytest tests/test_portfolio_benchmark.py
ontology_schema:
  name: KnowledgeGraphPipeline
  description: Domain model for a local-first knowledge graph pipeline that manages
    the lifecycle of AI-proposed knowledge items through human verification into immutable
    packs exposed via MCP
  fields:
  - name: proposal_id
    type: string
    description: Unique identifier for an extracted entity or relation proposal
    required: true
  - name: entity_name
    type: string
    description: Name of a knowledge graph node
    required: true
  - name: entity_type
    type: string
    description: Type classified by the active ontology schema preset
    required: true
  - name: relation_type
    type: string
    description: Type of directed edge between two entities
    required: true
  - name: lifecycle_status
    type: string
    description: One of proposed, verified, or rejected — only human action transitions
      from proposed
    required: true
  - name: source_reference
    type: string
    description: Origin document path or identifier with character spans for traceability
    required: true
  - name: schema_version_id
    type: string
    description: Ontology schema version the proposal was extracted against; proposals
      retain their original schema even after schema switches
    required: true
  - name: basis_timestamp
    type: string
    description: Commit hash or date the content is based on; distinguishes decision-time
      from implementation-state
    required: true
  - name: temporal_class
    type: string
    description: Whether the item records a confirmed decision or an observed implementation
      state
    required: true
  - name: pack_id
    type: string
    description: Immutable pack identifier; a new pack is created rather than updating
      an existing one
    required: true
  - name: pack_basis_commit
    type: string
    description: Git commit or date the pack was generated against; enables agents
      to judge staleness
    required: true
  - name: pending_verified_count
    type: number
    description: Count of verified items not yet reflected in the latest pack; exposed
      to consumers for staleness judgment
    required: true
  - name: exclusion_reason
    type: string
    description: Why an item was excluded from a pack — unresolved contradiction or
      unverified status; excluded items form the human work queue
    required: true
evaluation_principles:
- name: accuracy_over_coverage
  description: Verified accuracy is strictly preferred over completeness; a wrong
    answer causes more damage than a gap because agents use pack knowledge as ground
    truth for code generation
  weight: 0.3
- name: provenance_traceability
  description: Every fact in a pack traces to a specific source document and basis
    timestamp so agents can verify and assess currency
  weight: 0.25
- name: human_gate_integrity
  description: No content transitions to verified without explicit human approval;
    the proposed-to-verified gate is the core trust mechanism and must never be bypassed
  weight: 0.25
- name: staleness_observability
  description: Consumers can determine pack age and count of pending unreflected items;
    observable state replaces rigid refresh schedules
  weight: 0.15
- name: safe_failure
  description: Absent knowledge returns unknown rather than a guess with a warning;
    missing answers force agents to consult originals, which is the safe failure mode
  weight: 0.05
exit_conditions:
- name: benchmark_pass
  description: MUNI portfolio benchmark questions are answerable via pack queries
  criteria: New session agent resolves the seven archaeological questions without
    searching project files
- name: verification_gate
  description: All pack contents are human-verified
  criteria: No item with lifecycle_status=proposed exists inside any generated pack
- name: mcp_read_only
  description: MCP surface is read-only and exposes staleness metadata
  criteria: Pack queries return data with basis timestamps and pending counts; no
    write operations are accepted
- name: pipeline_generality
  description: Pipeline is not hardcoded to MUNI portfolio
  criteria: Ontology schema, connector structure, and extraction pipeline accept different
    domain configurations without structural changes
metadata:
  seed_id: seed_4beda6e95da5
  version: 1.0.0
  created_at: '2026-08-01T12:52:51.423739Z'
  ambiguity_score: 0.121
  interview_id: interview_20260801_062141
  parent_seed_id: null
  generation_mode: normal
  degraded: false
  unresolved_slots: []
  recovery_reason: null
```
