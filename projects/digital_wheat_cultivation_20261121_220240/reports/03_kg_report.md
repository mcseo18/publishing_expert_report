# 3단계 지식그래프 구축 보고서 — 《디지털 밀 재배》

- **생성 시각**: `2026-11-21T14:17:24+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **27건** (신규 처리: 24건)
- **증분 반영 결과**: 노드 **+246** (누적 `2352`) · 관계 **+166** (누적 `1511`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **농촌진흥청** | `ORG` | 7 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **메타데이터/초록** | `CONCEPT` | 6 | `SRC-09,SRC-116,SRC-182,SRC-59,SRC-93,SRC` |
| **2016** | `EVENT` | 6 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **2022** | `EVENT` | 5 | `SRC-13,SRC-132,SRC-182,SRC-97,SRC-99` |
| **soil** | `CONCEPT` | 5 | `SRC-14,SRC-186,SRC-20,SRC-23,SRC-39` |
| **wheat** | `CONCEPT` | 5 | `SRC-144,SRC-186,SRC-192,SRC-193` |
| **2021** | `EVENT` | 4 | `SRC-120,SRC-156,SRC-189,SRC-29` |
| **climate change** | `CONCEPT` | 4 | `SRC-182,SRC-37,SRC-46,SRC-47` |
| **Agricultural and Forest Meteorology** | `PRODUCT` | 4 | `SRC-181,SRC-182,SRC-183,SRC-184` |
| **2023** | `EVENT` | 3 | `SRC-12,SRC-183,SRC-81` |
| **Food and Agriculture Organization of the United Nations** | `ORG` | 3 | `SRC-137,SRC-193,SRC-20` |
| **Fertilizer Research** | `PRODUCT` | 3 | `SRC-185,SRC-186,SRC-59` |
| **EU** | `ORG` | 3 | `SRC-192,SRC-78,SRC-85` |
| **korean_society** | `ORG` | 3 | `SRC-116,SRC-182,SRC-98` |
| **2024** | `EVENT` | 3 | `SRC-123,SRC-169,SRC-184` |
| **USDA** | `ORG` | 2 | `SRC-19,SRC-192` |
| **CMIP6** | `OTHER` | 2 | `SRC-184,SRC-88` |
| **2010** | `EVENT` | 2 | `SRC-179,SRC-93` |
| **crop** | `PRODUCT` | 2 | `SRC-144,SRC-186` |
| **corn** | `CONCEPT` | 2 | `SRC-144,SRC-192` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| 열린장관실 | `소속됨` | 농림축산식품부 | `SRC-104` |
| 한국농촌경제연구원 | `발행함` | 2025 농어촌서비스기준 이행실태 점검·평가 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 2026년 소비자 김장 의향 및 주요 채소류 공급 전망 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 농축산물 수출입동향 2026년 3분기 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 농업관측정보 | `SRC-106` |
| 한국농촌경제연구원 | `발행함` | 청년농 영농 진입단계 의사결정 지원체계 설계 연구 | `SRC-106` |
| 2024 | `발행됨_in` | Agricultural and Forest Meteorology | `SRC-184` |
| wheat | `반응함` | nitrogen fertilization | `SRC-186` |
| wheat | `expected to decline` | world cereal production | `SRC-193` |
| 2013 | `발행연도` | Food Science and Biotechnology | `SRC-187` |
| 밀 | `세계 곡물 생산량에서` | 옥수수 | `SRC-173` |
| 밀 | `2위를 차지함` | 옥수수 | `SRC-173` |
| 밀 | `최대생산국은` | 중국 | `SRC-173` |
| 밀 | `원산지` | 아프가니스탄 | `SRC-173` |
| 밀 | `원산지` | 캅카스 | `SRC-173` |
| 밀 | `원산지로 추정` | 아르메니아 | `SRC-173` |
| 밀 | `원산지` | 터키 | `SRC-173` |
| 밀 | `주로` | 보통계 | `SRC-173` |
| Frederick James R. | `저술` | Crop Science | `SRC-174` |
| Bauer Philip J. | `저술` | Crop Science | `SRC-174` |
| Busscher Warren J. | `저술` | Crop Science | `SRC-174` |
| 2001 | `출판됨` | Crop Science | `SRC-174` |
| Synthetic hexaploid wheat | `derived from` | durum [ Triticum turgidum L. (syn. Triticum durum Desf.)] | `SRC-175` |
| Synthetic hexaploid wheat | `derived from` | Aegilops tauschii Coss. | `SRC-175` |
| Synthetic hexaploid wheat | `source of genes for` | bread wheat ( Triticum aestivum L.) | `SRC-175` |
