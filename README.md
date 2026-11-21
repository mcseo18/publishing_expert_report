# 전문 분야 교재 · 보고서 제작 통합 플랫폼 (`publishing_expert_report`)

> **Antigravity Ultra · Claude Code Pro · OpenAI API · 로컬 Ollama Gemma 4 (`gemma4:26b` / `gemma4:latest`) · `fal.ai` / 나노바나나 · 로컬 지식그래프(`C:\SMC_GRAPHRAG`)**를 결합한 근거 기반(Evidence-Based) 전문 대학교재·기술보고서 자동화 제작 플랫폼입니다.

---

## 1. 핵심 특징

- **단일 HTML 통합 대시보드 (`http://127.0.0.1:8501`)**: 여러 포트·주소를 오가지 않고 단일 화면 상단의 **6단계 진행상황 진도 바**와 5개 통합 탭으로 전체 제작 과정을 직관적으로 제어합니다.
- **6단계 표준 교재 제작 파이프라인 + 체크포인트 자동 이어하기**:
  - 작업 중 중단·오류·서버 재시작이 발생해도 `state.json`(원자적 저장)과 단원·시각화별 체크포인트를 보존해 중단 지점부터 바로 이어서 실행합니다.
- **Graph-First 선조회 & 증분 지식그래프 (`C:\SMC_GRAPHRAG`)**:
  - 웹 수집 전 기존 로컬 RAG 지식그래프를 선조회해 중복 수집을 방지하며, 기존 `graph.json`은 절대 덮어쓰지 않고 `graph_platform_incremental.json`에 증분(Append-Only) 통합합니다.
- **법적 컴플라이언스 & 출처 무결성 게이트**:
  - `robots.txt` 점검, PII(개인정보) 자동 마스킹, 웹 프롬프트 인젝션 방어, 모든 사실·수치에 `[SRC-NN]` 인용키 강제, 원문 15어절 이상 무단 복제 자동 차단(`scripts/verify_citations.py`).

---

## 2. 6단계 교재 제작 워크플로

