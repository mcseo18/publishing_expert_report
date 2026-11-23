"""전문 교재·보고서용 수식·화학식·원소기호·특수기호·첨자 통합 변환 및 DOCX 리치텍스트 렌더러.

기능:
1. LaTeX 인라인($...$) 및 블록($$...$$) 수식을 출판급 HTML/Unicode 타이포그래피로 무손실 변환:
   - 그리스 문자(θ, Δ, α, β, γ, μ, ρ, η, τ, λ, Ψ, Φ), 수학·화학 기호(×, ·, ±, ≈, ~, ∝, ∈, ≪, ≫, °, ∂, ∑, →, ↔, ↑, ↓, ⇒, ⇌)
   - 화학식·이온·동위원소·단위(CO₂, CH₄, N₂O, NH₄⁺, NO₃⁻, Ca²⁺, ¹³C-NMR, 10 °C, 53~250 μm, cmol(+)/kg)
   - 중첩 첨자(θ<sub>threshold</sub>, C<sub>SOM</sub>, e<sup>−kt</sup>) 및 반응 화살표(\\xrightarrow)
   - 분수(\\frac{a}{b})를 인쇄·웹용 세로 분수(<span class="m-frac">)로 렌더링
   - 수식 내부에 끼어 있던 [SRC-NN] 인용키를 수식 바깥으로 안전 분리
2. Word(.docx) 생성 시 <sub>/<sup>/<i>/<b>/**bold**/<span class="m-frac">/<div class="math-block">를
   네이티브 Word 위첨자·아래첨자·이탤릭·볼드·중앙정렬 수식 박스로 렌더링 (문단 + 표 셀 모두 지원).
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

STANDARD_EQUATIONS_PATH = Path(__file__).resolve().parent.parent / "schemas" / "standard_equations.json"
_EQUATIONS_CACHE: list[dict[str, Any]] | None = None


def load_standard_equations(path: Path | None = None) -> list[dict[str, Any]]:
    """검증된 농학·관개·토양 표준 수식 라이브러리(schemas/standard_equations.json)를 로드한다 (C7)."""
    global _EQUATIONS_CACHE
    target = path or STANDARD_EQUATIONS_PATH
    if path is None and _EQUATIONS_CACHE is not None:
        return _EQUATIONS_CACHE
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        eqs = list(data.get("equations") or [])
        if path is None:
            _EQUATIONS_CACHE = eqs
        return eqs
    except Exception:
        return []


def match_equations_for_text(query_text: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """주제·단원·절 텍스트와 관련된 검증 표준 수식 목록을 반환한다."""
    blob = (query_text or "").lower()
    if not blob.strip():
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for eq in load_standard_equations():
        kws = [str(k).lower() for k in (eq.get("keywords") or [])]
        score = sum(2 if len(k) >= 3 else 1 for k in kws if k and k in blob)
        if score > 0:
            scored.append((score, eq))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [eq for _, eq in scored[:limit]]


def format_equations_for_prompt(query_text: str, *, limit: int = 5) -> str:
    """4단계 집필 프롬프트에 주입할 [검증 표준 수식 라이브러리] 블록을 생성한다 (모델의 수식 창작 차단)."""
    matched = match_equations_for_text(query_text, limit=limit)
    if not matched:
        return ""
    lines = [
        "[검증 표준 수식 라이브러리 — 아래 수식이 필요할 경우 반드시 검증된 원형과 출처를 그대로 사용하고 임의로 변형·창작하지 마십시오]"
    ]
    for eq in matched:
        lines.append(f"- **{eq['name_ko']}** (`{eq['id']}`):")
        lines.append(f"  - 표준식: `{eq['html']}`")
        lines.append(f"  - 변수/단위: {'; '.join(eq.get('variables') or [])}")
        lines.append(f"  - 표준 출처: {eq.get('reference', '')}")
    return "\n".join(lines)


def validate_known_formulas(markdown_text: str) -> list[dict[str, Any]]:
    """원고 본문에서 알려진 오류 수식·개념 왜곡 패턴(P2~P5 등)을 탐지한다."""
    findings: list[dict[str, Any]] = []
    lines = (markdown_text or "").splitlines()
    for eq in load_standard_equations():
        patterns = eq.get("known_invalid_patterns") or []
        for pat in patterns:
            try:
                rx = re.compile(pat, re.I)
            except re.error:
                continue
            for lineno, line in enumerate(lines, start=1):
                stripped_l = line.strip()
                # '오해와 진실'의 오해(Myth) 예시 문장은 오류 교정 목적이므로 예외 처리
                if stripped_l.startswith(("- **오해", "**오해", "오해:")):
                    continue
                if rx.search(line):
                    findings.append(
                        {
                            "type": "INVALID_FORMULA_PATTERN",
                            "equation_id": eq["id"],
                            "equation_name": eq["name_ko"],
                            "line": lineno,
                            "snippet": line.strip()[:140],
                            "expected_html": eq.get("html", ""),
                            "reference": eq.get("reference", ""),
                            "message": (
                                f"검증된 표준식({eq['name_ko']})과 모순되는 오류 표현이 탐지되었습니다. "
                                f"표준식: {eq.get('html', '')} ({eq.get('reference', '')})"
                            ),
                        }
                    )
    return findings

# 지원 LaTeX 심볼 테이블 (그리스 문자·수학 연산자·집합·화살표·단위·함수명 완비)
SYMBOL_MAP: dict[str, str] = {
    # 그리스 문자 (소문자·대문자)
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "Gamma": "Γ",
    "delta": "δ",
    "Delta": "Δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "Theta": "Θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "Lambda": "Λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "Xi": "Ξ",
    "pi": "π",
    "Pi": "Π",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "Sigma": "Σ",
    "tau": "τ",
    "upsilon": "υ",
    "Upsilon": "Υ",
    "phi": "φ",
    "varphi": "φ",
    "Phi": "Φ",
    "chi": "χ",
    "psi": "ψ",
    "Psi": "Ψ",
    "omega": "ω",
    "Omega": "Ω",
    "ell": "ℓ",
    # 연산자·관계·집합·논리 기호
    "times": "×",
    "cdot": "·",
    "cdots": "⋯",
    "ldots": "…",
    "dots": "…",
    "pm": "±",
    "mp": "∓",
    "div": "÷",
    "ast": "∗",
    "star": "★",
    "oplus": "⊕",
    "otimes": "⊗",
    "approx": "≈",
    "sim": "~",
    "simeq": "≃",
    "cong": "≅",
    "equiv": "≡",
    "neq": "≠",
    "ne": "≠",
    "leq": "≤",
    "le": "≤",
    "geq": "≥",
    "ge": "≥",
    "ll": "≪",
    "gg": "≫",
    "propto": "∝",
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cup": "∪",
    "cap": "∩",
    "emptyset": "∅",
    "varnothing": "∅",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "wedge": "∧",
    "vee": "∨",
    "perp": "⊥",
    "parallel": "∥",
    "angle": "∠",
    "triangle": "△",
    "infty": "∞",
    "partial": "∂",
    "nabla": "∇",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "oint": "∮",
    "circ": "°",
    "degree": "°",
    "deg": "°",
    "prime": "′",
    "mid": "|",
    "setminus": "\\",
    "langle": "⟨",
    "rangle": "⟩",
    "lfloor": "⌊",
    "rfloor": "⌋",
    "lceil": "⌈",
    "rceil": "⌉",
    "Vert": "‖",
    "lVert": "‖",
    "rVert": "‖",
    "vert": "|",
    "lvert": "|",
    "rvert": "|",
    # 화살표·반응 기호
    "rightarrow": "→",
    "to": "→",
    "longrightarrow": "⟶",
    "leftarrow": "←",
    "longleftarrow": "⟵",
    "leftrightarrow": "↔",
    "longleftrightarrow": "⟷",
    "Rightarrow": "⇒",
    "implies": "⇒",
    "Leftarrow": "⇐",
    "Leftrightarrow": "⇔",
    "iff": "⇔",
    "mapsto": "↦",
    "rightleftharpoons": "⇌",
    "uparrow": "↑",
    "downarrow": "↓",
    "updownarrow": "↕",
    # 함수명 (로만체)
    "exp": "exp",
    "ln": "ln",
    "log": "log",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "arcsin": "arcsin",
    "arccos": "arccos",
    "arctan": "arctan",
    "max": "max",
    "min": "min",
    "argmax": "argmax",
    "argmin": "argmin",
    "arg": "arg",
    "sup": "sup",
    "inf": "inf",
    "lim": "lim",
    "det": "det",
    "Pr": "Pr",
    "std": "SD",
    "var": "Var",
    "cov": "Cov",
    # 공백·구분
    "quad": "  ",
    "qquad": "    ",
    "enspace": " ",
    "thinspace": " ",
    "space": " ",
    "left": "",
    "right": "",
    "big": "",
    "Big": "",
    "bigg": "",
    "Bigg": "",
    "displaystyle": "",
    "textstyle": "",
    "limits": "",
    "nolimits": "",
}

_BLACKBOARD_MAP: dict[str, str] = {
    "R": "ℝ",
    "N": "ℕ",
    "Z": "ℤ",
    "Q": "ℚ",
    "C": "ℂ",
    "E": "𝔼",
    "P": "ℙ",
}

_ACCENT_COMBINING: dict[str, str] = {
    "hat": "\u0302",
    "widehat": "\u0302",
    "bar": "\u0304",
    "overline": "\u0304",
    "tilde": "\u0303",
    "widetilde": "\u0303",
    "vec": "\u20d7",
    "dot": "\u0307",
    "ddot": "\u0308",
}

_ACCENT_PRECOMPOSED: dict[tuple[str, str], str] = {
    ("hat", "y"): "ŷ",
    ("hat", "Y"): "Ŷ",
    ("hat", "a"): "â",
    ("hat", "e"): "ê",
    ("hat", "i"): "î",
    ("hat", "o"): "ô",
    ("hat", "u"): "û",
    ("bar", "y"): "ȳ",
    ("bar", "Y"): "Ȳ",
    ("bar", "a"): "ā",
    ("bar", "e"): "ē",
    ("bar", "i"): "ī",
    ("bar", "o"): "ō",
    ("bar", "u"): "ū",
    ("tilde", "n"): "ñ",
    ("tilde", "a"): "ã",
    ("tilde", "o"): "õ",
}

_UNICODE_SUB_MAP = str.maketrans("0123456789+-=()aeoxhklmnpst", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ")
_UNICODE_SUP_MAP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")


def _read_brace_group(s: str, pos: int) -> tuple[str, int]:
    """s[pos] == '{' 인 위치에서 짝이 맞는 '}'까지의 내부 문자열과 다음 인덱스를 반환한다."""
    n = len(s)
    if pos >= n or s[pos] != "{":
        return "", pos
    depth = 0
    start = pos + 1
    i = pos
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i], i + 1
        i += 1
    return s[start:], n


def _read_script_arg(s: str, pos: int) -> tuple[str, int]:
    """_ 또는 ^ 뒤의 인자({group} 또는 \\cmd 또는 단일 문자)를 읽는다."""
    n = len(s)
    while pos < n and s[pos] == " ":
        pos += 1
    if pos >= n:
        return "", pos
    if s[pos] == "{":
        return _read_brace_group(s, pos)
    if s[pos] == "\\":
        m = re.match(r"\\([a-zA-Z]+|.)", s[pos:])
        if m:
            return m.group(0), pos + len(m.group(0))
    return s[pos], pos + 1


def _strip_outer_citations(expr: str) -> tuple[str, list[str]]:
    """수식 내부 말미에 포함된 \\text{[SRC-01]} 또는 [\\text{SRC-22}] 인용키를 안전하게 분리한다."""
    cites: list[str] = []

    def _collect(m: re.Match[str]) -> str:
        inner = m.group(1) or m.group(2) or ""
        # 내부 \text{...} 제거
        inner = re.sub(r"\\text\{([^}]*)\}", r"\1", inner)
        inner = re.sub(r"\\[,;:\s]+", " ", inner).strip()
        if inner:
            cites.append(f"[{inner}]")
        return ""

    # \quad \text{[SRC-01, SRC-02]} / \quad [\text{SRC-01}] / \ [SRC-68]
    cleaned = re.sub(
        r"(?:\\quad|\\qquad|\\[ ,;])*\s*(?:\\text\{\s*\[(SRC-\d{2,4}[^\]]*)\]\s*\}|\[\s*(?:\\text\{)?(SRC-\d{2,4}[^\]]*?)(?:\})?\s*\])",
        _collect,
        expr,
    )
    # \quad \text{[추정식]} 같은 보조 라벨은 일반 괄호 태그로 보존
    cleaned = re.sub(r"\\quad\s*\\text\{\[([^\]]+)\]\}", r"  [\1]", cleaned)
    cleaned = re.sub(r"\\quad\s*\[\\text\{([^\}]+)\}\]", r"  [\1]", cleaned)
    return cleaned.strip(), cites


def _format_plain_text_in_math(text: str) -> str:
    """\\text{...} 내부 텍스트의 백슬래시 이스케이프를 정리한다."""
    t = text.replace(r"\%", "%").replace(r"\_", "_").replace(r"\&", "&")
    t = t.replace(r"\ ", " ")
    return html.escape(t)


def latex_to_html(expr: str, *, display: bool = False) -> tuple[str, list[str]]:
    """단일 LaTeX 수식 문자열을 출판급 HTML 문자열과 분리된 인용키 목록으로 변환한다."""
    cleaned, cites = _strip_outer_citations(expr.strip())
    # 특수 패턴: ^\circ\text{C} / ^\circ C → °C, ^\circ → °
    cleaned = re.sub(r"\^\s*\\circ\s*(?:\\text\{C\}|C)\b", "°C", cleaned)
    cleaned = re.sub(r"\^\s*\{\s*\\circ\s*\}\s*(?:\\text\{C\}|C)\b", "°C", cleaned)
    cleaned = re.sub(r"\^\s*\\circ\b", "°", cleaned)
    cleaned = re.sub(r"\^\s*\{\s*\\circ\s*\}", "°", cleaned)

    html_out = _parse_latex_segment(cleaned, in_script=False)
    # 연속 공백 및 이항 연산자 주변 여백 미세 정리
    html_out = re.sub(r"[ \t]{3,}", " &nbsp; ", html_out)
    html_out = html_out.replace("°C", " °C").replace("  °C", " °C")
    html_out = re.sub(r"\(\s+", "(", html_out)
    html_out = re.sub(r"\s+\)", ")", html_out)
    html_out = html_out.strip()
    return html_out, cites


def _parse_latex_segment(s: str, *, in_script: bool = False) -> str:
    out: list[str] = []
    i = 0
    n = len(s)

    while i < n:
        ch = s[i]

        # 백슬래시 명령어
        if ch == "\\":
            if i + 1 >= n:
                i += 1
                continue
            nxt = s[i + 1]
            # 1문자 이스케이프: \|, \%, \_, \ , \,, \;, \:, \!
            if not nxt.isalpha():
                if nxt == "|":
                    out.append("‖")
                elif nxt in ("%", "_", "&", "#", "$", "{", "}"):
                    out.append(html.escape(nxt))
                elif nxt in (" ", ",", ";", ":"):
                    out.append(" ")
                elif nxt == "!":
                    pass
                else:
                    out.append(html.escape(nxt))
                i += 2
                continue

            # 영문 명령어 읽기
            m = re.match(r"[a-zA-Z]+", s[i + 1 :])
            cmd = m.group(0) if m else ""
            i += 1 + len(cmd)

            # \ce{...} 화학식 (mhchem 호환)
            if cmd == "ce":
                while i < n and s[i] == " ":
                    i += 1
                if i < n and s[i] == "{":
                    grp, i = _read_brace_group(s, i)
                    out.append(_parse_ce_formula(grp))
                continue

            # \text{...}, \mathrm{...}, \operatorname{...}, \mathsf{...}
            if cmd in ("text", "mathrm", "textrm", "operatorname", "rm", "mathsf", "mathtt"):
                while i < n and s[i] == " ":
                    i += 1
                if i < n and s[i] == "{":
                    grp, i = _read_brace_group(s, i)
                    if "\\" in grp or "^" in grp or "_" in grp:
                        out.append(_parse_latex_segment(grp, in_script=True))
                    else:
                        out.append(_format_plain_text_in_math(grp))
                continue

            # \mathbb{R}, \mathcal{L} 등 수학 특수 서체
            if cmd in ("mathbb", "mathcal", "mathfrak"):
                while i < n and s[i] == " ":
                    i += 1
                if i < n and s[i] == "{":
                    grp, i = _read_brace_group(s, i)
                    if cmd == "mathbb":
                        out.append("".join(_BLACKBOARD_MAP.get(c, c) for c in grp))
                    else:
                        out.append(f"<i>{html.escape(grp)}</i>")
                continue

            # \hat{y}, \bar{y}, \overline{x}, \tilde{x}, \vec{v}, \dot{x} 등 악센트 기호
            if cmd in _ACCENT_COMBINING:
                while i < n and s[i] == " ":
                    i += 1
                arg, i = _read_script_arg(s, i)
                rendered = _parse_latex_segment(arg, in_script=True).strip()
                plain_r = re.sub(r"<[^>]+>", "", rendered)
                base_cmd = "hat" if "hat" in cmd else ("bar" if cmd in ("bar", "overline") else ("tilde" if "tilde" in cmd else cmd))
                if len(plain_r) == 1 and (base_cmd, plain_r) in _ACCENT_PRECOMPOSED:
                    out.append(_ACCENT_PRECOMPOSED[(base_cmd, plain_r)])
                elif len(plain_r) == 1:
                    out.append(f"{plain_r}{_ACCENT_COMBINING[cmd]}")
                else:
                    out.append(f"{rendered}{_ACCENT_COMBINING[cmd]}")
                continue

            # \mathbf{...}, \textbf{...}, \boldsymbol{...}
            if cmd in ("mathbf", "textbf", "boldsymbol", "bm"):
                while i < n and s[i] == " ":
                    i += 1
                if i < n and s[i] == "{":
                    grp, i = _read_brace_group(s, i)
                    out.append(f"<b>{_parse_latex_segment(grp, in_script=True)}</b>")
                continue

            # \mathit{...}, \textit{...}
            if cmd in ("mathit", "textit"):
                while i < n and s[i] == " ":
                    i += 1
                if i < n and s[i] == "{":
                    grp, i = _read_brace_group(s, i)
                    out.append(f"<i>{_parse_latex_segment(grp, in_script=True)}</i>")
                continue

            # \frac{num}{den}
            if cmd in ("frac", "dfrac", "tfrac"):
                while i < n and s[i] == " ":
                    i += 1
                num, i = _read_script_arg(s, i)
                den, i = _read_script_arg(s, i)
                num_h = _parse_latex_segment(num, in_script=False)
                den_h = _parse_latex_segment(den, in_script=False)
                out.append(
                    f'<span class="m-frac"><span class="m-num">{num_h}</span>'
                    f'<span class="m-den">{den_h}</span></span>'
                )
                continue

            # \sqrt{x}
            if cmd == "sqrt":
                while i < n and s[i] == " ":
                    i += 1
                arg, i = _read_script_arg(s, i)
                out.append(f"√({_parse_latex_segment(arg, in_script=in_script)})")
                continue

            # \xrightarrow{label}
            if cmd == "xrightarrow":
                while i < n and s[i] == " ":
                    i += 1
                lbl, i = _read_script_arg(s, i)
                lbl_h = _parse_latex_segment(lbl, in_script=True)
                out.append(
                    f' <span class="m-rxn"><span class="m-rxn-lbl">{lbl_h}</span>'
                    f'<span class="m-rxn-arr">⟶</span></span> '
                )
                continue

            # 등록 심볼
            if cmd in SYMBOL_MAP:
                sym = SYMBOL_MAP[cmd]
                if cmd in ("rightarrow", "to", "leftarrow", "leftrightarrow", "implies", "rightleftharpoons", "approx", "propto", "in", "ll", "gg"):
                    out.append(f" {sym} ")
                elif cmd in ("times", "cdot", "pm"):
                    out.append(f" {sym} ")
                else:
                    out.append(sym)
                continue

            # 미등록 명령어는 안전하게 텍스트로 보존 (백슬래시 제거)
            out.append(html.escape(cmd))
            continue

        # 아래첨자 _
        if ch == "_":
            arg, i = _read_script_arg(s, i + 1)
            sub_h = _parse_latex_segment(arg, in_script=True)
            out.append(f"<sub>{sub_h}</sub>")
            continue

        # 위첨자 ^
        if ch == "^":
            arg, i = _read_script_arg(s, i + 1)
            # 이온 전하 '-' → 수학 마이너스 '−'
            if arg == "-":
                sup_h = "−"
            else:
                sup_h = _parse_latex_segment(arg, in_script=True)
                sup_h = sup_h.replace("-", "−")
            out.append(f"<sup>{sup_h}</sup>")
            continue

        # 중괄호 그룹 { ... }
        if ch == "{":
            grp, i = _read_brace_group(s, i)
            out.append(_parse_latex_segment(grp, in_script=in_script))
            continue

        if ch == "}":
            i += 1
            continue

        # HTML 특수문자 이스케이프 (<, >, &)
        if ch == "<":
            out.append("&lt;")
            i += 1
            continue
        if ch == ">":
            out.append("&gt;")
            i += 1
            continue
        if ch == "&":
            out.append("&amp;")
            i += 1
            continue

        out.append(ch)
        i += 1

    res = "".join(out)
    # 중복 공백 정리
    res = re.sub(r" {2,}", " ", res)
    return res


def _parse_ce_formula(ce_str: str) -> str:
    """\\ce{...} 화학식·이온·반응식을 출판급 HTML 첨자(<sub>/<sup>)로 변환한다."""
    s = ce_str.strip()
    s = s.replace("<=>", " ⇌ ").replace("<->", " ↔ ").replace("->", " → ").replace("<-", " ← ")
    # 명시적 위첨자 전하: ^{2+}, ^{3-}, ^+, ^-
    s = re.sub(r"\^\{([^}]+)\}", lambda m: f"<sup>{m.group(1).replace('-', '−')}</sup>", s)
    s = re.sub(r"\^([0-9]*[+-])", lambda m: f"<sup>{m.group(1).replace('-', '−')}</sup>", s)
    # 원소/닫는괄호 뒤 전하: NH4+, NO3-, Ca2+, PO43-
    s = re.sub(r"([A-Za-z\)])(\d+)([+-])(?=\s|$|[,;.)])", lambda m: f"{m.group(1)}<sub>{m.group(2)}</sub><sup>{m.group(3).replace('-', '−')}</sup>", s)
    s = re.sub(r"([A-Za-z\)])([+-])(?=\s|$|[,;.)])", lambda m: f"{m.group(1)}<sup>{m.group(2).replace('-', '−')}</sup>", s)
    # 원소/닫는괄호 뒤 화학량론 숫자: CO2, H2O, CaCO3, PO4
    s = re.sub(r"([A-Za-z\)])(\d+)", r"\1<sub>\2</sub>", s)
    return s


# 평문 본문에서 안전하게 정규화할 표준 화학식·이온·단위 패턴 (URL/DOI/코드/모델명 보호 영역 외부에서만 적용)
_PLAIN_CHEM_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # 주요 이온 (전하 포함)
    (re.compile(r"\bNH4\+"), "NH<sub>4</sub><sup>+</sup>"),
    (re.compile(r"\bNO3-(?!\w)"), "NO<sub>3</sub><sup>−</sup>"),
    (re.compile(r"\bNO2-(?!\w)"), "NO<sub>2</sub><sup>−</sup>"),
    (re.compile(r"\bPO4\^?3-"), "PO<sub>4</sub><sup>3−</sup>"),
    (re.compile(r"\bHPO4\^?2-"), "HPO<sub>4</sub><sup>2−</sup>"),
    (re.compile(r"\bH2PO4-(?!\w)"), "H<sub>2</sub>PO<sub>4</sub><sup>−</sup>"),
    (re.compile(r"\bSO4\^?2-"), "SO<sub>4</sub><sup>2−</sup>"),
    (re.compile(r"\bHCO3-(?!\w)"), "HCO<sub>3</sub><sup>−</sup>"),
    (re.compile(r"\bCO3\^?2-"), "CO<sub>3</sub><sup>2−</sup>"),
    (re.compile(r"\bCa2\+"), "Ca<sup>2+</sup>"),
    (re.compile(r"\bMg2\+"), "Mg<sup>2+</sup>"),
    (re.compile(r"\bFe2\+"), "Fe<sup>2+</sup>"),
    (re.compile(r"\bFe3\+"), "Fe<sup>3+</sup>"),
    (re.compile(r"\bAl3\+"), "Al<sup>3+</sup>"),
    (re.compile(r"\bMn2\+"), "Mn<sup>2+</sup>"),
    (re.compile(r"\bZn2\+"), "Zn<sup>2+</sup>"),
    # 주요 분자·산화물·동위원소
    (re.compile(r"\bCO2\b"), "CO<sub>2</sub>"),
    (re.compile(r"\bCH4\b"), "CH<sub>4</sub>"),
    (re.compile(r"\bN2O\b"), "N<sub>2</sub>O"),
    (re.compile(r"\bH2O\b"), "H<sub>2</sub>O"),
    (re.compile(r"\bO2\b"), "O<sub>2</sub>"),
    (re.compile(r"\bN2\b"), "N<sub>2</sub>"),
    (re.compile(r"\bNH3\b"), "NH<sub>3</sub>"),
    (re.compile(r"\bCaCO3\b"), "CaCO<sub>3</sub>"),
    (re.compile(r"\bP2O5\b"), "P<sub>2</sub>O<sub>5</sub>"),
    (re.compile(r"\bK2O\b"), "K<sub>2</sub>O"),
    (re.compile(r"\bSiO2\b"), "SiO<sub>2</sub>"),
    (re.compile(r"δ13C\b"), "δ<sup>13</sup>C"),
    (re.compile(r"\b13C-NMR\b"), "<sup>13</sup>C-NMR"),
    (re.compile(r"δ15N\b"), "δ<sup>15</sup>N"),
    # 주요 단위 지수·과학 지표 (단독 토큰 한정)
    (re.compile(r"(?<![A-Za-z0-9_])(cm|mm|km|μm|um)2(?![A-Za-z0-9_])"), r"\1<sup>2</sup>"),
    (re.compile(r"(?<![A-Za-z0-9_])(cm|mm|m)3(?![A-Za-z0-9_])"), r"\1<sup>3</sup>"),
    (re.compile(r"(?<![A-Za-z0-9_])m2(?=/m2|[^A-Za-z0-9_]|$)"), "m<sup>2</sup>"),
    (re.compile(r"(?<![A-Za-z0-9_])(m|s|d|day|h|ha|kg|g|L|mol)\^(-?\d+)(?![A-Za-z0-9_])"), lambda m: f"{m.group(1)}<sup>{m.group(2).replace('-', '−')}</sup>"),
    (re.compile(r"\b(AP|AR)(25|50|75)\b"), r"\1<sub>\2</sub>"),
    (re.compile(r"\bET0\b"), "ET<sub>0</sub>"),
    (re.compile(r"\bETc\b"), "ET<sub>c</sub>"),
    (re.compile(r"\bQ10\b"), "Q<sub>10</sub>"),
    (re.compile(r"\bR2(?=\s*(?:=|>|<|≥|≤|값|는|가|의|\d))"), "R<sup>2</sup>"),
]


def normalize_plain_scientific_tokens(text: str) -> str:
    """URL·DOI·코드·인용키·HTML 태그를 보호하면서 평문 화학식·원소이온·단위 지수를 <sub>/<sup>로 정규화한다."""
    if not text:
        return text
    protected: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return f"@@SCI_PROT_{idx}@@"

    # 코드펜스, 인라인 코드, URL, DOI, [SRC-NN], HTML 태그 보호
    s = re.sub(r"```[\s\S]*?```", _stash, text)
    s = re.sub(r"`[^`\n]+`", _stash, s)
    s = re.sub(r"https?://\S+", _stash, s)
    s = re.sub(r"\b10\.\d{4,9}/[^\s\])]+", _stash, s)
    s = re.sub(r"\[SRC-\d{2,4}[^\]]*\]", _stash, s)
    s = re.sub(r"<[^>]+>", _stash, s)

    for rx, repl in _PLAIN_CHEM_REPLACEMENTS:
        s = rx.sub(repl, s)

    for idx, orig in enumerate(protected):
        s = s.replace(f"@@SCI_PROT_{idx}@@", orig)
    return s


def convert_markdown_math_to_html(md_text: str) -> str:
    """마크다운 텍스트 내 코드펜스를 보존하면서 모든 $$...$$, \\[...\\], $...$, \\(...\\) 수식을 출판급 HTML/Unicode로 변환한다."""
    # 코드펜스·인라인 코드 보호
    fences: list[str] = []

    def _stash_fence(m: re.Match[str]) -> str:
        idx = len(fences)
        fences.append(m.group(0))
        return f"@@CODE_FENCE_{idx}@@"

    text = re.sub(r"```[\s\S]*?```", _stash_fence, md_text)
    text = re.sub(r"`[^`\n]+`", _stash_fence, text)

    # 1) 인용 괄호 내부에 들어간 $...$ 선처리: [SRC-65, 퇴비화 $\rightarrow$ 이분해성 탄소]
    def _clean_cite_bracket(m: re.Match[str]) -> str:
        inner = m.group(0)
        if "$" not in inner:
            return inner
        return re.sub(
            r"\$([^$\n]+?)\$",
            lambda mm: re.sub(r"<[^>]+>", "", latex_to_html(mm.group(1))[0]),
            inner,
        )

    text = re.sub(r"\[SRC-\d{2,4}[^\]]*\]", _clean_cite_bracket, text)

    # 2) 블록 수식 $$...$$ 및 \[...\] 변환
    def _replace_block(m: re.Match[str]) -> str:
        expr = m.group(1).strip()
        h, cites = latex_to_html(expr, display=True)
        cite_str = f' <span class="math-cite">{" ".join(cites)}</span>' if cites else ""
        return f'\n<div class="math-block"><span class="math-eq">{h}</span>{cite_str}</div>\n'

    text = re.sub(r"\$\$([\s\S]*?)\$\$", _replace_block, text)
    text = re.sub(r"\\\[([\s\S]*?)\\\]", _replace_block, text)

    # 3) 인라인 수식 $...$ 및 \(...\) 변환 (통화 금액 $1.00 / $0.039 제외!)
    def _replace_inline(m: re.Match[str]) -> str:
        expr = m.group(1)
        # 달러 통화($0.039, $1.00 등) 오인 방지: 앞뒤가 순수 금액 형태이고 LaTeX 기호가 없으면 유지
        if re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*(?:~|-|–|to)?\s*(?:\d+(?:[.,]\d+)?)?\s*", expr):
            return m.group(0)
        h, cites = latex_to_html(expr, display=False)
        cite_str = (" " + " ".join(cites)) if cites else ""
        if not h and cite_str:
            return cite_str.strip()
        return f"{h}{cite_str}"

    text = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)", _replace_inline, text)
    text = re.sub(r"\\\(([^)\n]+?)\\\)", _replace_inline, text)

    # 4) 평문 화학식·이온·단위 지수 정규화
    text = normalize_plain_scientific_tokens(text)

    # 코드펜스 복원
    for idx, code in enumerate(fences):
        text = text.replace(f"@@CODE_FENCE_{idx}@@", code)

    return text


def _html_scripts_to_unicode_plain(html_text: str) -> str:
    """<sub>/<sup> HTML 태그를 순수 유니코드 첨자(또는 괄호 안전 표기)로 변환하고 태그를 제거한다."""
    s = _flatten_html_math_for_docx(html_text)

    def _rep_sub(m: re.Match[str]) -> str:
        inner = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if inner and all(ch in "0123456789+-=()aeoxhklmnpst" for ch in inner):
            return inner.translate(_UNICODE_SUB_MAP)
        return f"_{inner}" if len(inner) <= 3 else f"({inner})"

    def _rep_sup(m: re.Match[str]) -> str:
        inner = re.sub(r"<[^>]+>", "", m.group(1)).strip().replace("−", "-")
        if inner and all(ch in "0123456789+-=()ni" for ch in inner):
            return inner.translate(_UNICODE_SUP_MAP)
        return f"^{inner}" if len(inner) <= 3 else f"^({inner})"

    s = re.sub(r"<sub>([\s\S]*?)</sub>", _rep_sub, s, flags=re.I)
    s = re.sub(r"<sup>([\s\S]*?)</sup>", _rep_sup, s, flags=re.I)
    s = re.sub(r"</?(?:b|i|strong|em|span|div)(?:\s+[^>]*)?>", "", s, flags=re.I)
    return html.unescape(s)


def normalize_scientific_typography(text: str, *, target_format: str = "html") -> str:
    """모든 문서 포맷(html | blog_html | docx | plain)에서 수식·특수기호·원소기호·첨자를 누수 없이 일괄 정규화한다."""
    if not text:
        return ""
    fmt = (target_format or "html").strip().lower()
    converted = convert_markdown_math_to_html(text)
    if fmt == "html":
        return converted
    if fmt == "blog_html":
        # 네이버 스마트에디터 등 CSS flex 분수가 깨지는 웹/블로그용 안전 인라인 평탄화 (<sub>/<sup>/<b>/<i> 유지)
        s = converted
        def _rep_frac_blog(m: re.Match[str]) -> str:
            num = m.group(1).strip()
            den = m.group(2).strip()
            np = re.sub(r"<[^>]+>", "", num)
            dp = re.sub(r"<[^>]+>", "", den)
            ns = num if len(np) <= 6 and " " not in np else f"({num})"
            ds = den if len(dp) <= 6 and " " not in dp else f"({den})"
            return f"{ns} / {ds}"
        for _ in range(3):
            prev = s
            s = re.sub(r'<span class="m-frac"><span class="m-num">([\s\S]*?)</span><span class="m-den">([\s\S]*?)</span></span>', _rep_frac_blog, s)
            if s == prev:
                break
        s = re.sub(r'<span class="m-rxn"><span class="m-rxn-lbl">([\s\S]*?)</span><span class="m-rxn-arr">[^<]*</span></span>', r"—[\1]→", s)
        return s
    if fmt == "docx":
        return _flatten_html_math_for_docx(converted)
    if fmt == "plain":
        return _html_scripts_to_unicode_plain(converted)
    return converted


_RAW_LATEX_LEAK_RE = re.compile(
    r"(?:\\(?:boldsymbol|mathbf|mathrm|mathit|text|frac|dfrac|sqrt|sum|prod|int|alpha|beta|gamma|delta|Delta|mu|sigma|Sigma|theta|phi|lambda|rho|omega|Omega|ge|le|geq|leq|neq|approx|times|cdot|pm|in|hat|bar|tilde|vec|overline|ce|qquad|quad)\b)"
    r"|(?:\$\$[^$]+\$\$)"
    r"|(?:(?<!\$)\$(?!\$)[^$\n]*\\[a-zA-Z]+[^$\n]*\$)"
)


def detect_unformatted_math_leaks(text: str) -> list[str]:
    """최종 산출물(DOCX/HTML/블로그/평문)에 미변환 LaTeX 명령어나 원시 수식 기호가 남아 있는지 탐지한다."""
    if not text:
        return []
    # 코드 블록 제외
    clean = re.sub(r"```[\s\S]*?```", "", text)
    return [m.group(0) for m in _RAW_LATEX_LEAK_RE.finditer(clean)]


def math_typography_css(theme: str = "print") -> str:
    """인쇄 PDF(print) 및 다크 웹(web)용 수식·첨자·분수 CSS를 반환한다."""
    if theme == "web":
        return """
        sub, sup { font-size: 74%; line-height: 0; position: relative; vertical-align: baseline; }
        sup { top: -0.45em; }
        sub { bottom: -0.22em; }
        .math-block {
          margin: 14px 0;
          padding: 12px 16px;
          background: #0f172a;
          border: 1px solid rgba(56,189,248,0.28);
          border-left: 4px solid #38bdf8;
          border-radius: 8px;
          text-align: center;
          font-family: 'Cambria Math', 'Times New Roman', 'Malgun Gothic', serif;
          font-size: 14.5px;
          line-height: 1.9;
          color: #f8fafc;
          max-width: 100%;
          overflow-x: auto;
        }
        main.article p, main.article li { overflow-wrap: anywhere; word-break: break-word; }
        main.article svg { max-width: 100%; height: auto !important; display: block; }
        .math-cite { margin-left: 12px; font-family: 'Malgun Gothic', sans-serif; font-size: 12px; }
        .m-frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 4px; font-size: 92%; line-height: 1.25; }
        .m-frac .m-num { border-bottom: 1px solid currentColor; padding: 0 5px 2px; }
        .m-frac .m-den { padding: 2px 5px 0; }
        .m-rxn { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 4px; line-height: 1.05; }
        .m-rxn .m-rxn-lbl { font-size: 72%; margin-bottom: -2px; }
        .m-rxn .m-rxn-arr { font-size: 125%; }
        """
    return """
    sub, sup { font-size: 73%; line-height: 0; position: relative; vertical-align: baseline; }
    sup { top: -0.45em; }
    sub { bottom: -0.22em; }
    .math-block {
      margin: 9px 0 12px;
      padding: 8px 12px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 3.5px solid #1d4ed8;
      border-radius: 6px;
      text-align: center;
      font-family: 'Cambria Math', 'Times New Roman', 'Malgun Gothic', serif;
      font-size: 9.8pt;
      line-height: 1.75;
      color: #0f172a;
      page-break-inside: avoid;
      break-inside: avoid;
    }
    .math-cite { margin-left: 10px; font-family: 'Malgun Gothic', sans-serif; font-size: 8pt; }
    .m-frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 3px; font-size: 90%; line-height: 1.2; }
    .m-frac .m-num { border-bottom: 1px solid #0f172a; padding: 0 4px 1px; }
    .m-frac .m-den { padding: 1px 4px 0; }
    .m-rxn { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 3px; line-height: 1.05; }
    .m-rxn .m-rxn-lbl { font-size: 72%; margin-bottom: -2px; }
    .m-rxn .m-rxn-arr { font-size: 120%; }
    """


# ---------- Word (.docx) 리치텍스트(위첨자·아래첨자·볼드·이탤릭·분수) 렌더러 ----------
def _flatten_html_math_for_docx(text: str) -> str:
    """<span class="m-frac">, <span class="m-rxn"> 등 복합 HTML 수식 태그를 DOCX 친화적 인라인 태그로 평탄화한다."""
    s = text

    # <span class="m-frac"><span class="m-num">A</span><span class="m-den">B</span></span> → (A) / (B)
    def _rep_frac(m: re.Match[str]) -> str:
        num = m.group(1).strip()
        den = m.group(2).strip()
        n_clean = num if len(re.sub(r"<[^>]+>", "", num)) <= 6 and " " not in re.sub(r"<[^>]+>", "", num) else f"({num})"
        d_clean = den if len(re.sub(r"<[^>]+>", "", den)) <= 6 and " " not in re.sub(r"<[^>]+>", "", den) else f"({den})"
        return f"{n_clean} / {d_clean}"

    for _ in range(3):
        prev = s
        s = re.sub(
            r'<span class="m-frac"><span class="m-num">([\s\S]*?)</span><span class="m-den">([\s\S]*?)</span></span>',
            _rep_frac,
            s,
        )
        if s == prev:
            break

    # <span class="m-rxn"><span class="m-rxn-lbl">LBL</span><span class="m-rxn-arr">⟶</span></span> → —[LBL]→
    s = re.sub(
        r'<span class="m-rxn"><span class="m-rxn-lbl">([\s\S]*?)</span><span class="m-rxn-arr">[^<]*</span></span>',
        r"—[\1]→",
        s,
    )
    # <div class="math-block">, <span class="math-eq">, <span class="math-cite"> 래퍼 제거
    s = re.sub(r"</?(?:div|span)(?:\s+[^>]*)?>", "", s)
    # 마크다운 **bold** 및 *italic* 및 `code`를 임시 태그로 통일
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"`([^`\n]+?)`", r"\1", s)
    s = s.replace("&nbsp;", " ").replace("\\|", "|")
    return html.unescape(s)


_INLINE_TAG_RE = re.compile(r"(</?(?:sub|sup|b|i|strong|em)>)", re.I)


def add_rich_runs_to_docx_paragraph(
    paragraph: Any,
    text: str,
    *,
    font_size: float = 9.8,
    color_rgb: tuple[int, int, int] | None = None,
    base_bold: bool = False,
    font_name: str = "Malgun Gothic",
) -> None:
    """LaTeX($...$/$$...$$)·화학식·단위·HTML <sub>/<sup>/<b>/<i>·마크다운 서식을 모두 네이티브 Word Run으로 안전 렌더링한다."""
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    # 어떤 경로에서 원시 LaTeX나 평문 화학식이 들어와도 DOCX용으로 먼저 자동 정규화
    flat = normalize_scientific_typography(text, target_format="docx")
    tokens = _INLINE_TAG_RE.split(flat)

    bold_depth = 1 if base_bold else 0
    italic_depth = 0
    sub_depth = 0
    sup_depth = 0

    for tok in tokens:
        if not tok:
            continue
        low = tok.lower()
        if low in ("<b>", "<strong>"):
            bold_depth += 1
            continue
        if low in ("</b>", "</strong>"):
            bold_depth = max(1 if base_bold else 0, bold_depth - 1)
            continue
        if low in ("<i>", "<em>"):
            italic_depth += 1
            continue
        if low in ("</i>", "</em>"):
            italic_depth = max(0, italic_depth - 1)
            continue
        if low == "<sub>":
            sub_depth += 1
            continue
        if low == "</sub>":
            sub_depth = max(0, sub_depth - 1)
            continue
        if low == "<sup>":
            sup_depth += 1
            continue
        if low == "</sup>":
            sup_depth = max(0, sup_depth - 1)
            continue

        run = paragraph.add_run(tok)
        run.font.name = font_name
        run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
        run.font.size = Pt(font_size)
        run.bold = bold_depth > 0
        run.italic = italic_depth > 0
        if sub_depth > 0:
            run.font.subscript = True
        if sup_depth > 0:
            run.font.superscript = True
        if color_rgb is not None:
            run.font.color.rgb = RGBColor(*color_rgb)
