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
from agro_framework import (  # noqa: E402
    AGRO_CORE_KEYWORDS_31,
    AGRO_SPECIALTY_CURRICULA,
    BRAND_IDENTITY,
    CONTEXT_AWARE_4STAGE_TEMPLATE,
    CROP_GDD_PROFILES,
    MULTI_TRIM_SPECS,
    auto_repair_chapter_citations,
    bind_project_master_formats,
    build_citation_inspector_report,
    compute_gdd_traffic_light,
    generate_dual_dpi_assets,
    render_live_dual_preview,
)
from monetization_packager import (  # noqa: E402
    POD_PLATFORMS,
    build_b2g_delivery_package,
    build_naver_marketing_bundle,
    build_pod_export_package,
    generate_saas_license_package,
    get_monetization_overview,
    simulate_monetization_revenue,
)
from image_generation_studio import (  # noqa: E402
    get_studio_state,
    plan_visual_queue,
    start_batch_generation_async,
    stop_batch_generation,
    sync_studio_to_pipeline,
    update_queue_item,
    upload_custom_image,
)
from output_converter import (  # noqa: E402
    CONVERSION_FORMATS,
    KOREAN_JOURNAL_PDF_SPEC,
    convert_project_output,
    list_project_outputs_summary,
    publish_default_outputs,
)
from persona_studio import (  # noqa: E402
    BUILTIN_PERSONAS,
    DEFAULT_PERSONA_BY_TYPE,
    compile_persona_system_prompt,
    delete_custom_persona,
    list_personas,
    resolve_project_persona,
    save_custom_persona,
)
from chapter_pipeline import (  # noqa: E402
    CHAPTER_RESEARCH_DEPTHS,
    get_chapter_pipeline_board,
    start_chapter_pipeline_async,
    stop_chapter_pipeline,
)
from rag_capture_unifier import (  # noqa: E402
    get_unified_rag_status,
    search_unified_smc_rag,
    sync_all_existing_sources_to_smc_graphrag,
)
from deep_research_engine import (  # noqa: E402
    harvest_selected_research_items,
    load_deep_research_state,
    start_deep_research_async,
    stop_deep_research,
)
from output_type_profiles import (  # noqa: E402
    PRIMARY_OUTPUT_TYPES,
    get_output_type_spec,
    resolve_output_profile,
)
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
    build_last_work_summary,
    create_project,
    create_stage_snapshot,
    evaluate_publish_readiness,
    list_stage_snapshots,
    restore_stage_snapshot,
    delete_project,
    get_ai_engines_status,
    list_projects,
    load_events,
    load_project_from_folder,
    load_project_state,
    load_stage_report,
    reset_projects_keep_only,
    revise_stage1_outline,
    save_project_state,
    scan_project_folders,
    set_chapter_expert_review,
    set_project_hidden,
    start_pipeline_async,
    stop_pipeline,
    update_project_options,
    write_last_work_session,
)

app = FastAPI(
    title="참참살이 영농 AI 출판도우미 · 통합 출판 프레임워크 대시보드",
    version="3.0.0",
)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_UNIFIED = STATIC_DIR / "unified.html"
STATIC_SETUP = STATIC_DIR / "setup.html"
STATIC_AGENTS = STATIC_DIR / "_legacy" / "agents.html"


# ============================================================
# Pydantic 요청 모델
# ============================================================
class CreateProjectRequest(BaseModel):
    topic_ko: str
    topic_en: str = ""
    primary_output_type: str = "textbook"  # textbook | web_publish | lecture | report | paper | storybook
    output_profile: dict[str, Any] | None = None
    persona: dict[str, Any] | None = None
    keywords_ko: list[str] = Field(default_factory=list)
    keywords_en: list[str] = Field(default_factory=list)
    domestic_agency_urls: list[str] = Field(default_factory=list)
    international_agency_urls: list[str] = Field(default_factory=list)
    target_audience: str = "대학 전공 심화, 대학원생, 연구자 및 선도 현장 실무자"
    target_pages: int = Field(default=450, ge=10, le=1500)
    chapter_count: int = Field(default=14, ge=3, le=24)
    papers_per_query: int = Field(default=5, ge=2, le=15)
    use_gemini_outline: bool = True
    use_fal_ai: bool = False
    fal_model: str = "fal-ai/nano-banana"
    use_nano_banana: bool = True
    visuals_per_chapter: int = Field(default=4, ge=0, le=25)
    gemma_model: str = "gemma4:26b"
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
    use_gemini: bool | None = None


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
    download_pdf: bool = True
    capture_webpage: bool = True
    auto_unify_rag: bool = True


class ScholarBatchIngestRequest(BaseModel):
    project_id: str
    papers: list[dict[str, Any]]
    download_pdf: bool = True
    capture_webpage: bool = True
    auto_unify_rag: bool = True


class UrlCollectRequest(BaseModel):
    project_id: str
    url: str
    title_hint: str = ""
    license_note: str = "공개 웹 자료"
    capture_screenshot: bool = True
    auto_unify_rag: bool = True


class BibtexCollectRequest(BaseModel):
    project_id: str
    bibtex_text: str
    download_pdf: bool = True
    auto_unify_rag: bool = True


class SaveApiKeysRequest(BaseModel):
    GEMINI_API_KEY: str = ""
    FAL_KEY: str = ""
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
    engine: str = "antigravity_gemini"  # antigravity_gemini | gemini_pro | ollama_gemma
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


