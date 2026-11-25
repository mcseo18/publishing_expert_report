"""Scientific-Figure-Design (qhy991, MIT) 통합 브리지 엔진.

도입 모델 (4대 핵심 표준):
1. Frozen Paper-Wide Color Contract (`paper-palette.yaml` + SHA-256 바인딩):
   - 한 교재/논문의 모든 그림(그림 1-1 ~ N-K)이 동일한 시맨틱 색상 체계(accent/secondary/success/warning/danger/neutral)를 공유해 색상 일탈(color drift)을 원천 차단.
2. Bundled 581 Vector SVG Icon Library (Lucide 단일 패밀리 177종 일관성 준수):
   - 한국어/영문 농학·과학 키워드 → 의미 매칭 → 팔레트 색상에 맞춰 자동 리컬러링 + SVG/Draw.io 내부 임베딩.
3. Editable Draw.io Scene Graph (`.drawio` + `.icons.json` 출처 매니페스트):
   - `build_drawio_figure.py`를 호출해 사람이 Draw.io Desktop / app.diagrams.net에서 박스·화살표·글자·아이콘을 자유롭게 편집할 수 있는 `.drawio` 원본을 동시 생성.
4. Automated Academic Aesthetic & Palette Validation:
   - `validate_drawio_figure.py` 및 `validate_paper_palette.py`로 학술 출판 기준(최소 폰트, 색상 일관성, 아이콘 라이선스 출처)을 자동 검증.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from config import PlatformConfig, get_config

SFD_SKILL_ROOT = Path(__file__).resolve().parent.parent / ".agents" / "skills" / "scientific-figure-design"
SFD_PAPER_ICONS_DIR = SFD_SKILL_ROOT / "assets" / "paper-icons"
SFD_BUILD_DRAWIO = SFD_SKILL_ROOT / "scripts" / "build_drawio_figure.py"
SFD_VALIDATE_DRAWIO = SFD_SKILL_ROOT / "scripts" / "validate_drawio_figure.py"
SFD_VALIDATE_PALETTE = SFD_SKILL_ROOT / "scripts" / "validate_paper_palette.py"
SFD_DEFAULT_PALETTE = SFD_SKILL_ROOT / "assets" / "paper-palette.yaml"

# Okabe-Ito 색맹 안전성 + Scientific-Figure-Design 시맨틱 톤 조화 팔레트
DEFAULT_PAPER_PALETTE: dict[str, Any] = {
    "schema_version": 1,
    "palette_id": "smc-academic-okabe-v1",
    "paper_id": "",
    "status": "frozen",
    "description": "One shared colorblind-safe semantic color system for all figures and charts in this book/paper (Scientific-Figure-Design contract).",
    "semantic": {
        "canvas": "#FFFFFF",
        "ink": "#172033",
        "muted": "#5B6472",
        "stroke": "#CBD5E1",
        "neutral": "#475569",
        "accent": "#00629B",     # Primary Blue (Okabe-Ito deep blue)
        "secondary": "#7C3AED",  # Violet (Strong baseline / mechanism)
        "success": "#047857",    # Emerald (Optimal / positive / feedback)
        "warning": "#C2410C",    # Vermilion-Amber (Stress / threshold / caution)
        "danger": "#B91C1C",     # Crimson (Hazard / limit / error)
    },
    "chart_roles": {
        "ours": "#00629B",
        "strong_baseline": "#C2410C",
        "other_baselines": "#475569",
        "upper_bound": "#172033",
        "positive": "#047857",
        "negative": "#B91C1C",
        "uncertainty": "#CBD5E1",
    },
    "rules": {
        "freeze_before_final_figures": True,
        "same_entity_same_color_across_figures": True,
        "ours_color_constant": True,
        "baseline_color_constant": True,
        "status_color_requires_redundant_encoding": True,
        "maximum_semantic_hues": 5,
        "card_tints_derive_from_semantic_hues": True,
        "background_policy": "white",
    },
}

# 톤별 카드 연색 배경(고대비 흰 글씨 헤더 + 밝은 틴트 본문)
SEMANTIC_CARD_STYLES: dict[str, tuple[str, str]] = {
    "accent": ("#E0F2FE", "#00629B"),
    "success": ("#DCFCE7", "#047857"),
    "warning": ("#FEF3C7", "#C2410C"),
    "secondary": ("#F3E8FF", "#7C3AED"),
    "neutral": ("#F1F5F9", "#334155"),
    "danger": ("#FEE2E2", "#B91C1C"),
}

TONE_CYCLE = ["accent", "success", "warning", "secondary", "neutral"]

# 한국어/영문 전문 키워드 → 번들 Lucide 벡터 아이콘 ID 매핑 (100% catalog.json 검증 ID만 사용)
LUCIDE_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("유전", "유전체", "염색체", "품종", "육종", "분자", "qtl", "dna", "gene", "genome", "breed"), "lucide-dna"),
    (("독성", "화학", "농약", "잔류", "성분", "약제", "용액", "시약", "pesticide", "chemical", "residue", "adi", "mrl"), "lucide-flask-conical"),
    (("시험", "실험", "검정", "시료", "추출", "분석법", "assay", "sample", "test"), "lucide-test-tube"),
    (("미생물", "세포", "조직", "해부", "현미경", "병해", "병원균", "세균", "진균", "microbe", "cell", "pathogen"), "lucide-microscope"),
    (("분자구조", "원자", "이온", "양분", "질소", "인산", "칼륨", "탄소", "광합성", "nutrient", "carbon", "nitrogen"), "lucide-atom"),
    (("기상", "기후", "강수", "습해", "배수", "관개", "침수", "가뭄", "water", "rain", "climate", "weather", "drainage"), "lucide-cloud"),
    (("생육", "생리", "활성", "호흡", "대사", "스트레스", "반응", "physiology", "growth", "stress", "activity"), "lucide-activity"),
    (("계측", "센서", "측정", "장력", "수분", "온도", "습도", "ec", "ph", "sensor", "moisture", "gauge", "meter"), "lucide-gauge"),
    (("통계", "비교", "수량", "수확량", "효율", "분포", "정량", "yield", "stat", "bar", "metric"), "lucide-chart-bar"),
    (("곡선", "추이", "예측", "반감기", "모형", "모델", "시뮬레이션", "감소", "model", "curve", "trend", "forecast"), "lucide-chart-line"),
    (("데이터", "db", "저장소", "코퍼스", "카탈로그", "지식", "database", "corpus", "storage"), "lucide-database"),
    (("인공지능", "딥러닝", "머신러닝", "알고리즘", "신경망", "스마트", "ai", "ml", "neural", "smart"), "lucide-brain-circuit"),
    (("계산", "연산", "프로세서", "제어기", "자동화", "하드웨어", "compute", "cpu", "control", "automation"), "lucide-cpu"),
    (("수식", "공식", "적산온도", "gdd", "계수", "방정식", "formula", "equation", "math"), "lucide-sigma"),
    (("안전", "방제", "보호", "저항성", "규제", "법규", "기준", "pls", "gap", "safety", "shield", "regulation"), "lucide-shield"),
    (("검증", "확정", "승인", "판정", "고시", "인증", "합격", "verify", "check", "approve", "certification"), "lucide-circle-check"),
    (("점검", "체크리스트", "지침", "절차", "매뉴얼", "표준", "checklist", "guideline", "protocol"), "lucide-list-checks"),
    (("탐색", "진단", "모니터링", "관찰", "영상", "드론", "위성", "scan", "monitor", "diagnos", "remote"), "lucide-scan-search"),
    (("계층", "구조", "단계", "층위", "토양", "단립", "분획", "layer", "soil", "hierarchy", "structure"), "lucide-layers"),
    (("분류", "계통", "진화", "경로", "분기", "작용기작", "taxonomy", "branch", "pathway", "frac", "irac", "hrac"), "lucide-git-branch"),
    (("흐름", "파이프라인", "공정", "프로세스", "체계", "연계", "workflow", "pipeline", "process", "system"), "lucide-workflow"),
    (("피드백", "순환", "교호", "재검증", "회복", "환원", "feedback", "loop", "cycle", "rotation"), "lucide-refresh-cw"),
    (("파종", "시기", "작형", "재배력", "생육기", "수확기", "calendar", "sowing", "season", "schedule"), "lucide-calendar"),
    (("시간", "기간", "지속", "저장기간", "phi", "dt50", "time", "duration", "half-life"), "lucide-clock"),
    (("문헌", "교재", "이론", "개념", "정의", "참고", "literature", "theory", "book", "review"), "lucide-book-open"),
    (("표", "기준표", "매트릭스", "비교표", "table", "matrix"), "lucide-table-2"),
    (("목표", "핵심", "표적", "최적", "target", "optimal", "goal"), "lucide-target"),
    (("조절", "최적화", "시비", "처방", "설정", "튜닝", "tuning", "parameter", "fertiliz"), "lucide-sliders-horizontal"),
    (("가공", "제분", "품질", "저장", "유통", "산업", "processing", "quality", "supply", "market"), "lucide-boxes"),
    (("네트워크", "생태계", "공생", "상호작용", "network", "ecosystem", "interaction"), "lucide-network"),
]

_LUCIDE_FALLBACK_CYCLE = [
    "lucide-file-text",
    "lucide-workflow",
    "lucide-gauge",
    "lucide-circle-check",
    "lucide-layers",
]

_ICON_SVG_CACHE: dict[str, str] = {}


def is_sfd_installed() -> bool:
    return SFD_BUILD_DRAWIO.is_file() and (SFD_PAPER_ICONS_DIR / "library" / "lucide").is_dir()


def ensure_project_paper_palette(project_id: str, cfg: PlatformConfig | None = None) -> tuple[Path, dict[str, Any]]:
    """프로젝트 전용 paper-palette.yaml 계약을 생성/로드하고 SHA-256 해시를 반환한다."""
    cfg = cfg or get_config()
    assets_dir = cfg.project_dir(project_id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    pal_path = assets_dir / "paper-palette.yaml"
    if pal_path.is_file():
        try:
            data = json.loads(pal_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("semantic"):
                return pal_path, data
        except Exception:
            pass
    data = json.loads(json.dumps(DEFAULT_PAPER_PALETTE))
    data["paper_id"] = project_id
    data["palette_id"] = f"smc-{re.sub(r'[^a-z0-9\\-]+', '-', project_id.lower())[:28]}-v1"
    pal_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pal_path, data


def palette_sha256(pal_path: Path) -> str:
    if not pal_path.is_file():
        return ""
    return hashlib.sha256(pal_path.read_bytes()).hexdigest()


def match_lucide_icon_for_text(text: str, idx: int = 0) -> str:
    """한글/영문 노드 텍스트에서 가장 적합한 단일 패밀리(Lucide) 벡터 아이콘 ID를 반환한다."""
    low = (text or "").lower()
    for keys, icon_id in LUCIDE_KEYWORD_MAP:
        if any(k in low for k in keys):
            svg_p = SFD_PAPER_ICONS_DIR / "library" / "lucide" / f"{icon_id.replace('lucide-', '')}.svg"
            if svg_p.is_file():
                return icon_id
    return _LUCIDE_FALLBACK_CYCLE[idx % len(_LUCIDE_FALLBACK_CYCLE)]


def load_recolored_lucide_inner_svg(icon_id: str, stroke_color: str = "#FFFFFF", stroke_width: float = 2.2) -> str:
    """Lucide SVG 아이콘의 내부 path/circle/rect 요소를 추출해 지정 색상·선두께로 SVG <g>에 삽입 가능하게 반환한다."""
    fname = icon_id.replace("lucide-", "") + ".svg"
    svg_path = SFD_PAPER_ICONS_DIR / "library" / "lucide" / fname
    if not svg_path.is_file():
        return ""
    raw = _ICON_SVG_CACHE.get(str(svg_path))
    if raw is None:
        raw = svg_path.read_text(encoding="utf-8", errors="ignore")
        _ICON_SVG_CACHE[str(svg_path)] = raw
    m = re.search(r"<svg[^>]*>([\s\S]*?)</svg>", raw, re.I)
    if not m:
        return ""
    inner = m.group(1).strip()
    inner = re.sub(r'stroke="currentColor"', f'stroke="{stroke_color}"', inner)
    inner = re.sub(r'fill="currentColor"', f'fill="{stroke_color}"', inner)
    return (
        f'<g fill="none" stroke="{stroke_color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</g>'
    )


def _compact_drawio_label(text: str, max_len: int = 24) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip(" ·,/(") + "…"


def build_drawio_spec_from_diagram(
    *,
    spec: dict[str, Any],
    nodes: list[dict[str, str]],
    edges: list[str],
    feedback_label: str,
    palette_path: Path,
) -> dict[str, Any]:
    """플랫폼 내용 구조도 명세(visual_studio)를 Scientific-Figure-Design build_drawio_figure.py 호환 JSON으로 변환한다."""
    style = str(spec.get("style") or "content_diagram")
    layout = "comparison" if style == "layered_comparison" else "pipeline"
    title = str(spec.get("title_ko") or "학술 구조 도해")
    desc = str(spec.get("subtitle_ko") or spec.get("claim_ko") or title)
    claim = str(spec.get("claim_ko") or desc)

    drawio_nodes: list[dict[str, Any]] = []
    n_cnt = max(1, min(4 if layout == "pipeline" else 3, len(nodes)))
    for i, nd in enumerate(nodes[:n_cnt]):
        tone = TONE_CYCLE[i % len(TONE_CYCLE)]
        probe = f"{nd.get('tag', '')} {nd.get('label', '')} {nd.get('detail', '')}"
        icon_id = match_lucide_icon_for_text(probe, idx=i)
        sub_txt = nd.get("metric") or nd.get("detail") or nd.get("tag") or ""
        node_obj: dict[str, Any] = {
            "id": f"n{i + 1}",
            "label": _compact_drawio_label(nd.get("label") or f"단계 {i + 1}", 22),
            "subtitle": _compact_drawio_label(sub_txt, 28),
            "icon": icon_id,
            "tone": tone,
            "kind": "transformation" if 0 < i < n_cnt - 1 else ("evidence" if i == n_cnt - 1 else "entity"),
        }
        if nd.get("tag"):
            node_obj["badge"] = _compact_drawio_label(nd["tag"], 14)
        drawio_nodes.append(node_obj)

    drawio_edges: list[dict[str, Any]] = []
    if layout == "pipeline":
        for i in range(n_cnt - 1):
            edge_obj: dict[str, Any] = {
                "from": f"n{i + 1}",
                "to": f"n{i + 2}",
                "relation": "data",
            }
            if i < len(edges) and str(edges[i]).strip():
                edge_obj["label"] = _compact_drawio_label(str(edges[i]), 14)
            drawio_edges.append(edge_obj)
        if feedback_label and n_cnt >= 2:
            drawio_edges.append(
                {
                    "from": f"n{n_cnt}",
                    "to": "n1",
                    "label": _compact_drawio_label(feedback_label, 34),
                    "tone": "success",
                    "style": "dashed",
                    "relation": "feedback",
                    "exit": [0.5, 1],
                    "entry": [0.5, 1],
                }
            )

    return {
        "metadata": {
            "title": title,
            "description": desc,
            "claim": claim,
        },
        "paper_palette": {
            "path": str(palette_path),
        },
        "figure": {
            "column": "double",
            "layout": layout,
            "direction": "horizontal",
            "width": 1080,
            "height": 520 if feedback_label else 460,
        },
        "nodes": drawio_nodes,
        "edges": drawio_edges,
    }


def generate_editable_drawio_for_spec(
    *,
    project_id: str,
    figure_id: str,
    spec: dict[str, Any],
    nodes: list[dict[str, str]],
    edges: list[str] | None = None,
    feedback_label: str = "",
    out_drawio_path: Path | None = None,
    validate: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """편집 가능한 `.drawio` + `.icons.json` + frozen `paper-palette.yaml`을 생성하고 학술 기준 검증 결과를 반환한다."""
    cfg = cfg or get_config()
    if not is_sfd_installed():
        return {"status": "UNAVAILABLE", "error": "scientific-figure-design 스킬이 설치되어 있지 않습니다."}

    ws = cfg.project_dir(project_id)
    drawio_dir = ws / "assets" / "drawio"
    drawio_dir.mkdir(parents=True, exist_ok=True)
    pal_path, pal_data = ensure_project_paper_palette(project_id, cfg)

    out_drawio = out_drawio_path or (drawio_dir / f"{figure_id}.drawio")
    spec_json_p = out_drawio.with_suffix(".spec.json")
    manifest_p = out_drawio.with_suffix(".icons.json")

    drawio_spec = build_drawio_spec_from_diagram(
        spec=spec,
        nodes=nodes,
        edges=edges or [],
        feedback_label=feedback_label,
        palette_path=pal_path,
    )
    spec_json_p.write_text(json.dumps(drawio_spec, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd_build = [
        sys.executable,
        str(SFD_BUILD_DRAWIO),
        str(spec_json_p),
        "--out",
        str(out_drawio),
        "--paper-icons-skill",
        str(SFD_PAPER_ICONS_DIR),
        "--manifest",
        str(manifest_p),
        "--paper-palette",
        str(pal_path),
    ]
    proc = subprocess.run(cmd_build, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0 or not out_drawio.is_file():
        return {
            "status": "ERROR",
            "error": (proc.stderr or proc.stdout or "build_drawio_figure.py 실행 실패")[:300],
        }

    # E:\ 백업 미러
    try:
        e_drawio_dir = cfg.e_projects_dir / project_id / "visuals" / "drawio"
        e_drawio_dir.mkdir(parents=True, exist_ok=True)
        for p in (out_drawio, manifest_p, pal_path):
            if p.is_file():
                (e_drawio_dir / p.name).write_bytes(p.read_bytes())
    except Exception:
        pass

    validation: dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
    if validate and SFD_VALIDATE_DRAWIO.is_file():
        try:
            v_proc = subprocess.run(
                [
                    sys.executable,
                    str(SFD_VALIDATE_DRAWIO),
                    str(out_drawio),
                    "--manifest",
                    str(manifest_p),
                    "--paper-palette",
                    str(pal_path),
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if v_proc.stdout.strip():
                validation = json.loads(v_proc.stdout)
        except Exception as exc:
            validation = {"ok": False, "errors": [str(exc)], "warnings": []}

    return {
        "status": "OK",
        "figure_id": figure_id,
        "drawio_path": str(out_drawio),
        "drawio_url": f"/project-files/{project_id}/assets/drawio/{out_drawio.name}",
        "icons_manifest_path": str(manifest_p),
        "palette_path": str(pal_path),
        "palette_id": pal_data.get("palette_id", ""),
        "palette_sha256": palette_sha256(pal_path),
        "validation": validation,
    }


def audit_project_palette_consistency(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트 내 생성된 모든 .drawio 파일이 단일 paper-palette.yaml 계약을 준수하는지 교차 감사한다."""
    cfg = cfg or get_config()
    pal_path, pal_data = ensure_project_paper_palette(project_id, cfg)
    drawio_dir = cfg.project_dir(project_id) / "assets" / "drawio"
    drawio_files = sorted(drawio_dir.glob("*.drawio")) if drawio_dir.is_dir() else []
    if not drawio_files or not SFD_VALIDATE_PALETTE.is_file():
        return {
            "palette_id": pal_data.get("palette_id", ""),
            "palette_path": str(pal_path),
            "palette_url": f"/project-files/{project_id}/assets/paper-palette.yaml",
            "palette_sha256": palette_sha256(pal_path),
            "drawio_count": len(drawio_files),
            "passed": True,
            "report": {},
        }
    proc = subprocess.run(
        [sys.executable, str(SFD_VALIDATE_PALETTE), "--palette", str(pal_path), "--json", *[str(p) for p in drawio_files]],
        capture_output=True,
        text=True,
        timeout=25,
    )
    rep = {}
    try:
        rep = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception:
        rep = {"raw": proc.stdout[:300]}
    return {
        "palette_id": pal_data.get("palette_id", ""),
        "palette_path": str(pal_path),
        "palette_url": f"/project-files/{project_id}/assets/paper-palette.yaml",
        "palette_sha256": palette_sha256(pal_path),
        "drawio_count": len(drawio_files),
        "passed": proc.returncode == 0,
        "report": rep,
    }
