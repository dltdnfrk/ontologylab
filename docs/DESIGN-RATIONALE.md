# ontologylab 설계 근거: "AI가 제안하고, 사람이 검증한다"

> 학술 문헌 dossier. ontologylab의 핵심 설계 명제가 취향이 아니라 Nature·Science·SCI급
> 문헌이 실증한 결론임을 보인다. 수록 논문 36편은 전량 Crossref REST API로 독립 재검증했다
> (제목·저널·연도·volume/page·저자수 대조, 모두 `journal-article` resolve).
> Obsidian vault에도 미러가 있으나 이 문서가 정본(self-contained)이다.

## 한 줄 요약

ontologylab의 핵심 명제 — **LLM 추출은 항상 첫 단계이지 마지막 단계가 아니며, 사람이 명시적으로 승인한 사실만 출고된다(verified-only)** — 는 2020~2026년 Nature·Science·SCI급 문헌이 반복 실증한 결론이다. 이 문서는 그 근거를 6개 기둥으로 정리하고, 각 기둥을 ontologylab의 구체적 설계 결정에 매핑한다.

## 계기

Nature 사설 **"Why AI cannot do good science without humans"** (*Nature* 653, 650, 2026)가 동시 게재된 두 '자율 AI 과학자' 논문 — Google **Co-Scientist**와 FutureHouse **Robin** — 을 논평하며 내린 결론이 ontologylab의 설계 철학과 정확히 일치한다:

> AI scientists can and should empower human researchers. They cannot and should not replace them.

두 시스템 모두 인상적인 성과(Robin은 인간 워크플로 대비 200배 단축, Co-Scientist는 연구진이 10년간 미발표로 붙들던 항생제 내성 가설을 며칠 만에 재발견)를 냈지만, **어느 쪽도 단독으로 일하지 않았다** — 사람이 문제를 틀 짓고, 실험을 수행하고, 산출물을 검증했다. ontologylab은 바로 그 "사람이 검증하는 층(human verification layer)"을 로컬·단일사용자 지식그래프 파이프라인으로 구현한 것이다.

앵커 (모두 *Nature* 2026, DOI 검증 완료):
- [editorial] "Why AI cannot do good science without humans". *Nature* 653, 650 (2026). doi:10.1038/d41586-026-01551-3
- Gottweis, J. et al. "Accelerating scientific discovery with Co-Scientist". *Nature* 655, 487–496 (2026). doi:10.1038/s41586-026-10644-y  *(Google, 51인)*
- Ghareeb, A. E. et al. "A multi-agent system for automating scientific discovery" (Robin). *Nature* 655, 497–505 (2026). doi:10.1038/s41586-026-10652-y  *(FutureHouse, 14인)*
- Lu, C. et al. "Towards end-to-end automation of AI research". *Nature* 651, 914–919 (2026). doi:10.1038/s41586-026-10265-5

---

## 6개 설계 기둥과 근거 문헌

### 기둥 1 — 사람의 검증은 선택이 아니라 필수 (AI는 강화하되 대체하지 않는다)

**ontologylab 매핑:** ARCHITECTURE §1.2 "Human-in-the-loop is mandatory" + §1.3 "Verified-only leaves the building". 모든 추출물은 `proposed`로 태어나고, 명시적 사람 승인으로만 `verified`가 된다. MCP 도구는 그래프를 절대 변경하지 못한다(승인은 MCP 범위 밖 사람 행위).

- Messeri, L. & Crockett, M. J. "Artificial intelligence and illusions of understanding in scientific research". *Nature* 627, 49–58 (2024). doi:10.1038/s41586-024-07146-0 — AI가 과학에서 "이해했다는 착각"을 만들어 인간이 실제보다 더 안다고 믿게 만드는 위험. verified-only 게이트의 핵심 근거.
- Wang, H. et al. "Scientific discovery in the age of artificial intelligence". *Nature* 620, 47–60 (2023). doi:10.1038/s41586-023-06221-2 — AI-for-science의 정전급 리뷰(30인). AI를 발견 파이프라인 전반에서 인간 판단을 **증강**하는 도구로 규정.
- Vaccaro, M., Almaatouq, A. & Malone, T. "When combinations of humans and AI are useful: A systematic review and meta-analysis". *Nature Human Behaviour* 8, 2293–2303 (2024). doi:10.1038/s41562-024-02024-1 — 인간+AI 조합이 **세심히 설계되지 않으면** 인간 단독/AI 단독보다 못하다는 메타분석. "AI가 제안, 사람이 결정"이라는 역할 분담의 실증 근거.
- Bengio, Y. et al. "Managing extreme AI risks amid rapid progress". *Science* 384, 842–845 (2024). doi:10.1126/science.adn0117 — 자율 AI에 대한 인간 감독·거버넌스 가드레일 합의문(25인).
- Van Noorden, R. & Perkel, J. M. "AI and science: what 1,600 researchers think". *Nature* 621, 672–675 (2023). doi:10.1038/d41586-023-02980-0 — 연구자 다수가 AI 산출물의 신뢰·검증을 우려한다는 대규모 설문. *(Nature 뉴스 피처 — 보조 근거)*

