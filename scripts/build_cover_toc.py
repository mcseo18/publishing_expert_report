"""전문 교재 표지(Cover) · 머리말(Preface) · 전체 목차(Table of Contents) 제작 모듈.

기능:
- 프로젝트의 master_outline.yaml과 사용자 커스텀 표지 설정(제목·부제·영문제목·저자·출판처·판형·테마·머리말)을 결합해
  출판급 표지 + 속표지/머리말 + 부·장·절·예상쪽수가 완비된 전체 목차 페이지를 생성한다.
- 선택적으로 fal.ai API 또는 Gemini 나노바나나로 표지 실사/일러스트 이미지를 생성하거나,
  API 미사용 시 출판급 벡터 SVG 커버 아트워크를 자동 합성한다.
- 산출물 (projects/<pid>/exports/front_matter/ 및 E:\\SMC_Report_Platform_Data\\projects\\<pid>\\exports\\front_matter\\):
  1. cover_and_toc.html  (대시보드 실시간 미리보기 및 인쇄 겸용)
  2. cover_and_toc.pdf   (신국판 / B5 / A4 인쇄 규격 PDF)
  3. cover_and_toc.docx  (편집 가능한 Word 문서)
  4. cover_and_toc.md    (마크다운 목차·서지 정보)
"""
from __future__ import annotations

import base64
import html
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from build_outputs import _render_html_to_pdf
from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key
from visual_studio import _generate_with_fal_ai, _generate_with_nano_banana

COVER_THEMES: dict[str, dict[str, str]] = {
    "golden_wheat": {
        "name_ko": "황금 밀밭 · 디지털 골드 (추천)",
        "bg_start": "#0f291e",
        "bg_end": "#1e3a2f",
        "accent": "#eab308",
        "accent_soft": "#fef08a",
        "ink": "#ffffff",
        "toc_accent": "#155e3b",
    },
    "academic_navy": {
        "name_ko": "학술 단행본 · 딥 네이비",
        "bg_start": "#0b1936",
        "bg_end": "#1e3a5f",
        "accent": "#38bdf8",
        "accent_soft": "#bae6fd",
        "ink": "#ffffff",
        "toc_accent": "#1e3a8a",
    },
    "emerald_agri": {
        "name_ko": "스마트팜 · 에메랄드 그린",
        "bg_start": "#063b2c",
        "bg_end": "#0f5e48",
        "accent": "#34d399",
        "accent_soft": "#a7f3d0",
        "ink": "#ffffff",
        "toc_accent": "#047857",
    },
    "slate_minimal": {
        "name_ko": "모던 연구보고서 · 슬레이트 미니멀",
        "bg_start": "#111827",
        "bg_end": "#273449",
        "accent": "#f59e0b",
        "accent_soft": "#fde68a",
        "ink": "#ffffff",
        "toc_accent": "#1f2937",
    },
}

TRIM_SPECS: dict[str, dict[str, str]] = {
    "shinkuk": {"label": "신국판 (152 × 225 mm)", "page_size": "152mm 225mm", "margin": "16mm 14mm 18mm 16mm", "cover_h": "190mm", "body_pt": "9.2pt"},
    "b5": {"label": "B5 대학교재 (182 × 257 mm)", "page_size": "182mm 257mm", "margin": "18mm 16mm 18mm 18mm", "cover_h": "220mm", "body_pt": "9.8pt"},
    "a4": {"label": "A4 마스터판 (210 × 297 mm)", "page_size": "210mm 297mm", "margin": "20mm 18mm 20mm 18mm", "cover_h": "255mm", "body_pt": "10.2pt"},
}


