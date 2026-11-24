"""참참살이 영농 AI 출판도우미 — 독립형 이미지 생성 스튜디오 & 비용·분할 배치 결합 모듈.

설계 목적:
- 유료 이미지 AI(Google Gemini Nano Banana / fal.ai)의 비용·쿼터·속도 제약으로 인해
  전체 단원의 이미지를 한 번에 생성할 수 없는 실무 환경을 해결한다.
- [1] 기획·프롬프트 먼저 설계(비용 0원) → [2] 단원·유형·배치장수·예산상한별 분할 생성 또는
  무료 로컬 도표(0원)·사용자 직접 업로드(0원) → [3] 메인 파이프라인(visuals_plan.json ·
  by_chapter/ · E:\\ 백업 · 6단계 PDF/DOCX/블로그)과 원클릭 결합 동기화!
- 단원당 시각화 자료 개수(visuals_per_chapter)를 0~25개까지 자유롭게 설정할 수 있다.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key

# 엔진별 1장당 예상 단가(USD) 및 원화 환산 기준 (실제 Google Gemini/fal.ai 단가 반영)
ENGINE_UNIT_COST_USD: dict[str, float] = {
    "free_local_only": 0.0,
    "cited_redraw": 0.0,      # 원문 표 재작성 / CC-BY 직접 인용 (0원)
    "auto_hybrid": 0.039,     # AI 대상(A/B)만 gemini-2.5-flash-image 과금, C/D는 무료(0원)
    "nano_banana": 0.039,     # gemini-2.5-flash-image (표준 저비용)
    "nano_banana_pro": 0.134, # nano-banana-pro-preview (고화질 표지·대표도판 선택 옵션)
    "fal_ai": 0.045,
}
USD_TO_KRW = 1400

# A/B/C/D 기본 유형 메타
VISUAL_TYPE_META: dict[str, dict[str, Any]] = {
    "A": {
        "code": "A",
        "label_ko": "현장 실사 (Zero-Text)",
        "visual_type": "photorealistic_field",
        "kind": "photo_ai",
        "aspect_ratio": "4:3",
        "default_paid": True,
    },
    "B": {
        "code": "B",
        "label_ko": "스튜디오 표본 · 접사",
        "visual_type": "photorealistic_macro",
        "kind": "photo_ai",
        "aspect_ratio": "4:3",
        "default_paid": True,
    },
    "C": {
        "code": "C",
        "label_ko": "개념 도해 · 구조도",
        "visual_type": "scientific_anatomy",
        "kind": "svg_flow",
        "aspect_ratio": "16:9",
        "default_paid": False,
    },
    "D": {
        "code": "D",
        "label_ko": "정량 차트 · 비교 도표",
        "visual_type": "quantitative_chart",
        "kind": "svg_bar",
        "aspect_ratio": "16:9",
        "default_paid": False,
    },
}

# 프로젝트별 독립 배치 실행 상태(인메모리 + 디스크 영속)
_STUDIO_JOBS: dict[str, dict[str, Any]] = {}
_STUDIO_STOPS: dict[str, threading.Event] = {}
_STUDIO_LOCK = threading.Lock()


def _queue_path(project_id: str, cfg: PlatformConfig) -> Path:
    d = cfg.project_dir(project_id) / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d / "image_studio_queue.json"


def _infer_type_code(rec: dict[str, Any]) -> str:
    t = str(rec.get("type") or "").upper().strip()
    if t in ("A", "B", "C", "D"):
        return t
    vt = str(rec.get("visual_type") or rec.get("style") or rec.get("kind") or "").lower()
    if "field" in vt or vt == "photorealistic":
        return "A"
    if "macro" in vt:
        return "B"
    if "bar" in vt or "chart" in vt or "curve" in vt or "matrix" in vt or "quantitative" in vt:
        return "D"
    return "C"


def _load_or_init_queue(project_id: str, cfg: PlatformConfig) -> dict[str, Any]:
    """image_studio_queue.json을 로드하거나, 기존 visuals_plan.json이 있으면 자동 이관한다."""
    qp = _queue_path(project_id, cfg)
    ws = cfg.project_dir(project_id)
    assets_dir = ws / "assets"

    if qp.is_file():
        try:
            data = json.loads(qp.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                _refresh_item_file_statuses(project_id, data["items"], ws)
                return data
        except Exception:
            pass

    # 기존 visuals_plan.json에서 마이그레이션
    plan_p = assets_dir / "visuals_plan.json"
    items: list[dict[str, Any]] = []
    per_ch = 6
    if plan_p.is_file():
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
            per_ch = int(plan.get("per_chapter_target") or 6)
            for idx, r in enumerate(plan.get("visuals") or plan.get("items") or [], 1):
                tcode = _infer_type_code(r)
                fid = r.get("figure_id") or f"fig_{r.get('chapter_id','ch01')}_v{idx:02d}"
                items.append(
                    {
                        "figure_id": fid,
                        "figure_no": r.get("figure_no") or f"그림 {r.get('chapter_number', 1)}-{r.get('index', idx)}",
                        "chapter_id": r.get("chapter_id", "ch01"),
                        "chapter_number": int(r.get("chapter_number") or 1),
                        "chapter_title": r.get("chapter_title") or r.get("chapter_id", "ch01"),
                        "index": int(r.get("index") or idx),
                        "type": tcode,
                        "visual_type": r.get("visual_type") or VISUAL_TYPE_META[tcode]["visual_type"],
                        "kind": r.get("kind") or VISUAL_TYPE_META[tcode]["kind"],
                        "aspect_ratio": r.get("aspect_ratio") or VISUAL_TYPE_META[tcode]["aspect_ratio"],
                        "target_section": r.get("target_section") or "",
                        "title_ko": r.get("title_ko") or fid,
                        "subtitle_ko": r.get("subtitle_ko") or "",
                        "narrative_ko": r.get("narrative_ko") or "",
                        "prompt": r.get("prompt") or "",
                        "is_ai_image": bool(r.get("is_ai_image", tcode in ("A", "B"))),
                        "status": "PENDING",
                        "engine": r.get("engine") or "",
                        "filename": r.get("filename") or f"{fid}.png",
                        "path": r.get("path") or "",
                        "docx_image_path": r.get("docx_image_path") or "",
                        "rel_url": r.get("rel_url") or r.get("png_url") or "",
                        "png_url": r.get("png_url") or r.get("rel_url") or "",
                        "updated_at": r.get("regenerated_at") or plan.get("generated_at") or "",
                        "error": "",
                    }
                )
        except Exception:
            pass

    _refresh_item_file_statuses(project_id, items, ws)
    queue = {
        "project_id": project_id,
        "updated_at": utc_now_iso(),
        "per_chapter_count": per_ch,
        "type_counts": {"A": 2, "B": 1, "C": 2, "D": 1},
        "items": items,
    }
    if items:
        _save_queue(project_id, queue, cfg)
    return queue


def _refresh_item_file_statuses(project_id: str, items: list[dict[str, Any]], ws: Path) -> None:
    """디스크의 실제 이미지 파일 존재 여부를 확인해 각 슬롯의 상태를 최신화한다."""
    fig_dir = ws / "assets" / "figures"
    chart_png_dir = ws / "assets" / "charts_png"
    chart_dir = ws / "assets" / "charts"

    for it in items:
        if it.get("status") == "SKIPPED":
            continue
        fid = it.get("figure_id", "")
        cand_png = fig_dir / f"{fid}.png"
        cand_cpng = chart_png_dir / f"{fid}.png"
        cand_svg = chart_dir / f"{fid}.svg"
        cur_p = Path(it["path"]) if it.get("path") else None

        found: Path | None = None
        if cur_p and cur_p.is_file() and cur_p.stat().st_size > 200:
            found = cur_p
        elif cand_png.is_file() and cand_png.stat().st_size > 200:
            found = cand_png
        elif cand_cpng.is_file() and cand_cpng.stat().st_size > 200:
            found = cand_cpng
        elif cand_svg.is_file() and cand_svg.stat().st_size > 200:
            found = cand_svg

        if found:
            it["path"] = str(found)
            it["filename"] = found.name
            if found.suffix.lower() == ".png":
                it["docx_image_path"] = str(found)
            rel_sub = found.relative_to(ws).as_posix()
            url = f"/project-files/{project_id}/{rel_sub}"
            it["rel_url"] = url
            it["png_url"] = url
            if it.get("status") not in ("UPLOADED",):
                it["status"] = "GENERATED"
        else:
            if it.get("status") in ("GENERATED", "UPLOADED"):
                it["status"] = "PENDING"


def _save_queue(project_id: str, queue: dict[str, Any], cfg: PlatformConfig) -> Path:
    queue["updated_at"] = utc_now_iso()
    qp = _queue_path(project_id, cfg)
    tmp = qp.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, qp)
    return qp


def _load_project_chapters_meta(project_id: str, cfg: PlatformConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from subagent_orchestrator import load_project_state

    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    ws = Path(st["workspace_dir"])
    bp_path = ws / "blueprints" / "master_outline.yaml"
    chs: list[dict[str, Any]] = []
    if bp_path.is_file():
        bp = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        for pt in bp.get("parts", []):
            for c in pt.get("chapters", []):
                chs.append(c)
    if not chs:
        ch_dir = ws / "chapters"
        if ch_dir.is_dir():
            for idx, p in enumerate(sorted(ch_dir.glob("*.mdx")), 1):
                chs.append({"chapter_id": p.stem, "chapter_number": idx, "title": p.stem, "sections": []})
    for idx, c in enumerate(chs, 1):
        c.setdefault("chapter_id", f"ch{idx:02d}")
        c.setdefault("chapter_number", idx)
        c.setdefault("title", f"제{idx}장")
    return st, chs


def _build_type_sequence(per_chapter_count: int, type_counts: dict[str, int] | None = None) -> list[str]:
    """단원당 목표 개수(0~25)와 A/B/C/D 유형 배분에 따라 슬롯 유형 순서를 생성한다."""
    n = max(0, min(25, int(per_chapter_count)))
    if n == 0:
        return []
    if type_counts:
        seq: list[str] = []
        for code in ("A", "B", "C", "D"):
            cnt = max(0, int(type_counts.get(code) or 0))
            seq.extend([code] * cnt)
        if seq:
            if len(seq) >= n:
                return seq[:n]
            cycle = ["A", "C", "D", "B"]
            while len(seq) < n:
                seq.append(cycle[len(seq) % len(cycle)])
            return seq
    # 기본 균형 배분 (비용 효율적: A 실사, C 도해, D 차트, B 표본 순환)
    cycle = ["A", "C", "D", "B", "C", "D", "A", "D", "C", "B"]
    return [cycle[i % len(cycle)] for i in range(n)]


def get_studio_state(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """독립 이미지 생성 스튜디오의 전체 큐·비용 예측·단원별 진행·실행 중 배치 상태를 반환한다."""
    cfg = cfg or get_config()
    st, chs = _load_project_chapters_meta(project_id, cfg)
    queue = _load_or_init_queue(project_id, cfg)
    items = queue.get("items") or []

    opts = st.get("options") or {}
    saved_per_ch = opts.get("visuals_per_chapter")
    if saved_per_ch is None:
        saved_per_ch = queue.get("per_chapter_count", 6)

    done_cnt = sum(1 for x in items if x.get("status") in ("GENERATED", "UPLOADED"))
    pending_cnt = sum(1 for x in items if x.get("status") == "PENDING")
    error_cnt = sum(1 for x in items if x.get("status") == "ERROR")
    skipped_cnt = sum(1 for x in items if x.get("status") == "SKIPPED")

    pending_ai_hybrid = sum(1 for x in items if x.get("status") in ("PENDING", "ERROR") and x.get("type") in ("A", "B"))
    pending_all_ai = sum(1 for x in items if x.get("status") in ("PENDING", "ERROR"))

    by_chapter: dict[str, dict[str, Any]] = {}
    for c in chs:
        cid = c["chapter_id"]
        by_chapter[cid] = {
            "chapter_id": cid,
            "title": c.get("title", cid),
            "total": 0,
            "done": 0,
            "pending": 0,
            "error": 0,
        }
    for x in items:
        cid = x.get("chapter_id", "ch01")
        row = by_chapter.setdefault(cid, {"chapter_id": cid, "title": x.get("chapter_title", cid), "total": 0, "done": 0, "pending": 0, "error": 0})
        row["total"] += 1
        stt = x.get("status")
        if stt in ("GENERATED", "UPLOADED"):
            row["done"] += 1
        elif stt == "ERROR":
            row["error"] += 1
        elif stt == "PENDING":
            row["pending"] += 1

    by_type = {code: {"total": 0, "done": 0, "pending": 0} for code in ("A", "B", "C", "D")}
    for x in items:
        tc = x.get("type", "C")
        if tc not in by_type:
            tc = "C"
        by_type[tc]["total"] += 1
        if x.get("status") in ("GENERATED", "UPLOADED"):
            by_type[tc]["done"] += 1
        elif x.get("status") in ("PENDING", "ERROR"):
            by_type[tc]["pending"] += 1

    job = dict(_STUDIO_JOBS.get(project_id) or {"running": False, "processed": 0, "total": 0, "message": "대기 중"})
    return {
        "project_id": project_id,
        "topic_ko": st.get("topic_ko", ""),
        "per_chapter_count": int(saved_per_ch),
        "type_counts": queue.get("type_counts") or {"A": 2, "B": 1, "C": 2, "D": 1},
        "total_chapters": len(chs),
        "summary": {
            "total": len(items),
            "done": done_cnt,
            "pending": pending_cnt,
            "error": error_cnt,
            "skipped": skipped_cnt,
            "progress_pct": round((done_cnt / max(1, len(items) - skipped_cnt)) * 100, 1) if items else 0.0,
            "est_cost_hybrid_usd": round(pending_ai_hybrid * ENGINE_UNIT_COST_USD["auto_hybrid"], 2),
            "est_cost_hybrid_krw": int(round(pending_ai_hybrid * ENGINE_UNIT_COST_USD["auto_hybrid"] * USD_TO_KRW)),
            "est_cost_all_ai_usd": round(pending_all_ai * ENGINE_UNIT_COST_USD["nano_banana"], 2),
            "est_cost_all_ai_krw": int(round(pending_all_ai * ENGINE_UNIT_COST_USD["nano_banana"] * USD_TO_KRW)),
            "pending_paid_hybrid_count": pending_ai_hybrid,
            "pending_free_hybrid_count": max(0, pending_all_ai - pending_ai_hybrid),
        },
        "api_ready": {
            "gemini": bool(resolve_api_key("GEMINI_API_KEY", None, cfg)),
            "fal": bool(resolve_api_key("FAL_KEY", None, cfg)),
        },
        "by_chapter": list(by_chapter.values()),
        "by_type": by_type,
        "type_meta": VISUAL_TYPE_META,
        "job": job,
        "items": items,
    }


def plan_visual_queue(
    *,
    project_id: str,
    per_chapter_count: int = 6,
    type_counts: dict[str, int] | None = None,
    chapter_ids: list[str] | None = None,
    keep_existing: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """비용 0원으로 단원별 원하는 개수(0~25)의 A/B/C/D 시각화 기획(제목·절·해설·프롬프트) 큐를 설계한다."""
    from context_visual_director import STYLE_SUFFIX_BY_TYPE
    from subagent_orchestrator import save_project_state
    from visual_studio import ZERO_TEXT_RULE, _resolve_english_visual_scenes

    cfg = cfg or get_config()
    st, chs = _load_project_chapters_meta(project_id, cfg)
    n_per = max(0, min(25, int(per_chapter_count)))

    # 프로젝트 옵션에도 시각화 개수 즉시 반영
    st.setdefault("options", {})["visuals_per_chapter"] = n_per
    save_project_state(st, cfg)

    queue = _load_or_init_queue(project_id, cfg)
    old_by_id = {x["figure_id"]: x for x in (queue.get("items") or [])}
    target_ch_set = set(chapter_ids) if chapter_ids else None
    type_seq = _build_type_sequence(n_per, type_counts)

    new_items: list[dict[str, Any]] = []
    topic_ko = st.get("topic_ko", project_id)
    topic_en = st.get("topic_en", "")

    svg_kinds = ["svg_flow", "svg_layers"]

    for ch in chs:
        cid = ch["chapter_id"]
        ch_num = int(ch.get("chapter_number") or 1)
        ch_title = ch.get("title") or f"제{ch_num}장"
        secs = ch.get("sections") or [f"{ch_num}.1 개념과 이론", f"{ch_num}.2 생리·메커니즘", f"{ch_num}.3 현장 적용", f"{ch_num}.4 법규·기준"]

        if target_ch_set is not None and cid not in target_ch_set:
            # 선택하지 않은 단원의 기존 항목은 그대로 유지
            new_items.extend([x for x in (queue.get("items") or []) if x.get("chapter_id") == cid])
            continue

        if n_per == 0:
            continue

        field_scene, diagram_scene, macro_scene = _resolve_english_visual_scenes(topic_ko, topic_en, ch)
        for idx, tcode in enumerate(type_seq, 1):
            fid = f"fig_{cid}_v{idx:02d}"
            existing = old_by_id.get(fid)
            if keep_existing and existing and existing.get("status") in ("GENERATED", "UPLOADED"):
                # 이미 돈/시간을 들여 만든 이미지는 보존!
                new_items.append(existing)
                continue

            sec_ref = secs[(idx - 1) % len(secs)]
            meta = VISUAL_TYPE_META[tcode]
            if tcode == "A":
                base_prompt = f"Ultra-realistic documentary agricultural photograph of {field_scene}, crisp natural daylight, field research station quality."
                prompt = base_prompt + STYLE_SUFFIX_BY_TYPE["A"]
                kind = "photo_ai"
                role_txt = "현장 실사진"
            elif tcode == "B":
                base_prompt = f"Ultra-sharp laboratory macro specimen photography of {macro_scene}, clean diagnostic focus."
                prompt = base_prompt + STYLE_SUFFIX_BY_TYPE["B"]
                kind = "photo_ai"
                role_txt = "스튜디오 표본·접사"
            elif tcode == "C":
                base_prompt = f"Publication-grade scientific anatomical and mechanism illustration of {diagram_scene}."
                prompt = base_prompt + STYLE_SUFFIX_BY_TYPE["C"]
                kind = svg_kinds[(idx - 1) % len(svg_kinds)]
                role_txt = "내용 기반 구조·흐름 도해"
            else:
                prompt = ""
                kind = "matplotlib_data_chart"
                role_txt = "실데이터 정량 차트(CSV/DB 필수)"

            fig_no = f"그림 {ch_num}-{idx}"
            short_sec = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_ref).strip()[:36]
            title_ko = f"[{fig_no}] {short_sec}"
            narrative_ko = (
                f"[{fig_no}] {short_sec}의 핵심 구성과 정량 관계를 보여준다. "
                f"도해의 입력 요소·축 단위와 판단 기준을 순서대로 따라 읽는다. "
                f"(자료: 《{topic_ko}》 {sec_ref} 본문 및 검증 근거 패킷)."
            )
            new_items.append(
                {
                    "figure_id": fid,
                    "figure_no": fig_no,
                    "chapter_id": cid,
                    "chapter_number": ch_num,
                    "chapter_title": ch_title,
                    "index": idx,
                    "type": tcode,
                    "visual_type": meta["visual_type"],
                    "kind": kind,
                    "aspect_ratio": meta["aspect_ratio"],
                    "target_section": sec_ref,
                    "title_ko": title_ko,
                    "subtitle_ko": f"{topic_ko} · {sec_ref}",
                    "narrative_ko": narrative_ko,
                    "prompt": prompt,
                    "is_ai_image": tcode in ("A", "B"),
                    "status": "PENDING",
                    "engine": "",
                    "filename": f"{fid}.png",
                    "path": "",
                    "docx_image_path": "",
                    "rel_url": "",
                    "png_url": "",
                    "sections": secs,
                    "updated_at": utc_now_iso(),
                    "error": "",
                }
            )

    # 단원·번호 순 정렬
    new_items.sort(key=lambda x: (int(x.get("chapter_number") or 0), int(x.get("index") or 0)))
    queue["per_chapter_count"] = n_per
    if type_counts:
        queue["type_counts"] = {k: max(0, int(type_counts.get(k) or 0)) for k in ("A", "B", "C", "D")}
    queue["items"] = new_items
    _save_queue(project_id, queue, cfg)
    return get_studio_state(project_id, cfg)


def _render_single_free_local(
    item: dict[str, Any],
    *,
    project_id: str,
    ws: Path,
    e_vis_root: Path,
) -> dict[str, Any]:
    """비용 0원 고해상도 로컬 벡터 SVG + PNG(Pillow/Playwright 폴백) 도표를 생성한다."""
    from visual_studio import _rasterize_svgs_batch, _render_vector_svg

    fid = item["figure_id"]
    cid = item["chapter_id"]
    chart_dir = ws / "assets" / "charts"
    png_dir = ws / "assets" / "charts_png"
    by_ch_dir = ws / "assets" / "by_chapter" / cid
    e_ch_dir = e_vis_root / "by_chapter" / cid
    for d in (chart_dir, png_dir, by_ch_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    spec_for_svg = dict(item)
    if spec_for_svg.get("style") in ("comparison_bar", "response_curve"):
        spec_for_svg["style"] = "content_diagram"
    if not str(spec_for_svg.get("kind", "")).startswith("svg_"):
        spec_for_svg["kind"] = "svg_flow"
        spec_for_svg["style"] = "content_diagram"
    secs = item.get("sections") or [item.get("target_section") or "핵심 원리", "정량 기준", "현장 적용"]
    svg_markup = _render_vector_svg(spec_for_svg, secs)
    svg_p = chart_dir / f"{fid}.svg"
    svg_p.write_text(svg_markup, encoding="utf-8")

    png_p = png_dir / f"{fid}.png"
    _rasterize_svgs_batch([(svg_p, png_p)], force=True)

    final_file = png_p if (png_p.is_file() and png_p.stat().st_size > 1000) else svg_p
    for dest_dir in (by_ch_dir, e_ch_dir):
        try:
            shutil.copy2(final_file, dest_dir / final_file.name)
            if svg_p.is_file():
                shutil.copy2(svg_p, dest_dir / svg_p.name)
        except Exception:
            pass

    rel_sub = final_file.relative_to(ws).as_posix()
    url = f"/project-files/{project_id}/{rel_sub}"
    item["path"] = str(final_file)
    item["filename"] = final_file.name
    item["docx_image_path"] = str(png_p) if png_p.is_file() else ""
    item["rel_url"] = url
    item["png_url"] = url
    item["engine"] = "Local Vector Chart (무료 · 0원)"
    item["is_ai_image"] = False
    item["status"] = "GENERATED"
    item["error"] = ""
    item["updated_at"] = utc_now_iso()
    return item


def _render_single_paid_ai(
    item: dict[str, Any],
    *,
    project_id: str,
    engine_mode: str,
    fal_model: str,
    ws: Path,
    e_vis_root: Path,
    cfg: PlatformConfig,
) -> dict[str, Any]:
    """유료 이미지 AI(Google Nano Banana 또는 fal.ai)로 단건 고화질 PNG를 생성한다."""
    from visual_studio import _generate_with_fal_ai, _generate_with_nano_banana

    fid = item["figure_id"]
    cid = item["chapter_id"]
    fig_dir = ws / "assets" / "figures"
    by_ch_dir = ws / "assets" / "by_chapter" / cid
    e_ch_dir = e_vis_root / "by_chapter" / cid
    for d in (fig_dir, by_ch_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    out_png = fig_dir / f"{fid}.png"
    tmp_png = out_png.with_name(f"{fid}_studio_tmp.png")
    prompt = str(item.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("이미지 영문 프롬프트가 비어 있습니다.")

    gem_key = resolve_api_key("GEMINI_API_KEY", None, cfg)
    fal_key = resolve_api_key("FAL_KEY", None, cfg)

    ok, msg = False, ""
    errs: list[str] = []
    if engine_mode == "fal_ai":
        if not fal_key:
            raise RuntimeError("FAL_KEY가 등록되어 있지 않습니다 (설정 탭에서 등록).")
        ok, msg = _generate_with_fal_ai(prompt=prompt, out_path=tmp_png, fal_model=fal_model, api_key=fal_key)
    else:
        if gem_key:
            # 이중 폴백 루프 제거 + 저비용 flash 기본 / 명시적 pro 옵션 분리
            target_mdl = "nano-banana-pro-preview" if engine_mode == "nano_banana_pro" else "gemini-2.5-flash-image"
            try:
                ok, msg = _generate_with_nano_banana(prompt=prompt, out_path=tmp_png, model=target_mdl, api_key=gem_key)
            except Exception as exc:
                errs.append(f"{target_mdl}: {str(exc)[:100]}")
        if not ok and fal_key:
            try:
                ok, msg = _generate_with_fal_ai(prompt=prompt, out_path=tmp_png, fal_model=fal_model, api_key=fal_key)
            except Exception as exc:
                errs.append(f"fal.ai: {str(exc)[:100]}")

    if not ok or not tmp_png.is_file():
        if not (gem_key or fal_key):
            raise RuntimeError("GEMINI_API_KEY 또는 FAL_KEY가 등록되어 있지 않습니다 (무료 로컬 도표 모드나 직접 업로드를 이용해 보세요).")
        raise RuntimeError(" / ".join(errs) or msg or "이미지 AI 응답 실패")

    os.replace(tmp_png, out_png)
    for dest_dir in (by_ch_dir, e_ch_dir):
        try:
            shutil.copy2(out_png, dest_dir / out_png.name)
        except Exception:
            pass

    url = f"/project-files/{project_id}/assets/figures/{out_png.name}"
    item["path"] = str(out_png)
    item["filename"] = out_png.name
    item["docx_image_path"] = str(out_png)
    item["rel_url"] = url
    item["png_url"] = url
    item["engine"] = msg
    item["is_ai_image"] = True
    item["status"] = "GENERATED"
    item["error"] = ""
    item["updated_at"] = utc_now_iso()
    return item


def start_batch_generation_async(
    *,
    project_id: str,
    engine: str = "auto_hybrid",  # auto_hybrid | free_local_only | nano_banana | nano_banana_pro | fal_ai
    fal_model: str = "fal-ai/nano-banana",
    figure_ids: list[str] | None = None,
    chapter_ids: list[str] | None = None,
    visual_types: list[str] | None = None,
    only_pending: bool = True,
    max_batch: int = 5,
    budget_limit_usd: float = 1.0,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """비용·장수 상한을 지키며 독립 백그라운드 스레드에서 분할 배치 이미지 생성을 시작한다."""
    cfg = cfg or get_config()
    with _STUDIO_LOCK:
        cur = _STUDIO_JOBS.get(project_id)
        if cur and cur.get("running"):
            return {"status": "ALREADY_RUNNING", "job": cur}

    queue = _load_or_init_queue(project_id, cfg)
    items = queue.get("items") or []
    if not items:
        raise ValueError("생성할 시각화 기획 슬롯이 없습니다. 먼저 [1단계: 시각화 기획 생성]을 실행하세요.")

    fid_set = set(figure_ids) if figure_ids else None
    ch_set = set(chapter_ids) if chapter_ids else None
    vt_set = {t.upper() for t in visual_types} if visual_types else None

    selected: list[dict[str, Any]] = []
    for it in items:
        if it.get("status") == "SKIPPED":
            continue
        if fid_set is not None and it["figure_id"] not in fid_set:
            continue
        if ch_set is not None and it["chapter_id"] not in ch_set:
            continue
        if vt_set is not None and it.get("type", "C").upper() not in vt_set:
            continue
        if only_pending and fid_set is None and it.get("status") in ("GENERATED", "UPLOADED"):
            continue
        selected.append(it)

    if max_batch and int(max_batch) > 0:
        selected = selected[: int(max_batch)]

    if not selected:
        return {"status": "NOTHING_TO_GENERATE", "message": "조건에 해당하는 미생성 이미지가 없습니다."}

    stop_ev = _STUDIO_STOPS.setdefault(project_id, threading.Event())
    stop_ev.clear()

    job_info = {
        "running": True,
        "engine": engine,
        "total": len(selected),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "spent_usd_est": 0.0,
        "budget_limit_usd": float(budget_limit_usd or 0.0),
        "current_figure": "",
        "message": f"{len(selected)}장 분할 배치 생성 시작 ({engine})...",
        "started_at": utc_now_iso(),
        "finished_at": "",
    }
    _STUDIO_JOBS[project_id] = job_info

    def _worker() -> None:
        ws = cfg.project_dir(project_id)
        e_vis_root = cfg.e_projects_dir / project_id / "visuals"
        spent = 0.0
        target_ids = [x["figure_id"] for x in selected]
        try:
            q_live = _load_or_init_queue(project_id, cfg)
            by_id = {x["figure_id"]: x for x in q_live.get("items", [])}
            for idx, fid in enumerate(target_ids, 1):
                if stop_ev.is_set():
                    job_info["message"] = f"사용자 중단 — {job_info['succeeded']}/{len(target_ids)}장 저장 완료"
                    break
                it = by_id.get(fid)
                if not it:
                    continue
                job_info["current_figure"] = fid
                use_paid = (
                    engine in ("nano_banana", "nano_banana_pro", "fal_ai")
                    or (engine == "auto_hybrid" and it.get("type") in ("A", "B"))
                )
                unit_cost = ENGINE_UNIT_COST_USD.get(engine, 0.039) if use_paid else 0.0
                if budget_limit_usd > 0 and use_paid and (spent + unit_cost) > budget_limit_usd + 1e-6:
                    job_info["message"] = f"예산 상한(${budget_limit_usd:.2f}) 도달로 안전 정지 ({job_info['succeeded']}장 완료)"
                    break

                job_info["message"] = f"[{idx}/{len(target_ids)}] {fid} ({'유료 AI' if use_paid else '무료 로컬'}) 생성 중..."
                try:
                    if use_paid:
                        paid_mode = engine if engine in ("fal_ai", "nano_banana_pro") else "nano_banana"
                        _render_single_paid_ai(
                            it,
                            project_id=project_id,
                            engine_mode=paid_mode,
                            fal_model=fal_model,
                            ws=ws,
                            e_vis_root=e_vis_root,
                            cfg=cfg,
                        )
                        spent = round(spent + unit_cost, 3)
                        job_info["spent_usd_est"] = spent
                    else:
                        _render_single_free_local(it, project_id=project_id, ws=ws, e_vis_root=e_vis_root)
                    job_info["succeeded"] += 1
                except Exception as exc:
                    it["status"] = "ERROR"
                    it["error"] = str(exc)[:220]
                    it["updated_at"] = utc_now_iso()
                    job_info["failed"] += 1
                job_info["processed"] = idx
                _save_queue(project_id, q_live, cfg)
                time.sleep(0.05)

            # 배치 종료 후 메인 파이프라인(visuals_plan.json / state.json) 자동 결합 동기화
            sync_studio_to_pipeline(project_id, cfg=cfg)
            if not stop_ev.is_set() and "예산 상한" not in job_info["message"]:
                job_info["message"] = f"배치 완료: 성공 {job_info['succeeded']}장 · 실패 {job_info['failed']}장 (추정 ${spent:.2f})"
        finally:
            job_info["running"] = False
            job_info["current_figure"] = ""
            job_info["finished_at"] = utc_now_iso()

    threading.Thread(target=_worker, daemon=True, name=f"img-studio-{project_id}").start()
    return {"status": "STARTED", "job": job_info}


def stop_batch_generation(project_id: str) -> dict[str, Any]:
    ev = _STUDIO_STOPS.get(project_id)
    if ev:
        ev.set()
    return {"status": "STOP_REQUESTED", "project_id": project_id}


def update_queue_item(
    *,
    project_id: str,
    figure_id: str,
    updates: dict[str, Any],
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    queue = _load_or_init_queue(project_id, cfg)
    rec = next((x for x in queue.get("items", []) if x.get("figure_id") == figure_id), None)
    if not rec:
        raise FileNotFoundError(f"Figure not found: {figure_id}")

    for field in ("title_ko", "narrative_ko", "prompt", "target_section"):
        if field in updates and updates[field] is not None:
            rec[field] = str(updates[field]).strip()
    if updates.get("type") in ("A", "B", "C", "D"):
        tc = str(updates["type"]).upper()
        rec["type"] = tc
        rec["visual_type"] = VISUAL_TYPE_META[tc]["visual_type"]
        rec["aspect_ratio"] = VISUAL_TYPE_META[tc]["aspect_ratio"]
    if updates.get("status") in ("PENDING", "SKIPPED"):
        rec["status"] = updates["status"]
    rec["updated_at"] = utc_now_iso()
    _save_queue(project_id, queue, cfg)
    return {"status": "UPDATED", "item": rec}


def upload_custom_image(
    *,
    project_id: str,
    figure_id: str,
    image_base64: str,
    original_filename: str = "upload.png",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """사용자가 외부에서 준비한 이미지(PNG/JPG/WEBP)를 해당 슬롯에 무료(0원)로 결합한다."""
    from PIL import Image

    cfg = cfg or get_config()
    queue = _load_or_init_queue(project_id, cfg)
    rec = next((x for x in queue.get("items", []) if x.get("figure_id") == figure_id), None)
    if not rec:
        raise FileNotFoundError(f"Figure not found: {figure_id}")

    b64_clean = re.sub(r"^data:image/[^;]+;base64,", "", image_base64.strip())
    raw_bytes = base64.b64decode(b64_clean)

    ws = cfg.project_dir(project_id)
    cid = rec["chapter_id"]
    fig_dir = ws / "assets" / "figures"
    by_ch_dir = ws / "assets" / "by_chapter" / cid
    e_ch_dir = cfg.e_projects_dir / project_id / "visuals" / "by_chapter" / cid
    for d in (fig_dir, by_ch_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    out_png = fig_dir / f"{figure_id}.png"
    with Image.open(io.BytesIO(raw_bytes)) as img:
        rgb = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
        rgb.save(out_png, format="PNG", dpi=(300, 300), optimize=True)

    for d in (by_ch_dir, e_ch_dir):
        try:
            shutil.copy2(out_png, d / out_png.name)
        except Exception:
            pass

    url = f"/project-files/{project_id}/assets/figures/{out_png.name}"
    rec["path"] = str(out_png)
    rec["filename"] = out_png.name
    rec["docx_image_path"] = str(out_png)
    rec["rel_url"] = url
    rec["png_url"] = url
    rec["engine"] = f"User Upload ({original_filename} · 무료)"
    rec["status"] = "UPLOADED"
    rec["error"] = ""
    rec["updated_at"] = utc_now_iso()
    _save_queue(project_id, queue, cfg)
    sync_studio_to_pipeline(project_id, cfg=cfg)
    return {"status": "UPLOADED", "item": rec}


def sync_studio_to_pipeline(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """이미지 스튜디오에서 확보(생성+업로드)된 도판들을 메인 파이프라인(visuals_plan.json · E:\\ · state.json)에 결합한다."""
    from subagent_orchestrator import load_project_state, save_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    assets_dir = ws / "assets"
    by_ch_dir = assets_dir / "by_chapter"
    e_vis_root = cfg.e_projects_dir / project_id / "visuals"
    by_ch_dir.mkdir(parents=True, exist_ok=True)
    e_vis_root.mkdir(parents=True, exist_ok=True)

    queue = _load_or_init_queue(project_id, cfg)
    ready_items = [x for x in (queue.get("items") or []) if x.get("status") in ("GENERATED", "UPLOADED")]

    by_ch_counts: dict[str, int] = {}
    ai_cnt = 0
    svg_cnt = 0
    png_cnt = 0
    for r in ready_items:
        cid = r.get("chapter_id", "ch01")
        by_ch_counts[cid] = by_ch_counts.get(cid, 0) + 1
        if not str(r.get("data_source") or r.get("source_note") or "").strip():
            narr_txt = str(r.get("narrative_ko") or "")
            m_src = re.search(r"\((?:자료|출처)\s*:\s*([^)]+)\)", narr_txt)
            if m_src:
                r["data_source"] = m_src.group(1).strip()
            else:
                cites_in_narr = re.findall(r"\[SRC-\d+\]", narr_txt)
                if cites_in_narr:
                    r["data_source"] = ", ".join(dict.fromkeys(cites_in_narr)) + " 기반 재구성"
                else:
                    r["data_source"] = f"《{st.get('topic_ko', '')}》 {r.get('target_section') or cid} 본문 근거 기반"
        if r.get("is_ai_image"):
            ai_cnt += 1
        else:
            svg_cnt += 1
        if str(r.get("filename", "")).lower().endswith(".png") or r.get("docx_image_path"):
            png_cnt += 1

    manifest_payload = {
        "project_id": project_id,
        "generated_at": utc_now_iso(),
        "generation_mode": "decoupled_image_studio",
        "per_chapter_target": int(queue.get("per_chapter_count") or 0),
        "total_generated": len(ready_items),
        "ai_images_count": ai_cnt,
        "svg_charts_count": svg_cnt,
        "png_rasterized_count": png_cnt,
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_counts,
        "visuals": ready_items,
    }
    m_txt = json.dumps(manifest_payload, ensure_ascii=False, indent=2)
    (assets_dir / "visuals_plan.json").write_text(m_txt, encoding="utf-8")
    try:
        (e_vis_root / "visuals_plan.json").write_text(m_txt, encoding="utf-8")
    except Exception:
        pass

    guide_lines = [
        f"# 《{st.get('topic_ko', project_id)}》 시각화 줄글 해설 가이드 (이미지 스튜디오 결합)",
        "",
        f"총 **{len(ready_items)}종**의 시각화 자료(AI 실사·도해 {ai_cnt}종 / 무료 벡터 차트·업로드 {svg_cnt}종)가 본문 및 6단계 출판과 결합 준비되었습니다.",
        "",
    ]
    for r in ready_items:
        guide_lines.extend([f"## {r.get('title_ko', r['figure_id'])}", "", r.get("narrative_ko", ""), ""])
    g_txt = "\n".join(guide_lines)
    (assets_dir / "visuals_text_guide.md").write_text(g_txt, encoding="utf-8")
    try:
        (e_vis_root / "visuals_text_guide.md").write_text(g_txt, encoding="utf-8")
    except Exception:
        pass

    # state.json 체크포인트 및 Stage 5 상태 갱신
    st.setdefault("checkpoint", {})["completed_visuals"] = sorted(r["figure_id"] for r in ready_items)
    st.setdefault("options", {})["visuals_per_chapter"] = int(queue.get("per_chapter_count") or 0)
    st["local_visuals_dir"] = str(by_ch_dir)
    st["e_visuals_dir"] = str(e_vis_root)

    total_active = sum(1 for x in (queue.get("items") or []) if x.get("status") != "SKIPPED")
    pct = 100 if (total_active == 0 or len(ready_items) >= total_active) else int((len(ready_items) / max(1, total_active)) * 100)
    for s in st.get("stages", []):
        if s.get("stage_id") == "stage5_visuals_generate":
            if ready_items or int(queue.get("per_chapter_count") or 0) == 0:
                s["status"] = "DONE" if pct >= 100 else "PAUSED"
                s["progress"] = pct
                s["current_action"] = f"이미지 스튜디오 결합 완료: {len(ready_items)}/{total_active}종 확보 (6단계 출판 반영 가능)"
                s["metrics"] = {
                    "total_visuals": len(ready_items),
                    "planned_visuals": total_active,
                    "per_chapter": int(queue.get("per_chapter_count") or 0),
                    "ai_images": ai_cnt,
                    "svg_charts": svg_cnt,
                }
    save_project_state(st, cfg)
    return {
        "status": "SYNCED",
        "bound_ready_count": len(ready_items),
        "total_planned": total_active,
        "progress_pct": pct,
        "by_chapter_counts": by_ch_counts,
    }
