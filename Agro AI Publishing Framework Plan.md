# **참참살이 영농 AI 출판도우미: 한정 자원 기반의 고효율 AI 전문 출판 프레임워크 및 수익화·운영 보완 계획서**

# **1\. 현재 시스템 및 파이프라인 자원 진단**

개인 연구자나 전문 작가가 한정된 자원과 시간으로 대형 출판사에 필적하는 학술·도메인 전문 도서를 지속적으로 출판하기 위해서는 기존 시스템 자원에 대한 정밀한 파이프라인 분석과 체계적인 구조화가 선행되어야 한다 [\[1, 2\]](#sources). 현재 구축된 시스템(`publishing_expert_report` 및 `SMC_Report_Platform_Data`)은 6단계 표준 자동화 제작 파이프라인과 관제 대시보드 인프라를 구축하고 있다 [\[1\]](#sources).

기존 파이프라인은 분업화된 에이전트 모듈 구조로 구현되어 완결성 높은 조판 프로세스를 수행한다 [\[1\]](#sources):

* **1단계 (`stage1_topic_outline` / `outline-architect`)**: AI 기반 목차, 요약, 핵심 키워드를 자동 추출하고 검토·확정하는 관문(`WAITING_REVIEW`)을 운용한다 [\[1\]](#sources).  
* **2단계 (`stage2_source_collect` / `web-scout`)**: 국내외 정부 기관, 학술지, 전문 웹사이트로부터 수집한 출처를 4계층으로 분리 및 검증하여 기초 데이터를 구조화한다 [\[1, 2\]](#sources).  
* **3단계 (`stage3_kg_build` / `kg-builder`)**: 로컬 지식그래프(`C:\SMC_GRAPHRAG`)를 증분 구축하여 엔티티 간 상호관계를 도출하고 지식그래프 분석 보고서를 생성한다 [\[1, 2\]](#sources).  
* **4단계 (`stage4_manuscript_draft` / `domain-drafter`)**: 검증된 근거 패킷을 바탕으로 단원별 본문을 집필하며, 모든 주요 명제에 `[SRC-NN]` 인용을 자동 표기하고 '오해와 진실(Myths)', 1:1 체크포인트 및 문제-풀이 앵커를 결합한다 [\[1, 2\]](#sources).  
* **5단계 (`stage5_visuals_generate` / `visual-artist` / `textbook-visual-director`)**: 단원당 10\~15종 이상의 시각화 자료를 A(현장실사), B(스튜디오 표본), C(개념 도해), D(Python `matplotlib` 정량 차트) 4개 유형으로 분류하여 자동 생성하고 원고에 1:1 매핑한다 [\[1, 2\]](#sources).  
* **6단계 (`stage6_publish_report` / `book-publisher`)**: Single-Source 원고로부터 다중 판형 PDF(신국판 152×225mm, B5 대학교재 182×257mm, A4 마스터판 210×297mm), Word DOCX, 네이버 블로그 전용 HTML을 자동 조판·제본한다 [\[1, 2\]](#sources).

원천 지식 자산 측면에서는 생육·생리, 양분·토양, 유전·종자, 작물보호, 생육모형·디지털농업, 수확후·품질, 지속가능성의 7개 영역에 걸친 31개 범용 핵심 키워드 체계를 보유하고 있으며 [\[2\]](#sources), 스마트 벼, 콩, 감자, 고추, 토양학, 재배생리학, 해외 농업 트렌드 등 17개 이상의 스페셜티 전문 분야 커리큘럼 데이터가 결합되어 있다 [\[3, 4\]](#sources).

| 파이프라인 단계 | 실행 모듈명 | 주요 처리 데이터 및 산출물 | 핵심 자동화 및 품질 검증 메커니즘 |
| :---- | :---- | :---- | :---- |
| **1단계: 기획 및 목차** | `stage1_topic_outline` | 목차 트리, 키워드 명세, `state.json` | `WAITING_REVIEW` 관문을 통한 전문가 인간 검토 연동 [\[1\]](#sources) |
| **2단계: 근거 수집** | `stage2_source_collect` | 4계층 출처 웹 수집 데이터, `02_collection_report.md` | 공공 API, 학술지, 전문DB 4계층 분류 수집 [\[1, 2\]](#sources) |
| **3단계: KG 구축** | `stage3_kg_build` | `C:\SMC_GRAPHRAG`, 엔티티-관계 트리플, KG 리포트 | 로컬 GraphRAG 기반 지식 네트워크 증분 업데이트 [\[1, 2\]](#sources) |
| **4단계: 원고 집필** | `stage4_manuscript_draft` | 단원별 Markdown (`chNN.md`), `[SRC-NN]` 인용 | 1:1 문제-풀이, 오해와 진실(≥3선), 출처 감사 [\[1, 2\]](#sources) |
| **5단계: 시각화 제작** | `stage5_visuals_generate` | A/B/C/D 유형 이미지, `visuals_text_guide.md` | Zero-Text 규율 실약 적용, Python 차트 인라인 합성 [\[1, 2\]](#sources) |
| **6단계: 다중 제본** | `stage6_publish_report` | 신국판/B5/A4 PDF, Word DOCX, 블로그 HTML | Pandoc/Quarto 엔진 기반 원클릭 멀티 포맷 조판 [\[1, 2\]](#sources) |

현재 구축된 시스템은 로컬 대형 언어 모델(Ollama Gemma 4 26B 등)과 로컬 GraphRAG 엔진을 연동하여 외부 API 의존 비용을 최소화하고 AI의 환각(Hallucination) 현상을 억제하는 고품질 지식 생성 기반을 확보하고 있다 [\[1, 5\]](#sources). 다만 1인 출판 환경에서 생산성을 극대화하기 위해서는 시각화 통합, 멀티 포맷 자동 제본, 반응형 대시보드 UI/UX, 다각화된 수익 모델에 관한 보완 체계가 추가 반영되어야 한다 [\[1, 2\]](#sources).

# **2\. 1인 전문 출판을 위한 고효율 파이프라인 보완 방안**

한정된 자원으로 최고 수준의 전문 도서를 지속 가능하게 출판하기 위해서는 검색, 문장 생성, 시각화, 통합 조판 모듈이 단절 없이 유기적으로 연동되는 단일 원출처(Single Source of Truth) 기반 파이프라인을 정립해야 한다 [\[2\]](#sources).

## **가. 문맥 인지형 장·단원 자동 분할 및 원고 집필 체계**

기초 지식 데이터 및 키워드를 표준 교재 구조로 변환하기 위해 문맥 인지형 분할기(Context-Aware Chunking Engine)를 도입한다 [\[2\]](#sources). 입력된 전문 지식은 '개념 소개 및 이론적 배경 → 생리·분자 메커니즘 → 현장 적용 및 실전 기술 → 관련 법규 및 정책 지침'의 4단계 표준 구조로 자동 챕터화된다 [\[2\]](#sources).

`domain-drafter` 모듈은 이 구조에 따라 장(Chapter), 단원(Section), 절(Subsection) 단위로 원고를 분할 집필한다 [\[1, 2\]](#sources). 집필 과정에서 로컬 지식그래프에 등록된 엔티티 관계(예: `부숙도` —\[규정한다\]→ `가축분뇨법`)를 추출하여 본문 각주 및 인용으로 자동 변환함으로써 학술적 정밀성을 유지한다 [\[2\]](#sources).

## **나. GraphRAG 기반 하이브리드 검색 및 검증 감사 엔진**

기존 Vector RAG 방식은 단락 간 분절로 인해 복잡한 다중 홉(Multi-hop) 추론이나 문헌 간 서술 구조 분석 시 맥락 손실을 초래하고, 표(Table)나 수식의 헤더 정보를 파괴하는 한계가 있다 [\[6, 7\]](#sources). 이에 따라 로컬 GraphRAG 기반의 하이브리드 검색 엔진을 고도화한다 [\[1, 2, 6\]](#sources).

GraphRAG 엔진은 단어 간 유사도 검색을 넘어, 지식 인프라로부터 추출된 엔티티와 관계 노드 트리플(`[Entity A] --[relationship]--> [Entity B]`)을 구조화하여 탐색한다 [\[5, 8\]](#sources). 쿼리 처리기, 탐색기, 조직기, 생성기로 이어지는 파이프라인을 통해 전역적 주제 요약(Query-focused Text Summarization)과 다중 문헌 합성 기능을 실행한다 [\[6, 7\]](#sources).

본문 집필 후에는 `verify_citations.py` 감사 스크립트가 구동되어 모든 명제에 표기된 `[SRC-NN]` 인용 문구가 실제 로컬 근거 패킷 및 공공 API 데이터와 1:1 일치하는지 자동 검증한다 [\[1, 2\]](#sources).

| 비교 항목 | 기존 Vector 기반 Naive RAG | 구축 대상 GraphRAG 하이브리드 엔진 | 출판 파이프라인 적용 효과 |
| :---- | :---- | :---- | :---- |
| **검색 메커니즘** | 단열 텍스트 임베딩 벡터 유사도 검색 [\[6, 7\]](#sources) | 엔티티-관계 지식그래프 \+ 벡터 하이브리드 탐색 [\[6\]](#sources) | 복잡한 생리 메커니즘 및 다중 문헌 관계 완전 복원 [\[6, 8\]](#sources) |
| **표·데이터 처리** | 텍스트 분할 시 헤더/각주 정보 파괴 현상 발생 [\[7\]](#sources) | 레이아웃 및 구조적 관계 노드 보존 [\[7\]](#sources) | 데이터 표, 수치 비교, 수식의 정밀 인용 보장 [\[1, 7\]](#sources) |
| **전역 주제 요약** | 전체 문헌 요약 시 텍스트 용량 초과 및 환각 발생 [\[7\]](#sources) | 사전 연산된 커뮤니티 요약 트리(Community Summary) 활용 [\[5, 7\]](#sources) | 단원 전체 종합 및 서론/결론 자동 작성 정밀도 대폭 향상 [\[2, 5\]](#sources) |
| **환각 억제 능력** | 통계적 유사성에 의존하여 개연성 있는 오답 생성 [\[5, 8\]](#sources) | 명시적 지식 트리플에 근거하여 출처 1:1 바인딩 [\[1, 5, 8\]](#sources) | 출판물의 학술적 신뢰도 확보 및 감사 자동화 [\[1, 2\]](#sources) |

## **다. 멀티 포맷 싱글 소스 조판 및 시각화 자동화**

원고 제작 시 하나의 마스터 소스 파일(`.qmd` 또는 `.mdx`)을 유지하면서 인쇄용 PDF, Word 보고서, 웹 콘텐츠를 동시 빌드하는 조판 엔진을 완비한다 [\[1, 2\]](#sources). Quarto 및 Pandoc 엔진과 연동하여 단 한 번의 빌드 명령으로 다양한 출판 판형을 도출한다 [\[1, 2, 9\]](#sources).

* **신국판 (152×225mm)**: 단행본 및 일반 상업 출판용 표준 판형 [\[1, 2\]](#sources).  
* **B5 대학교재판 (182×257mm)**: 학술 교재, 강의용 텍스트, 가이드북용 판형 [\[1, 2\]](#sources).  
* **A4 마스터판 (210×297mm)**: 정부 과제 보고서, 기술 용역서, 기관 제출용 판형 [\[1, 2\]](#sources).

시각화 엔진(`context_visual_director.py`)은 원고 내 데이터 수치 및 생리 지표를 감지하여 A, B, C, D 4유형 시각화 자원을 자동 생성하고 1:1 결합한다 [\[1, 2\]](#sources). A유형(현장 실사)은 zero-text 규율을 적용하여 이미지 내 텍스트 노이즈를 배제하고 고해상도 스케일바만 적용한다 [\[1\]](#sources). B유형(스튜디오 표본)은 피사체 중심의 고대비 표본 이미지를 수집 및 매핑한다 [\[1\]](#sources). C유형(개념 도해)은 Mermaid 코드 기반 구조 다이어그램 및 SVG를 자동 생성하며 [\[2\]](#sources), D유형(정량 차트)은 Python `matplotlib` 및 `seaborn`을 활용한 차트를 생성한다 [\[1, 2\]](#sources).

모든 시각화 자원은 인쇄용 300dpi 이상의 고해상도 파일과 웹/블로그용 72dpi 파일로 이중 저장되어 자동 배치된다 [\[2\]](#sources).

# **3\. 프리미엄 UI/UX 및 전문 브랜드 디자인 개편**

아마추어적인 이미지를 완전히 탈피하고 글로벌 학술 출판 플랫폼 수준의 인터페이스(UI)와 사용자 경험(UX)을 구축한다 [\[1, 2\]](#sources).

## **가. 비주얼 아이덴티티 및 타이포그래피 표준화**

농업 전문성과 지능형 기술을 상징하는 Emerald Agri(`#063b2c` / `#34d399`)를 주색으로 지정하고, 학술적 깊이를 더하는 Golden Wheat(`#0f291e` / `#eab308`) 및 Slate Gray 톤을 보조색으로 배치한다 [\[1, 2\]](#sources).

타이포그래피는 본문 명조체에 KoPubWorld 바탕/맑은 고딕을 적용하여 인쇄 판독성을 극대화하고, 제목 및 헤더 요소에는 감청색(`#1D3557`) 고해상도 산세리프 타이포그래피를 적용하여 시각적 위계를 형성한다 [\[1\]](#sources). 또한 실사 이미지 및 도해에 텍스트가 무분별하게 겹치는 현상을 차단하고 pure white background 또는 완전 독립형 캡션을 적용하여 전문 출판물의 visual quality를 확보한다 [\[1\]](#sources).

## **나. 엔터프라이즈급 대시보드 인터페이스 구조**

Streamlit 및 Electron 기반 단일 통합 대시보드 UI를 4개 핵심 영역으로 구획하여 집필 및 조판 과정을 실시간 모니터링한다 [\[1, 2\]](#sources).

| 대시보드 영역 | 주요 화면 요소 및 기능 | 실시간 모니터링 및 처리 데이터 |
| :---- | :---- | :---- |
| **Workspace Navigator (좌측)** | 17개 이상 챕터 트리 및 프로그레스 위젯 [\[1, 2\]](#sources) | 파이프라인 진행 상태(WAITING\_REVIEW, RUNNING, COMPLETED) 카드 표시 [\[1, 10\]](#sources) |
| **Multi-View Editor (중앙)** | WYSIWYG / Markdown 편집기 및 실시간 듀얼 프리뷰 [\[2\]](#sources) | 인쇄용 PDF 및 웹 HTML 실시간 라이브 조판 화면 확인 [\[2\]](#sources) |
| **Visual Asset Manager (우측)** | A/B/C/D 유형 시각화 자원 Drag & Drop 패널 [\[2\]](#sources) | 단원별 170여 종 이상의 PNG/SVG/차트 인라인 본문 삽입 [\[1, 2\]](#sources) |
| **Citation & QA Inspector (하단)** | 출처 검증 및 반응형 레이아웃 QA 패널 [\[2\]](#sources) | `[SRC-NN]` 인용 1:1 바인딩 검수 및 모바일/데스크톱 Layout 검증 [\[1, 2\]](#sources) |

## **다. 직관적 사용자 경험 및 데이터 해석 레이어**

시니어 농업인이나 비전문가 사용자도 시스템 연산 결과를 직관적으로 이해할 수 있도록 복잡한 계산 과정을 백엔드(Python)로 처리하고 표출 레이어를 단순화한다 [\[10\]](#sources).

예를 들어 생육 적산온도(GDD) 연산 시 백엔드에서는 일 최고기온(T\_max)과 일 최저기온(T\_min)의 평균값에서 작물별 기준온도(T\_base)를 차감한 뒤, 기준온도를 초과하는 일일 값을 누적 연산한다. 식 형태로는 `GDD = sum((T_max + T_min)/2 - T_base)`로 정의된다 [\[10\]](#sources).

백엔드 연산과 평년/작년 비교 검증을 거친 후 UI 화면에는 복잡한 숫자 대신 해석된 문장("작년보다 생육 온도가 적당해 작물 자람새가 5일 정도 빠릅니다")과 직관적인 신호등 상태 카드를 표출하여 인지 부담을 덜어준다 [\[10\]](#sources).

# **4\. 다각화 수익화(Monetization) 및 비즈니스 모델 구축**

개인 운영자가 구축된 프레임워크를 바탕으로 지속 가능한 수익을 창출하기 위해 B2C, B2B, B2G 및 SaaS를 아우르는 4단계 수익 모델을 도입한다 [\[1, 2\]](#sources).

1. **1단계 (B2C POD 및 전자책 출판)**: 개인 독자 및 소규모 연구자를 대상으로 주문 제작 출판 및 전자책을 판매한다 [\[1, 2\]](#sources).  
2. **2단계 (B2B 및 B2G 맞춤 용역)**: 농업기술센터, 지자체, 스마트팜 기업 대상 맞춤형 교재 및 보고서를 제작·납품한다 [\[1, 2\]](#sources).  
3. **3단계 (트래픽 마케팅 및 AI 아카데미)**: 네이버 블로그 자동 홍보를 통한 유입 트래픽을 아카데미 유료 구독 및 컨설팅으로 전환한다 [\[1, 2, 11\]](#sources).  
4. **4단계 (SaaS 및 API 라이선싱)**: 타 전문 분야 1인 저자 및 소형 출판사에 출판 엔진과 파이프라인 구독 서비스를 제공한다 [\[2\]](#sources).

| 수익화 채널 | 주 타깃 고객 | 출력 산출물 및 서비스 형태 | 수익 구조 및 상용화 모델 |
| :---- | :---- | :---- | :---- |
| **B2C POD 출판** | 일반 독자, 농업인, 귀농인 | 신국판/B5 POD 종이책 및 전자책 [\[1, 2\]](#sources) | 권당 판매 인세 수익 (재고 비용 0원) [\[1, 2\]](#sources) |
| **B2B/B2G 맞춤 제작** | 농업기술센터, 지자체, 스마트팜 기업 | A4/B5 기관 맞춤형 보고서 및 교재 [\[1, 2\]](#sources) | 권당/사업당 기술 용역 계약금 및 납품비 [\[1, 2\]](#sources) |
| **트래픽 마케팅** | 블로그 방문자, 영농 아카데미 회원 | 블로그 포스팅 HTML, 주간 리포트 [\[1, 2, 11\]](#sources) | 컨설팅 유입, 아카데미 수강료, 구독료 [\[1, 2, 11\]](#sources) |
| **SaaS 라이선싱** | 타 전문 분야 1인 저자, 소형 출판사 | AI 출판 도우미 파이프라인 엔진 [\[2\]](#sources) | 월/연 단위 SaaS 구독료 및 API 사용료 [\[2\]](#sources) |

# **5\. 단계별 실행 로드맵 및 시스템 보완 계획**

본 프레임워크의 완성을 위해 추진 과제를 4단계(Phase 1\~Phase 4)로 구분하고, 개발 및 검증 작업을 단계별로 이행한다 [\[1, 2\]](#sources).

## **Phase 1: 브랜드 아이덴티티 및 UI/UX 디자인 표준화**

대시보드 타이틀을 \*\*"참참살이 영농 AI 출판도우미"\*\*로 최종 변경하고 Emerald Agri 및 Golden Wheat 비주얼 테마를 대시보드 전체 CSS 및 컴포넌트에 표준 적용한다 [\[1, 2\]](#sources). 6단계 파이프라인 상태를 실시간 모니터링할 수 있는 스테이지 카드 위젯과 시니어/Low-Code 인터페이스를 구현한다 [\[1, 10\]](#sources).

## **Phase 2: GraphRAG 연동 및 검증 감사 자동화**

로컬 GraphRAG(`C:\SMC_GRAPHRAG`)와 본문 생성 모듈 간 동적 인터페이스를 확립하여, 문단 생성 시 지식 엔티티 및 트리플이 자동으로 출처 각주로 변환되도록 구축한다 [\[1, 2\]](#sources). `verify_citations.py` 검증 스크립트를 4단계 파이프라인 끝단에 상시 실행 관문으로 배치하여 인용 오류 발생 시 자동 수정 및 재집필 로직을 활성화한다 [\[1, 2\]](#sources).

## **Phase 3: 시각화 엔진 고도화 및 싱글 소스 조판 정밀화**

`context_visual_director.py` 기능을 강화하여 단원당 10\~15종의 A/B/C/D 시각화 자원이 본문 맥락에 따라 인라인 합성되도록 자동화한다 [\[1, 2\]](#sources). Quarto/Pandoc 빌드 스크립트를 고도화하여 신국판, B5, A4 PDF 및 Word DOCX, 네이버 블로그 HTML이 단 한 번의 실행으로 오차 없이 동시 제본되도록 조판 환경을 안정화한다 [\[1, 2\]](#sources).

## **Phase 4: 수익화 플랫폼 연동 및 상용 패키징**

POD 플랫폼(부크크, 교보문고 등) 출판 등록에 필요한 머리말, 전체 목차, 표지 이미지, 저자 소개, 메타데이터를 원클릭으로 압축 내보내기(Export)하는 모듈을 구현한다 [\[1, 2\]](#sources). 네이버 블로그 HTML 내 해시태그 20개 자동 생성 및 웹 이미지 자동 업로드 연동 테스트를 완료하고, 타 분야 확장용 SaaS 패키징 작업을 최종 마감한다 [\[1, 2\]](#sources).

| 개발 추진 단계 | 핵심 구축 목표 | 상세 개발 과제 및 모듈 구현 | 검증 및 완료 기준 (Checkpoint) |
| :---- | :---- | :---- | :---- |
| **Phase 1** | UI/UX & 브랜드 구축 | \- "참참살이 영농 AI 출판도우미" 타이틀 확정- Emerald Agri / Golden Wheat 테마 적용- 4분할 대시보드 및 프로그레스 위젯 설계 [\[1, 2\]](#sources) | \- Streamlit/Electron UI 디자인 표준 통과- 스테이지 카드 동작 및 레이아웃 검증 [\[1, 2\]](#sources) |
| **Phase 2** | GraphRAG & QA 강화 | \- `C:\SMC_GRAPHRAG` 하이브리드 엔진 연동- 엔티티 트리플 기반 출처 바인딩- `verify_citations.py` 원스톱 자동화 [\[1, 2\]](#sources) | \- 인용 감사 정확도 100% 달성- 환각 명제 0건 및 트리플 매핑 확인 [\[1, 2\]](#sources) |
| **Phase 3** | 시각화 & 조판 정밀화 | \- A/B/C/D 4유형 시각화 1:1 매칭 강화- Zero-Text 규율 및 고해상도 차트 생성- Quarto/Pandoc 싱글 소스 조판 스크립트 완성 [\[1, 2\]](#sources) | \- 단원당 10+ 시각화 자동 결합 완료- 신국판/B5/A4/DOCX/HTML 동시 도출 [\[1, 2\]](#sources) |
| **Phase 4** | 수익화 & 패키징 | \- POD 자동 출판용 메타데이터 내보내기- 네이버 블로그 HTML 20개 태그 파싱- SaaS 라이선스 패키징 및 API 정산 연결 [\[1, 2\]](#sources) | \- POD 플랫폼 원클릭 등록 package 도출- 블로그 마케팅 포스팅 자동화 검증 [\[1, 2\]](#sources) |

# **6\. 결론 및 향후 발전 전망**

"참참살이 영농 AI 출판도우미"는 한정된 자원을 가진 개인이 AI 기술과 지식그래프, 싱글 소스 출판 기술을 레버리지하여 대형 출판사 수준의 도서를 효율적으로 발행할 수 있도록 설계된 전문 출판 솔루션이다 [\[1, 2\]](#sources).

본 플랫폼은 기존에 구축된 6단계 자동화 파이프라인과 31개 핵심 키워드, 17개 이상 분야의 지식 자산을 완전 통합하고 [\[1, 2, 3\]](#sources), 로컬 GraphRAG 기반의 정밀 검색과 출처 감사를 결합함으로써 학술적 신뢰성을 확보한다 [\[1, 2, 5\]](#sources). 또한 프리미엄 visual identity와 엔터프라이즈급 대시보드 UX를 도입하여 시스템 운영 전반에서 전문성을 발휘하도록 보완되었다 [\[1, 2\]](#sources).

수익성 관점에서도 POD 종이책 출판, B2B/B2G 기관 용역, 네이버 블로그 트래픽 마케팅, SaaS 라이선싱으로 이어지는 4단계 비즈니스 모델을 구체화함으로써 지속 가능한 수익 창출이 가능하다 [\[1, 2\]](#sources). 본 보완 계획서에 제시된 Phase 1\~4 실행 로드맵을 단계별로 이행함으로써, 개인이 주도하는 전문 출판의 새로운 패러다임을 확립하고 스마트 농업 지식의 보급과 상업적 성공을 동시에 달성할 것이다 [\[1, 2\]](#sources).

# **Sources** {#sources}

1. [https\://drive.google.com/open?id=1KRXyitYmCX7PiuAt5\_0hc4n86NSIEpJk](https://drive.google.com/open?id=1KRXyitYmCX7PiuAt5_0hc4n86NSIEpJk)  
2. [https\://drive.google.com/open?id=1UVzctDQIv3rX\_RsJ8ccTqlOyFMzvtncV](https://drive.google.com/open?id=1UVzctDQIv3rX_RsJ8ccTqlOyFMzvtncV)  
3. [제목 없는 문서](https://drive.google.com/open?id=1tKWp1YbjPC6MFBSIoIOMpZguU-8NXm-ew1lm69WSR_4)  
4. [20260318\_참살이영농AI도우미앱디자인안.pptx](https://drive.google.com/open?id=1k98yaCnMhZKi6k8oYfmAfv-FzrviOGJf)  
5. [What Is GraphRAG? Architecture, GraphRAG vs RAG, Use Cases \- Atlan](https://atlan.com/know/what-is-graphrag/)  
6. [What is GraphRAG? \- IBM](https://www.ibm.com/think/topics/graphrag)  
7. [How to Implement GraphRAG: A Step-by-Step Guide \- PromptQL](https://promptql.io/blog/implement-graphrag)  
8. [From RAG to GraphRAG: Knowledge Graphs, Ontologies and Smarter AI \- Medium](https://medium.com/gooddata-developers/from-rag-to-graphrag-knowledge-graphs-ontologies-and-smarter-ai-01854d9fe7c3)  
9. [Typst book support? · quarto-dev · Discussion \#6979 \- GitHub](https://github.com/orgs/quarto-dev/discussions/6979)  
10. [참살이 영농 AI 도우미 프롬프트](https://drive.google.com/open?id=1moAU7BMM0YGEVK7-UtbcKXUFinuDnsTLJKcL3rOBliM)  
11. [제목 없는 문서](https://drive.google.com/open?id=1jWB7nwZ7RgvHNkF53pOxTC9yVixUlF3j8tapJjfIJ6g)

