"""문서 원고 문맥 기반 단원별 시각화 기획(이미지 번호·줄글 해설·영문 프롬프트 분리 저장) 및
Google Gemini Nano Banana(nano-banana-pro-preview / gemini-nano-banana-2.1) 전량 고품질 재제작 엔진.

기능:
1. 기존 저품질 시각화 자료 전량 삭제(로컬 assets/ + E:\\SMC_Report_Platform_Data\\projects\\<pid>\\visuals\\)
2. 각 단원 실제 원고(chapters/chNN.mdx)를 Google Gemini(gemini-2.5-flash)로 정독해
   문맥·절·수치·품종·메커니즘에 100% 일치하는 단원당 10종 시각화 명세 작성
3. 단원별 별도 폴더(로컬 by_chapter/<chNN>/ 및 E:\\...\\visuals\\by_chapter\\<chNN>\\)에:
   - prompts_and_descriptions.md  (이미지 번호별 매칭 절 · 상세 한국어 줄글 해설 · 영문 프롬프트)
   - prompts_and_descriptions.json
   - fig_chNN_vKK_prompt.txt      (개별 이미지 번호 1:1 매칭 해설·프롬프트 파일)
   - fig_chNN_vKK.png             (Google Gemini Nano Banana Pro 고품질 이미지)
4. visuals_plan.json, visuals_text_guide.md, E:\\visuals\\INDEX.md 및 프로젝트 state.json 자동 동기화
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key
from subagent_orchestrator import append_event, load_project_state, save_project_state

STRICT_VISUAL_SUFFIX = (
    " Publication-grade realism only — strictly NO cartoon, NO childish clipart, NO flat vector doodles. "
    "ABSOLUTE ZERO-TEXT REQUIREMENT: Strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, "
    "NO English labels, NO titles, NO arrows with text, NO captions, NO signboards, NO logos, NO screens, "
    "NO watermarks anywhere in the image."
)

# 『weed_control』 검증 A/B/C/D 도판 유형별 표준 스타일 서픽스 및 교과서 5색 팔레트
WEED_CONTROL_PALETTE = {
    "crop_green": "#3A7D44",
    "deep_header": "#1B4332",
    "weed_orange": "#E07A2E",
    "soil_brown": "#8B5E3C",
    "water_blue": "#3B82C4",
    "academic_navy": "#1D3557",
}

STYLE_SUFFIX_BY_TYPE = {
    "A": (
        " Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and "
        "environmental setting, accurate biological and technical morphology, high detail, "
        "strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3."
    ),
    "B": (
        " Professional studio macro specimen photography on pure seamless white background (#FFFFFF), "
        "soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter "
        "scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3."
    ),
    "C": (
        " Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), "
        "consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, "
        "water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. "
        "ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, "
        "NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9."
    ),
}

VISUAL_TYPE_TO_CODE = {
    "photorealistic_field": ("A", "4:3"),
    "photorealistic_macro": ("B", "4:3"),
    "scientific_anatomy": ("C", "16:9"),
    "quantitative_chart": ("D", "16:9"),
}

NANO_BANANA_MODEL_CHAIN = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
]
PRO_NANO_BANANA_MODEL = "nano-banana-pro-preview"

FAL_NANO_BANANA_MODEL = "fal-ai/nano-banana"


def purge_project_visuals(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트의 기존 시각화 자료(로컬 assets + E:\\ 별도 저장소 + 체크포인트)를 전량 삭제한다."""
    cfg = cfg or get_config()
    ws = cfg.project_dir(project_id)
    assets = ws / "assets"
    e_vis = cfg.e_projects_dir / project_id / "visuals"

    removed_dirs: list[str] = []
    for sub in ("figures", "charts", "charts_png", "by_chapter"):
        d = assets / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed_dirs.append(str(d))
    for fname in ("visuals_plan.json", "visuals_text_guide.md"):
        p = assets / fname
        if p.exists():
            p.unlink(missing_ok=True)
    if e_vis.exists():
        shutil.rmtree(e_vis, ignore_errors=True)
        removed_dirs.append(str(e_vis))

    st = load_project_state(project_id, cfg)
    if st:
        st.setdefault("checkpoint", {})["completed_visuals"] = []
        st["bound_visuals_by_chapter"] = {}
        for s in st.get("stages", []):
            if s.get("stage_id") == "stage5_visuals_generate":
                s["status"] = "PENDING"
                s["progress"] = 0
                s["current_action"] = "기존 시각화 전량 삭제 완료 — 문맥 기반 나노바나나 재제작 대기"
        save_project_state(st, cfg)
    return {"status": "PURGED", "project_id": project_id, "removed": removed_dirs}


