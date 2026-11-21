---
trigger: always_on
description: 수집 자료 E:\ 저장 및 기존 C:\SMC_GRAPHRAG 지식그래프 통합·증분 적재 상시 규칙
---

# 저장소 라우팅 및 지식그래프 통합 규칙

1. **수집 자료 물리 저장소 (`E:\SMC_Report_Platform_Data`)**:
   - 웹 원문(`raw/web`), 다운로드 문서(`raw/docs`), 정제 마크다운·표(`parsed`), 근거 패킷(`evidence`), 중복 제거 레지스트리(`index/sources.jsonl`)는 반드시 `E:\SMC_Report_Platform_Data`에 저장합니다.
   - 워크스페이스의 `data/{raw,parsed,evidence,index}`는 `E:\SMC_Report_Platform_Data`의 동일 하위 폴더에 연결된 NTFS 디렉터리 정션입니다.
2. **지식그래프 통합 저장소 (`C:\SMC_GRAPHRAG`)**:
   - LightRAG 영구 저장소는 `C:\SMC_GRAPHRAG\lightrag_store` (`data/kg_store` 정션)에 배치합니다.
   - 기존 구축된 `C:\SMC_GRAPHRAG\output\graph_*.json` 및 Neo4j 데이터를 `scripts/smc_kg_bridge.py`로 함께 조회하여 재활용합니다.
   - 기존 `C:\SMC_GRAPHRAG\output\graph.json`을 절대 덮어쓰지 않으며, 증분 그래프 갱신 전 반드시 `C:\SMC_GRAPHRAG\output\backup\<YYYYMMDD_HHMMSS>\` 백업을 수행합니다.
3. **Graph-First 선조회**:
   - 새로운 보고서·단원 수집을 시작하기 전에 반드시 `scripts/smc_kg_bridge.py gap-check` 또는 `lightrag` MCP로 기존 지식그래프를 먼저 검색하고, 결손 항목만 웹 수집합니다.