| 단계 | 에이전트 / 엔진 | 핵심 수행 내용 및 산출물 |
| :---: | :--- | :--- |
| **1단계** | `outline-architect`<br>초기 RAG + **OpenAI API** / Gemma 4 | 주제를 입력하면 초기 검색 후 **교재 개요 · 부/단원 목차 · 단원별 요약 · 핵심 영역별 키워드**를 제시 → `WAITING_REVIEW` 상태에서 사용자의 **AI 재요청·직접 수정**을 거쳐 최종 확정 |
| **2단계** | `web-scout`<br>eco-browser · OpenAlex/Europe PMC/Crossref 자동 폴백 | 확정 키워드로 국내외 공식기관·학회지·SCI·웹사이트 자료를 4계층 분리 폴더(`E:\SMC_Report_Platform_Data\projects\<id>\collected\`)에 저장 → **`02_collection_report.md`** 생성 |
| **3단계** | `kg-builder`<br>로컬 Gemma 4 + `C:\SMC_GRAPHRAG` | 수집 자료에서 엔티티·관계를 추출해 증분 지식그래프 구축(기존 `graph.json` 무훼손) → **`03_kg_report.md`** 생성 |
| **4단계** | `domain-drafter` · `citation-auditor`<br>로컬 Gemma 4 + Claude Code(선택) | `[SRC-NN]` 인용, **오해와 진실(≥3선)**, **1:1 문제↔풀이 연결**, 수식/첨자 정제 및 인용 무결성 감사 (단원별 체크포인트 저장) |
| **5단계** | `visual-artist`<br>**`fal.ai` API(체크 선택)** · 나노바나나 · Vector SVG | **단원당 10개 이상**의 실사진·과학 인포그래픽 및 정량 벡터 차트 생성 + 표 없는 자연스러운 학술 **줄글 해설(`visuals_text_guide.md`)** 작성 (이미지별 체크포인트 저장) |
| **6단계** | `book-publisher`<br>표지·목차 스튜디오 + 다중 포맷 제본 | **표지 · 머리말 · 전체 목차(HTML/PDF/DOCX/MD)** + 신국판·B5·A4 PDF · Word DOCX · 네이버 블로그 HTML(표 내부 수식 무손실 · 소단원별 해시태그 20개) 출판 → **`06_final_book_report.md`** 생성 |

---

## 3. 통합 대시보드 5개 탭 구성 (`http://127.0.0.1:8501`)

1. **`📋 6단계 교재 제작 워크플로`**: 상단 진도 바 연동 1~6단계 상세 화면, OpenAI 목차 재요청/직접 편집기, 2·3·6단계 마크다운 보고서 뷰어, 단원 원고 열람, 5단계 `fal.ai` ON/OFF 체크박스 및 시각화 갤러리, 실시간 실행 로그.
2. **`🎨 표지 · 목차 페이지 제작`**: 도서명·부제·저자·출판처·머리말·판형(신국판/B5/A4)·컬러 테마(4종)·AI 표지 일러스트 선택 후 `HTML · PDF · DOCX · MD` 즉시 생성 및 실시간 미리보기(`<iframe>`).
3. **`📚 자료실 · 학술/웹 수집`**: 프로젝트 수집 자료 4계층 조회, OpenAlex 장애 시 Europe PMC·Crossref 자동 폴백 학술 검색, URL 및 Google Scholar/KCI BibTeX 직접 적재.
4. **`🔎 데이터 탐색 · API · NotebookLM`**:
   - 로컬 통합 기상 DB (`weather_daily_kr.db`, 690만 행 · 876지점 ASOS/AWS/농업기상) 탐색
   - 기상청 API허브(ASOS), OpenWeatherMap, 공공데이터포털(`apis.data.go.kr`), 통계청 KOSIS OpenAPI 연동 및 RAG 적재
   - **Google NotebookLM** 노트북 목록 조회 · 소스 원문 추출 · 질의 및 프로젝트+RAG 직접 가져오기
   - 다채널 심층 자료 조사 대화 창 & 추가 프롬프트 분석
5. **`⚙️ AI 엔진 · API 키 · 프로젝트 관리`**:
   - **7종 통합 API 키 금고** (`OPENAI_API_KEY`, `FAL_KEY`, `GEMINI_API_KEY`, `KMA_HUB_KEY`, `OPENWEATHER_API_KEY`, `DATA_GO_KR_API_KEY`, `KOSIS_API_KEY` — Git 외부 `E:\SMC_Report_Platform_Data\index\local_api_keys.json`에 보관, UI에는 마스킹 상태만 노출)
   - Ollama(`gemma4:26b` / `gemma4:latest`) · Claude Code 정밀 검수 토글 · 프로젝트 삭제/초기화(아카이브 보호)

---

## 4. 현재 제작 진행 현황

### 📘 활성 프로젝트: 《디지털 밀 재배 (Digital Wheat Cultivation)》
- **목차 구성**: **16부 16장 · 목표 531p** ([master_outline.yaml](projects/digital_wheat_cultivation_20261121_220903/blueprints/master_outline.yaml))
  - 제1장 기초 생물학 ~ 제5장 분얼·분화기 ~ **제6장 밀의 생육시기별 양분 분배와 디지털 생육모형(신설)** ~ 제14장 디지털 트윈·AI ~ 제16장 미래 전망
- **근거 자료**: 국내외 공식기관·작물모형 기관(DSSAT·APSIM·FAO AquaCrop·WOFOST)·SCI·국내 학회지 **총 53건** 수집 완료 ([02_collection_report.md](projects/digital_wheat_cultivation_20261121_220903/reports/02_collection_report.md))
- **지식그래프**: 증분 그래프 **2,802 노드 · 1,797 관계** 구축 완료 ([03_kg_report.md](projects/digital_wheat_cultivation_20261121_220903/reports/03_kg_report.md))
- **집필 원고**: **`ch01.mdx` ~ `ch16.mdx` 16개 단원 전수 집필 완료** 및 인용·원문복사율 감사 **`PASS` (치명오류 0건)**
- **표지 · 목차 페이지**: B5 판형 6쪽 표지·머리말·16장 전체 목차 생성 완료 ([cover_and_toc.md](projects/digital_wheat_cultivation_20261121_220903/exports/front_matter/cover_and_toc.md))

### 📗 기준 완성본: 《토양 유기물학》 (500p)
- 5부 16장 전 단원 집필·증보·오해와 진실·1:1 문제풀이·20종 도해·신국판/B5/A4 합본 PDF & Word DOCX 완성 ([projects/soil_organic_matter/](projects/soil_organic_matter/))

---

## 5. 디렉터리 구조

```text
report_publishing_platform/
├── AGENTS.md / GEMINI.md / CLAUDE.md    # 3계층 AI 협업 헌장 및 보안·저장소 규약
├── .agents/ & .claude/                  # 서브에이전트 정의, 품질 훅, textbook-publishing-factory 스킬
├── dashboard/
│   ├── agents_app.py                    # 단일 통합 백엔드 서버 (FastAPI, Port 8501)
│   ├── app.py                           # 레거시 큐레이션 서버 (Port 8500, 테스트 호환)
│   └── static/unified.html              # 단일 HTML 6단계 통합 대시보드 UI
├── scripts/
│   ├── subagent_orchestrator.py         # 6단계 오케스트레이터 · OpenAI 검토 게이트 · 체크포인트 이어하기
│   ├── build_cover_toc.py               # 표지 · 머리말 · 전체 목차(HTML/PDF/DOCX/MD) 제작 모듈
│   ├── visual_studio.py                 # 단원당 10종+ 시각화 (fal.ai · 나노바나나 · SVG · 줄글 해설)
│   ├── fetch_project_sources.py         # 국내외 4계층 분리 수집기
│   ├── fetch_scholar.py                 # OpenAlex · Europe PMC · Crossref 자동 폴백 학술 검색기
│   ├── data_connectors.py               # 로컬 기상 DB · KMA · OWM · 공공포털 · KOSIS · 7종 API 키 금고
│   ├── notebooklm_connector.py          # Google NotebookLM 노트북/소스 가져오기 연동
│   ├── deep_research_chat.py            # 다채널 심층 자료 조사 대화 엔진
│   ├── smc_kg_bridge.py                 # C:\SMC_GRAPHRAG Graph-First 선조회 & 증분 브리지
│   ├── build_platform_kg.py             # 로컬 Gemma 4 엔티티·관계 추출 및 증분 KG 구축
│   ├── build_outputs.py / bind_master_book.py  # PDF · DOCX · 네이버 블로그 HTML 출판 제본
│   └── verify_citations.py              # [SRC-NN] 인용 무결성 · 15어절 원문 복사율 감사기
├── projects/                            # 프로젝트별 청사진 · 단원 원고 · 보고서 · 표지/목차
├── tests/                               # 단위·통합 테스트 (pytest 10/10 PASS)
└── scripts/launch_dashboards.ps1        # 원클릭 실행/종료 런처 (.bat 연동)
```

---

## 6. 빠른 시작 (Windows)

```powershell
# 1. 가상환경 생성 및 패키지 설치
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt

# 2. 환경 변수 템플릿 복사 (.env는 Git 제외)
copy .env.example .env

# 3. 단일 통합 대시보드 실행 (http://127.0.0.1:8501)
.\scripts\launch_dashboards.ps1 -Target all
# 또는 배치 파일 실행: .\00_전체_플랫폼_실행.bat

# 4. 품질 및 테스트 검증
.\.venv\Scripts\python.exe -m pytest tests/test_phase1.py tests/test_phase2.py -v
.\.venv\Scripts\python.exe scripts\verify_citations.py projects
```

---

## 7. 보안 및 저장소 분리 원칙
- 대용량 원문·PDF·근거 패킷·API 키 금고는 Git 저장소 외부(`E:\SMC_Report_Platform_Data\`)에 분리 저장되며 `.gitignore`로 엄격히 차단됩니다.
- `.env` 및 실제 API 키 파일은 절대 커밋되지 않습니다.
