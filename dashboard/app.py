"""자료 수집 정리·큐레이션·지식그래프·인용검증 통합 대시보드 서버 (FastAPI).

실행:
    .venv\\Scripts\\python.exe -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8500
또는:
    .\\scripts\\start_dashboard.ps1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from compliance import SourcesRegistry, utc_now_iso  # noqa: E402
from config import get_config  # noqa: E402
from fetch_clean import fetch_and_clean_url  # noqa: E402
from fetch_scholar import (  # noqa: E402
    KOREAN_SOCIETY_JOURNALS,
    ingest_paper_record,
    parse_bibtex_entries,
    search_crossref_korean_society,
    search_openalex_papers,
)
from local_gemma import LocalGemmaClient  # noqa: E402
from notebooklm_connector import (  # noqa: E402
    import_notebooklm_sources,
    list_notebook_sources,
    list_notebooks,
)
from parse_pdf import parse_document  # noqa: E402
from smc_kg_bridge import ingest_text_to_kg, show_status  # noqa: E402
from subagent_orchestrator import (  # noqa: E402
    append_event,
    ensure_seed_soil_project,
    list_projects,
    load_project_state,
    save_project_state,
)


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _dump_clean_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False, width=140)

app = FastAPI(title="전문 교재 제작 · 자료 수집·큐레이션·지식그래프 통합 대시보드", version="2.1.0")

STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


# ---------- 활성 프로젝트 선택 상태 관리 (8500 · 8501 · /explorer 공용) ----------
def _active_project_file() -> Path:
    cfg = get_config()
    return cfg.index_dir / "active_project.json"


def _get_saved_active_project_id() -> str:
    p = _active_project_file()
    if p.is_file():
        try:
            pid = json.loads(p.read_text(encoding="utf-8")).get("project_id", "")
            if pid and load_project_state(pid):
                return pid
        except Exception:
            pass
    projs = list_projects()
    return projs[0]["project_id"] if projs else "soil_organic_matter_500p"


def _save_active_project_id(project_id: str) -> None:
    p = _active_project_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"project_id": project_id, "updated_at": utc_now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_project_ctx(project: str | None = None) -> tuple[dict[str, Any], Any]:
    """요청된 project_id (또는 마지막 선택 프로젝트)에 대한 state와 PlatformConfig를 반환한다."""
    ensure_seed_soil_project()
    pid = (project or "").strip() or _get_saved_active_project_id()
    st = load_project_state(pid)
    if not st:
        # workspace slug(예: soil_organic_matter)로 들어온 경우 매칭 시도
        for pinfo in list_projects():
            cand = load_project_state(pinfo["project_id"])
            if cand and Path(cand.get("workspace_dir", "")).name == pid:
                st = cand
                pid = pinfo["project_id"]
                break
    if not st:
        st = ensure_seed_soil_project()
        pid = st["project_id"]
    ws_slug = Path(st.get("workspace_dir", "")).name or ("soil_organic_matter" if st.get("is_reference_book") else pid)
    cfg = get_config(active_project=ws_slug)
    return st, cfg


# ---------- 큐레이션 상태 저장소 (E:\SMC_Report_Platform_Data\index\curation_state.json) ----------
def _curation_path() -> Path:
    cfg = get_config()
    return cfg.index_dir / "curation_state.json"


def _load_curation() -> dict[str, dict[str, Any]]:
    p = _curation_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_curation(state: dict[str, dict[str, Any]]) -> None:
    p = _curation_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _infer_category(rec: dict[str, Any], ev_src: dict[str, Any] | None = None) -> str:
    sc = rec.get("scholar_category")
    if sc:
        return sc
    stype = rec.get("source_type") or (ev_src or {}).get("source_type") or "web"
    if stype == "kg_reuse":
        return "kg_reuse"
    url = (rec.get("url") or "").lower()
    if "maff.go.jp" in url or "naro.go.jp" in url or "jssspn.jp" in url:
        return "japan_source"
    if "cornell.edu" in url or "usda.gov" in url:
        return "usa_source"
    if "rothamsted.ac.uk" in url or "europa.eu" in url or "4p1000.org" in url or "ejpsoil.eu" in url:
        return "europe_source"
    if "nongsaro.go.kr" in url or "rda.go.kr" in url:
        return "rda_nongsaro"
    if "sare.org" in url or "libretexts.org" in url or "kocw.net" in url:
        return "textbook"
    if "fao.org" in url:
        return "official_agency"
    if "nature.com" in url or "wiley.com" in url or "doi.org" in url or "sciencedirect" in url:
        return "international_journal"
    if stype == "pdf":
        return "pdf_document"
    return "web_article"


def _infer_tier(cat: str) -> str:
    return {
        "cn_model": "질소·탄소 모델 핵심논문",
        "textbook": "표준 교재·교과서",
        "rda_nongsaro": "농진청·농사로",
        "japan_source": "일본 기관·학회",
        "usa_source": "미국 기관·학회",
        "europe_source": "유럽 기관·학회",
        "official_agency": "1차 공식기관",
        "international_journal": "국제 SCI 저널",
        "korean_society": "국내 학회지",
        "google_scholar_bibtex": "구글 스칼라(BibTeX)",
        "korean_society_bibtex": "국내 학회(BibTeX)",
        "kg_reuse": "기존 C:\\SMC_GRAPHRAG",
        "notebooklm_import": "NotebookLM 수집자료",
        "pdf_document": "전문 PDF 문서",
        "web_article": "공개 웹 자료",
    }.get(cat, "일반 자료")


def _load_all_evidence_sources() -> dict[str, tuple[str, dict[str, Any]]]:
    """source_id -> (packet_id, source_item) 매핑."""
    cfg = get_config()
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    if not cfg.evidence_dir.is_dir():
        return out
    for p in sorted(cfg.evidence_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            pid = data.get("packet_id") or p.stem
            for src in data.get("sources", []):
                sid = src.get("source_id")
                if sid:
                    out[sid] = (pid, src)
        except Exception:
            continue
    return out


def _collect_unified_sources() -> list[dict[str, Any]]:
    cfg = get_config()
    reg = SourcesRegistry(cfg.sources_registry_path)
    ev_map = _load_all_evidence_sources()
    curation = _load_curation()

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for rec in reg.records:
        sid = rec.get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        pid, ev_src = ev_map.get(sid, ("", None))
        cur = curation.get(sid, {})
        cat = cur.get("category") or _infer_category(rec, ev_src)
        default_chapter = pid.replace("_evidence", "") if pid.endswith("_evidence") else (pid or "ch01")
        rows.append(
            {
                "source_id": sid,
                "title": cur.get("custom_title") or rec.get("title") or (ev_src or {}).get("title", ""),
                "source_type": rec.get("source_type") or (ev_src or {}).get("source_type", "web"),
                "category": cat,
                "tier": cur.get("tier") or _infer_tier(cat),
                "authors": rec.get("authors", ""),
                "year": rec.get("year"),
                "journal": rec.get("journal", ""),
                "doi": rec.get("doi", ""),
                "cited_by_count": rec.get("cited_by_count", 0),
                "is_oa": rec.get("is_oa", False),
                "provider": rec.get("provider") or rec.get("parser_engine", ""),
                "url": rec.get("url") or (ev_src or {}).get("url", ""),
                "accessed_at": rec.get("accessed_at") or (ev_src or {}).get("accessed_at", ""),
                "robots_allowed": rec.get("robots_allowed", True),
                "robots_status": rec.get("robots_status", ""),
                "license_note": (ev_src or {}).get("license_note", ""),
                "packet_id": pid or Path(rec.get("packet_path", "ch01_evidence.json")).stem,
                "raw_path": rec.get("raw_path") or (ev_src or {}).get("raw_path", ""),
                "parsed_path": rec.get("parsed_path") or (ev_src or {}).get("parsed_path", ""),
                "chunk_count": len((ev_src or {}).get("chunks", [])) if ev_src else rec.get("chunk_count", 0),
                "table_count": len((ev_src or {}).get("tables", [])) if ev_src else rec.get("table_count", 0),
                "fact_count": len((ev_src or {}).get("extracted_facts", [])) if ev_src else rec.get("fact_count", 0),
                "pii_redaction_count": (ev_src or {}).get("pii_redaction_count", 0),
                "prompt_injection_warnings": (ev_src or {}).get("prompt_injection_warnings", []),
                # 사용자 큐레이션 필드
                "status": cur.get("status", "approved"),  # approved | review | hold | rejected
                "chapters": cur.get("chapters") or [default_chapter],
                "tags": cur.get("tags") or [],
                "notes": cur.get("notes", ""),
                "rating": cur.get("rating", 4),
                "kg_ingested": bool(cur.get("kg_ingested", cat == "kg_reuse")),
                "updated_at": cur.get("updated_at", ""),
            }
        )

    # sources.jsonl에 누락되었으나 evidence에 존재하는 항목 보완
    for sid, (pid, ev_src) in ev_map.items():
        if sid in seen:
            continue
        cur = curation.get(sid, {})
        cat = cur.get("category") or _infer_category(ev_src, ev_src)
        rows.append(
            {
                "source_id": sid,
                "title": cur.get("custom_title") or ev_src.get("title", ""),
                "source_type": ev_src.get("source_type", "web"),
                "category": cat,
                "tier": cur.get("tier") or _infer_tier(cat),
                "authors": "",
                "year": None,
                "journal": "",
                "doi": "",
                "cited_by_count": 0,
                "is_oa": False,
                "provider": "evidence_packet",
                "url": ev_src.get("url", ""),
                "accessed_at": ev_src.get("accessed_at", ""),
                "robots_allowed": ev_src.get("robots_allowed", True),
                "robots_status": ev_src.get("robots_status", ""),
                "license_note": ev_src.get("license_note", ""),
                "packet_id": pid,
                "raw_path": ev_src.get("raw_path", ""),
                "parsed_path": ev_src.get("parsed_path", ""),
                "chunk_count": len(ev_src.get("chunks", [])),
                "table_count": len(ev_src.get("tables", [])),
                "fact_count": len(ev_src.get("extracted_facts", [])),
                "pii_redaction_count": ev_src.get("pii_redaction_count", 0),
                "prompt_injection_warnings": ev_src.get("prompt_injection_warnings", []),
                "status": cur.get("status", "approved"),
                "chapters": cur.get("chapters") or [pid.replace("_evidence", "")],
                "tags": cur.get("tags") or [],
                "notes": cur.get("notes", ""),
                "rating": cur.get("rating", 4),
                "kg_ingested": bool(cur.get("kg_ingested", cat == "kg_reuse")),
                "updated_at": cur.get("updated_at", ""),
            }
        )

    return rows


# ---------- Request Models ----------
class CurationPatch(BaseModel):
    status: str | None = None
    chapters: list[str] | None = None
    tags: list[str] | None = None
    notes: str | None = None
    tier: str | None = None
    category: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    custom_title: str | None = None


class ScholarSearchRequest(BaseModel):
    query: str
    scope: str = "all"  # all | korean_societies | crossref_ksssf | korea_all | open_access
    limit: int = 8
    year_from: int | None = None
    sort: str = "cited_by_count:desc"


class ScholarIngestRequest(BaseModel):
    paper: dict[str, Any]
    packet_id: str = "ch01_evidence"
    topic: str = "토양 유기물"
    download_oa_pdf: bool = False
    chapters: list[str] = Field(default_factory=lambda: ["ch01"])
    notes: str = ""


class BibtexImportRequest(BaseModel):
    bibtex_text: str
    packet_id: str = "ch01_evidence"
    topic: str = "토양 유기물"
    chapters: list[str] = Field(default_factory=lambda: ["ch01"])


class UrlCollectRequest(BaseModel):
    url: str
    packet_id: str = "ch01_evidence"
    topic: str = "토양 유기물"
    license_note: str = "공개 웹 자료 - 변환적 분석 및 인용 목적(원본 미재게시)"
    extract_facts: bool = False


class LocalFileCollectRequest(BaseModel):
    file_path: str
    packet_id: str = "ch01_evidence"
    topic: str = "토양 유기물"
    license_note: str = "로컬 확보 문서 - 변환적 분석 및 인용 목적"


class NlmImportMainRequest(BaseModel):
    project_id: str = ""
    notebook_id: str
    notebook_title: str = ""
    source_ids: list[str]
    also_ingest_rag: bool = True
    chapters: list[str] = Field(default_factory=lambda: ["ch01"])


class ActiveProjectRequest(BaseModel):
    project_id: str


# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not STATIC_INDEX.is_file():
        return HTMLResponse("<h1>Dashboard index.html missing</h1>", status_code=500)
    return HTMLResponse(STATIC_INDEX.read_text(encoding="utf-8"))


@app.get("/api/projects")
def api_projects() -> dict[str, Any]:
    return {"projects": list_projects(), "active_project_id": _get_saved_active_project_id()}


@app.post("/api/active-project")
def api_set_active_project(req: ActiveProjectRequest) -> dict[str, Any]:
    st = load_project_state(req.project_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found")
    _save_active_project_id(req.project_id)
    return {"status": "OK", "project_id": req.project_id, "topic_ko": st.get("topic_ko", "")}


def _project_source_ids(st: dict[str, Any]) -> set[str]:
    if st.get("is_reference_book"):
        return set()  # 기준 도서는 레거시 ch01~ch16 패킷으로 필터링
    sids = {s.get("source_id") for s in (st.get("collected_sources") or []) if s.get("source_id")}
    pkt_id = st.get("packet_id", "")
    if pkt_id:
        cfg = get_config()
        pkt_f = cfg.evidence_dir / f"{pkt_id}.json"
        if pkt_f.is_file():
            try:
                for src in json.loads(pkt_f.read_text(encoding="utf-8")).get("sources", []):
                    if src.get("source_id"):
                        sids.add(src["source_id"])
            except Exception:
                pass
    return sids


def _filter_sources_for_project(rows: list[dict[str, Any]], st: dict[str, Any]) -> list[dict[str, Any]]:
    if st.get("is_reference_book"):
        # 토양 유기물학 기준 프로젝트: ch01~ch16 패킷 또는 SRC-01~SRC-94 범위
        out = []
        for r in rows:
            pkt = str(r.get("packet_id", ""))
            sid = str(r.get("source_id", ""))
            if pkt.startswith("ch") or pkt == "soil_organic_matter_evidence":
                out.append(r)
            elif sid.startswith("SRC-") and sid[4:].isdigit() and int(sid[4:]) <= 94:
                out.append(r)
        return out
    sids = _project_source_ids(st)
    pkt_id = st.get("packet_id", "")
    return [r for r in rows if r.get("source_id") in sids or (pkt_id and r.get("packet_id") == pkt_id)]


@app.get("/api/overview")
def api_overview(project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    if project.strip():
        _save_active_project_id(st["project_id"])
    all_sources = _collect_unified_sources()
    proj_sources = _filter_sources_for_project(all_sources, st)

    by_category: dict[str, int] = {}
    by_status: dict[str, int] = {"approved": 0, "review": 0, "hold": 0, "rejected": 0}
    for s in proj_sources:
        by_category[s["category"]] = by_category.get(s["category"], 0) + 1
        stt = s.get("status", "approved")
        by_status[stt] = by_status.get(stt, 0) + 1

    gap_report = None
    for gap_cand in (cfg.active_project_dir / "reports" / "kg_gap_report.json", cfg.reports_dir / "kg_gap_report.json"):
        if gap_cand.is_file():
            try:
                gap_report = json.loads(gap_cand.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    audit_ch01 = None
    for aud_cand in (
        cfg.active_project_dir / "reports" / "audit_latest.json",
        cfg.active_project_dir / "reports" / "audit_ch01.json",
        cfg.reports_dir / "audit_ch01.json" if st.get("is_reference_book") else Path("__nonexistent__"),
    ):
        if aud_cand.is_file():
            try:
                audit_ch01 = json.loads(aud_cand.read_text(encoding="utf-8"))
                break
            except Exception:
                pass

    ollama_info: dict[str, Any] = {"online": False}
    try:
        ollama_info = {"online": True, **LocalGemmaClient(cfg).check_health()}
    except Exception as exc:
        ollama_info = {"online": False, "error": str(exc)}

    kg_status = show_status(cfg)
    catalog_summary = {"total_nodes": 0, "total_edges": 0, "graph_files": 0}
    if cfg.smc_catalog_db_path.is_file():
        import sqlite3

        conn = sqlite3.connect(str(cfg.smc_catalog_db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(node_count),0), COALESCE(SUM(edge_count),0) FROM graph_files"
            ).fetchone()
            catalog_summary = {"graph_files": row[0], "total_nodes": row[1], "total_edges": row[2]}
        finally:
            conn.close()

    return {
        "active_project": {
            "project_id": st["project_id"],
            "workspace_slug": cfg.active_project,
            "topic_ko": st.get("topic_ko", ""),
            "topic_en": st.get("topic_en", ""),
            "target_pages": st.get("target_pages", 500),
            "chapter_count": st.get("chapter_count", 12),
            "keywords_ko": st.get("keywords_ko", []),
            "keywords_en": st.get("keywords_en", []),
            "packet_id": st.get("packet_id", f"{st['project_id']}_evidence"),
            "overall_status": st.get("overall_status", "IDLE"),
            "is_reference_book": bool(st.get("is_reference_book", False)),
            "workspace_dir": str(cfg.active_project_dir),
            "collected_dir": st.get("collected_dir") or str(cfg.project_collected_dir(st["project_id"])),
        },
        "projects": list_projects(),
        "storage_root": str(cfg.collected_data_root),
        "kg_root": str(cfg.smc_graphrag_root),
        "lightrag_webui": f"{cfg.lightrag_api_url}/webui",
        "total_sources": len(proj_sources),
        "global_total_sources": len(all_sources),
        "by_category": by_category,
        "by_status": by_status,
        "korean_society_journals": KOREAN_SOCIETY_JOURNALS,
        "catalog_summary": catalog_summary,
        "kg_gap_reuse_percent": (gap_report or {}).get("reuse_ratio_percent"),
        "kg_gaps": (gap_report or {}).get("missing_or_outdated_gaps", []),
        "kg_status": kg_status,
        "ollama": ollama_info,
        "audit_ch01_status": (audit_ch01 or {}).get("status", "PENDING"),
    }


@app.get("/api/sources")
def api_sources(
    q: str = Query(default=""),
    category: str = Query(default="all"),
    status: str = Query(default="all"),
    chapter: str = Query(default="all"),
    project: str = Query(default=""),
    scope: str = Query(default="project"),  # project | all
) -> dict[str, Any]:
    rows = _collect_unified_sources()
    if scope != "all":
        st, _ = _resolve_project_ctx(project)
        rows = _filter_sources_for_project(rows, st)
    ql = q.strip().lower()
    filtered = []
    for r in rows:
        if category != "all" and r.get("category") != category:
            continue
        if status != "all" and r.get("status") != status:
            continue
        if chapter != "all" and chapter not in (r.get("chapters") or []):
            continue
        if ql:
            hay = " ".join(
                [
                    str(r.get("source_id", "")),
                    str(r.get("title", "")),
                    str(r.get("authors", "")),
                    str(r.get("journal", "")),
                    str(r.get("notes", "")),
                    " ".join(r.get("tags") or []),
                ]
            ).lower()
            if ql not in hay:
                continue
        filtered.append(r)
    return {"total": len(filtered), "sources": filtered}


@app.get("/api/sources/{source_id}")
def api_source_detail(source_id: str) -> dict[str, Any]:
    rows = {r["source_id"]: r for r in _collect_unified_sources()}
    if source_id not in rows:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    row = dict(rows[source_id])
    ev_map = _load_all_evidence_sources()
    _, ev_src = ev_map.get(source_id, ("", {}))

    parsed_preview = ""
    pp = row.get("parsed_path")
    if pp and Path(pp).is_file():
        parsed_preview = Path(pp).read_text(encoding="utf-8", errors="ignore")[:8000]

    row["extracted_facts"] = (ev_src or {}).get("extracted_facts", [])[:40]
    row["tables"] = (ev_src or {}).get("tables", [])[:10]
    row["chunks_preview"] = (ev_src or {}).get("chunks", [])[:8]
    row["parsed_preview"] = parsed_preview
    return row


@app.patch("/api/sources/{source_id}")
def api_patch_source(source_id: str, patch: CurationPatch) -> dict[str, Any]:
    state = _load_curation()
    entry = state.get(source_id, {})
    for field in ("status", "chapters", "tags", "notes", "tier", "category", "rating", "custom_title"):
        val = getattr(patch, field)
        if val is not None:
            entry[field] = val
    entry["updated_at"] = utc_now_iso()
    state[source_id] = entry
    _save_curation(state)
    return {"status": "OK", "source_id": source_id, "curation": entry}


@app.post("/api/collect/scholar/search")
def api_scholar_search(req: ScholarSearchRequest) -> dict[str, Any]:
    try:
        if req.scope == "crossref_ksssf":
            papers = search_crossref_korean_society(req.query, limit=req.limit)
        else:
            papers = search_openalex_papers(
                query=req.query,
                limit=req.limit,
                scope=req.scope,
                year_from=req.year_from,
                sort=req.sort,
            )
        return {"status": "OK", "count": len(papers), "papers": papers}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"학술 검색 오류: {exc}")


@app.post("/api/collect/scholar/ingest")
def api_scholar_ingest(req: ScholarIngestRequest) -> dict[str, Any]:
    try:
        res = ingest_paper_record(
            paper=req.paper,
            packet_id=req.packet_id,
            topic=req.topic,
            download_oa_pdf=req.download_oa_pdf,
        )
        if res.get("status") == "OK":
            sid = res["source_id"]
            state = _load_curation()
            state[sid] = {
                "status": "approved",
                "chapters": req.chapters or ["ch01"],
                "tags": [req.paper.get("journal", ""), str(req.paper.get("year", ""))],
                "notes": req.notes,
                "rating": 5 if (req.paper.get("cited_by_count") or 0) >= 100 else 4,
                "updated_at": utc_now_iso(),
            }
            _save_curation(state)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"논문 수집 오류: {exc}")


@app.post("/api/collect/bibtex")
def api_collect_bibtex(req: BibtexImportRequest) -> dict[str, Any]:
    papers = parse_bibtex_entries(req.bibtex_text)
    if not papers:
        raise HTTPException(status_code=400, detail="유효한 BibTeX 항목(@article{...} 등)을 찾지 못했습니다.")
    results = []
    state = _load_curation()
    for p in papers:
        r = ingest_paper_record(paper=p, packet_id=req.packet_id, topic=req.topic)
        if r.get("status") == "OK":
            state[r["source_id"]] = {
                "status": "approved",
                "chapters": req.chapters or ["ch01"],
                "tags": ["GoogleScholar", "BibTeX"],
                "notes": "Google Scholar / 학술 DB BibTeX 일괄 가져오기",
                "rating": 4,
                "updated_at": utc_now_iso(),
            }
        results.append(r)
    _save_curation(state)
    return {"status": "OK", "parsed": len(papers), "results": results}


@app.post("/api/collect/url")
def api_collect_url(req: UrlCollectRequest) -> dict[str, Any]:
    try:
        res = fetch_and_clean_url(
            url=req.url,
            packet_id=req.packet_id,
            topic=req.topic,
            license_note=req.license_note,
            use_crawl4ai=False,
            extract_facts=req.extract_facts,
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"웹 수집 오류: {exc}")


@app.post("/api/collect/file")
def api_collect_file(req: LocalFileCollectRequest) -> dict[str, Any]:
    try:
        res = parse_document(
            file_path=Path(req.file_path),
            packet_id=req.packet_id,
            topic=req.topic,
            license_note=req.license_note,
            use_docling=False,
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"파일 파싱 오류: {exc}")


@app.get("/api/notebooklm/notebooks")
def api_main_nlm_notebooks(q: str = Query(default="")) -> dict[str, Any]:
    try:
        nbs = list_notebooks(query=q)
        return {"status": "OK", "count": len(nbs), "notebooks": nbs}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 목록 조회 오류: {exc}")


@app.get("/api/notebooklm/notebooks/{notebook_id}/sources")
def api_main_nlm_sources(notebook_id: str) -> dict[str, Any]:
    try:
        return list_notebook_sources(notebook_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 소스 조회 오류: {exc}")


@app.post("/api/notebooklm/import")
def api_main_nlm_import(req: NlmImportMainRequest) -> dict[str, Any]:
    st, _ = _resolve_project_ctx(req.project_id)
    if not req.source_ids:
        raise HTTPException(status_code=400, detail="가져올 소스를 1건 이상 선택해 주세요.")
    try:
        return import_notebooklm_sources(
            project_id=st["project_id"],
            notebook_id=req.notebook_id,
            notebook_title=req.notebook_title,
            source_ids=req.source_ids,
            also_ingest_rag=req.also_ingest_rag,
            chapters=req.chapters,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"NotebookLM 가져오기 오류: {exc}")


@app.post("/api/kg/ingest/{source_id}")
def api_kg_ingest(source_id: str) -> dict[str, Any]:
    rows = {r["source_id"]: r for r in _collect_unified_sources()}
    if source_id not in rows:
        raise HTTPException(status_code=404, detail="Source not found")
    pp = rows[source_id].get("parsed_path")
    if not pp or not Path(pp).is_file():
        raise HTTPException(status_code=400, detail="정제된 마크다운 파일이 없습니다.")
    res = ingest_text_to_kg(file_path=Path(pp), source_id=source_id, also_legacy_graph=False)
    if (res.get("lightrag_ingest") or {}).get("mode") == "server_api":
        state = _load_curation()
        entry = state.get(source_id, {})
        entry["kg_ingested"] = True
        entry["updated_at"] = utc_now_iso()
        state[source_id] = entry
        _save_curation(state)
    return res


@app.get("/api/kg/platform-graph")
def api_kg_platform_graph(limit_nodes: int = Query(default=120, ge=10, le=500)) -> dict[str, Any]:
    """신규 구축된 C:\\SMC_GRAPHRAG\\output\\graph_platform_incremental.json 노드·관계를 반환한다."""
    cfg = get_config()
    inc = cfg.smc_incremental_graph_path
    if not inc.is_file():
        return {"exists": False, "nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}
    raw = json.loads(inc.read_text(encoding="utf-8"))
    nodes = raw.get("nodes", [])
    edges = raw.get("edges", raw.get("links", []))
    sorted_nodes = sorted(nodes, key=lambda n: int(n.get("mentions", 1) or 1), reverse=True)[:limit_nodes]
    keep_ids = {n.get("id") for n in sorted_nodes}
    filtered_edges = [e for e in edges if e.get("source") in keep_ids and e.get("target") in keep_ids][: limit_nodes * 3]
    return {
        "exists": True,
        "graph_path": str(inc),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": sorted_nodes,
        "edges": filtered_edges,
    }


@app.post("/api/kg/build-incremental")
def api_kg_build_incremental() -> dict[str, Any]:
    from build_platform_kg import build_knowledge_graph_from_sources

    return build_knowledge_graph_from_sources()


@app.get("/api/blueprint")
def api_blueprint(project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    bp_path = cfg.blueprints_dir / "master_outline.yaml"
    if not bp_path.is_file():
        return {
            "exists": False,
            "project_id": st["project_id"],
            "topic_ko": st.get("topic_ko", ""),
            "target_pages": st.get("target_pages", 500),
            "chapter_count": st.get("chapter_count", 12),
        }
    data = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    sources = _filter_sources_for_project(_collect_unified_sources(), st)
    ch_counts: dict[str, int] = {}
    for s in sources:
        if s.get("status") == "rejected":
            continue
        for ch in s.get("chapters") or []:
            ch_counts[ch] = ch_counts.get(ch, 0) + 1

    proj_rep_dir = cfg.active_project_dir / "reports"
    for part in data.get("parts", []):
        for ch in part.get("chapters", []):
            cid = ch["chapter_id"]
            ch["source_count"] = ch_counts.get(cid, 0)
            mdx = cfg.chapters_dir / f"{cid}.mdx"
            audit_f = proj_rep_dir / f"audit_{cid}.json"
            if not audit_f.is_file() and st.get("is_reference_book"):
                audit_f = cfg.reports_dir / f"audit_{cid}.json"
            ch["draft_exists"] = mdx.is_file()
            ch["draft_chars"] = len(mdx.read_text(encoding="utf-8")) if mdx.is_file() else 0
            if audit_f.is_file():
                try:
                    ch["audit_status"] = json.loads(audit_f.read_text(encoding="utf-8")).get("status", "UNKNOWN")
                except Exception:
                    ch["audit_status"] = "UNKNOWN"
            else:
                ch["audit_status"] = "NOT_STARTED"
            exp_dir = cfg.workspace_exports_dir / cid
            ch["exports"] = {
                "textbook_pdf": (exp_dir / f"{cid}_textbook.pdf").is_file(),
                "curriculum_pdf": (exp_dir / f"{cid}_curriculum.pdf").is_file(),
                "report_docx": (exp_dir / f"{cid}_report.docx").is_file(),
                "report_pdf": (exp_dir / f"{cid}_report.pdf").is_file(),
                "interactive_html": (exp_dir / f"{cid}_interactive.html").is_file(),
                "naver_blog_html": (exp_dir / f"{cid}_naver_blog.html").is_file(),
            }
    mb_dir = cfg.workspace_exports_dir / "master_book"
    mb_rep = (proj_rep_dir / "master_book_report.json") if (proj_rep_dir / "master_book_report.json").is_file() else (cfg.reports_dir / "master_book_report.json" if st.get("is_reference_book") else Path("__none__"))
    from figure_registry import load_chapter_visuals

    visuals_map = load_chapter_visuals(cfg)
    figures_flat: list[dict[str, Any]] = []
    for cid in sorted(visuals_map.keys()):
        for v in visuals_map[cid]:
            sub = "figures" if v["kind"] == "nano_banana" else "charts"
            figures_flat.append(
                {
                    "chapter_id": cid,
                    "kind": v["kind"],
                    "figure_id": v["figure_id"],
                    "filename": v["filename"],
                    "caption_ko": v["caption_ko"],
                    "url": f"/assets/{sub}/{v['filename']}?project={st['project_id']}",
                }
            )
    data["exists"] = True
    data["project_id"] = st["project_id"]
    data["topic_ko"] = st.get("topic_ko", "")
    data["target_pages"] = st.get("target_pages", 500)
    data["visuals"] = figures_flat
    data["active_project"] = cfg.active_project
    data["project_exports_dir"] = str(cfg.workspace_exports_dir)
    data["e_project_exports_dir"] = str(cfg.exports_dir)
    data["master_book"] = {
        "shinkuk_exists": (mb_dir / "Soil_Organic_Matter_Master_Book_Shinkuk.pdf").is_file(),
        "b5_exists": (mb_dir / "Soil_Organic_Matter_Master_Book_B5.pdf").is_file(),
        "pdf_exists": (mb_dir / "Soil_Organic_Matter_Master_Book.pdf").is_file(),
        "docx_exists": (mb_dir / "Soil_Organic_Matter_Master_Book.docx").is_file(),
        "report": json.loads(mb_rep.read_text(encoding="utf-8")) if mb_rep.is_file() else None,
    }
    return data


class BlueprintSaveRequest(BaseModel):
    book_metadata: dict[str, Any] = Field(default_factory=dict)
    parts: list[dict[str, Any]] = Field(default_factory=list)


class BlueprintYamlSaveRequest(BaseModel):
    yaml_text: str


def _persist_blueprint(st: dict[str, Any], cfg: Any, raw_data: dict[str, Any]) -> dict[str, Any]:
    """마스터 청사진(master_outline.yaml), 단원별 chNN.yaml, state.json을 백업 후 일괄 동기화 저장한다."""
    import shutil
    from datetime import datetime

    bp_dir = cfg.blueprints_dir
    bp_dir.mkdir(parents=True, exist_ok=True)
    master_path = bp_dir / "master_outline.yaml"

    if master_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = bp_dir / "_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master_path, backup_dir / f"master_outline_{stamp}.yaml")

    parts_in = raw_data.get("parts") or []
    if not isinstance(parts_in, list) or not parts_in:
        raise ValueError("최소 1개 이상의 부(Part)와 단원(Chapter)이 필요합니다.")

    default_pkt = f"{st.get('packet_id', st['project_id'] + '_evidence')}.json"
    default_sources = [s.get("source_id") for s in (st.get("collected_sources") or []) if s.get("source_id")]

    clean_parts: list[dict[str, Any]] = []
    ch_seq = 0
    total_pages = 0
    saved_ch_files: set[str] = set()

    for p_idx, part in enumerate(parts_in, 1):
        chs_in = part.get("chapters") or []
        clean_chs: list[dict[str, Any]] = []
        part_pages = 0
        for ch in chs_in:
            ch_seq += 1
            cid = str(ch.get("chapter_id") or f"ch{ch_seq:02d}").strip()
            if not cid:
                cid = f"ch{ch_seq:02d}"
            t_pages = max(1, int(ch.get("target_pages") or 30))
            raw_secs = ch.get("sections") or []
            if isinstance(raw_secs, str):
                secs = [x.strip() for x in raw_secs.splitlines() if x.strip()]
            else:
                secs = [str(x).strip() for x in raw_secs if str(x).strip()]
            assigned = list(ch.get("assigned_sources") or default_sources)
            ch_obj = {
                "chapter_id": cid,
                "chapter_number": ch_seq,
                "title": str(ch.get("title") or f"제{ch_seq}장").strip(),
                "target_pages": t_pages,
                "sections": secs or [f"{ch_seq}.1 개요", f"{ch_seq}.2 핵심 원리", f"{ch_seq}.3 현장 적용"],
                "evidence_packet": str(ch.get("evidence_packet") or default_pkt),
                "assigned_sources": assigned,
            }
            # 기존 추가 필드(learning_objectives 등) 보존
            for extra_k in ("learning_objectives", "key_terms", "notes"):
                if ch.get(extra_k):
                    ch_obj[extra_k] = ch[extra_k]
            clean_chs.append(ch_obj)
            part_pages += t_pages

            ch_path = bp_dir / f"{cid}.yaml"
            ch_path.write_text(_dump_clean_yaml(ch_obj), encoding="utf-8")
            saved_ch_files.add(ch_path.name)

        if not clean_chs:
            continue
        clean_parts.append(
            {
                "part_number": len(clean_parts) + 1,
                "title": str(part.get("title") or f"제{len(clean_parts)+1}부").strip(),
                "pages": part_pages,
                "chapters": clean_chs,
            }
        )
        total_pages += part_pages

    if ch_seq == 0:
        raise ValueError("최소 1개 이상의 단원(Chapter)이 필요합니다.")

    # 삭제된 단원의 구 chNN.yaml 정리
    for old_f in bp_dir.glob("ch*.yaml"):
        if old_f.name not in saved_ch_files:
            old_f.unlink(missing_ok=True)

    meta_in = dict(raw_data.get("book_metadata") or {})
    meta_out = {
        **meta_in,
        "title_ko": str(meta_in.get("title_ko") or st.get("topic_ko", "")).strip(),
        "title_en": str(meta_in.get("title_en") or st.get("topic_en", "")).strip(),
        "target_audience": str(meta_in.get("target_audience") or st.get("target_audience", "")).strip(),
        "target_pages": int(meta_in.get("target_pages") or total_pages),
        "target_total_pages": total_pages,
        "chapter_count": ch_seq,
        "updated_at": utc_now_iso(),
    }
    master_out = {"book_metadata": meta_out, "parts": clean_parts}
    master_path.write_text(_dump_clean_yaml(master_out), encoding="utf-8")

    # state.json 동기화 (제목·목표쪽수·단원수·청사진 미리보기)
    st["topic_ko"] = meta_out["title_ko"] or st.get("topic_ko", "")
    st["topic_en"] = meta_out["title_en"] or st.get("topic_en", "")
    st["target_audience"] = meta_out["target_audience"] or st.get("target_audience", "")
    st["target_pages"] = total_pages
    st["chapter_count"] = ch_seq
    st["blueprint_preview"] = master_out
    save_project_state(st)
    append_event(
        st["project_id"],
        "curriculum-architect",
        "stage4_curriculum_architect",
        f"사용자 마스터 청사진 수정 저장 완료: 《{st['topic_ko']}》 ({len(clean_parts)}부 {ch_seq}장 · {total_pages}p)",
    )
    return {
        "status": "OK",
        "project_id": st["project_id"],
        "parts_count": len(clean_parts),
        "chapter_count": ch_seq,
        "total_pages": total_pages,
        "master_outline_path": str(master_path),
    }


@app.put("/api/blueprint")
def api_save_blueprint(req: BlueprintSaveRequest, project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    try:
        return _persist_blueprint(st, cfg, {"book_metadata": req.book_metadata, "parts": req.parts})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"청사진 저장 오류: {exc}")


@app.get("/api/blueprint/yaml")
def api_get_blueprint_yaml(project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    bp_path = cfg.blueprints_dir / "master_outline.yaml"
    if not bp_path.is_file():
        return {"exists": False, "project_id": st["project_id"], "yaml_text": ""}
    # alias 없이 깔끔하게 직렬화해 편집 편의 제공
    data = yaml.safe_load(bp_path.read_text(encoding="utf-8"))
    return {"exists": True, "project_id": st["project_id"], "yaml_text": _dump_clean_yaml(data)}


@app.put("/api/blueprint/yaml")
def api_save_blueprint_yaml(req: BlueprintYamlSaveRequest, project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    try:
        parsed = yaml.safe_load(req.yaml_text)
        if not isinstance(parsed, dict):
            raise ValueError("유효한 YAML 객체(book_metadata, parts) 형식이 아닙니다.")
        return _persist_blueprint(st, cfg, parsed)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"YAML 파싱·저장 오류: {exc}")


@app.post("/api/blueprint/init")
def api_init_blueprint(project: str = Query(default=""), chapters: int = Query(default=15, ge=3, le=24)) -> dict[str, Any]:
    """청사진이 없는 프로젝트에 편집 가능한 기본 마스터 청사진을 즉시 생성한다."""
    st, cfg = _resolve_project_ctx(project)
    n_ch = max(3, min(24, chapters))
    t_pages = int(st.get("target_pages") or 500)
    per_ch = max(15, round(t_pages / n_ch))
    kws = st.get("keywords_ko") or []
    parts_n = min(5, max(1, (n_ch + 2) // 3))
    parts: list[dict[str, Any]] = []
    ch_i = 0
    for p_idx in range(1, parts_n + 1):
        cnt = (n_ch - ch_i) if p_idx == parts_n else max(1, round((n_ch - ch_i) / (parts_n - p_idx + 1)))
        chs = []
        for _ in range(cnt):
            ch_i += 1
            kw_hint = kws[(ch_i - 1) % len(kws)] if kws else f"핵심 주제 {ch_i}"
            chs.append(
                {
                    "chapter_id": f"ch{ch_i:02d}",
                    "title": f"제{ch_i}장. {kw_hint}",
                    "target_pages": per_ch,
                    "sections": [f"{ch_i}.1 개요 및 원리", f"{ch_i}.2 정량 분석 및 메커니즘", f"{ch_i}.3 디지털 현장 적용"],
                }
            )
        parts.append({"part_number": p_idx, "title": f"제{p_idx}부. {st.get('topic_ko', '')} 영역 {p_idx}", "chapters": chs})
    return _persist_blueprint(
        st,
        cfg,
        {
            "book_metadata": {
                "title_ko": st.get("topic_ko", ""),
                "title_en": st.get("topic_en", ""),
                "target_audience": st.get("target_audience", ""),
                "target_pages": t_pages,
            },
            "parts": parts,
        },
    )


@app.get("/assets/{subdir}/{filename}")
def serve_visual_asset(subdir: str, filename: str, project: str = Query(default="")) -> FileResponse:
    if subdir not in ("figures", "charts", "charts_png"):
        raise HTTPException(status_code=404, detail="Invalid asset directory")
    _, cfg = _resolve_project_ctx(project)
    safe_name = Path(filename).name
    p = cfg.assets_dir / subdir / safe_name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path=str(p))


@app.get("/chapters/{chapter_id}", response_class=HTMLResponse)
def serve_interactive_chapter(chapter_id: str, project: str = Query(default="")) -> HTMLResponse:
    _, cfg = _resolve_project_ctx(project)
    p = cfg.workspace_exports_dir / chapter_id / f"{chapter_id}_interactive.html"
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"{chapter_id} 인터랙티브 웹페이지가 아직 빌드되지 않았습니다.")
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/blog/{chapter_id}", response_class=HTMLResponse)
def serve_naver_blog_chapter(chapter_id: str, project: str = Query(default="")) -> HTMLResponse:
    _, cfg = _resolve_project_ctx(project)
    p = cfg.workspace_exports_dir / chapter_id / f"{chapter_id}_naver_blog.html"
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"{chapter_id} 네이버 블로그 전용 HTML이 아직 빌드되지 않았습니다.")
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/exports/{chapter_id}/{filename}")
def download_export_file(chapter_id: str, filename: str, project: str = Query(default="")) -> FileResponse:
    _, cfg = _resolve_project_ctx(project)
    safe_name = Path(filename).name
    p = cfg.workspace_exports_dir / chapter_id / safe_name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(path=str(p), filename=safe_name)


@app.get("/api/chapter/{chapter_id}")
def api_chapter(chapter_id: str, project: str = Query(default="")) -> dict[str, Any]:
    st, cfg = _resolve_project_ctx(project)
    mdx = cfg.chapters_dir / f"{chapter_id}.mdx"
    audit_f = cfg.active_project_dir / "reports" / f"audit_{chapter_id}.json"
    if not audit_f.is_file() and st.get("is_reference_book"):
        audit_f = cfg.reports_dir / f"audit_{chapter_id}.json"
    content = mdx.read_text(encoding="utf-8") if mdx.is_file() else ""
    audit = json.loads(audit_f.read_text(encoding="utf-8")) if audit_f.is_file() else None
    sources = {r["source_id"]: r for r in _collect_unified_sources()}
    return {
        "project_id": st["project_id"],
        "chapter_id": chapter_id,
        "exists": mdx.is_file(),
        "content": content,
        "audit": audit,
        "sources_index": sources,
    }


@app.get("/api/export/bibliography", response_class=PlainTextResponse)
def api_export_bibliography(
    fmt: str = Query(default="markdown"),
    chapter: str = Query(default="all"),
    status: str = Query(default="approved"),
) -> PlainTextResponse:
    rows = _collect_unified_sources()
    selected = []
    for r in rows:
        if status != "all" and r.get("status") != status:
            continue
        if chapter != "all" and chapter not in (r.get("chapters") or []):
            continue
        selected.append(r)

    if fmt == "bibtex":
        blocks = []
        for r in selected:
            key = r["source_id"].replace("-", "_")
            blocks.append(
                f"@article{{{key},\n"
                f"  title = {{{r['title']}}},\n"
                f"  author = {{{r.get('authors') or r.get('provider') or 'Unknown'}}},\n"
                f"  journal = {{{r.get('journal') or r.get('tier')}}},\n"
                f"  year = {{{r.get('year') or '2026'}}},\n"
                f"  doi = {{{r.get('doi', '')}}},\n"
                f"  url = {{{r.get('url', '')}}}\n"
                f"}}"
            )
        return PlainTextResponse("\n\n".join(blocks), media_type="text/plain; charset=utf-8")

    if fmt == "apa":
        lines = []
        for r in selected:
            auth = r.get("authors") or r.get("tier")
            yr = r.get("year") or str(r.get("accessed_at", ""))[:4] or "n.d."
            jr = r.get("journal") or r.get("provider")
            lines.append(f"- [{r['source_id']}] {auth} ({yr}). {r['title']}. *{jr}*. {r.get('doi') or r.get('url')}")
        return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8")

    # default markdown table
    lines = [
        "| 출처 ID | 구분 | 등급 | 연도 | 피인용 | 제목 | 저널/출처 | 배정 단원 | 상태 |",
        "| :--- | :--- | :--- | :--- | ---: | :--- | :--- | :--- | :--- |",
    ]
    for r in selected:
        t = str(r["title"]).replace("|", "\\|")
        j = str(r.get("journal") or r.get("provider")).replace("|", "\\|")
        chs = ", ".join(r.get("chapters") or [])
        lines.append(
            f"| `{r['source_id']}` | {r['category']} | {r['tier']} | {r.get('year') or '-'} | "
            f"{r.get('cited_by_count', 0)} | {t} | {j} | {chs} | {r['status']} |"
        )
    return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")
