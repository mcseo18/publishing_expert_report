"""Unit & FastAPI integration tests for dashboard error diagnosis and 1-click recovery."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

from config import PlatformConfig
from error_recovery import diagnose_project_issues, execute_recovery_action
from subagent_orchestrator import create_project, load_project_state, save_project_state, stop_pipeline


def _make_isolated_cfg(tmp_path: Path) -> PlatformConfig:
    data_root = tmp_path / "e_data"
    kg_root = tmp_path / "kg"
    proj_root = tmp_path / "projects"
    for d in (
        data_root / "raw" / "web",
        data_root / "raw" / "docs",
        data_root / "parsed",
        data_root / "evidence",
        data_root / "index",
        data_root / "projects",
        kg_root / "lightrag_store",
        kg_root / "output",
        proj_root,
    ):
        d.mkdir(parents=True, exist_ok=True)
    return PlatformConfig(
        workspace_root=tmp_path,
        collected_data_root=data_root,
        smc_graphrag_root=kg_root,
        lightrag_working_dir=kg_root / "lightrag_store",
        lightrag_workspace="test_ws",
        lightrag_api_url="http://127.0.0.1:1",
        ollama_host="http://127.0.0.1:1",  # offline deterministic lexical mode
        ollama_llm_model="gemma4:26b",
        ollama_fast_model="gemma4:26b",
        ollama_embed_model="bge-m3",
        ollama_num_ctx=4096,
    )


def _seed_broken_project(cfg: PlatformConfig) -> str:
    st = create_project(
        topic_ko="테스트 농약 안전성 평가",
        topic_en="Test Agrochemical Safety Evaluation",
        keywords_ko=["농약", "잔류", "독성"],
        keywords_en=["pesticide", "residue", "toxicity"],
        target_pages=60,
        chapter_count=2,
        cfg=cfg,
    )
    pid = st["project_id"]
    ws = Path(st["workspace_dir"])

    # 1) Create an evidence packet with 1 relevant source (SRC-901) and 1 unrelated source (SRC-902)
    pkt = {
        "packet_id": st["packet_id"],
        "topic": "농약 잔류 독성",
        "created_at": "2026-11-24T00:00:00Z",
        "sources": [
            {
                "source_id": "SRC-901",
                "title": "농약 잔류 분석 QuEChERS LC-MS/MS 반감기 ADI MRL 안전성 평가",
                "url": "https://example.org/pesticide-residue",
                "source_type": "academic",
                "accessed_at": "2026-11-24T00:00:00Z",
                "robots_allowed": True,
                "license_note": "CC-BY",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "text": "농약 잔류 분석 QuEChERS 전처리와 LC-MS/MS MRM 정량으로 잔류 반감기 DT50 2.1일과 MRL 0.5 mg/kg 및 ADI 안전성 평가를 수행하였다.",
                        "page": 1,
                    }
                ],
            },
            {
                "source_id": "SRC-902",
                "title": "Medieval Castle Architecture Stone Masonry",
                "url": "https://example.org/castle",
                "source_type": "web",
                "accessed_at": "2026-11-24T00:00:00Z",
                "robots_allowed": True,
                "license_note": "CC-BY",
                "chunks": [
                    {
                        "chunk_id": "c2",
                        "text": "Gothic cathedral arches and limestone fortifications in fourteenth century Europe.",
                        "page": 1,
                    }
                ],
            },
        ],
    }
    (cfg.evidence_dir / f"{st['packet_id']}_evidence.json").write_text(
        json.dumps(pkt, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) Write 2 chapters: ch01 has valid SRC-901 + unrelated SRC-902 + invalid SRC-999
    ch_dir = ws / "chapters"
    ch_dir.mkdir(parents=True, exist_ok=True)
    (ch_dir / "ch01.mdx").write_text(
        "# 제1장. 농약 잔류 분석\n\n"
        "농약 잔류 분석 QuEChERS 전처리와 LC-MS/MS 정량으로 반감기 DT50 2.1일을 측정하였다 [SRC-901].\n"
        "MRL 0.5 mg/kg 및 ADI 안전성 평가 기준을 충족하였다 [SRC-901, SRC-902].\n"
        "잔류 농약 감쇄 모형으로 수확전 살포일수를 계산한다 [SRC-902].\n"
        "미등록 인용 테스트 문장이다 [SRC-999].\n",
        encoding="utf-8",
    )
    (ch_dir / "ch02.mdx").write_text(
        "# 제2장. 독성 기준\n\n"
        "농약 잔류 분석과 ADI MRL 안전성 평가를 통해 소비자 위해도를 검증하였다 [SRC-901].\n",
        encoding="utf-8",
    )

    # 3) Create a broken visuals_plan.json (1 good PNG missing source_note, 1 UNGENERATED stub)
    assets_dir = ws / "assets"
    fig_dir = assets_dir / "by_chapter" / "ch01"
    fig_dir.mkdir(parents=True, exist_ok=True)
    good_png = fig_dir / "fig_ch01_v01.png"
    good_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    vis_plan = {
        "project_id": pid,
        "visuals": [
            {
                "figure_id": "fig_ch01_v01",
                "chapter_id": "ch01",
                "title_ko": "그림 1-1. 잔류 감쇄 곡선",
                "path": str(good_png),
                "docx_image_path": str(good_png),
                "status": "GENERATED",
                "engine": "Matplotlib 300 DPI",
                "exclude_from_publish": False,
                "data_source": "",
                "source_note": "",
            },
            {
                "figure_id": "fig_ch01_v02",
                "chapter_id": "ch01",
                "title_ko": "그림 1-2. 미생성 스텁",
                "path": "",
                "status": "UNGENERATED",
                "engine": "svg_blueprint_ready",
                "exclude_from_publish": False,
                "data_source": "",
            },
        ],
    }
    (assets_dir / "visuals_plan.json").write_text(json.dumps(vis_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) Seed audit_latest.json showing high unrelated ratio & critical error
    rep_dir = ws / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    fake_audit = {
        "status": "FAIL",
        "critical_errors": [{"type": "MISSING_SOURCE_ID", "source_id": "SRC-999", "line": 6}],
        "content_audit": {"checked_claims": 4, "supported": 2, "partial": 0, "unrelated": 2, "alignment_rate_pct": 50.0, "unrelated_ratio_pct": 50.0},
        "files": [],
    }
    (rep_dir / "audit_latest.json").write_text(json.dumps(fake_audit, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) Put low-relevance sources + zombie RUNNING + Stage 6 ERROR into state.json
    st["collected_sources"] = [
        {"source_id": "SRC-901", "title": "Good pesticide paper", "relevance_score": 0.90, "is_anchor": True},
        {"source_id": "SRC-902", "title": "Castle architecture", "relevance_score": 0.05},
        {"source_id": "SRC-903", "title": "Unrelated blog", "relevance_score": 0.10},
    ]
    st["overall_status"] = "RUNNING"  # zombie lock (no live thread!)
    st["active_stage_id"] = "stage6_publish_report"
    for s in st["stages"]:
        if s["stage_id"] == "stage6_publish_report":
            s["status"] = "ERROR"
            s["error"] = "품질 게이트 미달로 6단계 출판이 차단되었습니다: 출처와 무관한 인용 비율(50.0%)이 기준(30% 이하)을 초과합니다."
    save_project_state(st, cfg)
    return pid


def test_zombie_running_auto_reconcile_and_diagnostics(tmp_path: Path):
    cfg = _make_isolated_cfg(tmp_path)
    pid = _seed_broken_project(cfg)

    diag = diagnose_project_issues(pid, cfg=cfg)
    # load_project_state automatically reconciles zombie RUNNING -> INTERRUPTED/PAUSED on load
    assert diag["overall_status"] in ("INTERRUPTED", "PAUSED")
    assert diag["is_zombie_running"] is False
    codes = {i["code"] for i in diag["issues"]}
    assert "QUALITY_GATE_BLOCKED" not in codes  # deduplicated in favor of concrete QUALITY_GATE_* issues
    assert "QUALITY_GATE_NO_REVIEW" in codes
    assert "QUALITY_GATE_VISUAL_QA" in codes
    assert "QUALITY_GATE_LOW_RELEVANCE" in codes
    assert "QUALITY_GATE_UNRELATED_CITATIONS" in codes
    wg = diag["workflow_guide"]
    assert wg["phase"] == "NEEDS_REPAIR"
    assert wg["step2_recovery"]["has_auto_fix"] is True
    assert wg["step3_restart"]["can_restart_now"] is False
    assert wg["step3_restart"]["target_stage_id"] == "stage6_publish_report"

    # Explicit unlock_stuck_running action works safely even when already interrupted
    res_unlock = execute_recovery_action(pid, "unlock_stuck_running", cfg=cfg)
    assert res_unlock["status"] == "OK"
    st_after = load_project_state(pid, cfg)
    assert st_after["overall_status"] == "INTERRUPTED"


def test_full_auto_heal_recovers_all_quality_gate_blockers(tmp_path: Path):
    cfg = _make_isolated_cfg(tmp_path)
    pid = _seed_broken_project(cfg)

    res = execute_recovery_action(pid, "run_full_auto_heal", cfg=cfg)
    assert res["status"] == "OK"
    diag = res["diagnostics"]

    assert diag["is_zombie_running"] is False
    assert diag["readiness"]["ready"] is True, f"Remaining blockers: {diag['readiness']['blockers']}"
    assert diag["readiness"]["blockers"] == []
    assert diag["readiness"]["metrics"]["reviewed_chapters"] == 2
    assert diag["readiness"]["metrics"]["critical_errors"] == 0
    assert diag["readiness"]["metrics"]["visual_has_placeholder_or_fake"] is False
    assert diag["readiness"]["metrics"]["visual_source_coverage_pct"] == 100.0
    assert diag["readiness"]["metrics"]["avg_evidence_relevance_pct"] >= 40.0
    assert (diag["readiness"]["metrics"]["unrelated_ratio_pct"] or 0.0) <= 30.0

    # Stage 6 error should be cleared cleanly and workflow_guide should move to READY_TO_RESTART
    st = res["project"]
    s6 = next(s for s in st["stages"] if s["stage_id"] == "stage6_publish_report")
    assert s6["error"] == ""
    assert s6["status"] != "ERROR"
    assert diag["workflow_guide"]["phase"] == "READY_TO_RESTART"
    assert diag["workflow_guide"]["step2_recovery"]["done"] is True
    assert diag["workflow_guide"]["step3_restart"]["can_restart_now"] is True
    assert res["details"]["critical_before"] >= 4
    assert res["details"]["critical_after"] == 0
    assert res["details"]["no_progress"] is False


def test_manual_error_sets_no_progress_anti_loop_guard(tmp_path: Path):
    cfg = _make_isolated_cfg(tmp_path)
    st = create_project(
        topic_ko="수동 오류 테스트",
        topic_en="Manual Error Test",
        keywords_ko=["테스트"],
        keywords_en=["test"],
        target_pages=20,
        chapter_count=2,
        cfg=cfg,
    )
    pid = st["project_id"]
    for s in st["stages"]:
        if s["stage_id"] == "stage4_manuscript_draft":
            s["status"] = "ERROR"
            s["error"] = "Ollama Connection refused on 127.0.0.1:11434"
    st["overall_status"] = "ERROR"
    save_project_state(st, cfg)

    diag = diagnose_project_issues(pid, cfg=cfg)
    assert diag["workflow_guide"]["phase"] == "MANUAL_ACTION_REQUIRED"
    assert diag["workflow_guide"]["step2_recovery"]["has_auto_fix"] is False
    assert len(diag["workflow_guide"]["step2_recovery"]["manual_hints"]) >= 1

    res = execute_recovery_action(pid, "run_full_auto_heal", cfg=cfg)
    assert res["details"]["no_progress"] is True
    assert "반복 실행 중단" in res["summary_ko"]


def test_dashboard_api_diagnostics_and_bulk_review_endpoints(tmp_path: Path, monkeypatch):
    import agents_app
    import agro_framework
    import config as cfg_mod
    import error_recovery
    import subagent_orchestrator
    import visual_studio

    cfg = _make_isolated_cfg(tmp_path)
    pid = _seed_broken_project(cfg)

    for mod in (cfg_mod, agents_app, error_recovery, subagent_orchestrator, agro_framework, visual_studio):
        if hasattr(mod, "get_config"):
            monkeypatch.setattr(mod, "get_config", lambda *a, **kw: cfg)

    client = TestClient(agents_app.app)

    r_diag = client.get(f"/api/projects/{pid}/diagnostics")
    assert r_diag.status_code == 200
    body = r_diag.json()
    assert body["overall_status"] in ("INTERRUPTED", "PAUSED")
    assert body["critical_count"] >= 4
    assert len(body["gate_checks"]) == 6

    r_rev = client.post(f"/api/projects/{pid}/chapters/review-all", json={"reviewed": True, "reviewer": "테스트"})
    assert r_rev.status_code == 200
    assert r_rev.json()["diagnostics"]["readiness"]["metrics"]["reviewed_chapters"] == 2

    r_heal = client.post(f"/api/projects/{pid}/recovery/execute", json={"action_id": "run_full_auto_heal", "params": {}})
    assert r_heal.status_code == 200
    healed = r_heal.json()
    assert healed["diagnostics"]["readiness"]["ready"] is True
    assert healed["diagnostics"]["critical_count"] == 0
