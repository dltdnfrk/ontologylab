# Wave 2.1 Remediation Proposal

> **RECOVERED SUMMARY — 원본과 byte-identical하지 않음.**
>
> 이 문서는 실수로 삭제된 untracked GJC 보고서의 복구본이다. 원본의 기록된
> SHA-256은 `64613f9486602fae88948baa8aeacf4165edb7d884e14fc757958701ca208f5f`다.
> 세션 원문에서는 원본 전체를 찾지 못했으므로, 삭제 전 생성된 Graphify 추출과
> 최종 통합 보고서에 보존된 판정을 사용해 아래 내용을 복구했다.
>
> 최종 구현 권위는
> `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`와
> `.omo/mass-ulw/20260820-ingestion-integration/04-domain-architecture.md`다.
> 이 문서는 대안 설계 입력이며 최종 결정문이 아니다.

## 1. 복구된 문제 정의

기존 수집 경로의 first-write-wins 동작은 같은 DOI의 더 풍부한 원문을 버릴 수 있다.
문헌의 서지 식별자, 실제 바이트 표현, 한 번의 수집 관측을 한 document row로 합치면
다음 문제가 생긴다.

- richer full text가 도착해도 기존 abstract가 계속 선택됨
- 서로 다른 DOI와 동일 bytes의 의미를 분리하지 못함
- 수집 시점·소스·query·stage 같은 관측 metadata가 표현 바이트와 섞임
- extraction과 citation이 실제로 읽은 표현을 가리키지 못함
- DB commit과 provenance append 사이가 원자적이지 않음

## 2. GJC가 제안한 네 계층

Graphify 추출에 보존된 원 제안의 구조는 다음과 같다.

1. **Work Cluster** — 같은 학술 작업 계열
2. **Citable Version** — 인용 가능한 버전 단위
3. **Immutable Representation** — 실제로 수집한 불변 바이트
4. **Ingest Observation** — 소스, query, 시점, stage를 가진 수집 관측

관련 복구 개념:

- §2.2 A: First-write-wins Data Loss
- §4.1: Work Cluster, Citable Version, Representation, Observation
- §4.1–4.3: Immutable Representation
- §5.3: Deterministic Preferred Representation Projection
- §6: SQLite Transactional Provenance Outbox
- §7: Exact Representation Citation

## 3. 제안된 보완책

- representation은 append-only immutable row로 보존한다.
- observation은 representation과 source/query/stage를 연결한다.
- preferred representation은 mutable pointer가 아니라 deterministic read-time
  projection으로 계산한다.
- persistence와 provenance는 SQLite transactional outbox로 묶는다.
- extraction과 citation은 정확히 사용한 representation을 참조한다.

## 4. 최종 통합에서의 판정

최종 통합은 이 네 계층을 그대로 채택하지 않았다.

- DOI를 가진 preprint와 version of record는 별도 Work로 둔다.
- 두 Work의 관계는 provenance를 가진 `work_relations`로 표현한다.
- stage는 Observation metadata와 read-time projection으로 처리한다.
- 저장형 cluster/version 및 mutable preferred pointer는 두지 않는다.

즉 GJC 보고서는 손실 모델과 대안 공간을 넓힌 중요한 입력이지만, 최종 스키마 권위는
세 축 Work / Representation / Observation Design B다.

## 5. 복구 provenance

- 원본 SHA-256:
  `64613f9486602fae88948baa8aeacf4165edb7d884e14fc757958701ca208f5f`
- Graphify source nodes:
  `graphify-out/graph.json`, source file
  `docs/WAVE-2.1-DEEP-RESEARCH-REMEDIATION-GJC-2026-08-20.md`
- 최종 비교·채택 근거:
  `.omo/mass-ulw/20260820-ingestion-integration/04-domain-architecture.md`
- 최종 통합 보고서:
  `docs/OMO-INGESTION-WAVE-2.1-MASS-ULW-INTEGRATED-ANALYSIS-2026-08-20.md`
