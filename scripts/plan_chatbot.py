"""Antigravity · Google Gemini API 기반 대화형 교재 계획서 작성 챗봇 엔진.

기능:
1. 사용자가 제시한 주제어·핵심 키워드와 대화 메시지로 부(Part)·장(Chapter)·절(Section)·핵심내용 요약·표(Table) 구성·
   시각화(A/B/C/D 4유형) 구성·국/영문 검색 쿼리를 포함한 전문 교재 계획서를 반복 협의·생성한다.
2. 기본 AI 엔진: Antigravity · Google Gemini API (gemini-3.8-flash 우선, 폴백 체인 지원).
   선택 엔진: Gemini Pro / OpenAI / 로컬 Ollama Gemma 4.
3. 생성된 계획서를 현재 프로젝트의 청사진(master_outline.yaml, chNN.yaml)과 state.json(keywords_ko, keywords_en,
   domain_keywords, search_queries_ko, search_queries_en)에 즉시 반영하여 2단계 자동 수집, 자료실 학술 검색,
   심층 조사 챗봇 검색에 바로 활용한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key
from subagent_orchestrator import (
    _save_outline_files,
    append_event,
    approve_stage1_outline,
    create_project,
    load_project_state,
    save_project_state,
)

GEMINI_DEFAULT_CHAIN = [
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]

GEMINI_PRO_CHAIN = [
    "gemini-2.5-pro",
    "gemini-3-pro-preview",
    "gemini-3.8-flash",
]


def _chat_history_path(project_id: str, cfg: PlatformConfig) -> Path:
    d = cfg.project_dir(project_id) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d / "plan_chat_history.json"


def _plan_json_path(project_id: str, cfg: PlatformConfig) -> Path:
    d = cfg.project_dir(project_id) / "blueprints"
    d.mkdir(parents=True, exist_ok=True)
    return d / "book_plan_studio.json"


def _plan_md_path(project_id: str, cfg: PlatformConfig) -> Path:
    d = cfg.project_dir(project_id) / "blueprints"
    d.mkdir(parents=True, exist_ok=True)
    return d / "book_plan_studio.md"


def _seed_plan_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """기존 프로젝트 blueprint_preview가 있으면 챗봇 계획서 스키마로 변환해 초기값으로 제공한다."""
    bp = state.get("blueprint_preview") or {}
    meta = bp.get("book_metadata") or {}
    parts_in = bp.get("parts") or []
    parts_out: list[dict[str, Any]] = []
    for p_i, pt in enumerate(parts_in, 1):
        chs_out: list[dict[str, Any]] = []
        for c in pt.get("chapters") or []:
            ch_no = int(c.get("chapter_number") or (len(chs_out) + 1))
            cid = str(c.get("chapter_id") or f"ch{ch_no:02d}")
            chs_out.append(
                {
                    "chapter_id": cid,
                    "chapter_number": ch_no,
                    "title": str(c.get("title") or f"제{ch_no}장"),
                    "target_pages": int(c.get("target_pages") or 30),
                    "summary_ko": str(c.get("summary_ko") or ""),
                    "sections": list(c.get("sections") or []),
                    "tables": list(c.get("tables") or []),
                    "visuals": list(c.get("visuals") or []),
                    "keywords_ko": list(c.get("keywords_ko") or []),
                    "keywords_en": list(c.get("keywords_en") or []),
                }
            )
        parts_out.append(
            {
                "part_number": int(pt.get("part_number") or p_i),
                "title": str(pt.get("title") or f"제{p_i}부"),
                "summary_ko": str(pt.get("summary_ko") or ""),
                "chapters": chs_out,
            }
        )

    kws_ko = list(state.get("keywords_ko") or [])
    kws_en = list(state.get("keywords_en") or [])
    return {
        "book_title_ko": meta.get("title_ko") or state.get("topic_ko", ""),
        "book_title_en": meta.get("title_en") or state.get("topic_en", ""),
        "book_summary_ko": meta.get("book_summary_ko") or "",
        "target_audience": meta.get("target_audience") or state.get("target_audience", "대학 전공 심화, 연구자 및 현장 실무자"),
        "target_pages": int(meta.get("target_total_pages") or state.get("target_pages") or 400),
        "domain_keywords": list(bp.get("domain_keywords") or state.get("domain_keywords") or []),
        "search_queries_ko": list(state.get("search_queries_ko") or kws_ko[:8]),
        "search_queries_en": list(state.get("search_queries_en") or kws_en[:8]),
        "parts": parts_out,
    }


def render_plan_markdown(plan: dict[str, Any]) -> str:
    """구조화된 교재 계획서 JSON을 출판·검토용 마크다운 계획서로 렌더링한다."""
    if not plan or not plan.get("parts"):
        return (
            "# 교재 기획안 (작성 대기)\n\n"
            "왼쪽 챗봇 대화창에 **주제어·핵심 키워드**와 원하는 구성을 입력하면 "
            "Antigravity · Gemini API가 **부 · 장 · 절 · 핵심 요약 · 표 · A/B/C/D 시각화 구성 · 검색 쿼리**를 실시간으로 작성합니다."
        )

    parts = plan.get("parts") or []
    all_chs = [c for pt in parts for c in (pt.get("chapters") or [])]
    total_sec = sum(len(c.get("sections") or []) for c in all_chs)
    total_tbl = sum(len(c.get("tables") or []) for c in all_chs)
    total_vis = sum(len(c.get("visuals") or []) for c in all_chs)
    total_pages = sum(int(c.get("target_pages") or 0) for c in all_chs) or int(plan.get("target_pages") or 400)

    lines = [
        f"# 《{plan.get('book_title_ko', '전문 교재 계획서')}》 집필 · 검색 · 시각화 종합 계획서",
        "",
        f"- **영문 제목**: {plan.get('book_title_en', '')}",
        f"- **대상 독자**: {plan.get('target_audience', '')}",
        f"- **구성 규모**: **{len(parts)}부 {len(all_chs)}장 {total_sec}절** · 목표 **{total_pages}쪽** · 표 **{total_tbl}종** · 시각화 **{total_vis}종**",
        f"- **기획 엔진**: `{plan.get('engine_used', 'Antigravity · Gemini API')}`",
        "",
        "## 1. 교재 전체 기획 의도 및 핵심 요약",
        plan.get("book_summary_ko", ""),
        "",
        "## 2. 검색 반영 핵심 키워드 및 학술 검색 쿼리",
        "",
    ]

    for dk in plan.get("domain_keywords") or []:
        ko_s = ", ".join(dk.get("keywords_ko") or [])
        en_s = ", ".join(dk.get("keywords_en") or [])
        lines.append(f"- **{dk.get('domain', '핵심 영역')}**: {ko_s}" + (f" / `{en_s}`" if en_s else ""))

    sq_ko = plan.get("search_queries_ko") or []
    sq_en = plan.get("search_queries_en") or []
    if sq_ko:
        lines.append(f"- **국내 기관·학술 검색 쿼리**: " + " | ".join(f"`{q}`" for q in sq_ko))
    if sq_en:
        lines.append(f"- **국제 SCI/OA 검색 쿼리**: " + " | ".join(f"`{q}`" for q in sq_en))
    lines.append("")
    lines.append("## 3. 부 · 장 · 절 · 핵심 요약 · 표 · 시각화 상세 설계")
    lines.append("")

    for pt in parts:
        lines.append(f"### {pt.get('title', '')}")
        if pt.get("summary_ko"):
            lines.append(f"> {pt['summary_ko']}")
        lines.append("")
        for ch in pt.get("chapters") or []:
            lines.append(f"#### {ch.get('title', '')} (`{ch.get('chapter_id', '')}` · 약 {ch.get('target_pages', 30)}쪽)")
            if ch.get("summary_ko"):
                lines.append(f"- **핵심내용 요약**: {ch['summary_ko']}")
            if ch.get("sections"):
                lines.append("- **절 구성**: " + " / ".join(ch["sections"]))
            if ch.get("keywords_ko") or ch.get("keywords_en"):
                lines.append(
                    "- **단원 검색 키워드**: "
                    + ", ".join(ch.get("keywords_ko") or [])
                    + (" · " + ", ".join(ch.get("keywords_en") or []) if ch.get("keywords_en") else "")
                )
            if ch.get("tables"):
                lines.append("- **표(Table) 구성**:")
                for tb in ch["tables"]:
                    cols = ", ".join(tb.get("columns") or [])
                    lines.append(f"  - `[{tb.get('table_id', '표')}]` **{tb.get('title', '')}** — 열 구성: `{cols}` ({tb.get('purpose', '')})")
            if ch.get("visuals"):
                lines.append("- **시각화(A/B/C/D) 구성**:")
                for vs in ch["visuals"]:
                    lines.append(
                        f"  - `[{vs.get('fig_id', '그림')}]` **유형 {vs.get('type', 'C')}** (`{vs.get('aspect_ratio', '16:9')}`, `{vs.get('method', 'nano_banana_pro')}`) "
                        f"**{vs.get('title', '')}** — {vs.get('description', '')}"
                    )
            lines.append("")

    lines.extend(
        [
            "## 4. 단원별 분량·표·시각화 총괄표",
            "",
            "| 단원 ID | 단원명 | 쪽수 | 절 수 | 표 수 | 시각화 수 | 핵심 검색어 |",
            "| :---: | :--- | :---: | :---: | :---: | :---: | :--- |",
        ]
    )
    for ch in all_chs:
        kws = ", ".join((ch.get("keywords_ko") or [])[:3])
        lines.append(
            f"| `{ch.get('chapter_id', '')}` | {str(ch.get('title', '')).replace('|', '/')} | "
            f"{ch.get('target_pages', 30)}p | {len(ch.get('sections') or [])} | "
            f"{len(ch.get('tables') or [])} | {len(ch.get('visuals') or [])} | {kws} |"
        )
    return "\n".join(lines) + "\n"


def load_plan_chat_session(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    hp = _chat_history_path(project_id, cfg)
    pp = _plan_json_path(project_id, cfg)

    history: list[dict[str, Any]] = []
    if hp.is_file():
        try:
            history = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            history = []

    if pp.is_file():
        try:
            plan = json.loads(pp.read_text(encoding="utf-8"))
        except Exception:
            plan = _seed_plan_from_state(st)
    else:
        plan = _seed_plan_from_state(st)

    return {
        "project_id": project_id,
        "topic_ko": st.get("topic_ko", ""),
        "topic_en": st.get("topic_en", ""),
        "keywords_ko": st.get("keywords_ko") or [],
        "keywords_en": st.get("keywords_en") or [],
        "chapter_count": st.get("chapter_count", 12),
        "target_pages": st.get("target_pages", 400),
        "history": history,
        "plan": plan,
        "plan_markdown": render_plan_markdown(plan),
    }


def reset_plan_chat_session(project_id: str, keep_plan: bool = False, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    _chat_history_path(project_id, cfg).write_text("[]", encoding="utf-8")
    if not keep_plan:
        p = _plan_json_path(project_id, cfg)
        if p.exists():
            p.unlink(missing_ok=True)
    return load_plan_chat_session(project_id, cfg)


def _normalize_plan(raw_plan: dict[str, Any], *, fallback_topic_ko: str, fallback_topic_en: str, fallback_pages: int, engine_used: str) -> dict[str, Any]:
    parts_in = raw_plan.get("parts") or []
    parts_out: list[dict[str, Any]] = []
    ch_seq = 0
    all_ko: list[str] = []
    all_en: list[str] = []

    for p_i, pt in enumerate(parts_in, 1):
        chs_out: list[dict[str, Any]] = []
        for c in pt.get("chapters") or []:
            ch_seq += 1
            cid = f"ch{ch_seq:02d}"
            raw_title = str(c.get("title") or f"제{ch_seq}장").strip()
            if not re.match(r"^제\d+장", raw_title):
                raw_title = f"제{ch_seq}장. {raw_title}"

            # 표 정규화
            tables_out: list[dict[str, Any]] = []
            for t_i, tb in enumerate(c.get("tables") or [], 1):
                if isinstance(tb, str):
                    tables_out.append({"table_id": f"표 {ch_seq}-{t_i}", "title": tb, "columns": ["항목", "핵심 기준", "비고"], "purpose": ""})
                elif isinstance(tb, dict):
                    tables_out.append(
                        {
                            "table_id": str(tb.get("table_id") or f"표 {ch_seq}-{t_i}").strip(),
                            "title": str(tb.get("title") or f"핵심 비교표 {t_i}").strip(),
                            "columns": [str(x).strip() for x in (tb.get("columns") or ["항목", "내용", "기준"]) if str(x).strip()],
                            "purpose": str(tb.get("purpose") or "").strip(),
                        }
                    )

            # 시각화(A/B/C/D) 정규화
            visuals_out: list[dict[str, Any]] = []
            for v_i, vs in enumerate(c.get("visuals") or [], 1):
                if isinstance(vs, str):
                    visuals_out.append(
                        {
                            "fig_id": f"그림 {ch_seq}-{v_i:02d}",
                            "type": "C",
                            "aspect_ratio": "16:9",
                            "method": "nano_banana_pro",
                            "title": vs,
                            "description": "",
                        }
                    )
                elif isinstance(vs, dict):
                    vtype = str(vs.get("type") or "C").strip().upper()[:1]
                    if vtype not in ("A", "B", "C", "D"):
                        vtype = "C"
                    ar = "4:3" if vtype in ("A", "B") else "16:9"
                    method = "python" if vtype == "D" else "nano_banana_pro"
                    visuals_out.append(
                        {
                            "fig_id": str(vs.get("fig_id") or f"그림 {ch_seq}-{v_i:02d}").strip(),
                            "type": vtype,
                            "aspect_ratio": str(vs.get("aspect_ratio") or ar),
                            "method": str(vs.get("method") or method),
                            "title": str(vs.get("title") or f"도판 {v_i}").strip(),
                            "description": str(vs.get("description") or "").strip(),
                        }
                    )

            c_ko = [str(x).strip() for x in (c.get("keywords_ko") or []) if str(x).strip()]
            c_en = [str(x).strip() for x in (c.get("keywords_en") or []) if str(x).strip()]
            all_ko.extend(c_ko)
            all_en.extend(c_en)

            chs_out.append(
                {
                    "chapter_id": cid,
                    "chapter_number": ch_seq,
                    "title": raw_title,
                    "target_pages": max(10, int(c.get("target_pages") or 30)),
                    "summary_ko": str(c.get("summary_ko") or "").strip(),
                    "sections": [str(x).strip() for x in (c.get("sections") or [f"{ch_seq}.1 개요", f"{ch_seq}.2 원리", f"{ch_seq}.3 현장 적용"]) if str(x).strip()],
                    "tables": tables_out,
                    "visuals": visuals_out,
                    "keywords_ko": c_ko,
                    "keywords_en": c_en,
                }
            )
        pt_title = str(pt.get("title") or f"제{p_i}부").strip()
        if not re.match(r"^제\d+부", pt_title):
            pt_title = f"제{p_i}부. {pt_title}"
        parts_out.append(
            {
                "part_number": p_i,
                "title": pt_title,
                "summary_ko": str(pt.get("summary_ko") or "").strip(),
                "chapters": chs_out,
            }
        )

    dom_kws = raw_plan.get("domain_keywords") or []
    clean_dom_kws = []
    for dk in dom_kws:
        if isinstance(dk, dict) and dk.get("domain"):
            clean_dom_kws.append(
                {
                    "domain": str(dk["domain"]).strip(),
                    "keywords_ko": [str(x).strip() for x in (dk.get("keywords_ko") or []) if str(x).strip()],
                    "keywords_en": [str(x).strip() for x in (dk.get("keywords_en") or []) if str(x).strip()],
                }
            )
    if not clean_dom_kws and parts_out:
        clean_dom_kws = [
            {
                "domain": pt["title"],
                "keywords_ko": list(dict.fromkeys(k for c in pt["chapters"] for k in c["keywords_ko"]))[:5],
                "keywords_en": list(dict.fromkeys(k for c in pt["chapters"] for k in c["keywords_en"]))[:5],
            }
            for pt in parts_out
        ]

    sq_ko = [str(x).strip() for x in (raw_plan.get("search_queries_ko") or []) if str(x).strip()]
    sq_en = [str(x).strip() for x in (raw_plan.get("search_queries_en") or []) if str(x).strip()]
    if not sq_ko:
        sq_ko = list(dict.fromkeys([fallback_topic_ko, *all_ko]))[:10]
    if not sq_en:
        sq_en = list(dict.fromkeys([fallback_topic_en or fallback_topic_ko, *all_en]))[:10]

    total_p = sum(c["target_pages"] for pt in parts_out for c in pt["chapters"]) or fallback_pages
    return {
        "book_title_ko": str(raw_plan.get("book_title_ko") or fallback_topic_ko).strip(),
        "book_title_en": str(raw_plan.get("book_title_en") or fallback_topic_en or fallback_topic_ko).strip(),
        "book_summary_ko": str(raw_plan.get("book_summary_ko") or "").strip(),
        "target_audience": str(raw_plan.get("target_audience") or "대학 전공 심화, 대학원생, 연구자 및 선도 현장 실무자").strip(),
        "target_pages": total_p,
        "domain_keywords": clean_dom_kws,
        "search_queries_ko": sq_ko[:12],
        "search_queries_en": sq_en[:12],
        "parts": parts_out,
        "engine_used": engine_used,
        "updated_at": utc_now_iso(),
    }


def _call_gemini_plan_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model_chain: list[str],
) -> tuple[dict[str, Any], str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    last_err = ""
    for mdl in model_chain:
        try:
            resp = client.models.generate_content(
                model=mdl,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.35,
                ),
            )
            txt = (resp.text or "").strip()
            # 코드펜스 방어
            txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S).strip()
            parsed = json.loads(txt)
            return parsed, f"Antigravity · Gemini ({mdl})"
        except Exception as exc:
            last_err = f"{mdl}: {str(exc)[:120]}"
    raise RuntimeError(f"Gemini API 계획서 생성 실패: {last_err}")


def _call_openai_plan_chat(
    *,
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> tuple[dict[str, Any], str]:
    import urllib.request

    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "temperature": 0.35,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return json.loads(content), f"OpenAI ({model})"


def run_plan_chat_turn(
    *,
    project_id: str,
    message: str,
    topic_ko: str = "",
    topic_en: str = "",
    keywords_ko: list[str] | None = None,
    keywords_en: list[str] | None = None,
    chapter_count: int = 12,
    target_pages: int = 400,
    engine: str = "antigravity_gemini",
    include_tables: bool = True,
    include_visuals: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """사용자 메시지와 주제어/키워드로 대화형 교재 계획서를 생성·수정한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    sess = load_plan_chat_session(project_id, cfg)
    history = list(sess.get("history") or [])
    current_plan = sess.get("plan") or {}

    eff_topic_ko = (topic_ko or "").strip() or current_plan.get("book_title_ko") or st.get("topic_ko", "")
    eff_topic_en = (topic_en or "").strip() or current_plan.get("book_title_en") or st.get("topic_en", "")
    eff_kw_ko = [k.strip() for k in (keywords_ko or []) if k.strip()] or list(st.get("keywords_ko") or [])
    eff_kw_en = [k.strip() for k in (keywords_en or []) if k.strip()] or list(st.get("keywords_en") or [])
    eff_ch_cnt = max(3, min(24, int(chapter_count or st.get("chapter_count") or 12)))
    eff_pages = max(60, min(1500, int(target_pages or st.get("target_pages") or 400)))
    per_ch = max(15, round(eff_pages / max(1, eff_ch_cnt)))

    system_prompt = (
        "당신은 Antigravity Ultra 지휘 계층의 수석 대학교재·전문 보고서 교육과정 설계자(Curriculum & Visual Architect)입니다.\n"
        "사용자가 제시한 주제어·핵심 키워드 및 대화 요청을 반영해 학술적으로 완성도 높은 교재 종합 계획서를 JSON으로 작성·개선하세요.\n\n"
        "필수 설계 규범:\n"
        "1. 체계적인 부(Part) → 장/단원(Chapter) → 절(Section, 장당 3~5개) 구조를 설계한다.\n"
        "2. 각 장마다 구체적인 핵심내용 요약(summary_ko, 2~3문장, 원리→정량기준→현장적용 흐름)을 작성한다.\n"
        "3. 표(tables) 구성 포함 시: 각 장당 1~3개의 학술 비교표/기준표(table_id, title, columns, purpose)를 설계한다.\n"
        "4. 시각화(visuals) 구성 포함 시: 『weed_control』 검증 4유형 표준을 적용해 각 장당 3~5개의 대표 도판을 배정한다:\n"
        "   - type='A': 현장 다큐멘터리 실사 (aspect_ratio='4:3', method='nano_banana_pro')\n"
        "   - type='B': 스튜디오 접사·표본 실사 (aspect_ratio='4:3', method='nano_banana_pro')\n"
        "   - type='C': 교재 개념도·기작 도해·인포그래픽 (aspect_ratio='16:9', method='nano_banana_pro')\n"
        "   - type='D': 정량 통계 그래프·수리모델 곡선 (aspect_ratio='16:9', method='python')\n"
        "5. 문헌·학술·기관 검색에 즉시 반영할 수 있도록 domain_keywords, search_queries_ko(6~10개), search_queries_en(6~10개) 및 장별 keywords_ko/keywords_en을 정교하게 추출한다.\n"
        "6. 기존 계획서가 주어지면 사용자가 수정/추가/삭제를 요청한 부분을 정확히 반영하되, 변경 요청이 없는 기존 장·구성은 불필요하게 훼손하지 않는다.\n"
        "7. 반드시 유효한 JSON 객체만 출력한다."
    )

    recent_turns = "\n".join(
        f"- [{h.get('role', 'user')}] {str(h.get('content', ''))[:320]}"
        for h in history[-6:]
    )
    prev_plan_snippet = ""
    if current_plan.get("parts"):
        prev_plan_snippet = "\n[현재까지 작성된 계획서 JSON]\n" + json.dumps(current_plan, ensure_ascii=False)[:14000]

    user_prompt = (
        f"[기본 기획 정보]\n"
        f"- 주제어(국문): {eff_topic_ko}\n"
        f"- 주제어(영문): {eff_topic_en}\n"
        f"- 핵심 키워드(국문): {', '.join(eff_kw_ko)}\n"
        f"- 핵심 키워드(영문): {', '.join(eff_kw_en)}\n"
        f"- 권장 단원 수: 약 {eff_ch_cnt}장 (단원당 약 {per_ch}쪽, 총 약 {eff_pages}쪽)\n"
        f"- 표(Table) 구성 포함: {'예 (장당 1~2종)' if include_tables else '아니오'}\n"
        f"- 시각화(A/B/C/D) 구성 포함: {'예 (장당 3~4종, A/B/C/D 균형 배정)' if include_visuals else '아니오'}\n"
        + (f"\n[최근 대화 이력]\n{recent_turns}\n" if recent_turns else "")
        + prev_plan_snippet
        + f"\n\n[사용자 현재 요청]\n{message.strip()}\n\n"
        "출력 JSON 스키마:\n"
        "{\n"
        '  "assistant_reply": "사용자에게 전달할 친절하고 구체적인 한국어 설계 설명 및 다음 보완 제안 (3~6문장)",\n'
        '  "plan": {\n'
        '    "book_title_ko": "교재 제목",\n'
        '    "book_title_en": "English Title",\n'
        '    "book_summary_ko": "전체 기획 의도 및 핵심 요약 (3~4문장)",\n'
        '    "target_audience": "대상 독자",\n'
        f'    "target_pages": {eff_pages},\n'
        '    "domain_keywords": [{"domain": "핵심 영역", "keywords_ko": ["..."], "keywords_en": ["..."]}],\n'
        '    "search_queries_ko": ["국내 기관·학술 검색 쿼리 1", "..."],\n'
        '    "search_queries_en": ["international scholarly search query 1", "..."],\n'
        '    "parts": [\n'
        "      {\n"
        '        "part_number": 1,\n'
        '        "title": "제1부. ...",\n'
        '        "summary_ko": "이 부의 핵심 흐름 요약",\n'
        '        "chapters": [\n'
        "          {\n"
        '            "chapter_number": 1,\n'
        '            "title": "제1장. ...",\n'
        f'            "target_pages": {per_ch},\n'
        '            "summary_ko": "핵심내용 요약 (2~3문장)",\n'
        '            "sections": ["1.1 ...", "1.2 ...", "1.3 ...", "1.4 ..."],\n'
        '            "tables": [{"table_id": "표 1-1", "title": "...", "columns": ["항목", "기준", "비고"], "purpose": "..."}],\n'
        '            "visuals": [{"fig_id": "그림 1-01", "type": "C", "aspect_ratio": "16:9", "method": "nano_banana_pro", "title": "...", "description": "..."}],\n'
        '            "keywords_ko": ["단원검색어1", "단원검색어2"],\n'
        '            "keywords_en": ["chapter query 1", "chapter query 2"]\n'
        "          }\n"
        "        ]\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "}"
    )

    gemini_key = resolve_api_key("GEMINI_API_KEY", None, cfg)
    openai_key = resolve_api_key("OPENAI_API_KEY", None, cfg)

    raw_resp: dict[str, Any] | None = None
    engine_used = ""
    errors: list[str] = []

    if engine in ("antigravity_gemini", "gemini_pro") and gemini_key:
        try:
            chain = GEMINI_PRO_CHAIN if engine == "gemini_pro" else GEMINI_DEFAULT_CHAIN
            raw_resp, engine_used = _call_gemini_plan_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=gemini_key,
                model_chain=chain,
            )
        except Exception as exc:
            errors.append(str(exc))

    if raw_resp is None and engine == "openai" and openai_key:
        try:
            raw_resp, engine_used = _call_openai_plan_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=openai_key,
            )
        except Exception as exc:
            errors.append(str(exc))

    # 자동 폴백: Gemini 우선 → 로컬 Ollama Gemma 4
    if raw_resp is None and gemini_key and engine not in ("antigravity_gemini", "gemini_pro"):
        try:
            raw_resp, engine_used = _call_gemini_plan_chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=gemini_key,
                model_chain=GEMINI_DEFAULT_CHAIN,
            )
        except Exception as exc:
            errors.append(str(exc))

    if raw_resp is None:
        try:
            from local_gemma import LocalGemmaClient

            gmdl = (st.get("options") or {}).get("gemma_model") or cfg.ollama_fast_model
            g_txt = LocalGemmaClient(cfg).chat(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                model=gmdl,
                timeout=180,
            )
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", g_txt.strip(), flags=re.S).strip()
            m_obj = re.search(r"\{[\s\S]*\}", cleaned)
            raw_resp = json.loads(m_obj.group(0) if m_obj else cleaned)
            engine_used = f"로컬 Ollama ({gmdl})"
        except Exception as exc:
            errors.append(f"Ollama: {exc}")
            raise RuntimeError("계획서 생성 실패: " + " | ".join(errors))

    raw_plan = raw_resp.get("plan") if isinstance(raw_resp.get("plan"), dict) else raw_resp
    reply_text = str(raw_resp.get("assistant_reply") or "요청하신 주제어와 키워드를 반영해 교재 종합 계획서를 업데이트했습니다.").strip()
    norm_plan = _normalize_plan(
        raw_plan,
        fallback_topic_ko=eff_topic_ko,
        fallback_topic_en=eff_topic_en,
        fallback_pages=eff_pages,
        engine_used=engine_used,
    )
    plan_md = render_plan_markdown(norm_plan)

    # 통계 요약
    all_chs = [c for pt in norm_plan["parts"] for c in pt["chapters"]]
    stats = {
        "parts": len(norm_plan["parts"]),
        "chapters": len(all_chs),
        "sections": sum(len(c["sections"]) for c in all_chs),
        "tables": sum(len(c["tables"]) for c in all_chs),
        "visuals": sum(len(c["visuals"]) for c in all_chs),
        "queries": len(norm_plan["search_queries_ko"]) + len(norm_plan["search_queries_en"]),
    }

    now = utc_now_iso()
    history.append({"role": "user", "content": message.strip(), "timestamp": now})
    history.append(
        {
            "role": "assistant",
            "content": reply_text,
            "engine_used": engine_used,
            "stats": stats,
            "timestamp": now,
        }
    )

    _chat_history_path(project_id, cfg).write_text(json.dumps(history[-40:], ensure_ascii=False, indent=2), encoding="utf-8")
    _plan_json_path(project_id, cfg).write_text(json.dumps(norm_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _plan_md_path(project_id, cfg).write_text(plan_md, encoding="utf-8")

    append_event(
        project_id,
        "plan-chatbot",
        "stage1_topic_outline",
        f"챗봇 계획서 갱신 ({engine_used}): {stats['parts']}부 {stats['chapters']}장 · 표 {stats['tables']}종 · 시각화 {stats['visuals']}종",
        cfg=cfg,
    )
    return {
        "status": "OK",
        "engine_used": engine_used,
        "reply": reply_text,
        "stats": stats,
        "plan": norm_plan,
        "plan_markdown": plan_md,
        "history": history[-40:],
    }


def plan_to_master_outline(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """챗봇 계획서 JSON을 플랫폼 표준 master_outline.yaml 구조로 변환한다 (표·시각화·검색쿼리 보존)."""
    parts_out: list[dict[str, Any]] = []
    assigned_sids = [s.get("source_id") for s in (state.get("collected_sources") or []) if s.get("source_id")]
    for pt in plan.get("parts") or []:
        chs_out = []
        for c in pt.get("chapters") or []:
            chs_out.append(
                {
                    "chapter_id": c["chapter_id"],
                    "chapter_number": c["chapter_number"],
                    "title": c["title"],
                    "target_pages": int(c.get("target_pages") or 30),
                    "summary_ko": c.get("summary_ko", ""),
                    "sections": list(c.get("sections") or []),
                    "tables": list(c.get("tables") or []),
                    "visuals": list(c.get("visuals") or []),
                    "keywords_ko": list(c.get("keywords_ko") or []),
                    "keywords_en": list(c.get("keywords_en") or []),
                    "evidence_packet": f"{state['packet_id']}.json",
                    "assigned_sources": assigned_sids,
                }
            )
        parts_out.append(
            {
                "part_number": pt["part_number"],
                "title": pt["title"],
                "summary_ko": pt.get("summary_ko", ""),
                "pages": sum(c["target_pages"] for c in chs_out),
                "chapters": chs_out,
            }
        )
    total_p = sum(pt["pages"] for pt in parts_out) or int(plan.get("target_pages") or 400)
    return {
        "book_metadata": {
            "title_ko": plan.get("book_title_ko") or state.get("topic_ko", ""),
            "title_en": plan.get("book_title_en") or state.get("topic_en", ""),
            "target_audience": plan.get("target_audience") or state.get("target_audience", ""),
            "book_summary_ko": plan.get("book_summary_ko", ""),
            "target_pages": total_p,
            "target_total_pages": total_p,
            "chapter_count": sum(len(pt["chapters"]) for pt in parts_out),
            "engine_used": plan.get("engine_used", "Antigravity · Gemini API"),
            "generated_at": utc_now_iso(),
        },
        "domain_keywords": list(plan.get("domain_keywords") or []),
        "search_queries_ko": list(plan.get("search_queries_ko") or []),
        "search_queries_en": list(plan.get("search_queries_en") or []),
        "parts": parts_out,
    }


def apply_plan_to_project(
    project_id: str,
    *,
    plan_override: dict[str, Any] | None = None,
    approve_stage1: bool = True,
    auto_start_stage2: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """챗봇 계획서를 프로젝트 청사진·검색 키워드에 반영하고, 선택 시 2단계 자료 수집을 즉시 시작한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    if plan_override and plan_override.get("parts"):
        plan = plan_override
    else:
        pp = _plan_json_path(project_id, cfg)
        if not pp.is_file():
            raise ValueError("반영할 계획서가 아직 생성되지 않았습니다. 먼저 챗봇으로 계획서를 작성해 주세요.")
        plan = json.loads(pp.read_text(encoding="utf-8"))

    outline = plan_to_master_outline(plan, st)

    # 검색 쿼리를 프로젝트 상태에도 최우선 저장 (2단계 자동 수집·자료실·심층 조사에 직결)
    sq_ko = [str(x).strip() for x in (plan.get("search_queries_ko") or []) if str(x).strip()]
    sq_en = [str(x).strip() for x in (plan.get("search_queries_en") or []) if str(x).strip()]
    st["search_queries_ko"] = sq_ko
    st["search_queries_en"] = sq_en
    # 기존 keywords 앞쪽에 계획서 검색 쿼리 병합
    st["keywords_ko"] = list(dict.fromkeys([*sq_ko, *(st.get("keywords_ko") or [])]))[:24]
    st["keywords_en"] = list(dict.fromkeys([*sq_en, *(st.get("keywords_en") or [])]))[:24]
    save_project_state(st, cfg)

    master_p = _save_outline_files(st, outline, cfg)
    plan_md = render_plan_markdown(plan)
    _plan_json_path(project_id, cfg).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _plan_md_path(project_id, cfg).write_text(plan_md, encoding="utf-8")

    # E:\SMC_Report_Platform_Data\projects\<pid>\reports\ 에도 계획서 마크다운 백업
    try:
        e_rep = cfg.e_projects_dir / project_id / "reports"
        e_rep.mkdir(parents=True, exist_ok=True)
        (e_rep / "book_plan_studio.md").write_text(plan_md, encoding="utf-8")
    except Exception:
        pass

    run_info = None
    if approve_stage1:
        res_ap = approve_stage1_outline(project_id, edited_outline=outline, auto_continue=auto_start_stage2, cfg=cfg)
        st = res_ap.get("project") or load_project_state(project_id, cfg)
        run_info = res_ap.get("run")
    else:
        st = load_project_state(project_id, cfg)

    append_event(
        project_id,
        "plan-chatbot",
        "stage1_topic_outline",
        f"챗봇 계획서 프로젝트 반영 및 검색 쿼리 동기화 완료 (국문 {len(sq_ko)}개 · 영문 {len(sq_en)}개)",
        cfg=cfg,
    )
    return {
        "status": "APPLIED",
        "blueprint_path": str(master_p),
        "plan_md_url": f"/project-files/{project_id}/blueprints/book_plan_studio.md",
        "search_queries_ko": sq_ko,
        "search_queries_en": sq_en,
        "project": st,
        "run": run_info,
    }


def run_plan_based_search(
    project_id: str,
    *,
    queries_ko: list[str] | None = None,
    queries_en: list[str] | None = None,
    limit_per_query: int = 4,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """챗봇 계획서에서 생성된 국·영문 검색 쿼리로 로컬 RAG · 국내 학회지 · 국제 SCI/OA 논문을 즉시 통합 검색한다."""
    from fetch_scholar import search_crossref_korean_society, search_openalex_papers
    from smc_kg_bridge import run_gap_check

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    sess = load_plan_chat_session(project_id, cfg)
    plan = sess.get("plan") or {}
    q_ko = [q.strip() for q in (queries_ko or plan.get("search_queries_ko") or st.get("search_queries_ko") or st.get("keywords_ko") or []) if q.strip()][:5]
    q_en = [q.strip() for q in (queries_en or plan.get("search_queries_en") or st.get("search_queries_en") or st.get("keywords_en") or []) if q.strip()][:5]

    # 1) 로컬 지식그래프(C:\SMC_GRAPHRAG) 선조회
    rag_summary: dict[str, Any] = {}
    try:
        gap_out = cfg.project_dir(project_id) / "reports" / "plan_search_gap.json"
        rag_summary = run_gap_check(
            topic=plan.get("book_title_ko") or st.get("topic_ko", ""),
            terms=list(dict.fromkeys([*q_ko, *q_en]))[:12],
            out_path=gap_out,
            cfg=cfg,
        )
    except Exception as exc:
        rag_summary = {"error": str(exc)[:120]}

    # 2) 국제 학술(OpenAlex/Europe PMC 자동 폴백) + 국내 학회지(Crossref) 검색
    results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for q in q_en[:3]:
        try:
            papers = search_openalex_papers(query=q, limit=limit_per_query, scope="international")
            for p in papers:
                key = re.sub(r"\W+", "", str(p.get("title", "")).lower())[:60]
                if key and key not in seen_titles:
                    seen_titles.add(key)
                    results.append({**p, "matched_query": q, "search_channel": "국제 SCI/OA"})
        except Exception:
            continue

    for q in q_ko[:3]:
        try:
            papers = search_crossref_korean_society(query=q, limit=limit_per_query)
            for p in papers:
                key = re.sub(r"\W+", "", str(p.get("title", "")).lower())[:60]
                if key and key not in seen_titles:
                    seen_titles.add(key)
                    results.append({**p, "matched_query": q, "search_channel": "국내 학술지"})
        except Exception:
            continue

    append_event(
        project_id,
        "plan-chatbot",
        "stage2_source_collect",
        f"계획서 검색 쿼리 즉시 탐색 완료: 국문 {len(q_ko)} · 영문 {len(q_en)} → 문헌 {len(results)}건 발굴",
        cfg=cfg,
    )
    return {
        "status": "OK",
        "queries_ko": q_ko,
        "queries_en": q_en,
        "rag_summary": {
            "reuse_ratio_percent": rag_summary.get("reuse_ratio_percent", 0),
            "matched_terms": rag_summary.get("matched_terms", [])[:10],
            "missing_terms": rag_summary.get("missing_or_outdated_gaps", [])[:10],
        },
        "count": len(results),
        "papers": results[:25],
    }


def create_project_from_plan(
    *,
    plan: dict[str, Any],
    auto_start_stage2: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """챗봇에서 작성한 계획서로 아예 새 교재 프로젝트를 생성하고 청사진·검색 쿼리를 즉시 반영한다."""
    cfg = cfg or get_config()
    if not plan or not plan.get("parts"):
        raise ValueError("생성할 계획서 내용이 비어 있습니다.")
    all_chs = [c for pt in plan["parts"] for c in (pt.get("chapters") or [])]
    st = create_project(
        topic_ko=plan.get("book_title_ko") or "신규 전문 교재",
        topic_en=plan.get("book_title_en") or "",
        keywords_ko=list(plan.get("search_queries_ko") or []),
        keywords_en=list(plan.get("search_queries_en") or []),
        target_audience=plan.get("target_audience") or "대학 전공 심화, 연구자 및 현장 실무자",
        target_pages=int(plan.get("target_pages") or 400),
        chapter_count=max(3, min(24, len(all_chs))),
        cfg=cfg,
    )
    return apply_plan_to_project(
        st["project_id"],
        plan_override=plan,
        approve_stage1=True,
        auto_start_stage2=auto_start_stage2,
        cfg=cfg,
    )
