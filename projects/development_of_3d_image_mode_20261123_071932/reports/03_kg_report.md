# 3단계 지식그래프 구축 보고서 — 《작물 대상 3차원 이미지 모델 개발》

- **생성 시각**: `2026-11-22T22:25:50+00:00`
- **통합 저장소**: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` (기존 `C:\SMC_GRAPHRAG\output\graph.json` 100% 무훼손 보존)
- **프로젝트 대상 자료 수**: **27건** (신규 처리: 20건)
- **증분 반영 결과**: 노드 **+224** (누적 `4531`) · 관계 **+166** (누적 `5056`)

## 핵심 추출 엔티티 (상위 20개)

| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |
| :--- | :---: | :---: | :--- |
| **발행연도** | `KEY_TERM` | 299 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스** | `METRIC` | 298 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **DOI / URL** | `METRIC` | 294 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **저자** | `KEY_TERM` | 292 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **학술지 / 학회** | `KEY_TERM` | 292 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **피인용수** | `KEY_TERM` | 292 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **분류** | `KEY_TERM` | 292 | `SRC-07,SRC-08,SRC-09,SRC-10,SRC-109,SRC-` |
| **오픈액세스 본문 발췌 (PDF 다운로드** | `SECTION_CONCEPT` | 17 | `SRC-295,SRC-302,SRC-306,SRC-316,SRC-319,` |
| **international_journal** | `METRIC` | 12 | `SRC-07,SRC-09,SRC-151,SRC-152,SRC-166,SR` |
| **2023** | `EVENT` | 10 | `SRC-12,SRC-183,SRC-294,SRC-297,SRC-300,S` |
| **2016** | `EVENT` | 10 | `SRC-116,SRC-117,SRC-119,SRC-160,SRC-180,` |
| **2021** | `EVENT` | 9 | `SRC-120,SRC-156,SRC-189,SRC-234,SRC-283,` |
| **농촌진흥청** | `ORG` | 8 | `SRC-100,SRC-101,SRC-103,SRC-172,SRC-26,S` |
| **2017** | `EVENT` | 8 | `SRC-133,SRC-152,SRC-168,SRC-241,SRC-30,S` |
| **2019** | `EVENT` | 8 | `SRC-127,SRC-158,SRC-164,SRC-233,SRC-356,` |
| **temperature** | `CONCEPT` | 6 | `SRC-02,SRC-198,SRC-208,SRC-287,SRC-346,S` |
| **Foods** | `PERSON` | 5 | `SRC-124,SRC-132,SRC-152,SRC-343,SRC-353` |
| **farmers** | `PERSON` | 4 | `SRC-140,SRC-203,SRC-48,SRC-84` |
| **Climate change** | `CONCEPT` | 4 | `SRC-227,SRC-297,SRC-355,SRC-89` |
| **Crossref** | `ORG` | 4 | `SRC-118,SRC-222,SRC-337,SRC-98` |

## 핵심 지식 관계망 (Triples 발췌)

| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |
| :--- | :---: | :--- | :--- |
| temperature | `사용된 특징` | crop yield prediction | `SRC-346` |
| rainfall | `사용된 특징` | crop yield prediction | `SRC-346` |
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
| food | `impacts` | health | `SRC-140` |
| 한국식품연구원 | `포함함` | 전략기획본부 | `SRC-102` |
| 한국식품연구원 | `포함함` | 경영지원본부 | `SRC-102` |
| 한국식품연구원 | `포함함` | 감사부 | `SRC-102` |
| 한국식품연구원 | `협력함` | UST | `SRC-102` |
| 한국식품연구원 | `운영함` | 식품융합연구본부 | `SRC-102` |
| 한국식품연구원 | `운영함` | 식품기능연구본부 | `SRC-102` |
| 한국식품연구원 | `운영함` | 식품산업연구본부 | `SRC-102` |
| 한국식품연구원 | `추구함` | 국민건강 증진 | `SRC-102` |
| 한국식품연구원 | `추구함` | 국민안전먹거리 제공 | `SRC-102` |
| 한국식품연구원 | `포함한다` | 국민안전먹거리 제공 | `SRC-102` |
