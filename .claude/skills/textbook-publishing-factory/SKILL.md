---
name: textbook-publishing-factory
description: 주제를 설정하면 ① 초기 검색 + OpenAI API로 목차·요약·영역별 키워드 제시 및 사용자 검토·재요청·확정 → ② eco-browser·학술·기관 자료 분리 수집 및 현황 보고서 → ③ C:\SMC_GRAPHRAG 지식그래프 증분 구축 및 KG 보고서 → ④ 단원별 교재 집필(체크포인트 이어하기)·인용 감사 → ⑤ 단원당 10개+ 시각화(fal.ai API 선택 체크 · 나노바나나 · Vector SVG · 줄글 해설) → ⑥ 다중 판형 PDF·Word DOCX·네이버 블로그 HTML 출판 및 완료 종합 보고서까지 단일 HTML 대시보드(http://127.0.0.1:8501)에서 6단계로 실행하는 표준 제작 스킬.
---

# textbook-publishing-factory — 전문 교재·보고서 6단계 표준 제작 지침 (v2.0)

상세 내용과 동일한 마스터 스킬 문서는 `.agents/skills/textbook-publishing-factory/SKILL.md`와 동기화되어 있습니다.

## 6단계 표준 실행 순서 (단일 대시보드 `http://127.0.0.1:8501`)
1. `stage1_topic_outline`: 초기 RAG/학술 탐색 + OpenAI API(또는 Gemma 4)로 목차·요약·영역별 키워드 제시 → 사용자 검토·재요청·직접 수정 후 확정 (`WAITING_REVIEW` 게이트)
2. `stage2_source_collect`: 문헌·교과서·웹사이트 4계층 분리 폴더 수집 → `02_collection_report.md` 보고서 생성
3. `stage3_kg_build`: `C:\SMC_GRAPHRAG\output\graph_platform_incremental.json` 지식그래프 증분 구축(기존 `graph.json` 무훼손) → `03_kg_report.md` 보고서 생성
4. `stage4_manuscript_draft`: 단원별 교재 집필(`[SRC-NN]`, 오해와 진실, 1:1 문제↔풀이, 단원별 체크포인트) + 수식/인용 감사
5. `stage5_visuals_generate`: 『weed_control』 검증 **`textbook-visual-director`** 표준 적용 — 단원당 10~15종 `A/B/C/D` 4유형 분류(`A` 현장 실사 4:3 · `B` 스튜디오 표본 4:3 · `C` 교재 도해 16:9 5색 팔레트 · `D` 순수 Python `matplotlib` 300 DPI) · 3계층 하이브리드(`fal-ai/nano-banana-pro` `2K` / Google `nano-banana-pro-preview` / `Pillow` 오버레이 보정) · 단원별 `prompts_and_descriptions.md`·`manifest.json`·`qa_grid_chNN.jpg` 이중 저장 + `V-01~V-05` 멀티모달 시각 QA(`--only` 선택 재생성) + 줄글 해설
6. `stage6_publish_report`: PDF · DOCX(`16:9` 155 mm · `4:3` 135 mm) · 오프라인 단일 HTML(`WebP` Base64 Data URI) · 네이버 블로그 HTML(`1600 px` JPG 분리 · 유니코드 수식) 출판 → `06_final_book_report.md` 완료 보고서 생성
