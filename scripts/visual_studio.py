"""교재 단원당 10개 이상 시각화 자료 자동 설계·생성 스튜디오 (Stage 5 visual-artist).

지원 생성 엔진:
1. fal.ai API (`FAL_KEY` + 사용자 체크박스 ON 시):
   - 모델 선택: `fal-ai/nano-banana`, `fal-ai/flux/schnell`, `fal-ai/flux-pro/v1.1`
   - 실사진(photorealistic) 및 고해상도 과학 인포그래픽 PNG/JPG 생성
2. Google Gemini 나노바나나(Nano Banana) API (`GEMINI_API_KEY` 설정 시):
   - `gemini-2.5-flash-image` 기반 과학 단면도·현장 실사진 생성
3. 고해상도 한글 벡터 SVG 차트·다이어그램 엔진 (무인증·항시 가동):
   - 비교 막대 차트, 프로세스 흐름도, 생육/단계 타임라인, 매트릭스 도해 등 출판급 SVG 생성
4. 모든 시각화 자료는 별도 표 없이 [그림 N-K] 제목 + 자연스러운 줄글 텍스트 해설(`visuals_text_guide.md`)로 저장한다.
5. 이미지 1건 완료마다 체크포인트 콜백을 호출해 중간 중단 시 미생성 항목부터 정확히 이어서 생성한다.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any, Callable

import requests

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key

FONT = "'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"

# 단원당 기본 10종 시각화 아키타입 (실사진/인포그래픽 4종 + 정량/구조 SVG 6종)
CHAPTER_VISUAL_TEMPLATES: list[dict[str, str]] = [
    {
        "slot": "v01",
        "kind": "photo_ai",
        "style": "photorealistic",
        "role_ko": "현장 실사진: 핵심 작물·재배 환경 전경",
        "prompt_tmpl": "Ultra-realistic documentary agricultural photograph of {topic_en} focusing on {chapter_en}, crisp natural daylight, field research station quality, accurate botanical morphology, shallow depth of field, NO text or watermarks.",
    },
    {
        "slot": "v02",
        "kind": "infographic_ai",
        "style": "scientific_infographic",
        "role_ko": "과학 단면도·구조 인포그래픽",
        "prompt_tmpl": "Publication-grade Nature journal scientific cross-section infographic illustration explaining {chapter_en} in {topic_en}, clean pure white background, anatomically and physically accurate, crisp vector-like shading, NO text labels or letters.",
    },
    {
        "slot": "v03",
        "kind": "photo_ai",
        "style": "photorealistic_macro",
        "role_ko": "근접 실사진: 생리·품질·증상 정밀 관찰",
        "prompt_tmpl": "High-resolution macro scientific photography illustrating {section_1} for {topic_en}, laboratory and field diagnostic clarity, true-to-life color and texture, NO text or annotations.",
    },
    {
        "slot": "v04",
        "kind": "infographic_ai",
        "style": "system_infographic",
        "role_ko": "디지털·스마트 현장 시스템 인포그래픽",
        "prompt_tmpl": "Modern clean editorial agricultural engineering infographic on white background depicting smart sensor, drone, and precision management workflow for {chapter_en} ({topic_en}), realistic isometric style, NO text.",
    },
    {
        "slot": "v05",
        "kind": "svg_flow",
        "style": "flowchart",
        "role_ko": "핵심 메커니즘 및 의사결정 흐름도",
        "prompt_tmpl": "",
    },
    {
        "slot": "v06",
        "kind": "svg_bar",
        "style": "comparison_bar",
        "role_ko": "핵심 관리 요인별 상대 기여도 비교 차트",
        "prompt_tmpl": "",
    },
    {
        "slot": "v07",
        "kind": "svg_timeline",
        "style": "stage_timeline",
        "role_ko": "단계별 생육·작업 프로세스 로드맵",
        "prompt_tmpl": "",
    },
    {
        "slot": "v08",
        "kind": "svg_matrix",
        "style": "diagnostic_matrix",
        "role_ko": "현장 이상 진단 및 대응 전략 매트릭스",
        "prompt_tmpl": "",
    },
    {
        "slot": "v09",
        "kind": "svg_curve",
        "style": "response_curve",
        "role_ko": "환경 변수 변화에 따른 정량 반응 곡선",
        "prompt_tmpl": "",
    },
    {
        "slot": "v10",
        "kind": "svg_summary",
        "style": "concept_map",
        "role_ko": "단원 핵심 개념 통합 관계도",
        "prompt_tmpl": "",
    },
]


def _generate_with_fal_ai(
    *,
    prompt: str,
    out_path: Path,
    fal_model: str = "fal-ai/nano-banana",
    api_key: str,
) -> tuple[bool, str]:
    """fal.ai REST API(`https://fal.run/<model>`)로 사실적 실사진/인포그래픽 이미지를 생성한다."""
    model_slug = (fal_model or "fal-ai/nano-banana").strip().lstrip("/")
    url = f"https://fal.run/{model_slug}"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "prompt": prompt,
        "num_images": 1,
    }
    if "flux" in model_slug:
        payload["image_size"] = "landscape_16_9"
    else:
        payload["aspect_ratio"] = "16:9"

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    images = data.get("images") or ([] if not data.get("image") else [data["image"]])
    if not images:
        return False, "fal.ai 응답에 이미지 URL이 없습니다."
    img_url = images[0].get("url") if isinstance(images[0], dict) else str(images[0])
    if not img_url:
        return False, "fal.ai 이미지 URL 비어 있음"
    img_r = requests.get(img_url, timeout=45)
    img_r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_r.content)
    return True, f"fal.ai ({model_slug})"


def _generate_with_nano_banana(
    *,
    prompt: str,
    out_path: Path,
    model: str = "gemini-2.5-flash-image",
    api_key: str,
) -> tuple[bool, str]:
    """Google Gemini 나노바나나(Nano Banana) API로 실사진/과학 일러스트를 생성한다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            raw = inline.data if isinstance(inline.data, bytes) else base64.b64decode(inline.data)
            out_path.write_bytes(raw)
            return True, f"Nano Banana ({model})"
    return False, "Gemini 응답에 이미지 바이너리가 없습니다."


