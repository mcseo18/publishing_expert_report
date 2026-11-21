# 7단계 서브에이전트 파이프라인 상세 체크리스트 및 품질 게이트

| 단계 | 서브에이전트 | 담당 엔진 / 스크립트 | 주요 산출물 | 필수 통과 게이트 |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `kg-scout` | `scripts/smc_kg_bridge.py` | `kg_gap_report.json` | 기존 `C:\SMC_GRAPHRAG` 재활용률·결손 목록 기록 |
| 2 | `web-scout` | `scripts/fetch_project_sources.py` (`fetch_clean.py` + `fetch_scholar.py`) | `E:\...\projects\<slug>\collected\{01..04}\`, `collection_manifest.json`, `INDEX.md`, `evidence\<slug>_evidence.json` | 4계층 분리 저장 완료, `robots.txt` 준수, PII 마스킹, 중복 제거 완료 |
| 3 | `kg-builder` | `scripts/build_platform_kg.py` (2단계 매니페스트 `source_ids` 연동) | `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json`, `reports/kg_ingest_report.json` | 분리 폴더 확보 자료만 정확히 증분 이관, 기존 `graph.json` 무훼손 확인 |
| 4 | `curriculum-architect` | `scripts/subagent_orchestrator.py` / `generate_blueprints.py` | `master_outline.yaml`, `chNN.yaml` | 목표 페이지·단원별 학습목표·근거 패킷 배정 완료 |
| 5 | `domain-drafter` | `draft_chapter.py`, `expand_to_500p.py`, `add_myths_and_link_quizzes.py` | `ch01.mdx`~`chNN.mdx` | 모든 사실 `[SRC-NN]`, 장당 오해와 진실 ≥3건, 문제↔풀이 1:1 연결 |
| 6 | `citation-auditor` | `clean_manuscripts.py`, `verify_citations.py` | `audit_latest.json`, `math_cleanup_report.json` | 치명오류 0건, 잔여 `$`/LaTeX 0건, `NEED_EVIDENCE` 0건 |
| 7 | `visual-publisher` | `generate_nano_banana_figures.py`, `figure_registry.py`, `build_outputs.py`, `bind_master_book.py`, `qa_web_outputs.py` | 신국판·B5·A4 PDF, DOCX, 네이버 블로그 HTML, `visuals_text_guide.md` | 도해 줄글 텍스트 설명, 표 수식 깨짐 0건, 소단원별 해시태그 20개, Playwright QA PASS |

## 네이버 블로그 게재 및 시각화 핵심 규격
1. **시각화 설명**: 별도 표로 정리하지 않고 이미지 바로 아래 `[그림 N-K] 제목` + 줄글 문단으로 상세 해설을 작성한다.
2. **표 내부 수식 보호**: `<table>` 내부 및 네이버 블로그 클립보드 복사 시 `<sub>`/`<sup>`/`.m-frac`/`.m-rxn`을 네이티브 유니코드(`CO₂`, `NH₄⁺`, `Ca²⁺`, `¹³C`, `N₀`) 및 안전 평문(`k_fast`, `θ_threshold`, `dN_L / dt`, `e^(−kt)`)으로 변환하고 `<div class="table-wrap">`을 언랩한다.
3. **해시태그**: 참고문헌을 제외한 모든 소단원 말미에 중복 없는 정확히 20개의 관련 해시태그를 텍스트로 삽입한다.
4. **문제↔풀이 연결**: 상단 바로가기 링크(`문제 K ↔ 풀이 K`)와 각 문제 직하단 연결 풀이 박스(`▶ 문제 K 정답 및 상세 풀이`)를 제공한다.
