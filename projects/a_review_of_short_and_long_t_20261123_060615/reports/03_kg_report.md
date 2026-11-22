# 3단계 지식그래프 구축 보고서 — 《토양 유기물 분해에 관한 장단기 모델 리뷰》

- **생성 시각**: `2026-11-22T21:19:25+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **27건** (신규 처리: 0건)
- **증분 반영 결과**: 노드 **+0** (누적 `4269`) · 관계 **+0** (누적 `4610`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **발행연도** | `KEY_TERM` | 258 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스** | `METRIC` | 256 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **DOI / URL** | `METRIC` | 253 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **저자** | `KEY_TERM` | 251 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **학술지 / 학회** | `KEY_TERM` | 251 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **피인용수** | `KEY_TERM` | 251 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **분류** | `KEY_TERM` | 251 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스 본문 발췌 (PDF** | `SECTION_CONCEPT` | 13 | `SRC-125,SRC-129,SRC-135,SRC-149,SRC-230,` |
| **international_journal** | `METRIC` | 11 | `SRC-07,SRC-09,SRC-151,SRC-152,SRC-166,SR` |
| **오픈액세스 본문 발췌 (PDF 다운로드** | `SECTION_CONCEPT` | 10 | `SRC-295,SRC-302,SRC-306,SRC-316,SRC-319,` |
| **산도(pH)** | `CONCEPT` | 9 | `SRC-02,SRC-132,SRC-133,SRC-148,SRC-15,SR` |
| **2016** | `EVENT` | 9 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **korean_society** | `ORG` | 9 | `SRC-116,SRC-182,SRC-218,SRC-219,SRC-220,` |
| **농촌진흥청** | `ORG` | 8 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **Nature** | `PRODUCT` | 7 | `SRC-07,SRC-09,SRC-236,SRC-249,SRC-301,SR` |
| **2017** | `EVENT` | 7 | `SRC-133,SRC-152,SRC-168,SRC-241,SRC-30,S` |
| **2019** | `EVENT` | 7 | `SRC-127,SRC-158,SRC-164,SRC-233,SRC-37,S` |
| **2015** | `EVENT` | 6 | `SRC-09,SRC-11,SRC-118,SRC-163,SRC-226,SR` |
| **Global Change Biology** | `OTHER` | 6 | `SRC-10,SRC-204,SRC-208,SRC-296,SRC-56,SR` |
| **2021** | `EVENT` | 6 | `SRC-120,SRC-156,SRC-189,SRC-234,SRC-283,` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| soil organic matter (SOM) | `requires knowledge to address` | global change | `SRC-10` |
| soil organic matter (SOM) | `separates into` | particulate (POM) | `SRC-10` |
| soil organic matter (SOM) | `separates into` | mineral-associated (MAOM) | `SRC-10` |
| CO 2 | `증가시킴` | global photosynthesis | `SRC-235` |
| CO 2 | `잠재적으로 증가시킴` | terrestrial carbon sink | `SRC-235` |
| CO 2 | `영향을 미침` | terrestrial carbon sink | `SRC-235` |
| Eric A. Davidson | `저자` | Nature | `SRC-07` |
| Ivan A. Janssens | `저자` | Nature | `SRC-07` |
| Nature | `발행연도` | 2006 | `SRC-07` |
| Nature | `DOI` | https://doi.org/10.1038/nature04514 | `SRC-07` |
| Nature | `피인용수` | 7777회 | `SRC-07` |
| Nature | `분류` | international_journal | `SRC-07` |
| Else K. Bünemann | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| Giulia Bongiorno | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| Zhanguo Bai | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| Rachel Creamer | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| Gerlinde B. De Deyn | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| R.G.M. de Goede | `저술함` | Soil Biology and Biochemistry | `SRC-08` |
| Soil Biology and Biochemistry | `published_in` | 2021 | `SRC-234` |
| Soil Biology and Biochemistry | `has_doi` | https://doi.org/10.1016/j.soilbio.2021.108189 | `SRC-234` |
| Soil Biology and Biochemistry | `has_citation_count` | 1290회 | `SRC-234` |
| soil quality | `검토함` | soil attributes | `SRC-08` |
| soil quality | `평가함` | soil threats | `SRC-08` |
| soil quality | `관련됨` | soil functions | `SRC-08` |
| soil quality | `관련됨` | ecosystem services | `SRC-08` |
