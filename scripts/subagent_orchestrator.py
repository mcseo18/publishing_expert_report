"""6단계 전문 교재 제작 오케스트레이터 (단일 통합 대시보드 · 체크포인트 이어하기 · 보고서 자동 생성).

새로운 표준 제작 절차 (6단계):
  1단계 [stage1_topic_outline]    : 주제 설정 → 초기 RAG/학술 탐색 + OpenAI API(또는 Gemma 4)로
                                    목차·단원별 요약·핵심 영역별 키워드 제시 → 사용자 검토·재요청·직접 수정 후 확정
  2단계 [stage2_source_collect]   : 확정 키워드 기반 문헌·교과서·교재·웹사이트(eco-browser/학술/기관) 수집·저장
                                    → 「2단계 자료 수집 현황 보고서(02_collection_report.md)」 자동 생성
  3단계 [stage3_kg_build]         : 수집 자료 기반 지식그래프 증분 구축(C:\\SMC_GRAPHRAG, 기존 graph.json 무훼손)
                                    → 「3단계 지식그래프 구축 보고서(03_kg_report.md)」 자동 생성
  4단계 [stage4_manuscript_draft] : 단원별 교재 집필([SRC-NN]·오해와 진실·문제풀이 연결) + 수식/인용 감사
                                    (단원별 체크포인트 저장 → 중단 시 마지막 완료 단원 다음부터 이어하기)
  5단계 [stage5_visuals_generate] : 단원당 10개 이상 시각화 자료 제작 (실사진·인포그래픽: fal.ai API 체크 ON 또는 나노바나나,
                                    정량 도해: Vector SVG + 줄글 텍스트 해설, 이미지별 체크포인트 저장)
  6단계 [stage6_publish_report]   : 신국판·B5·A4 PDF · Word DOCX · 네이버 블로그 HTML(해시태그 20개) 출판
                                    → 「6단계 교재 생성 완료 종합 보고서(06_final_book_report.md)」 자동 생성
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _dump_clean_yaml(data: Any) -> str:
    return yaml.dump(data, Dumper=_NoAliasDumper, allow_unicode=True, sort_keys=False, width=140)


STAGE_DEFINITIONS: list[dict[str, str]] = [
    {
        "stage_id": "stage1_topic_outline",
        "order": "1",
        "agent_name": "outline-architect",
        "title": "주제 탐색 · 목차/요약/키워드 설계 및 검토",
        "short_title": "목차·키워드 확정",
        "tier": "초기 검색 + OpenAI API / 로컬 Gemma 4 + 사용자 검토·재요청",
        "description": "주제를 바탕으로 초기 탐색과 OpenAI API를 활용해 목차·단원 요약·핵심 영역별 키워드를 제시하고 사용자 검토·수정 후 확정합니다.",
    },
    {
        "stage_id": "stage2_source_collect",
        "order": "2",
        "agent_name": "web-scout",
        "title": "문헌·교과서·웹사이트 수집 & 현황 보고서",
        "short_title": "자료 수집·보고서",
        "tier": "eco-browser · 국내외 학술 · 기관 · 교과서 → 분리 폴더 저장",
        "description": "확정된 목차·키워드에 따라 관련 문헌·교과서·웹사이트를 프로젝트 폴더에 수집·저장하고 수집 현황 보고서를 생성합니다.",
    },
    {
        "stage_id": "stage3_kg_build",
        "order": "3",
        "agent_name": "kg-builder",
        "title": "지식그래프 구축 & KG 보고서 생성",
        "short_title": "지식그래프·보고서",
        "tier": "로컬 Gemma 4 + C:\\SMC_GRAPHRAG (Append-Only)",
        "description": "수집 자료에서 엔티티·관계를 추출해 기존 graph.json을 보존하며 지식그래프를 증분 구축하고 KG 보고서를 생성합니다.",
    },
    {
        "stage_id": "stage4_manuscript_draft",
        "order": "4",
        "agent_name": "domain-drafter",
        "title": "교재 단원 집필 · 오해교정 · 인용 감사",
        "short_title": "교재 집필·감사",
        "tier": "로컬 Gemma 4 + 근거 패킷 + 인용/수식 감사 (단원별 이어하기)",
        "description": "[SRC-NN] 인용, 오해와 진실(≥3선), 1:1 문제↔풀이 연결 원고를 단원별로 집필·감사합니다.",
    },
    {
        "stage_id": "stage5_visuals_generate",
        "order": "5",
        "agent_name": "visual-artist",
        "title": "시각화 자료 제작 (단원당 10개 이상)",
        "short_title": "시각화(장당 10+)",
        "tier": "fal.ai API (선택 체크) · 나노바나나 · Vector SVG · 줄글 해설",
        "description": "단원당 10개 이상의 실사진·과학 인포그래픽(fal.ai/나노바나나) 및 정량 벡터 차트를 생성하고 줄글 해설을 작성합니다.",
    },
    {
        "stage_id": "stage6_publish_report",
        "order": "6",
        "agent_name": "book-publisher",
        "title": "최종 출판 & 교재 생성 완료 보고서",
        "short_title": "최종 출판·보고서",
        "tier": "PDF · Word DOCX · 네이버 블로그 HTML + 완료 종합 보고서",
        "description": "다중 판형 PDF·DOCX·네이버 블로그 HTML을 출판하고 교재 생성 완료 종합 보고서를 생성합니다.",
    },
]

STAGE_IDS_ORDER: list[str] = [s["stage_id"] for s in STAGE_DEFINITIONS]

_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_STOP_FLAGS: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def _runs_root(cfg: PlatformConfig | None = None) -> Path:
    cfg = cfg or get_config()
    root = cfg.index_dir / "subagent_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_dir(project_id: str, cfg: PlatformConfig | None = None) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_id).strip("_") or "project"
    d = _runs_root(cfg) / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(project_id: str, cfg: PlatformConfig | None = None) -> Path:
    return _project_dir(project_id, cfg) / "state.json"


def _events_path(project_id: str, cfg: PlatformConfig | None = None) -> Path:
    return _project_dir(project_id, cfg) / "events.jsonl"


def _slugify(topic: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "_", topic).strip("_").lower()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if ascii_part and len(ascii_part) >= 3:
        return f"{ascii_part[:28]}_{ts}"
    return f"book_{ts}"


def _fresh_stages() -> list[dict[str, Any]]:
    return [
        {
            **sdef,
            "status": "PENDING",
            "progress": 0,
            "started_at": "",
            "finished_at": "",
            "current_action": "실행 대기 중",
            "metrics": {},
            "artifacts": [],
            "error": "",
        }
        for sdef in STAGE_DEFINITIONS
    ]


def append_event(
    project_id: str,
    agent: str,
    stage_id: str,
    message: str,
    *,
    level: str = "INFO",
    detail: dict[str, Any] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    ev = {
        "timestamp": utc_now_iso(),
        "local_time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "stage_id": stage_id,
        "level": level,
        "message": message,
        "detail": detail or {},
    }
    ep = _events_path(project_id, cfg)
    with _LOCK:
        with ep.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def load_events(project_id: str, limit: int = 120, cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    ep = _events_path(project_id, cfg)
    if not ep.is_file():
        return []
    lines = ep.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def save_project_state(state: dict[str, Any], cfg: PlatformConfig | None = None) -> None:
    """체크포인트 안전 보장을 위해 임시 파일 작성 후 원자적(os.replace)으로 state.json을 저장한다."""
    state["updated_at"] = utc_now_iso()
    sp = _state_path(state["project_id"], cfg)
    tmp = sp.with_suffix(".json.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with _LOCK:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, sp)


def _migrate_to_v2_if_needed(state: dict[str, Any], cfg: PlatformConfig) -> dict[str, Any]:
    """기존 7단계 프로젝트 상태를 신규 6단계 워크플로(+체크포인트+보고서)로 무손실 자동 이관한다."""
    cur_ids = [s.get("stage_id") for s in state.get("stages", [])]
    if cur_ids == STAGE_IDS_ORDER and state.get("workflow_version") == 2:
        return state

    old_map = {s.get("stage_id"): s for s in state.get("stages", [])}
    ws_dir = Path(state.get("workspace_dir") or cfg.project_dir(state["project_id"]))
    rep_dir = ws_dir / "reports"
    bp_path = ws_dir / "blueprints" / "master_outline.yaml"
    ch_files = sorted((ws_dir / "chapters").glob("*.mdx")) if (ws_dir / "chapters").is_dir() else []

    new_stages = _fresh_stages()
    # 1단계: 기존 blueprint 존재 시 목차 확정/검토 상태로 반영
    if bp_path.is_file():
        bp_data = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        state["blueprint_preview"] = bp_data
        parts = bp_data.get("parts", [])
        n_ch = sum(len(pt.get("chapters") or []) for pt in parts)
        new_stages[0].update(
            {
                "status": "DONE",
                "progress": 100,
                "current_action": f"목차 확정 완료 ({len(parts)}부 {n_ch}장 · 언제든 수정·재요청 가능)",
                "metrics": {"parts": len(parts), "chapters": n_ch, "approved": True},
                "artifacts": [str(bp_path)],
            }
        )
        state["outline_approved"] = True

    # 2단계: 기존 수집 자료 반영
    if state.get("collected_sources"):
        s2_old = old_map.get("stage2_web_scout", {})
        new_stages[1].update(
            {
                "status": "DONE" if s2_old.get("status") == "DONE" else "PENDING",
                "progress": 100 if s2_old.get("status") == "DONE" else 0,
                "current_action": s2_old.get("current_action") or f"수집 완료 ({len(state['collected_sources'])}건)",
                "metrics": s2_old.get("metrics") or {"total_collected": len(state["collected_sources"])},
                "artifacts": s2_old.get("artifacts") or [],
            }
        )

    # 3단계: 기존 KG 구축 반영
    s3_old = old_map.get("stage3_kg_builder", {})
    if s3_old.get("status") == "DONE":
        new_stages[2].update(
            {
                "status": "DONE",
                "progress": 100,
                "current_action": s3_old.get("current_action", "지식그래프 증분 구축 완료"),
                "metrics": s3_old.get("metrics", {}),
                "artifacts": s3_old.get("artifacts", []),
            }
        )

    # 4단계: 기존 집필 원고 반영
    if ch_files:
        completed_chs = [p.stem for p in ch_files]
        new_stages[3].update(
            {
                "status": "INTERRUPTED" if len(completed_chs) < int(state.get("chapter_count") or 15) else "DONE",
                "progress": min(100, int((len(completed_chs) / max(1, int(state.get("chapter_count") or 15))) * 100)),
                "current_action": f"{len(completed_chs)}/{state.get('chapter_count', 15)}개 단원 집필 완료 (이어하기 가능)",
                "metrics": {"completed_chapters": len(completed_chs), "total_chapters": int(state.get("chapter_count") or 15)},
                "artifacts": [str(p) for p in ch_files[:5]],
            }
        )
        state.setdefault("checkpoint", {})["completed_chapters"] = completed_chs

    state["workflow_version"] = 2
    state["stages"] = new_stages
    state.setdefault("checkpoint", {})
    state.setdefault("reports", {})
    state.setdefault("domain_keywords", [])
    opts = dict(state.get("options") or {})
    opts.setdefault("use_openai_outline", True)
    opts.setdefault("openai_model", "gpt-4o-mini")
    opts.setdefault("use_fal_ai", False)
    opts.setdefault("fal_model", "fal-ai/nano-banana")
    opts.setdefault("use_nano_banana", True)
    opts.setdefault("visuals_per_chapter", 10)
    opts.setdefault("gemma_model", cfg.ollama_fast_model)
    opts.setdefault("kg_model", cfg.ollama_fast_model)
    state["options"] = opts

    # 기존 수집/KG 데이터로 2단계·3단계 마크다운 보고서 자동 보완
    rep_dir.mkdir(parents=True, exist_ok=True)
    if state.get("collected_sources") and not (rep_dir / "02_collection_report.md").is_file():
        _write_stage2_report(state, cfg)
    if new_stages[2]["status"] == "DONE" and not (rep_dir / "03_kg_report.md").is_file():
        _write_stage3_report(state, new_stages[2].get("metrics", {}), cfg)

    all_done = all(s["status"] == "DONE" for s in new_stages)
    state["overall_status"] = "DONE" if all_done else "PAUSED"
    save_project_state(state, cfg)
    return state


def load_project_state(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any] | None:
    cfg = cfg or get_config()
    sp = _state_path(project_id, cfg)
    if not sp.is_file():
        return None
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return None

    st = _migrate_to_v2_if_needed(st, cfg)

    # 비정상 중단(서버 종료/재시작 등) 자동 복구: 스레드가 없는데 RUNNING이면 INTERRUPTED로 전환해 이어하기 제공
    th = _ACTIVE_THREADS.get(project_id)
    is_live = bool(th and th.is_alive())
    if not is_live and st.get("overall_status") == "RUNNING":
        st["overall_status"] = "INTERRUPTED"
        st["active_stage_id"] = None
        for s in st.get("stages", []):
            if s.get("status") == "RUNNING":
                s["status"] = "INTERRUPTED"
                s["current_action"] = f"중단됨(체크포인트 저장 완료) — [▶ 이어하기]로 재개 가능 ({s.get('current_action','')[:60]})"
        save_project_state(st, cfg)
    return st


def ensure_seed_soil_project(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """하위 호환용: 토양 유기물학 기준 프로젝트가 존재할 때만 반환하고, 초기화 후에는 강제 재생성하지 않는다."""
    cfg = cfg or get_config()
    existing = load_project_state("soil_organic_matter_500p", cfg)
    if existing:
        return existing
    # 아카이브된 경우 빈 참조 메타만 반환 (활성 프로젝트 목록에 강제 삽입 금지)
    return {
        "project_id": "soil_organic_matter_500p",
        "is_reference_book": True,
        "topic_ko": "토양 유기물학",
        "workspace_dir": str(cfg.project_dir("soil_organic_matter")),
        "packet_id": "ch01_evidence",
        "target_pages": 500,
        "chapter_count": 16,
    }


def list_projects(cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    """현재 활성 관리 중인 프로젝트 목록만 반환한다 (자동 시드 재주입 없음)."""
    cfg = cfg or get_config()
    out = []
    for d in sorted(_runs_root(cfg).iterdir()):
        if not d.is_dir():
            continue
        st = load_project_state(d.name, cfg)
        if st:
            done_cnt = sum(1 for s in st.get("stages", []) if s.get("status") == "DONE")
            out.append(
                {
                    "project_id": st["project_id"],
                    "topic_ko": st["topic_ko"],
                    "topic_en": st.get("topic_en", ""),
                    "target_pages": st.get("target_pages", 500),
                    "chapter_count": st.get("chapter_count", 15),
                    "overall_status": st.get("overall_status", "IDLE"),
                    "active_stage_id": st.get("active_stage_id"),
                    "done_stages": done_cnt,
                    "total_stages": len(st.get("stages", [])),
                    "outline_approved": bool(st.get("outline_approved", False)),
                    "is_reference_book": bool(st.get("is_reference_book", False)),
                    "updated_at": st.get("updated_at", ""),
                }
            )
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


def delete_project(project_id: str, *, archive: bool = True, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트를 관리 목록에서 삭제한다 (안전을 위해 E:\\_archived_projects로 이동 후 제거)."""
    cfg = cfg or get_config()
    stop_pipeline(project_id, cfg)
    run_dir = _runs_root(cfg) / re.sub(r"[^a-zA-Z0-9_\-]", "_", project_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Project not found: {project_id}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arch_root = cfg.collected_data_root / "_archived_projects" / f"{project_id}_{stamp}"
    if archive:
        arch_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(run_dir), str(arch_root / "run_state"))
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
    return {"status": "DELETED", "project_id": project_id, "archived_to": str(arch_root) if archive else ""}


