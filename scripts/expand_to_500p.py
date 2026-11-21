"""각 장(ch01~ch16)을 실제 500페이지급 전문 교재 인쇄 분량(장당 ~30~35p, ~28,000~35,000자)으로
증보 집필하는 심화 확장 모듈.

기존 검증 통과 원고(content/chapters/chNN.mdx)의 본문·용어집·참고문헌을 보존하면서,
각 장의 근거 패킷(chNN_evidence.json)에 엄격히 기반한 3개 심화 증보 절을 자동 삽입한다:
  A. 심화 메커니즘 · 정량 수식 및 이론 확장 (Deep Theory & Quantitative Equations)
  B. 실전 정량 계산 예제 및 단계별 풀이 (Worked Numerical Problems — 2문항)
  C. 국내외(한국·일본·미국·유럽) 비교 실증 사례 연구 및 현장 관리 체크리스트

모든 증보 문장에는 [SRC-NN] 인용키를 부착하고, 완료 후 verify_citations.py 로 무결성을 검증한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from config import PlatformConfig, get_config
from draft_chapter import _build_evidence_digest, _format_references
from local_gemma import LocalGemmaClient
from verify_citations import verify_target

EXPANSION_MARKER = "<!-- EXPANDED_500P_V1 -->"


def _insert_before_glossary(mdx_text: str, extra_md: str) -> str:
    """'## 핵심 용어집' (없으면 '## 참고문헌') 직전에 심화 증보 섹션을 깔끔하게 삽입한다."""
    for anchor in (r"(?m)^##\s*핵심 용어집", r"(?m)^##\s*이해도 점검", r"(?m)^##\s*참고문헌"):
        m = re.search(anchor, mdx_text)
        if m:
            idx = m.start()
            return mdx_text[:idx].rstrip() + "\n\n" + EXPANSION_MARKER + "\n\n" + extra_md.strip() + "\n\n" + mdx_text[idx:]
    return mdx_text.rstrip() + "\n\n" + EXPANSION_MARKER + "\n\n" + extra_md.strip() + "\n"


def _refresh_references_section(mdx_text: str, packet: dict[str, Any]) -> str:
    """참고문헌 표를 최신 동기화 패킷 기준으로 갱신한다."""
    ref_md = _format_references(packet)
    m = re.search(r"(?m)^##\s*참고문헌", mdx_text)
    if m:
        return mdx_text[: m.start()].rstrip() + "\n\n" + ref_md + "\n"
    return mdx_text.rstrip() + "\n\n" + ref_md + "\n"


def expand_chapter(
    ch_id: str,
    model: str = "gemma4:latest",
    force: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    mdx_path = cfg.chapters_dir / f"{ch_id}.mdx"
    bp_path = cfg.blueprints_dir / f"{ch_id}.yaml"
    ev_path = cfg.evidence_dir / f"{ch_id}_evidence.json"

    if not mdx_path.is_file() or not bp_path.is_file() or not ev_path.is_file():
        return {"chapter_id": ch_id, "status": "MISSING_INPUT"}

    original = mdx_path.read_text(encoding="utf-8")
    if EXPANSION_MARKER in original and not force:
        return {"chapter_id": ch_id, "status": "ALREADY_EXPANDED", "chars": len(original)}

    # force 시 이전 증보 구간 제거 후 재증보
    if EXPANSION_MARKER in original and force:
        original = re.sub(
            rf"(?m){re.escape(EXPANSION_MARKER)}[\s\S]*?(?=^##\s*(?:핵심 용어집|이해도 점검|참고문헌)|\Z)",
            "",
            original,
        )

    bp = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    packet = json.loads(ev_path.read_text(encoding="utf-8"))
    client = LocalGemmaClient(cfg)

    ch_num = bp.get("chapter_number", int(ch_id[2:]))
    ch_title = bp.get("title", ch_id)
    valid_ids = [s.get("source_id", "") for s in packet.get("sources", []) if s.get("source_id")]
    valid_ids_str = ", ".join(valid_ids)
    digest = _build_evidence_digest(packet, max_chars=18000)

    sys_prompt = (
        "당신은 500페이지 규모 대학원·연구자용 표준 전문 교재 《토양 유기물학》의 수석 저자입니다. "
        "제공된 검증 근거 패킷의 사실·수치만을 바탕으로 해당 단원의 심화 증보 절을 깊이 있고 풍부하게 집필하십시오.\n"
        "[절대 준수 규칙]\n"
        "1. 모든 사실적 주장·수치·단위·사례 문장 끝에 반드시 유효 출처 ID 목록의 `[SRC-NN]`을 표기하십시오.\n"
        "2. 유효 출처 ID 목록에 없는 출처 번호를 절대 지어내지 마십시오.\n"
        "3. 근거 패킷에 없는 세부 상수·지역 실측값은 추측하지 말고 일반 원리·기호식으로 설명하거나 "
        "`<!-- NEED_EVIDENCE: 필요한 자료 설명 -->` 주석을 남기십시오.\n"
        "4. 출처 원문을 연속 15어절 이상 그대로 복사하지 말고 한국어 전문 학술 문체로 재구성하십시오.\n"
        "5. 모든 수치 표현(%, 톤, 년, mg/kg, Pg C 등)이 들어간 줄에는 반드시 `[SRC-NN]` 인용을 포함하십시오."
    )

    modules = [
        (
            f"{ch_num}.4",
            "심화 이론, 정량 수식 및 메커니즘 확장",
            (
                f"'{ch_title}'의 핵심 원리를 대학원 수준으로 심화 확장하는 `## {ch_num}.4 심화 이론, 정량 수식 및 메커니즘 확장` 절을 작성하십시오.\n"
                f"- 분량 목표: 공백 포함 약 4,500자 이상 (상세한 하위 소절 `### {ch_num}.4.1`, `### {ch_num}.4.2`, `### {ch_num}.4.3` 구성)\n"
                f"- 반드시 포함할 요소: (1) 물리·화학·생물·수학적 지배 방정식 또는 정량 관계식(LaTeX 수식 또는 명확한 기호식과 변수 정의), "
                f"(2) 핵심 매개변수별 민감도 및 경계 조건 비교 마크다운 표, (3) 기존 이론과 최신 연구 패러다임 간 논쟁점 및 통합 해석.\n"
                f"- 유효 출처 ID 목록(이 외 금지): [{valid_ids_str}]\n\n[검증 근거 패킷]\n{digest}"
            ),
        ),
        (
            f"{ch_num}.5",
            "실전 정량 계산 예제 및 단계별 풀이 (Worked Examples)",
            (
                f"'{ch_title}'의 이론을 연구실·영농 현장에 바로 적용할 수 있는 `## {ch_num}.5 실전 정량 계산 예제 및 단계별 풀이` 절을 작성하십시오.\n"
                f"- 분량 목표: 공백 포함 약 4,000자 이상\n"
                f"- 반드시 포함할 요소: 서로 다른 주제의 **실전 계산/해석 예제 2문항** (`### 예제 {ch_num}-1`, `### 예제 {ch_num}-2`) — 각 문항마다 "
                f"[문제 상황 및 주어진 조건] → [적용 원리 및 수식] → [단계별 계산 과정] → [결과 해석 및 현장 처방 시사점] 순으로 상세 서술하고, "
                f"계산 결과를 요약하는 마크다운 표를 포함하십시오. (예제용 가정 입력값임을 명시하되, 모든 원리·기준치에는 `[SRC-NN]` 인용 필수)\n"
                f"- 유효 출처 ID 목록(이 외 금지): [{valid_ids_str}]\n\n[검증 근거 패킷]\n{digest}"
            ),
        ),
        (
            f"{ch_num}.6",
            "국내외(한국·일본·미국·유럽) 비교 실증 사례 및 현장 관리 진단 체크리스트",
            (
                f"'{ch_title}'와 관련된 국제·국내 실증 연구와 현장 적용 가이드를 정리하는 `## {ch_num}.6 국내외 비교 실증 사례 및 현장 관리 진단 체크리스트` 절을 작성하십시오.\n"
                f"- 분량 목표: 공백 포함 약 4,500자 이상 (`### {ch_num}.6.1`, `### {ch_num}.6.2`, `### {ch_num}.6.3` 구성)\n"
                f"- 반드시 포함할 요소: (1) 근거 패킷에 포함된 국내(농진청·흙토람·한국토양비료학회지) 및 해외(일본·미국·유럽·FAO) 사례의 심층 비교 분석 마크다운 표, "
                f"(2) 실무 현장에서 자주 발생하는 오류·함정과 대책을 정리한 콜아웃(`> **[현장 주의사항]** ...`) 2개 이상, "
                f"(3) 연구자·지도사를 위한 단계별 현장 진단 체크리스트 표.\n"
                f"- 유효 출처 ID 목록(이 외 금지): [{valid_ids_str}]\n\n[검증 근거 패킷]\n{digest}"
            ),
        ),
    ]

    t0 = time.time()
    parts: list[str] = []
    mod_stats: list[dict[str, Any]] = []
    for sec_id, sec_title, prompt in modules:
        mt0 = time.time()
        txt = client.draft_text(
            system_prompt=sys_prompt,
            user_prompt=prompt,
            think=False,
            model=model,
            temperature=0.7,
            num_ctx=24576,
            num_predict=4096,
        )
        parts.append(txt.strip())
        mod_stats.append({"section": sec_id, "chars": len(txt), "elapsed_sec": round(time.time() - mt0, 2)})

    expanded_block = "\n\n".join(parts)
    merged = _insert_before_glossary(original, expanded_block)
    merged = _refresh_references_section(merged, packet)
    mdx_path.write_text(merged, encoding="utf-8")

    audit = verify_target(mdx_path, cfg=cfg)
    (cfg.reports_dir / f"audit_{ch_id}.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "chapter_id": ch_id,
        "status": audit["status"],
        "chars_before": len(original),
        "chars_after": len(merged),
        "elapsed_sec": round(time.time() - t0, 2),
        "critical_errors": len(audit["critical_errors"]),
        "warnings": len(audit["warnings"]),
        "modules": mod_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="전 단원 500페이지급 심화 증보 집필 러너")
    parser.add_argument("--chapters", default="", help="쉼표 구분 단원 ID (비우면 ch01~ch16 전체)")
    parser.add_argument("--model", default="gemma4:latest", help="로컬 Ollama 모델 (기본 gemma4:latest 100% GPU)")
    parser.add_argument("--force", action="store_true", help="이미 증보된 단원도 재증보")
    args = parser.parse_args()

    cfg = get_config()
    if args.chapters:
        ch_ids = [c.strip() for c in args.chapters.split(",") if c.strip()]
    else:
        ch_ids = sorted(p.stem for p in cfg.chapters_dir.glob("ch*.mdx"))

    results = []
    for cid in ch_ids:
        print(f"[EXPAND 500P] {cid} ({args.model}) ...", flush=True)
        r = expand_chapter(cid, model=args.model, force=args.force, cfg=cfg)
        print(f"  -> {cid}: {r['status']} | {r.get('chars_before', 0):,} -> {r.get('chars_after', r.get('chars', 0)):,}자 (crit={r.get('critical_errors', 0)})", flush=True)
        results.append(r)

    full_audit = verify_target(cfg.chapters_dir, cfg=cfg)
    (cfg.reports_dir / "audit_latest.json").write_text(json.dumps(full_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "chapters": len(results),
        "total_chars": sum(r.get("chars_after", r.get("chars", 0)) for r in results),
        "full_audit_status": full_audit["status"],
        "full_audit_critical_errors": len(full_audit["critical_errors"]),
        "results": results,
    }
    (cfg.reports_dir / "expansion_500p_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))
    return 0 if full_audit["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