### 기둥 2 — 자동화 편향·앵커링: 자문 점수는 결정을 미리 채워선 안 된다

**ontologylab 매핑:** W8 크리틱 트리아지의 anti-anchoring 가드. 크리틱 모델 점수는 **순수 자문**이며, 코드상 점수→상태전이 경로가 존재하지 않고, UI는 어떤 결정도 미리 선택/체크하지 않는다. 이 기둥이 W8 설계의 직접 근거다.

- Dratsch, T. et al. "Automation Bias in Mammography: The Impact of AI BI-RADS Suggestions on Reader Performance". *Radiology* 307 (2023). doi:10.1148/radiol.222176 — **가장 강력한 단일 근거.** AI가 틀린 BI-RADS를 제시하자 방사선과 전문의 정확도가 급락. 미리 채워진 AI 점수가 전문가를 앵커링한다는 통제 실험.
- Gaube, S. et al. "Do as AI say: susceptibility in deployment of clinical decision-aids". *npj Digital Medicine* 4 (2021). doi:10.1038/s41746-021-00385-9 — 전문가·비전문가 모두 틀린 AI 조언을 따름. 전문성과 무관한 과의존.
- Jabbour, S. et al. "Measuring the Impact of AI in the Diagnosis of Hospitalized Patients". *JAMA* 330, 2275 (2023). doi:10.1001/jama.2023.22295 — 편향된 AI가 임상의 진단 정확도를 떨어뜨렸고, 이미지 기반 설명도 완전히 막지 못한 RCT.
- Tschandl, P. et al. "Human–computer collaboration for skin cancer recognition". *Nature Medicine* 26, 1229–1234 (2020). doi:10.1038/s41591-020-0942-0 — AI가 틀렸을 때조차 임상의 결정이 AI 예측 쪽으로 끌려감(잘못된 AI가 좋은 임상의를 해침).
- Reverberi, C. et al. "Experimental evidence of effective human–AI collaboration in medical decision-making". *Scientific Reports* 12 (2022). doi:10.1038/s41598-022-18751-2 — 내시경의가 (오류 조언 포함) AI 조언 쪽으로 결정을 옮기는 정도를 정량화. *(Nature-family, 보조 근거)*

### 기둥 3 — LLM 환각·사실 불신뢰성, 그리고 출처 provenance의 필요

**ontologylab 매핑:** W2 provenance 필드 + char-span 인용 무결성 — 출고되는 모든 사실은 원문 좌표로 역추적된다. verified-only 서빙과 결합해 "유창함을 정확함으로 오인"하는 것을 구조적으로 차단.

- Singhal, K. et al. "Large language models encode clinical knowledge" (Med-PaLM). *Nature* 620, 172–180 (2023). doi:10.1038/s41586-023-06291-2 — LLM 의학 답변의 사실성·유해성에 대한 인간 평가 필요를 도입(32인).
- Tang, L. et al. "Evaluating large language models on medical evidence summarization". *npj Digital Medicine* 6 (2023). doi:10.1038/s41746-023-00896-7 — LLM 의학 요약의 사실 불일치·환각 문서화.
- Wornow, M. et al. "The shaky foundations of large language models and foundation models for electronic health records". *npj Digital Medicine* 6 (2023). doi:10.1038/s41746-023-00879-8 — 임상 파운데이션 모델의 신뢰성·평가 공백. 원본 모델 출력을 그대로 서빙하면 안 되는 근거.
- Van Veen, D. et al. "Adapted large language models can outperform medical experts in clinical text summarization". *Nature Medicine* 30, 1134–1142 (2024). doi:10.1038/s41591-024-02855-5 — 긍정적 결과에서도 잔존 환각·누락이 사람 판독 조정을 요구.
- Chelli, M. et al. "Hallucination Rates and Reference Accuracy of ChatGPT and Bard for Systematic Reviews". *Journal of Medical Internet Research* 26, e53164 (2024). doi:10.2196/53164 — **조작된/부정확한 인용**을 직접 정량화. ontologylab의 출처-provenance 요구가 방어하는 바로 그 실패 모드.
- Ayers, J. W. et al. "Comparing Physician and AI Chatbot Responses to Patient Questions". *JAMA Internal Medicine* 183, 589 (2023). doi:10.1001/jamainternmed.2023.1838 — 챗봇 답변이 유창하고 종종 선호됨 → 검증 없이도 설득력이 있음. provenance 필요의 동기.
- Ji, Z. et al. "Survey of Hallucination in Natural Language Generation". *ACM Computing Surveys* 55, 1–38 (2023). doi:10.1145/3571730 — 환각 분류·faithfulness/factuality 지표의 정의 레퍼런스. *(비의학 CS, 고IF SCIE 저널 — 컨퍼런스 논문 아님)*