@app.get("/setup", response_class=HTMLResponse)
def setup_wizard_page() -> HTMLResponse:
    if not STATIC_SETUP.is_file():
        return HTMLResponse("<h1>setup.html missing</h1>", status_code=500)
    return HTMLResponse(STATIC_SETUP.read_text(encoding="utf-8"))


@app.get("/api/output-types")
def api_list_output_types() -> dict[str, Any]:
    return {"output_types": PRIMARY_OUTPUT_TYPES}


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


@app.get("/api/projects/folders")
def api_scan_project_folders(include_archived: bool = False) -> dict[str, Any]:
    """projects/ 폴더(및 선택 시 아카이브 폴더)를 스캔해 각 프로젝트의 마지막 작업 기록과 함께 반환한다."""
    cfg = get_config()
    return {
        "projects_root": str((cfg.workspace_root / "projects").resolve()),
        "folders": scan_project_folders(include_archived=include_archived, cfg=cfg),
    }


class LoadFolderRequest(BaseModel):
    folder_path: str


@app.post("/api/projects/load-folder")
def api_load_project_folder(req: LoadFolderRequest) -> dict[str, Any]:
    if not req.folder_path.strip():
        raise HTTPException(status_code=400, detail="불러올 프로젝트 폴더 경로를 입력하거나 선택해 주세요.")
    try:
        return load_project_from_folder(req.folder_path.strip())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"폴더 불러오기 오류: {exc}")


@app.post("/api/projects/browse-folder-dialog")
def api_browse_folder_dialog() -> dict[str, Any]:
    """Windows 기본 폴더 선택 창을 열어 사용자가 직접 프로젝트 폴더를 고를 수 있게 한다."""
    cfg = get_config()
    initial_dir = str((cfg.workspace_root / "projects").resolve())
    try:
        import subprocess

        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dlg.Description = '불러올 이전 교재 프로젝트 폴더를 선택하세요'; "
            f"$dlg.SelectedPath = '{initial_dir.replace(chr(39), chr(39)*2)}'; "
            "$top = New-Object System.Windows.Forms.Form; $top.TopMost = $true; "
            "if ($dlg.ShowDialog($top) -eq 'OK') { Write-Output $dlg.SelectedPath }"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120,
        )
        chosen = (proc.stdout or "").strip()
        return {"status": "OK" if chosen else "CANCELLED", "folder_path": chosen}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "folder_path": "", "detail": str(exc)[:140]}


class LastWorkRecordRequest(BaseModel):
    last_tab: str | None = None
    last_subtab: str | None = None
    last_stage_id: str | None = None
    last_open_chapter: str | None = None
    last_visual_filter: str | None = None
    last_action_summary: str | None = None


@app.post("/api/projects/{project_id}/last-work")
def api_save_last_work(project_id: str, req: LastWorkRecordRequest) -> dict[str, Any]:
    try:
        sess = write_last_work_session(project_id, overrides=req.model_dump(exclude_none=True))
        return {"status": "SAVED", "last_work_session": sess}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


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
        raise HTTPException(status_code=400, detail="주제(국문)를 입력해 주세요.")
    resolved_prof = resolve_output_profile(req.primary_output_type, req.output_profile)
    type_spec = get_output_type_spec(req.primary_output_type)
    st = create_project(
        topic_ko=req.topic_ko,
        topic_en=req.topic_en,
        keywords_ko=req.keywords_ko,
        keywords_en=req.keywords_en,
        target_audience=req.target_audience,
        target_pages=req.target_pages,
        chapter_count=req.chapter_count,
        primary_output_type=req.primary_output_type,
        output_profile=resolved_prof,
        persona=req.persona,
        options={
            "papers_per_query": req.papers_per_query,
            "domestic_agency_urls": req.domestic_agency_urls,
            "international_agency_urls": req.international_agency_urls,
            "use_gemini_outline": req.use_gemini_outline,
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
            "trim_formats": type_spec.get("trim_formats", ["shinkuk", "b5", "a4"]),
        },
    )
    run_info = None
    if req.auto_start:
        # 1단계(주제 탐색 + Google Gemini 목차·요약·키워드 제시)를 즉시 시작하고 검토 게이트에서 자동 대기
        run_info = start_pipeline_async(st["project_id"], mode="single", target_stage="stage1_topic_outline")
    return {"status": "OK", "project": st, "run": run_info}


class UpdateOutputProfileRequest(BaseModel):
    primary_output_type: str = "textbook"
    output_profile: dict[str, Any] = Field(default_factory=dict)
    persona: dict[str, Any] | None = None
    target_pages: int | None = None
    chapter_count: int | None = None
    target_audience: str | None = None
    visuals_per_chapter: int | None = None


