# 3단계 지식그래프 구축 보고서 — 《디지털 밀 재배》

- **생성 시각**: `2026-11-21T14:41:07+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **53건** (신규 처리: 26건)
- **증분 반영 결과**: 노드 **+361** (누적 `2802`) · 관계 **+253** (누적 `1797`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **international_journal** | `METRIC` | 11 | `SRC-07,SRC-09,SRC-151,SRC-152,SRC-166,SR` |
| **Korean Journal of Soil Science and Fertilizer** | `PRODUCT` | 11 | `SRC-11,SRC-12,SRC-13,SRC-217,SRC-219,SRC` |
| **메타데이터/초록** | `CONCEPT` | 8 | `SRC-09,SRC-116,SRC-182,SRC-218,SRC-219,S` |
| **soil** | `CONCEPT` | 7 | `SRC-14,SRC-186,SRC-198,SRC-20,SRC-212,SR` |
| **농촌진흥청** | `ORG` | 7 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **wheat** | `CONCEPT` | 7 | `SRC-144,SRC-186,SRC-192,SRC-193,SRC-201,` |
| **2016** | `EVENT` | 6 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **korean_society** | `ORG` | 6 | `SRC-116,SRC-182,SRC-218,SRC-219,SRC-220,` |
| **Global Change Biology** | `OTHER` | 5 | `SRC-10,SRC-204,SRC-208,SRC-56,SRC-58` |
| **2022** | `EVENT` | 5 | `SRC-13,SRC-132,SRC-182,SRC-97,SRC-99` |
| **climate change** | `CONCEPT` | 5 | `SRC-182,SRC-210,SRC-37,SRC-46,SRC-47` |
| **2012** | `EVENT` | 5 | `SRC-220,SRC-53,SRC-60,SRC-85,SRC-96` |
| **Fertilizer Research** | `PRODUCT` | 5 | `SRC-185,SRC-186,SRC-213,SRC-218,SRC-59` |
| **Agricultural and Forest Meteorology** | `PRODUCT` | 5 | `SRC-181,SRC-182,SRC-183,SRC-184,SRC-209` |
| **temperature** | `CONCEPT` | 4 | `SRC-02,SRC-198,SRC-208,SRC-55` |
| **Food and Agriculture Organization of the United Nations** | `ORG` | 4 | `SRC-137,SRC-193,SRC-197,SRC-20` |
| **2021** | `EVENT` | 4 | `SRC-120,SRC-156,SRC-189,SRC-29` |
| **farmers** | `PERSON` | 4 | `SRC-140,SRC-203,SRC-48,SRC-84` |
| **2014** | `EVENT` | 4 | `SRC-113,SRC-199,SRC-208,SRC-91` |
| **Plant and Soil** | `PRODUCT` | 4 | `SRC-149,SRC-211,SRC-212,SRC-93` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| Global Change Biology | `분류됨` | international_journal | `SRC-208` |
| Korean Journal of Soil Science and Fertilizer | `분류` | korean_society | `SRC-220` |
| Korean Journal of Soil Science and Fertilizer | `발행연도` | 2020 | `SRC-217` |
| Korean Journal of Soil Science and Fertilizer | `DOI/URL` | https://doi.org/10.7745/kjssf.2020.53.4.589 | `SRC-217` |
| Korean Journal of Soil Science and Fertilizer | `발행연도` | 2012 | `SRC-220` |
| Korean Journal of Soil Science and Fertilizer | `DOI` | https://doi.org/10.7745/kjssf.2012.45.2.198 | `SRC-220` |
| Korean Journal of Soil Science and Fertilizer | `피인용수` | 4회 | `SRC-220` |
| Food and Agriculture Organization of the United Nations | `hosts` | AquaCrop | `SRC-197` |
| climate change | `affect` | pathosystems | `SRC-210` |
| Fertilizer Research | `발행연도` | 1995 | `SRC-218` |
| Fertilizer Research | `제공함` | 메타데이터/초록 | `SRC-218` |
| Fertilizer Research | `발행연도` | 1990 | `SRC-213` |
| Fertilizer Research | `피인용수` | 19회 | `SRC-218` |
| 2014 | `발행됨` | Global Change Biology | `SRC-208` |
| korean_society | `분류` | Fertilizer Research | `SRC-218` |
| 열린장관실 | `소속됨` | 농림축산식품부 | `SRC-104` |
| 한국농촌경제연구원 | `발행함` | 2025 농어촌서비스기준 이행실태 점검·평가 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 2026년 소비자 김장 의향 및 주요 채소류 공급 전망 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 농축산물 수출입동향 2026년 3분기 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 농업관측정보 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 청년농 영농 진입단계 의사결정 지원체계 설계 연구 | `SRC-106` |
| 2024 | `발행됨_in` | Agricultural and Forest Meteorology | `SRC-184` |
| wheat | `반응함` | nitrogen fertilization | `SRC-186` |
| wheat | `expected to decline` | world cereal production | `SRC-193` |
| wheat | `보인다` | growth-related nutrient demand | `SRC-211` |
