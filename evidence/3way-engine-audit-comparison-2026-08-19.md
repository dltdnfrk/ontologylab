# 3-way head-to-head: OntologyLab 엔진 파이프라인 적대적 감사 (2026-08-19)

동일 요청(8개 파이프라인 단계 REAL/THIN/HOLLOW 판정 + file:line 증거 + 리팩토링 우선순위, 커밋 금지, 읽기 전용, 실데이터/8799 불가침)을 3개 어시스턴트에 투입.

- omo (본 세션): `docs/ENGINE-PIPELINE-AUDIT-2026-08-19.md`
- GJC (Grok 4.6 xhigh, gajae-code): `docs/ENGINE-PIPELINE-AUDIT-GJC-2026-08-19.md` (15KB, 15:09 완료)
- prime-agent (GPT-5.6 Sol): `docs/ENGINE-PIPELINE-AUDIT-PRIME-AGENT-2026-08-19.md` (33KB, 15:24 완료)

## 프로세스 비교

| | omo | GJC | prime-agent |
|---|---|---|---|
| 방법 | 8레인 DAG 병렬 + 리드 직접 검증 + 12건 스팟 검증 | 단일 세션 정적 독해 + 표적 pytest 31건 | 4 서브에이전트 + 전체 스위트 2회 + 라이브 뮤테이션 반례 |
| 실행 증거 | 없음(정적+과거 스위트 지식) | 31 passed (선별) | 2236+228+표적 1400+ passed, 변조 팩 반례 실연 |
| 장애 | deep/ultrabrain 라우트(Sol) 다운 → Grok 대체, 하네스 AbortError 크래시 1회 | 없음 | 첫 카드/경계 확인 후 순항 |
| 산출 시각 | 00:07 (중간에 커밋 정리·init-deep 병행) | 15:09 | 15:24 |

## 판정 수렴/발산

**3자 전원 일치**: 단일 단계가 통째로 HOLLOW인 곳은 없음. 추출 API 기본값 mock, conformal/calibration 수학은 진짜지만 UI 미배선, method_*는 실구현이나 웹/UI와 단절, agrochem 트랙 정규화는 실구현.

**판정 톤**: omo·GJC는 REAL 중심 + THIN 심. prime은 8개 중 6개를 THIN으로 — "구현 존재 ≠ 주장한 신뢰 수준" 기준 적용, 뮤테이션으로 테스트가 못 잡는 결함을 실증.

**고유 발견 (prime만)**: CAS 체크섬 무력화 뮤턴트가 29테스트 통과 / conformal·calibration에서 edge 제거 뮤턴트 통과 / G5가 실제 contradiction을 통과 / G7 replay는 행동이 아니라 필드 비교 / substring grounding(CAT→concatenate) / proposed alias가 즉시 identity 권한 / ontology apply 비원자성 / collect provenance 누락(routes.py:1777).

**고유 발견 (omo)**: `ExtractRequest.engine="mock"` split-brain 프레이밍 / 리서치 전원실패→complete 거짓(테스트가 핀) / 설정 data_dir 장식 입력 / searchquery×mock 마커 충돌.

**GJC 실수**: pack/MCP를 REAL로 판정하며 `test_mcp_pack_integrity` 바이트-flip 테스트를 증거로 인용 — 그 테스트는 resource_*를 제외하는 게 하드코딩된 빈껍데기 주장(omo L6·prime 모두 지적). GJC는 해시 우회 구멍을 놓침.

## 종합 평

- 가장 깊은 증거: **prime-agent** (라이브 뮤테이션·변조 반례까지).
- 가장 균형 잡힌 커버리지: **omo** (8레인 + 스팟검증; 속도보다 폭).
- 가장 빠른: **GJC**, 그러나 무결성 구멍 1개 누락 + 문서 주장을 그대로 인용한 곳 있음.
- 3개를 합치면 서로의 사각이 상당 부분 상쇄됨 — prime의 런타임 반례 + omo의 표면/정직성 지도 + GJC의 테스트-증명 매트릭스.
