"""6단계 전문 교재 제작 오케스트레이터 (단일 통합 대시보드 · 체크포인트 이어하기 · 보고서 자동 생성).

새로운 표준 제작 절차 (6단계):
  1단계 [stage1_topic_outline]    : 주제 설정 → 초기 RAG/학술 탐색 + Google Gemini API(또는 Gemma 4)로
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
        "tier": "초기 검색 + Google Gemini API / 로컬 Gemma 4 + 사용자 검토·재요청",
        "description": "주제를 바탕으로 초기 탐색과 Google Gemini API를 활용해 목차·단원 요약·핵심 영역별 키워드를 제시하고 사용자 검토·수정 후 확정합니다.",
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
        "title": "시각화 자료 제작 (주장·내용 기반 3~6장)",
        "short_title": "시각화(내용 기반)",
        "tier": "실데이터 matplotlib 300 DPI · 내용 기반 도해 · AI 실사+Pillow 라벨",
        "description": "원고의 핵심 주장과 검증 데이터에 기반해 단원당 3~6장의 학술 차트·도해·실사를 생성하고 시각 QA 검수를 수행합니다.",
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


def _last_work_path(project_ws: Path) -> Path:
    return project_ws / "last_work_session.json"


def build_last_work_summary(
    state: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트의 마지막 작업 상태(탭·단계·열람 단원·마지막 실행 내용·체크포인트)를 요약 객체로 생성한다."""
    prev = dict(state.get("last_work_session") or {})
    ov = {k: v for k, v in (overrides or {}).items() if v is not None}
    stages = state.get("stages") or []

    active_st = None
    if ov.get("last_stage_id"):
        active_st = next((s for s in stages if s.get("stage_id") == ov["last_stage_id"]), None)
    if not active_st and state.get("active_stage_id"):
        active_st = next((s for s in stages if s.get("stage_id") == state.get("active_stage_id")), None)
    if not active_st:
        active_st = (
            next((s for s in stages if s.get("status") in ("RUNNING", "WAITING_REVIEW", "INTERRUPTED", "ERROR")), None)
            or next((s for s in reversed(stages) if s.get("status") == "DONE"), None)
            or (stages[0] if stages else None)
        )

    stage_id = ov.get("last_stage_id") or prev.get("last_stage_id") or (active_st.get("stage_id") if active_st else "stage1_topic_outline")
    stage_obj = next((s for s in stages if s.get("stage_id") == stage_id), active_st) or {}
    stage_order = stage_obj.get("order", "")
    stage_title = stage_obj.get("short_title") or stage_obj.get("title") or stage_id
    stage_status = stage_obj.get("status", "PENDING")
    stage_progress = int(stage_obj.get("progress") or (100 if stage_status == "DONE" else 0))
    stage_action = stage_obj.get("current_action") or ""

    last_ev_msg = ""
    try:
        evs = load_events(state["project_id"], limit=1, cfg=cfg)
        if evs:
            last_ev_msg = str(evs[-1].get("message") or "")
    except Exception:
        pass

    done_cnt = sum(1 for s in stages if s.get("status") == "DONE")
    ck = state.get("checkpoint") or {}
    auto_summary = ov.get("last_action_summary") or stage_action or last_ev_msg or f"{stage_order}단계 {stage_title} ({stage_status})"

    now_iso = utc_now_iso()
    return {
        "project_id": state["project_id"],
        "topic_ko": state.get("topic_ko", ""),
        "workspace_dir": str(state.get("workspace_dir") or ""),
        "last_tab": ov.get("last_tab") or prev.get("last_tab") or "workflow",
        "last_subtab": ov.get("last_subtab") if "last_subtab" in ov else prev.get("last_subtab", ""),
        "last_stage_id": stage_id,
        "last_stage_order": stage_order,
        "last_stage_title": stage_title,
        "last_stage_status": stage_status,
        "last_stage_progress": stage_progress,
        "last_open_chapter": ov.get("last_open_chapter") if "last_open_chapter" in ov else prev.get("last_open_chapter", ""),
        "last_visual_filter": ov.get("last_visual_filter") if "last_visual_filter" in ov else prev.get("last_visual_filter", "ALL"),
        "last_action_summary": auto_summary,
        "last_event_message": last_ev_msg,
        "done_stages": done_cnt,
        "total_stages": len(stages),
        "overall_status": state.get("overall_status", "IDLE"),
        "completed_chapters_count": len(ck.get("completed_chapters") or []),
        "completed_visuals_count": len(ck.get("completed_visuals") or []),
        "saved_at": now_iso,
        "saved_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_last_work_session(
    project_id: str,
    overrides: dict[str, Any] | None = None,
    *,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 폴더(projects/<pid>/last_work_session.json)와 state.json에 마지막 작업 기록을 영구 저장한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    session = build_last_work_summary(st, overrides=overrides, cfg=cfg)
    st["last_work_session"] = session
    save_project_state(st, cfg)
    try:
        ws = Path(st.get("workspace_dir") or cfg.project_dir(project_id))
        ws.mkdir(parents=True, exist_ok=True)
        _last_work_path(ws).write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return session


def scan_project_folders(include_archived: bool = False, cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    """워크스페이스 projects/ 폴더(및 선택 시 아카이브 폴더)를 스캔하여 폴더별 마지막 작업 기록과 진행 현황을 반환한다."""
    cfg = cfg or get_config()
    results: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    roots: list[tuple[Path, bool]] = [(cfg.workspace_root / "projects", False)]
    if include_archived:
        arch = cfg.e_data_root / "_archived_projects"
        if arch.is_dir():
            roots.append((arch, True))

    for root_dir, is_arch in roots:
        if not root_dir.is_dir():
            continue
        for p in sorted(root_dir.iterdir()):
            if not p.is_dir() or p.name.startswith(".") or p.name.startswith("_"):
                continue
            resolved = str(p.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            pid = p.name
            st = load_project_state(pid, cfg)
            lw_file = _last_work_path(p)
            lw_disk: dict[str, Any] = {}
            if lw_file.is_file():
                try:
                    lw_disk = json.loads(lw_file.read_text(encoding="utf-8"))
                except Exception:
                    lw_disk = {}

            bp_path = p / "blueprints" / "master_outline.yaml"
            bp_meta: dict[str, Any] = {}
            bp_ch_cnt = 0
            if bp_path.is_file():
                try:
                    bp_obj = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
                    bp_meta = bp_obj.get("book_metadata") or {}
                    bp_ch_cnt = sum(len(pt.get("chapters") or []) for pt in (bp_obj.get("parts") or []))
                except Exception:
                    pass

            ch_cnt_disk = len(list((p / "chapters").glob("*.mdx"))) if (p / "chapters").is_dir() else 0
            vis_cnt_disk = 0
            vp = p / "assets" / "visuals_plan.json"
            if vp.is_file():
                try:
                    vis_cnt_disk = int(json.loads(vp.read_text(encoding="utf-8")).get("total_generated") or 0)
                except Exception:
                    pass
            exp_cnt_disk = sum(1 for f in (p / "exports").rglob("*") if f.is_file()) if (p / "exports").is_dir() else 0

            # 프로젝트 폴더로 볼 수 있는 최소 흔적이 없으면 건너뜀
            if not (st or lw_disk or bp_path.is_file() or ch_cnt_disk > 0 or vis_cnt_disk > 0 or exp_cnt_disk > 0):
                continue

            lw = lw_disk or (st.get("last_work_session") if st else None) or (build_last_work_summary(st, cfg=cfg) if st else {})
            topic_ko = (st or {}).get("topic_ko") or lw.get("topic_ko") or bp_meta.get("title_ko") or pid
            done_stages = sum(1 for s in ((st or {}).get("stages") or []) if s.get("status") == "DONE")
            total_stages = len((st or {}).get("stages") or []) or len(STAGE_DEFINITIONS)
            updated_at = lw.get("saved_at") or (st or {}).get("updated_at") or datetime.fromtimestamp(p.stat().st_mtime).isoformat()

            results.append(
                {
                    "project_id": pid,
                    "folder_path": resolved,
                    "rel_folder": f"projects/{pid}" if not is_arch else str(p),
                    "is_archived": is_arch,
                    "is_registered": bool(st),
                    "hidden": bool((st or {}).get("hidden_from_list", False)),
                    "topic_ko": topic_ko,
                    "target_pages": int((st or {}).get("target_pages") or bp_meta.get("target_total_pages") or bp_meta.get("target_pages") or 0),
                    "chapter_count": int((st or {}).get("chapter_count") or bp_ch_cnt or ch_cnt_disk),
                    "drafted_chapters": ch_cnt_disk,
                    "visuals_count": vis_cnt_disk,
                    "exports_count": exp_cnt_disk,
                    "done_stages": done_stages,
                    "total_stages": total_stages,
                    "overall_status": (st or {}).get("overall_status") or lw.get("overall_status") or "IDLE",
                    "updated_at": updated_at,
                    "last_work_session": lw,
                }
            )
    return sorted(results, key=lambda x: str(x.get("updated_at") or ""), reverse=True)


def load_project_from_folder(folder_path: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """지정된 프로젝트 폴더에서 프로젝트 상태와 마지막 작업 기록(last_work_session.json)을 복원·불러온다."""
    cfg = cfg or get_config()
    raw_p = Path(folder_path.strip().strip('"').strip("'"))
    if not raw_p.is_absolute():
        cand = (cfg.workspace_root / raw_p).resolve()
        if cand.is_dir():
            raw_p = cand
        else:
            cand2 = (cfg.workspace_root / "projects" / raw_p).resolve()
            if cand2.is_dir():
                raw_p = cand2
    else:
        raw_p = raw_p.resolve()

    if not raw_p.is_dir():
        raise FileNotFoundError(f"지정한 프로젝트 폴더를 찾을 수 없습니다: {folder_path}")

    pid = raw_p.name
    # 아카이브 폴더에서 선택한 경우 projects/<pid>로 안전 복원(이동/복사)
    target_ws = cfg.project_dir(pid)
    if raw_p != target_ws.resolve() and "_archived_projects" in str(raw_p):
        if not target_ws.exists():
            shutil.copytree(raw_p, target_ws)
        raw_p = target_ws.resolve()

    # 폴더 내 last_work_session.json 읽기
    lw_file = _last_work_path(raw_p)
    lw_disk: dict[str, Any] = {}
    if lw_file.is_file():
        try:
            lw_disk = json.loads(lw_file.read_text(encoding="utf-8"))
        except Exception:
            lw_disk = {}

    st = load_project_state(pid, cfg)
    if not st:
        # state.json이 없는 폴더면 디스크 자산(master_outline.yaml, chapters, assets, exports)에서 자동 재구성
        bp_path = raw_p / "blueprints" / "master_outline.yaml"
        bp_obj = yaml.safe_load(bp_path.read_text(encoding="utf-8")) if bp_path.is_file() else {}
        bp_meta = (bp_obj or {}).get("book_metadata") or {}
        parts = (bp_obj or {}).get("parts") or []
        ch_files = sorted((raw_p / "chapters").glob("*.mdx")) if (raw_p / "chapters").is_dir() else []
        ch_count = sum(len(pt.get("chapters") or []) for pt in parts) or len(ch_files) or 10

        st = create_project(
            topic_ko=lw_disk.get("topic_ko") or bp_meta.get("title_ko") or pid,
            topic_en=bp_meta.get("title_en") or pid,
            target_audience=bp_meta.get("target_audience") or "대학 전공 심화, 연구자 및 현장 실무자",
            target_pages=int(bp_meta.get("target_total_pages") or bp_meta.get("target_pages") or 400),
            chapter_count=max(3, min(24, ch_count)),
            project_id_override=pid,
            cfg=cfg,
        )
        st["workspace_dir"] = str(raw_p)
        if bp_obj and parts:
            st["blueprint_preview"] = bp_obj
            st["outline_approved"] = True
            st["stages"][0].update({"status": "DONE", "progress": 100, "current_action": f"폴더에서 목차 복원 ({len(parts)}부 {ch_count}장)"})
        if ch_files:
            st["checkpoint"]["completed_chapters"] = [f.stem for f in ch_files]
            st["stages"][3].update({"status": "DONE" if len(ch_files) >= ch_count else "INTERRUPTED", "progress": min(100, int(len(ch_files) / max(1, ch_count) * 100)), "current_action": f"폴더에서 원고 {len(ch_files)}개 장 복원"})
        vp = raw_p / "assets" / "visuals_plan.json"
        if vp.is_file():
            try:
                vdata = json.loads(vp.read_text(encoding="utf-8"))
                vids = [v.get("figure_id") for v in (vdata.get("visuals") or []) if v.get("figure_id")]
                st["checkpoint"]["completed_visuals"] = vids
                st["stages"][4].update({"status": "DONE", "progress": 100, "current_action": f"폴더에서 시각화 {len(vids)}종 복원"})
            except Exception:
                pass
        if (raw_p / "exports").is_dir() and any((raw_p / "exports").rglob("*.pdf")):
            st["stages"][5].update({"status": "DONE", "progress": 100, "current_action": "폴더에서 출판 산출물 복원"})
    else:
        st["workspace_dir"] = str(raw_p)
        if st.get("hidden_from_list"):
            st["hidden_from_list"] = False

    lw_final = lw_disk or st.get("last_work_session") or build_last_work_summary(st, cfg=cfg)
    st["last_work_session"] = lw_final
    save_project_state(st, cfg)
    try:
        _last_work_path(raw_p).write_text(json.dumps(lw_final, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    append_event(
        pid,
        "orchestrator",
        lw_final.get("last_stage_id") or "stage1_topic_outline",
        f"폴더에서 이전 프로젝트 불러오기 완료: {lw_final.get('last_action_summary') or st.get('topic_ko', pid)}",
        cfg=cfg,
    )
    return {
        "status": "LOADED",
        "project": st,
        "events": load_events(pid, limit=150, cfg=cfg),
        "last_work_session": lw_final,
    }


def save_project_state(state: dict[str, Any], cfg: PlatformConfig | None = None) -> None:
    """체크포인트 안전 보장을 위해 임시 파일 작성 후 원자적(os.replace)으로 state.json을 저장한다."""
    state["updated_at"] = utc_now_iso()
    sp = _state_path(state["project_id"], cfg)
    tmp = sp.with_suffix(".json.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with _LOCK:
        tmp.write_text(payload, encoding="utf-8")
        # Windows에서 백신·동기화 프로그램이 state.json을 잠시 잡고 있으면 os.replace가
        # [WinError 5] 액세스 거부로 실패할 수 있으므로 잠시 기다렸다가 최대 5회 재시도한다.
        last_exc: Exception | None = None
        replaced = False
        for attempt in range(5):
            try:
                os.replace(tmp, sp)
                replaced = True
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.3 * (attempt + 1))
        if not replaced:
            # 마지막 수단: 원자적 교체 대신 직접 덮어쓰기
            try:
                sp.write_text(payload, encoding="utf-8")
                try:
                    tmp.unlink()
                except OSError:
                    pass
            except Exception:
                raise last_exc if last_exc else RuntimeError("state.json 저장 실패")
    # 프로젝트 폴더 내부에도 마지막 작업 요약(last_work_session.json)을 항상 최신 동기화 (폴더 단위 불러오기 복원용)
    try:
        ws_str = state.get("workspace_dir")
        if ws_str and Path(ws_str).is_dir():
            lw = state.get("last_work_session")
            if not isinstance(lw, dict) or not lw.get("last_stage_id"):
                lw = build_last_work_summary(state, cfg=cfg)
            else:
                stages = state.get("stages") or []
                act = next((s for s in stages if s.get("stage_id") == (state.get("active_stage_id") or lw.get("last_stage_id"))), None)
                if act and act.get("current_action"):
                    lw = {
                        **lw,
                        "topic_ko": state.get("topic_ko", lw.get("topic_ko", "")),
                        "last_stage_id": act.get("stage_id", lw.get("last_stage_id")),
                        "last_stage_order": act.get("order", lw.get("last_stage_order", "")),
                        "last_stage_title": act.get("short_title") or act.get("title") or lw.get("last_stage_title", ""),
                        "last_stage_status": act.get("status", lw.get("last_stage_status", "")),
                        "last_stage_progress": int(act.get("progress") or (100 if act.get("status") == "DONE" else 0)),
                        "last_action_summary": act.get("current_action") or lw.get("last_action_summary", ""),
                        "done_stages": sum(1 for s in stages if s.get("status") == "DONE"),
                        "total_stages": len(stages),
                        "overall_status": state.get("overall_status", lw.get("overall_status", "IDLE")),
                        "saved_at": state.get("updated_at", utc_now_iso()),
                        "saved_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
            _last_work_path(Path(ws_str)).write_text(json.dumps(lw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


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
    opts.setdefault("use_gemini_outline", True)
    opts.setdefault("use_fal_ai", False)
    opts.setdefault("fal_model", "fal-ai/nano-banana")
    opts.setdefault("use_nano_banana", False)
    opts.setdefault("allow_auto_paid_ai", False)
    opts.setdefault("image_model_tier", "flash")
    opts.setdefault("visual_budget_limit_usd", 1.0)
    opts.setdefault("visual_generation_mode", "cited_and_redrawn_only" if state.get("primary_output_type") == "paper" else "hybrid_cited")
    opts.setdefault("auto_harvest_oa_assets", True)
    opts.setdefault("visuals_per_chapter", 4)
    opts.setdefault("gemma_model", cfg.ollama_llm_model)
    opts.setdefault("kg_model", cfg.ollama_fast_model)
    opts.setdefault("strict_evidence_gate", True)
    opts.setdefault("require_expert_review", True)
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


def set_project_hidden(project_id: str, hidden: bool, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """교재를 지우지 않고 대시보드 목록에서만 숨기거나 다시 보이게 한다."""
    cfg = cfg or get_config()
    state = load_project_state(project_id, cfg)
    if not state:
        raise FileNotFoundError(project_id)
    state["hidden_from_list"] = bool(hidden)
    save_project_state(state, cfg)
    return {"status": "OK", "project_id": project_id, "hidden": bool(hidden)}


def list_projects(cfg: PlatformConfig | None = None, include_hidden: bool = False) -> list[dict[str, Any]]:
    """현재 활성 관리 중인 프로젝트 목록만 반환한다 (자동 시드 재주입 없음). 숨긴 교재는 기본 제외."""
    cfg = cfg or get_config()
    out = []
    for d in sorted(_runs_root(cfg).iterdir()):
        if not d.is_dir():
            continue
        st = load_project_state(d.name, cfg)
        if st and st.get("hidden_from_list") and not include_hidden:
            continue
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
                    "hidden": bool(st.get("hidden_from_list", False)),
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
    primary_output_type: str = "textbook",
    output_profile: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    project_id_override: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    from output_type_profiles import get_output_type_spec, resolve_output_profile
    from persona_studio import resolve_project_persona

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

    resolved_profile = resolve_output_profile(primary_output_type, output_profile)
    resolved_persona = resolve_project_persona(resolved_profile["primary_output_type"], persona, cfg=cfg)
    type_spec = get_output_type_spec(primary_output_type)

    is_paper_track = (resolved_profile["primary_output_type"] == "paper")
    workflow_track = resolved_profile.get("workflow_track") or ("paper_review" if is_paper_track else resolved_profile["primary_output_type"])
    opts = {
        "use_gemini_outline": True,
        "use_fal_ai": False,
        "fal_model": "fal-ai/nano-banana",
        "use_nano_banana": False,  # 비용 누수 차단: 5단계 자동 유료 AI 기본 OFF (출처 표/그림 재작성·SVG 0원 우선)
        "allow_auto_paid_ai": False,
        "image_model_tier": "flash",  # flash(gemini-2.5-flash-image, $0.039) | pro(nano-banana-pro-preview, $0.134)
        "visual_budget_limit_usd": 0.0 if is_paper_track else 1.0,
        "visual_generation_mode": "cited_and_redrawn_only" if is_paper_track else "hybrid_cited",
        "auto_harvest_oa_assets": True,
        "visuals_per_chapter": int(resolved_profile.get("visuals_per_chapter", 2 if is_paper_track else 4)),
        "enable_naver_blog": bool(resolved_profile.get("include_naver_hashtags", not is_paper_track)),
        "enable_myths": bool(resolved_profile.get("include_myths", not is_paper_track)),
        "enable_linked_quiz": bool(resolved_profile.get("include_exercises", not is_paper_track)),
        "download_oa_pdf": True,
        "gemma_model": cfg.ollama_llm_model,
        "kg_model": cfg.ollama_fast_model,
        "strict_evidence_gate": True,
        "require_expert_review": True,
        "use_claude_review": False,
        "use_claude_blueprint": False,
        "domestic_agency_urls": [],
        "international_agency_urls": [],
        "trim_formats": type_spec.get("trim_formats", ["shinkuk", "b5", "a4"]),
        "papers_per_query": 7 if is_paper_track else 5,
        "draft_chapter_limit": 0,  # 0 = 전체 단원 순차 집필
        **(options or {}),
    }

    now = utc_now_iso()
    state = {
        "workflow_version": 3,
        "workflow_track": workflow_track,
        "project_id": pid,
        "is_reference_book": False,
        "primary_output_type": resolved_profile["primary_output_type"],
        "output_profile": resolved_profile,
        "persona": resolved_persona,
        "topic_ko": topic_ko.strip(),
        "topic_en": topic_en.strip() or topic_ko.strip(),
        "keywords_ko": kw_ko,
        "keywords_en": kw_en,
        "domain_keywords": [],
        "target_audience": (target_audience or resolved_profile.get("target_audience", "")).strip(),
        "target_pages": max(10, int(target_pages)),
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
        "use_gemini_outline",
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
# Google Gemini API (또는 Gemma 4 폴백) 목차·요약·핵심 영역별 키워드 설계기
# ============================================================
GEMINI_OUTLINE_CHAIN = [
    "gemini-3.8-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]


def _call_gemini_outline_json(
    *,
    prompt: str,
    system_prompt: str,
    api_key: str,
    model_chain: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Gemini API로 목차 JSON을 생성한다. 모델 목록을 차례로 시도하고 (결과, 사용 모델)을 돌려준다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    last_err = ""
    for mdl in model_chain or GEMINI_OUTLINE_CHAIN:
        try:
            resp = client.models.generate_content(
                model=mdl,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0.4,
                ),
            )
            txt = (resp.text or "").strip()
            txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S).strip()
            return json.loads(txt), mdl
        except Exception as exc:
            last_err = f"{mdl}: {str(exc)[:160]}"
    raise RuntimeError(f"Gemini 모델 모두 실패 ({last_err})")


def _generate_outline_proposal(
    state: dict[str, Any],
    cfg: PlatformConfig,
    feedback_prompt: str = "",
    initial_context: str = "",
) -> tuple[dict[str, Any], str]:
    """목차·요약·핵심 영역별 키워드를 생성한다. 엔진 순서: Google Gemini API → 로컬 Ollama Gemma 4."""
    n_ch = int(state.get("chapter_count") or 15)
    t_pages = int(state.get("target_pages") or 500)
    per_ch = max(15, round(t_pages / max(1, n_ch)))
    opts = state.get("options") or {}
    use_gemini = bool(opts.get("use_gemini_outline", True))
    gemini_key = resolve_api_key("GEMINI_API_KEY", None, cfg) if use_gemini else ""

    prev_outline = state.get("blueprint_preview")
    prev_summary_txt = ""
    if feedback_prompt and prev_outline and prev_outline.get("parts"):
        prev_lines = []
        for pt in prev_outline["parts"]:
            prev_lines.append(f"[{pt.get('title','')}] " + " / ".join(c.get("title", "") for c in pt.get("chapters", [])))
        prev_summary_txt = "\n[기존 목차 초안]\n" + "\n".join(prev_lines)

    from output_type_profiles import build_outline_instruction_for_type
    from persona_studio import build_outline_persona_context

    role_inst, type_guide = build_outline_instruction_for_type(state)
    persona_ctx = build_outline_persona_context(state, cfg=cfg)
    sys_prompt = (
        f"{role_inst} "
        "반드시 순수 JSON 객체만 출력하며, 선택한 1차 산출물 유형의 구조에 맞게 부(Part)/단원(Chapter)을 체계적으로 설계하고 "
        "각 단원의 상세 요약(summary_ko)과 핵심 영역별 한국어/영문 검색 키워드(domain_keywords)를 빠짐없이 제시하십시오."
        f"{persona_ctx}"
    )
    user_prompt = (
        f"{type_guide}\n\n"
        f"주제(국문): {state['topic_ko']}\n"
        f"주제(영문): {state.get('topic_en', '')}\n"
        f"초기 입력 키워드: {', '.join(state.get('keywords_ko', []))}\n"
        f"목표 분량: {t_pages}쪽 · 정확히 {n_ch}개 단원/섹션 (단원당 약 {per_ch}쪽)\n"
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

    if gemini_key:
        try:
            raw, gmodel = _call_gemini_outline_json(prompt=user_prompt, system_prompt=sys_prompt, api_key=gemini_key)
            engine_used = f"Gemini ({gmodel})"
        except Exception as exc:
            raw = None
            append_event(state["project_id"], "outline-architect", "stage1_topic_outline", f"Gemini API 호출 실패 → 로컬 Gemma 4 폴백: {exc}", level="WARN", cfg=cfg)

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
    otype_eff = state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook"
    if otype_eff == "paper":
        from output_type_profiles import enforce_paper_outline_structure

        outline = enforce_paper_outline_structure(outline, state)
        state["chapter_count"] = 5
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
    use_gemini: bool | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """1단계: 사용자의 수정·재요청 프롬프트를 반영해 목차·요약·영역별 키워드를 재생성한다."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    if use_gemini is not None:
        st.setdefault("options", {})["use_gemini_outline"] = use_gemini

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
    append_event(project_id, "outline-architect", "stage1_topic_outline", f"사용자 최종 승인 완료: {len(parts)}부 {st['chapter_count']}장 → 단원별 심층 검색·집필 준비 완료", cfg=cfg)
    run_info = None
    if auto_continue:
        from chapter_pipeline import start_chapter_pipeline_async

        run_info = start_chapter_pipeline_async(
            project_id,
            research_depth="deep",
            auto_continue_stages56=True,
            cfg=cfg,
        )
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
    append_event(pid, "outline-architect", sid, f"1단계 시작: 《{state['topic_ko']}》 초기 탐색 + Google Gemini/Gemma 목차·요약·키워드 설계", cfg=cfg)

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

    _update_stage(state, sid, cfg, progress=55, current_action="Google Gemini API(또는 Gemma 4)로 목차 · 단원 요약 · 핵심 영역별 키워드 초안 생성 중...")
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

    eff_kw_ko = list(dict.fromkeys([*(state.get("search_queries_ko") or []), *(state.get("keywords_ko") or [])]))
    eff_kw_en = list(dict.fromkeys([*(state.get("search_queries_en") or []), *(state.get("keywords_en") or [])]))
    res = collect_project_sources(
        project_id=pid,
        topic_ko=state["topic_ko"],
        topic_en=state.get("topic_en", ""),
        keywords_ko=eff_kw_ko,
        keywords_en=eff_kw_en,
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

    # 2단계 후속(0원): OA 논문 JATS XML 및 PDF에서 인용/재작성 가능한 표·CC-BY 그림 자동 색인
    harvest_summary: dict[str, Any] = {}
    if opts.get("auto_harvest_oa_assets", True):
        try:
            from source_visual_harvester import harvest_project_visual_assets

            _update_stage(state, sid, cfg, progress=92, current_action="OA 원문 표·CC-BY 그림 자동 추출(0원) 중...")
            h_res = harvest_project_visual_assets(
                pid,
                max_jats=8 if state.get("primary_output_type") == "paper" else 4,
                max_pdfs=4,
                cfg=cfg,
            )
            harvest_summary = h_res.get("summary") or {}
            state["harvested_visuals_summary"] = harvest_summary
            save_project_state(state, cfg)
            append_event(
                pid,
                "web-scout",
                sid,
                f"OA 표·그림 자동 추출 완료(0원): 표 {harvest_summary.get('tables', 0)}건(그래프화 가능 {harvest_summary.get('plottable_tables', 0)}건), CC-BY 그림 {harvest_summary.get('direct_reuse_figures', 0)}건",
                cfg=cfg,
            )
        except Exception as exc:
            append_event(pid, "web-scout", sid, f"OA 표·그림 자동 추출 생략: {exc}", level="WARN", cfg=cfg)

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
        current_action=f"자료 수집 완료 총 {manifest['total_collected']}건 · 추출 표 {harvest_summary.get('tables', 0)}건 · 보고서 생성 완료",
        metrics={
            "total_collected": manifest["total_collected"],
            "01_국내기관": bd["domestic_agencies"],
            "02_국내학회": bd["domestic_journals"],
            "03_해외기관": bd["international_agencies"],
            "04_국제SCI": bd["international_journals"],
            "harvested_tables": harvest_summary.get("tables", 0),
            "harvested_cc_figures": harvest_summary.get("direct_reuse_figures", 0),
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


def build_subsection_evidence_checked(
    sources: list[dict[str, Any]],
    query_text: str,
    cfg: PlatformConfig,
    *,
    max_chunks: int = 12,
    max_chars_per_chunk: int = 880,
    min_relevant_score: int = 2,
) -> dict[str, Any]:
    """C2/C3: 핵심 앵커 문헌을 최우선 배치하고 포털 첫 화면을 제외한 뒤, 관련도 기준을 넘는 근거 조각 수를 반환한다."""
    tokens = [t.lower() for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", query_text or "")]
    tok_set = set(tokens)

    scored_chunks: list[tuple[int, bool, int, str, str, str]] = []
    for idx_s, s in enumerate(sources):
        sid = str(s.get("source_id") or "").strip()
        if not sid:
            continue
        if s.get("citable") is False:
            continue
        is_anchor = bool(s.get("is_anchor", False))
        title = str(s.get("title") or "").strip()
        chunks = s.get("chunks") or []
        if not chunks:
            summary_txt = str(s.get("abstract") or s.get("summary") or title).strip()
            if summary_txt:
                chunks = [{"text": summary_txt}]
        chunk_cap = 8 if is_anchor else 5
        for c in chunks[:chunk_cap]:
            txt = str(c.get("text") or "").strip()
            if not txt:
                continue
            hay = (title + " " + txt).lower()
            hit_score = sum(2 if t in title.lower() else 1 for t in tok_set if t in hay)
            anchor_bonus = 500 if is_anchor else 0
            sort_score = anchor_bonus + hit_score * 10 - idx_s
            scored_chunks.append((sort_score, is_anchor, hit_score, sid, title, txt[:max_chars_per_chunk]))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    picked_lines: list[str] = []
    used_ids: list[str] = []
    per_source_cap: dict[str, int] = {}
    relevant_chunks = 0
    anchor_hits = 0
    for _, is_anchor, hit_score, sid, title, snippet in scored_chunks:
        if len(picked_lines) >= max_chunks:
            break
        cap_for_src = 4 if is_anchor else 2
        if per_source_cap.get(sid, 0) >= cap_for_src:
            continue
        if not is_anchor and hit_score < min_relevant_score:
            continue
        per_source_cap[sid] = per_source_cap.get(sid, 0) + 1
        tag_prefix = "[핵심앵커] " if is_anchor else ""
        picked_lines.append(f"[{sid}] {tag_prefix}{title}\n{snippet}")
        relevant_chunks += 1
        if is_anchor:
            anchor_hits += 1
        if sid not in used_ids:
            used_ids.append(sid)

    # C:\SMC_GRAPHRAG 통합 RAG 보강 검색 (동일 프로젝트 근거 출처 내 보강)
    try:
        from rag_capture_unifier import search_unified_rag

        rag_hits = search_unified_rag(query_text[:120], limit=4, cfg=cfg)
        existing_sids = {str(s.get("source_id")) for s in sources if s.get("source_id") and s.get("citable") is not False}
        for hit in rag_hits:
            h_sid = str(hit.get("source_id") or "").strip()
            h_snip = str(hit.get("snippet") or hit.get("content") or "").strip()[:500]
            h_title = str(hit.get("title") or "").strip()
            if h_snip and h_sid in existing_sids and per_source_cap.get(h_sid, 0) < 2:
                per_source_cap[h_sid] = per_source_cap.get(h_sid, 0) + 1
                picked_lines.append(f"[{h_sid}] (통합RAG) {h_title}\n{h_snip}")
                relevant_chunks += 1
                if h_sid not in used_ids:
                    used_ids.append(h_sid)
    except Exception:
        pass

    return {
        "text": "\n\n".join(picked_lines),
        "used_ids": used_ids,
        "relevant_chunks": relevant_chunks,
        "anchor_hits": anchor_hits,
    }


def _build_subsection_evidence_context(
    sources: list[dict[str, Any]],
    query_text: str,
    cfg: PlatformConfig,
    *,
    max_chunks: int = 12,
    max_chars_per_chunk: int = 880,
) -> tuple[str, list[str]]:
    """세부 절 제목·키워드에 맞춰 핵심 앵커 문헌 우선 + 근거 패킷에서 고밀도 관련 발췌를 조합한다."""
    res = build_subsection_evidence_checked(
        sources,
        query_text,
        cfg,
        max_chunks=max_chunks,
        max_chars_per_chunk=max_chars_per_chunk,
        min_relevant_score=1,
    )
    return res["text"], res["used_ids"]


def _dedup_leading_chapter_heading(draft_body: str, ch_title: str) -> str:
    """# 제목 직후 동일한 ## 제목이 중복 출력되는 패턴을 깔끔히 제거한다."""
    lines = draft_body.strip().splitlines()
    if len(lines) >= 2:
        norm_t = re.sub(r"\s+", "", ch_title)
        out: list[str] = []
        seen_h1 = False
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("# ") and not seen_h1:
                seen_h1 = True
                out.append(ln)
                continue
            if seen_h1 and stripped.startswith("## "):
                h2_norm = re.sub(r"\s+", "", stripped[3:])
                if h2_norm == norm_t or norm_t in h2_norm:
                    continue
            out.append(ln)
        return "\n".join(out)
    return draft_body


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
    gemma_model = state.get("options", {}).get("gemma_model") or cfg.ollama_llm_model
    strict_ev_gate = bool(state.get("options", {}).get("strict_evidence_gate", True))
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

        from agro_framework import (
            build_context_aware_sections,
            format_triples_for_prompt,
            query_kg_triples_for_chapter,
        )
        from output_type_profiles import (
            format_paper_consolidated_references,
            infer_paper_section_role,
            resolve_output_profile,
        )
        from persona_studio import (
            build_deepening_prompt,
            compile_persona_system_prompt,
            resolve_project_persona,
        )

        otype = state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook"
        is_paper = (otype == "paper")
        chapter_role = infer_paper_section_role(ch, idx, total_n) if is_paper else None
        persona = resolve_project_persona(otype, state.get("persona"), cfg=cfg)
        secs = (
            build_context_aware_sections(idx, ch["title"], ch.get("sections"))
            if otype == "textbook"
            else (ch.get("sections") or [f"{idx}.1 도입 및 배경", f"{idx}.2 핵심 내용", f"{idx}.3 적용 및 정리"])
        )

        is_fallback = False
        if is_paper and chapter_role == "references":
            # 논문·리뷰 규칙: 문서 마지막(ch05)에 전체 본문(ch01~ch04) 인용 출처만 중복 없이 단 1회 통합 수록
            cited_in_paper: list[str] = []
            seen_cites: set[str] = set()
            for prev_mdx in sorted(ch_dir.glob("*.mdx")):
                if prev_mdx.name == out_mdx.name:
                    continue
                try:
                    prev_txt = prev_mdx.read_text(encoding="utf-8")
                    for m_sid in re.findall(r"SRC-\d+", prev_txt):
                        if m_sid not in seen_cites:
                            seen_cites.add(m_sid)
                            cited_in_paper.append(m_sid)
                except Exception:
                    pass
            prof_paper = resolve_output_profile("paper", state.get("output_profile"))
            draft_body = format_paper_consolidated_references(
                sources=sources,
                cited_ids=cited_in_paper,
                citation_style=str(prof_paper.get("citation_style") or "APA 7th / 한국농학계 표준"),
                title=ch["title"],
            )
            append_event(
                pid,
                "citation-auditor",
                sid,
                f"[{cid}] 논문·리뷰 단일 통합 참고문헌 자동 편찬 완료 (본문 인용 {len(cited_in_paper)}건 기준)",
                cfg=cfg,
            )
        else:
            deep_per_sec = (
                str(persona.get("section_depth_mode") or "deep_per_section") == "deep_per_section"
                and len(secs) >= 2
                and (not is_paper or chapter_role in {"methods", "results_discussion"})
            )
            min_sub_chars = int(persona.get("min_chars_per_subsection") or (1800 if (is_paper and chapter_role == "results_discussion") else 1400))
            auto_deepen = bool(persona.get("auto_deepen_short_sections", True))

            if deep_per_sec:
                # 절별 분할 심층 집필 + 세부 절 맞춤 RAG 검색 + 기준 미달 절 자동 2차 심층 보강
                assembled_parts: list[str] = [f"# {ch['title']}"]
                prior_outline_notes: list[str] = []
                sec_failures = 0
                for s_i, sec_title in enumerate(secs, 1):
                    if _should_stop(pid):
                        _update_stage(
                            state,
                            sid,
                            cfg,
                            status="INTERRUPTED",
                            current_action=f"사용자 중단 — [{cid}] {sec_title} 집필 전 체크포인트 보존",
                        )
                        return
                    _update_stage(
                        state,
                        sid,
                        cfg,
                        progress=min(89, pct + int((s_i / max(1, len(secs))) * (78 / total_n))),
                        current_action=f"[{idx}/{total_n}] {cid} · 세부 절 ({s_i}/{len(secs)}) '{sec_title[:28]}' 심층 집필 중 ({persona['name_ko']})...",
                    )
                    from math_typography import format_equations_for_prompt

                    sec_query = f"{state['topic_ko']} {ch['title']} {sec_title} {' '.join(ch.get('keywords_ko') or [])}"
                    ev_checked = build_subsection_evidence_checked(sources, sec_query, cfg, max_chunks=12, max_chars_per_chunk=900)
                    sec_evidence = ev_checked["text"]
                    if strict_ev_gate and ev_checked["relevant_chunks"] < 3:
                        assembled_parts.append(
                            f"## {sec_title}\n\n"
                            f"> **[근거 부족 — 추가 수집 필요 (C3)]** 본 절('{sec_title}')에 대해 주제 관련도 기준을 통과한 1차 근거 조각이 "
                            f"**{ev_checked['relevant_chunks']}개(최소 3개 필요)**에 불과하여 임의 집필을 중단했습니다. "
                            f"1단계 핵심 문헌(앵커 PDF) 업로드 또는 2단계 주제별 재수집 후 이 단원을 다시 집필하십시오.\n\n"
                            f"<!-- NEED_EVIDENCE: {sec_title} 관련 1차 문헌·표준 수치·실험 데이터 최소 3건 이상 필요 -->"
                        )
                        append_event(
                            pid,
                            "domain-drafter",
                            sid,
                            f"[{cid}] C3 근거 부족 차단: '{sec_title}' (관련 근거 {ev_checked['relevant_chunks']}건 < 3건)",
                            level="WARN",
                            cfg=cfg,
                        )
                        continue
                    eq_block = format_equations_for_prompt(sec_query, limit=5)
                    kg_triples = query_kg_triples_for_chapter(
                        chapter_title=f"{ch['title']} {sec_title}",
                        chapter_text=ch.get("summary_ko", "") + " " + sec_title,
                        project_source_ids=set(valid_ids),
                        limit=12,
                        cfg=cfg,
                    )
                    kg_block = format_triples_for_prompt(kg_triples)
                    sys_prompt = compile_persona_system_prompt(
                        state,
                        valid_ids,
                        chapter_role=chapter_role,
                        subsection_title=sec_title,
                        cfg=cfg,
                    )
                    continuity_note = (
                        "\n[이미 작성된 앞 절 요약 — 아래 내용과 중복 서술 금지]\n" + "\n".join(prior_outline_notes[-3:])
                        if prior_outline_notes
                        else ""
                    )
                    extra_sec_directive = ""
                    if is_paper and chapter_role == "results_discussion":
                        is_last_res = (s_i == len(secs))
                        extra_sec_directive = (
                            "\n[학회 투고급 결과 및 고찰 세부 절 필수 논리 (C8)] 먼저 문헌 비교표(연구·작물·방법·데이터셋·정확도·출처)를 작성한 뒤 "
                            "① 정량 실증 발견, ② 생리·분자·물리화학·알고리즘 인과 기작 해석(Why/How), "
                            "③ 국내외 선행연구 비교 및 불일치 원인 규명, ④ 경계조건·민감도·트레이드오프·교란변수 분석, "
                            "⑤ 학술적 기여 및 한국 농업 현장·정책 함의를 빠짐없이 깊이 있게 논증하십시오."
                            + (" 또한 최종 세부 절이므로 ⑥ 방법론적 한계(Limitations)와 구체적 후속 연구 설계를 완결하십시오." if is_last_res else "")
                        )
                    user_prompt = (
                        f"전체 프로젝트 주제: {state['topic_ko']} ({state.get('topic_en', '')})\n"
                        f"소속 단원: {ch['title']}\n"
                        f"현재 단독 심층 집필 대상 세부 절 ({s_i}/{len(secs)}): {sec_title}\n"
                        f"단원 요약: {ch.get('summary_ko', '')}\n"
                        f"대상 독자: {state['target_audience']}\n"
                        f"{continuity_note}\n\n"
                        + (f"{eq_block}\n\n" if eq_block else "")
                        + (f"{kg_block}\n\n" if kg_block else "")
                        + f"[세부 절 맞춤 검증 근거 자료 (관련 조각 {ev_checked['relevant_chunks']}건 · 앵커 {ev_checked['anchor_hits']}건)]\n{sec_evidence}\n\n"
                        f"오직 '## {sec_title}' 절 하나에만 온전히 집중하여 단위가 있는 핵심 수치 3개 이상, 비교표 1개 이상, 대상 작물 고유 사례 1개 이상을 포함한 "
                        f"고밀도 전문 원고(보조 기준 약 {min_sub_chars:,}자)를 작성하십시오 (장 제목 '# ...'이나 다른 절, 참고문헌 표는 쓰지 마십시오)."
                        + extra_sec_directive
                    )
                    try:
                        sec_text = client.draft_text(
                            system_prompt=sys_prompt,
                            user_prompt=user_prompt,
                            model=gemma_model,
                            think=False,
                            num_predict=4096,
                            timeout=260,
                        )
                        # 분량·밀도 기준 미달 시 자동 2차 심층 보강 패스
                        if auto_deepen and len(sec_text.strip()) < int(min_sub_chars * 0.68):
                            append_event(
                                pid,
                                "domain-drafter",
                                sid,
                                f"[{cid}] '{sec_title[:26]}' 1차 초안({len(sec_text):,}자) 분량 보강 → 2차 심층 확장 실행",
                                cfg=cfg,
                            )
                            deep_prompt = build_deepening_prompt(sec_title, sec_text, sec_evidence, persona, valid_ids)
                            try:
                                expanded = client.draft_text(
                                    system_prompt=sys_prompt,
                                    user_prompt=deep_prompt,
                                    model=gemma_model,
                                    think=False,
                                    num_predict=4096,
                                    timeout=260,
                                )
                                if len(expanded.strip()) > len(sec_text.strip()) * 1.15:
                                    sec_text = expanded
                            except Exception:
                                pass
                        sec_clean = re.sub(r"^\s*#\s+[^\n]+\n*", "", sec_text.strip())
                        if not sec_clean.lstrip().startswith("## "):
                            sec_clean = f"## {sec_title}\n\n" + sec_clean
                        assembled_parts.append(sec_clean)
                        prior_outline_notes.append(f"- {sec_title}: {re.sub(r'\\s+', ' ', sec_clean)[:200]}")
                    except Exception as sec_exc:
                        sec_failures += 1
                        append_event(pid, "domain-drafter", sid, f"[{cid}] 세부 절 '{sec_title}' 집필 오류 폴백: {sec_exc}", level="WARN", cfg=cfg)
                        c_tag = f"[{valid_ids[0]}]" if valid_ids else ""
                        assembled_parts.append(f"## {sec_title}\n\n본 절에서는 {state['topic_ko']}의 {sec_title}에 관한 정량 근거와 기작 분석을 정리한다 {c_tag}.")

                if sec_failures >= len(secs):
                    is_fallback = True
                draft_body = "\n\n".join(assembled_parts)
            else:
                ch_evidence, _ = _build_subsection_evidence_context(
                    sources,
                    f"{state['topic_ko']} {ch['title']} {' '.join(secs)}",
                    cfg,
                    max_chunks=12,
                    max_chars_per_chunk=850,
                )
                ch_evidence = ch_evidence or digest
                kg_triples = query_kg_triples_for_chapter(
                    chapter_title=ch["title"],
                    chapter_text=ch.get("summary_ko", "") + " " + " ".join(secs),
                    project_source_ids=set(valid_ids),
                    limit=14,
                    cfg=cfg,
                )
                kg_block = format_triples_for_prompt(kg_triples)
                sys_prompt = compile_persona_system_prompt(state, valid_ids, chapter_role=chapter_role, cfg=cfg)
                extra_paper_directive = (
                    "\n[논문·리뷰 단일성 지시] 이 섹션의 지정 역할에만 엄격히 집중하고, "
                    "다른 섹션의 내용(초록·핵심 요약·참고문헌 목록)을 절대 중복 생성하지 마십시오."
                    if is_paper
                    else ""
                )
                user_prompt = (
                    f"단원 제목: {ch['title']}\n단원 요약: {ch.get('summary_ko', '')}\n필수 절: {', '.join(secs)}\n"
                    f"대상 독자: {state['target_audience']}\n\n"
                    + (f"{kg_block}\n\n" if kg_block else "")
                    + f"[검증 근거 패킷]\n{ch_evidence}\n\n"
                    "위 근거와 지식그래프 트리플을 바탕으로 설정된 전문가 페르소나와 시나리오에 걸맞은 풍부하고 깊이 있는 한국어 원고를 작성하세요."
                    + extra_paper_directive
                )
                try:
                    draft_body = client.draft_text(
                        system_prompt=sys_prompt,
                        user_prompt=user_prompt,
                        model=gemma_model,
                        think=False,
                        num_predict=6144 if (is_paper and chapter_role == "results_discussion") else 4096,
                        timeout=320 if (is_paper and chapter_role == "results_discussion") else 240,
                    )
                except Exception as exc:
                    append_event(pid, "domain-drafter", sid, f"[{cid}] Ollama 폴백 템플릿 적용(⚠ 품질 확인 필요 — 이 단원은 다시 집필해야 합니다): {exc}", level="WARN", cfg=cfg)
                    is_fallback = True
                    c_tag = f"[{valid_ids[0]}]" if valid_ids else ""
                    if is_paper:
                        draft_body = (
                            f"# {ch['title']}\n\n"
                            + "\n\n".join(
                                f"## {sec}\n\n본 절에서는 {state['topic_ko']}에 관한 정량 근거와 기작 분석을 정리한다 {c_tag}."
                                for sec in secs
                            )
                            + "\n"
                        )
                    else:
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

        # 논문·리뷰 모드는 ch05에서만 참고문헌을 단 1회 통합 수록하므로 ch01~ch04에 단원별 참고문헌 표를 부착하지 않는다.
        ref_block = ""
        if not is_paper:
            ref_lines = ["", "## 참고문헌 및 근거 출처 목록", "", "| 출처 ID | 유형 | 제목 | URL | 라이선스 |", "| :--- | :--- | :--- | :--- | :--- |"]
            for s in sources:
                ref_lines.append(f"| `{s.get('source_id','')}` | {s.get('source_type','web')} | {str(s.get('title','')).replace('|','/')} | {s.get('url','')} | {s.get('license_note','')} |")
            ref_block = "\n" + "\n".join(ref_lines)

        fm_role = f'chapter_role: "{chapter_role}"\n' if chapter_role else ""
        fm = f'---\nchapter_id: "{cid}"\n{fm_role}title: "{ch["title"]}"\naudience: "{state["target_audience"]}"\nevidence_packet: "{state["packet_id"]}.json"\npersona: "{persona.get("persona_id", "")}"\n---\n\n'
        if not draft_body.lstrip().startswith("# "):
            draft_body = f"# {ch['title']}\n\n" + draft_body
        draft_body = _dedup_leading_chapter_heading(draft_body, ch["title"])
        full_mdx, _ = _clean_single_chapter(fm + draft_body.strip() + ref_block + "\n")
        out_mdx.write_text(full_mdx, encoding="utf-8")

        completed_chs.add(cid)
        state["checkpoint"]["completed_chapters"] = sorted(completed_chs)
        fb_set = set(state["checkpoint"].get("fallback_chapters") or [])
        if is_fallback:
            fb_set.add(cid)
        else:
            fb_set.discard(cid)
        state["checkpoint"]["fallback_chapters"] = sorted(fb_set)
        save_project_state(state, cfg)
        append_event(pid, "domain-drafter", sid, f"체크포인트 저장 [{cid}] 완료 ({len(full_mdx):,}자, 누적 {len(completed_chs)}/{total_n}장)", cfg=cfg)

    # 전수 인용·수식·내용 일치 감사 (+ 미등록 인용키 자동 보정 게이트, C6/P15)
    _update_stage(state, sid, cfg, progress=92, current_action="전 단원 인용 형식·표준 수식·내용 일치율 감사 실행 중...")
    audit = verify_target(ch_dir, semantic=True, cfg=cfg)
    if any(e.get("type") == "MISSING_SOURCE_ID" for e in audit.get("critical_errors", [])):
        try:
            from agro_framework import auto_repair_chapter_citations

            rep_res = auto_repair_chapter_citations(pid, cfg=cfg)
            append_event(
                pid,
                "citation-auditor",
                sid,
                f"인용 자동 보정 게이트 실행: {rep_res.get('repaired_files', 0)}개 단원 · {rep_res.get('replaced_tags', 0)}건 보정 완료",
                cfg=cfg,
            )
            audit = verify_target(ch_dir, semantic=True, cfg=cfg)
        except Exception as exc:
            append_event(pid, "citation-auditor", sid, f"인용 자동 보정 경고: {exc}", level="WARN", cfg=cfg)
    audit_path = rep_dir / "audit_latest.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    crit = len(audit.get("critical_errors", []))
    warns = len(audit.get("warnings", []))
    fmt_label = audit.get("format_check_status") or f"형식 검사 {audit['status']}"
    ca = audit.get("content_audit") or {}
    align_str = f" · 내용 일치율 {ca.get('alignment_rate_pct', 0)}%(무관 {ca.get('unrelated_ratio_pct', 0)}%)" if ca else ""

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

    _fb_list = sorted(set(state.get("checkpoint", {}).get("fallback_chapters") or []))
    if _fb_list:
        append_event(pid, "domain-drafter", sid, f"⚠ AI 집필 실패로 틀 원고가 들어간 단원: {', '.join(_fb_list)} — 원고 품질 점검표에서 확인 후 해당 단원을 다시 집필하세요.", level="WARN", cfg=cfg)
    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"{len(completed_chs)}개 단원 집필·정제 및 감사({fmt_label}, 치명오류 {crit}건{align_str}) 완료"
        + (f" · ⚠ 틀 원고 {len(_fb_list)}개 단원({', '.join(_fb_list[:5])}) 재집필 필요" if _fb_list else ""),
        metrics={
            "completed_chapters": len(completed_chs),
            "total_chapters": total_n,
            "audit_status": audit["status"],
            "format_check_status": fmt_label,
            "alignment_rate_pct": ca.get("alignment_rate_pct") if ca else None,
            "unrelated_ratio_pct": ca.get("unrelated_ratio_pct") if ca else None,
            "critical_errors": crit,
            "warnings": warns,
            "fallback_chapters": len(_fb_list),
        },
        artifacts=[str(audit_path)] + [str(ch_dir / f"{c}.mdx") for c in sorted(completed_chs)[:5]],
    )


def _run_stage5_visuals_generate(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from visual_studio import generate_project_visuals

    pid = state["project_id"]
    sid = "stage5_visuals_generate"
    opts = state.get("options", {})
    raw_per_ch = opts.get("visuals_per_chapter")
    per_ch = max(0, min(25, int(4 if raw_per_ch is None else raw_per_ch)))
    if per_ch == 0:
        _update_stage(
            state,
            sid,
            cfg,
            status="DONE",
            progress=100,
            finished_at=utc_now_iso(),
            current_action="시각화 개수 0개 설정 — 텍스트 전용 완료 (필요 시 [🖼️ 이미지 스튜디오]에서 개별·분할 추가 가능)",
            metrics={"total_visuals": 0, "per_chapter": 0, "ai_images": 0, "svg_charts": 0},
        )
        return
    is_paper_track = (state.get("primary_output_type") == "paper")
    use_fal = bool(opts.get("use_fal_ai", False)) and not is_paper_track
    fal_model = opts.get("fal_model") or "fal-ai/nano-banana"
    use_nb = bool(opts.get("use_nano_banana", False)) and not is_paper_track
    allow_auto_paid = bool(opts.get("allow_auto_paid_ai", False)) and not is_paper_track
    model_tier = str(opts.get("image_model_tier") or "flash").lower()
    nb_primary = "nano-banana-pro-preview" if model_tier == "pro" else "gemini-2.5-flash-image"

    # 5단계 선행(0원): OA 원문 표·CC-BY 그림 자산 인덱스 최신화
    try:
        from source_visual_harvester import harvest_project_visual_assets

        h_res = harvest_project_visual_assets(pid, max_jats=6 if is_paper_track else 3, max_pdfs=3, cfg=cfg)
        state["harvested_visuals_summary"] = h_res.get("summary") or {}
        save_project_state(state, cfg)
    except Exception:
        pass

    ch_dir = Path(state["workspace_dir"]) / "chapters"
    drafted_files = sorted(ch_dir.glob("*.mdx"))
    gemini_key = resolve_api_key("GEMINI_API_KEY", None, cfg)

    # 비용 누수 차단: 전량 유료 AI 엔진은 사용자가 명시적으로 allow_auto_paid_ai=True를 켠 비-논문 프로젝트에서만 실행
    if allow_auto_paid and drafted_files and gemini_key and (use_nb or use_fal):
        try:
            from context_visual_director import rebuild_project_visuals_with_nano_banana

            res = rebuild_project_visuals_with_nano_banana(
                pid,
                per_chapter_count=per_ch,
                primary_model=nb_primary,
                backend="fal" if (use_fal and resolve_api_key("FAL_KEY", None, cfg)) else "google",
                max_workers=2,
                purge_first=False,
                cfg=cfg,
            )
            # 최신 state 동기화
            fresh = load_project_state(pid, cfg)
            if fresh:
                state.clear()
                state.update(fresh)
            return
        except Exception as exc:
            append_event(pid, "visual-artist", sid, f"문맥 기반 이미지 AI 엔진 폴백 → 저비용 하이브리드 visual_studio 사용: {exc}", level="WARN", cfg=cfg)

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
    state["local_visuals_dir"] = res.get("local_visuals_dir", "")
    state["e_visuals_dir"] = res.get("e_visuals_dir", "")
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
        current_action=f"시각화 총 {res['total_generated']}종 별도 저장 완료 (단원당 {per_ch}개 · PNG 변환 {res.get('png_rasterized_count',0)}종 · E:\\ 미러링)",
        metrics={
            "total_visuals": res["total_generated"],
            "per_chapter": per_ch,
            "ai_images": res["ai_images_count"],
            "svg_charts": res["svg_charts_count"],
            "png_rasterized": res.get("png_rasterized_count", 0),
            "fal_ai": use_fal,
            "e_visuals_dir": res.get("e_visuals_dir", ""),
        },
        artifacts=[res["manifest_path"], res["guide_path"]],
    )


def set_chapter_expert_review(
    project_id: str,
    chapter_id: str,
    reviewed: bool,
    *,
    reviewer: str = "전문가",
    note: str = "",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """C9: 단원별 전문가 [검토 완료] 상태를 기록한다 (검토 완료된 단원만 6단계 출판에 포함)."""
    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    safe_cid = Path(chapter_id).name.replace(".mdx", "")
    reviews = dict(st.get("chapter_reviews") or {})
    reviews[safe_cid] = {
        "reviewed": bool(reviewed),
        "reviewer": reviewer.strip() or "전문가",
        "note": note.strip(),
        "reviewed_at": utc_now_iso() if reviewed else "",
    }
    st["chapter_reviews"] = reviews
    save_project_state(st, cfg)
    append_event(
        project_id,
        "expert-reviewer",
        "stage4_manuscript_draft",
        f"[{safe_cid}] 전문가 검토 상태 변경: {'✅ 검토 완료' if reviewed else '⏳ 검토 해제'} ({reviewer})",
        cfg=cfg,
    )
    return {"status": "OK", "chapter_id": safe_cid, "review": reviews[safe_cid], "chapter_reviews": reviews}


def evaluate_publish_readiness(
    project_id: str,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """C6/C9/V7: 6단계 출판 전 4대 품질 게이트(근거 관련도·내용 일치율·그림 자료 출처·전문가 검토)를 종합 판정한다."""
    from visual_studio import audit_visual_assets

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    ch_files = sorted(ch_dir.glob("*.mdx")) if ch_dir.is_dir() else []
    ch_ids = [p.stem for p in ch_files]

    # 1. 근거 관련도 (수집 소스의 relevance_score 평균 또는 앵커 존재 여부)
    collected = st.get("collected_sources") or []
    rel_scores = [float(s["relevance_score"]) for s in collected if s.get("relevance_score") is not None]
    avg_rel_pct = round((sum(rel_scores) / len(rel_scores)) * 100.0, 1) if rel_scores else None

    # 2. 인용 형식 및 내용 일치율 (audit_latest.json)
    audit_p = ws / "reports" / "audit_latest.json"
    audit = json.loads(audit_p.read_text(encoding="utf-8")) if audit_p.is_file() else {}
    crit_cnt = len(audit.get("critical_errors") or [])
    ca = audit.get("content_audit") or {}
    align_pct = ca.get("alignment_rate_pct")
    unrel_pct = ca.get("unrelated_ratio_pct")

    # 3. 그림 자료 출처 및 가짜/틀 그림 여부 (V7)
    vis_qa = audit_visual_assets(project_id, cfg=cfg)

    # 4. 전문가 검토 완료 단원 (C9)
    reviews = st.get("chapter_reviews") or {}
    reviewed_ids = [cid for cid in ch_ids if (reviews.get(cid) or {}).get("reviewed")]
    require_review = bool((st.get("options") or {}).get("require_expert_review", True))

    blockers: list[str] = []
    if not ch_ids:
        blockers.append("집필된 원고(.mdx)가 없습니다.")
    if crit_cnt > 0:
        blockers.append(f"인용·수식 치명 오류 {crit_cnt}건이 남아 있습니다.")
    if avg_rel_pct is not None and avg_rel_pct < 40.0:
        blockers.append(f"근거 평균 관련도({avg_rel_pct}%)가 기준(40% 이상) 미만입니다.")
    if unrel_pct is not None and float(unrel_pct) > 30.0:
        blockers.append(f"출처와 무관한 인용 비율({unrel_pct}%)이 기준(30% 이하)을 초과합니다.")
    if vis_qa.get("has_placeholder_or_fake"):
        blockers.append("빈 틀 그림 또는 가짜 수치 차트가 남아 있습니다(5단계 정리 필요).")
    if vis_qa.get("total", 0) > 0 and vis_qa.get("source_coverage_pct", 100.0) < 80.0:
        blockers.append(f"그림 자료 출처 기재율({vis_qa['source_coverage_pct']}%)이 기준(80% 이상) 미만입니다.")
    if require_review and len(reviewed_ids) == 0:
        blockers.append("전문가 [검토 완료] 체크된 단원이 0개입니다(4단계 점검표에서 1개 이상 검토 완료 필요).")

    return {
        "ready": len(blockers) == 0,
        "blockers": blockers,
        "metrics": {
            "total_chapters": len(ch_ids),
            "reviewed_chapters": len(reviewed_ids),
            "reviewed_chapter_ids": reviewed_ids,
            "avg_evidence_relevance_pct": avg_rel_pct,
            "critical_errors": crit_cnt,
            "alignment_rate_pct": align_pct,
            "unrelated_ratio_pct": unrel_pct,
            "visuals_total": vis_qa.get("total", 0),
            "visuals_publishable": vis_qa.get("publishable", 0),
            "visual_source_coverage_pct": vis_qa.get("source_coverage_pct", 100.0),
            "visual_has_placeholder_or_fake": bool(vis_qa.get("has_placeholder_or_fake", False)),
            "require_expert_review": require_review,
        },
    }


def _run_stage6_publish_report(state: dict[str, Any], cfg: PlatformConfig) -> None:
    from output_converter import publish_default_outputs

    pid = state["project_id"]
    sid = "stage6_publish_report"
    otype = state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook"
    docx_desc = "국내 학회지 논문 투고 규격 DOCX(A4 · 3선표)" if otype == "paper" else "마스터 Word(DOCX)"

    # C6/C9/V7: 품질 게이트 미달 시 6단계 출판 차단
    gate = evaluate_publish_readiness(pid, cfg=cfg)
    if not gate["ready"]:
        msg = "품질 게이트 미달로 6단계 출판이 차단되었습니다: " + " / ".join(gate["blockers"])
        append_event(pid, "book-publisher", sid, f"⛔ {msg}", level="WARN", cfg=cfg)
        raise RuntimeError(msg)

    _update_stage(
        state,
        sid,
        cfg,
        status="RUNNING",
        progress=15,
        started_at=utc_now_iso(),
        current_action=f"기본 핵심 산출물 2종({docx_desc} + 블로그용 단일 HTML) 생성 중...",
        error="",
    )
    append_event(pid, "book-publisher", sid, f"6단계 시작: 중복 제거 기본 2종 출판 ({docx_desc} + 블로그용 단일 HTML)", cfg=cfg)

    only_rev = bool((state.get("options") or {}).get("require_expert_review", True))
    res = publish_default_outputs(pid, only_reviewed=only_rev, check_quality_gate=False, cfg=cfg)
    fresh = load_project_state(pid, cfg)
    if fresh:
        state.clear()
        state.update(fresh)

    d_out = res.get("default_outputs") or {}
    docx_info = d_out.get("master_docx") or {}
    blog_info = d_out.get("blog_single_html") or {}
    built_files = res.get("built_files") or []

    append_event(
        pid,
        "book-publisher",
        sid,
        f"기본 산출물 2종 완료: ① {docx_info.get('label_ko', '마스터 DOCX')} ({docx_info.get('size_kb', 0)} KB), "
        f"② 블로그용 단일 HTML ({blog_info.get('size_kb', 0)} KB) · 시각화 {res.get('total_visuals_bound', 0)}종 결합",
        cfg=cfg,
    )

    _update_stage(state, sid, cfg, progress=92, current_action="6단계 출판 완료 종합 보고서(06_final_book_report.md) 작성 중...")
    rep_md = _write_stage6_report(state, {"published_files": len(built_files)}, cfg)
    append_event(pid, "book-publisher", sid, f"6단계 출판 완료 종합 보고서 작성 완료: {rep_md.name}", cfg=cfg)
    _update_stage(
        state,
        sid,
        cfg,
        status="DONE",
        progress=100,
        finished_at=utc_now_iso(),
        current_action=f"기본 산출물 2종 완료 ({docx_info.get('label_ko', 'DOCX')} + 블로그용 단일 HTML) · PDF 등 추가 포맷은 변환 모듈에서 선택 생성",
        metrics={
            "published_files": len(built_files),
            "chapters_published": res.get("chapters_count", 0),
            "total_visuals_bound": res.get("total_visuals_bound", 0),
            "master_docx_mode": docx_info.get("mode", ""),
            "report": rep_md.name,
        },
        artifacts=[str(rep_md)] + built_files,
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

    # 완료된 단계를 다시 실행하면 덮어쓰기 전에 자동 백업
    done_targets = [s["stage_id"] for s in state["stages"] if s["stage_id"] in stage_ids and s["status"] == "DONE"]
    snapshot = None
    if done_targets:
        try:
            snapshot = create_stage_snapshot(project_id, done_targets, cfg=cfg)
        except Exception as exc:
            append_event(project_id, "orchestrator", done_targets[0], f"자동 백업 실패(실행은 계속): {exc}", level="WARN", cfg=cfg)

    th = threading.Thread(target=_worker_loop, args=(project_id, stage_ids, cfg), daemon=True)
    _ACTIVE_THREADS[project_id] = th
    th.start()
    return {"status": "STARTED", "project_id": project_id, "queued_stages": stage_ids, "snapshot": snapshot}


def stop_pipeline(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    th = _ACTIVE_THREADS.get(project_id)
    if not (th and th.is_alive()):
        return {"status": "NOT_RUNNING", "project_id": project_id}
    ev = _STOP_FLAGS.get(project_id)
    if ev:
        ev.set()
    return {"status": "STOP_REQUESTED", "project_id": project_id}


# ============================================================
# F3: 재실행 전 자동 백업(스냅샷) · 되돌리기
# ============================================================
# 단계별로 다시 만들어지는 폴더 (작업 폴더 기준). 3단계 지식그래프는 Append-Only라 상태만 백업한다.
STAGE_SNAPSHOT_DIRS: dict[str, list[str]] = {
    "stage1_topic_outline": ["blueprints"],
    "stage2_source_collect": ["collected", "reports"],
    "stage3_kg_build": ["reports"],
    "stage4_manuscript_draft": ["chapters", "reports"],
    "stage5_visuals_generate": ["assets"],
    "stage6_publish_report": ["exports", "reports"],
}
SNAPSHOT_KEEP = 3  # 프로젝트당 최근 백업 보관 개수 (용량 절약)


def _snapshots_root(state: dict[str, Any]) -> Path:
    return Path(state["workspace_dir"]) / "_snapshots"


def create_stage_snapshot(project_id: str, stage_ids: list[str], reason: str = "", cfg: PlatformConfig | None = None, prune: bool = True) -> dict[str, Any] | None:
    """재실행 직전 해당 단계 산출물 폴더와 state.json을 _snapshots/<시각>_<단계>/ 에 복사해 둔다."""
    cfg = cfg or get_config()
    state = load_project_state(project_id, cfg)
    if not state:
        return None
    ws = Path(state["workspace_dir"])
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "+".join(s.split("_")[0] for s in stage_ids) or "manual"
    snap_dir = _snapshots_root(state) / f"{ts}_{label}"
    n = 2
    while snap_dir.exists():
        snap_dir = _snapshots_root(state) / f"{ts}_{label}_{n}"
        n += 1
    snap_dir.mkdir(parents=True)
    copied: list[str] = []
    for sid in stage_ids:
        for sub in STAGE_SNAPSHOT_DIRS.get(sid, []):
            src = ws / sub
            dst = snap_dir / sub
            if src.is_dir() and not dst.exists():
                shutil.copytree(src, dst)
                copied.append(sub)
    (snap_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "snapshot_id": snap_dir.name,
        "created_at": utc_now_iso(),
        "stage_ids": stage_ids,
        "folders": copied,
        "reason": reason or "재실행 전 자동 백업",
    }
    (snap_dir / "snapshot_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(project_id, "orchestrator", stage_ids[0] if stage_ids else "snapshot", f"💾 재실행 전 자동 백업 완료: {snap_dir.name} ({', '.join(copied) or '상태만'})", cfg=cfg)
    if prune:
        _prune_snapshots(state)
    return meta


def _prune_snapshots(state: dict[str, Any]) -> None:
    """오래된 자동 백업을 지워 최근 SNAPSHOT_KEEP 개만 남긴다 (용량 절약)."""
    root = _snapshots_root(state)
    if not root.is_dir():
        return
    snaps = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda d: d.name)
    for old in snaps[:-SNAPSHOT_KEEP]:
        shutil.rmtree(old, ignore_errors=True)


def list_stage_snapshots(project_id: str, cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    cfg = cfg or get_config()
    state = load_project_state(project_id, cfg)
    if not state:
        raise FileNotFoundError(project_id)
    root = _snapshots_root(state)
    out: list[dict[str, Any]] = []
    if root.is_dir():
        for d in sorted(root.iterdir(), key=lambda d: d.name, reverse=True):
            mp = d / "snapshot_meta.json"
            if d.is_dir() and mp.is_file():
                try:
                    out.append(json.loads(mp.read_text(encoding="utf-8")))
                except Exception:
                    continue
    return out


def restore_stage_snapshot(project_id: str, snapshot_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """백업 시점으로 되돌린다. 현재 상태도 먼저 백업하므로 되돌리기 자체도 다시 되돌릴 수 있다."""
    cfg = cfg or get_config()
    t_existing = _ACTIVE_THREADS.get(project_id)
    if t_existing and t_existing.is_alive():
        raise ValueError("작업이 실행 중일 때는 되돌릴 수 없습니다. 먼저 중단하세요.")
    state = load_project_state(project_id, cfg)
    if not state:
        raise FileNotFoundError(project_id)
    snap_dir = _snapshots_root(state) / Path(snapshot_id).name
    meta_p = snap_dir / "snapshot_meta.json"
    if not meta_p.is_file():
        raise ValueError("백업을 찾을 수 없습니다.")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    ws = Path(state["workspace_dir"])
    stage_ids = meta.get("stage_ids") or []
    # 현재 상태를 먼저 백업 (되돌리기 취소 가능)
    create_stage_snapshot(project_id, stage_ids, reason=f"되돌리기({snapshot_id}) 직전 상태", cfg=cfg, prune=False)
    for sub in meta.get("folders") or []:
        src = snap_dir / sub
        dst = ws / sub
        if not src.is_dir():
            continue
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    old_state = json.loads((snap_dir / "state.json").read_text(encoding="utf-8"))
    old_stages = {s["stage_id"]: s for s in old_state.get("stages", [])}
    for i, s in enumerate(state.get("stages", [])):
        if s["stage_id"] in stage_ids and s["stage_id"] in old_stages:
            state["stages"][i] = old_stages[s["stage_id"]]
    for key in ("checkpoint", "outputs", "bound_visuals_by_chapter", "blueprint_preview"):
        if key in old_state:
            state[key] = old_state[key]
    all_done = all(s["status"] == "DONE" for s in state["stages"])
    state["overall_status"] = "DONE" if all_done else "PAUSED"
    save_project_state(state, cfg)
    append_event(project_id, "orchestrator", stage_ids[0] if stage_ids else "snapshot", f"↩ 백업 {snapshot_id} 시점으로 되돌렸습니다.", cfg=cfg)
    _prune_snapshots(state)
    return {"status": "RESTORED", "snapshot": meta, "project": state}


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
