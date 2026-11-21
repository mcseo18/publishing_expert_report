---
name: domain-drafter
description: 로컬 Ollama Gemma 4 26B 워커(scripts/draft_chapter.py)를 호출해 청사진과 근거 패킷 기반으로 [SRC-NN] 인용 포함 전문 교재 단원 초안을 생성하는 스킬.
---

# domain-drafter 스킬

```powershell
.\.venv\Scripts\python.exe scripts\draft_chapter.py --blueprint content\blueprints\ch01.yaml --evidence data\evidence\ch01_evidence.json --out content\chapters\ch01.mdx
.\.venv\Scripts\python.exe scripts\verify_citations.py content\chapters\ch01.mdx --out reports\audit_ch01.json
```
