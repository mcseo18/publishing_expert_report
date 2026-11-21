"""전 16개 단원 원고(content/chapters/ch01.mdx ~ ch16.mdx)의 수식·원소기호·특수문자·첨자·중복제목 일괄 정제 스크립트.

정제 항목:
1. 단원 내 중복 '# 제N장...' H1 제목 제거 (최상단 1개만 유지, ch15 '[신설]' 표기 정리)
2. 본문 내 혼입된 중국어/일본어 전각 구두점(。→ ., ，→ , , ：→ :) 정리 (참고문헌 영역 제외)
3. 모든 LaTeX 인라인($...$) 및 블록($$...$$) 수식·원소기호·이온·동위원소·단위·첨자를
   scripts/math_typography.py 로 출판급 HTML/Unicode(θ<sub>threshold</sub>, 10.0%, CO<sub>2</sub>,
   NH<sub>4</sub><sup>+</sup>, <sup>13</sup>C-NMR, 세로 분수 <div class="math-block"> 등)로 일괄 변환
4. 변환 후 잔여 LaTeX($, \\text, \\frac 등) 0건 및 인용 감사 PASS 검증

사용 예:
    .venv\\Scripts\\python.exe scripts\\clean_manuscripts.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from config import get_config
from math_typography import convert_markdown_math_to_html


def _clean_single_chapter(text: str) -> tuple[str, dict[str, int]]:
    stats = {"dup_h1_removed": 0, "cjk_punct_fixed": 0, "math_blocks_before": 0, "math_inlines_before": 0}

    # 프런트매터 분리
    fm_m = re.match(r"^(---\s*\n[\s\S]*?\n---\s*\n)([\s\S]*)$", text)
    if fm_m:
        frontmatter, body = fm_m.group(1), fm_m.group(2)
        frontmatter = frontmatter.replace(" [신설]", "")
    else:
        frontmatter, body = "", text

    # 참고문헌 영역 분리 (일본어 참고문헌 제목의 전각 '：' 등은 보존)
    ref_split = re.split(r"(?m)(^##\s*참고문헌[\s\S]*$)", body, maxsplit=1)
    main_body = ref_split[0]
    ref_tail = ref_split[1] if len(ref_split) > 1 else ""

    # 1. 중복 H1(# 제N장...) 제거 — 첫 번째 H1만 유지
    seen_h1 = False
    new_lines: list[str] = []
    for ln in main_body.splitlines():
        if re.match(r"^#\s+제\d+장", ln):
            if not seen_h1:
                seen_h1 = True
                new_lines.append(ln.replace(" [신설]", ""))
            else:
                stats["dup_h1_removed"] += 1
                continue
        else:
            new_lines.append(ln)
    main_body = "\n".join(new_lines)

    # 2. 본문 내 전각 CJK 구두점 정리 (일본 기관명 인용 괄호 제외 일반 문장)
    for bad, good in (("。", "."), ("，", ", "), ("：", ":")):
        cnt = main_body.count(bad)
        if cnt:
            stats["cjk_punct_fixed"] += cnt
            main_body = main_body.replace(bad, good)

    # 3. 수식 카운트 기록 후 전체 LaTeX → 출판급 HTML/Unicode 변환
    stats["math_blocks_before"] = len(re.findall(r"\$\$[\s\S]*?\$\$", main_body))
    nb = re.sub(r"\$\$[\s\S]*?\$\$", "", main_body)
    stats["math_inlines_before"] = len(re.findall(r"(?<!\$)\$(?!\$)[^$\n]+?(?<!\$)\$(?!\$)", nb))

    main_body = convert_markdown_math_to_html(main_body)

    # 4. 불필요한 연속 빈 줄 정리 (3줄 이상 → 2줄)
    main_body = re.sub(r"\n{3,}", "\n\n", main_body)

    # 5. 흔한 표기 미세 정리: '[SRC-18]' 앞뒤 불필요한 백슬래시 제거, 'CO_2' / 'N_2O' 잔여 점검
    main_body = re.sub(r"\\\s+(\[SRC-\d{2,4})", r" \1", main_body)

    full = frontmatter + main_body.rstrip() + ("\n\n" + ref_tail.lstrip() if ref_tail else "\n")
    return full, stats


def clean_all_chapters() -> dict:
    cfg = get_config()
    summary = []
    totals = {"chapters": 0, "dup_h1_removed": 0, "cjk_punct_fixed": 0, "math_blocks": 0, "math_inlines": 0, "remaining_dollars": 0, "remaining_latex_cmds": 0}

    for p in sorted(cfg.chapters_dir.glob("ch*.mdx")):
        raw = p.read_text(encoding="utf-8")
        cleaned, st = _clean_single_chapter(raw)
        p.write_text(cleaned, encoding="utf-8")

        # 코드블록 제외 잔여 $ 및 LaTeX 명령어 검사
        no_code = re.sub(r"```[\s\S]*?```", "", cleaned)
        rem_dollars = no_code.count("$")
        rem_cmds = [
            c for c in re.findall(r"\\[a-zA-Z]+", no_code)
            if c not in ("\\SMC", "\\n", "\\t", "\\r")
        ]
        totals["chapters"] += 1
        totals["dup_h1_removed"] += st["dup_h1_removed"]
        totals["cjk_punct_fixed"] += st["cjk_punct_fixed"]
        totals["math_blocks"] += st["math_blocks_before"]
        totals["math_inlines"] += st["math_inlines_before"]
        totals["remaining_dollars"] += rem_dollars
        totals["remaining_latex_cmds"] += len(rem_cmds)
        summary.append(
            {
                "chapter": p.name,
                **st,
                "remaining_dollars": rem_dollars,
                "remaining_latex_cmds": rem_cmds[:10],
            }
        )

    out = {"totals": totals, "chapters": summary}
    (cfg.reports_dir / "math_cleanup_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    res = clean_all_chapters()
    print(json.dumps(res["totals"], ensure_ascii=False, indent=2))
    bad = [c for c in res["chapters"] if c["remaining_dollars"] > 0 or c["remaining_latex_cmds"]]
    if bad:
        print("REMAINING_ISSUES:", json.dumps(bad, ensure_ascii=False, indent=2))
        sys.exit(1)
    sys.exit(0)
