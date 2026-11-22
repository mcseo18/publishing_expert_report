---
name: textbook-publishing-factory
description: 주제를 설정하면 ① 초기 검색 + OpenAI API로 목차·요약·영역별 키워드 제시 및 사용자 검토·재요청·확정 → ② eco-browser·학술·기관 자료 분리 수집 및 현황 보고서 → ③ C:\SMC_GRAPHRAG 지식그래프 증분 구축 및 KG 보고서 → ④ 단원별 교재 집필(체크포인트 이어하기)·인용 감사 → ⑤ 단원당 10개+ 시각화(fal.ai API 선택 체크 · 나노바나나 · Vector SVG · 줄글 해설) → ⑥ 다중 판형 PDF·Word DOCX·네이버 블로그 HTML 출판 및 완료 종합 보고서까지 단일 HTML 대시보드(http://127.0.0.1:8501)에서 6단계로 실행하는 표준 제작 스킬.
---

# textbook-publishing-factory — 전문 교재·보고서 6단계 표준 제작 지침 (v2.0)

## 1. 저장소 및 지식그래프 절대 규약
- **프로젝트별 격리 폴더 구조**:
  - 워크스페이스: `projects/<project_id>/{collected,blueprints,chapters,assets,exports,reports}`
  - E 드라이브 분리 수집 저장소: `E:\SMC_Report_Platform_Data\projects\<project_id>\collected\{01_domestic_agencies,02_domestic_journals,03_international_agencies,04_international_journals}`
  - 공용 물리 저장소: `E:\SMC_Report_Platform_Data\` (`data/{raw,parsed,evidence,index}` 정션)
- **지식그래프 통합 저장소 (`C:\SMC_GRAPHRAG`)**:
  - 기존 `output/graph.json`은 **절대 덮어쓰지 않고** 백업 후 `output/graph_platform_incremental.json` 및 `lightrag_store/`에 증분(append-only) 적재한다.
- **중단 지점 자동 체크포인트 저장 및 이어하기**:
  - `state.json`은 임시 파일 기록 후 원자적 교체(`os.replace`)로 저장하며, 단원 집필(`checkpoint.completed_chapters`)·시각화(`checkpoint.completed_visuals`)·출판(`checkpoint.published_chapters`) 완료 건마다 체크포인트를 갱신한다.
  - 실행 중 중단되거나 서버가 재시작되면 `RUNNING` 상태가 자동으로 `INTERRUPTED`로 전환되어 `[▶ 이어하기]`로 중단 지점부터 재개된다.

## 2. 6단계 표준 교재 제작 파이프라인 (단일 통합 대시보드 `http://127.0.0.1:8501`)

1. **1단계 `stage1_topic_outline` (`outline-architect`): 주제 탐색 · OpenAI 목차/요약/영역별 키워드 제안 & 사용자 검토 확정**
   - 초기 로컬 RAG(`C:\SMC_GRAPHRAG`) 선조회 + 학술 스캔 후 **OpenAI API**(`OPENAI_API_KEY`, 미등록 시 로컬 Ollama Gemma 4 폴백)로 교재 개요, 핵심 영역별 키워드(`domain_keywords`), 부·단원별 요약(`summary_ko`)과 절 구성을 제시한다.
   - `WAITING_REVIEW` 게이트에서 자동 대기하며, 사용자는 **AI 재요청 프롬프트** 또는 **직접 편집기**로 무제한 수정한 뒤 `[✅ 목차·키워드 최종 확정]`을 눌러 2단계로 진입한다.
2. **2단계 `stage2_source_collect` (`web-scout`): 문헌·교과서·교재·웹사이트 수집 & 현황 보고서 생성**
   - 확정된 목차·키워드를 기반으로 `eco-browser` · OpenAlex/Europe PMC/Crossref(자동 폴백) · 국내외 공식기관·대학·교과서 자료를 4계층 분리 폴더에 저장하고 **`reports/02_collection_report.md`** 현황 보고서를 자동 생성한다.
3. **3단계 `stage3_kg_build` (`kg-builder`): 지식그래프 증분 구축 & KG 보고서 생성**
   - 2단계 수집 자료에서 로컬 Gemma 4로 엔티티·관계 트리플을 추출해 `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json`에 증분 적재하고 **`reports/03_kg_report.md`** 보고서를 자동 생성한다.
4. **4단계 `stage4_manuscript_draft` (`domain-drafter`): 교재 단원 집필 · 오해교정 · 인용/수식 감사**
   - 단원별로 `[SRC-NN]` 인용, `오해와 진실`(≥3선), 1:1 문제↔풀이 연결 원고를 집필하고 완료 단원마다 체크포인트를 저장한다.
   - 수식·화학식 유니코드/HTML 정제(`clean_manuscripts.py`) 및 인용·15어절 복사율 전수 감사(`verify_citations.py`)를 수행한다.
5. **5단계 `stage5_visuals_generate` (`visual-artist`): 『weed_control』 검증 4유형(A/B/C/D)·3계층 하이브리드 시각화 제작 & 4게이트 시각 QA**
   - 상세 실행 표준은 **`textbook-visual-director`** 스킬(`.agents/skills/textbook-visual-director/SKILL.md`)을 반드시 따른다.
   - **원고 문맥 기반 기획 & 4유형 분류**: 단원별 실제 원고(`chapters/chNN.mdx`)를 정독해 **단원당 최소 10~15종**(`visuals_per_chapter >= 10`)을 **유형 A(현장 실사, `4:3`, 무문자)** · **유형 B(스튜디오 표본 접사, `4:3`, 스케일바 외 무문자)** · **유형 C(교재 개념·기작 도해, `16:9`, 5색 통일 팔레트 `#3A7D44/#E07A2E/#8B5E3C/#3B82C4/#1D3557`, Two-Track 타이포그래피·물음표 `?` 금지)** · **유형 D(정량 통계·수리 곡선, `16:9`, 100% 순수 Python `matplotlib` `2560×1440` `300 DPI`, 생성형 AI 단독 금지)**로 배정한다.
   - **3계층 하이브리드 생성**: Tier 1(`fal-ai/nano-banana-pro` `2K` PNG 또는 Google Gemini `nano-banana-pro-preview`) · Tier 2(`/edit` 참조 편집 및 `Pillow`/`malgunbd.ttf` 픽셀 정밀 한글 오버레이 보정) · Tier 3(순수 Python `matplotlib`/`RDKit`). 실행 엔진은 `scripts/context_visual_director.py`(문맥 기획·단원별 해설/프롬프트·`manifest.json`·`qa_grid_chNN.jpg` 컨택트 시트 자동 생성 및 `--only` 선택 재생성 지원)와 `scripts/visual_studio.py`를 사용한다.
   - **이중 분리 저장 & 멀티모달 시각 QA (`V-01`~`V-05`)**: 단원별 폴더(`assets/by_chapter/<chNN>/` 및 `E:\SMC_Report_Platform_Data\projects\<pid>\visuals\by_chapter\<chNN>\`)에 이미지 PNG·`prompts_and_descriptions.md`/`.json`·개별 `_prompt.txt`·`manifest.json`·`qa_grid_<chNN>.jpg`를 동시 보관하고, `read_file`로 5대 게이트(`V-01` 해부/도메인 · `V-02` 타이포그래피 · `V-03` 수치 일치 · `V-04` 현장/안전/PPE · `V-05` 팔레트/해상도)를 검증한다.
   - 각 시각화의 설명은 **표 형식을 쓰지 않고** 이미지 직하단 학술 **줄글 텍스트**(`assets/visuals_text_guide.md`)로 작성하며, 이미지 1건 완료마다 체크포인트를 저장한다.
6. **6단계 `stage6_publish_report` (`book-publisher`): 최종 멀티포맷 출판 & 완료 종합 보고서 생성**
   - 신국판·B5·A4 PDF, Word DOCX(`16:9` 155 mm · `4:3` 135 mm 중앙 정렬), 오프라인 단일 HTML(`RGB` 변환 WebP Base64 Data URI, 외부 의존 0건), 네이버 블로그 HTML(인라인 스타일 전용 · 표 내부 수식 유니코드 무손실 · 번호순 `1600 px` JPG 분리 · 소단원별 해시태그 20개)을 생성해 `E:\SMC_Report_Platform_Data\projects\<project_id>\exports\`에 미러링하고, **`reports/06_final_book_report.md`** 완료 종합 보고서를 생성한다.

## 3. 단일 HTML 통합 대시보드 실행
- 모든 기능(상단 6단계 진도 바 · 1~6단계 워크플로 · 자료실/학술검색 · 690만건 기상 DB/KMA/OpenWeatherMap/공공포털/KOSIS/NotebookLM/심층조사 대화 · 7종 API 키 금고 · 프로젝트 관리)은 **단일 주소 `http://127.0.0.1:8501`**에서 URL 이동 없이 동작한다.
  ```powershell
  .\scripts\launch_dashboards.ps1 -Target all
  ```
