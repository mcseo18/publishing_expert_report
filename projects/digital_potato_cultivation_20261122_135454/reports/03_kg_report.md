# 3단계 지식그래프 구축 보고서 — 《디지털 감자 재배》

- **생성 시각**: `2026-11-22T05:07:48+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **27건** (신규 처리: 6건)
- **증분 반영 결과**: 노드 **+56** (누적 `3103`) · 관계 **+40** (누적 `2020`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **산도(pH)** | `CONCEPT` | 9 | `SRC-02,SRC-132,SRC-133,SRC-148,SRC-15,SR` |
| **korean_society** | `ORG` | 8 | `SRC-116,SRC-182,SRC-218,SRC-219,SRC-220,` |
| **농촌진흥청** | `ORG` | 7 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **2017** | `EVENT` | 7 | `SRC-133,SRC-152,SRC-168,SRC-241,SRC-30,S` |
| **2019** | `EVENT` | 7 | `SRC-127,SRC-158,SRC-164,SRC-233,SRC-37,S` |
| **2016** | `EVENT` | 7 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **Nature** | `PRODUCT` | 6 | `SRC-07,SRC-09,SRC-236,SRC-249,SRC-80,SRC` |
| **soil organic matter (SOM)** | `CONCEPT` | 5 | `SRC-04,SRC-10,SRC-42,SRC-51,SRC-54` |
| **2015** | `EVENT` | 5 | `SRC-09,SRC-11,SRC-118,SRC-163,SRC-226` |
| **Global Change Biology** | `OTHER` | 5 | `SRC-10,SRC-204,SRC-208,SRC-56,SRC-58` |
| **soil organic matter** | `CONCEPT` | 5 | `SRC-03,SRC-20,SRC-235,SRC-58,SRC-82` |
| **2021** | `EVENT` | 5 | `SRC-120,SRC-156,SRC-189,SRC-234,SRC-29` |
| **soil organic carbon** | `CONCEPT` | 4 | `SRC-04,SRC-227,SRC-37,SRC-58` |
| **farmers** | `PERSON` | 4 | `SRC-140,SRC-203,SRC-48,SRC-84` |
| **Soil Science** | `PRODUCT` | 4 | `SRC-222,SRC-223,SRC-224,SRC-94` |
| **2006** | `EVENT` | 3 | `SRC-07,SRC-167,SRC-232` |
| **soil carbon sequestration** | `METRIC` | 3 | `SRC-38,SRC-84,SRC-86` |
| **biochar** | `PERSON` | 3 | `SRC-225,SRC-39,SRC-86` |
| **food** | `PRODUCT` | 3 | `SRC-140,SRC-152,SRC-46` |
| **토양 유기탄소(SOC)** | `CONCEPT` | 3 | `SRC-225,SRC-62,SRC-89` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| soil organic matter (SOM) | `requires knowledge to address` | global change | `SRC-10` |
| soil organic matter (SOM) | `separates into` | particulate (POM) | `SRC-10` |
| soil organic matter (SOM) | `separates into` | mineral-associated (MAOM) | `SRC-10` |
| CO 2 | `증가시킴` | global photosynthesis | `SRC-235` |
| CO 2 | `잠재적으로 증가시킴` | terrestrial carbon sink | `SRC-235` |
| CO 2 | `영향을 미침` | terrestrial carbon sink | `SRC-235` |
| Soil Biology and Biochemistry | `published_in` | 2021 | `SRC-234` |
| Soil Biology and Biochemistry | `has_doi` | https://doi.org/10.1016/j.soilbio.2021.108189 | `SRC-234` |
| Soil Biology and Biochemistry | `has_citation_count` | 1290회 | `SRC-234` |
| Jocelyn M. Lavallee | `authored` | Global Change Biology | `SRC-10` |
| Jennifer L. Soong | `authored` | Global Change Biology | `SRC-10` |
| M. Francesca Cotrufo | `authored` | Global Change Biology | `SRC-10` |
| M. Francesca Cotrufo | `저자` | Nature Geoscience | `SRC-233` |
| particulate (POM) | `contrasts with` | mineral-associated (MAOM) | `SRC-10` |
| 2017 | `발행연도` | Geoderma | `SRC-84` |
| biochar | `영향` | 토양 유기탄소(SOC) | `SRC-225` |
| Johan Six | `저자` | Nature Geoscience | `SRC-233` |
| food | `impacts` | health | `SRC-140` |
| researchers | `rarely appreciate` | rural people's knowledge | `SRC-247` |
| soil carbon storage | `관련됨` | elevated CO2 | `SRC-236` |
| SOC | `관련됨` | Developments in Soil Science | `SRC-221` |
| Biochar | `sequesters` | carbon dioxide | `SRC-227` |
| Biochar | `sequesters` | methane | `SRC-227` |
| Biochar | `sequesters` | nitrous oxide | `SRC-227` |
| Biochar | `is produced by` | pyrolizing biomass | `SRC-227` |