def reset_projects_keep_only(keep_ids: list[str], cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """지정한 프로젝트(예: 디지털 밀 재배)만 남기고 나머지 프로젝트 관리 이력을 초기화(아카이브)한다."""
    cfg = cfg or get_config()
    keep_set = set(keep_ids)
    removed: list[str] = []
    kept: list[str] = []
    for d in sorted(_runs_root(cfg).iterdir()):
        if not d.is_dir():
            continue
        if d.name in keep_set:
            kept.append(d.name)
            continue
        delete_project(d.name, archive=True, cfg=cfg)
        removed.append(d.name)
    # active_project.json 도 유지 프로젝트로 동기화
    if kept:
        ap = cfg.index_dir / "active_project.json"
        ap.write_text(json.dumps({"project_id": kept[0], "updated_at": utc_now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "OK", "kept": kept, "removed": removed}


def create_project(
    topic_ko: str,
    topic_en: str = "",
    keywords_ko: list[str] | None = None,
    keywords_en: list[str] | None = None,
    target_audience: str = "대학 전공 심화, 연구자 및 선도 실무자",
    target_pages: int = 500,
    chapter_count: int = 15,
    options: dict[str, Any] | None = None,
    project_id_override: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    if project_id_override:
        pid = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_id_override).strip("_").lower() or _slugify(topic_en or topic_ko)
    else:
        pid = _slugify(topic_en or topic_ko)
    proj_ws = cfg.project_dir(pid)
    for sub in ("collected", "blueprints", "chapters", "assets", "exports", "reports"):
        (proj_ws / sub).mkdir(parents=True, exist_ok=True)
    e_proj_exp = cfg.project_e_exports_dir(pid)
    e_proj_exp.mkdir(parents=True, exist_ok=True)
    e_proj_col = cfg.project_collected_dir(pid)
    for tdir in ("01_domestic_agencies", "02_domestic_journals", "03_international_agencies", "04_international_journals"):
        (e_proj_col / tdir).mkdir(parents=True, exist_ok=True)
    e_proj_ev = cfg.project_e_evidence_dir(pid)
    e_proj_ev.mkdir(parents=True, exist_ok=True)

    kw_ko = [k.strip() for k in (keywords_ko or []) if k.strip()] or [topic_ko.strip()]
    kw_en = [k.strip() for k in (keywords_en or []) if k.strip()] or ([topic_en.strip()] if topic_en.strip() else [topic_ko.strip()])

    opts = {
        "use_openai_outline": True,
        "openai_model": "gpt-4o-mini",
        "use_fal_ai": False,
        "fal_model": "fal-ai/nano-banana",
        "use_nano_banana": True,
        "visuals_per_chapter": 10,
        "enable_naver_blog": True,
        "enable_myths": True,
        "enable_linked_quiz": True,
        "download_oa_pdf": True,
        "gemma_model": cfg.ollama_fast_model,
        "kg_model": cfg.ollama_fast_model,
        "use_claude_review": False,
        "use_claude_blueprint": False,
        "domestic_agency_urls": [],
        "international_agency_urls": [],
        "trim_formats": ["shinkuk", "b5", "a4"],
        "papers_per_query": 5,
        "draft_chapter_limit": 0,  # 0 = 전체 단원 순차 집필
        **(options or {}),
    }

    now = utc_now_iso()
    state = {
        "workflow_version": 2,
        "project_id": pid,
        "is_reference_book": False,
        "topic_ko": topic_ko.strip(),
        "topic_en": topic_en.strip() or topic_ko.strip(),
        "keywords_ko": kw_ko,
        "keywords_en": kw_en,
        "domain_keywords": [],
        "target_audience": target_audience.strip(),
        "target_pages": max(50, int(target_pages)),
        "chapter_count": max(3, min(24, int(chapter_count))),
        "outline_approved": False,
        "outline_revisions": [],
        "options": opts,
        "workspace_dir": str(proj_ws),
        "collected_dir": str(e_proj_col),
        "e_evidence_dir": str(e_proj_ev),
        "e_exports_dir": str(e_proj_exp),
        "packet_id": f"{pid}_evidence",
        "overall_status": "IDLE",
        "active_stage_id": None,
        "created_at": now,
        "updated_at": now,
        "stages": _fresh_stages(),
        "checkpoint": {
            "completed_chapters": [],
            "completed_visuals": [],
            "published_chapters": [],
        },
        "reports": {},
        "collection_breakdown": {
            "domestic_agencies": 0,
            "domestic_journals": 0,
            "international_agencies": 0,
            "international_journals": 0,
            "total": 0,
        },
        "collection_manifest_path": "",
        "collected_sources": [],
        "blueprint_preview": None,
        "outputs": {},
    }
    save_project_state(state, cfg)
    append_event(pid, "orchestrator", "init", f"신규 교재 프로젝트 생성: 《{topic_ko}》 ({target_pages}p / {chapter_count}장)", cfg=cfg)
    return state


# ---------- AI 엔진 상태 및 유틸 ----------
def _resolve_claude_bin() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "claude.EXE"
    return str(candidate) if candidate.is_file() else None


def get_ai_engines_status(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    ollama_info: dict[str, Any] = {"online": False, "version": "", "models": [], "running": []}
    try:
        from local_gemma import LocalGemmaClient

        h = LocalGemmaClient(cfg).check_health()
        ollama_info = {
            "online": True,
            "version": h.get("version", ""),
            "models": [m.get("name") for m in h.get("installed_models", []) if m.get("name")],
            "running": h.get("running_models", []),
            "host": cfg.ollama_host,
        }
    except Exception as exc:
        ollama_info["error"] = str(exc)[:120]

    claude_bin = _resolve_claude_bin()
    claude_info: dict[str, Any] = {"installed": bool(claude_bin), "path": claude_bin or "", "version": ""}
    if claude_bin:
        try:
            proc = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=8)
            claude_info["version"] = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
        except Exception as exc:
            claude_info["error"] = str(exc)[:100]

    rag_info: dict[str, Any] = {"catalog_exists": cfg.smc_catalog_db_path.is_file(), "nodes": 0, "edges": 0}
    if cfg.smc_catalog_db_path.is_file():
        try:
            conn = sqlite3.connect(str(cfg.smc_catalog_db_path))
            row = conn.execute("SELECT COALESCE(SUM(node_count),0), COALESCE(SUM(edge_count),0) FROM graph_files").fetchone()
            conn.close()
            if row:
                rag_info["nodes"] = int(row[0] or 0)
                rag_info["edges"] = int(row[1] or 0)
        except Exception:
            pass

    return {
        "checked_at": utc_now_iso(),
        "ollama": ollama_info,
        "claude_code": claude_info,
        "local_rag": rag_info,
        "openai_configured": bool(resolve_api_key("OPENAI_API_KEY", None, cfg)),
        "fal_configured": bool(resolve_api_key("FAL_KEY", None, cfg)),
        "gemini_configured": bool(resolve_api_key("GEMINI_API_KEY", None, cfg)),
    }


def update_project_options(project_id: str, updates: dict[str, Any], cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    opts = dict(st.get("options") or {})
    allowed_keys = {
        "use_openai_outline",
        "openai_model",
        "use_fal_ai",
        "fal_model",
        "use_nano_banana",
        "visuals_per_chapter",
        "gemma_model",
        "kg_model",
        "use_claude_review",
        "use_claude_blueprint",
        "download_oa_pdf",
        "papers_per_query",
        "draft_chapter_limit",
        "domestic_agency_urls",
        "international_agency_urls",
    }
    changed: dict[str, Any] = {}
    for k, v in updates.items():
        if k in allowed_keys and v is not None:
            opts[k] = v
            changed[k] = v
    st["options"] = opts
    save_project_state(st, cfg)
    if changed:
        append_event(project_id, "orchestrator", "config", f"설정 업데이트: {json.dumps(changed, ensure_ascii=False)}", cfg=cfg)
    return st


def _run_claude_code_stream(
    *,
    project_id: str,
    agent_name: str,
    stage_id: str,
    prompt: str,
    cfg: PlatformConfig,
    timeout_sec: int = 180,
) -> tuple[bool, str]:
    claude_bin = _resolve_claude_bin()
    if not claude_bin:
        append_event(project_id, f"{agent_name}:claude", stage_id, "Claude Code CLI 미설치로 건너뜁니다.", level="WARN", cfg=cfg)
        return False, ""

    append_event(project_id, f"{agent_name}:claude", stage_id, f"Claude Code 검수 실행 ({Path(claude_bin).name} --print)...", cfg=cfg)
    output_lines: list[str] = []
    start_ts = time.time()
    proc = subprocess.Popen(
        [claude_bin, "--print", prompt, "--output-format", "text"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cfg.workspace_root),
    )
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if line:
                output_lines.append(line)
                if len(output_lines) <= 30 or len(output_lines) % 4 == 0:
                    append_event(project_id, f"{agent_name}:claude", stage_id, line[:240], cfg=cfg)
            if time.time() - start_ts > timeout_sec:
                proc.kill()
                break
        proc.wait(timeout=10)
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        append_event(project_id, f"{agent_name}:claude", stage_id, f"Claude Code 오류: {exc}", level="WARN", cfg=cfg)
        return False, "\n".join(output_lines)

    full_text = "\n".join(output_lines).strip()
    ok = proc.returncode == 0 and bool(full_text) and "Please run /login" not in full_text
    return ok, full_text


def _update_stage(state: dict[str, Any], stage_id: str, cfg: PlatformConfig, **kwargs: Any) -> dict[str, Any]:
    for st in state["stages"]:
        if st["stage_id"] == stage_id:
            st.update(kwargs)
            save_project_state(state, cfg)
            return st
    raise KeyError(stage_id)


def _should_stop(project_id: str) -> bool:
    ev = _STOP_FLAGS.get(project_id)
    return bool(ev and ev.is_set())


# ============================================================
# OpenAI API (또는 Gemma 4 폴백) 목차·요약·핵심 영역별 키워드 설계기
# ============================================================
def _call_openai_outline_json(
    *,
    prompt: str,
    system_prompt: str,
    model: str = "gpt-4o-mini",
    api_key: str,
) -> dict[str, Any]:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model or "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def _generate_outline_proposal(
    state: dict[str, Any],
    cfg: PlatformConfig,
    feedback_prompt: str = "",
    initial_context: str = "",
) -> tuple[dict[str, Any], str]:
    """OpenAI API(설정 시 우선) 또는 로컬 Ollama Gemma 4로 목차·요약·핵심 영역별 키워드를 생성한다."""
    n_ch = int(state.get("chapter_count") or 15)
    t_pages = int(state.get("target_pages") or 500)
    per_ch = max(15, round(t_pages / max(1, n_ch)))
    opts = state.get("options") or {}
    use_openai = bool(opts.get("use_openai_outline", True))
    openai_key = resolve_api_key("OPENAI_API_KEY", None, cfg) if use_openai else ""
    openai_model = opts.get("openai_model") or "gpt-4o-mini"

    prev_outline = state.get("blueprint_preview")
    prev_summary_txt = ""
    if feedback_prompt and prev_outline and prev_outline.get("parts"):
        prev_lines = []
        for pt in prev_outline["parts"]:
            prev_lines.append(f"[{pt.get('title','')}] " + " / ".join(c.get("title", "") for c in pt.get("chapters", [])))
        prev_summary_txt = "\n[기존 목차 초안]\n" + "\n".join(prev_lines)

    sys_prompt = (
        "당신은 500페이지 대학 전공 심화·연구자·현장 실무자용 표준 전문 교재를 기획하는 수석 교육과정 설계자입니다. "
        "반드시 순수 JSON 객체만 출력하며, 5개 부(Part) 내외로 체계적으로 그룹화하고 각 단원의 상세 요약(summary_ko)과 "
        "핵심 영역별 한국어/영문 검색 키워드(domain_keywords)를 빠짐없이 제시하십시오."
    )
    user_prompt = (
        f"교재 주제(국문): {state['topic_ko']}\n"
        f"교재 주제(영문): {state.get('topic_en', '')}\n"
        f"초기 입력 키워드: {', '.join(state.get('keywords_ko', []))}\n"
        f"목표 분량: {t_pages}쪽 · 정확히 {n_ch}개 단원 (단원당 약 {per_ch}쪽, 4~5개 부로 체계적 그룹화)\n"
        f"대상 독자: {state.get('target_audience', '')}\n"
        + (f"\n[초기 탐색 참고 문헌·RAG 현황]\n{initial_context}\n" if initial_context else "")
        + prev_summary_txt
        + (f"\n\n[사용자 수정·재요청 사항 — 반드시 최우선 반영]\n{feedback_prompt}\n" if feedback_prompt else "")
        + "\n출력 JSON 형식:\n"
        "{\n"
        '  "book_summary_ko": "교재 전체 기획 의도 및 핵심 요약 (3~4문장)",\n'
        '  "domain_keywords": [\n'
        '    {"domain": "핵심 영역명", "keywords_ko": ["한글키워드1", "한글키워드2"], "keywords_en": ["english keyword 1", "english keyword 2"]}\n'
        "  ],\n"
        '  "parts": [\n'
        "    {\n"
        '      "part_number": 1,\n'
        '      "title": "제1부. ...",\n'
        '      "chapters": [\n'
        "        {\n"
        '          "chapter_number": 1,\n'
        '          "title": "제1장. ...",\n'
        f'          "target_pages": {per_ch},\n'
        '          "summary_ko": "이 단원에서 다루는 핵심 원리·정량 기준·현장 적용 요약 (2문장)",\n'
        '          "sections": ["1.1 ...", "1.2 ...", "1.3 ...", "1.4 ..."],\n'
        '          "keywords_ko": ["단원핵심어1", "단원핵심어2"],\n'
        '          "keywords_en": ["chapter keyword 1", "chapter keyword 2"]\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    raw: dict[str, Any] | None = None
    engine_used = "fallback"

    if openai_key:
        try:
            raw = _call_openai_outline_json(prompt=user_prompt, system_prompt=sys_prompt, model=openai_model, api_key=openai_key)
            engine_used = f"OpenAI ({openai_model})"
        except Exception as exc:
            append_event(state["project_id"], "outline-architect", "stage1_topic_outline", f"OpenAI API 호출 실패 → 로컬 Gemma 4 폴백: {exc}", level="WARN", cfg=cfg)

    if raw is None:
        try:
            from local_gemma import LocalGemmaClient

            gmdl = opts.get("gemma_model") or cfg.ollama_fast_model
            schema = {
                "type": "object",
                "properties": {
                    "book_summary_ko": {"type": "string"},
                    "domain_keywords": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "domain": {"type": "string"},
                                "keywords_ko": {"type": "array", "items": {"type": "string"}},
                                "keywords_en": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["domain", "keywords_ko", "keywords_en"],
                        },
                    },
                    "parts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "part_number": {"type": "integer"},
                                "title": {"type": "string"},
                                "chapters": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "chapter_number": {"type": "integer"},
                                            "title": {"type": "string"},
                                            "target_pages": {"type": "integer"},
                                            "summary_ko": {"type": "string"},
                                            "sections": {"type": "array", "items": {"type": "string"}},
                                            "keywords_ko": {"type": "array", "items": {"type": "string"}},
                                            "keywords_en": {"type": "array", "items": {"type": "string"}},
                                        },
                                        "required": ["title", "sections"],
                                    },
                                },
                            },
                            "required": ["title", "chapters"],
                        },
                    },
                },
                "required": ["parts"],
            }
            raw = LocalGemmaClient(cfg).chat_structured(
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                schema=schema,
                model=gmdl,
                timeout=180,
            )
            engine_used = f"Ollama ({gmdl})"
        except Exception as exc:
            append_event(state["project_id"], "outline-architect", "stage1_topic_outline", f"로컬 Gemma 4 목차 생성 폴백: {exc}", level="WARN", cfg=cfg)

    # 정규화 및 단원 수 보정
    parts_in = (raw or {}).get("parts") or []
    flat_chs: list[tuple[str, dict[str, Any]]] = []
    for pt in parts_in:
        pt_title = str(pt.get("title") or "제1부").strip()
        for c in pt.get("chapters") or []:
            flat_chs.append((pt_title, c))

    kws_ko = state.get("keywords_ko") or [state["topic_ko"]]
    kws_en = state.get("keywords_en") or [state.get("topic_en", state["topic_ko"])]
    while len(flat_chs) < n_ch:
        idx = len(flat_chs) + 1
        kw = kws_ko[(idx - 1) % len(kws_ko)]
        p_grp = min(5, ((idx - 1) * 5) // max(1, n_ch) + 1)
        flat_chs.append(
            (
                f"제{p_grp}부. {state['topic_ko']} 핵심 영역 {p_grp}",
                {
                    "title": f"제{idx}장. {kw}의 원리와 디지털 현장 관리",
                    "target_pages": per_ch,
                    "summary_ko": f"{state['topic_ko']}에서 {kw}의 과학적 메커니즘, 정량 측정 지표 및 디지털 정밀 관리 전략을 다룹니다.",
                    "sections": [f"{idx}.1 기초 원리 및 개념", f"{idx}.2 정량 측정·모델링", f"{idx}.3 국내외 기준 비교", f"{idx}.4 디지털 현장 적용"],
                    "keywords_ko": [kw],
                    "keywords_en": [kws_en[(idx - 1) % len(kws_en)]],
                },
            )
        )
    flat_chs = flat_chs[:n_ch]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for ch_i, (pt_title, c) in enumerate(flat_chs, 1):
        cid = f"ch{ch_i:02d}"
        grouped.setdefault(pt_title, []).append(
            {
                "chapter_id": cid,
                "chapter_number": ch_i,
                "title": str(c.get("title") or f"제{ch_i}장").strip(),
                "target_pages": max(10, int(c.get("target_pages") or per_ch)),
                "summary_ko": str(c.get("summary_ko") or "").strip(),
                "sections": [str(x).strip() for x in (c.get("sections") or [f"{ch_i}.1 개요", f"{ch_i}.2 원리", f"{ch_i}.3 적용"]) if str(x).strip()],
                "keywords_ko": [str(x).strip() for x in (c.get("keywords_ko") or []) if str(x).strip()],
                "keywords_en": [str(x).strip() for x in (c.get("keywords_en") or []) if str(x).strip()],
                "evidence_packet": f"{state['packet_id']}.json",
                "assigned_sources": [s.get("source_id") for s in state.get("collected_sources", []) if s.get("source_id")],
            }
        )

    parts_out = [
        {
            "part_number": p_i,
            "title": pt_title,
            "pages": sum(c["target_pages"] for c in chs),
            "chapters": chs,
        }
        for p_i, (pt_title, chs) in enumerate(grouped.items(), 1)
    ]
    total_p = sum(pt["pages"] for pt in parts_out)
    dom_kws = (raw or {}).get("domain_keywords") or [
        {"domain": pt["title"], "keywords_ko": list(dict.fromkeys(k for c in pt["chapters"] for k in c.get("keywords_ko", []))) or kws_ko[:3], "keywords_en": list(dict.fromkeys(k for c in pt["chapters"] for k in c.get("keywords_en", []))) or kws_en[:3]}
        for pt in parts_out
    ]
    outline = {
        "book_metadata": {
            "title_ko": state["topic_ko"],
            "title_en": state.get("topic_en", state["topic_ko"]),
            "target_audience": state.get("target_audience", ""),
            "book_summary_ko": (raw or {}).get("book_summary_ko") or f"《{state['topic_ko']}》 {total_p}p 전문 대학교재 및 현장 실무 지침서",
            "target_pages": total_p,
            "target_total_pages": total_p,
            "chapter_count": len(flat_chs),
            "engine_used": engine_used,
            "generated_at": utc_now_iso(),
        },
        "domain_keywords": dom_kws,
        "parts": parts_out,
    }
    return outline, engine_used


def _save_outline_files(state: dict[str, Any], outline: dict[str, Any], cfg: PlatformConfig) -> Path:
    bp_dir = Path(state["workspace_dir"]) / "blueprints"
    bp_dir.mkdir(parents=True, exist_ok=True)
    master_path = bp_dir / "master_outline.yaml"
    if master_path.is_file():
        bdir = bp_dir / "_backups"
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(master_path, bdir / f"master_outline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml")
    master_path.write_text(_dump_clean_yaml(outline), encoding="utf-8")

    saved_names: set[str] = set()
    for pt in outline.get("parts", []):
        for c in pt.get("chapters", []):
            cid = c["chapter_id"]
            p = bp_dir / f"{cid}.yaml"
            p.write_text(_dump_clean_yaml(c), encoding="utf-8")
            saved_names.add(p.name)
    for old_f in bp_dir.glob("ch*.yaml"):
        if old_f.name not in saved_names:
            old_f.unlink(missing_ok=True)

    # 영역별 키워드 -> state.keywords_ko / keywords_en에도 통합 반영
    dom_kws = outline.get("domain_keywords") or []
    all_ko = list(dict.fromkeys([*(state.get("keywords_ko") or []), *(k for d in dom_kws for k in d.get("keywords_ko", []))]))
    all_en = list(dict.fromkeys([*(state.get("keywords_en") or []), *(k for d in dom_kws for k in d.get("keywords_en", []))]))
    state["keywords_ko"] = all_ko[:24]
    state["keywords_en"] = all_en[:24]
    state["domain_keywords"] = dom_kws
    state["blueprint_preview"] = outline
    meta = outline.get("book_metadata") or {}
    if meta.get("title_ko"):
        state["topic_ko"] = meta["title_ko"]
    if meta.get("title_en"):
        state["topic_en"] = meta["title_en"]
    state["target_pages"] = int(meta.get("target_total_pages") or meta.get("target_pages") or state.get("target_pages", 500))
    state["chapter_count"] = sum(len(pt.get("chapters") or []) for pt in outline.get("parts", []))
    save_project_state(state, cfg)
    return master_path


# ============================================================
# 보고서 자동 생성기 (2단계 수집 현황 / 3단계 KG / 6단계 최종 완료)
# ============================================================
def _write_stage2_report(state: dict[str, Any], cfg: PlatformConfig) -> Path:
    rep_dir = Path(state["workspace_dir"]) / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    srcs = state.get("collected_sources") or []
    bd = state.get("collection_breakdown") or {}
    lines = [
        f"# 2단계 자료 수집 현황 보고서 — 《{state['topic_ko']}》",
        "",
        f"- **생성 시각**: `{utc_now_iso()}`",
        f"- **프로젝트 ID**: `{state['project_id']}`",
        f"- **분리 저장 폴더**: `{state.get('collected_dir', '')}`",
        f"- **총 수집 확보 자료**: **{len(srcs)}건**",
        f"  - `01_domestic_agencies` (국내 공식기관·웹사이트): **{bd.get('domestic_agencies', 0)}건**",
        f"  - `02_domestic_journals` (국내 학회지·연구기관): **{bd.get('domestic_journals', 0)}건**",
        f"  - `03_international_agencies` (해외 공식기관·국제기구·대학): **{bd.get('international_agencies', 0)}건**",
        f"  - `04_international_journals` (국제 SCI·오픈액세스 저널): **{bd.get('international_journals', 0)}건**",
        "",
        "## 수집 확보 문헌·웹사이트 목록",
        "",
        "| 출처 ID | 분류 폴더 | 제공처/기관 | 연도 | 제목 | URL |",
        "| :--- | :--- | :--- | :---: | :--- | :--- |",
    ]
    for s in srcs:
        t = str(s.get("title", "")).replace("|", "/")[:80]
        p = str(s.get("provider", "")).replace("|", "/")[:32]
        lines.append(f"| `{s.get('source_id','')}` | `{s.get('tier_folder','-')}` | {p} | {s.get('year') or '-'} | {t} | {s.get('url','')} |")
    md_path = rep_dir / "02_collection_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state.setdefault("reports", {})["stage2_collection"] = str(md_path)
    save_project_state(state, cfg)
    return md_path


def _write_stage3_report(state: dict[str, Any], kg_metrics: dict[str, Any], cfg: PlatformConfig) -> Path:
    rep_dir = Path(state["workspace_dir"]) / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    top_nodes: list[dict[str, Any]] = []
    sample_edges: list[dict[str, Any]] = []
    inc_path = cfg.smc_incremental_graph_path
    proj_sids = {s.get("source_id") for s in (state.get("collected_sources") or []) if s.get("source_id")}
    if inc_path.is_file():
        try:
            raw = json.loads(inc_path.read_text(encoding="utf-8"))
            nodes = raw.get("nodes", [])
            edges = raw.get("edges", raw.get("links", []))
            proj_nodes = [n for n in nodes if any(sid in str(n.get("source_ids", "")) for sid in proj_sids)] or nodes
            top_nodes = sorted(proj_nodes, key=lambda n: int(n.get("mentions", 1) or 1), reverse=True)[:20]
            sample_edges = [e for e in edges if e.get("source_id") in proj_sids][:25] or edges[-25:]
        except Exception:
            pass

    lines = [
        f"# 3단계 지식그래프 구축 보고서 — 《{state['topic_ko']}》",
        "",
        f"- **생성 시각**: `{utc_now_iso()}`",
        f"- **통합 저장소**: `{cfg.smc_incremental_graph_path}` (기존 `C:\\SMC_GRAPHRAG\\output\\graph.json` 100% 무훼손 보존)",
        f"- **프로젝트 대상 자료 수**: **{kg_metrics.get('project_sources', len(proj_sids))}건** (신규 처리: {kg_metrics.get('newly_ingested', 0)}건)",
        f"- **증분 반영 결과**: 노드 **+{kg_metrics.get('nodes_added', 0)}** (누적 `{kg_metrics.get('nodes_after', 0)}`) · 관계 **+{kg_metrics.get('edges_added', 0)}** (누적 `{kg_metrics.get('edges_after', 0)}`)",
        "",
        "## 핵심 추출 엔티티 (상위 20개)",
        "",
        "| 엔티티 | 유형 | 언급 횟수 | 근거 출처 ID |",
        "| :--- | :---: | :---: | :--- |",
    ]
    for n in top_nodes:
        lines.append(f"| **{str(n.get('id','')).replace('|','/')}** | `{n.get('type','CONCEPT')}` | {n.get('mentions',1)} | `{str(n.get('source_ids',''))[:40]}` |")
    lines.extend(["", "## 핵심 지식 관계망 (Triples 발췌)", "", "| 주체 (Source) | 관계 (Relation) | 대상 (Target) | 출처 ID |", "| :--- | :---: | :--- | :--- |"])
    for e in sample_edges:
        lines.append(f"| {str(e.get('source','')).replace('|','/')} | `{str(e.get('relation','')).replace('|','/')}` | {str(e.get('target','')).replace('|','/')} | `{e.get('source_id','')}` |")

    md_path = rep_dir / "03_kg_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state.setdefault("reports", {})["stage3_kg"] = str(md_path)
    save_project_state(state, cfg)
    return md_path


def _write_stage6_report(state: dict[str, Any], pub_info: dict[str, Any], cfg: PlatformConfig) -> Path:
    rep_dir = Path(state["workspace_dir"]) / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    ch_dir = Path(state["workspace_dir"]) / "chapters"
    ch_files = sorted(ch_dir.glob("*.mdx"))
    total_chars = sum(len(p.read_text(encoding="utf-8", errors="ignore")) for p in ch_files)
    vis_plan = Path(state["workspace_dir"]) / "assets" / "visuals_plan.json"
    vis_meta = json.loads(vis_plan.read_text(encoding="utf-8")) if vis_plan.is_file() else {}
    audit_path = rep_dir / "audit_latest.json"
    audit_meta = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}

    lines = [
        f"# 6단계 교재 생성 완료 종합 보고서 — 《{state['topic_ko']}》",
        "",
        f"- **완료 시각**: `{utc_now_iso()}`",
        f"- **교재 제목**: 《{state['topic_ko']}》 ({state.get('topic_en', '')})",
        f"- **목표 분량 / 단원 수**: {state.get('target_pages', 500)}p / {state.get('chapter_count', 15)}개 단원",
        f"- **집필 완료 원고**: **{len(ch_files)}개 단원 · 총 {total_chars:,}자**",
        f"- **근거 수집 자료**: **{len(state.get('collected_sources') or [])}건** (`{state.get('collected_dir', '')}`)",
        f"- **시각화 자료**: 총 **{vis_meta.get('total_generated', 0)}종** (AI 실사진/인포그래픽 {vis_meta.get('ai_images_count', 0)}종 · Vector SVG {vis_meta.get('svg_charts_count', 0)}종, 단원당 목표 {vis_meta.get('per_chapter_target', 10)}개+)",
        f"- **인용 무결성 감사**: `{audit_meta.get('status', 'N/A')}` (치명오류 {len(audit_meta.get('critical_errors') or [])}건 · 경고 {len(audit_meta.get('warnings') or [])}건)",
        f"- **출판 산출물 파일 수**: **{pub_info.get('published_files', 0)}개** (`{state.get('e_exports_dir', '')}` 미러링 완료)",
        "",
        "## 단원별 작성 및 출판 요약",
        "",
        "| 단원 | 파일명 | 분량 (자) | 출판 포맷 |",
        "| :---: | :--- | ---: | :--- |",
    ]
    for p in ch_files:
        c_len = len(p.read_text(encoding="utf-8", errors="ignore"))
        lines.append(f"| `{p.stem}` | `{p.name}` | {c_len:,} | 교재 PDF · 교과서 PDF · 보고서 DOCX · 네이버 블로그 HTML |")

    md_path = rep_dir / "06_final_book_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state.setdefault("reports", {})["stage6_final"] = str(md_path)
    save_project_state(state, cfg)
    return md_path


