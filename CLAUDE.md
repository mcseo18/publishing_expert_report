# CLAUDE.md — Claude Code Pro 프로젝트 지침

1. 작업 전 `AGENTS.md`와 `schemas/evidence_packet.schema.json`을 확인하십시오.
2. 웹 수집 전 `lightrag` MCP 또는 `.venv/Scripts/python.exe scripts/smc_kg_bridge.py gap-check`로 `C:\SMC_GRAPHRAG` 기존 지식을 선조회하십시오.
3. 공개 웹은 `ecobrowser` MCP로 최소 토큰 탐색 후 URL/PDF만 확보하고, 본문 추출은 반드시 `scripts/fetch_clean.py` / `scripts/parse_pdf.py`에 위임하십시오.
4. 로그인·학술 DB는 `ego-browser` 전용 TaskSpace만 사용하며 인증/캡차 시 즉시 `task.handOff()`로 사용자에게 넘기십시오.
5. 수집 파일은 `E:\SMC_Report_Platform_Data` (`data/` 정션), 지식그래프는 `C:\SMC_GRAPHRAG` (`data/kg_store` 정션)에 증분 저장하고 기존 `C:\SMC_GRAPHRAG\output\graph.json`을 덮어쓰지 마십시오.
6. 모든 원고는 `[SRC-NN]` 인용키를 포함해야 하며, 작업 종료 시 Stop 훅(`scripts/verify_citations.py`)을 통과해야 합니다.
7. 메인 컨텍스트 보호를 위해 원문 전체를 응답에 붙여넣지 말고 파일 경로와 15줄 이내 요약만 보고하십시오.
