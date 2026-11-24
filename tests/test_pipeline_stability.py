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
    from config import get_config
    from subagent_orchestrator import create_project, delete_project

    cfg = get_config()
    pid = "_pytest_smc_default_check"
    try:
        st = create_project(
            topic_ko="테스트 메밀 생육 분석",
            topic_en="Test Buckwheat Growth Analysis",
            project_id_override=pid,
            cfg=cfg,
        )
        assert st["options"].get("use_smc_graphrag") is True
    finally:
        import shutil
        try:
            delete_project(pid, archive=False, cfg=cfg)
        except Exception:
            pass
        shutil.rmtree(cfg.project_dir(pid), ignore_errors=True)
        shutil.rmtree(cfg.e_projects_dir / pid, ignore_errors=True)


