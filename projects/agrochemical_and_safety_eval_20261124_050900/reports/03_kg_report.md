# 3단계 지식그래프 구축 보고서 — 《농약학 및 안정성 평가》

- **생성 시각**: `2026-11-23T20:40:39+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **14건** (신규 처리: 12건)
- **증분 반영 결과**: 노드 **+147** (누적 `4745`) · 관계 **+96** (누적 `5617`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **발행연도** | `KEY_TERM` | 362 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스** | `METRIC` | 361 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **DOI / URL** | `METRIC` | 357 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **저자** | `KEY_TERM` | 355 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **학술지 / 학회** | `KEY_TERM` | 355 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **피인용수** | `KEY_TERM` | 355 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **분류** | `KEY_TERM` | 355 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스 본문 발췌 (PDF 다운로드** | `SECTION_CONCEPT` | 25 | `SRC-295,SRC-302,SRC-306,SRC-316,SRC-319,` |
| **2021** | `EVENT` | 10 | `SRC-120,SRC-156,SRC-189,SRC-234,SRC-283,` |
| **korean_society** | `ORG` | 10 | `SRC-116,SRC-182,SRC-218,SRC-219,SRC-220,` |
| **메타데이터/초록** | `CONCEPT` | 9 | `SRC-09,SRC-116,SRC-182,SRC-218,SRC-219,S` |
| **2017** | `EVENT` | 9 | `SRC-133,SRC-152,SRC-168,SRC-241,SRC-30,S` |
| **wheat** | `CONCEPT` | 8 | `SRC-144,SRC-186,SRC-192,SRC-193,SRC-201,` |
| **2006** | `EVENT` | 4 | `SRC-07,SRC-167,SRC-232,SRC-509` |
| **agriculture** | `CONCEPT` | 3 | `SRC-43,SRC-47,SRC-541` |
| **pesticides** | `CONCEPT` | 3 | `SRC-46,SRC-541,SRC-78` |
| **Pakistan** | `LAW` | 3 | `SRC-191,SRC-193,SRC-538` |
| **nanoparticles** | `CONCEPT` | 3 | `SRC-230,SRC-305,SRC-524` |
| **1회** | `METRIC` | 2 | `SRC-118,SRC-507` |
| **pharmaceuticals** | `PRODUCT` | 2 | `SRC-148,SRC-540` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| pesticides | `사용됨` | agriculture | `SRC-541` |
| pesticides | `포함함` | insecticide | `SRC-541` |
| pesticides | `포함함` | herbicide | `SRC-541` |
| pesticides | `포함함` | fungicide | `SRC-541` |
| pesticides | `주요 사용 대상` | cotton crops | `SRC-541` |
| pesticides | `사용됨` | paddy | `SRC-541` |
| pesticides | `사용됨` | wheat | `SRC-541` |
| Food is Never Waste Coalition | `co-led by` | UNEP | `SRC-136` |
| Food is Never Waste Coalition | `aims to advance` | Agenda 2030 | `SRC-136` |
| Agenda 2030 | `targets` | SDG target 12.3 | `SRC-136` |
| 2026 IDAFLW | `held alongside` | 28th Session of FAO Committee on Forestry (COFO28) | `SRC-136` |
| 2026 IDAFLW | `held alongside` | World Forest Week | `SRC-136` |
| Youth for food, not waste: A facilitation guide for a youth-led month of action on food waste | `developed by` | UNEP | `SRC-136` |
| pharmaceuticals | `포함` | PPCPs | `SRC-540` |
| nanoparticles | `사용됨` | agricultural production | `SRC-524` |
| nanoparticles | `개선함` | agricultural chemicals | `SRC-524` |
| nanoparticles | `흡수됨` | crops | `SRC-524` |
| nanoparticles | `흡수 및 이동 메커니즘을 가짐` | crops | `SRC-524` |
| nanoparticles | `영향을 미침` | plant physiological activities | `SRC-524` |
| nanoparticles | `흡수 및 운송 연구의 주제` | leaf | `SRC-524` |
| nanoparticles | `흡수 및 운송 연구의 주제` | root | `SRC-524` |
| Technical Platform on the Measurement and Reduction of Food Loss | `포함한다` | Food loss and waste reduction, measurement and policies | `SRC-136` |
| Technical Platform on the Measurement and Reduction of Food Loss | `포함한다` | FAO stories | `SRC-136` |
| Artificial intelligence and IoT driven technologies for environm | `포함한다` | 오픈액세스 본문 발췌 (PDF 다운로드 | `SRC-350` |
| Artificial intelligence and IoT driven technologies for environm | `포함한다` | 오픈액세스 본문 발췌 (PDF 다운로드 | `SRC-350` |