@app.patch("/api/projects/{project_id}/output-profile")
def api_update_output_profile(project_id: str, req: UpdateOutputProfileRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    prof = resolve_output_profile(req.primary_output_type, req.output_profile)
    spec = get_output_type_spec(req.primary_output_type)
    st["primary_output_type"] = prof["primary_output_type"]
    st["output_profile"] = prof
    if req.persona is not None:
        st["persona"] = resolve_project_persona(prof["primary_output_type"], req.persona, cfg=cfg)
    if req.target_pages is not None:
        st["target_pages"] = max(10, int(req.target_pages))
    if req.chapter_count is not None:
        st["chapter_count"] = max(3, min(24, int(req.chapter_count)))
    if req.target_audience is not None:
        st["target_audience"] = req.target_audience.strip()
    opts = st.setdefault("options", {})
    if req.visuals_per_chapter is not None:
        opts["visuals_per_chapter"] = max(0, min(25, int(req.visuals_per_chapter)))
    opts["enable_myths"] = bool(prof.get("include_myths", True))
    opts["enable_linked_quiz"] = bool(prof.get("include_exercises", True))
    opts["enable_naver_blog"] = bool(prof.get("include_naver_hashtags", True))
    opts["trim_formats"] = spec.get("trim_formats", ["shinkuk", "b5", "a4"])
    save_project_state(st, cfg)
    return {"status": "UPDATED", "project": st}


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str, limit_events: int = 120) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    # 폴더 내 last_work_session.json 우선 병합
    lw = st.get("last_work_session") or {}
    try:
        ws = Path(st.get("workspace_dir") or cfg.project_dir(project_id))
        lw_p = ws / "last_work_session.json"
        if lw_p.is_file():
            lw_disk = json.loads(lw_p.read_text(encoding="utf-8"))
            if isinstance(lw_disk, dict) and lw_disk.get("saved_at", "") >= str(lw.get("saved_at", "")):
                lw = lw_disk
        if not lw:
            lw = build_last_work_summary(st, cfg=cfg)
    except Exception:
        if not lw:
            lw = build_last_work_summary(st, cfg=cfg)
    st["last_work_session"] = lw
    try:
        ap = cfg.index_dir / "active_project.json"
        ap.write_text(
            json.dumps({"project_id": project_id, "topic_ko": st.get("topic_ko", "")}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return {"project": st, "events": load_events(project_id, limit=limit_events), "last_work_session": lw}


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
        return revise_stage1_outline(project_id, req.feedback_prompt.strip(), use_gemini=req.use_gemini)
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
    audit_by_ch: dict[str, dict[str, Any]] = {}
    if audit and isinstance(audit.get("files"), list):
        for fr in audit["files"]:
            fname = Path(str(fr.get("file") or "")).stem
            if fname:
                audit_by_ch[fname] = fr

    # C1/C6/C9/V7: 단원별 근거 관련도 · 내용 일치율 · 그림 출처 유무 · 전문가 검토 상태 결합
    from visual_studio import audit_visual_assets

    collected = st.get("collected_sources") or []
    rel_vals = [float(s["relevance_score"]) for s in collected if s.get("relevance_score") is not None]
    proj_rel_pct = round((sum(rel_vals) / len(rel_vals)) * 100.0, 1) if rel_vals else None
    reviews = st.get("chapter_reviews") or {}
    vis_qa = audit_visual_assets(project_id, cfg=cfg)
    vis_by_ch: dict[str, list[dict[str, Any]]] = {}
    for vi in vis_qa.get("items") or []:
        vis_by_ch.setdefault(vi.get("chapter_id", ""), []).append(vi)

    for it in items:
        cid = it["chapter_id"]
        fr = audit_by_ch.get(cid) or {}
        ca = fr.get("content_audit") or {}
        ch_vis = vis_by_ch.get(cid) or []
        vis_ok_cnt = sum(1 for v in ch_vis if v.get("has_source") and v.get("publishable"))
        rev_obj = reviews.get(cid) or {}
        it["evidence_relevance_pct"] = proj_rel_pct
        it["alignment_rate_pct"] = ca.get("alignment_rate_pct")
        it["unrelated_ratio_pct"] = ca.get("unrelated_ratio_pct")
        it["formula_error_count"] = len(fr.get("formula_errors") or [])
        it["visual_total"] = len(ch_vis)
        it["visual_source_ok_count"] = vis_ok_cnt
        it["visual_source_status"] = (
            f"{vis_ok_cnt}/{len(ch_vis)}" if ch_vis else "-"
        )
        it["expert_reviewed"] = bool(rev_obj.get("reviewed", False))
        it["expert_review"] = rev_obj

    readiness = evaluate_publish_readiness(project_id, cfg=cfg)
    written = [c for c in items if c["exists"]]
    summary = {
        "written": len(written),
        "total": len(items),
        "est_pages_total": sum(c.get("est_pages", 0) for c in written),
        "pages_from_pdf": sum(1 for c in written if c.get("pdf_pages")),
        "target_pages_total": int(st.get("target_pages") or sum(int(c.get("target_pages") or 0) for c in items)),
        "fallback_count": sum(1 for c in written if c.get("is_fallback")),
        "weak_count": sum(1 for c in written if c.get("quality") in ("약함", "틀 원고")),
        "reviewed_count": sum(1 for c in written if c.get("expert_reviewed")),
        "avg_evidence_relevance_pct": proj_rel_pct,
        "chars_per_page": CHARS_PER_PAGE,
    }
    return {"chapters": items, "audit": audit, "summary": summary, "publish_readiness": readiness}


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
        model = m.group(1) if m else "nano-banana-pro-preview"
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
            capture_webpage=req.capture_webpage,
            auto_unify_rag=req.auto_unify_rag,
            cfg=cfg,
        )
        sid = res.get("source_id") or (res.get("existing") or {}).get("source_id")
        if sid and not any(s.get("source_id") == sid for s in st.get("collected_sources", [])):
            st.setdefault("collected_sources", []).append(
                {
                    "source_id": sid,
                    "title": req.paper.get("title", ""),
                    "url": req.paper.get("url", ""),
                    "year": req.paper.get("year"),
                    "provider": req.paper.get("provider", "Academic"),
                    "tier_folder": "04_international_journals",
                    "capture_mode": res.get("capture_mode", ""),
                    "pdf_downloaded": bool(res.get("pdf_downloaded")),
                    "capture_png_path": res.get("capture_png_path", ""),
                    "rag_unified": bool(res.get("rag_unified")),
                }
            )
            save_project_state(st, cfg)
        return {"status": "OK", "result": res}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"논문 적재 오류: {exc}")


