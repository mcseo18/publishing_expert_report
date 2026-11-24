"""Tests for bilingual (Korean + English) visual prompt pack generation & manuscript anchor linking."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from docx import Document
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

from config import PlatformConfig
from math_typography import detect_unformatted_math_leaks
from subagent_orchestrator import create_project, evaluate_publish_readiness, save_project_state, set_chapter_expert_review
from visual_prompt_pack import ANCHOR_START_RE, build_project_visual_prompt_pack, load_project_visual_prompt_pack
from visual_studio import audit_visual_assets


def _make_cfg(tmp_path: Path) -> PlatformConfig:
    data_root = tmp_path / "e_data"
    kg_root = tmp_path / "kg"
    for d in (
        data_root / "raw" / "web",
        data_root / "raw" / "docs",
        data_root / "parsed",
        data_root / "evidence",
        data_root / "index",
        data_root / "projects",
        kg_root / "lightrag_store",
        kg_root / "output",
        tmp_path / "projects",
    ):
        d.mkdir(parents=True, exist_ok=True)
    return PlatformConfig(
        workspace_root=tmp_path,
        collected_data_root=data_root,
        smc_graphrag_root=kg_root,
        lightrag_working_dir=kg_root / "lightrag_store",
        lightrag_workspace="test_ws",
        lightrag_api_url="http://127.0.0.1:1",
        ollama_host="http://127.0.0.1:1",
        ollama_llm_model="gemma4:26b",
        ollama_fast_model="gemma4:26b",
        ollama_embed_model="bge-m3",
        ollama_num_ctx=4096,
    )


def _seed_project(cfg: PlatformConfig) -> str:
    st = create_project(
        topic_ko="정밀 농업 관개 제어 공학",
        topic_en="Precision Agricultural Irrigation Control Engineering",
        keywords_ko=["토양수분", "점적관개", "증발산량"],
        keywords_en=["soil moisture", "drip irrigation", "evapotranspiration"],
        target_pages=120,
        chapter_count=2,
        options={
            "visual_generation_mode": "prompt_pack_only",
            "generate_visual_prompt_pack": True,
            "visuals_per_chapter": 4,
        },
        cfg=cfg,
    )
    pid = st["project_id"]
    ws = Path(st["workspace_dir"])
    st["collected_sources"] = [
        {"source_id": "SRC-101", "title": "FAO-56 Crop Evapotranspiration Guidelines", "year": 2024, "relevance_score": 0.92},
        {"source_id": "SRC-102", "title": "Smart Drip Irrigation Control in Loam Soils", "year": 2025, "relevance_score": 0.88},
    ]
    save_project_state(st, cfg)

    ch_dir = ws / "chapters"
    ch_dir.mkdir(parents=True, exist_ok=True)
    (ch_dir / "ch01.mdx").write_text(
        "# 제1장. 토양 수분 역학과 센서 구조\n\n"
        "## 1.1 근권 토양 수분 장력 메커니즘과 구조\n\n"
        "점토와 사질양토의 **포장용수량**은 각각 32% 및 18%이며 **위조점** 미만에서 수분 스트레스가 급증한다 [SRC-101].\n\n"
        "## 1.2 자동 관개 의사결정 절차와 제어 흐름\n\n"
        "센서 계측값이 **임계 수분 장력** -30 kPa 이하로 하강하면 밸브를 개방하고 25 mm를 관수한 뒤 피드백 검증을 수행한다 [SRC-102].\n\n"
        "## 1.3 처리구별 관수 효율 정량 비교\n\n"
        "| 관개 방식 | 관수량 (mm) | 수분이용효율 (kg/m³) | 수량 (ton/ha) |\n"
        "|---|---|---|---|\n"
        "| 관행 고랑관개 | 420 | 4.2 | 48.5 |\n"
        "| 센서 점적관개 | 285 | 7.6 | 56.2 |\n\n"
        "센서 점적관개는 관행 대비 물 사용량을 32% 절감하면서 수량을 15.9% 향상시켰다 [SRC-102].\n\n"
        "## 1.4 포장 점적관개 설비 현장 관찰\n\n"
        "포장 두둑 위 점적테이프와 토양 수분 센서의 설치 간격은 30 cm가 표준이며 작물 근권 습윤 구근을 균일하게 유지한다 [SRC-101].\n\n"
        "### 참고문헌\n"
        "- [SRC-101] FAO (2024)\n"
        "- [SRC-102] Smart Drip (2025)\n",
        encoding="utf-8",
    )
    set_chapter_expert_review(pid, "ch01", True, reviewer="검토자", cfg=cfg)
    return pid


def test_bilingual_prompt_pack_generation_anchors_and_quality_gate(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    pid = _seed_project(cfg)

    res = build_project_visual_prompt_pack(pid, per_chapter_count=4, inject_manuscript_anchors=True, cfg=cfg)
    assert res["status"] == "OK"
    assert res["total_prompts"] == 4
    assert res["anchor_sync"]["updated_chapters"] == 1
    assert res["anchor_sync"]["anchors_inserted"] == 4

    docx_p = Path(res["docx_path"])
    md_p = Path(res["md_path"])
    assert docx_p.is_file() and docx_p.stat().st_size > 15_000
    assert md_p.is_file()

    # Check bilingual prompt richness and zero math leaks in DOCX
    items = res["pack"]["items"]
    cats = {it["category"] for it in items}
    assert len(cats) >= 3  # diverse categories: diagram, flowchart, data_chart, photorealistic/infographic
    for it in items:
        assert it["prompt_id"].startswith("VP-CH01-")
        assert "[1. 핵심 주제 및 목적]" in it["prompt_ko"]
        assert len(it["prompt_en"]) >= 160
        assert len(it["negative_prompt_en"]) >= 40
        assert it["source_note"]

    doc = Document(str(docx_p))
    leaks = []
    for p in doc.paragraphs:
        leaks.extend(detect_unformatted_math_leaks(p.text))
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                leaks.extend(detect_unformatted_math_leaks(cell.text))
    assert leaks == [], f"Unexpected math leaks in prompt pack DOCX: {leaks}"

    # Verify anchors inserted into ch01.mdx and idempotent on second run (no duplication!)
    ch01_p = cfg.project_dir(pid) / "chapters" / "ch01.mdx"
    ch01_txt = ch01_p.read_text(encoding="utf-8")
    assert len(ANCHOR_START_RE.findall(ch01_txt)) == 4
    assert "VP-CH01-01" in ch01_txt
    assert f"{pid}_visual_prompts.docx" in ch01_txt

    res2 = build_project_visual_prompt_pack(pid, per_chapter_count=4, inject_manuscript_anchors=True, cfg=cfg)
    ch01_txt2 = ch01_p.read_text(encoding="utf-8")
    assert len(ANCHOR_START_RE.findall(ch01_txt2)) == 4  # strictly idempotent!

    # Verify visual QA & Stage 6 Publish Readiness PASS in prompt_pack_only mode!
    vis_qa = audit_visual_assets(pid, cfg=cfg)
    assert vis_qa["publishable"] == 4
    assert vis_qa["has_placeholder_or_fake"] is False
    assert vis_qa["source_coverage_pct"] == 100.0

    gate = evaluate_publish_readiness(pid, cfg=cfg)
    assert gate["ready"] is True, f"Blockers: {gate['blockers']}"


def test_prompt_pack_api_endpoints(tmp_path: Path, monkeypatch):
    import agents_app
    import config as cfg_mod
    import subagent_orchestrator
    import visual_prompt_pack
    import visual_studio

    cfg = _make_cfg(tmp_path)
    pid = _seed_project(cfg)
    for mod in (cfg_mod, agents_app, subagent_orchestrator, visual_prompt_pack, visual_studio):
        if hasattr(mod, "get_config"):
            monkeypatch.setattr(mod, "get_config", lambda *a, **kw: cfg)

    client = TestClient(agents_app.app)
    r_post = client.post(
        f"/api/projects/{pid}/visuals/prompt-pack",
        json={"per_chapter_count": 4, "inject_manuscript_anchors": True},
    )
    assert r_post.status_code == 200
    assert r_post.json()["total_prompts"] == 4

    r_get = client.get(f"/api/projects/{pid}/visuals/prompt-pack")
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["exists"] is True
    assert len(data["items"]) == 4

    # Verify create_project accepts prompt_pack_only initial option cleanly
    r_create = client.post(
        "/api/projects",
        json={
            "topic_ko": "프롬프트 모드 초기 옵션 테스트",
            "topic_en": "Prompt Pack Mode Init Test",
            "visual_generation_mode": "prompt_pack_only",
            "generate_visual_prompt_pack": True,
            "auto_start": False,
        },
    )
    assert r_create.status_code == 200
    opts = r_create.json()["project"]["options"]
    assert opts["visual_generation_mode"] == "prompt_pack_only"
    assert opts["generate_visual_prompt_pack"] is True