### 기둥 4 — 생성형 AI 시대의 학술 기록 무결성 (AI slop 방어)

**ontologylab 매핑:** verified-only 불변 pack + deny-by-default 인제스트(allowlist). "AI slop이 문헌을 오염시킨다"는 사설의 디스토피아 시나리오에 대해, 사람이 큐레이션하고 provenance로 고정한 지식그래프가 구조적 방어선.

- [editorial] "Tools such as ChatGPT threaten transparent science; here are our ground rules for their use". *Nature* 613, 612 (2023). doi:10.1038/d41586-023-00191-1 — Nature 자체 정책: AI는 책임 저자가 될 수 없고 인간 책임성·provenance가 필수. ontologylab의 "사람 승인분만 출고"와 동형.
- Else, H. "Abstracts written by ChatGPT fool scientists". *Nature* 613, 423 (2023). doi:10.1038/d41586-023-00056-7 — 인간이 AI 생성 과학 텍스트를 맨눈으로 구별 못 함 → 신뢰가 아닌 강제된 출처 provenance가 필요.
- Van Noorden, R. "How big is science's fake-paper problem?". *Nature* 623, 466–467 (2023). doi:10.1038/d41586-023-03464-x — 조작·오염 문헌의 규모. ontologylab이 저항하도록 설계된 환경.
- Liang, W. et al. "Can Large Language Models Provide Useful Feedback on Research Papers? A Large-Scale Empirical Analysis". *NEJM AI* 1 (2024). doi:10.1056/AIoa2400196 — 검증 루프 속 LLM: 인간 리뷰어와 겹치지만 깊이를 놓침. "AI 보조, 사람 판정"의 근거.

### 기둥 5 — 다중 에이전트 AI 과학자 / 자율 발견 (앵커 3편을 넘어서)

**ontologylab 매핑:** ontologylab은 이런 자율 시스템이 **여전히 필요로 하는 verify 단계**다. A-Lab조차 모호한 결과 해석에 사람 개입이 필요했고, GNoME의 방대한 후보는 실험/사람 검증을 요구한다 — ontologylab이 그 검증 게이트를 표준화한다.

- Boiko, D. A. et al. "Autonomous chemical research with large language models" (Coscientist). *Nature* 624, 570–578 (2023). doi:10.1038/s41586-023-06792-0 — LLM 주도 자율 화학 연구의 정전급 선행연구. 안전 논의가 사람 게이팅을 정당화.
- Szymanski, N. J. et al. "An autonomous laboratory for the accelerated synthesis of inorganic materials" (A-Lab). *Nature* 624, 86–91 (2023). doi:10.1038/s41586-023-06734-w — closed-loop 자율 실험실. **모호한 결과 해석엔 사람 개입이 여전히 필요** — 사람 검증 게이트의 직접 근거.
- Merchant, A. et al. "Scaling deep learning for materials discovery" (GNoME). *Nature* 624, 80–85 (2023). doi:10.1038/s41586-023-06735-9 — AI가 방대한 후보를 제안하고 실험/사람이 검증하는 "제안→검증" 패턴의 대규모 사례.
- Burger, B. et al. "A mobile robotic chemist". *Nature* 583, 237–241 (2020). doi:10.1038/s41586-020-2442-2 — 자율 실험의 토대 인용. closed-loop 실험실 계보.
- M. Bran, A. et al. "Augmenting large language models with chemistry tools" (ChemCrow). *Nature Machine Intelligence* 6, 525–535 (2024). doi:10.1038/s42256-024-00832-8 — LLM 에이전트+외부 도구. 환각 억제를 위한 전문가 감독·grounding 필요를 명시.

### 기둥 6 — 지식그래프와 사람 큐레이션 기반 엔티티 해소

**ontologylab 매핑:** W7 엔티티 병합 리뷰 — 퍼지 중복 후보는 스캐너가 **제안만** 하고 병합/기각은 전적으로 사람 결정. KG 데이터 모델과 provenance 주석. 아래 생의학 KG들이 아키텍처적 유사 선례.

