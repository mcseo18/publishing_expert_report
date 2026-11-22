# GEMINI.md — Antigravity Ultra 프로젝트 지침

1. 작업 전 반드시 루트의 `AGENTS.md`와 `.agents/rules/`의 상시 규칙을 준수하십시오.
2. 대량 원문 요약, 정형 JSON 추출, 초안 확장은 로컬 Ollama (`scripts/local_gemma.py`, `gemma4:26b`, `http://127.0.0.1:11434`)로 오프로드하고, Antigravity는 구조 설계·청사진·서브에이전트 지휘·대시보드·최종 검수에 집중하십시오.
3. 모든 수집 파일은 `E:\SMC_Report_Platform_Data` (`data/{raw,parsed,evidence,index}` 정션)에 저장하고, 지식그래프는 `C:\SMC_GRAPHRAG` (`data/kg_store` 정션 및 `scripts/smc_kg_bridge.py`)에 증분 통합하십시오.
4. 새 자료 수집 전에는 반드시 `C:\SMC_GRAPHRAG` 기존 지식그래프와 LightRAG를 선조회(Graph-First)하여 중복 수집을 방지하십시오.
5. 기존 `C:\SMC_GRAPHRAG\output\graph.json` 등 기존 그래프 파일은 절대 덮어쓰지 마십시오.
6. 모든 원고 변경 후 `scripts/verify_citations.py content/chapters/`로 출처 무결성과 원문 복사율을 검증하십시오.
7. 1차 산출물로 **논문·리뷰(`paper`)**를 선택한 경우 반드시 `.agents/rules/academic-paper-review-standard.md`를 적용하여 초록 1개 · 핵심 내용 요약 1개 · 마지막 1회 통합 참고문헌 원칙, 『재료 및 방법』·『결과 및 고찰(학회 투고급 6단계 심층 논리)』 세부 절 구성, 그리고 **국내 학회지 논문 규격 PDF(A4 2단·1단 초록·3선표)** 조판을 강제하십시오.
8. 기본 최종 산출물은 중복을 방지하기 위해 **① 마스터 PDF 1종**과 **② 블로그용 단일 HTML 1종**만 생성하고, DOCX·추가 판형·단원 분할본 등은 필요 시 `scripts/output_converter.py` 변환 모듈로 사후 생성하십시오.