@app.post("/api/collect/scholar/ingest-batch")
def api_collect_scholar_ingest_batch(req: ScholarBatchIngestRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(req.project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    results: list[dict[str, Any]] = []
    pdf_cnt = 0
    cap_cnt = 0
    rag_cnt = 0
    for paper in req.papers[:25]:
        try:
            res = ingest_paper_record(
                paper=paper,
                packet_id=st["packet_id"],
                topic=st.get("topic_ko", ""),
                download_oa_pdf=req.download_pdf,
                capture_webpage=req.capture_webpage,
                auto_unify_rag=req.auto_unify_rag,
                cfg=cfg,
            )
            results.append(res)
            if res.get("pdf_downloaded"):
                pdf_cnt += 1
            if res.get("capture_png_path"):
                cap_cnt += 1
            if res.get("rag_unified"):
                rag_cnt += 1
            sid = res.get("source_id") or (res.get("existing") or {}).get("source_id")
            if sid and not any(s.get("source_id") == sid for s in st.get("collected_sources", [])):
                st.setdefault("collected_sources", []).append(
                    {
                        "source_id": sid,
                        "title": paper.get("title", ""),
                        "url": paper.get("url", ""),
                        "year": paper.get("year"),
                        "provider": paper.get("provider", "Academic"),
                        "tier_folder": "04_international_journals",
                        "capture_mode": res.get("capture_mode", ""),
                        "pdf_downloaded": bool(res.get("pdf_downloaded")),
                        "capture_png_path": res.get("capture_png_path", ""),
                        "rag_unified": bool(res.get("rag_unified")),
                    }
                )
        except Exception as exc:
            results.append({"status": "ERROR", "title": paper.get("title", ""), "error": str(exc)})
    save_project_state(st, cfg)
    return {
        "status": "OK",
        "processed": len(results),
        "pdf_downloaded": pdf_cnt,
        "web_captured": cap_cnt,
        "rag_unified": rag_cnt,
        "results": results,
    }


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
            capture_screenshot=req.capture_screenshot,
            auto_unify_rag=req.auto_unify_rag,
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
                    "capture_mode": res.get("capture_mode", ""),
                    "pdf_downloaded": bool(res.get("pdf_path")),
                    "capture_png_path": res.get("capture_png_path", ""),
                    "rag_unified": bool(res.get("rag_unified")),
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
        res = ingest_paper_record(
            paper=p,
            packet_id=st["packet_id"],
            topic=st.get("topic_ko", ""),
            download_oa_pdf=req.download_pdf,
            capture_webpage=True,
            auto_unify_rag=req.auto_unify_rag,
            cfg=cfg,
        )
        results.append(res)
    return {"status": "OK", "ingested_count": len(results), "results": results}


# ============================================================
# C:\SMC_GRAPHRAG 통합 RAG 아카이브 현황 · 일괄 결합 · 전문검색 API
# ============================================================
@app.get("/api/rag/unified/status")
def api_rag_unified_status() -> dict[str, Any]:
    return get_unified_rag_status()


class RagUnifiedSyncRequest(BaseModel):
    capture_missing_web: bool = False
    use_ollama_kg: bool = False


@app.post("/api/rag/unified/sync-all")
def api_rag_unified_sync_all(req: RagUnifiedSyncRequest) -> dict[str, Any]:
    return sync_all_existing_sources_to_smc_graphrag(
        capture_missing_web=req.capture_missing_web,
        use_ollama_kg=req.use_ollama_kg,
    )


class RagUnifiedSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=12, ge=1, le=50)


@app.post("/api/rag/unified/search")
def api_rag_unified_search(req: RagUnifiedSearchRequest) -> dict[str, Any]:
    return search_unified_smc_rag(req.query, limit=req.limit)


# ============================================================
# 대규모 4-Wave 멀티채널 딥 리서치 센터 API
# ============================================================
@app.get("/api/projects/{project_id}/deep-research")
def api_deep_research_state(project_id: str) -> dict[str, Any]:
    try:
        return load_deep_research_state(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"딥 리서치 상태 조회 오류: {exc}")


class DeepResearchStartRequest(BaseModel):
    query: str = ""
    depth: str = "deep"  # standard | deep | exhaustive
    channels: list[str] | None = None
    year_from: int | None = 2016
    enable_snowball: bool = True
    auto_harvest_top_n: int = Field(default=25, ge=0, le=150)
    chapter_mode: bool = False


@app.post("/api/projects/{project_id}/deep-research/start")
def api_deep_research_start(project_id: str, req: DeepResearchStartRequest) -> dict[str, Any]:
    try:
        return start_deep_research_async(
            project_id=project_id,
            query=req.query,
            depth=req.depth,
            channels=req.channels,
            year_from=req.year_from,
            enable_snowball=req.enable_snowball,
            auto_harvest_top_n=req.auto_harvest_top_n,
            chapter_mode=req.chapter_mode,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"딥 리서치 실행 오류: {exc}")


@app.post("/api/projects/{project_id}/deep-research/stop")
def api_deep_research_stop(project_id: str) -> dict[str, Any]:
    return stop_deep_research(project_id)


class DeepResearchHarvestRequest(BaseModel):
    ranks: list[int] = Field(default_factory=list)


@app.post("/api/projects/{project_id}/deep-research/harvest")
def api_deep_research_harvest(project_id: str, req: DeepResearchHarvestRequest) -> dict[str, Any]:
    if not req.ranks:
        raise HTTPException(status_code=400, detail="적재할 문헌을 1건 이상 선택해 주세요.")
    try:
        return harvest_selected_research_items(project_id=project_id, ranks=req.ranks)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"선택 문헌 적재 오류: {exc}")


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


