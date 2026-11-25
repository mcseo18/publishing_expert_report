"""단원별 파이프라인·스키마 검증·프리셋 오매칭·워커 충돌 회귀 방지 테스트."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_buckwheat_does_not_match_wheat_preset() -> None:
    from fetch_project_sources import detect_domain_preset

    # '메밀의 과학적 재배 기술' / 'Buckwheat'가 '밀(wheat)' 프리셋으로 오매칭되면 안 됨
    preset = detect_domain_preset(
        topic_ko="메밀의 과학적 재배 기술",
        topic_en="Scientific Cultivation Techniques for Buckwheat",
        keywords_ko=["메밀", "타타리메밀", "파종시기", "도복저항성"],
        keywords_en=["Buckwheat", "Fagopyrum esculentum", "Tartary buckwheat"],
    )
    assert preset != "wheat", f"Buckwheat falsely matched wheat preset: {preset}"

    # 실제 밀 주제는 여전히 wheat 프리셋으로 매칭되어야 함
    assert detect_domain_preset("겨울밀의 과학적 재배 기술", "Winter Wheat Cultivation") == "wheat"
    assert detect_domain_preset("디지털 밀 재배학", "Digital Wheat Agronomy") == "wheat"


def test_upsert_evidence_packet_auto_heals_missing_created_at(tmp_path: Path) -> None:
    from compliance import upsert_evidence_packet
    from config import get_config

    cfg = get_config()
    pkt_path = tmp_path / "broken_evidence.json"
    # 과거 chapter_pipeline._merge_sources_into_packet가 created_at 없이 저장한 깨진 패킷 재현
    pkt_path.write_text(
        json.dumps({"packet_id": "test_pkt", "topic": "메밀", "sources": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    src = {
        "source_id": "SRC-01",
        "source_type": "web",
        "url": "https://example.org/buckwheat-2025",
        "title": "Buckwheat Agronomy Study",
        "accessed_at": "2026-11-25T00:00:00Z",
        "robots_allowed": True,
        "license_note": "OA",
        "page_or_section": "본문",
        "extracted_facts": [],
        "tables": [],
        "sha256": "a" * 64,
    }
    res = upsert_evidence_packet(
        packet_path=pkt_path,
        source_item=src,
        packet_id="test_pkt",
        topic="메밀",
        storage_root=str(cfg.collected_data_root),
        kg_store_root=str(cfg.smc_graphrag_root),
        schema_path=cfg.evidence_schema_path,
    )
    assert res.get("created_at")
    assert len(res.get("sources") or []) == 1


def test_merge_sources_into_packet_includes_required_schema_fields(tmp_path: Path) -> None:
    from chapter_pipeline import _merge_sources_into_packet
    from compliance import validate_evidence_packet
    from config import get_config

    cfg = get_config()
    pkt_path = tmp_path / "merged_evidence.json"
    _merge_sources_into_packet(pkt_path, "test_merged", "메밀 재배", [], cfg=cfg)
    pkt = json.loads(pkt_path.read_text(encoding="utf-8"))
    assert pkt.get("created_at")
    assert pkt.get("updated_at")
    errs = validate_evidence_packet(pkt, cfg.evidence_schema_path)
    assert errs == [], f"Schema validation failed: {errs}"


def test_chapter_pipeline_calls_valid_ingest_signatures() -> None:
    """chapter_pipeline._research_single_chapter가 fetch_and_clean_url·ingest_paper_record 유효 인자만 쓰는지 검증."""
    import chapter_pipeline
    from fetch_clean import fetch_and_clean_url
    from fetch_scholar import ingest_paper_record

    src_code = inspect.getsource(chapter_pipeline._research_single_chapter)
    assert "download_pdf=True" not in src_code
    assert "project_id=pid" not in src_code
    assert "download_oa_pdf=True" in src_code

    p_sig = inspect.signature(ingest_paper_record).parameters
    assert "download_oa_pdf" in p_sig
    assert "download_pdf" not in p_sig

    w_sig = inspect.signature(fetch_and_clean_url).parameters
    assert "project_id" not in w_sig


def test_smc_graphrag_unified_search_and_catalog_triples() -> None:
    """C:\\SMC_GRAPHRAG 통합 RAG와 48만 노드 카탈로그 DB가 집필용 트리플·근거로 정상 조회되는지 검증."""
    from agro_framework import format_triples_for_prompt, query_kg_triples_for_chapter
    from config import get_config
    from rag_capture_unifier import search_unified_rag, search_unified_smc_rag

    cfg = get_config()
    assert search_unified_rag is search_unified_smc_rag

    res = search_unified_smc_rag("메밀 도복 습해", limit=5, cfg=cfg)
    assert isinstance(res.get("documents"), list)
    assert isinstance(res.get("kg_nodes"), list)
    assert isinstance(res.get("kg_relations"), list)
    # kg_nodes가 dict 키 문자열('matched_entities')이 아니라 실제 엔티티 dict인지 검증
    for nd in res["kg_nodes"]:
        assert isinstance(nd, dict) and "name" in nd

    if cfg.smc_catalog_db_path.is_file():
        triples = query_kg_triples_for_chapter(
            chapter_title="제6장. 메밀의 과습·습해 및 도복 저항성 관리",
            chapter_text="메밀 재배 시 습해와 도복 피해를 줄이기 위한 배수 관리",
            limit=12,
            cfg=cfg,
        )
        assert len(triples) > 0, "C:\\SMC_GRAPHRAG 카탈로그 DB에서 트리플이 1건 이상 조회되어야 함"
        prompt_blk = format_triples_for_prompt(triples)
        assert "SMC_GRAPHRAG" in prompt_blk


def test_new_project_defaults_use_smc_graphrag_on(tmp_path: Path, monkeypatch) -> None:
    """신규 프로젝트 생성 시 use_smc_graphrag 기본값이 True로 활성화되는지 검증."""
    import shutil
    from config import get_config
    from subagent_orchestrator import create_project, delete_project

    cfg = get_config()
    st = None
    try:
        st = create_project(
            topic_ko="테스트 메밀 생육 분석",
            topic_en="Test Buckwheat Growth Analysis",
            project_id_override="pytest_smc_default_check",
            cfg=cfg,
        )
        assert st["options"].get("use_smc_graphrag") is True
    finally:
        actual_pid = (st or {}).get("project_id") or "pytest_smc_default_check"
        try:
            delete_project(actual_pid, archive=False, cfg=cfg)
        except Exception:
            pass
        shutil.rmtree(cfg.project_dir(actual_pid), ignore_errors=True)
        shutil.rmtree(cfg.project_publishing_db_dir(actual_pid), ignore_errors=True)
        shutil.rmtree(cfg.e_projects_dir / actual_pid, ignore_errors=True)


def test_scientific_figure_design_drawio_and_lucide_icons(tmp_path: Path) -> None:
    """qhy991/Scientific-Figure-Design 통합 모델(paper-palette + Lucide 벡터 아이콘 + 편집 가능 .drawio + 검증기) 테스트."""
    from scientific_figure_engine import (
        DEFAULT_PAPER_PALETTE,
        generate_editable_drawio_for_spec,
        is_sfd_installed,
        match_lucide_icon_for_text,
    )
    from visual_studio import render_content_diagram_svg

    assert is_sfd_installed() is True
    assert match_lucide_icon_for_text("유전체 QTL 분자표지") == "lucide-dna"
    assert match_lucide_icon_for_text("농약 잔류 독성 ADI") == "lucide-flask-conical"
    assert match_lucide_icon_for_text("습해 배수 기상 스트레스") == "lucide-cloud"

    spec = {
        "style": "content_diagram",
        "title_ko": "그림 1-1. 메밀 생육 모형 및 습해·도복 통합 진단 흐름도",
        "subtitle_ko": "유전형·기상 입력에서 생육 모의와 배수 처방까지의 피드백 체계",
        "data_source": "농촌진흥청 메밀 재배 지침 [SRC-01]",
        "diagram_nodes": [
            {"tag": "STEP 1 · 유전", "label": "품종·유전체 특성 입력", "detail": "단메밀·타타리메밀 생육 계수", "metric": "GDD 기준 950°C·d"},
            {"tag": "STEP 2 · 기상", "label": "토양수분·습해 계측", "detail": "강수량 및 배수 상태 실시간 감지", "metric": "수분장력 -20 kPa"},
            {"tag": "STEP 3 · 모의", "label": "생육 모형 예측 연산", "detail": "개화·결실·도복 위험도 산출", "metric": "RMSE < 8.5%"},
            {"tag": "STEP 4 · 방제", "label": "배수·시비 안전 처방", "detail": "명거배수 정비 및 질소 감량", "metric": "수량 손실 35%↓"},
        ],
        "diagram_edges": ["계수 전달", "스트레스 입력", "처방 도출"],
        "feedback_label": "포장 모니터링 오차 > 10% 시 모형 매개변수 재보정 피드백 루프",
    }
    svg_txt = render_content_diagram_svg(spec)
    assert 'aria-label="lucide-dna"' in svg_txt
    assert 'aria-label="lucide-cloud"' in svg_txt or 'aria-label="lucide-gauge"' in svg_txt

    from config import get_config

    out_drawio = tmp_path / "fig_test_v01.drawio"
    tmp_pid = "tmp_sfd_unit_test_project"
    cfg = get_config()
    try:
        res = generate_editable_drawio_for_spec(
            project_id=tmp_pid,
            figure_id="fig_test_v01",
            spec=spec,
            nodes=spec["diagram_nodes"],
            edges=spec["diagram_edges"],
            feedback_label=spec["feedback_label"],
            out_drawio_path=out_drawio,
            validate=True,
        )
        assert res["status"] == "OK", res
        assert out_drawio.is_file() and out_drawio.stat().st_size > 1500
        assert Path(res["icons_manifest_path"]).is_file()
        assert res.get("palette_sha256")
    finally:
        import shutil

        shutil.rmtree(cfg.project_dir(tmp_pid), ignore_errors=True)


def test_v2_projects_publishing_db_and_frontend_routes() -> None:
    """v2 아키텍처(projects_v2 · publishing_DB 미러링 · 지식그래프 · 반응형 프론트엔드 라우트) 통합 테스트."""
    import shutil
    from fastapi.testclient import TestClient
    from dashboard.agents_app import app
    from config import get_config
    from publishing_db import build_project_knowledge_graph, list_publishing_db_assets
    from subagent_orchestrator import create_project, delete_project

    cfg = get_config()
    assert cfg.projects_dir.name == "projects_v2"
    assert cfg.legacy_projects_dir.name == "projects"
    assert cfg.publishing_db_dir.name == "publishing_DB"

    client = TestClient(app)
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "SMC 출판 스튜디오" in r_index.text
    assert "/app-assets/styles.css" in r_index.text

    assert client.get("/legacy").status_code == 200
    assert client.get("/app-assets/styles.css").status_code == 200
    assert client.get("/app-assets/graph_view.js").status_code == 200
    assert client.get("/app-assets/app.js").status_code == 200

    boot = client.get("/api/v2/bootstrap")
    assert boot.status_code == 200
    bdata = boot.json()
    assert bdata["workspace_info"]["projects_dir_name"] == "projects_v2"
    assert bdata["workspace_info"]["publishing_db_name"] == "publishing_DB"

    st = create_project(
        topic_ko="테스트 스마트 원예 수분관리",
        topic_en="Smart Horticulture Moisture Management",
        keywords_ko=["스마트팜", "토양수분", "관수"],
        project_id_override="pytest_v2_clean_smoke",
        cfg=cfg,
    )
    pid = st["project_id"]
    try:
        proj_dir = cfg.project_dir(pid)
        pub_db_dir = cfg.project_publishing_db_dir(pid)
        assert proj_dir.parent.name == "projects_v2"
        assert pub_db_dir.parent.name == "publishing_DB"
        assert pub_db_dir.name == proj_dir.name
        for sub in ("captures", "pdfs", "reference_images", "web_pages", "knowledge_graph", "evidence"):
            assert (pub_db_dir / sub).is_dir()

        db_res = list_publishing_db_assets(pid, cfg=cfg)
        assert db_res["project_id"] == pid

        kg_res = build_project_knowledge_graph(pid, cfg=cfg)
        assert kg_res["stats"]["nodes"] >= 1
        assert (pub_db_dir / "knowledge_graph" / "kg_graph.json").is_file()

        r_db = client.get(f"/api/v2/projects/{pid}/publishing-db")
        assert r_db.status_code == 200
        r_kg = client.get(f"/api/v2/projects/{pid}/knowledge-graph")
        assert r_kg.status_code == 200
        assert len(r_kg.json()["nodes"]) >= 1
    finally:
        delete_project(pid, archive=False, cfg=cfg)
        shutil.rmtree(cfg.project_dir(pid), ignore_errors=True)
        shutil.rmtree(cfg.project_publishing_db_dir(pid), ignore_errors=True)




