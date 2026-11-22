# 3단계 지식그래프 구축 보고서 — 《작물 생육모형》

- **생성 시각**: `2026-11-22T20:28:59+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **29건** (신규 처리: 21건)
- **증분 반영 결과**: 노드 **+227** (누적 `4182`) · 관계 **+129** (누적 `4385`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **발행연도** | `KEY_TERM` | 230 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스** | `METRIC` | 228 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **DOI / URL** | `METRIC` | 225 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **저자** | `KEY_TERM` | 223 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **학술지 / 학회** | `KEY_TERM` | 223 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **피인용수** | `KEY_TERM` | 223 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **분류** | `KEY_TERM` | 223 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **Korean Journal of Soil Science and Fertilizer** | `PRODUCT` | 12 | `SRC-11,SRC-12,SRC-13,SRC-217,SRC-219,SRC` |
| **2016** | `EVENT` | 9 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **korean_society** | `ORG` | 9 | `SRC-116,SRC-182,SRC-218,SRC-219,SRC-220,` |
| **농촌진흥청** | `ORG` | 8 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **Nature** | `PRODUCT` | 7 | `SRC-07,SRC-09,SRC-236,SRC-249,SRC-301,SR` |
| **Global Change Biology** | `OTHER` | 6 | `SRC-10,SRC-204,SRC-208,SRC-296,SRC-56,SR` |
| **2023** | `EVENT` | 6 | `SRC-12,SRC-183,SRC-294,SRC-297,SRC-300,S` |
| **2022** | `EVENT` | 6 | `SRC-13,SRC-132,SRC-182,SRC-292,SRC-97,SR` |
| **2021** | `EVENT` | 6 | `SRC-120,SRC-156,SRC-189,SRC-234,SRC-283,` |
| **climate change** | `CONCEPT` | 6 | `SRC-182,SRC-210,SRC-299,SRC-37,SRC-46,SR` |
| **temperature** | `CONCEPT` | 5 | `SRC-02,SRC-198,SRC-208,SRC-287,SRC-55` |
| **Soil Science** | `PRODUCT` | 5 | `SRC-222,SRC-223,SRC-224,SRC-291,SRC-94` |
| **2013** | `EVENT` | 5 | `SRC-157,SRC-187,SRC-219,SRC-290,SRC-291` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| temperature | `affect` | spring wheat (Triticum aestivum L., cv. Polkka) | `SRC-287` |
| Korean Journal of Soil Science and Fertilizer | `발행연도` | 2025 | `SRC-86` |
| Shim Jae-Hong | `저자` | Korean Journal of Soil Science and Fertilizer | `SRC-86` |
| Jeon Sang-Ho | `저자` | Korean Journal of Soil Science and Fertilizer | `SRC-86` |
| 2023 | `발행됨` | Plants | `SRC-297` |
| soil texture | `영향력` | plant water stress | `SRC-295` |
| 농촌진흥청 | `포함한다` | 채용공고 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 알립니다 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 전체 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 보도자료 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 공지사항 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 입찰공고 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 인물/동정 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 주요행사 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 알림판 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 농사로 바로가기 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 정책브리핑 뉴스 위젯으로 구성되어 있습니다 | `SRC-100` |
| 농촌진흥청 | `포함한다` | 농업기술원 | `SRC-100` |
| climate change | `affects` | biodiversity | `SRC-299` |
| climate change | `operates at` | individual | `SRC-299` |
| climate change | `operates at` | population | `SRC-299` |
| climate change | `operates at` | species | `SRC-299` |
| climate change | `operates at` | community | `SRC-299` |
| climate change | `operates at` | ecosystem | `SRC-299` |
| climate change | `operates at` | biome | `SRC-299` |
