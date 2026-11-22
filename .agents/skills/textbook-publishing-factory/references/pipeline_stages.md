# 7단계 서브에이전트 파이프라인 상세 체크리스트 및 품질 게이트

| 단계 | 서브에이전트 | 담당 엔진 / 스크립트 | 주요 산출물 | 필수 통과 게이트 |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `kg-scout` | `scripts/smc_kg_bridge.py` | `kg_gap_report.json` | 기존 `C:\SMC_GRAPHRAG` 재활용률·결손 목록 기록 |
| 2 | `web-scout` | `scripts/fetch_project_sources.py` (`fetch_clean.py` + `fetch_scholar.py`) | `E:\...\projects\<slug>\collected\{01..04}\`, `collection_manifest.json`, `INDEX.md`, `evidence\<slug>_evidence.json` | 4계층 분리 저장 완료, `robots.txt` 준수, PII 마스킹, 중복 제거 완료 |
| 3 | `kg-builder` | `scripts/build_platform_kg.py` (2단계 매니페스트 `source_ids` 연동) | `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json`, `reports/kg_ingest_report.json` | 분리 폴더 확보 자료만 정확히 증분 이관, 기존 `graph.json` 무훼손 확인 |
| 4 | `curriculum-architect` | `scripts/subagent_orchestrator.py` / `generate_blueprints.py` | `master_outline.yaml`, `chNN.yaml` | 목표 페이지·단원별 학습목표·근거 패킷 배정 완료 |
| 5 | `domain-drafter` | `draft_chapter.py`, `expand_to_500p.py`, `add_myths_and_link_quizzes.py` | `ch01.mdx`~`chNN.mdx` | 모든 사실 `[SRC-NN]`, 장당 오해와 진실 ≥3건, 문제↔풀이 1:1 연결 |
| 6 | `citation-auditor` | `clean_manuscripts.py`, `verify_citations.py` | `audit_latest.json`, `math_cleanup_report.json` | 치명오류 0건, 잔여 `$`/LaTeX 0건, `NEED_EVIDENCE` 0건 |
| 7 | `visual-publisher` | `context_visual_director.py`, `visual_studio.py`, `figure_registry.py`, `build_outputs.py`, `bind_master_book.py`, `qa_web_outputs.py` | 단원별 `by_chapter/<chNN>/` (`PNG`, `prompts_and_descriptions.md/.json`, `manifest.json`, `qa_grid_<chNN>.jpg`), 신국판·B5·A4 PDF, DOCX, 단일 HTML, 네이버 블로그 HTML, `visuals_text_guide.md` | A/B/C/D 4유형 분류, V-01~V-05 멀티모달 시각 QA PASS, 도해 줄글 텍스트 설명, 표 수식 깨짐 0건, 소단원별 해시태그 20개, Playwright QA PASS |

## 『weed_control』 검증 시각화 4유형·5게이트 표준 (`textbook-visual-director` 연계)
1. **4유형 분류 (`A/B/C/D`) 및 화면비**:
   - **유형 A (현장 실사, `4:3`, `2K` PNG)**: 완전 무문자, 한국형 현장 경관, PPE·뒷모습 초상권 준수.
   - **유형 B (스튜디오 접사·표본, `4:3`, `2K` PNG)**: 순백 배경(`#FFFFFF`), 단순 눈금자(`10 mm`/`10 cm` 또는 무문자 스케일바) 외 문자 금지.
   - **유형 C (교재 도해·인포그래픽, `16:9`, `2K` PNG)**: 표준 5색 팔레트(`#3A7D44`, `#E07A2E`, `#8B5E3C`, `#3B82C4`, `#1D3557`), 물음표(`?`) 금지, Two-Track 타이포그래피(단문 네이티브 한글 또는 무문자 기반 + `Pillow`/`malgunbd.ttf` 오버레이 보정).
   - **유형 D (정량 그래프·수리 곡선, `16:9`, `2560×1440` `300 DPI`)**: **생성형 AI 단독 금지**, 100% 순수 Python `matplotlib`(`Malgun Gothic`, 독립 정규화 요약 카드 축, 하단 `자료:` 출처 명시).
2. **5대 멀티모달 시각 감수 게이트 (`V-01 ~ V-05`)**:
   - 단원별 `qa_grid_<chNN>.jpg` 컨택트 시트와 `manifest.json` 생성 후 `read_file`로 육안 판독 → `V-01` 해부/생육단계, `V-02` 한글 자모/물음표 0건, `V-03` 수치 일치, `V-04` 현장/PPE/상표 배제, `V-05` 색채·해상도·잘림 0건 검증. 불량 건은 `--only <fig_id>` 재생성 또는 `Pillow` 오버레이 보정.
3. **매체별 도판 삽입 규격**:
   - **Word DOCX**: `16:9` 폭 `155 mm`, `4:3` 폭 `135 mm` 중앙 정렬.
   - **단일 HTML**: `RGBA→RGB`, 최대 폭 `1920 px`, `WebP(q=92)` Base64 Data URI 내장(외부 의존 0건).
   - **네이버 블로그 (`SmartEditor ONE`)**: 인라인 스타일 전용(외부 CSS/base64 제거), 번호순 `1600 px` JPG 분리 저장, 45장 초과 시 글 자동 분할.

## 네이버 블로그 게재 및 시각화 핵심 규격
1. **시각화 설명**: 별도 표로 정리하지 않고 이미지 바로 아래 `[그림 N-K] 제목` + 줄글 문단으로 상세 해설을 작성한다.
2. **표 내부 수식 보호**: `<table>` 내부 및 네이버 블로그 클립보드 복사 시 `<sub>`/`<sup>`/`.m-frac`/`.m-rxn`을 네이티브 유니코드(`CO₂`, `NH₄⁺`, `Ca²⁺`, `¹³C`, `N₀`) 및 안전 평문(`k_fast`, `θ_threshold`, `dN_L / dt`, `e^(−kt)`)으로 변환하고 `<div class="table-wrap">`을 언랩한다.
3. **해시태그**: 참고문헌을 제외한 모든 소단원 말미에 중복 없는 정확히 20개의 관련 해시태그를 텍스트로 삽입한다.
4. **문제↔풀이 연결**: 상단 바로가기 링크(`문제 K ↔ 풀이 K`)와 각 문제 직하단 연결 풀이 박스(`▶ 문제 K 정답 및 상세 풀이`)를 제공한다.
