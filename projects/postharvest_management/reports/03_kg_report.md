# 3단계 지식그래프 구축 보고서 — 《수확, 수확 후 관리 및 품질 평가》

- **생성 시각**: `2026-11-21T14:17:24+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **69건** (신규 처리: 69건)
- **증분 반영 결과**: 노드 **+907** (누적 `2058`) · 관계 **+581** (누적 `1335`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **international_journal** | `METRIC` | 10 | `SRC-07,SRC-09,SRC-151,SRC-152,SRC-166,SR` |
| **산도(pH)** | `CONCEPT` | 8 | `SRC-02,SRC-132,SRC-133,SRC-148,SRC-15,SR` |
| **농촌진흥청** | `ORG` | 7 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **firmness** | `CONCEPT` | 7 | `SRC-114,SRC-115,SRC-122,SRC-129,SRC-131,` |
| **메타데이터/초록** | `CONCEPT` | 6 | `SRC-09,SRC-116,SRC-182,SRC-59,SRC-93,SRC` |
| **2017** | `EVENT` | 6 | `SRC-133,SRC-152,SRC-168,SRC-30,SRC-77,SR` |
| **2019** | `EVENT` | 6 | `SRC-127,SRC-158,SRC-164,SRC-37,SRC-58,SR` |
| **2016** | `EVENT` | 6 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **2022** | `EVENT` | 5 | `SRC-13,SRC-132,SRC-182,SRC-97,SRC-99` |
| **오픈액세스** | `METRIC` | 5 | `SRC-151,SRC-152,SRC-166,SRC-77,SRC-83` |
| **wheat** | `CONCEPT` | 5 | `SRC-144,SRC-186,SRC-192,SRC-193` |
| **2015** | `EVENT` | 4 | `SRC-09,SRC-11,SRC-118,SRC-163` |
| **FAO** | `ORG` | 4 | `SRC-124,SRC-137,SRC-20,SRC-47` |
| **2021** | `EVENT` | 4 | `SRC-120,SRC-156,SRC-189,SRC-29` |
| **oxygen** | `CONCEPT` | 3 | `SRC-02,SRC-145,SRC-146` |
| **Food and Agriculture Organization of the United Nations** | `ORG` | 3 | `SRC-137,SRC-193,SRC-20` |
| **fungi** | `ORG` | 3 | `SRC-150,SRC-21,SRC-46` |
| **food** | `PRODUCT` | 3 | `SRC-140,SRC-152,SRC-46` |
| **farmers** | `PERSON` | 3 | `SRC-140,SRC-48,SRC-84` |
| **2018** | `EVENT` | 3 | `SRC-154,SRC-83,SRC-95` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| oxygen | `is reduced in` | Controlled atmosphere | `SRC-145` |
| oxygen | `causes` | lipid oxidation reactions | `SRC-146` |
| oxygen | `encourages growth of` | aerobic spoilage microorganisms | `SRC-146` |
| international_journal | `분류` | Frontiers in bioscience | `SRC-167` |
| Microorganisms | `published_in` | 2017 | `SRC-168` |
| FAO | `관련됨` | SDG 12.3 | `SRC-137` |
| Food and Agriculture Organization of the United Nations | `운영함` | FLW Database | `SRC-137` |
| insects | `cannot survive without` | oxygen | `SRC-145` |
| 농촌진흥청 | `제공함` | 정보공개제도 | `SRC-101` |
| 농촌진흥청 | `관리함` | 업무추진비 | `SRC-101` |
| 농촌진흥청 | `공개함` | 공공데이터개방 | `SRC-101` |
| 농촌진흥청 | `운영함` | 농업기술 상담예약 | `SRC-101` |
| 농촌진흥청 | `발행함` | 농업분야규제혁신 사례 | `SRC-101` |
| 농촌진흥청 | `관련됨` | 규제법령정보 | `SRC-101` |
| 농촌진흥청 | `발행함` | 농촌진흥사업 기본(시행)계획 | `SRC-101` |
| 농촌진흥청 | `연구함` | 농업과학기술 연구개발계획 | `SRC-101` |
| 농촌진흥청 | `제시함` | 농촌지도사업 시행지침 | `SRC-101` |
| 농촌진흥청 | `보고함` | 2025년 연구성과 보고서 | `SRC-101` |
| 농촌진흥청 | `공개함` | 정부출범 1주년 성과 | `SRC-101` |
| 농촌진흥청 | `활용함` | 농업기술 | `SRC-101` |
| 농촌진흥청 | `운영함` | 그린매거진 | `SRC-101` |
| 농촌진흥청 | `제공함` | 사진마당 | `SRC-101` |
| 농촌진흥청 | `관리함` | 채용공고 | `SRC-101` |
| 농촌진흥청 | `참조함` | 국가법령정보센터 | `SRC-101` |
| 농촌진흥청 | `발표함` | 청장인사말 | `SRC-101` |