# ============================================================
# 참참살이 영농 AI 출판도우미 — Phase 1~4 프레임워크 & 수익화 API
# ============================================================
@app.get("/api/framework/catalog")
def api_framework_catalog() -> dict[str, Any]:
    return {
        "brand": BRAND_IDENTITY,
        "core_keywords_31": AGRO_CORE_KEYWORDS_31,
        "specialty_curricula": AGRO_SPECIALTY_CURRICULA,
        "context_4stage_template": CONTEXT_AWARE_4STAGE_TEMPLATE,
        "gdd_crop_profiles": CROP_GDD_PROFILES,
        "trim_specs": MULTI_TRIM_SPECS,
        "pod_platforms": POD_PLATFORMS,
    }


class WorkbenchPreviewRequest(BaseModel):
    chapter_id: str = "ch01"
    markdown: str = ""
    mode: str = "print"  # print | web
    trim_format: str = "b5"  # shinkuk | b5 | a4


@app.post("/api/projects/{project_id}/workbench/preview")
def api_workbench_preview(project_id: str, req: WorkbenchPreviewRequest) -> dict[str, Any]:
    try:
        return render_live_dual_preview(
            project_id=project_id,
            chapter_id=req.chapter_id,
            markdown_text=req.markdown,
            mode=req.mode,
            trim_format=req.trim_format,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"실시간 프리뷰 렌더링 오류: {exc}")


@app.get("/api/projects/{project_id}/inspector/qa")
def api_inspector_qa(project_id: str, chapter_id: str | None = None) -> dict[str, Any]:
    try:
        return build_citation_inspector_report(project_id, chapter_id=chapter_id or None)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"인용·QA 검사 오류: {exc}")


class InspectorAuditRequest(BaseModel):
    chapter_id: str | None = None
    auto_repair: bool = False


@app.post("/api/projects/{project_id}/inspector/audit")
def api_inspector_audit(project_id: str, req: InspectorAuditRequest) -> dict[str, Any]:
    try:
        repair_res = None
        if req.auto_repair:
            repair_res = auto_repair_chapter_citations(project_id, chapter_id=req.chapter_id)
        report = build_citation_inspector_report(project_id, chapter_id=req.chapter_id)
        return {"status": report["status"], "repair": repair_res, "report": report}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"감사 실행 오류: {exc}")


@app.post("/api/projects/{project_id}/visuals/optimize-dpi")
def api_visuals_optimize_dpi(project_id: str) -> dict[str, Any]:
    try:
        return generate_dual_dpi_assets(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"이중 해상도(300dpi/72dpi) 변환 오류: {exc}")


class MultiFormatBindRequest(BaseModel):
    trim_formats: list[str] = Field(default_factory=lambda: ["shinkuk", "b5", "a4"])
    build_docx: bool = True


@app.post("/api/projects/{project_id}/publish/multi-format")
def api_publish_multi_format(project_id: str, req: MultiFormatBindRequest) -> dict[str, Any]:
    try:
        return bind_project_master_formats(
            project_id,
            trim_formats=req.trim_formats,
            build_docx=req.build_docx,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"멀티 판형 마스터 제본 오류: {exc}")


class GddDiagnoseRequest(BaseModel):
    crop_key: str = "wheat"
    station: str = "수원"
    start_date: str = ""
    end_date: str = ""
    t_base_override: float | None = None
    custom_daily_temps: list[dict[str, float]] | None = None