def _extract_chapter_body(mdx_path: Path) -> tuple[str, str, list[str]]:
    raw = mdx_path.read_text(encoding="utf-8", errors="ignore")
    # frontmatter 제거
    body = re.sub(r"^---[\s\S]*?---\s*", "", raw, count=1)
    # 참고문헌 표 이전 본문만 추출
    body_main = re.split(r"(?m)^##\s*참고문헌", body, maxsplit=1)[0].strip()
    m_h1 = re.search(r"(?m)^#\s+(.+)$", body_main)
    ch_title = m_h1.group(1).strip() if m_h1 else mdx_path.stem
    headings = [
        re.sub(r"^#+\s*", "", ln).strip()
        for ln in body_main.splitlines()
        if re.match(r"^##\s+(?!#|참고문헌|핵심 용어집|이해도 점검)", ln.strip())
    ]
    return ch_title, body_main, headings


def plan_chapter_visuals_from_manuscript(
    *,
    topic_ko: str,
    topic_en: str,
    chapter_id: str,
    chapter_number: int,
    mdx_path: Path,
    per_chapter_count: int = 4,
    api_key: str = "",
    use_gemini_planner: bool = False,
) -> list[dict[str, Any]]:
    """로컬 Ollama(gemma4:26b, 비용 0원) 우선 + 선택적 Gemini 폴백으로 원고 문맥 기반 시각화 기획을 생성한다."""
    ch_title, body_main, headings = _extract_chapter_body(mdx_path)

    sys_inst = (
        "You are a senior scientific visual director for Nature/Springer university agricultural textbooks.\n"
        "Read the provided Korean textbook chapter manuscript carefully and design EXACTLY "
        f"{per_chapter_count} distinct, high-impact visual figures (v01 to v{per_chapter_count:02d}) "
        "strictly grounded in the chapter's actual sections, biological/agronomic mechanisms, cultivars, tools, and field practices.\n\n"
        "CRITICAL RULES:\n"
        "1. Distribute visuals across body sections (## headings) of the chapter, covering concrete concepts.\n"
        "   STRICT BOTANICAL SUBJECT RULE: Every single image prompt MUST depict ONLY the exact target crop/subject of the book title and chapter manuscript.\n"
        "2. Alternate thoughtfully between:\n"
        "   - 'photorealistic_field': documentary field photograph.\n"
        "   - 'photorealistic_macro': laboratory macro / microscopy photography.\n"
        "   - 'scientific_anatomy': publication-grade cross-section or biological mechanism illustration on a pure white background.\n"
        "3. EVERY 'image_prompt_en' MUST BE 100% PURE ENGLISH with ZERO Korean/Hangul characters, ZERO text/labels/captions.\n"
        "4. EVERY 'description_ko' MUST be 3 concise academic Korean sentences (what it shows, how to read it, source).\n"
        "5. Output valid JSON strictly matching {\"figures\": [{\"slot_index\": 1, \"target_section\": \"...\", \"visual_type\": \"...\", \"title_ko\": \"...\", \"description_ko\": \"...\", \"image_prompt_en\": \"...\"}]}."
    )

    user_prompt = (
        f"Book Title: {topic_ko} ({topic_en})\n"
        f"Chapter: {chapter_id} (Chapter {chapter_number}) — {ch_title}\n"
        f"Body Sections: {', '.join(headings)}\n\n"
        f"=== FULL CHAPTER MANUSCRIPT (Korean) ===\n{body_main[:7000]}\n=== END MANUSCRIPT ===\n\n"
        f"Design exactly {per_chapter_count} bespoke, non-redundant, context-matched figures for this chapter."
    )

    data: dict[str, Any] | None = None
    # 1) 비용 0원 로컬 Ollama(gemma4:26b) 우선 실행
    if not use_gemini_planner:
        try:
            from local_gemma import generate_json

            cfg_local = get_config()
            local_out = generate_json(
                prompt=user_prompt,
                system=sys_inst,
                model=cfg_local.ollama_llm_model,
                num_ctx=16384,
                timeout=120,
            )
            if isinstance(local_out, dict) and isinstance(local_out.get("figures"), list) and local_out["figures"]:
                data = local_out
        except Exception:
            data = None

    # 2) 명시 요청 또는 로컬 폴백 시에만 Gemini Flash 텍스트 모델 사용
    if data is None and api_key:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        schema = {
            "type": "OBJECT",
            "properties": {
                "figures": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "slot_index": {"type": "INTEGER"},
                            "target_section": {"type": "STRING"},
                            "visual_type": {"type": "STRING"},
                            "title_ko": {"type": "STRING"},
                            "description_ko": {"type": "STRING"},
                            "image_prompt_en": {"type": "STRING"},
                        },
                        "required": ["slot_index", "target_section", "visual_type", "title_ko", "description_ko", "image_prompt_en"],
                    },
                }
            },
            "required": ["figures"],
        }
        resp = None
        last_plan_err = ""
        for plan_mdl in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
            try:
                resp = client.models.generate_content(
                    model=plan_mdl,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=sys_inst,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.35,
                    ),
                )
                break
            except Exception as exc:
                last_plan_err = f"{plan_mdl}: {str(exc)[:100]}"
        if resp is None:
            raise RuntimeError(f"Gemini context planner failed: {last_plan_err}")
        data = json.loads(resp.text)

    if data is None:
        raise RuntimeError("시각화 기획 생성 실패: 로컬 Ollama와 Gemini 모두 응답하지 않았습니다.")
    raw_figs = data.get("figures") or []

    out: list[dict[str, Any]] = []
    for idx, f in enumerate(raw_figs[:per_chapter_count], 1):
        fid = f"fig_{chapter_id}_v{idx:02d}"
        fig_no = f"그림 {chapter_number}-{idx}"
        vtype = str(f.get("visual_type") or "scientific_anatomy").strip()
        type_code, aspect_ratio = VISUAL_TYPE_TO_CODE.get(vtype, ("C", "16:9"))
        # Gate 1 프롬프트 정제: 한글·물음표(?)·금지 단어 철저히 제거 후 유형별 표준 서픽스(STYLE_A/B/C) 부착
        clean_en = re.sub(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+", "", str(f.get("image_prompt_en", ""))).replace("?", "").strip()
        clean_en = re.sub(r"\b(infographic|labeled|labelled|text label|korean text|caption|title)\b", "scientific illustration", clean_en, flags=re.I)
        style_suffix = STYLE_SUFFIX_BY_TYPE.get(type_code, STRICT_VISUAL_SUFFIX)
        full_prompt = f"{clean_en.rstrip('.')}." + style_suffix

        raw_title = re.sub(r"^\[?그림\s*\d+-\d+\]?\.?\s*", "", str(f.get("title_ko", "")).replace("?", "").strip())
        full_title = f"[{fig_no}] {raw_title}"
        desc_ko = str(f.get("description_ko", "")).replace("?", "").strip()
        if not desc_ko.startswith("[그림"):
            desc_ko = f"[{fig_no}] {desc_ko}"

        out.append(
            {
                "figure_id": fid,
                "figure_no": fig_no,
                "chapter_id": chapter_id,
                "chapter_number": chapter_number,
                "chapter_title": ch_title,
                "index": idx,
                "target_section": str(f.get("target_section") or (headings[(idx - 1) % max(1, len(headings))] if headings else ch_title)).strip(),
                "type": type_code,
                "aspect_ratio": aspect_ratio,
                "visual_type": vtype,
                "kind": "nano_banana_pro",
                "style": vtype,
                "is_ai_image": True,
                "title_ko": full_title,
                "subtitle_ko": f"{topic_ko} · {f.get('target_section', ch_title)}",
                "narrative_ko": desc_ko,
                "prompt": full_prompt,
            }
        )
    return out


def _save_chapter_prompt_docs(
    chapter_id: str,
    chapter_title: str,
    specs: list[dict[str, Any]],
    loc_ch_dir: Path,
    e_ch_dir: Path,
) -> tuple[Path, Path]:
    """각 챕터 별도 폴더에 이미지 번호별 설명과 프롬프트 문서(.md, .json, 개별 _prompt.txt)를 저장한다."""
    loc_ch_dir.mkdir(parents=True, exist_ok=True)
    e_ch_dir.mkdir(parents=True, exist_ok=True)

    md_lines = [
        f"# {chapter_title} — 문맥 기반 시각화 기획서 (이미지 번호 · 설명 · 프롬프트)",
        "",
        f"- **단원 ID**: `{chapter_id}`",
        f"- **총 시각화 수**: **{len(specs)}종** (Google Gemini Nano Banana 전량 제작)",
        f"- **생성 시각**: `{utc_now_iso()}`",
        "",
        "---",
        "",
    ]
    for sp in specs:
        fname = f"{sp['figure_id']}.png"
        md_lines.extend(
            [
                f"## {sp['title_ko']}",
                "",
                f"- **이미지 번호 / 파일명**: `{sp['figure_no']}` / `{fname}`",
                f"- **문서 결합 절(Section)**: {sp['target_section']}",
                f"- **시각화 유형**: `{sp['visual_type']}`",
                "",
                "### 문맥 기반 상세 설명 (줄글)",
                sp["narrative_ko"],
                "",
                "### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)",
                f"```text\n{sp['prompt']}\n```",
                "",
                "---",
                "",
            ]
        )
        # 개별 이미지 1:1 매칭 텍스트 파일 (fig_chNN_vKK_prompt.txt)
        sidecar_txt = (
            f"이미지 번호: {sp['figure_no']}\n"
            f"이미지 파일명: {fname}\n"
            f"단원: {chapter_title} ({chapter_id})\n"
            f"결합 절: {sp['target_section']}\n"
            f"시각화 유형: {sp['visual_type']}\n"
            f"제목: {sp['title_ko']}\n\n"
            f"[문맥 기반 이미지 설명]\n{sp['narrative_ko']}\n\n"
            f"[나노바나나 생성 프롬프트]\n{sp['prompt']}\n"
        )
        (loc_ch_dir / f"{sp['figure_id']}_prompt.txt").write_text(sidecar_txt, encoding="utf-8")
        (e_ch_dir / f"{sp['figure_id']}_prompt.txt").write_text(sidecar_txt, encoding="utf-8")

    md_text = "\n".join(md_lines)
    loc_md = loc_ch_dir / "prompts_and_descriptions.md"
    e_md = e_ch_dir / "prompts_and_descriptions.md"
    loc_md.write_text(md_text, encoding="utf-8")
    e_md.write_text(md_text, encoding="utf-8")

    json_text = json.dumps({"chapter_id": chapter_id, "chapter_title": chapter_title, "generated_at": utc_now_iso(), "figures": specs}, ensure_ascii=False, indent=2)
    (loc_ch_dir / "prompts_and_descriptions.json").write_text(json_text, encoding="utf-8")
    (e_ch_dir / "prompts_and_descriptions.json").write_text(json_text, encoding="utf-8")
    return loc_md, e_md


def _measure_image_meta(path: Path) -> tuple[int, int, int]:
    if not path.exists():
        return 0, 0, 0
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        return w, h, path.stat().st_size
    except Exception:
        return 0, 0, path.stat().st_size


def build_chapter_qa_grid_and_manifest(
    chapter_id: str,
    chapter_title: str,
    chapter_records: list[dict[str, Any]],
    loc_ch_dir: Path,
    e_ch_dir: Path,
) -> tuple[Path, Path]:
    """『weed_control』 Gate 3 표준: 단원별 manifest.json(Pillow 실측) + qa_grid_<chNN>.jpg 컨택트 시트를 로컬·E:\\ 이중 저장한다."""
    from PIL import Image, ImageDraw, ImageFont

    loc_ch_dir.mkdir(parents=True, exist_ok=True)
    e_ch_dir.mkdir(parents=True, exist_ok=True)

    manifest_figs: list[dict[str, Any]] = []
    for rec in chapter_records:
        p = loc_ch_dir / rec["filename"]
        w, h, sz = _measure_image_meta(p)
        manifest_figs.append(
            {
                "id": rec.get("figure_no", rec["figure_id"]),
                "figure_id": rec["figure_id"],
                "filename": rec["filename"],
                "type": rec.get("type", "C"),
                "visual_type": rec.get("visual_type", "scientific_anatomy"),
                "aspect_ratio": rec.get("aspect_ratio", "16:9"),
                "engine": rec.get("engine", ""),
                "width": w,
                "height": h,
                "resolution": f"{w}x{h}",
                "bytes": sz,
                "status": "COMPLETED" if sz > 30_000 else "PENDING",
            }
        )

    manifest_obj = {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "generated_at": utc_now_iso(),
        "total_required": len(chapter_records),
        "total_completed": sum(1 for x in manifest_figs if x["status"] == "COMPLETED"),
        "figures": manifest_figs,
    }
    m_txt = json.dumps(manifest_obj, ensure_ascii=False, indent=2)
    loc_m = loc_ch_dir / "manifest.json"
    loc_m.write_text(m_txt, encoding="utf-8")
    (e_ch_dir / "manifest.json").write_text(m_txt, encoding="utf-8")

    # 4열 고해상도 QA 컨택트 시트 생성 (마지막 셀에 무결성 요약 카드 배치)
    total_cells = len(chapter_records) + 1
    cols = 4
    rows = max(1, (total_cells + cols - 1) // cols)
    cell_w, cell_h = 640, 420
    margin, header_h = 18, 66
    canvas_w = margin + cols * (cell_w + margin)
    canvas_h = header_h + margin + rows * (cell_h + margin)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (248, 250, 252))
    draw = ImageDraw.Draw(canvas)
    try:
        f_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 28)
        f_lbl = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 18)
        f_body = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 18)
    except Exception:
        f_title = f_lbl = f_body = ImageFont.load_default()

    draw.rectangle([0, 0, canvas_w, header_h], fill=(29, 53, 87))
    draw.text(
        (24, 16),
        f"[{chapter_id}] {chapter_title} — 시각 QA 컨택트 시트 (Gate V-01 ~ V-05)",
        fill=(255, 255, 255),
        font=f_title,
    )

    for idx, rec in enumerate(chapter_records):
        r, c = idx // cols, idx % cols
        x = margin + c * (cell_w + margin)
        y = header_h + margin + r * (cell_h + margin)
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(255, 255, 255), outline=(203, 213, 225), width=2)
        img_p = loc_ch_dir / rec["filename"]
        if img_p.exists():
            try:
                with Image.open(img_p) as im:
                    im_rgb = im.convert("RGB")
                    im_rgb.thumbnail((cell_w - 8, cell_h - 38), Image.Resampling.LANCZOS)
                    px = x + (cell_w - im_rgb.width) // 2
                    py = y + (cell_h - 34 - im_rgb.height) // 2
                    canvas.paste(im_rgb, (px, py))
            except Exception:
                draw.text((x + 14, y + 40), f"LOAD ERR: {rec['filename']}", fill=(220, 38, 38), font=f_lbl)
        lbl_y = y + cell_h - 32
        draw.rectangle([x + 1, lbl_y, x + cell_w - 1, y + cell_h - 1], fill=(238, 242, 248))
        draw.text(
            (x + 10, lbl_y + 5),
            f"{rec.get('figure_no', rec['figure_id'])} | 유형 {rec.get('type', 'C')} ({rec.get('aspect_ratio', '16:9')}) | {rec['filename']}",
            fill=(30, 41, 59),
            font=f_lbl,
        )

    # 마지막 셀: 무결성 요약 박스
    s_idx = len(chapter_records)
    sr, sc = s_idx // cols, s_idx % cols
    sx = margin + sc * (cell_w + margin)
    sy = header_h + margin + sr * (cell_h + margin)
    draw.rectangle([sx, sy, sx + cell_w, sy + cell_h], fill=(255, 255, 255), outline=(58, 125, 68), width=3)
    ok_cnt = manifest_obj["total_completed"]
    summary_lines = [
        f"■ {chapter_id} 시각 도판 QA 요약",
        f"• 완료 수량: {ok_cnt} / {len(chapter_records)}점",
        "• V-01 도메인·해부 정확성 점검",
        "• V-02 한글·영문·물음표(?) 0건 점검",
        "• V-03 본문·서지 수치 일치 점검",
        "• V-04 현장 현실성·PPE·초상권 점검",
        "• V-05 팔레트·해상도·잘림 0건 점검",
    ]
    cy = sy + 28
    for li, line in enumerate(summary_lines):
        draw.text((sx + 22, cy), line, fill=(29, 53, 87) if li == 0 else (30, 41, 59), font=f_lbl if li == 0 else f_body)
        cy += 42 if li == 0 else 36

    loc_grid = loc_ch_dir / f"qa_grid_{chapter_id}.jpg"
    canvas.save(loc_grid, format="JPEG", quality=90)
    shutil.copy2(loc_grid, e_ch_dir / loc_grid.name)
    return loc_m, loc_grid