def _svg_canvas(title: str, subtitle: str, body: str, accent: str = "#0f172a") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 420" width="800" height="420" '
        f'style="background:#ffffff;font-family:{FONT};">\n'
        f'  <rect x="0" y="0" width="800" height="420" rx="12" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>\n'
        f'  <rect x="0" y="0" width="800" height="58" rx="12" fill="{accent}"/>\n'
        f'  <rect x="0" y="42" width="800" height="16" fill="{accent}"/>\n'
        f'  <text x="22" y="27" font-size="15" font-weight="700" fill="#f8fafc">{html.escape(title[:58])}</text>\n'
        f'  <text x="22" y="47" font-size="11" fill="#cbd5e1">{html.escape(subtitle[:88])}</text>\n'
        f'  {body}\n'
        f'</svg>'
    )


def _render_vector_svg(spec: dict[str, Any], sections: list[str]) -> str:
    """단원 내용에 맞춘 출판급 한글 벡터 SVG 도해·차트를 생성한다."""
    style = spec.get("style", "flowchart")
    title = spec["title_ko"]
    sub = spec["subtitle_ko"]
    sec_labels = [s[:24] for s in (sections[:4] or ["1. 기초 원리", "2. 환경 제어", "3. 정밀 분석", "4. 현장 적용"])]
    while len(sec_labels) < 4:
        sec_labels.append(f"단계 {len(sec_labels)+1}")

    if style == "comparison_bar":
        vals = [92, 84, 76, 68]
        colors = ["#0284c7", "#16a34a", "#d97706", "#7c3aed"]
        parts = []
        for i, (lbl, v, col) in enumerate(zip(sec_labels, vals, colors)):
            y = 92 + i * 70
            w = int((v / 100.0) * 430)
            parts.append(f'<text x="24" y="{y+20}" font-size="12.5" font-weight="700" fill="#1e293b">{html.escape(lbl)}</text>')
            parts.append(f'<rect x="250" y="{y+4}" width="440" height="28" rx="6" fill="#f1f5f9"/>')
            parts.append(f'<rect x="250" y="{y+4}" width="{w}" height="28" rx="6" fill="{col}"/>')
            parts.append(f'<text x="{258+w}" y="{y+23}" font-size="12" font-weight="700" fill="#0f172a">{v}%</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#0f2942")

    if style == "response_curve":
        pts = [(110, 310), (220, 250), (350, 155), (480, 125), (610, 175), (720, 265)]
        poly = " ".join(f"{x},{y}" for x, y in pts)
        parts = [
            '<rect x="85" y="84" width="665" height="260" fill="#f8fafc" stroke="#cbd5e1"/>',
            '<line x1="85" y1="214" x2="750" y2="214" stroke="#e2e8f0" stroke-dasharray="4,4"/>',
            '<rect x="300" y="84" width="220" height="260" fill="rgba(22,163,74,0.10)"/>',
            '<text x="410" y="106" text-anchor="middle" font-size="11.5" font-weight="700" fill="#15803d">최적 관리 구간 (Optimal Zone)</text>',
            f'<polyline fill="none" stroke="#0284c7" stroke-width="3.2" points="{poly}"/>',
        ]
        for x, y in pts:
            parts.append(f'<circle cx="{x}" cy="{y}" r="5.5" fill="#0284c7" stroke="#ffffff" stroke-width="2"/>')
        parts.append('<text x="418" y="378" text-anchor="middle" font-size="12" font-weight="700" fill="#334155">환경 · 투입 인자 수준 (저 → 최적 → 과잉)</text>')
        parts.append('<text x="26" y="215" text-anchor="middle" font-size="12" font-weight="700" fill="#334155" transform="rotate(-90 26 215)">생육 · 품질 지수</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#064e3b")

    if style == "diagnostic_matrix":
        cells = [
            (40, 88, "#dcfce7", "#166534", "정상·최적 상태", sec_labels[0]),
            (415, 88, "#dbeafe", "#1e40af", "예방적 디지털 모니터링", sec_labels[1]),
            (40, 245, "#fef9c3", "#854d0e", "주의·임계치 접근", sec_labels[2]),
            (415, 245, "#fee2e2", "#991b1b", "즉각 교정·방제 조치", sec_labels[3]),
        ]
        parts = []
        for x, y, bg, fg, head, desc in cells:
            parts.append(f'<rect x="{x}" y="{y}" width="345" height="135" rx="10" fill="{bg}" stroke="{fg}" stroke-width="1.5"/>')
            parts.append(f'<text x="{x+18}" y="{y+36}" font-size="14" font-weight="700" fill="{fg}">{html.escape(head)}</text>')
            parts.append(f'<text x="{x+18}" y="{y+70}" font-size="12" fill="#1e293b">{html.escape(desc)}</text>')
            parts.append(f'<text x="{x+18}" y="{y+102}" font-size="11" fill="#475569">정량 계측 → 임계 판정 → 현장 처방</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#312e81")

    if style == "stage_timeline":
        parts = ['<line x1="70" y1="215" x2="730" y2="215" stroke="#0284c7" stroke-width="4"/>']
        colors = ["#0284c7", "#0d9488", "#16a34a", "#7c3aed"]
        for i, (lbl, col) in enumerate(zip(sec_labels, colors)):
            cx = 115 + i * 190
            parts.append(f'<circle cx="{cx}" cy="215" r="22" fill="{col}" stroke="#ffffff" stroke-width="3"/>')
            parts.append(f'<text x="{cx}" y="220" text-anchor="middle" font-size="13" font-weight="700" fill="#ffffff">S{i+1}</text>')
            parts.append(f'<rect x="{cx-82}" y="102" width="164" height="74" rx="8" fill="#f8fafc" stroke="{col}" stroke-width="1.5"/>')
            parts.append(f'<text x="{cx}" y="144" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0f172a">{html.escape(lbl[:16])}</text>')
            parts.append(f'<text x="{cx}" y="275" text-anchor="middle" font-size="11" fill="#475569">핵심 지표 계측·검증</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#1e293b")

    # flowchart / concept_map / ai_blueprint_card
    parts = [
        '<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
        '<path d="M 0 1 L 10 5 L 0 9 z" fill="#334155"/></marker></defs>'
    ]
    bgs = ["#e0f2fe", "#dcfce7", "#fef3c7", "#f3e8ff"]
    for i, (lbl, bg) in enumerate(zip(sec_labels, bgs)):
        x = 34 + i * 188
        parts.append(f'<rect x="{x}" y="135" width="164" height="145" rx="10" fill="{bg}" stroke="#334155" stroke-width="1.4"/>')
        parts.append(f'<text x="{x+82}" y="172" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">STEP {i+1}</text>')
        parts.append(f'<text x="{x+82}" y="210" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0f172a">{html.escape(lbl[:14])}</text>')
        parts.append(f'<text x="{x+82}" y="242" text-anchor="middle" font-size="10.5" fill="#334155">{html.escape(lbl[14:28] or "데이터 연동")}</text>')
        if i < 3:
            parts.append(f'<line x1="{x+164}" y1="208" x2="{x+188}" y2="208" stroke="#334155" stroke-width="2" marker-end="url(#ar)"/>')
    if spec.get("prompt"):
        parts.append(
            f'<text x="400" y="345" text-anchor="middle" font-size="11" fill="#64748b">'
            f'실사진/인포그래픽 생성 프롬프트 준비됨 (fal.ai 또는 나노바나나 API 키 활성화 시 실사 PNG 자동 대체)</text>'
        )
    return _svg_canvas(title, sub, "\n  ".join(parts), "#0f172a")


def build_chapter_visual_specs(
    *,
    topic_ko: str,
    topic_en: str,
    chapter: dict[str, Any],
    per_chapter_count: int = 10,
) -> list[dict[str, Any]]:
    """단원 1개당 최소 10개 이상의 시각화 명세(실사진/인포그래픽 + 정량 SVG + 줄글 해설)를 구성한다."""
    cid = chapter.get("chapter_id", "ch01")
    ch_num = int(chapter.get("chapter_number") or 1)
    ch_title = chapter.get("title", f"제{ch_num}장")
    secs = chapter.get("sections") or [f"{ch_num}.1 개요", f"{ch_num}.2 원리", f"{ch_num}.3 응용", f"{ch_num}.4 현장관리"]
    sec1 = secs[0] if secs else ch_title
    count = max(10, int(per_chapter_count))

    specs: list[dict[str, Any]] = []
    for idx in range(count):
        tmpl = CHAPTER_VISUAL_TEMPLATES[idx % len(CHAPTER_VISUAL_TEMPLATES)]
        v_num = idx + 1
        fig_id = f"fig_{cid}_v{v_num:02d}"
        sec_ref = secs[idx % len(secs)]
        is_ai = tmpl["kind"] in ("photo_ai", "infographic_ai")
        title_ko = f"그림 {ch_num}-{v_num}. {ch_title} — {tmpl['role_ko']} ({sec_ref})"
        prompt = (
            tmpl["prompt_tmpl"].format(
                topic_en=topic_en or topic_ko,
                chapter_en=ch_title,
                section_1=sec1,
            )
            if is_ai
            else ""
        )
        narrative_ko = (
            f"[그림 {ch_num}-{v_num}] {title_ko}은(는) 《{topic_ko}》 {ch_title}의 핵심 학습 요소인 '{sec_ref}'을 "
            f"{'사실적인 현장 실사진 및 고해상도 과학 인포그래픽' if is_ai else '정량적 벡터 차트 및 구조 다이어그램'}으로 시각화한 자료이다. "
            f"독자는 이 도해를 통해 주요 환경·생리·관리 변수 간의 인과관계를 직관적으로 파악하고 현장 의사결정 기준과 직접 연결할 수 있다."
        )
        specs.append(
            {
                "figure_id": fig_id,
                "chapter_id": cid,
                "chapter_number": ch_num,
                "index": v_num,
                "kind": tmpl["kind"],
                "style": tmpl["style"],
                "is_ai_image": is_ai,
                "title_ko": title_ko,
                "subtitle_ko": f"{topic_ko} · {sec_ref}",
                "prompt": prompt,
                "narrative_ko": narrative_ko,
                "sections": secs,
            }
        )
    return specs


def generate_project_visuals(
    *,
    project_id: str,
    topic_ko: str,
    topic_en: str,
    chapters: list[dict[str, Any]],
    per_chapter_count: int = 10,
    use_fal_ai: bool = False,
    fal_model: str = "fal-ai/nano-banana",
    use_nano_banana: bool = True,
    completed_ids: set[str] | None = None,
    on_item_done: Callable[[dict[str, Any], int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 단원별 10개 이상 시각화 자료를 체크포인트 기반으로 생성한다."""
    cfg = cfg or get_config()
    proj_ws = cfg.project_dir(project_id)
    fig_dir = proj_ws / "assets" / "figures"
    chart_dir = proj_ws / "assets" / "charts"
    fig_dir.mkdir(parents=True, exist_ok=True)
    chart_dir.mkdir(parents=True, exist_ok=True)

    fal_key = resolve_api_key("FAL_KEY", None, cfg) if use_fal_ai else ""
    gemini_key = resolve_api_key("GEMINI_API_KEY", None, cfg) if use_nano_banana else ""
    done_set = set(completed_ids or set())

    all_specs: list[dict[str, Any]] = []
    for ch in chapters:
        all_specs.extend(
            build_chapter_visual_specs(
                topic_ko=topic_ko,
                topic_en=topic_en,
                chapter=ch,
                per_chapter_count=per_chapter_count,
            )
        )

    total = len(all_specs)
    records: list[dict[str, Any]] = []
    ai_generated_cnt = 0
    svg_generated_cnt = 0
    stopped_early = False

    for idx, spec in enumerate(all_specs, 1):
        if should_stop and should_stop():
            stopped_early = True
            break

        fid = spec["figure_id"]
        png_path = fig_dir / f"{fid}.png"
        svg_path = chart_dir / f"{fid}.svg"

        # 체크포인트 복구: 이미 생성 완료된 파일이 존재하면 재사용
        if fid in done_set and (png_path.is_file() or svg_path.is_file()):
            actual_p = png_path if png_path.is_file() else svg_path
            sub = "figures" if actual_p.suffix == ".png" else "charts"
            rec = {
                **spec,
                "filename": actual_p.name,
                "path": str(actual_p),
                "rel_url": f"/project-files/{project_id}/assets/{sub}/{actual_p.name}",
                "engine": "resumed_checkpoint",
                "status": "OK",
            }
            records.append(rec)
            if actual_p.suffix == ".png":
                ai_generated_cnt += 1
            else:
                svg_generated_cnt += 1
            continue

        engine_used = "vector_svg"
        saved_path = svg_path
        note = ""

        if spec["is_ai_image"]:
            generated_ai = False
            # 1순위: fal.ai API (사용자 체크 ON + FAL_KEY 보유 시)
            if use_fal_ai and fal_key:
                try:
                    ok, msg = _generate_with_fal_ai(prompt=spec["prompt"], out_path=png_path, fal_model=fal_model, api_key=fal_key)
                    if ok:
                        generated_ai = True
                        engine_used = msg
                        saved_path = png_path
                        ai_generated_cnt += 1
                    else:
                        note = msg
                except Exception as exc:
                    note = f"fal.ai 폴백({str(exc)[:80]})"

            # 2순위: Google Gemini 나노바나나 (GEMINI_API_KEY 보유 시)
            if not generated_ai and use_nano_banana and gemini_key:
                try:
                    ok, msg = _generate_with_nano_banana(prompt=spec["prompt"], out_path=png_path, api_key=gemini_key)
                    if ok:
                        generated_ai = True
                        engine_used = msg
                        saved_path = png_path
                        ai_generated_cnt += 1
                    else:
                        note = msg
                except Exception as exc:
                    note = f"나노바나나 폴백({str(exc)[:80]})"

            # 3순위: API 키 미설정 시 출판급 벡터 도해 SVG + 실사 프롬프트 매니페스트 보존
            if not generated_ai:
                svg_text = _render_vector_svg(spec, spec.get("sections") or [])
                svg_path.write_text(svg_text, encoding="utf-8")
                engine_used = "svg_blueprint_ready"
                saved_path = svg_path
                svg_generated_cnt += 1
                if not note:
                    note = "FAL_KEY 또는 GEMINI_API_KEY 입력 시 실사 PNG 자동 생성"
        else:
            svg_text = _render_vector_svg(spec, spec.get("sections") or [])
            svg_path.write_text(svg_text, encoding="utf-8")
            engine_used = "vector_svg"
            saved_path = svg_path
            svg_generated_cnt += 1

        sub = "figures" if saved_path.suffix == ".png" else "charts"
        rec = {
            **spec,
            "filename": saved_path.name,
            "path": str(saved_path),
            "rel_url": f"/project-files/{project_id}/assets/{sub}/{saved_path.name}",
            "engine": engine_used,
            "note": note,
            "status": "OK",
        }
        records.append(rec)
        done_set.add(fid)
        if on_item_done:
            on_item_done(rec, idx, total)

    # 매니페스트 및 줄글 텍스트 해설 가이드(표 금지 규칙 준수!) 저장
    manifest_path = proj_ws / "assets" / "visuals_plan.json"
    manifest_path.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "generated_at": utc_now_iso(),
                "per_chapter_target": max(10, int(per_chapter_count)),
                "use_fal_ai": use_fal_ai,
                "fal_model": fal_model,
                "use_nano_banana": use_nano_banana,
                "total_generated": len(records),
                "ai_images_count": ai_generated_cnt,
                "svg_charts_count": svg_generated_cnt,
                "stopped_early": stopped_early,
                "visuals": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    guide_lines = [
        f"# 《{topic_ko}》 시각화 자료 줄글 해설 가이드",
        "",
        f"본 문서는 각 단원당 {max(10, int(per_chapter_count))}개 이상 제작된 실사진·인포그래픽 및 정량 차트의 상세 내용을 표 형식이 아닌 자연스러운 줄글로 설명합니다.",
        "",
    ]
    for r in records:
        guide_lines.append(f"## {r['title_ko']}")
        guide_lines.append("")
        guide_lines.append(r["narrative_ko"])
        guide_lines.append("")
    guide_path = proj_ws / "assets" / "visuals_text_guide.md"
    guide_path.write_text("\n".join(guide_lines), encoding="utf-8")

    return {
        "status": "INTERRUPTED" if stopped_early else "DONE",
        "total_planned": total,
        "total_generated": len(records),
        "ai_images_count": ai_generated_cnt,
        "svg_charts_count": svg_generated_cnt,
        "completed_visual_ids": sorted(done_set),
        "manifest_path": str(manifest_path),
        "guide_path": str(guide_path),
        "visuals": records,
    }
