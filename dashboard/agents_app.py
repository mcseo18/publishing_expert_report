"""단일 통합 교재 제작 플랫폼 · 6단계 에이전트 관제 대시보드 서버 (FastAPI, 기본 포트 8501).

실행:
    .venv\\Scripts\\python.exe -m uvicorn dashboard.agents_app:app --host 127.0.0.1 --port 8501
또는:
    .\\scripts\\launch_dashboards.ps1 -Target all
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
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
from plan_chatbot import (  # noqa: E402
    apply_plan_to_project,
    create_project_from_plan,
    load_plan_chat_session,
    reset_plan_chat_session,
    run_plan_based_search,
    run_plan_chat_turn,
)
from subagent_orchestrator import (  # noqa: E402
    STAGE_DEFINITIONS,
    _save_outline_files,
    approve_stage1_outline,
    create_project,
    create_stage_snapshot,
    list_stage_snapshots,
    restore_stage_snapshot,
    delete_project,
    get_ai_engines_status,
    list_projects,
    load_events,
    load_project_state,
    load_stage_report,
    reset_projects_keep_only,
    revise_stage1_outline,
    save_project_state,
    set_project_hidden,
    start_pipeline_async,
    stop_pipeline,
    update_project_options,
)

app = FastAPI(title="전문 교재 제작 통합 플랫폼 (단일 HTML 6단계 관제)", version="2.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_UNIFIED = STATIC_DIR / "unified.html"
STATIC_AGENTS = STATIC_DIR / "_legacy" / "agents.html"


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
    use_gemini_outline: bool = True
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
    use_gemini_outline: bool | None = None
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


class PlanChatSendRequest(BaseModel):
    message: str
    topic_ko: str = ""
    topic_en: str = ""
    keywords_ko: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    chapter_count: int = Field(default=12, ge=3, le=24)
    target_pages: int = Field(default=400, ge=60, le=1500)
    engine: str = "antigravity_gemini"  # antigravity_gemini | gemini_pro | openai | ollama_gemma
    include_tables: bool = True
    include_visuals: bool = True


class PlanChatApplyRequest(BaseModel):
    plan: dict[str, Any] | None = None
    approve_stage1: bool = True
    auto_start_stage2: bool = False


class PlanChatSearchRequest(BaseModel):
    queries_ko: list[str] = Field(default_factory=list)
    queries_en: list[str] = Field(default_factory=list)
    limit_per_query: int = Field(default=4, ge=1, le=10)


class PlanChatResetRequest(BaseModel):
    keep_plan: bool = False


class PlanChatCreateProjectRequest(BaseModel):
    plan: dict[str, Any]
    auto_start_stage2: bool = False


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
def api_list_projects(include_hidden: bool = False) -> dict[str, Any]:
    return {"projects": list_projects(include_hidden=include_hidden)}


class ProjectVisibilityRequest(BaseModel):
    hidden: bool


@app.post("/api/projects/{project_id}/visibility")
def api_project_visibility(project_id: str, req: ProjectVisibilityRequest) -> dict[str, Any]:
    try:
        return set_project_hidden(project_id, req.hidden)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


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
            "use_gemini_outline": req.use_gemini_outline,
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


# ---------- 대화형 교재 계획서 작성 챗봇 (Antigravity · Gemini API 기본) ----------
@app.get("/api/projects/{project_id}/plan-chat")
def api_get_plan_chat(project_id: str) -> dict[str, Any]:
    try:
        return load_plan_chat_session(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/projects/{project_id}/plan-chat/send")
def api_send_plan_chat(project_id: str, req: PlanChatSendRequest) -> dict[str, Any]:
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="챗봇에 전달할 계획서 요청 메시지를 입력해 주세요.")
    try:
        return run_plan_chat_turn(
            project_id=project_id,
            message=req.message.strip(),
            topic_ko=req.topic_ko,
            topic_en=req.topic_en,
            keywords_ko=req.keywords_ko,
            keywords_en=req.keywords_en,
            chapter_count=req.chapter_count,
            target_pages=req.target_pages,
            engine=req.engine,
            include_tables=req.include_tables,
            include_visuals=req.include_visuals,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"계획서 챗봇 생성 오류: {exc}")


@app.post("/api/projects/{project_id}/plan-chat/apply")
def api_apply_plan_chat(project_id: str, req: PlanChatApplyRequest) -> dict[str, Any]:
    try:
        return apply_plan_to_project(
            project_id=project_id,
            plan_override=req.plan,
            approve_stage1=req.approve_stage1,
            auto_start_stage2=req.auto_start_stage2,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"계획서 반영 오류: {exc}")


@app.post("/api/projects/{project_id}/plan-chat/search")
def api_search_from_plan_chat(project_id: str, req: PlanChatSearchRequest) -> dict[str, Any]:
    try:
        return run_plan_based_search(
            project_id=project_id,
            queries_ko=req.queries_ko,
            queries_en=req.queries_en,
            limit_per_query=req.limit_per_query,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"계획서 기반 검색 오류: {exc}")


@app.post("/api/projects/{project_id}/plan-chat/reset")
def api_reset_plan_chat(project_id: str, req: PlanChatResetRequest) -> dict[str, Any]:
    try:
        return reset_plan_chat_session(project_id, keep_plan=req.keep_plan)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/plan-chat/create-project")
def api_create_project_from_plan(req: PlanChatCreateProjectRequest) -> dict[str, Any]:
    try:
        return create_project_from_plan(plan=req.plan, auto_start_stage2=req.auto_start_stage2)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"계획서 기반 새 프로젝트 생성 오류: {exc}")


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
    fallback_set = set((st.get("checkpoint") or {}).get("fallback_chapters") or [])
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
                **_chapter_quality(p, cid, fallback_set, c.get("target_pages", 30)),
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
                        **_chapter_quality(p, p.stem, fallback_set, 0),
                    }
                )
    audit_path = ws / "reports" / "audit_latest.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else None
    written = [c for c in items if c["exists"]]
    summary = {
        "written": len(written),
        "total": len(items),
        "est_pages_total": sum(c.get("est_pages", 0) for c in written),
        "pages_from_pdf": sum(1 for c in written if c.get("pdf_pages")),
        "target_pages_total": int(st.get("target_pages") or sum(int(c.get("target_pages") or 0) for c in items)),
        "fallback_count": sum(1 for c in written if c.get("is_fallback")),
        "weak_count": sum(1 for c in written if c.get("quality") in ("약함", "틀 원고")),
        "chars_per_page": CHARS_PER_PAGE,
    }
    return {"chapters": items, "audit": audit, "summary": summary}


# ---------- F1: 원고 품질 점검 ----------
CHARS_PER_PAGE = 1100  # 교재 본문 1쪽 ≈ 1,100자(공백 포함, 표·그림 제외) 기준 추정치
_FALLBACK_MARKERS = ("의 핵심 원리와 정량 기준을 다룬다", "단일 지표만으로 충분하다")
_SRC_RE = re.compile(r"\[SRC-\d+\]")


_PDF_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")


_PDF_PAGE_CACHE: dict[str, tuple[float, int]] = {}


def _pdf_page_count(pdf: Path) -> int:
    """PDF 쪽수 (파일이 바뀌지 않았으면 이전 계산값 재사용)."""
    try:
        mt = pdf.stat().st_mtime
        hit = _PDF_PAGE_CACHE.get(str(pdf))
        if hit and hit[0] == mt:
            return hit[1]
        n = len(_PDF_PAGE_RE.findall(pdf.read_bytes()))
        _PDF_PAGE_CACHE[str(pdf)] = (mt, n)
        return n
    except Exception:
        return 0


def _chapter_quality(p: Path, cid: str, fallback_set: set[str], target_pages: Any = 0) -> dict[str, Any]:
    empty = {"char_count": 0, "body_chars": 0, "citation_count": 0, "est_pages": 0, "pdf_pages": 0, "pages_source": "", "is_fallback": False, "quality": "-", "quality_notes": []}
    if not p.is_file():
        return empty
    text = p.read_text(encoding="utf-8", errors="ignore")
    body = text.split("## 참고문헌 및 근거 출처 목록")[0]
    body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
    body_chars = len(body)
    cites = len(_SRC_RE.findall(body))
    marker_hits = sum(body.count(m) for m in _FALLBACK_MARKERS)
    is_fb = cid in fallback_set or marker_hits >= 2
    # 실제 출판된 교재 PDF가 있으면 그 쪽수를, 없으면 글자 수로 추정
    ws = p.parent.parent
    pdf = ws / "exports" / cid / f"{cid}_textbook.pdf"
    pdf_pages = _pdf_page_count(pdf) if pdf.is_file() else 0
    est_pages = pdf_pages or round(body_chars / CHARS_PER_PAGE, 1)
    try:
        tgt = int(target_pages or 0)
    except (TypeError, ValueError):
        tgt = 0
    notes: list[str] = []
    if is_fb:
        notes.append("AI 집필 실패로 들어간 틀 원고 — 이 단원을 다시 집필하세요")
    if tgt and est_pages < tgt * 0.5:
        notes.append(f"분량 부족: 목표 {tgt}쪽 중 {est_pages:g}쪽({round(est_pages / tgt * 100)}%)")
    elif not tgt and body_chars < 6000:
        notes.append("분량이 적음(본문 6,000자 미만)")
    if cites < 5:
        notes.append(f"인용 출처가 적음({cites}개)")
    quality = "틀 원고" if is_fb else ("약함" if notes else "양호")
    return {
        "char_count": len(text),
        "body_chars": body_chars,
        "citation_count": cites,
        "est_pages": est_pages,
        "pdf_pages": pdf_pages,
        "pages_source": "PDF" if pdf_pages else "글자 수 추정",
        "is_fallback": is_fb,
        "quality": quality,
        "quality_notes": notes,
    }


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


# ---------- F4: 원고 직접 수정 (수정 전 원고는 chapters/_history 에 자동 보관) ----------
class ChapterSaveRequest(BaseModel):
    content: str
    note: str = ""


@app.put("/api/projects/{project_id}/chapters/{chapter_id}")
def api_save_chapter(project_id: str, chapter_id: str, req: ChapterSaveRequest) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    safe_cid = Path(chapter_id).name.replace(".mdx", "")
    ch_dir = Path(st["workspace_dir"]) / "chapters"
    p = ch_dir / f"{safe_cid}.mdx"
    if not p.is_file():
        raise HTTPException(status_code=404, detail="아직 집필되지 않은 단원은 수정할 수 없습니다.")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="빈 원고는 저장할 수 없습니다.")
    hist = ch_dir / "_history"
    hist.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = hist / f"{safe_cid}_{ts}.mdx"
    n = 2
    while backup.exists():
        backup = hist / f"{safe_cid}_{ts}_{n}.mdx"
        n += 1
    shutil.copy2(p, backup)
    p.write_text(req.content.replace("\r\n", "\n"), encoding="utf-8")
    # 사람이 직접 고친 단원은 틀 원고 표시를 해제
    ck = st.setdefault("checkpoint", {})
    fb = set(ck.get("fallback_chapters") or [])
    if safe_cid in fb:
        fb.discard(safe_cid)
        ck["fallback_chapters"] = sorted(fb)
        save_project_state(st)
    return {"status": "SAVED", "chapter_id": safe_cid, "backup": backup.name, "chars": len(req.content)}


@app.get("/api/projects/{project_id}/chapters/{chapter_id}/history")
def api_chapter_history(project_id: str, chapter_id: str) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    safe_cid = Path(chapter_id).name.replace(".mdx", "")
    hist = Path(st["workspace_dir"]) / "chapters" / "_history"
    items = sorted(hist.glob(f"{safe_cid}_*.mdx"), reverse=True) if hist.is_dir() else []
    return {"history": [{"name": h.name, "saved_at": h.stem[len(safe_cid) + 1:], "chars": h.stat().st_size} for h in items[:20]]}


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/history/{name}/restore")
def api_chapter_history_restore(project_id: str, chapter_id: str, name: str) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    safe_cid = Path(chapter_id).name.replace(".mdx", "")
    ch_dir = Path(st["workspace_dir"]) / "chapters"
    src = ch_dir / "_history" / Path(name).name
    if not src.is_file() or not src.name.startswith(safe_cid + "_"):
        raise HTTPException(status_code=404, detail="보관본을 찾을 수 없습니다.")
    return api_save_chapter(project_id, safe_cid, ChapterSaveRequest(content=src.read_text(encoding="utf-8"), note=f"restore {src.name}"))


# ---------- F3: 재실행 전 자동 백업 목록 · 되돌리기 ----------
@app.get("/api/projects/{project_id}/snapshots")
def api_list_snapshots(project_id: str) -> dict[str, Any]:
    try:
        return {"snapshots": list_stage_snapshots(project_id)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/projects/{project_id}/snapshots/{snapshot_id}/restore")
def api_restore_snapshot(project_id: str, snapshot_id: str) -> dict[str, Any]:
    try:
        return restore_stage_snapshot(project_id, snapshot_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------- F7: 산출물 한 번에 내려받기 · 폴더 열기 ----------
@app.get("/api/projects/{project_id}/exports.zip")
def api_exports_zip(project_id: str):
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = Path(st["workspace_dir"])
    exp = ws / "exports"
    if not exp.is_dir():
        raise HTTPException(status_code=404, detail="아직 출판 산출물이 없습니다. 6단계를 먼저 실행하세요.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in exp.rglob("*"):
            if f.is_file():
                zf.write(f, f"exports/{f.relative_to(exp).as_posix()}")
        for rp in (ws / "reports").glob("*.md") if (ws / "reports").is_dir() else []:
            zf.write(rp, f"reports/{rp.name}")
    buf.seek(0)
    fname = f"{project_id}_exports_{datetime.now().strftime('%Y%m%d')}.zip"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class OpenFolderRequest(BaseModel):
    target: str = "exports"  # exports | chapters | assets | reports | workspace | e_visuals | collected


@app.post("/api/projects/{project_id}/open-folder")
def api_open_folder(project_id: str, req: OpenFolderRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = Path(st["workspace_dir"])
    mapping = {
        "workspace": ws,
        "exports": ws / "exports",
        "chapters": ws / "chapters",
        "assets": ws / "assets" / "by_chapter",
        "reports": ws / "reports",
        "e_visuals": cfg.e_projects_dir / project_id / "visuals",
        "collected": Path(st.get("collected_dir") or (ws / "collected")),
    }
    target = mapping.get(req.target)
    if not target:
        raise HTTPException(status_code=400, detail="알 수 없는 폴더입니다.")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"폴더가 아직 없습니다: {target}")
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            raise OSError("Windows 탐색기 열기는 Windows에서만 지원됩니다.")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"폴더 열기 실패: {exc} — 경로: {target}")
    return {"status": "OPENED", "path": str(target)}


# ---------- F2: 그림 한 장만 다시 만들기 ----------
class RegenerateVisualRequest(BaseModel):
    figure_id: str
    prompt: str | None = None  # 비우면 기존 프롬프트 그대로 사용


@app.post("/api/projects/{project_id}/visuals/regenerate")
def api_regenerate_visual(project_id: str, req: RegenerateVisualRequest) -> dict[str, Any]:
    from data_connectors import resolve_api_key
    from visual_studio import _generate_with_fal_ai, _generate_with_nano_banana

    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    assets_dir = Path(st["workspace_dir"]) / "assets"
    plan_p = assets_dir / "visuals_plan.json"
    if not plan_p.is_file():
        raise HTTPException(status_code=404, detail="시각화 목록(visuals_plan.json)이 없습니다. 5단계를 먼저 실행하세요.")
    plan = json.loads(plan_p.read_text(encoding="utf-8"))
    items = plan.get("visuals") or plan.get("items") or []
    rec = next((r for r in items if r.get("figure_id") == req.figure_id), None)
    if not rec:
        raise HTTPException(status_code=404, detail="해당 그림을 찾을 수 없습니다.")
    if str(rec.get("is_ai_image")).lower() not in ("true", "1"):
        raise HTTPException(status_code=400, detail="이 그림은 AI 이미지가 아닌 자동 도표(SVG)라 다시 만들 필요가 없습니다.")
    prompt = (req.prompt or rec.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="이미지 프롬프트가 없습니다.")

    out_png = assets_dir / "figures" / f"{rec['figure_id']}.png"
    tmp_png = out_png.with_name(out_png.stem + "_regen_tmp.png")
    opts = st.get("options") or {}
    engine_txt = str(rec.get("engine") or "")
    ok, msg = False, ""
    errors: list[str] = []
    fal_key = resolve_api_key("FAL_KEY", None, cfg)
    gem_key = resolve_api_key("GEMINI_API_KEY", None, cfg)
    if "fal.ai" in engine_txt and fal_key:
        try:
            ok, msg = _generate_with_fal_ai(prompt=prompt, out_path=tmp_png, fal_model=opts.get("fal_model") or "fal-ai/nano-banana", api_key=fal_key)
        except Exception as exc:
            errors.append(f"fal.ai: {str(exc)[:120]}")
    if not ok and gem_key:
        m = re.search(r"Nano Banana \(([^)]+)\)", engine_txt)
        model = m.group(1) if m else "gemini-2.5-flash-image"
        try:
            ok, msg = _generate_with_nano_banana(prompt=prompt, out_path=tmp_png, model=model, api_key=gem_key)
        except Exception as exc:
            errors.append(f"나노바나나: {str(exc)[:120]}")
    if not ok and fal_key and "fal.ai" not in engine_txt:
        try:
            ok, msg = _generate_with_fal_ai(prompt=prompt, out_path=tmp_png, fal_model=opts.get("fal_model") or "fal-ai/nano-banana", api_key=fal_key)
        except Exception as exc:
            errors.append(f"fal.ai: {str(exc)[:120]}")
    if not ok:
        if not (fal_key or gem_key):
            errors.append("FAL_KEY 또는 GEMINI_API_KEY가 등록되어 있지 않습니다 (설정 탭에서 등록)")
        raise HTTPException(status_code=502, detail="그림 생성 실패: " + (" / ".join(errors) or msg or "알 수 없는 오류"))

    # 기존 그림은 assets/_replaced 에 보관
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_png.is_file():
        rep_dir = assets_dir / "_replaced"
        rep_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_png, rep_dir / f"{out_png.stem}_{ts}.png")
    os.replace(tmp_png, out_png)
    for key in ("chapter_dir_local", "chapter_dir_e"):
        d = rec.get(key)
        if d:
            try:
                Path(d).mkdir(parents=True, exist_ok=True)
                shutil.copy2(out_png, Path(d) / out_png.name)
            except Exception:
                pass
    rec["path"] = str(out_png)
    rec["filename"] = out_png.name
    rec["docx_image_path"] = str(out_png)
    rec["rel_url"] = rec["png_url"] = f"/project-files/{project_id}/assets/figures/{out_png.name}"
    rec["engine"] = msg
    rec["prompt"] = prompt
    rec["regenerated_at"] = ts
    plan_text = json.dumps(plan, ensure_ascii=False, indent=2)
    plan_p.write_text(plan_text, encoding="utf-8")
    try:
        e_plan = cfg.e_projects_dir / project_id / "visuals" / "visuals_plan.json"
        if e_plan.parent.is_dir():
            e_plan.write_text(plan_text, encoding="utf-8")
    except Exception:
        pass
    return {"status": "REGENERATED", "figure_id": rec["figure_id"], "engine": msg, "png_url": rec["png_url"] + f"?v={ts}", "note": "PDF·DOCX·블로그에 반영하려면 6단계(출판)를 다시 실행하세요."}


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {"status": "OK"}


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
