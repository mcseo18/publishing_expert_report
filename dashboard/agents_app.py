"""단일 통합 교재 제작 플랫폼 · 6단계 에이전트 관제 대시보드 서버 (FastAPI, 기본 포트 8501).

실행:
    .venv\\Scripts\\python.exe -m uvicorn dashboard.agents_app:app --host 127.0.0.1 --port 8501
또는:
    .\\scripts\\launch_dashboards.ps1 -Target all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from config import get_config  # noqa: E402
from build_cover_toc import (  # noqa: E402
    build_project_cover_and_toc,
    load_cover_settings,
)
from data_connectors import (  # noqa: E402
    OWM_PRESET_CITIES,
    PUBLIC_PORTAL_PRESETS,
    download_kosis_data,
    fetch_kma_apihub_asos,
    fetch_openweathermap,
    fetch_public_data_portal,
    get_api_keys_status,
    get_weather_db_overview,
    query_local_weather_db,
    rows_to_csv_text,
    save_api_keys,
    save_explorer_dataset_to_project,
    search_kosis_tables,
    synthesize_explorer_prompt,
)
from deep_research_chat import (  # noqa: E402
    commit_research_items,
    load_research_chat,
    run_research_turn,
)
from fetch_clean import fetch_and_clean_url  # noqa: E402
from fetch_scholar import (  # noqa: E402
    ingest_paper_record,
    parse_bibtex_entries,
    search_crossref_korean_society,
    search_openalex_papers,
)
from notebooklm_connector import (  # noqa: E402
    import_notebooklm_sources,
    list_notebook_sources,
    list_notebooks,
    query_notebooklm,
)
from subagent_orchestrator import (  # noqa: E402
    STAGE_DEFINITIONS,
    _save_outline_files,
    approve_stage1_outline,
    create_project,
    delete_project,
    get_ai_engines_status,
    list_projects,
    load_events,
    load_project_state,
    load_stage_report,
    reset_projects_keep_only,
    revise_stage1_outline,
    save_project_state,
    start_pipeline_async,
    stop_pipeline,
    update_project_options,
)

app = FastAPI(title="전문 교재 제작 통합 플랫폼 (단일 HTML 6단계 관제)", version="2.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_UNIFIED = STATIC_DIR / "unified.html"
STATIC_AGENTS = STATIC_DIR / "agents.html"
STATIC_EXPLORER = STATIC_DIR / "explorer.html"


# ============================================================
# Pydantic 요청 모델
# ============================================================
class CreateProjectRequest(BaseModel):
    topic_ko: str
    topic_en: str = ""
    keywords_ko: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    domestic_agency_urls: list[str] = Field(default_factory=list)
    international_agency_urls: list[str] = Field(default_factory=list)
    target_audience: str = "대학 전공 심화, 대학원생, 연구자 및 선도 현장 실무자"
    target_pages: int = Field(default=500, ge=50, le=1500)
    chapter_count: int = Field(default=15, ge=3, le=24)
    papers_per_query: int = Field(default=5, ge=2, le=15)
    use_openai_outline: bool = True
    openai_model: str = "gpt-4o-mini"
    use_fal_ai: bool = False
    fal_model: str = "fal-ai/nano-banana"
    use_nano_banana: bool = True
    visuals_per_chapter: int = Field(default=10, ge=10, le=25)
    gemma_model: str = "gemma4:latest"
    use_claude_review: bool = False
    use_claude_blueprint: bool = False
    download_oa_pdf: bool = True
    enable_naver_blog: bool = True
    enable_myths: bool = True
    enable_linked_quiz: bool = True
    draft_chapter_limit: int = Field(default=0, ge=0, le=24)
    auto_start: bool = True


class UpdateOptionsRequest(BaseModel):
    use_openai_outline: bool | None = None
    openai_model: str | None = None
    use_fal_ai: bool | None = None
    fal_model: str | None = None
    use_nano_banana: bool | None = None
    visuals_per_chapter: int | None = None
    gemma_model: str | None = None
    kg_model: str | None = None
    use_claude_review: bool | None = None
    use_claude_blueprint: bool | None = None
    download_oa_pdf: bool | None = None
    enable_naver_blog: bool | None = None
    draft_chapter_limit: int | None = None
    papers_per_query: int | None = None


class RunProjectRequest(BaseModel):
    mode: str = "all"  # all | resume | next | single
    stage_id: str | None = None


class Stage1ReviseRequest(BaseModel):
    feedback_prompt: str
    use_openai: bool | None = None


class Stage1ApproveRequest(BaseModel):
    edited_outline: dict[str, Any] | None = None
    auto_continue: bool = True


class BlueprintSaveRequest(BaseModel):
    outline: dict[str, Any]


class CoverTocGenerateRequest(BaseModel):
    title_ko: str | None = None
    subtitle_ko: str | None = None
    title_en: str | None = None
    author: str | None = None
    publisher: str | None = None
    edition: str | None = None
    target_audience: str | None = None
    theme: str | None = None
    trim_format: str | None = None
    use_ai_cover: bool | None = None
    use_fal_ai: bool | None = None
    fal_model: str | None = None
    preface_ko: str | None = None


class ResetProjectsRequest(BaseModel):
    keep_ids: list[str] = Field(default_factory=list)


class ResearchQueryRequest(BaseModel):
    message: str
    channels: list[str] = Field(
        default_factory=lambda: [
            "local_rag",
            "scholar_intl",
            "scholar_kr",
            "agencies_kr",
            "agencies_global",
            "statistics_api",
        ]
    )
    limit_per_channel: int = Field(default=4, ge=1, le=10)


class ResearchCommitRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    custom_urls: list[str] = Field(default_factory=list)
    bibtex_text: str = ""
    also_ingest_kg: bool = False


class ScholarSearchRequest(BaseModel):
    query: str
    scope: str = "all"  # all | korean | international
    limit: int = Field(default=8, ge=1, le=20)


class ScholarIngestRequest(BaseModel):
    project_id: str
    paper: dict[str, Any]
    download_pdf: bool = False


class UrlCollectRequest(BaseModel):
    project_id: str
    url: str
    title_hint: str = ""
    license_note: str = "공개 웹 자료"


class BibtexCollectRequest(BaseModel):
    project_id: str
    bibtex_text: str


class SaveApiKeysRequest(BaseModel):
    OPENAI_API_KEY: str = ""
    FAL_KEY: str = ""
    GEMINI_API_KEY: str = ""
    KMA_HUB_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    DATA_GO_KR_API_KEY: str = ""
    KOSIS_API_KEY: str = ""


class LocalWeatherQueryRequest(BaseModel):
    network: str = "ASOS"
    station_query: str = ""
    province: str = ""
    start_date: str = "2024-01-01"
    end_date: str = "2026-10-31"
    agg_mode: str = "monthly"
    limit: int = Field(default=200, ge=10, le=2000)


class KmaAsosApiRequest(BaseModel):
    start_date: str = "20261001"
    end_date: str = "20261031"
    stn: str = "119"
    api_key: str = ""


class OpenWeatherRequest(BaseModel):
    city: str = "Suwon,KR"
    lat: float | None = None
    lon: float | None = None
    include_forecast: bool = True
    include_air: bool = True
    api_key: str = ""


class PublicPortalRequest(BaseModel):
    endpoint: str
    params: dict[str, Any] = Field(default_factory=dict)
    key_param: str = "serviceKey"
    dataset_label: str = ""
    api_key: str = ""


class KosisSearchRequest(BaseModel):
    keyword: str
    count: int = Field(default=15, ge=1, le=30)
    api_key: str = ""


class KosisDownloadRequest(BaseModel):
    org_id: str = ""
    tbl_id: str = ""
    tbl_name: str = ""
    itm_id: str = "ALL"
    obj_l1: str = "ALL"
    prd_se: str = "Y"
    start_prd: str = "2019"
    end_prd: str = "2025"
    full_openapi_url: str = ""
    api_key: str = ""


class ExplorerDatasetItem(BaseModel):
    title: str
    source_kind: str
    url: str = ""
    license_note: str = "공식 API/DB 수집 자료"
    markdown: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class ExplorerSaveRequest(BaseModel):
    project_id: str
    datasets: list[ExplorerDatasetItem]
    user_prompt_note: str = ""
    also_ingest_rag: bool = True


class ExplorerPromptRequest(BaseModel):
    project_id: str
    prompt_text: str
    checked_sources: list[str] = Field(default_factory=list)
    attached_datasets: list[ExplorerDatasetItem] = Field(default_factory=list)
    use_claude: bool = False
    gemma_model: str = "gemma4:latest"


class CsvExportRequest(BaseModel):
    filename: str = "dataset.csv"
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class NotebookLmImportRequest(BaseModel):
    project_id: str
    notebook_id: str
    notebook_title: str = ""
    source_ids: list[str]
    also_ingest_rag: bool = True
    chapters: list[str] = Field(default_factory=lambda: ["ch01"])


class NotebookLmQueryRequest(BaseModel):
    notebook_id: str
    question: str


# ============================================================
# 단일 HTML 페이지 라우팅
# ============================================================
@app.get("/", response_class=HTMLResponse)
def unified_index() -> HTMLResponse:
    target = STATIC_UNIFIED if STATIC_UNIFIED.is_file() else STATIC_AGENTS
    if not target.is_file():
        return HTMLResponse("<h1>unified.html missing</h1>", status_code=500)
    return HTMLResponse(target.read_text(encoding="utf-8"))


@app.get("/explorer")
def explorer_redirect():
    return RedirectResponse(url="/#explorer")


# ============================================================
# 6단계 프로젝트 관리 & 파이프라인 제어 API
# ============================================================
@app.get("/api/stages")
def api_stages() -> dict[str, Any]:
    return {"stages": STAGE_DEFINITIONS}


@app.get("/api/projects")
def api_list_projects() -> dict[str, Any]:
    return {"projects": list_projects()}


@app.post("/api/projects")
def api_create_project(req: CreateProjectRequest) -> dict[str, Any]:
    if not req.topic_ko.strip():
        raise HTTPException(status_code=400, detail="교재 주제(국문)를 입력해 주세요.")
    st = create_project(
        topic_ko=req.topic_ko,
        topic_en=req.topic_en,
        keywords_ko=req.keywords_ko,
        keywords_en=req.keywords_en,
        target_audience=req.target_audience,
        target_pages=req.target_pages,
        chapter_count=req.chapter_count,
        options={
            "papers_per_query": req.papers_per_query,
            "domestic_agency_urls": req.domestic_agency_urls,
            "international_agency_urls": req.international_agency_urls,
            "use_openai_outline": req.use_openai_outline,
            "openai_model": req.openai_model,
            "use_fal_ai": req.use_fal_ai,
            "fal_model": req.fal_model,
            "use_nano_banana": req.use_nano_banana,
            "visuals_per_chapter": req.visuals_per_chapter,
            "gemma_model": req.gemma_model,
            "kg_model": "gemma4:latest",
            "use_claude_review": req.use_claude_review,
            "use_claude_blueprint": req.use_claude_blueprint,
            "download_oa_pdf": req.download_oa_pdf,
            "enable_naver_blog": req.enable_naver_blog,
            "enable_myths": req.enable_myths,
            "enable_linked_quiz": req.enable_linked_quiz,
            "draft_chapter_limit": req.draft_chapter_limit,
            "trim_formats": ["shinkuk", "b5", "a4"],
        },
    )
    run_info = None
    if req.auto_start:
        # 1단계(주제 탐색 + OpenAI 목차·요약·키워드 제시)를 즉시 시작하고 검토 게이트에서 자동 대기
        run_info = start_pipeline_async(st["project_id"], mode="single", target_stage="stage1_topic_outline")
    return {"status": "OK", "project": st, "run": run_info}


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str, limit_events: int = 120) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    try:
        cfg = get_config()
        ap = cfg.index_dir / "active_project.json"
        ap.write_text(
            json.dumps({"project_id": project_id, "topic_ko": st.get("topic_ko", "")}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return {"project": st, "events": load_events(project_id, limit=limit_events)}


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str) -> dict[str, Any]:
    try:
        return delete_project(project_id, archive=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/projects/reset")
def api_reset_projects(req: ResetProjectsRequest) -> dict[str, Any]:
    return reset_projects_keep_only(req.keep_ids)


@app.post("/api/projects/{project_id}/run")
def api_run_project(project_id: str, req: RunProjectRequest) -> dict[str, Any]:
    try:
        return start_pipeline_async(project_id, mode=req.mode, target_stage=req.stage_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/projects/{project_id}/stop")
def api_stop_project(project_id: str) -> dict[str, Any]:
    return stop_pipeline(project_id)


@app.patch("/api/projects/{project_id}/options")
def api_update_project_options(project_id: str, req: UpdateOptionsRequest) -> dict[str, Any]:
    try:
        st = update_project_options(project_id, req.model_dump(exclude_none=True))
        return {"status": "OK", "options": st.get("options", {}), "project": st}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


# ---------- 1단계: 목차·요약·키워드 재요청 / 직접 편집 / 확정 ----------
@app.post("/api/projects/{project_id}/stage1/revise")
def api_stage1_revise(project_id: str, req: Stage1ReviseRequest) -> dict[str, Any]:
    if not req.feedback_prompt.strip():
        raise HTTPException(status_code=400, detail="수정·재요청 내용을 입력해 주세요.")
    try:
        return revise_stage1_outline(project_id, req.feedback_prompt.strip(), use_openai=req.use_openai)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"목차 재요청 처리 오류: {exc}")


@app.post("/api/projects/{project_id}/stage1/approve")
def api_stage1_approve(project_id: str, req: Stage1ApproveRequest) -> dict[str, Any]:
    try:
        return approve_stage1_outline(
            project_id,
            edited_outline=req.edited_outline,
            auto_continue=req.auto_continue,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.put("/api/projects/{project_id}/blueprint")
def api_save_blueprint(project_id: str, req: BlueprintSaveRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    if not req.outline or not req.outline.get("parts"):
        raise HTTPException(status_code=400, detail="최소 1개 이상의 부(Part)와 단원(Chapter)이 필요합니다.")
    master_p = _save_outline_files(st, req.outline, cfg)
    return {"status": "SAVED", "path": str(master_p), "project": st}


# ---------- 단계별 보고서 / KG / 단원 원고 / 시각화 조회 ----------
@app.get("/api/projects/{project_id}/reports/{report_key}")
def api_get_stage_report(project_id: str, report_key: str) -> dict[str, Any]:
    try:
        return load_stage_report(project_id, report_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/api/projects/{project_id}/kg-preview")
def api_get_kg_preview(project_id: str) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    inc_path = cfg.smc_incremental_graph_path
    proj_sids = {s.get("source_id") for s in (st.get("collected_sources") or []) if s.get("source_id")}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    total_nodes = 0
    total_edges = 0
    if inc_path.is_file():
        try:
            raw = json.loads(inc_path.read_text(encoding="utf-8"))
            all_nodes = raw.get("nodes", [])
            all_edges = raw.get("edges", raw.get("links", []))
            total_nodes = len(all_nodes)
            total_edges = len(all_edges)
            p_nodes = [n for n in all_nodes if any(sid in str(n.get("source_ids", "")) for sid in proj_sids)] or all_nodes
            nodes = sorted(p_nodes, key=lambda n: int(n.get("mentions", 1) or 1), reverse=True)[:30]
            edges = [e for e in all_edges if e.get("source_id") in proj_sids][:40] or all_edges[-40:]
        except Exception:
            pass
    return {
        "graph_path": str(inc_path),
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "project_source_count": len(proj_sids),
        "top_nodes": nodes,
        "sample_edges": edges,
    }


@app.get("/api/projects/{project_id}/chapters")
def api_list_chapters(project_id: str) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    bp_path = ws / "blueprints" / "master_outline.yaml"
    bp_chs = []
    if bp_path.is_file():
        bp = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        bp_chs = [c for pt in bp.get("parts", []) for c in pt.get("chapters", [])]
    completed = set((st.get("checkpoint") or {}).get("completed_chapters") or [])
    items = []
    seen = set()
    for c in bp_chs:
        cid = c.get("chapter_id", "")
        p = ch_dir / f"{cid}.mdx"
        seen.add(cid)
        items.append(
            {
                "chapter_id": cid,
                "title": c.get("title", cid),
                "summary_ko": c.get("summary_ko", ""),
                "target_pages": c.get("target_pages", 30),
                "exists": p.is_file(),
                "completed_checkpoint": cid in completed or p.is_file(),
                "char_count": len(p.read_text(encoding="utf-8", errors="ignore")) if p.is_file() else 0,
            }
        )
    if ch_dir.is_dir():
        for p in sorted(ch_dir.glob("*.mdx")):
            if p.stem not in seen:
                items.append(
                    {
                        "chapter_id": p.stem,
                        "title": p.stem,
                        "summary_ko": "",
                        "target_pages": 30,
                        "exists": True,
                        "completed_checkpoint": True,
                        "char_count": len(p.read_text(encoding="utf-8", errors="ignore")),
                    }
                )
    audit_path = ws / "reports" / "audit_latest.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else None
    return {"chapters": items, "audit": audit}


@app.get("/api/projects/{project_id}/chapters/{chapter_id}")
def api_get_chapter(project_id: str, chapter_id: str) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    safe_cid = Path(chapter_id).name.replace(".mdx", "")
    p = Path(st["workspace_dir"]) / "chapters" / f"{safe_cid}.mdx"
    if not p.is_file():
        raise HTTPException(status_code=404, detail="아직 집필되지 않은 단원입니다.")
    return {"chapter_id": safe_cid, "content": p.read_text(encoding="utf-8"), "path": str(p)}


@app.get("/api/projects/{project_id}/visuals")
def api_get_visuals(project_id: str) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    assets_dir = Path(st["workspace_dir"]) / "assets"
    plan_p = assets_dir / "visuals_plan.json"
    guide_p = assets_dir / "visuals_text_guide.md"
    plan = json.loads(plan_p.read_text(encoding="utf-8")) if plan_p.is_file() else {"visuals": [], "total_generated": 0}
    guide = guide_p.read_text(encoding="utf-8") if guide_p.is_file() else ""
    e_vis_dir = str(cfg.e_projects_dir / project_id / "visuals")
    local_vis_dir = str(assets_dir / "by_chapter")
    return {
        "plan": plan,
        "text_guide": guide,
        "local_visuals_dir": plan.get("local_visuals_dir") or local_vis_dir,
        "e_visuals_dir": plan.get("e_visuals_dir") or e_vis_dir,
        "bound_visuals_by_chapter": st.get("bound_visuals_by_chapter") or {},
    }


@app.get("/api/projects/{project_id}/cover-toc")
def api_get_cover_toc(project_id: str) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    return load_cover_settings(project_id)


@app.post("/api/projects/{project_id}/cover-toc/generate")
def api_generate_cover_toc(project_id: str, req: CoverTocGenerateRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        res = build_project_cover_and_toc(
            project_id,
            overrides=req.model_dump(exclude_none=True),
            cfg=cfg,
        )
        outs = dict(st.get("outputs") or {})
        for k, u in (res.get("files") or {}).items():
            outs[f"00_cover_toc_{k}"] = u
        st["outputs"] = outs
        save_project_state(st, cfg)
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"표지·목차 생성 오류: {exc}")


@app.get("/api/engines/status")
def api_engines_status() -> dict[str, Any]:
    return get_ai_engines_status()


# ============================================================
# 자료실 · 학술 검색(자동 폴백) · URL · BibTeX 직접 수집 API
# ============================================================
@app.post("/api/collect/scholar/search")
def api_collect_scholar_search(req: ScholarSearchRequest) -> dict[str, Any]:
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력해 주세요.")
    try:
        if req.scope == "korean":
            papers = search_crossref_korean_society(query=req.query.strip(), limit=req.limit)
        else:
            papers = search_openalex_papers(query=req.query.strip(), limit=req.limit, scope=req.scope)
        return {"status": "OK", "count": len(papers), "papers": papers}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"학술 검색 오류: {exc}")


@app.post("/api/collect/scholar/ingest")
def api_collect_scholar_ingest(req: ScholarIngestRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(req.project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        res = ingest_paper_record(
            paper=req.paper,
            packet_id=st["packet_id"],
            topic=st.get("topic_ko", ""),
            download_oa_pdf=req.download_pdf,
            cfg=cfg,
        )
        sid = res.get("source_id")
        if sid and not any(s.get("source_id") == sid for s in st.get("collected_sources", [])):
            st.setdefault("collected_sources", []).append(
                {
                    "source_id": sid,
                    "title": req.paper.get("title", ""),
                    "url": req.paper.get("url", ""),
                    "year": req.paper.get("year"),
                    "provider": req.paper.get("provider", "Academic"),
                    "tier_folder": "04_international_journals",
                }
            )
            save_project_state(st, cfg)
        return {"status": "OK", "result": res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"논문 적재 오류: {exc}")


@app.post("/api/collect/url")
def api_collect_url(req: UrlCollectRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(req.project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        res = fetch_and_clean_url(
            url=req.url.strip(),
            packet_id=st["packet_id"],
            topic=req.title_hint or st.get("topic_ko", ""),
            license_note=req.license_note,
            cfg=cfg,
        )
        sid = res.get("source_id")
        if sid and not any(s.get("source_id") == sid for s in st.get("collected_sources", [])):
            st.setdefault("collected_sources", []).append(
                {
                    "source_id": sid,
                    "title": res.get("title") or req.title_hint or req.url,
                    "url": req.url.strip(),
                    "provider": "직접 URL 수집",
                    "tier_folder": "01_domestic_agencies",
                }
            )
            save_project_state(st, cfg)
        return {"status": "OK", "result": res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"URL 수집 오류: {exc}")


@app.post("/api/collect/bibtex")
def api_collect_bibtex(req: BibtexCollectRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(req.project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    entries = parse_bibtex_entries(req.bibtex_text)
    if not entries:
        raise HTTPException(status_code=400, detail="유효한 BibTeX 항목을 찾지 못했습니다.")
    results = []
    for p in entries:
        res = ingest_paper_record(paper=p, packet_id=st["packet_id"], topic=st.get("topic_ko", ""), download_oa_pdf=False, cfg=cfg)
        results.append(res)
    return {"status": "OK", "ingested_count": len(results), "results": results}


# ============================================================
# 심층 자료 조사 대화 API
# ============================================================
@app.get("/api/projects/{project_id}/research-chat")
def api_get_research_chat(project_id: str, limit: int = 40) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "messages": load_research_chat(project_id, limit=limit)}


@app.post("/api/projects/{project_id}/research-chat/query")
def api_research_chat_query(project_id: str, req: ResearchQueryRequest) -> dict[str, Any]:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="조사할 질의 내용을 입력해 주세요.")
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    entry = run_research_turn(
        project_id=project_id,
        message=req.message.strip(),
        channels=req.channels,
        limit_per_channel=req.limit_per_channel,
        state=st,
    )
    return {"status": "OK", "reply": entry}


@app.post("/api/projects/{project_id}/research-chat/commit")
def api_research_chat_commit(project_id: str, req: ResearchCommitRequest) -> dict[str, Any]:
    try:
        return commit_research_items(
            project_id=project_id,
            candidate_ids=req.candidate_ids,
            custom_urls=req.custom_urls,
            bibtex_text=req.bibtex_text,
            also_ingest_kg=req.also_ingest_kg,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/project-files/{project_id}/{subpath:path}")
def serve_project_file(project_id: str, subpath: str):
    cfg = get_config()
    base = cfg.project_dir(project_id).resolve()
    target = (base / subpath).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Project artifact not found")
    if target.suffix.lower() == ".html":
        return HTMLResponse(target.read_text(encoding="utf-8"))
    return FileResponse(path=str(target), filename=target.name)


# ============================================================
# 데이터 탐색 · 외부 API (기상 DB/KMA/OWM/공공포털/KOSIS) · NotebookLM
# ============================================================
@app.get("/api/explorer/meta")
def api_explorer_meta() -> dict[str, Any]:
    return {
        "projects": list_projects(),
        "api_keys": get_api_keys_status(),
        "weather_db": get_weather_db_overview(),
        "public_portal_presets": PUBLIC_PORTAL_PRESETS,
        "owm_preset_cities": OWM_PRESET_CITIES,
        "engines": get_ai_engines_status(),
    }


@app.post("/api/explorer/keys")
def api_explorer_save_keys(req: SaveApiKeysRequest) -> dict[str, Any]:
    return save_api_keys(req.model_dump())


@app.post("/api/explorer/weather-local")
def api_explorer_weather_local(req: LocalWeatherQueryRequest) -> dict[str, Any]:
    try:
        return query_local_weather_db(
            network=req.network,
            station_query=req.station_query,
            province=req.province,
            start_date=req.start_date,
            end_date=req.end_date,
            agg_mode=req.agg_mode,
            limit=req.limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/kma-asos")
def api_explorer_kma_asos(req: KmaAsosApiRequest) -> dict[str, Any]:
    try:
        return fetch_kma_apihub_asos(
            start_date=req.start_date,
            end_date=req.end_date,
            stn=req.stn,
            api_key=req.api_key or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/openweathermap")
def api_explorer_owm(req: OpenWeatherRequest) -> dict[str, Any]:
    try:
        return fetch_openweathermap(
            city=req.city,
            lat=req.lat,
            lon=req.lon,
            include_forecast=req.include_forecast,
            include_air=req.include_air,
            api_key=req.api_key or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/public-portal")
def api_explorer_public_portal(req: PublicPortalRequest) -> dict[str, Any]:
    try:
        return fetch_public_data_portal(
            endpoint=req.endpoint,
            params=req.params,
            key_param=req.key_param,
            dataset_label=req.dataset_label,
            api_key=req.api_key or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/kosis/search")
def api_explorer_kosis_search(req: KosisSearchRequest) -> dict[str, Any]:
    try:
        return search_kosis_tables(keyword=req.keyword, count=req.count, api_key=req.api_key or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/kosis/download")
def api_explorer_kosis_download(req: KosisDownloadRequest) -> dict[str, Any]:
    try:
        return download_kosis_data(
            org_id=req.org_id,
            tbl_id=req.tbl_id,
            tbl_name=req.tbl_name,
            itm_id=req.itm_id,
            obj_l1=req.obj_l1,
            prd_se=req.prd_se,
            start_prd=req.start_prd,
            end_prd=req.end_prd,
            full_openapi_url=req.full_openapi_url,
            api_key=req.api_key or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/explorer/save")
def api_explorer_save(req: ExplorerSaveRequest) -> dict[str, Any]:
    if not req.datasets:
        raise HTTPException(status_code=400, detail="저장할 데이터셋을 1건 이상 체크해 주세요.")
    results = []
    for ds in req.datasets:
        res = save_explorer_dataset_to_project(
            project_id=req.project_id,
            title=ds.title,
            source_kind=ds.source_kind,
            url=ds.url,
            license_note=ds.license_note,
            markdown_text=ds.markdown,
            columns=ds.columns,
            rows=ds.rows,
            user_prompt_note=req.user_prompt_note,
            also_ingest_rag=req.also_ingest_rag,
        )
        results.append(res)
    return {"status": "OK", "saved_count": len(results), "results": results}


@app.post("/api/explorer/prompt-synthesize")
def api_explorer_prompt(req: ExplorerPromptRequest) -> dict[str, Any]:
    if not req.prompt_text.strip():
        raise HTTPException(status_code=400, detail="추가 요청 사항 프롬프트를 입력해 주세요.")
    return synthesize_explorer_prompt(
        project_id=req.project_id,
        prompt_text=req.prompt_text.strip(),
        checked_sources=req.checked_sources,
        attached_datasets=[d.model_dump() for d in req.attached_datasets],
        use_claude=req.use_claude,
        gemma_model=req.gemma_model,
    )


@app.post("/api/explorer/export-csv")
def api_explorer_export_csv(req: CsvExportRequest) -> PlainTextResponse:
    csv_txt = "\ufeff" + rows_to_csv_text(req.columns, req.rows)
    safe_name = (req.filename or "dataset.csv").replace('"', "")
    return PlainTextResponse(
        content=csv_txt,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@app.get("/api/explorer/notebooklm/notebooks")
def api_explorer_nlm_notebooks(q: str = "") -> dict[str, Any]:
    try:
        nbs = list_notebooks(query=q)
        return {"status": "OK", "count": len(nbs), "notebooks": nbs}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 목록 조회 오류: {exc}")


@app.get("/api/explorer/notebooklm/notebooks/{notebook_id}/sources")
def api_explorer_nlm_sources(notebook_id: str) -> dict[str, Any]:
    try:
        return list_notebook_sources(notebook_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 소스 조회 오류: {exc}")


@app.post("/api/explorer/notebooklm/import")
def api_explorer_nlm_import(req: NotebookLmImportRequest) -> dict[str, Any]:
    if not req.source_ids:
        raise HTTPException(status_code=400, detail="가져올 NotebookLM 소스를 1건 이상 선택해 주세요.")
    try:
        return import_notebooklm_sources(
            project_id=req.project_id,
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            source_ids=req.source_ids,
            also_ingest_rag=req.also_ingest_rag,
            chapters=req.chapters,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 가져오기 오류: {exc}")


@app.post("/api/explorer/notebooklm/query")
def api_explorer_nlm_query(req: NotebookLmQueryRequest) -> dict[str, Any]:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="질문 내용을 입력해 주세요.")
    try:
        return query_notebooklm(req.notebook_id, req.question)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 질의 오류: {exc}")