def _generate_single_nano_banana(
    spec: dict[str, Any],
    *,
    api_key: str,
    model_chain: list[str],
    fig_dir: Path,
    loc_ch_dir: Path,
    e_ch_dir: Path,
    project_id: str,
    backend: str = "google",
    fal_key: str | None = None,
    force: bool = True,
) -> dict[str, Any]:
    from google import genai
    from google.genai import types

    fid = spec["figure_id"]
    out_png = fig_dir / f"{fid}.png"
    aspect_ratio = spec.get("aspect_ratio", "16:9")

    # 캐시 재사용 모드(force=False이고 기존 30KB 이상 파일 존재 시 재생성 생략)
    if not force and out_png.exists() and out_png.stat().st_size > 30_000:
        w, h, sz = _measure_image_meta(out_png)
        cid = spec["chapter_id"]
        return {
            **spec,
            "filename": out_png.name,
            "path": str(out_png),
            "docx_image_path": str(out_png),
            "rel_url": f"/project-files/{project_id}/assets/figures/{out_png.name}",
            "png_url": f"/project-files/{project_id}/assets/figures/{out_png.name}",
            "prompt_txt_url": f"/project-files/{project_id}/assets/by_chapter/{cid}/{fid}_prompt.txt",
            "chapter_prompts_md_url": f"/project-files/{project_id}/assets/by_chapter/{cid}/prompts_and_descriptions.md",
            "chapter_dir_local": str(loc_ch_dir),
            "chapter_dir_e": str(e_ch_dir),
            "width": w,
            "height": h,
            "bytes": sz,
            "engine": "cached",
            "status": "OK",
        }

    last_err = ""
    engine_used = ""

    # fal.ai 2K PNG 백엔드 (weed_control 표준: resolution="2K", enable_web_search=False)
    if backend == "fal" and fal_key:
        try:
            import os
            import fal_client
            import httpx
            os.environ["FAL_KEY"] = fal_key
            res = fal_client.subscribe(
                FAL_NANO_BANANA_MODEL,
                arguments={
                    "prompt": spec["prompt"],
                    "aspect_ratio": aspect_ratio,
                    "resolution": "2K",
                    "output_format": "png",
                    "num_images": 1,
                    "enable_web_search": False,
                },
                with_logs=False,
            )
            img_url = (res.get("images") or [{}])[0].get("url")
            if img_url:
                with httpx.Client(timeout=90.0, follow_redirects=True) as hcli:
                    r = hcli.get(img_url)
                    r.raise_for_status()
                    out_png.parent.mkdir(parents=True, exist_ok=True)
                    out_png.write_bytes(r.content)
                    shutil.copy2(out_png, loc_ch_dir / out_png.name)
                    shutil.copy2(out_png, e_ch_dir / out_png.name)
                    engine_used = f"fal.ai ({FAL_NANO_BANANA_MODEL} 2K)"
        except Exception as exc:
            last_err = f"fal.ai: {str(exc)[:100]}"

    # Google Gemini Nano Banana 백엔드 (단일 시도 + 일시적 오류만 1회 재시도해 중복 과금 차단)
    if not engine_used:
        client = genai.Client(api_key=api_key)
        for mdl in model_chain:
            try:
                resp = client.models.generate_content(
                    model=mdl,
                    contents=spec["prompt"],
                    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
                for part in resp.candidates[0].content.parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        raw = inline.data if isinstance(inline.data, bytes) else base64.b64decode(inline.data)
                        out_png.parent.mkdir(parents=True, exist_ok=True)
                        out_png.write_bytes(raw)
                        shutil.copy2(out_png, loc_ch_dir / out_png.name)
                        shutil.copy2(out_png, e_ch_dir / out_png.name)
                        engine_used = f"Nano Banana ({mdl})"
                        break
                if engine_used:
                    break
            except Exception as exc:
                last_err = f"{mdl}: {str(exc)[:100]}"
                time.sleep(1.0)

    if not engine_used:
        raise RuntimeError(f"Failed to generate {fid}: {last_err}")

    w, h, sz = _measure_image_meta(out_png)
    cid = spec["chapter_id"]
    return {
        **spec,
        "filename": out_png.name,
        "path": str(out_png),
        "docx_image_path": str(out_png),
        "rel_url": f"/project-files/{project_id}/assets/figures/{out_png.name}",
        "png_url": f"/project-files/{project_id}/assets/figures/{out_png.name}",
        "prompt_txt_url": f"/project-files/{project_id}/assets/by_chapter/{cid}/{fid}_prompt.txt",
        "chapter_prompts_md_url": f"/project-files/{project_id}/assets/by_chapter/{cid}/prompts_and_descriptions.md",
        "chapter_dir_local": str(loc_ch_dir),
        "chapter_dir_e": str(e_ch_dir),
        "width": w,
        "height": h,
        "bytes": sz,
        "engine": engine_used,
        "status": "OK",
    }


def rebuild_project_visuals_with_nano_banana(
    project_id: str,
    *,
    per_chapter_count: int = 4,
    primary_model: str = "gemini-2.5-flash-image",
    backend: str = "google",
    only_figure_ids: list[str] | None = None,
    max_workers: int = 2,
    purge_first: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 시각화 자료 전량/선택 제작 → 문맥 기반 단원별 설명·프롬프트·manifest.json·qa_grid 저장 → 나노바나나(Google/fal.ai 2K) 생성."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    api_key = resolve_api_key("GEMINI_API_KEY", None, cfg)
    fal_key = resolve_api_key("FAL_KEY", None, cfg)
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")

    target_set = set(only_figure_ids or [])
    if target_set:
        purge_first = False

    if purge_first:
        purge_project_visuals(project_id, cfg)
        st = load_project_state(project_id, cfg)

    ws = cfg.project_dir(project_id)
    fig_dir = ws / "assets" / "figures"
    by_ch_dir = ws / "assets" / "by_chapter"
    e_vis_root = cfg.e_projects_dir / project_id / "visuals"
    e_by_ch_dir = e_vis_root / "by_chapter"
    for d in (fig_dir, by_ch_dir, e_vis_root, e_by_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    ch_files = sorted((ws / "chapters").glob("*.mdx"))
    if not ch_files:
        raise FileNotFoundError("집필된 단원(.mdx) 파일이 없습니다.")

    # 모델 우선순위 구성
    model_chain = [primary_model] + [m for m in NANO_BANANA_MODEL_CHAIN if m != primary_model]

    # 1단계: 모든 단원의 실제 원고를 정독해 문맥 기반 10종 기획(설명+프롬프트) 작성 또는 기존 기획 재사용
    all_specs: list[dict[str, Any]] = []
    prompt_docs_summary: dict[str, dict[str, str]] = {}
    for ch_idx, mdx_p in enumerate(ch_files, 1):
        cid = mdx_p.stem
        m_num = re.search(r"(\d+)", cid)
        ch_num = int(m_num.group(1)) if m_num else ch_idx
        loc_ch = by_ch_dir / cid
        e_ch = e_by_ch_dir / cid
        existing_json = loc_ch / "prompts_and_descriptions.json"
        if not purge_first and existing_json.exists():
            specs = json.loads(existing_json.read_text(encoding="utf-8")).get("figures") or []
            loc_md = loc_ch / "prompts_and_descriptions.md"
            e_md = e_ch / "prompts_and_descriptions.md"
        else:
            print(f"[PLAN {ch_idx}/{len(ch_files)}] {cid} 원고 문맥 분석 및 {per_chapter_count}종 프롬프트·해설 설계 중...", flush=True)
            specs = plan_chapter_visuals_from_manuscript(
                topic_ko=st["topic_ko"],
                topic_en=st.get("topic_en", ""),
                chapter_id=cid,
                chapter_number=ch_num,
                mdx_path=mdx_p,
                per_chapter_count=per_chapter_count,
                api_key=api_key,
            )
            loc_md, e_md = _save_chapter_prompt_docs(cid, specs[0]["chapter_title"], specs, loc_ch, e_ch)
            append_event(project_id, "visual-artist", "stage5_visuals_generate", f"[{cid}] 원고 문맥 기반 {len(specs)}종 설명·프롬프트 저장 완료 ({loc_md.name})", cfg=cfg)
        prompt_docs_summary[cid] = {
            "local_md": str(loc_md),
            "e_md": str(e_md),
            "web_url": f"/project-files/{project_id}/assets/by_chapter/{cid}/prompts_and_descriptions.md",
        }
        all_specs.extend(specs)

    # 대시보드 진행 상태 초기화
    for s in st["stages"]:
        if s["stage_id"] == "stage5_visuals_generate":
            s["status"] = "RUNNING"
            s["progress"] = 12
            s["started_at"] = utc_now_iso()
            s["current_action"] = f"전 단원 {len(all_specs)}종 문맥 프롬프트 준비 완료 → {backend}/{primary_model} 생성 시작..."
    st["overall_status"] = "RUNNING"
    st["active_stage_id"] = "stage5_visuals_generate"
    save_project_state(st, cfg)

    # 2단계: Nano Banana (Google 또는 fal.ai 2K) 병렬 생성 (체크포인트 실시간 저장 · --only 선택 재생성 지원)
    total = len(all_specs)
    records_by_id: dict[str, dict[str, Any]] = {}
    done_ids: list[str] = []

    def _task(sp: dict[str, Any]) -> dict[str, Any]:
        cid = sp["chapter_id"]
        should_force = purge_first or (not target_set) or (sp["figure_id"] in target_set) or (f"{sp['figure_id']}.png" in target_set)
        return _generate_single_nano_banana(
            sp,
            api_key=api_key,
            model_chain=model_chain,
            fig_dir=fig_dir,
            loc_ch_dir=by_ch_dir / cid,
            e_ch_dir=e_by_ch_dir / cid,
            project_id=project_id,
            backend=backend,
            fal_key=fal_key,
            force=should_force,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_task, sp): sp for sp in all_specs}
        done_cnt = 0
        for fut in as_completed(futs):
            rec = fut.result()
            done_cnt += 1
            records_by_id[rec["figure_id"]] = rec
            done_ids.append(rec["figure_id"])
            pct = 12 + int((done_cnt / max(1, total)) * 86)
            if done_cnt <= 5 or done_cnt % 5 == 0 or done_cnt == total:
                print(f"  [GEN {done_cnt}/{total}] {rec['figure_id']} ({rec['engine']}) — {rec['title_ko'][:52]}", flush=True)
                st["checkpoint"]["completed_visuals"] = sorted(done_ids)
                for s in st["stages"]:
                    if s["stage_id"] == "stage5_visuals_generate":
                        s["progress"] = min(98, pct)
                        s["current_action"] = f"나노바나나 제작 [{done_cnt}/{total}] {rec['figure_id']} ({rec['engine']})"
                save_project_state(st, cfg)

    # 원래 단원·번호 순으로 정렬
    ordered_records = [records_by_id[sp["figure_id"]] for sp in all_specs if sp["figure_id"] in records_by_id]
    by_ch_counts: dict[str, int] = {}
    records_by_chapter: dict[str, list[dict[str, Any]]] = {}
    for r in ordered_records:
        cid = r["chapter_id"]
        by_ch_counts[cid] = by_ch_counts.get(cid, 0) + 1
        records_by_chapter.setdefault(cid, []).append(r)

    # 2.5단계: 『weed_control』 Gate 3 표준 — 단원별 manifest.json + qa_grid_<chNN>.jpg 컨택트 시트 자동 생성
    qa_grids_summary: dict[str, str] = {}
    for cid, ch_recs in sorted(records_by_chapter.items()):
        ch_title_str = ch_recs[0].get("chapter_title", cid)
        _, grid_p = build_chapter_qa_grid_and_manifest(
            cid, ch_title_str, ch_recs, by_ch_dir / cid, e_by_ch_dir / cid
        )
        qa_grids_summary[cid] = f"/project-files/{project_id}/assets/by_chapter/{cid}/{grid_p.name}"
        if cid in prompt_docs_summary:
            prompt_docs_summary[cid]["qa_grid_url"] = qa_grids_summary[cid]

    # 3단계: visuals_plan.json · visuals_text_guide.md · E:\visuals\INDEX.md 최종 저장
    manifest_payload = {
        "project_id": project_id,
        "generated_at": utc_now_iso(),
        "generation_mode": "weed_control_4type_nano_banana",
        "backend": backend,
        "primary_model": primary_model,
        "per_chapter_target": per_chapter_count,
        "use_fal_ai": backend == "fal",
        "use_nano_banana": True,
        "total_generated": len(ordered_records),
        "ai_images_count": len(ordered_records),
        "svg_charts_count": 0,
        "png_rasterized_count": len(ordered_records),
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_counts,
        "chapter_prompt_docs": prompt_docs_summary,
        "chapter_qa_grids": qa_grids_summary,
        "visuals": ordered_records,
    }
    manifest_text = json.dumps(manifest_payload, ensure_ascii=False, indent=2)
    manifest_path = ws / "assets" / "visuals_plan.json"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    (e_vis_root / "visuals_plan.json").write_text(manifest_text, encoding="utf-8")

    # 표 없는 줄글 해설 가이드
    guide_lines = [
        f"# 《{st['topic_ko']}》 문맥 기반 나노바나나 시각화 줄글 해설 가이드",
        "",
        f"본 문서는 각 단원 원고의 문맥에 맞추어 Google Gemini 나노바나나(`{primary_model}`)로 전량 제작된 {len(ordered_records)}종 고화질 시각화의 상세 해설을 자연스러운 줄글로 정리합니다.",
        f"- 로컬 단원별 폴더(이미지 + 프롬프트/해설): `{by_ch_dir}`",
        f"- E 드라이브 별도 시각화 저장소: `{e_vis_root}`",
        "",
    ]
    for r in ordered_records:
        guide_lines.append(f"## {r['title_ko']}")
        guide_lines.append("")
        guide_lines.append(r["narrative_ko"])
        guide_lines.append("")
    guide_text = "\n".join(guide_lines)
    guide_path = ws / "assets" / "visuals_text_guide.md"
    guide_path.write_text(guide_text, encoding="utf-8")
    (e_vis_root / "visuals_text_guide.md").write_text(guide_text, encoding="utf-8")

    idx_lines = [
        f"# 《{st['topic_ko']}》 단원별 시각화 · 설명 · 프롬프트 별도 저장소 인덱스",
        "",
        f"- **총 제작 수량**: **{len(ordered_records)}종 전량 AI 실사·과학도해** (`{primary_model}`)",
        f"- **로컬 단원별 폴더**: `{by_ch_dir}`",
        f"- **E 드라이브 별도 저장소**: `{e_by_ch_dir}`",
        "",
    ]
    for cid, cnt in sorted(by_ch_counts.items()):
        idx_lines.append(f"- `{cid}`: {cnt}종 (`by_chapter/{cid}/prompts_and_descriptions.md` · `fig_{cid}_v01.png` ~ `fig_{cid}_v{cnt:02d}.png`)")
    (e_vis_root / "INDEX.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

    # 프로젝트 state.json Stage 5 완료 갱신
    st["checkpoint"]["completed_visuals"] = sorted(done_ids)
    st["local_visuals_dir"] = str(by_ch_dir)
    st["e_visuals_dir"] = str(e_vis_root)
    st["overall_status"] = "PAUSED"
    st["active_stage_id"] = None
    for s in st["stages"]:
        if s["stage_id"] == "stage5_visuals_generate":
            s["status"] = "DONE"
            s["progress"] = 100
            s["finished_at"] = utc_now_iso()
            s["current_action"] = f"문맥 기반 나노바나나 전량 재제작 완료 ({len(ordered_records)}종 · 단원별 해설/프롬프트 별도 폴더 저장)"
            s["metrics"] = {
                "total_visuals": len(ordered_records),
                "per_chapter": per_chapter_count,
                "ai_images": len(ordered_records),
                "svg_charts": 0,
                "model": primary_model,
                "e_visuals_dir": str(e_vis_root),
            }
            s["artifacts"] = [str(manifest_path), str(guide_path)]
    save_project_state(st, cfg)
    append_event(project_id, "visual-artist", "stage5_visuals_generate", f"문맥 기반 나노바나나({primary_model}) 전량 {len(ordered_records)}종 재제작 및 단원별 해설·프롬프트 저장 완료", cfg=cfg)
    return manifest_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="『weed_control』 표준 문맥 기반 단원별 시각화 기획(해설·프롬프트·manifest·QA그리드) 및 나노바나나 생성")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--per-chapter", type=int, default=10)
    parser.add_argument("--model", default="nano-banana-pro-preview")
    parser.add_argument("--backend", choices=["google", "fal"], default="google")
    parser.add_argument("--only", nargs="*", default=None, help="특정 figure_id 또는 파일명만 선택 재생성 (예: fig_ch01_v03)")
    parser.add_argument("--no-purge", action="store_true", help="기존 기획/캐시 이미지를 유지하고 미생성 항목만 이어서 생성")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    res = rebuild_project_visuals_with_nano_banana(
        args.project_id,
        per_chapter_count=args.per_chapter,
        primary_model=args.model,
        backend=args.backend,
        only_figure_ids=args.only,
        max_workers=args.workers,
        purge_first=(not args.no_purge) and (not args.only),
    )
    print(json.dumps({
        "status": "DONE",
        "project_id": res["project_id"],
        "backend": res.get("backend"),
        "total_generated": res["total_generated"],
        "primary_model": res["primary_model"],
        "local_visuals_dir": res["local_visuals_dir"],
        "e_visuals_dir": res["e_visuals_dir"],
        "chapter_qa_grids": res.get("chapter_qa_grids", {}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