- Chandak, P., Huang, K. & Zitnik, M. "Building a knowledge graph to enable precision medicine" (PrimeKG). *Scientific Data* 10 (2023). doi:10.1038/s41597-023-01960-3 — 검증된 출처를 통합한 provenance 주석 생의학 KG. ontologylab의 가장 가까운 아키텍처 아날로그.
- Santos, A. et al. "A knowledge graph to interpret clinical proteomics data" (CKG). *Nature Biotechnology* 40, 692–702 (2022). doi:10.1038/s41587-021-01145-6 — 원본 데이터→결론의 provenance·추적성 강조. "모든 출고 사실에 출처"의 근거.
- Himmelstein, D. S. et al. "Systematic integration of biomedical knowledge prioritizes drugs for repurposing" (Hetionet). *eLife* 6 (2017). doi:10.7554/eLife.26726 — 재현가능·출처추적 이종 생의학 네트워크. provenance 보존 통합의 토대.
- Zitnik, M., Agrawal, M. & Leskovec, J. "Modeling polypharmacy side effects with graph convolutional networks" (Decagon). *Bioinformatics* 34, i457–i466 (2018). doi:10.1093/bioinformatics/bty294 — 엣지/엔티티 품질(큐레이션)이 하류 추론 신뢰성을 좌우함을 보임.
- Nicholson, D. N. & Greene, C. S. "Constructing knowledge graphs and their biomedical applications". *Computational and Structural Biotechnology Journal* 18, 1414–1428 (2020). doi:10.1016/j.csbj.2020.05.017 — 엔티티 해소·큐레이션 트레이드오프 리뷰. 사람 큐레이션 설계의 근거.
- Bonner, S. et al. "A review of biomedical datasets relating to drug discovery: a knowledge graph perspective". *Briefings in Bioinformatics* 23 (2022). doi:10.1093/bib/bbac404 — 데이터 provenance·품질이 KG의 전제조건임을 서베이.

---

## 종합

ontologylab은 자율 AI 과학자를 대체하려는 것이 아니라, **그들이 여전히 필요로 하는 검증·provenance 층**을 로컬·단일사용자 도구로 표준화한 것이다. 6개 기둥은 각각 다른 문헌군에서 같은 결론에 수렴한다:

1. 사람 검증은 필수 (illusions of understanding, human+AI 메타분석) → verified-only 게이트
2. 자문 점수는 앵커링하므로 결정을 미리 채우면 안 됨 (mammography/JAMA/skin-cancer 앵커링 실증) → **W8 anti-anchoring**
3. LLM은 환각하므로 출처가 필요 (조작된 인용 정량화) → **W2 provenance / char-span**
4. AI slop이 학술 기록을 오염시킴 → **verified-only 불변 pack + deny-by-default**
5. 최첨단 자율 실험실조차 사람 검증 단계를 필요로 함 (A-Lab 모호 결과) → **ontologylab = the verify stage**
6. KG는 사람 큐레이션·provenance가 전제 → **W7 병합 리뷰**

## 검증 방법 (meta note)

ontologylab의 철학을 이 dossier 자체에 적용했다 — 리서치 에이전트가 후보를 **제안**하고, **모든 DOI(36개)를 Crossref REST API로 독립 재검증**한 뒤에만 등재했다. 각 DOI에 대해 제목·저널(container-title)·연도·volume/page·저자수를 authoritative 메타데이터로 대조했고, 전부 `journal-article`로 resolve됨을 확인했다. 즉 이 서지 자체가 "AI 제안 → 검증 게이트 → verified-only 출고" 파이프라인의 산물이다.

## 엄격 기준 / 제외

포함 기준: Nature·Science·Cell·PNAS·Nature 계열(npj·Sci Data·Nat Med·Nat Biotech·Nat Mach Intell·Nat Hum Behav)·Lancet 계열·JAMA·NEJM 및 동급 SCIE/SSCI 저널의 피어리뷰 논문(리뷰·퍼스펙티브·사설 포함). 제외:

- arXiv/bioRxiv 프리프린트 일체.
- 컨퍼런스 전용 논문(NeurIPS/ICML/ACL/COLM 등). 예: LLM 문헌 침투율의 유명 결과(Liang 계열)는 컨퍼런스 전용이라 기둥 4의 강력 후보였으나 저널 미색인으로 제외.
- 확정 불가 인용: Conroy "How ChatGPT and generative AI could disrupt scientific publishing" (보유 DOI가 Crossref 404) — 확정 전까지 제외.

## 관련 문서

- `docs/ARCHITECTURE.md` — 설계 원칙(§1), KG 데이터 모델, MCP 인터페이스.
- `docs/RESEARCH-post-mvp.md` — post-MVP 방향 리서치(Wave 1–3). 이 dossier를 상호참조.
- `docs/ROADMAP.md` — M0–M8 + Wave 로드맵.
- 구현 매핑: W2 provenance · W7 엔티티 병합 리뷰 · W8 크리틱 anti-anchoring · verified-only 불변 pack.
