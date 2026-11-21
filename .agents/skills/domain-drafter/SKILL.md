---
name: domain-drafter
description: 단원 청사진(content/blueprints/chNN.yaml)과 검증 근거 패킷(E:\SMC_Report_Platform_Data\evidence\chNN_evidence.json)을 로컬 Ollama Gemma 4 26B 워커로 전달해 [SRC-NN] 인용이 포함된 전문 교재 단원 초안(content/chapters/chNN.mdx)을 생성하는 스킬.
---

# domain-drafter 스킬 사용법

1. 사전 확인:
   - 단원 청사진: `content/blueprints/chNN.yaml`
   - 근거 패킷: `E:\SMC_Report_Platform_Data\evidence\chNN_evidence.json` (`data/evidence/chNN_evidence.json`)
2. 로컬 Gemma 4 26B 초안 생성 실행:
   ```powershell
   .\.venv\Scripts\python.exe scripts\draft_chapter.py `
     --blueprint content\blueprints\ch01.yaml `
     --evidence data\evidence\ch01_evidence.json `
     --out content\chapters\ch01.mdx
   ```
3. 생성 완료 후 즉시 인용·저작권 검증 실행:
   ```powershell
   .\.venv\Scripts\python.exe scripts\verify_citations.py content\chapters\ch01.mdx --out reports\audit_ch01.json
   ```
4. `FAIL` 또는 `UNCITED_NUMERIC_CLAIM` 경고 발생 시 원고의 인용키 및 수치 표현을 근거 패킷에 맞춰 보정한 뒤 재검증합니다.