def _default_cover_artwork_svg(theme_cfg: dict[str, str], title_ko: str) -> str:
    acc = theme_cfg["accent"]
    soft = theme_cfg["accent_soft"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 320" width="800" height="320">
  <defs>
    <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{acc}" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="{soft}" stop-opacity="0.06"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="800" height="320" rx="14" fill="url(#g1)" stroke="{acc}" stroke-opacity="0.35" stroke-width="1.2"/>
  <!-- 정밀농업 위성/센서 격자 -->
  <g stroke="{soft}" stroke-opacity="0.18" stroke-width="1">
    <line x1="0" y1="64" x2="800" y2="64"/><line x1="0" y1="128" x2="800" y2="128"/>
    <line x1="0" y1="192" x2="800" y2="192"/><line x1="0" y1="256" x2="800" y2="256"/>
    <line x1="160" y1="0" x2="160" y2="320"/><line x1="320" y1="0" x2="320" y2="320"/>
    <line x1="480" y1="0" x2="480" y2="320"/><line x1="640" y1="0" x2="640" y2="320"/>
  </g>
  <!-- 생육모형 시그모이드 성장곡선 & 등고선 -->
  <path d="M 40 270 C 180 265, 250 110, 410 95 C 550 82, 630 140, 760 60" fill="none" stroke="{acc}" stroke-width="3.5" stroke-linecap="round"/>
  <path d="M 40 288 C 200 280, 290 175, 450 160 C 590 148, 660 190, 760 130" fill="none" stroke="{soft}" stroke-width="2" stroke-dasharray="6 5" opacity="0.8"/>
  <!-- 스타일라이즈드 밀 이삭(Wheat Spike) 모티프 -->
  <g transform="translate(625, 165)" stroke="{acc}" fill="{acc}" fill-opacity="0.82">
    <line x1="0" y1="115" x2="0" y2="-95" stroke="{soft}" stroke-width="2.5"/>
    <ellipse cx="-14" cy="-65" rx="7" ry="15" transform="rotate(-28 -14 -65)"/>
    <ellipse cx="14" cy="-58" rx="7" ry="15" transform="rotate(28 14 -58)"/>
    <ellipse cx="-16" cy="-35" rx="7.5" ry="16" transform="rotate(-30 -16 -35)"/>
    <ellipse cx="16" cy="-28" rx="7.5" ry="16" transform="rotate(30 16 -28)"/>
    <ellipse cx="-17" cy="-4" rx="8" ry="17" transform="rotate(-30 -17 -4)"/>
    <ellipse cx="17" cy="4" rx="8" ry="17" transform="rotate(30 17 4)"/>
    <ellipse cx="-15" cy="28" rx="7.5" ry="16" transform="rotate(-28 -15 28)"/>
    <ellipse cx="15" cy="36" rx="7.5" ry="16" transform="rotate(28 15 36)"/>
    <ellipse cx="0" cy="-92" rx="6" ry="15"/>
  </g>
  <!-- 센서 노드 포인트 -->
  <g fill="{soft}">
    <circle cx="160" cy="242" r="5"/><circle cx="320" cy="130" r="6"/><circle cx="480" cy="100" r="6"/>
  </g>
  <text x="36" y="42" fill="{soft}" font-size="13" font-weight="700" font-family="Malgun Gothic, sans-serif">DATA-DRIVEN PRECISION AGRONOMY · CROP MODELING EDITION</text>
  <text x="36" y="300" fill="{soft}" opacity="0.85" font-size="12" font-family="Malgun Gothic, sans-serif">{html.escape(title_ko)} — Evidence-Based Academic Textbook</text>
</svg>"""


def load_cover_settings(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    proj_ws = cfg.project_dir(project_id)
    bp_path = proj_ws / "blueprints" / "master_outline.yaml"
    outline = yaml.safe_load(bp_path.read_text(encoding="utf-8")) if bp_path.is_file() else {}
    meta = outline.get("book_metadata") or {}
    parts = outline.get("parts") or []
    ch_count = sum(len(pt.get("chapters") or []) for pt in parts)
    total_pages = int(meta.get("target_total_pages") or meta.get("target_pages") or 500)

    defaults: dict[str, Any] = {
        "title_ko": meta.get("title_ko") or project_id,
        "subtitle_ko": "생육생리·양분분배·작물생육모형에서 디지털 트윈·가공품질까지",
        "title_en": meta.get("title_en") or "",
        "author": "스마트농업·작물과학 전문 교재 집필위원회",
        "publisher": "SMC 전문 교재 출판 플랫폼",
        "edition": f"초판 1쇄 ({datetime.now().strftime('%Y년 %m월')})",
        "target_audience": meta.get("target_audience") or "대학 전공 심화, 대학원생, 연구자 및 선도 농업인",
        "theme": "golden_wheat",
        "trim_format": "b5",
        "use_ai_cover": False,
        "use_fal_ai": False,
        "fal_model": "fal-ai/nano-banana",
        "preface_ko": (
            f"본 교재 《{meta.get('title_ko') or project_id}》는 국내외 1차 공식 기관 보고서와 핵심 SCI 학술 문헌을 "
            f"근거로 삼아 총 {len(parts)}부 {ch_count}장({total_pages}쪽 규모)으로 집필한 전문 대학교재이자 현장 실무 지침서입니다. "
            "각 단원은 기초 원리에서 정량 모형·디지털 현장 적용·오해와 진실·이해도 점검 문제풀이까지 일관된 체계로 구성되었습니다."
        ),
    }
    saved_p = proj_ws / "exports" / "front_matter" / "cover_settings.json"
    if saved_p.is_file():
        try:
            saved = json.loads(saved_p.read_text(encoding="utf-8"))
            defaults.update({k: v for k, v in saved.items() if v is not None})
        except Exception:
            pass

    fm_dir = proj_ws / "exports" / "front_matter"
    files = {}
    for key, fname in [
        ("html", "cover_and_toc.html"),
        ("pdf", "cover_and_toc.pdf"),
        ("docx", "cover_and_toc.docx"),
        ("md", "cover_and_toc.md"),
    ]:
        p = fm_dir / fname
        if p.is_file():
            files[key] = f"/project-files/{project_id}/exports/front_matter/{fname}"

    return {
        "project_id": project_id,
        "settings": defaults,
        "themes": COVER_THEMES,
        "trim_specs": TRIM_SPECS,
        "parts_count": len(parts),
        "chapter_count": ch_count,
        "target_pages": total_pages,
        "files": files,
    }


def _compute_toc_with_pages(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """각 부·단원·절에 예상 시작 쪽수를 부여한 목차 구조를 생성한다."""
    cur_page = 1
    out_parts: list[dict[str, Any]] = []
    for pt in outline.get("parts") or []:
        pt_start = cur_page
        chs_out: list[dict[str, Any]] = []
        for ch in pt.get("chapters") or []:
            ch_pages = max(10, int(ch.get("target_pages") or 30))
            secs = ch.get("sections") or []
            sec_step = max(2, ch_pages // max(1, len(secs)))
            secs_out = []
            for s_idx, s_title in enumerate(secs):
                secs_out.append({"title": str(s_title), "page": cur_page + min(ch_pages - 2, s_idx * sec_step)})
            chs_out.append(
                {
                    "chapter_id": ch.get("chapter_id", ""),
                    "chapter_number": ch.get("chapter_number", 0),
                    "title": ch.get("title", ""),
                    "summary_ko": ch.get("summary_ko", ""),
                    "start_page": cur_page,
                    "end_page": cur_page + ch_pages - 1,
                    "target_pages": ch_pages,
                    "sections": secs_out,
                }
            )
            cur_page += ch_pages
        out_parts.append(
            {
                "part_number": pt.get("part_number", len(out_parts) + 1),
                "title": pt.get("title", ""),
                "start_page": pt_start,
                "pages": sum(c["target_pages"] for c in chs_out),
                "chapters": chs_out,
            }
        )
    return out_parts


def _build_cover_toc_html(
    settings: dict[str, Any],
    toc_parts: list[dict[str, Any]],
    art_data_uri: str,
    total_pages: int,
    chapter_count: int,
    source_count: int,
) -> str:
    theme = COVER_THEMES.get(settings.get("theme", "golden_wheat"), COVER_THEMES["golden_wheat"])
    trim = TRIM_SPECS.get(settings.get("trim_format", "b5"), TRIM_SPECS["b5"])

    toc_blocks: list[str] = []
    for pt in toc_parts:
        ch_html = []
        for ch in pt["chapters"]:
            sec_lis = "".join(
                f'<div class="toc-sec"><span class="toc-sec-t">{html.escape(s["title"])}</span><span class="toc-dots"></span><span class="toc-pg">{s["page"]}</span></div>'
                for s in ch["sections"]
            )
            sum_html = f'<div class="toc-sum">{html.escape(ch["summary_ko"])}</div>' if ch.get("summary_ko") else ""
            ch_html.append(
                f"""
                <div class="toc-ch">
                  <div class="toc-ch-head">
                    <span class="toc-ch-title">{html.escape(ch['title'])}</span>
                    <span class="toc-dots"></span>
                    <span class="toc-ch-pg">p.{ch['start_page']}</span>
                  </div>
                  {sum_html}
                  <div class="toc-secs">{sec_lis}</div>
                </div>"""
            )
        toc_blocks.append(
            f"""
            <div class="toc-part">
              <div class="toc-part-head">
                <span class="toc-part-badge">제{pt['part_number']}부</span>
                <span class="toc-part-title">{html.escape(pt['title'])}</span>
                <span class="toc-part-pg">p.{pt['start_page']} ({pt['pages']}p)</span>
              </div>
              {''.join(ch_html)}
            </div>"""
        )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<title>{html.escape(settings['title_ko'])} — 표지 및 전체 목차</title>
<style>
@page {{
  size: {trim['page_size']};
  margin: {trim['margin']};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: 'Malgun Gothic', 'Pretendard', 'Apple SD Gothic Neo', sans-serif;
  color: #0f172a;
  background: #e2e8f0;
  font-size: {trim['body_pt']};
  line-height: 1.62;
}}
.page-sheet {{
  background: #ffffff;
  max-width: 820px;
  margin: 18px auto;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.16);
  border-radius: 6px;
  overflow: hidden;
}}
@media print {{
  body {{ background: #fff; }}
  .page-sheet {{ max-width: none; margin: 0; box-shadow: none; border-radius: 0; page-break-after: always; }}
  .page-sheet:last-child {{ page-break-after: auto; }}
}}
/* 1. 표지 */
.cover {{
  min-height: {trim['cover_h']};
  background: linear-gradient(155deg, {theme['bg_start']} 0%, {theme['bg_end']} 100%);
  color: {theme['ink']};
  padding: 42px 44px 36px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
}}
.cover-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1.5px solid {theme['accent']};
  padding-bottom: 10px;
  font-size: 11px;
  letter-spacing: 1.4px;
  color: {theme['accent_soft']};
  font-weight: 700;
}}
.cover-main {{ margin: 26px 0 18px; }}
.cover-kicker {{
  display: inline-block;
  background: rgba(255,255,255,0.12);
  border: 1px solid {theme['accent']};
  color: {theme['accent_soft']};
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 700;
  margin-bottom: 14px;
}}
.cover-title {{
  font-size: 36px;
  font-weight: 900;
  margin: 0 0 10px;
  letter-spacing: -0.8px;
  line-height: 1.2;
}}
.cover-en {{
  font-size: 16px;
  font-weight: 600;
  color: {theme['accent_soft']};
  margin: 0 0 14px;
  letter-spacing: 0.4px;
}}
.cover-sub {{
  font-size: 14.5px;
  color: rgba(255,255,255,0.88);
  margin: 0;
  max-width: 620px;
}}
.cover-art {{
  margin: 18px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.22);
}}
.cover-art img {{ width: 100%; display: block; max-height: 270px; object-fit: cover; }}
.cover-meta-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 12px;
}}
.cover-stat {{
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 8px;
  padding: 9px 12px;
}}
.cover-stat-v {{ font-size: 15px; font-weight: 800; color: {theme['accent_soft']}; }}
.cover-stat-l {{ font-size: 10.5px; color: rgba(255,255,255,0.75); }}
.cover-footer {{
  margin-top: 22px;
  padding-top: 14px;
  border-top: 1px solid rgba(255,255,255,0.22);
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
}}
.cover-author {{ font-size: 14px; font-weight: 700; }}
.cover-pub {{ text-align: right; font-size: 12px; color: {theme['accent_soft']}; }}

/* 2. 속표지 · 머리말 */
.inner-page {{ padding: 38px 42px; }}
.preface-box {{
  border-left: 4px solid {theme['toc_accent']};
  background: #f8fafc;
  padding: 18px 20px;
  border-radius: 0 8px 8px 0;
  margin: 16px 0 24px;
}}
.info-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 14px; }}
.info-table th, .info-table td {{ border: 1px solid #cbd5e1; padding: 8px 11px; text-align: left; }}
.info-table th {{ background: #f1f5f9; width: 26%; color: #334155; }}

/* 3. 목차 페이지 */
.toc-banner {{
  border-bottom: 2.5px solid {theme['toc_accent']};
  padding-bottom: 10px;
  margin-bottom: 18px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}}
.toc-banner h1 {{ margin: 0; font-size: 22px; color: {theme['toc_accent']}; }}
.toc-part {{ margin-bottom: 14px; page-break-inside: avoid; }}
.toc-part-head {{
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f1f5f9;
  border-left: 4px solid {theme['toc_accent']};
  padding: 6px 10px;
  border-radius: 0 6px 6px 0;
  font-weight: 800;
  color: #0f172a;
}}
.toc-part-badge {{
  background: {theme['toc_accent']};
  color: #fff;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
}}
.toc-part-pg {{ margin-left: auto; font-size: 11.5px; color: #475569; font-weight: 700; }}
.toc-ch {{ padding: 7px 6px 4px 12px; }}
.toc-ch-head {{ display: flex; align-items: baseline; font-weight: 800; font-size: 13.5px; color: #1e293b; }}
.toc-dots {{ flex: 1; border-bottom: 1px dotted #94a3b8; margin: 0 8px; }}
.toc-ch-pg {{ font-weight: 800; color: {theme['toc_accent']}; font-size: 12px; }}
.toc-sum {{ font-size: 11.5px; color: #475569; margin: 3px 0 4px; padding-left: 4px; }}
.toc-secs {{ padding-left: 14px; }}
.toc-sec {{ display: flex; align-items: baseline; font-size: 12px; color: #334155; padding: 1.5px 0; }}
.toc-pg {{ font-size: 11.5px; color: #64748b; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>

<!-- PAGE 1: 표지 -->
<section class="page-sheet">
  <div class="cover">
    <div class="cover-top">
      <span>PROFESSIONAL ACADEMIC TEXTBOOK · EVIDENCE-BASED EDITION</span>
      <span>{html.escape(trim['label'])}</span>
    </div>
    <div class="cover-main">
      <div class="cover-kicker">{len(toc_parts)}부 {chapter_count}장 · 근거 기반 전문 대학교재</div>
      <h1 class="cover-title">{html.escape(settings['title_ko'])}</h1>
      <div class="cover-en">{html.escape(settings['title_en'])}</div>
      <p class="cover-sub">{html.escape(settings['subtitle_ko'])}</p>
    </div>
    <div class="cover-art">
      <img src="{art_data_uri}" alt="표지 일러스트" />
    </div>
    <div class="cover-meta-grid">
      <div class="cover-stat"><div class="cover-stat-v">{len(toc_parts)}부 {chapter_count}장</div><div class="cover-stat-l">체계적 단원 구성</div></div>
      <div class="cover-stat"><div class="cover-stat-v">약 {total_pages}쪽</div><div class="cover-stat-l">목표 전문 분량</div></div>
      <div class="cover-stat"><div class="cover-stat-v">{source_count}건 1차 근거</div><div class="cover-stat-l">국내외 학술·기관 검증</div></div>
    </div>
    <div class="cover-footer">
      <div>
        <div class="cover-author">{html.escape(settings['author'])}</div>
        <div style="font-size:11.5px;opacity:0.8;margin-top:3px">대상 독자: {html.escape(settings['target_audience'])}</div>
      </div>
      <div class="cover-pub">
        <div style="font-weight:800;font-size:13.5px">{html.escape(settings['publisher'])}</div>
        <div>{html.escape(settings['edition'])}</div>
      </div>
    </div>
  </div>
</section>

<!-- PAGE 2: 속표지 · 머리말 · 서지 정보 -->
<section class="page-sheet">
  <div class="inner-page">
    <div class="toc-banner">
      <h1>머리말 및 교재 안내</h1>
      <span style="font-size:12px;color:#64748b">PREFACE &amp; BOOK INFORMATION</span>
    </div>
    <h2 style="margin:0 0 6px;font-size:18px">《{html.escape(settings['title_ko'])}》</h2>
    <div style="color:#475569;margin-bottom:14px">{html.escape(settings['title_en'])} — {html.escape(settings['subtitle_ko'])}</div>
    <div class="preface-box">
      {html.escape(settings['preface_ko'])}
    </div>
    <h3 style="margin:18px 0 8px;color:{theme['toc_accent']}">교재 서지 및 제작 규격</h3>
    <table class="info-table">
      <tr><th>도서명 (국문 / 영문)</th><td><strong>{html.escape(settings['title_ko'])}</strong> ({html.escape(settings['title_en'])})</td></tr>
      <tr><th>집필 / 책임 편찬</th><td>{html.escape(settings['author'])}</td></tr>
      <tr><th>발행처 / 판차</th><td>{html.escape(settings['publisher'])} · {html.escape(settings['edition'])}</td></tr>
      <tr><th>인쇄 판형 규격</th><td>{html.escape(trim['label'])}</td></tr>
      <tr><th>전체 구성 및 분량</th><td>총 {len(toc_parts)}부 {chapter_count}개 단원 · 약 {total_pages}쪽 (근거 문헌 {source_count}건)</td></tr>
      <tr><th>대상 독자</th><td>{html.escape(settings['target_audience'])}</td></tr>
    </table>
  </div>
</section>

<!-- PAGE 3+: 전체 목차 -->
<section class="page-sheet">
  <div class="inner-page">
    <div class="toc-banner">
      <h1>목 차 (Table of Contents)</h1>
      <span style="font-size:12px;color:#64748b">《{html.escape(settings['title_ko'])}》 · {len(toc_parts)}부 {chapter_count}장</span>
    </div>
    {''.join(toc_blocks)}
  </div>
</section>

</body>
</html>
"""


def _build_cover_toc_docx(
    settings: dict[str, Any],
    toc_parts: list[dict[str, Any]],
    art_png_path: Path | None,
    out_docx: Path,
    total_pages: int,
    chapter_count: int,
    source_count: int,
) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal.font.size = Pt(10)

    # 1. 표지 페이지
    p_top = doc.add_paragraph("PROFESSIONAL ACADEMIC TEXTBOOK · EVIDENCE-BASED EDITION")
    p_top.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_top.runs[0].font.size = Pt(9)
    p_top.runs[0].font.color.rgb = RGBColor(0x47, 0x55, 0x69)

    p_sp = doc.add_paragraph()
    p_sp.paragraph_format.space_before = Pt(36)

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = p_title.add_run(settings["title_ko"])
    rt.bold = True
    rt.font.size = Pt(28)
    rt.font.color.rgb = RGBColor(0x0F, 0x29, 0x1E)

    if settings.get("title_en"):
        p_en = doc.add_paragraph()
        p_en.alignment = WD_ALIGN_PARAGRAPH.CENTER
        re_run = p_en.add_run(settings["title_en"])
        re_run.font.size = Pt(14)
        re_run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

    if settings.get("subtitle_ko"):
        p_sub = doc.add_paragraph()
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rs = p_sub.add_run(settings["subtitle_ko"])
        rs.font.size = Pt(12)
        rs.font.color.rgb = RGBColor(0x33, 0x41, 0x55)

    if art_png_path and art_png_path.is_file():
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.add_run().add_picture(str(art_png_path), width=Inches(5.2))

    p_meta = doc.add_paragraph()
    p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_meta.paragraph_format.space_before = Pt(36)
    p_meta.add_run(
        f"{len(toc_parts)}부 {chapter_count}장 · 약 {total_pages}쪽 · 1차 근거 {source_count}건\n\n"
        f"{settings['author']}\n"
        f"{settings['publisher']} · {settings['edition']}"
    ).font.size = Pt(11)

    doc.add_page_break()

    # 2. 머리말
    h_pre = doc.add_heading("머리말 및 교재 안내", level=1)
    h_pre.runs[0].font.name = "Malgun Gothic"
    doc.add_paragraph(settings["preface_ko"])
    doc.add_paragraph(f"대상 독자: {settings['target_audience']}")
    doc.add_page_break()

    # 3. 전체 목차
    h_toc = doc.add_heading(f"목 차 — 《{settings['title_ko']}》", level=1)
    h_toc.runs[0].font.name = "Malgun Gothic"

    for pt in toc_parts:
        p_pt = doc.add_paragraph()
        p_pt.paragraph_format.space_before = Pt(10)
        r_pt = p_pt.add_run(f"제{pt['part_number']}부. {pt['title']}  (p.{pt['start_page']})")
        r_pt.bold = True
        r_pt.font.size = Pt(11.5)
        r_pt.font.color.rgb = RGBColor(0x15, 0x5E, 0x3B)
        for ch in pt["chapters"]:
            p_ch = doc.add_paragraph()
            p_ch.paragraph_format.left_indent = Inches(0.2)
            p_ch.paragraph_format.space_after = Pt(2)
            r_ch = p_ch.add_run(f"{ch['title']}  ·····  p.{ch['start_page']}")
            r_ch.bold = True
            r_ch.font.size = Pt(10.5)
            for sec in ch["sections"]:
                p_s = doc.add_paragraph()
                p_s.paragraph_format.left_indent = Inches(0.45)
                p_s.paragraph_format.space_after = Pt(1)
                r_s = p_s.add_run(f"{sec['title']}  ·····  p.{sec['page']}")
                r_s.font.size = Pt(9.5)

    doc.save(str(out_docx))


def build_project_cover_and_toc(
    project_id: str,
    overrides: dict[str, Any] | None = None,
    *,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 표지 + 머리말 + 전체 목차(HTML · PDF · DOCX · MD)를 생성하고 E:\\에도 미러링한다."""
    cfg = cfg or get_config()
    proj_ws = cfg.project_dir(project_id)
    bp_path = proj_ws / "blueprints" / "master_outline.yaml"
    if not bp_path.is_file():
        raise FileNotFoundError(f"master_outline.yaml not found for {project_id}")
    outline = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}

    base_info = load_cover_settings(project_id, cfg)
    settings = {**base_info["settings"], **(overrides or {})}

    fm_dir = proj_ws / "exports" / "front_matter"
    fm_dir.mkdir(parents=True, exist_ok=True)
    (fm_dir / "cover_settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    toc_parts = _compute_toc_with_pages(outline)
    chapter_count = sum(len(pt["chapters"]) for pt in toc_parts)
    total_pages = sum(pt["pages"] for pt in toc_parts)

    # 프로젝트 수집 근거 수 조회
    state_p = cfg.index_dir / "subagent_runs" / project_id / "state.json"
    source_count = 0
    if state_p.is_file():
        try:
            st_raw = json.loads(state_p.read_text(encoding="utf-8"))
            source_count = len(st_raw.get("collected_sources") or [])
        except Exception:
            pass

    # 표지 일러스트 생성 (선택적 fal.ai / 나노바나나 → 기본 출판급 SVG)
    theme_cfg = COVER_THEMES.get(settings.get("theme", "golden_wheat"), COVER_THEMES["golden_wheat"])
    art_png_path: Path | None = None
    art_svg_path = fm_dir / "cover_art.svg"
    art_engine = "editorial_svg"

    if settings.get("use_ai_cover"):
        prompt = (
            f"Editorial scientific textbook cover artwork for '{settings['title_en'] or settings['title_ko']}', "
            "golden winter wheat field at sunrise overlaid with subtle clean precision agriculture sensor grid and data contour lines, "
            "photorealistic academic publication style, no text, no letters, high resolution 16:9."
        )
        cand_png = fm_dir / "cover_art.png"
        ok = False
        if settings.get("use_fal_ai"):
            fkey = resolve_api_key("FAL_KEY", None, cfg)
            if fkey:
                try:
                    ok, msg = _generate_with_fal_ai(prompt=prompt, out_path=cand_png, fal_model=settings.get("fal_model") or "fal-ai/nano-banana", api_key=fkey)
                    if ok:
                        art_png_path = cand_png
                        art_engine = msg
                except Exception:
                    ok = False
        if not ok:
            gkey = resolve_api_key("GEMINI_API_KEY", None, cfg)
            if gkey:
                try:
                    ok, msg = _generate_with_nano_banana(prompt=prompt, out_path=cand_png, api_key=gkey)
                    if ok:
                        art_png_path = cand_png
                        art_engine = msg
                except Exception:
                    ok = False

    if art_png_path and art_png_path.is_file():
        b64 = base64.b64encode(art_png_path.read_bytes()).decode("ascii")
        art_data_uri = f"data:image/png;base64,{b64}"
    else:
        svg_str = _default_cover_artwork_svg(theme_cfg, settings["title_ko"])
        art_svg_path.write_text(svg_str, encoding="utf-8")
        b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
        art_data_uri = f"data:image/svg+xml;base64,{b64}"

    # 1. HTML 생성
    html_text = _build_cover_toc_html(settings, toc_parts, art_data_uri, total_pages, chapter_count, source_count)
    out_html = fm_dir / "cover_and_toc.html"
    out_html.write_text(html_text, encoding="utf-8")

    # 2. PDF 생성
    out_pdf = fm_dir / "cover_and_toc.pdf"
    pdf_ok = True
    pdf_err = ""
    try:
        _render_html_to_pdf(html_text, out_pdf)
    except Exception as exc:
        pdf_ok = False
        pdf_err = str(exc)

    # 3. Word DOCX 생성
    out_docx = fm_dir / "cover_and_toc.docx"
    _build_cover_toc_docx(settings, toc_parts, art_png_path, out_docx, total_pages, chapter_count, source_count)

    # 4. Markdown 목차 생성
    md_lines = [
        f"# 《{settings['title_ko']}》 ({settings['title_en']})",
        "",
        f"> {settings['subtitle_ko']}",
        "",
        f"- **집필**: {settings['author']}",
        f"- **발행**: {settings['publisher']} · {settings['edition']}",
        f"- **판형 / 분량**: {TRIM_SPECS.get(settings['trim_format'], TRIM_SPECS['b5'])['label']} · 총 {len(toc_parts)}부 {chapter_count}장 (약 {total_pages}쪽)",
        f"- **생성 시각**: `{utc_now_iso()}`",
        "",
        "## 머리말",
        "",
        settings["preface_ko"],
        "",
        "## 전체 목차 (Table of Contents)",
        "",
    ]
    for pt in toc_parts:
        md_lines.append(f"### 제{pt['part_number']}부. {pt['title']} (p.{pt['start_page']})")
        for ch in pt["chapters"]:
            md_lines.append(f"- **{ch['title']}** (p.{ch['start_page']}~{ch['end_page']}, {ch['target_pages']}p)")
            for s in ch["sections"]:
                md_lines.append(f"  - {s['title']} ··· p.{s['page']}")
        md_lines.append("")
    out_md = fm_dir / "cover_and_toc.md"
    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    # E 드라이브 미러링
    e_fm = cfg.project_e_exports_dir(project_id) / "front_matter"
    e_fm.mkdir(parents=True, exist_ok=True)
    for f in fm_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, e_fm / f.name)

    files_urls = {
        "html": f"/project-files/{project_id}/exports/front_matter/cover_and_toc.html",
        "docx": f"/project-files/{project_id}/exports/front_matter/cover_and_toc.docx",
        "md": f"/project-files/{project_id}/exports/front_matter/cover_and_toc.md",
    }
    if out_pdf.is_file():
        files_urls["pdf"] = f"/project-files/{project_id}/exports/front_matter/cover_and_toc.pdf"

    return {
        "status": "OK",
        "project_id": project_id,
        "art_engine": art_engine,
        "pdf_ok": pdf_ok,
        "pdf_error": pdf_err,
        "parts_count": len(toc_parts),
        "chapter_count": chapter_count,
        "target_pages": total_pages,
        "local_dir": str(fm_dir),
        "e_mirror_dir": str(e_fm),
        "files": files_urls,
        "settings": settings,
    }