def load_stage_report(project_id: str, report_key: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project {project_id} not found")
    rep_dir = Path(st["workspace_dir"]) / "reports"
    fname_map = {
        "stage2_collection": "02_collection_report.md",
        "stage3_kg": "03_kg_report.md",
        "stage6_final": "06_final_book_report.md",
    }
    p = Path(st.get("reports", {}).get(report_key) or (rep_dir / fname_map.get(report_key, report_key)))
    if not p.is_file():
        return {"exists": False, "report_key": report_key, "content": ""}
    return {"exists": True, "report_key": report_key, "path": str(p), "content": p.read_text(encoding="utf-8")}


# ============================================================
# 1단계 사용자 검토 · 재요청 · 승인 API 함수
# ============================================================
def revise_stage1_outline(
    project_id: str,
    feedback_prompt: str,
    *,
    use_openai: bool | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """1단계: 사용자의 수정·재요청 프롬프트를 반영해 목차·요약·영역별 키워드를 재생성한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    if use_openai is not None:
        st.setdefault("options", {})["use_openai_outline"] = use_openai

    append_event(project_id, "outline-architect", "stage1_topic_outline", f"사용자 재요청 반영 중: {feedback_prompt[:120]}", cfg=cfg)
    outline, engine_used = _generate_outline_proposal(st, cfg, feedback_prompt=feedback_prompt)
    master_path = _save_outline_files(st, outline, cfg)
    st.setdefault("outline_revisions", []).append(
        {"timestamp": utc_now_iso(), "feedback": feedback_prompt, "engine_used": engine_used}
    )
    st["outline_approved"] = False
    st["overall_status"] = "WAITING_REVIEW"
    _update_stage(
        st,
        "stage1_topic_outline",
        cfg,
        status="WAITING_REVIEW",
        progress=85,
        current_action=f"재요청 반영 완료({engine_used}) — 검토 후 [✅ 목차 확정] 또는 추가 수정 요청",
        metrics={
            "parts": len(outline["parts"]),
            "chapters": st["chapter_count"],
            "engine": engine_used,
            "revisions": len(st["outline_revisions"]),
            "approved": False,
        },
        artifacts=[str(master_path)],
    )
    return {"status": "OK", "engine_used": engine_used, "outline": outline, "project": st}


def approve_stage1_outline(
    project_id: str,
    edited_outline: dict[str, Any] | None = None,
    *,
    auto_continue: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """1단계: 사용자가 목차·요약·영역별 키워드를 최종 확정하고 2단계 자료 수집을 해제한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    if edited_outline and edited_outline.get("parts"):
        _save_outline_files(st, edited_outline, cfg)

    st["outline_approved"] = True
    st["overall_status"] = "PAUSED"
    bp_path = Path(st["workspace_dir"]) / "blueprints" / "master_outline.yaml"
    parts = (st.get("blueprint_preview") or {}).get("parts") or []
    _update_stage(
        st,
        "stage1_topic_outline",
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"목차·요약·핵심 키워드 확정 완료 ({len(parts)}부 {st['chapter_count']}장)",
        metrics={"parts": len(parts), "chapters": st["chapter_count"], "approved": True},
        artifacts=[str(bp_path)] if bp_path.is_file() else [],
    )
    append_event(project_id, "outline-architect", "stage1_topic_outline", f"사용자 최종 승인 완료: {len(parts)}부 {st['chapter_count']}장 → 2단계 자료 수집 준비 완료", cfg=cfg)
    run_info = start_pipeline_async(project_id, mode="all", cfg=cfg) if auto_continue else None
    return {"status": "APPROVED", "project": st, "run": run_info}


# ============================================================
# 6개 서브에이전트 단계 실행 구현
# ============================================================
def _run_stage1_topic_outline(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from fetch_scholar import search_openalex_papers
    from smc_kg_bridge import run_gap_check

    pid = state["project_id"]
    sid = "stage1_topic_outline"
    _update_stage(state, sid, cfg, status="RUNNING", progress=15, started_at=utc_now_iso(), current_action="초기 로컬 RAG 및 최신 학술 동향 선조회 중...", error="")
    append_event(pid, "outline-architect", sid, f"1단계 시작: 《{state['topic_ko']}》 초기 탐색 + OpenAI/Gemma 목차·요약·키워드 설계", cfg=cfg)

    # 1) 초기 RAG 선조회 + 학술 타이틀 3~5편 스캔 (목차의 최신성 확보)
    kws = list(dict.fromkeys((state.get("keywords_ko") or []) + (state.get("keywords_en") or [])))[:10]
    gap_out = Path(state["workspace_dir"]) / "reports" / "kg_gap_report.json"
    gap = run_gap_check(topic=state["topic_ko"], terms=kws, out_path=gap_out, cfg=cfg)
    preview_lines = [f"- 기존 로컬 RAG 재활용률: {gap.get('reuse_ratio_percent', 0)}%"]
    try:
        q_en = " ".join((state.get("keywords_en") or [state.get("topic_en", "")])[:3])
        init_papers = search_openalex_papers(query=q_en, limit=4, scope="all", sort="relevance_score:desc")
        for p in init_papers[:4]:
            preview_lines.append(f"- 최신 문헌: {p.get('title','')} ({p.get('year','-')}, {p.get('journal','')})")
    except Exception:
        pass

    _update_stage(state, sid, cfg, progress=55, current_action="OpenAI API(또는 Gemma 4)로 목차 · 단원 요약 · 핵심 영역별 키워드 초안 생성 중...")
    outline, engine_used = _generate_outline_proposal(state, cfg, initial_context="\n".join(preview_lines))
    master_path = _save_outline_files(state, outline, cfg)

    state["outline_approved"] = False
    _update_stage(
        state,
        sid,
        cfg,
        status="WAITING_REVIEW",
        progress=90,
        current_action=f"초안 완성 ({engine_used}, {len(outline['parts'])}부 {state['chapter_count']}장) — 검토·재요청 후 [✅ 목차 확정]을 눌러주세요",
        metrics={
            "parts": len(outline["parts"]),
            "chapters": state["chapter_count"],
            "domains": len(outline.get("domain_keywords") or []),
            "engine": engine_used,
            "approved": False,
        },
        artifacts=[str(master_path), str(gap_out)],
    )
    append_event(pid, "outline-architect", sid, f"목차·요약·영역별 키워드 초안 제시 완료({engine_used}) — 사용자 검토 및 확정 대기 중", cfg=cfg)


def _run_stage2_source_collect(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from fetch_project_sources import collect_project_sources

    pid = state["project_id"]
    sid = "stage2_source_collect"
    collected_dir = cfg.project_collected_dir(pid)
    _update_stage(state, sid, cfg, status="RUNNING", progress=8, started_at=utc_now_iso(), current_action="확정 키워드 기반 문헌·교과서·교재·웹사이트 4계층 분리 수집 시작...", error="")
    append_event(pid, "web-scout", sid, f"2단계 시작: 확정 키워드({len(state.get('keywords_ko',[]))}개) 기반 자료 수집 → {collected_dir}", cfg=cfg)

    opts = state.get("options", {})
    limit = int(opts.get("papers_per_query", 5))

    def _on_progress(pct: int, action: str, msg: str, level: str = "INFO") -> None:
        _update_stage(state, sid, cfg, progress=min(92, max(8, pct)), current_action=action)
        append_event(pid, "web-scout", sid, msg, level=level, cfg=cfg)

    res = collect_project_sources(
        project_id=pid,
        topic_ko=state["topic_ko"],
        topic_en=state.get("topic_en", ""),
        keywords_ko=state.get("keywords_ko", []),
        keywords_en=state.get("keywords_en", []),
        packet_id=state["packet_id"],
        papers_per_query=limit,
        domestic_agency_urls=opts.get("domestic_agency_urls") or [],
        international_agency_urls=opts.get("international_agency_urls") or [],
        download_oa_pdf=bool(opts.get("download_oa_pdf", True)),
        max_pdf_downloads=4,
        progress_cb=_on_progress,
        cfg=cfg,
    )
    manifest = res["manifest"]
    bd = manifest["breakdown"]
    state["collected_dir"] = manifest["collected_root"]
    state["e_evidence_dir"] = str(cfg.project_e_evidence_dir(pid))
    state["collection_manifest_path"] = res["manifest_path"]
    state["collection_breakdown"] = {**bd, "total": manifest["total_collected"]}
    state["collected_sources"] = manifest["sources"]
    save_project_state(state, cfg)

    _update_stage(state, sid, cfg, progress=95, current_action="2단계 자료 수집 현황 보고서(02_collection_report.md) 작성 중...")
    rep_md = _write_stage2_report(state, cfg)
    append_event(pid, "web-scout", sid, f"2단계 자료 수집 현황 보고서 생성 완료: {rep_md.name} (총 {manifest['total_collected']}건)", cfg=cfg)
    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"자료 수집 완료 총 {manifest['total_collected']}건 · 현황 보고서 생성 완료",
        metrics={
            "total_collected": manifest["total_collected"],
            "01_국내기관": bd["domestic_agencies"],
            "02_국내학회": bd["domestic_journals"],
            "03_해외기관": bd["international_agencies"],
            "04_국제SCI": bd["international_journals"],
            "report": rep_md.name,
        },
        artifacts=[str(rep_md), res["manifest_path"], res["index_md_path"]],
    )


def _run_stage3_kg_build(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from build_platform_kg import build_knowledge_graph_from_sources

    pid = state["project_id"]
    sid = "stage3_kg_build"
    _update_stage(state, sid, cfg, status="RUNNING", progress=15, started_at=utc_now_iso(), current_action="2단계 수집 자료 기반 지식그래프 증분 구축 준비 중...", error="")

    proj_source_ids = [s["source_id"] for s in state.get("collected_sources", []) if s.get("source_id")]
    kg_model = state.get("options", {}).get("kg_model") or cfg.ollama_fast_model
    append_event(pid, "kg-builder", sid, f"3단계 시작: 수집 자료 {len(proj_source_ids)}건 → C:\\SMC_GRAPHRAG 증분 구축 (기존 graph.json 무훼손)", cfg=cfg)
    _update_stage(state, sid, cfg, progress=40, current_action=f"로컬 {kg_model}로 {len(proj_source_ids)}건 엔티티·관계 추출 중...")

    res = build_knowledge_graph_from_sources(source_ids=proj_source_ids or None, model=kg_model, cfg=cfg)
    nodes_added = res.get("nodes_after", 0) - res.get("nodes_before", 0)
    edges_added = res.get("edges_after", 0) - res.get("edges_before", 0)
    metrics = {
        "project_sources": len(proj_source_ids),
        "newly_ingested": res.get("sources_processed", 0),
        "nodes_added": nodes_added,
        "edges_added": edges_added,
        "nodes_after": res.get("nodes_after", 0),
        "edges_after": res.get("edges_after", 0),
    }

    rep_json = Path(state["workspace_dir"]) / "reports" / "kg_ingest_report.json"
    rep_json.write_text(json.dumps({"project_id": pid, **res}, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_stage(state, sid, cfg, progress=92, current_action="3단계 지식그래프 구축 보고서(03_kg_report.md) 작성 중...")
    rep_md = _write_stage3_report(state, metrics, cfg)

    append_event(pid, "kg-builder", sid, f"3단계 지식그래프 구축 & 보고서 완료: 노드 +{nodes_added} / 관계 +{edges_added}", cfg=cfg)
    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"KG 증분 완료 (노드 +{nodes_added} / 관계 +{edges_added}) · 보고서 생성 완료",
        metrics={**metrics, "report": rep_md.name},
        artifacts=[str(rep_md), str(rep_json), str(cfg.smc_incremental_graph_path)],
    )


def _run_stage4_manuscript_draft(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from clean_manuscripts import _clean_single_chapter
    from local_gemma import LocalGemmaClient
    from verify_citations import verify_target

    pid = state["project_id"]
    sid = "stage4_manuscript_draft"
    _update_stage(state, sid, cfg, status="RUNNING", progress=5, started_at=utc_now_iso(), current_action="확정 목차 및 근거 패킷 로드 중...", error="")

    bp_dir = Path(state["workspace_dir"]) / "blueprints"
    ch_dir = Path(state["workspace_dir"]) / "chapters"
    rep_dir = Path(state["workspace_dir"]) / "reports"
    ch_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    master_p = bp_dir / "master_outline.yaml"
    if not master_p.is_file():
        raise FileNotFoundError("1단계 마스터 청사진(master_outline.yaml)이 아직 생성되지 않았습니다.")
    master = yaml.safe_load(master_p.read_text(encoding="utf-8"))
    all_chapters = [c for pt in master.get("parts", []) for c in pt.get("chapters", [])]
    limit_n = int(state.get("options", {}).get("draft_chapter_limit") or 0)
    target_chapters = all_chapters[:limit_n] if limit_n > 0 else all_chapters

    pkt_path = cfg.evidence_dir / f"{state['packet_id']}.json"
    pkt = json.loads(pkt_path.read_text(encoding="utf-8")) if pkt_path.is_file() else {"sources": []}
    sources = pkt.get("sources", [])
    valid_ids = [s["source_id"] for s in sources if s.get("source_id")]
    digest_lines = [
        f"[{s['source_id']}] {s.get('title', '')} — {' '.join(c.get('text', '') for c in (s.get('chunks') or [])[:2])[:420]}"
        for s in sources[:12]
    ]
    digest = "\n".join(digest_lines) or f"주제: {state['topic_ko']}"

    completed_chs: set[str] = set(state.setdefault("checkpoint", {}).get("completed_chapters") or [])
    gemma_model = state.get("options", {}).get("gemma_model") or cfg.ollama_fast_model
    client = LocalGemmaClient(cfg)

    total_n = max(1, len(target_chapters))
    for idx, ch in enumerate(target_chapters, 1):
        cid = ch["chapter_id"]
        out_mdx = ch_dir / f"{cid}.mdx"
        if cid in completed_chs and out_mdx.is_file():
            append_event(pid, "domain-drafter", sid, f"[{cid}] 기존 완료 체크포인트 유지 → 건너뜀 ({idx}/{total_n})", cfg=cfg)
            continue

        if _should_stop(pid):
            _update_stage(
                state,
                sid,
                cfg,
                status="INTERRUPTED",
                progress=int((len(completed_chs) / total_n) * 90),
                current_action=f"사용자 중단 — {len(completed_chs)}/{total_n}장 체크포인트 저장 완료 (이어하기 가능)",
                metrics={"completed_chapters": len(completed_chs), "total_chapters": total_n},
            )
            return

        pct = 10 + int(((idx - 1) / total_n) * 78)
        _update_stage(state, sid, cfg, progress=pct, current_action=f"[{idx}/{total_n}] {cid} ({ch['title'][:32]}) 집필 중...")
        append_event(pid, "domain-drafter", sid, f"단원 집필 시작 [{cid}] {ch['title']} (모델: {gemma_model})", cfg=cfg)

        secs = ch.get("sections") or [f"{idx}.1 개요", f"{idx}.2 핵심 원리", f"{idx}.3 현장 적용"]
        sys_prompt = (
            "당신은 전문 분야 대학교재 수석 저자입니다.\n"
            f"1. 모든 사실·수치 문장 끝에 제공된 출처 키({', '.join(valid_ids[:15]) if valid_ids else '근거'})만 부착하십시오.\n"
            "2. 원소기호·화학식·첨자는 LaTeX($...$) 대신 일반 유니코드/HTML(예: CO₂, NH₄⁺, θ<sub>opt</sub>)로 작성하십시오.\n"
            "3. 본문 절(##), ## 핵심 용어집 (표), ## 이해도 점검 연습문제 및 해설 (문제 3문항과 각 문제 직하단 정답·상세 풀이 1:1 연결), "
            "## 오해와 진실: 현장·이론 핵심 오해 교정 (오해 3개 이상)을 모두 작성하십시오."
        )
        user_prompt = (
            f"단원 제목: {ch['title']}\n단원 요약: {ch.get('summary_ko', '')}\n필수 절: {', '.join(secs)}\n"
            f"대상 독자: {state['target_audience']}\n\n[검증 근거 패킷]\n{digest}\n\n"
            "위 근거를 바탕으로 풍부하고 학술적인 한국어 단원 원고를 작성하세요."
        )
        try:
            draft_body = client.draft_text(
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                model=gemma_model,
                think=False,
                num_predict=4096,
                timeout=240,
            )
        except Exception as exc:
            append_event(pid, "domain-drafter", sid, f"[{cid}] Ollama 폴백 템플릿 적용: {exc}", level="WARN", cfg=cfg)
            c_tag = f"[{valid_ids[0]}]" if valid_ids else ""
            draft_body = (
                f"# {ch['title']}\n\n> **단원 요약:** {ch.get('summary_ko') or state['topic_ko']}\n\n"
                + "\n\n".join(f"## {sec}\n\n본 절에서는 {ch['title']}의 핵심 원리와 정량 기준을 다룬다 {c_tag}." for sec in secs)
                + f"\n\n## 이해도 점검 연습문제 및 해설\n\n### 문제 1\n\n{ch['title']}의 핵심 관리 원칙으로 옳은 것은?\n① 1차 근거 기반 정량 관리 {c_tag}\n② 임의 추정\n\n"
                f"#### ▶ 문제 1 정답 및 상세 풀이\n\n**정답: ①** — 실측 데이터와 근거 패킷에 기반한 정량 관리가 필수적이다 {c_tag}.\n\n"
                f"## 오해와 진실: 현장·이론 핵심 오해 교정\n\n### 오해 {idx}-1. 단일 지표만으로 충분하다\n"
                f"- **오해 (Myth):** 단일 지표만 보면 전체 생육을 판단할 수 있다.\n"
                f"- **진실 (Fact):** 기상·토양·작물 생리 지표를 통합 해석해야 한다 {c_tag}.\n"
                f"- **현장 교정 포인트:** 다중 센서 및 정량 기준표를 병행 적용한다 {c_tag}.\n"
            )

        ref_lines = ["", "## 참고문헌 및 근거 출처 목록", "", "| 출처 ID | 유형 | 제목 | URL | 라이선스 |", "| :--- | :--- | :--- | :--- | :--- |"]
        for s in sources:
            ref_lines.append(f"| `{s.get('source_id','')}` | {s.get('source_type','web')} | {str(s.get('title','')).replace('|','/')} | {s.get('url','')} | {s.get('license_note','')} |")

        fm = f'---\nchapter_id: "{cid}"\ntitle: "{ch["title"]}"\naudience: "{state["target_audience"]}"\nevidence_packet: "{state["packet_id"]}.json"\n---\n\n'
        if not draft_body.lstrip().startswith("# "):
            draft_body = f"# {ch['title']}\n\n" + draft_body
        full_mdx, _ = _clean_single_chapter(fm + draft_body.strip() + "\n" + "\n".join(ref_lines) + "\n")
        out_mdx.write_text(full_mdx, encoding="utf-8")

        completed_chs.add(cid)
        state["checkpoint"]["completed_chapters"] = sorted(completed_chs)
        save_project_state(state, cfg)
        append_event(pid, "domain-drafter", sid, f"체크포인트 저장 [{cid}] 완료 ({len(full_mdx):,}자, 누적 {len(completed_chs)}/{total_n}장)", cfg=cfg)

    # 전수 인용·수식 감사
    _update_stage(state, sid, cfg, progress=92, current_action="전 단원 인용 무결성·원문 복사율 감사 실행 중...")
    audit = verify_target(ch_dir, cfg=cfg)
    audit_path = rep_dir / "audit_latest.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    crit = len(audit.get("critical_errors", []))
    warns = len(audit.get("warnings", []))

    if state.get("options", {}).get("use_claude_review"):
        sample_chs = sorted(ch_dir.glob("*.mdx"))[:2]
        if sample_chs:
            excerpt = "\n\n---\n\n".join(p.read_text(encoding="utf-8", errors="ignore")[:3000] for p in sample_chs)
            ok_cr, cr_txt = _run_claude_code_stream(
                project_id=pid,
                agent_name="citation-auditor",
                stage_id=sid,
                prompt=f"원고 감사 결과(status={audit['status']}, crit={crit})와 아래 발췌를 한국어 8줄 이내로 정밀 검수해 주세요.\n\n{excerpt}",
                cfg=cfg,
            )
            if ok_cr and cr_txt:
                (rep_dir / "claude_audit_review.md").write_text(cr_txt, encoding="utf-8")

    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"{len(completed_chs)}개 단원 집필·정제 및 감사({audit['status']}, 치명오류 {crit}건) 완료",
        metrics={"completed_chapters": len(completed_chs), "total_chapters": total_n, "audit_status": audit["status"], "critical_errors": crit, "warnings": warns},
        artifacts=[str(audit_path)] + [str(ch_dir / f"{c}.mdx") for c in sorted(completed_chs)[:5]],
    )


def _run_stage5_visuals_generate(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from visual_studio import generate_project_visuals

    pid = state["project_id"]
    sid = "stage5_visuals_generate"
    opts = state.get("options", {})
    per_ch = max(10, int(opts.get("visuals_per_chapter") or 10))
    use_fal = bool(opts.get("use_fal_ai", False))
    fal_model = opts.get("fal_model") or "fal-ai/nano-banana"
    use_nb = bool(opts.get("use_nano_banana", True))

    _update_stage(
        state,
        sid,
        cfg,
        status="RUNNING",
        progress=5,
        started_at=utc_now_iso(),
        current_action=f"단원당 {per_ch}개 시각화 제작 시작 (fal.ai={'ON' if use_fal else 'OFF'} / 나노바나나={'ON' if use_nb else 'OFF'})...",
        error="",
    )
    append_event(pid, "visual-artist", sid, f"5단계 시작: 단원당 {per_ch}개 시각화 (fal.ai={use_fal} [{fal_model}], 나노바나나={use_nb})", cfg=cfg)

    bp_path = Path(state["workspace_dir"]) / "blueprints" / "master_outline.yaml"
    master = yaml.safe_load(bp_path.read_text(encoding="utf-8")) if bp_path.is_file() else {"parts": []}
    all_chapters = [c for pt in master.get("parts", []) for c in pt.get("chapters", [])]
    # 집필 완료된 단원 우선, 없으면 청사진 단원 대상
    ch_dir = Path(state["workspace_dir"]) / "chapters"
    drafted_ids = {p.stem for p in ch_dir.glob("*.mdx")}
    target_chs = [c for c in all_chapters if c.get("chapter_id") in drafted_ids] or all_chapters[:3]

    done_vis: set[str] = set(state.setdefault("checkpoint", {}).get("completed_visuals") or [])

    def _on_item(rec: dict[str, Any], idx: int, total: int) -> None:
        done_vis.add(rec["figure_id"])
        state["checkpoint"]["completed_visuals"] = sorted(done_vis)
        pct = min(98, max(5, int((idx / max(1, total)) * 98)))
        _update_stage(state, sid, cfg, progress=pct, current_action=f"시각화 생성 [{idx}/{total}] {rec['figure_id']} ({rec['engine']})")
        if idx <= 10 or idx % 5 == 0 or idx == total:
            append_event(pid, "visual-artist", sid, f"시각화 완료 [{idx}/{total}] {rec['title_ko'][:60]} ({rec['engine']})", cfg=cfg)

    res = generate_project_visuals(
        project_id=pid,
        topic_ko=state["topic_ko"],
        topic_en=state.get("topic_en", ""),
        chapters=target_chs,
        per_chapter_count=per_ch,
        use_fal_ai=use_fal,
        fal_model=fal_model,
        use_nano_banana=use_nb,
        completed_ids=done_vis,
        on_item_done=_on_item,
        should_stop=lambda: _should_stop(pid),
        cfg=cfg,
    )
    state["checkpoint"]["completed_visuals"] = res["completed_visual_ids"]
    save_project_state(state, cfg)

    if res["status"] == "INTERRUPTED":
        _update_stage(
            state,
            sid,
            cfg,
            status="INTERRUPTED",
            current_action=f"사용자 중단 — 시각화 {res['total_generated']}/{res['total_planned']}종 체크포인트 저장 완료 (이어하기 가능)",
            metrics={"generated": res["total_generated"], "planned": res["total_planned"], "ai_images": res["ai_images_count"], "svg_charts": res["svg_charts_count"]},
        )
        return

    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"시각화 총 {res['total_generated']}종 제작 완료 (단원당 {per_ch}개 · 실사/AI {res['ai_images_count']} + SVG {res['svg_charts_count']})",
        metrics={
            "total_visuals": res["total_generated"],
            "per_chapter": per_ch,
            "ai_images": res["ai_images_count"],
            "svg_charts": res["svg_charts_count"],
            "fal_ai": use_fal,
        },
        artifacts=[res["manifest_path"], res["guide_path"]],
    )


def _run_stage6_publish_report(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from build_outputs import (
        _load_all_sources_map,
        _parse_frontmatter,
        build_curriculum,
        build_executive_report,
        build_interactive_web,
        build_textbook,
    )

    pid = state["project_id"]
    sid = "stage6_publish_report"
    _update_stage(state, sid, cfg, status="RUNNING", progress=15, started_at=utc_now_iso(), current_action="교재·교과서·보고서·네이버 블로그 HTML 출판 및 E:\\ 미러링 중...", error="")

    ch_dir = Path(state["workspace_dir"]) / "chapters"
    exp_root = Path(state["workspace_dir"]) / "exports"
    exp_root.mkdir(parents=True, exist_ok=True)
    e_proj_exp = cfg.project_e_exports_dir(pid)
    e_proj_exp.mkdir(parents=True, exist_ok=True)
    sources_map = _load_all_sources_map(cfg)

    built_files: list[str] = []
    outputs_map: dict[str, str] = {}
    ch_files = sorted(ch_dir.glob("*.mdx"))
    pub_done: set[str] = set(state.setdefault("checkpoint", {}).get("published_chapters") or [])

    for idx, p in enumerate(ch_files, 1):
        if _should_stop(pid):
            _update_stage(state, sid, cfg, status="INTERRUPTED", current_action=f"출판 중단 ({len(pub_done)}/{len(ch_files)}장 완료 — 이어하기 가능)")
            return
        cid = p.stem
        meta, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
        out_dir = exp_root / cid
        out_dir.mkdir(parents=True, exist_ok=True)

        build_textbook(cid, meta, body, out_dir)
        build_curriculum(cid, meta, body, out_dir)
        build_executive_report(cid, meta, body, out_dir)
        r_wb = build_interactive_web(cid, meta, body, sources_map, out_dir)

        e_ch = e_proj_exp / cid
        e_ch.mkdir(parents=True, exist_ok=True)
        for f in out_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, e_ch / f.name)
                built_files.append(str(f))

        outputs_map[f"{cid}_textbook_pdf"] = f"/project-files/{pid}/exports/{cid}/{cid}_textbook.pdf"
        outputs_map[f"{cid}_report_docx"] = f"/project-files/{pid}/exports/{cid}/{cid}_report.docx"
        outputs_map[f"{cid}_naver_web"] = f"/project-files/{pid}/exports/{cid}/{cid}_interactive.html"
        outputs_map[f"{cid}_naver_pure"] = f"/project-files/{pid}/exports/{cid}/{cid}_naver_blog.html"
        pub_done.add(cid)
        state["checkpoint"]["published_chapters"] = sorted(pub_done)
        _update_stage(state, sid, cfg, progress=20 + int((idx / max(1, len(ch_files))) * 68), current_action=f"{cid} 4종 멀티포맷 + 네이버 블로그 HTML 출판 완료")
        append_event(pid, "book-publisher", sid, f"{cid} 출판 완료 (해시태그 20개 소단원 {r_wb.get('subsections_with_20_hashtags')}곳)", cfg=cfg)

    state["outputs"] = outputs_map
    # 표지(Cover) · 머리말 · 전체 목차(TOC) 페이지 자동 생성 및 산출물 연결
    try:
        from build_cover_toc import build_project_cover_and_toc

        fm_res = build_project_cover_and_toc(pid, cfg=cfg)
        for k, u in (fm_res.get("files") or {}).items():
            outputs_map[f"00_cover_toc_{k}"] = u
        built_files.extend([str(Path(fm_res["local_dir"]) / f"cover_and_toc.{ext}") for ext in ("html", "pdf", "docx", "md") if (Path(fm_res["local_dir"]) / f"cover_and_toc.{ext}").is_file()])
        append_event(pid, "book-publisher", sid, f"표지 · 머리말 · 전체 목차 페이지({fm_res['chapter_count']}장) 생성 완료", cfg=cfg)
    except Exception as exc:
        append_event(pid, "book-publisher", sid, f"표지·목차 생성 경고: {exc}", level="WARN", cfg=cfg)
    state["outputs"] = outputs_map
    save_project_state(state, cfg)

    _update_stage(state, sid, cfg, progress=94, current_action="6단계 교재 생성 완료 종합 보고서(06_final_book_report.md) 작성 중...")
    rep_md = _write_stage6_report(state, {"published_files": len(built_files)}, cfg)
    append_event(pid, "book-publisher", sid, f"6단계 교재 생성 완료 종합 보고서 작성 완료: {rep_md.name}", cfg=cfg)
    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"최종 출판({len(built_files)}개 파일) 및 교재 완료 보고서 생성 완료",
        metrics={"published_files": len(built_files), "chapters_published": len(ch_files), "report": rep_md.name},
        artifacts=[str(rep_md)] + built_files[:6],
    )


STAGE_RUNNERS = {
    "stage1_topic_outline": _run_stage1_topic_outline,
    "stage2_source_collect": _run_stage2_source_collect,
    "stage3_kg_build": _run_stage3_kg_build,
    "stage4_manuscript_draft": _run_stage4_manuscript_draft,
    "stage5_visuals_generate": _run_stage5_visuals_generate,
    "stage6_publish_report": _run_stage6_publish_report,
}


def _worker_loop(project_id: str, stage_ids: list[str], cfg: PlatformConfig) -> None:
    stop_ev = _STOP_FLAGS.setdefault(project_id, threading.Event())
    stop_ev.clear()

    state = load_project_state(project_id, cfg)
    if not state:
        return
    state["overall_status"] = "RUNNING"
    save_project_state(state, cfg)

    try:
        for sid in stage_ids:
            if stop_ev.is_set():
                state["overall_status"] = "INTERRUPTED"
                state["active_stage_id"] = None
                save_project_state(state, cfg)
                append_event(project_id, "orchestrator", sid, "사용자 요청으로 중단(체크포인트 저장 완료 — 이어하기 가능)", level="WARN", cfg=cfg)
                return

            # 1단계 미승인 상태에서 2단계 이후 진입 차단 (검토 게이트)
            if sid != "stage1_topic_outline" and not state.get("outline_approved", False):
                state["overall_status"] = "WAITING_REVIEW"
                state["active_stage_id"] = None
                save_project_state(state, cfg)
                append_event(project_id, "orchestrator", sid, "1단계 목차·키워드 확정 대기 중입니다. 검토 후 [✅ 목차 확정]을 눌러주세요.", level="WARN", cfg=cfg)
                return

            state["active_stage_id"] = sid
            save_project_state(state, cfg)
            runner = STAGE_RUNNERS[sid]
            try:
                runner(state, cfg)
            except Exception as exc:
                _update_stage(
                    state,
                    sid,
                    cfg,
                    status="ERROR",
                    finished_at=utc_now_iso(),
                    current_action=f"오류 발생(체크포인트 보존): {str(exc)[:140]}",
                    error=str(exc),
                )
                state["overall_status"] = "ERROR"
                state["active_stage_id"] = None
                save_project_state(state, cfg)
                append_event(project_id, "orchestrator", sid, f"단계 실행 오류: {exc}", level="ERROR", cfg=cfg)
                return

            # 1단계 완료 직후 사용자 검토 게이트에서 자동 대기
            cur_stage = next((s for s in state["stages"] if s["stage_id"] == sid), {})
            if cur_stage.get("status") == "WAITING_REVIEW":
                state["overall_status"] = "WAITING_REVIEW"
                state["active_stage_id"] = None
                save_project_state(state, cfg)
                return
            if cur_stage.get("status") == "INTERRUPTED":
                state["overall_status"] = "INTERRUPTED"
                state["active_stage_id"] = None
                save_project_state(state, cfg)
                return
            time.sleep(0.15)

        all_done = all(s["status"] == "DONE" for s in state["stages"])
        state["overall_status"] = "DONE" if all_done else "PAUSED"
        state["active_stage_id"] = None
        save_project_state(state, cfg)
        if all_done:
            append_event(project_id, "orchestrator", "complete", f"《{state['topic_ko']}》 6단계 교재 제작 파이프라인 전체 완료!", cfg=cfg)
    finally:
        _ACTIVE_THREADS.pop(project_id, None)


def start_pipeline_async(
    project_id: str,
    *,
    mode: str = "all",
    target_stage: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """백그라운드 워커에서 순차/이어하기(all | resume | next | single)를 시작한다."""
    cfg = cfg or get_config()
    state = load_project_state(project_id, cfg)
    if not state:
        raise FileNotFoundError(f"Project not found: {project_id}")

    t_existing = _ACTIVE_THREADS.get(project_id)
    if t_existing and t_existing.is_alive():
        return {"status": "ALREADY_RUNNING", "project_id": project_id, "active_stage_id": state.get("active_stage_id")}

    if mode == "single" and target_stage:
        if target_stage not in STAGE_RUNNERS:
            raise ValueError(f"Unknown stage_id: {target_stage}")
        stage_ids = [target_stage]
    elif mode == "next":
        nxt = next((s["stage_id"] for s in state["stages"] if s["status"] != "DONE"), None)
        stage_ids = [nxt] if nxt else []
    else:  # all / resume
        stage_ids = [s["stage_id"] for s in state["stages"] if s["status"] != "DONE"]

    if not stage_ids:
        return {"status": "ALREADY_DONE", "project_id": project_id}

    th = threading.Thread(target=_worker_loop, args=(project_id, stage_ids, cfg), daemon=True)
    _ACTIVE_THREADS[project_id] = th
    th.start()
    return {"status": "STARTED", "project_id": project_id, "queued_stages": stage_ids}


def stop_pipeline(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    ev = _STOP_FLAGS.get(project_id)
    if ev:
        ev.set()
    return {"status": "STOP_REQUESTED", "project_id": project_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="6단계 전문 교재 제작 오케스트레이터")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="프로젝트 목록 조회")

    p_c = sub.add_parser("create", help="신규 교재 주제 프로젝트 생성")
    p_c.add_argument("--topic", required=True)
    p_c.add_argument("--topic-en", default="")
    p_c.add_argument("--keywords", default="")
    p_c.add_argument("--keywords-en", default="")
    p_c.add_argument("--pages", type=int, default=500)
    p_c.add_argument("--chapters", type=int, default=15)

    p_r = sub.add_parser("run", help="지정 프로젝트 순차/이어하기 실행 (동기)")
    p_r.add_argument("--project-id", required=True)
    p_r.add_argument("--stage", default="")

    args = parser.parse_args()
    cfg = get_config()

    if args.cmd == "list":
        print(json.dumps(list_projects(cfg), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "create":
        st = create_project(
            topic_ko=args.topic,
            topic_en=args.topic_en,
            keywords_ko=[x.strip() for x in args.keywords.split(",") if x.strip()],
            keywords_en=[x.strip() for x in args.keywords_en.split(",") if x.strip()],
            target_pages=args.pages,
            chapter_count=args.chapters,
            cfg=cfg,
        )
        print(json.dumps({"project_id": st["project_id"], "workspace_dir": st["workspace_dir"]}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "run":
        st = load_project_state(args.project_id, cfg)
        if not st:
            print("Project not found", file=sys.stderr)
            return 1
        sids = [args.stage] if args.stage else [s["stage_id"] for s in st["stages"] if s["status"] != "DONE"]
        _worker_loop(args.project_id, sids, cfg)
        print(json.dumps(load_project_state(args.project_id, cfg), ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
