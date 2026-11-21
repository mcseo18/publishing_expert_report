"""단원 청사진(YAML) + 근거 패킷(JSON) 기반 로컬 Gemma 4 단원 초안 생성기 (domain-drafter 워커).

특징 (구축 가이드 프롬프트 4B 반영):
- 절(Section) 단위로 로컬 Ollama(gemma4:26b 또는 지정 모델)를 호출해 장문 전문 교재 초안을 안정적으로 생성
- 매 사실·수치 뒤에 [SRC-NN] 또는 [SRC-NN, p.XX] 인용 강제
- 근거 부족 시 임의 창작 금지 -> <!-- NEED_EVIDENCE: ... --> 표시
- 멀티턴 사고 블록(<|channel>thought) 자동 제거
- 단원 말미에 핵심 용어집 표, 이해도 점검 연습문제 3문항+해설, 정식 참고문헌 자동 결합
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from config import PlatformConfig, get_config
from local_gemma import LocalGemmaClient


def _build_evidence_digest(packet: dict[str, Any], allowed_sids: list[str] | None = None, max_chars: int = 18000) -> str:
    """근거 패킷을 로컬 LLM 컨텍스트에 최적화된 출처별 요약 패킷으로 직렬화한다."""
    sources = packet.get("sources", [])
    if allowed_sids:
        allowed_set = set(allowed_sids)
        filtered = [s for s in sources if s.get("source_id") in allowed_set]
        if filtered:
            sources = filtered

    parts: list[str] = []
    used = 0
    for src in sources:
        sid = src.get("source_id", "SRC-00")
        block_lines = [
            f"=== [{sid}] {src.get('title', '')} ===",
            f"- 유형: {src.get('source_type', 'unknown')} | 출처: {src.get('url', '')} | 범위: {src.get('page_or_section', '')}",
        ]
        facts = src.get("extracted_facts", [])
        if facts:
            block_lines.append("- 추출된 핵심 사실·수치:")
            for f in facts[:25]:
                claim = f.get("claim", "")
                psec = f.get("page_or_section", "")
                block_lines.append(f"  * {claim} ({psec})")
        tables = src.get("tables", [])
        if tables:
            block_lines.append(f"- 포함 표({len(tables)}개):")
            for t in tables[:3]:
                headers = " | ".join(t.get("headers", []))
                sample_rows = "; ".join(" | ".join(r) for r in t.get("rows", [])[:4])
                block_lines.append(f"  * {t.get('table_id')}: {t.get('caption')} [{headers}] -> {sample_rows}")
        chunks = src.get("chunks", [])
        if chunks:
            block_lines.append("- 대표 근거 발췌:")
            for ch in chunks[:8]:
                psec = ch.get("page_or_section", "")
                txt = ch.get("text", "").replace("\n", " ")[:360]
                block_lines.append(f"  * ({psec}) {txt}")

        block = "\n".join(block_lines) + "\n"
        if used + len(block) > max_chars:
            remaining = max(max_chars - used, 600)
            parts.append(block[:remaining] + "\n...(truncated)\n")
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


def _format_references(packet: dict[str, Any]) -> str:
    lines = ["## 참고문헌 및 근거 출처 목록", "", "| 출처 ID | 유형 | 제목 | URL / 경로 | 접근일 | robots/라이선스 |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
    for src in packet.get("sources", []):
        sid = src.get("source_id", "")
        stype = src.get("source_type", "")
        title = str(src.get("title", "")).replace("|", "\\|")
        url = str(src.get("url", "")).replace("|", "\\|")
        acc = str(src.get("accessed_at", ""))[:10]
        lic = str(src.get("license_note", "")).replace("|", "\\|")
        lines.append(f"| `{sid}` | {stype} | {title} | {url} | {acc} | {lic} |")
    return "\n".join(lines)


def draft_chapter(
    blueprint_path: Path,
    evidence_path: Path,
    out_path: Path,
    model: str | None = None,
    think: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    bp = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
    packet = json.loads(evidence_path.read_text(encoding="utf-8"))
    client = LocalGemmaClient(cfg)

    target_model = model or cfg.ollama_llm_model
    chapter_title = bp.get("title", "제1장")
    chapter_num = bp.get("chapter_number", 1)
    audience = bp.get("target_audience", "대학 전공 심화 및 농업·토양 연구자")
    objectives = bp.get("learning_objectives", [])
    sections = bp.get("sections", [])

    system_prompt = (
        "당신은 토양학 및 토양 유기물학 분야의 대학 전공 교재 저자입니다. "
        "제공된 단원 청사진과 검증된 근거 패킷의 사실·수치만을 바탕으로 완성도 높은 한국어 전문 교재 원고를 작성하십시오.\n"
        "[절대 준수 규칙]\n"
        "1. 모든 사실적 주장, 수치, 비율, 연도, 분류 기준, 화학·물리·생물학적 메커니즘 문장 끝에는 "
        "반드시 제공된 근거 패킷의 출처 ID를 `[SRC-NN]` 또는 `[SRC-NN, p.XX]` 형식으로 표기하십시오.\n"
        "2. 근거 패킷에 등록되지 않은 출처 ID를 절대 만들지 마십시오.\n"
        "3. 근거가 부족해 수치나 세부 사실을 확인할 수 없는 부분은 임의로 추론·창작하지 말고 "
        "`<!-- NEED_EVIDENCE: 필요한 구체 자료 설명 -->` 주석으로 표시하십시오.\n"
        "4. 출처 원문 문장을 그대로 길게 옮기지 말고(연속 15어절 이상 복사 금지), "
        "`원리 → 메커니즘 → 실무 트레이드오프 → 현장/농업 예시` 순으로 교육적 재구성을 수행하십시오.\n"
        "5. 수치가 포함된 문장은 예외 없이 해당 문장에 `[SRC-NN]` 인용키를 포함하십시오."
    )

    doc_parts: list[str] = [
        "---",
        f'title: "{chapter_title}"',
        f"chapter: {chapter_num}",
        f'target_pages: "{bp.get("target_pages", 38)}"',
        f'audience: "{audience}"',
        f'evidence_packet: "{evidence_path.name}"',
        f'drafted_by_model: "{target_model}"',
        "---",
        "",
        f"# {chapter_title}",
        "",
        "> **학습 목표 (Learning Objectives)**",
    ]
    for idx, obj in enumerate(objectives, start=1):
        doc_parts.append(f"> {idx}. {obj}")
    doc_parts.append("")

    section_timings: list[dict[str, Any]] = []

    # 1. 절(Section)별 본문 집필
    for sec in sections:
        sec_id = sec.get("section_id", "")
        sec_title = sec.get("title", "")
        key_points = sec.get("key_points", [])
        mapped_sids = sec.get("source_ids", [])
        target_chars = sec.get("target_chars", 1600)
        required_table = sec.get("required_table", "")

        evidence_digest = _build_evidence_digest(packet, allowed_sids=mapped_sids or None, max_chars=16000)
        valid_ids_str = ", ".join(s.get("source_id", "") for s in packet.get("sources", []))

        user_prompt = (
            f"아래 절(Section)의 전문 교재 본문을 한국어로 작성하십시오.\n"
            f"- 절 번호 및 제목: ## {sec_id} {sec_title}\n"
            f"- 대상 독자: {audience}\n"
            f"- 분량 목표: 공백 포함 약 {target_chars}자 내외 (충실한 심화 해설)\n"
            f"- 반드시 다룰 핵심 논점:\n"
            + "\n".join(f"  * {kp}" for kp in key_points)
            + (f"\n- 포함할 비교/요약 마크다운 표: {required_table}" if required_table else "")
            + f"\n- 사용 가능한 유효 출처 ID 목록(이 외 금지): [{valid_ids_str}]\n\n"
            f"[검증 근거 패킷]\n{evidence_digest}\n\n"
            f"출력 형식: 반드시 `## {sec_id} {sec_title}` 헤딩으로 시작하는 순수 마크다운 본문만 출력하십시오."
        )

        t0 = time.time()
        sec_text = client.draft_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            think=think,
            model=target_model,
            temperature=0.7,
            num_ctx=min(cfg.ollama_num_ctx, 24576),
            num_predict=3072,
        )
        elapsed = round(time.time() - t0, 2)
        section_timings.append({"section": sec_id, "chars": len(sec_text), "elapsed_sec": elapsed})
        doc_parts.append(sec_text.strip())
        doc_parts.append("")

    # 2. 단원 말미 핵심 용어집 표 + 연습문제 3문항 + 해설
    all_digest = _build_evidence_digest(packet, max_chars=14000)
    valid_ids_str = ", ".join(s.get("source_id", "") for s in packet.get("sources", []))
    end_prompt = (
        f"'{chapter_title}' 단원 말미에 들어갈 아래 두 섹션을 마크다운으로 작성하십시오.\n"
        f"1. `## 핵심 용어집 (Glossary)`: 토양 유기물 핵심 용어 6~8개를 마크다운 표(`| 용어 | 영문 | 정의 및 의의 | 출처 |`)로 정리.\n"
        f"2. `## 이해도 점검 연습문제 및 해설`: 객관식 2문항 + 심화 서술형 1문항(총 3문항)과 각 문항의 정답·해설.\n"
        f"- 모든 정의와 수치·해설에는 반드시 유효 출처 ID([{valid_ids_str}]) 중 해당하는 `[SRC-NN]`을 표기하십시오.\n"
        f"- 출처 원문을 연속 15어절 이상 그대로 복사하지 마십시오.\n\n"
        f"[검증 근거 패킷]\n{all_digest}"
    )
    t0 = time.time()
    end_matter = client.draft_text(
        system_prompt=system_prompt,
        user_prompt=end_prompt,
        think=think,
        model=target_model,
        temperature=0.7,
        num_ctx=min(cfg.ollama_num_ctx, 24576),
        num_predict=2560,
    )
    section_timings.append({"section": "glossary_and_exercises", "chars": len(end_matter), "elapsed_sec": round(time.time() - t0, 2)})

    doc_parts.append(end_matter.strip())
    doc_parts.append("")
    doc_parts.append(_format_references(packet))
    doc_parts.append("")

    full_text = "\n".join(doc_parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_text, encoding="utf-8")

    return {
        "status": "OK",
        "model": target_model,
        "think": think,
        "out_path": str(out_path),
        "total_chars": len(full_text),
        "sections": section_timings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 Gemma 4 기반 단원 초안 생성기 (domain-drafter)")
    parser.add_argument("--blueprint", type=Path, required=True, help="단원 청사진 YAML 경로")
    parser.add_argument("--evidence", type=Path, required=True, help="근거 패킷 JSON 경로")
    parser.add_argument("--out", type=Path, required=True, help="출력 MDX/MD 경로")
    parser.add_argument("--model", default=None, help="Ollama 모델 오버라이드 (예: gemma4:26b, gemma4:latest)")
    parser.add_argument("--think", action="store_true", help="Gemma 4 <|think|> 추론 모드 활성화")
    args = parser.parse_args()

    res = draft_chapter(
        blueprint_path=args.blueprint,
        evidence_path=args.evidence,
        out_path=args.out,
        model=args.model,
        think=args.think,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