@app.post("/api/agro/gdd-diagnose")
def api_agro_gdd_diagnose(req: GddDiagnoseRequest) -> dict[str, Any]:
    try:
        return compute_gdd_traffic_light(
            crop_key=req.crop_key,
            station=req.station,
            start_date=req.start_date,
            end_date=req.end_date,
            t_base_override=req.t_base_override,
            custom_daily_temps=req.custom_daily_temps,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GDD 생육 진단 연산 오류: {exc}")


@app.get("/api/projects/{project_id}/monetization/overview")
def api_monetization_overview(project_id: str) -> dict[str, Any]:
    try:
        return get_monetization_overview(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


class PodExportRequest(BaseModel):
    platform: str = "bookk"
    author: str = "참참살이 영농 AI 출판위원회"
    author_bio: str = "스마트 농업·작물생리·데이터 기반 정밀농업 전문 연구 및 현장 컨설팅 저자."
    list_price_krw: int = 28000
    isbn_placeholder: str = "발급 예정 (POD 플랫폼 신청)"
    book_intro: str = ""


@app.post("/api/projects/{project_id}/monetization/pod-export")
def api_monetization_pod_export(project_id: str, req: PodExportRequest) -> dict[str, Any]:
    try:
        return build_pod_export_package(
            project_id=project_id,
            platform=req.platform,
            author=req.author,
            author_bio=req.author_bio,
            list_price_krw=req.list_price_krw,
            isbn_placeholder=req.isbn_placeholder,
            book_intro=req.book_intro,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"POD 패키지 생성 오류: {exc}")


class B2gExportRequest(BaseModel):
    client_org: str = "지역 농업기술센터 / 지자체 농정과"
    contract_title: str = ""
    trim_format: str = "a4"
    contract_amount_krw: int = 5000000


@app.post("/api/projects/{project_id}/monetization/b2g-export")
def api_monetization_b2g_export(project_id: str, req: B2gExportRequest) -> dict[str, Any]:
    try:
        return build_b2g_delivery_package(
            project_id=project_id,
            client_org=req.client_org,
            contract_title=req.contract_title,
            trim_format=req.trim_format,
            contract_amount_krw=req.contract_amount_krw,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"B2B/B2G 패키지 생성 오류: {exc}")


class BlogPackRequest(BaseModel):
    academy_cta_title: str = "참참살이 영농 AI 아카데미 · 주간 정밀영농 리포트 구독 안내"
    academy_cta_url: str = "https://blog.naver.com/"


@app.post("/api/projects/{project_id}/monetization/blog-pack")
def api_monetization_blog_pack(project_id: str, req: BlogPackRequest) -> dict[str, Any]:
    try:
        return build_naver_marketing_bundle(
            project_id=project_id,
            academy_cta_title=req.academy_cta_title,
            academy_cta_url=req.academy_cta_url,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"블로그 마케팅 번들 생성 오류: {exc}")


class SaasPackRequest(BaseModel):
    tenant_name: str = "참참살이 영농 AI 출판 파트너"
    domain_vertical: str = "스마트 농업 · 생명과학"
    plan_tier: str = "Pro Author (월 49,000원)"
    monthly_quota_chapters: int = 40


@app.post("/api/projects/{project_id}/monetization/saas-package")
def api_monetization_saas_pack(project_id: str, req: SaasPackRequest) -> dict[str, Any]:
    try:
        return generate_saas_license_package(
            project_id=project_id,
            tenant_name=req.tenant_name,
            domain_vertical=req.domain_vertical,
            plan_tier=req.plan_tier,
            monthly_quota_chapters=req.monthly_quota_chapters,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SaaS 라이선스 패키지 생성 오류: {exc}")


class RevenueSimRequest(BaseModel):
    pod_monthly_copies: int = 80
    pod_unit_royalty: int = 8500
    b2g_quarterly_contracts: int = 2
    b2g_contract_value: int = 4500000
    academy_subscribers: int = 60
    academy_monthly_fee: int = 29000
    saas_tenants: int = 15
    saas_monthly_fee: int = 49000


@app.post("/api/monetization/simulate")
def api_monetization_simulate(req: RevenueSimRequest) -> dict[str, Any]:
    return simulate_monetization_revenue(**req.model_dump())


# ============================================================
# 독립형 이미지 생성 스튜디오 (비용 제어 · 분할 배치 · 직접 업로드 · 결합)
# ============================================================
@app.get("/api/projects/{project_id}/image-studio")
def api_image_studio_state(project_id: str) -> dict[str, Any]:
    try:
        return get_studio_state(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"이미지 스튜디오 상태 조회 오류: {exc}")


class StudioPlanRequest(BaseModel):
    per_chapter_count: int = Field(default=6, ge=0, le=25)
    type_counts: dict[str, int] | None = None
    chapter_ids: list[str] | None = None
    keep_existing: bool = True


@app.post("/api/projects/{project_id}/image-studio/plan")
def api_image_studio_plan(project_id: str, req: StudioPlanRequest) -> dict[str, Any]:
    try:
        return plan_visual_queue(
            project_id=project_id,
            per_chapter_count=req.per_chapter_count,
            type_counts=req.type_counts,
            chapter_ids=req.chapter_ids,
            keep_existing=req.keep_existing,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"시각화 기획 생성 오류: {exc}")


class StudioGenerateRequest(BaseModel):
    engine: str = "auto_hybrid"  # auto_hybrid | free_local_only | nano_banana | fal_ai
    fal_model: str = "fal-ai/nano-banana-pro"
    figure_ids: list[str] | None = None
    chapter_ids: list[str] | None = None
    visual_types: list[str] | None = None
    only_pending: bool = True
    max_batch: int = Field(default=5, ge=0, le=200)
    budget_limit_usd: float = Field(default=0.0, ge=0.0, le=500.0)


@app.post("/api/projects/{project_id}/image-studio/generate")
def api_image_studio_generate(project_id: str, req: StudioGenerateRequest) -> dict[str, Any]:
    try:
        return start_batch_generation_async(
            project_id=project_id,
            engine=req.engine,
            fal_model=req.fal_model,
            figure_ids=req.figure_ids,
            chapter_ids=req.chapter_ids,
            visual_types=req.visual_types,
            only_pending=req.only_pending,
            max_batch=req.max_batch,
            budget_limit_usd=req.budget_limit_usd,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"이미지 분할 생성 시작 오류: {exc}")


@app.post("/api/projects/{project_id}/image-studio/stop")
def api_image_studio_stop(project_id: str) -> dict[str, Any]:
    return stop_batch_generation(project_id)


class StudioUpdateItemRequest(BaseModel):
    title_ko: str | None = None
    narrative_ko: str | None = None
    prompt: str | None = None
    target_section: str | None = None
    type: str | None = None
    status: str | None = None


@app.patch("/api/projects/{project_id}/image-studio/items/{figure_id}")
def api_image_studio_update_item(project_id: str, figure_id: str, req: StudioUpdateItemRequest) -> dict[str, Any]:
    try:
        return update_queue_item(
            project_id=project_id,
            figure_id=figure_id,
            updates=req.model_dump(exclude_none=True),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Figure not found")


class StudioUploadImageRequest(BaseModel):
    image_base64: str
    filename: str = "custom.png"


@app.post("/api/projects/{project_id}/image-studio/items/{figure_id}/upload")
def api_image_studio_upload(project_id: str, figure_id: str, req: StudioUploadImageRequest) -> dict[str, Any]:
    if not req.image_base64.strip():
        raise HTTPException(status_code=400, detail="업로드할 이미지 데이터가 비어 있습니다.")
    try:
        return upload_custom_image(
            project_id=project_id,
            figure_id=figure_id,
            image_base64=req.image_base64,
            original_filename=req.filename,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Figure not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"이미지 업로드 처리 오류: {exc}")


@app.post("/api/projects/{project_id}/image-studio/sync")
def api_image_studio_sync(project_id: str) -> dict[str, Any]:
    try:
        return sync_studio_to_pipeline(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"원고·출판물 결합 동기화 오류: {exc}")


# ============================================================
# 기본 2종 출판(PDF + 블로그 단일 HTML) 및 사후 포맷 변환 모듈 API
# ============================================================
@app.get("/api/output-converter/formats")
def api_output_converter_formats() -> dict[str, Any]:
    return {
        "formats": CONVERSION_FORMATS,
        "korean_journal_pdf_spec": KOREAN_JOURNAL_PDF_SPEC,
    }


@app.get("/api/projects/{project_id}/outputs-summary")
def api_project_outputs_summary(project_id: str) -> dict[str, Any]:
    try:
        return list_project_outputs_summary(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.post("/api/projects/{project_id}/publish-default")
def api_publish_default_outputs(project_id: str, force: bool = False) -> dict[str, Any]:
    try:
        return publish_default_outputs(project_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"기본 2종 출판 오류: {exc}")


# ---------- C2: 핵심 문헌(앵커 PDF/문서) 업로드 · 목록 · 삭제 ----------
class AnchorUploadRequest(BaseModel):
    filename: str
    file_base64: str
    title: str = ""
    citation: str = ""
    license_note: str = "연구자 지정 핵심 앵커 문헌(표준 교과서·매뉴얼·논문) - 최우선 근거"


@app.get("/api/projects/{project_id}/anchors")
def api_list_anchors(project_id: str) -> dict[str, Any]:
    st = load_project_state(project_id)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"anchors": st.get("anchor_sources") or []}


@app.post("/api/projects/{project_id}/anchors/upload")
def api_upload_anchor(project_id: str, req: AnchorUploadRequest) -> dict[str, Any]:
    import base64
    from parse_pdf import parse_document

    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    if not req.file_base64.strip():
        raise HTTPException(status_code=400, detail="업로드할 파일 데이터가 비어 있습니다.")

    raw_b64 = req.file_base64.split(",", 1)[-1]
    try:
        raw_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Base64 디코딩 실패: {exc}")

    safe_name = re.sub(r"[^0-9A-Za-z가-힣._\-]", "_", Path(req.filename or "anchor.pdf").name)
    anchor_dir = cfg.project_collected_dir(project_id) / "00_anchor_literature"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    saved_file = anchor_dir / safe_name
    saved_file.write_bytes(raw_bytes)

    parsed = parse_document(
        file_path=saved_file,
        packet_id=st["packet_id"],
        topic=st.get("topic_ko", project_id),
        license_note=req.license_note,
        use_docling=False,
        extract_facts=False,
        force=True,
        is_anchor=True,
        anchor_citation=req.citation,
        title_override=req.title or saved_file.stem,
        project_id=project_id,
        cfg=cfg,
    )
    anchor_rec = {
        "source_id": parsed["source_id"],
        "title": parsed["title"],
        "citation": req.citation.strip(),
        "filename": safe_name,
        "page_count": parsed.get("page_count", 1),
        "chunk_count": parsed.get("chunk_count", 0),
        "is_anchor": True,
        "relevance_score": 1.0,
        "provider": "핵심 앵커 문헌 (연구자 업로드)",
        "tier_folder": "00_anchor_literature",
        "url": saved_file.as_uri(),
    }
    anchors = list(st.get("anchor_sources") or [])
    anchors.append(anchor_rec)
    st["anchor_sources"] = anchors
    col = list(st.get("collected_sources") or [])
    col.insert(0, anchor_rec)
    st["collected_sources"] = col
    save_project_state(st, cfg)
    return {"status": "OK", "anchor": anchor_rec, "anchors": anchors}


@app.delete("/api/projects/{project_id}/anchors/{source_id}")
def api_delete_anchor(project_id: str, source_id: str) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    st["anchor_sources"] = [a for a in (st.get("anchor_sources") or []) if a.get("source_id") != source_id]
    save_project_state(st, cfg)
    return {"status": "DELETED", "source_id": source_id, "anchors": st["anchor_sources"]}


# ---------- C9: 단원별 전문가 [검토 완료] 토글 & 6단계 출판 가능성 품질 게이트 ----------
class ChapterReviewRequest(BaseModel):
    reviewed: bool = True
    reviewer: str = "연구자"
    note: str = ""


@app.post("/api/projects/{project_id}/chapters/{chapter_id}/review")
def api_set_chapter_review(project_id: str, chapter_id: str, req: ChapterReviewRequest) -> dict[str, Any]:
    try:
        res = set_chapter_expert_review(
            project_id,
            chapter_id,
            req.reviewed,
            reviewer=req.reviewer,
            note=req.note,
        )
        res["publish_readiness"] = evaluate_publish_readiness(project_id)
        return res
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/api/projects/{project_id}/publish-readiness")
def api_publish_readiness(project_id: str) -> dict[str, Any]:
    try:
        return evaluate_publish_readiness(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


@app.get("/api/projects/{project_id}/visuals/qa")
def api_visuals_qa(project_id: str, chapter_id: str | None = None) -> dict[str, Any]:
    from visual_studio import audit_visual_assets

    try:
        return audit_visual_assets(project_id, chapter_id=chapter_id or None)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


class ConvertOutputRequest(BaseModel):
    target_format: str


@app.post("/api/projects/{project_id}/convert-output")
def api_convert_project_output(project_id: str, req: ConvertOutputRequest) -> dict[str, Any]:
    try:
        return convert_project_output(project_id, req.target_format)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"포맷 변환 오류: {exc}")


# ============================================================
# 출판물별 저자 페르소나 · 심층 집필 시나리오 프롬프트 스튜디오 API
# ============================================================
@app.get("/api/personas")
def api_list_personas(output_type: str | None = None) -> dict[str, Any]:
    return {
        "personas": list_personas(output_type=output_type),
        "defaults_by_type": DEFAULT_PERSONA_BY_TYPE,
    }


class CustomPersonaRequest(BaseModel):
    persona_id: str = ""
    output_type: str = "textbook"
    name_ko: str
    badge: str = "사용자 커스텀"
    role_title: str = ""
    identity_and_credentials: str = ""
    writing_scenario: str = ""
    reasoning_protocol: str = ""
    depth_and_evidence_rules: str = ""
    banned_cliches: list[str] | str = Field(default_factory=list)
    voice_and_style: str = ""
    section_depth_mode: str = "deep_per_section"
    min_chars_per_subsection: int = 1500
    auto_deepen_short_sections: bool = True
    custom_instructions: str = ""


@app.post("/api/personas/custom")
def api_save_custom_persona(req: CustomPersonaRequest) -> dict[str, Any]:
    try:
        saved = save_custom_persona(req.model_dump())
        return {"status": "SAVED", "persona": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/personas/custom/{persona_id}")
def api_delete_custom_persona(persona_id: str) -> dict[str, Any]:
    try:
        return delete_custom_persona(persona_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class PreviewPersonaPromptRequest(BaseModel):
    output_type: str = "paper"
    persona: dict[str, Any] = Field(default_factory=dict)
    output_profile: dict[str, Any] = Field(default_factory=dict)
    topic_ko: str = "스마트 농업 정밀 연구"
    chapter_role: str | None = None
    subsection_title: str | None = "3.1 핵심 정량 결과 및 기작 분석"


@app.post("/api/personas/preview-prompt")
def api_preview_persona_prompt(req: PreviewPersonaPromptRequest) -> dict[str, Any]:
    state_mock = {
        "topic_ko": req.topic_ko,
        "primary_output_type": req.output_type,
        "output_profile": resolve_output_profile(req.output_type, req.output_profile),
        "persona": req.persona,
    }
    role_eff = req.chapter_role or ("results_discussion" if req.output_type == "paper" else None)
    compiled = compile_persona_system_prompt(
        state_mock,
        ["SRC-01", "SRC-02", "SRC-03"],
        chapter_role=role_eff,
        subsection_title=req.subsection_title,
    )
    return {
        "prompt": compiled,
        "length": len(compiled),
        "persona": resolve_project_persona(req.output_type, req.persona),
    }


class UpdateProjectPersonaRequest(BaseModel):
    persona: dict[str, Any] = Field(default_factory=dict)
    reset_stage4_checkpoint: bool = False
    auto_restart_stage4: bool = False


@app.patch("/api/projects/{project_id}/persona")
def api_update_project_persona(project_id: str, req: UpdateProjectPersonaRequest) -> dict[str, Any]:
    cfg = get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise HTTPException(status_code=404, detail="Project not found")
    otype = st.get("primary_output_type") or (st.get("output_profile") or {}).get("primary_output_type") or "textbook"
    resolved = resolve_project_persona(otype, req.persona, cfg=cfg)
    st["persona"] = resolved
    if req.reset_stage4_checkpoint:
        st.setdefault("checkpoint", {})["completed_chapters"] = []
        st["checkpoint"]["fallback_chapters"] = []
    save_project_state(st, cfg)
    run_info = None
    if req.auto_restart_stage4:
        run_info = start_pipeline_async(project_id, mode="single", target_stage="stage4_manuscript_draft")
    return {"status": "UPDATED", "persona": resolved, "project": st, "run": run_info}


# ============================================================
# 단원별 순차 심층 검색 · KG · 절별 집필 · 실시간 현황판 API
# ============================================================
@app.get("/api/projects/{project_id}/chapter-pipeline")
def api_get_chapter_pipeline_board(project_id: str) -> dict[str, Any]:
    try:
        return get_chapter_pipeline_board(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


class ChapterPipelineStartRequest(BaseModel):
    chapter_ids: list[str] | None = None
    research_depth: str = "deep"  # standard | deep | exhaustive
    force_rerun: bool = False
    auto_continue_stages56: bool = False


@app.post("/api/projects/{project_id}/chapter-pipeline/start")
def api_start_chapter_pipeline(project_id: str, req: ChapterPipelineStartRequest) -> dict[str, Any]:
    try:
        return start_chapter_pipeline_async(
            project_id,
            chapter_ids=req.chapter_ids,
            research_depth=req.research_depth,
            force_rerun=req.force_rerun,
            auto_continue_stages56=req.auto_continue_stages56,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"단원별 파이프라인 실행 오류: {exc}")


@app.post("/api/projects/{project_id}/chapter-pipeline/stop")
def api_stop_chapter_pipeline(project_id: str) -> dict[str, Any]:
    return stop_chapter_pipeline(project_id)
