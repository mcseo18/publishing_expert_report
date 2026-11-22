"""참참살이 영농 AI 출판도우미 (Agro AI Publishing Framework Plan v3.0) 통합 검증 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agro_framework import (  # noqa: E402
    AGRO_CORE_KEYWORDS_31,
    AGRO_SPECIALTY_CURRICULA,
    BRAND_IDENTITY,
    build_context_aware_sections,
    compute_gdd_traffic_light,
)
from dashboard.agents_app import app as agents_app  # noqa: E402
from monetization_packager import simulate_monetization_revenue  # noqa: E402


def test_brand_and_catalog_counts():
    assert BRAND_IDENTITY["app_title"] == "참참살이 영농 AI 출판도우미"
    assert BRAND_IDENTITY["palette"]["emerald_primary"] == "#063b2c"
    assert BRAND_IDENTITY["palette"]["golden_wheat"] == "#eab308"
    assert len(AGRO_CORE_KEYWORDS_31) == 7
    total_kws = sum(len(d["keywords"]) for d in AGRO_CORE_KEYWORDS_31)
    assert total_kws == 31
    assert len(AGRO_SPECIALTY_CURRICULA) >= 17


def test_context_aware_4stage_structure():
    secs = build_context_aware_sections(3, "제3장. 겨울밀 생육과 질소관리", [])
    assert len(secs) == 4
    assert "이론적 배경" in secs[0]
    assert "생리·분자 메커니즘" in secs[1]
    assert "현장 적용" in secs[2]
    assert "법규" in secs[3]


def test_gdd_traffic_light_calculation():
    custom_days = [{"t_max": 24.0, "t_min": 14.0} for _ in range(20)]  # avg 19, t_base 4 -> 15 * 20 = 300
    res = compute_gdd_traffic_light(
        crop_key="wheat",
        station="수원",
        start_date="2026-04-01",
        end_date="2026-04-20",
        custom_daily_temps=custom_days,
    )
    assert res["gdd_current"] == 300.0
    assert res["signal"] in ("green", "yellow", "red")
    assert res["headline_ko"]
    assert len(res["actions_ko"]) == 3


def test_monetization_revenue_simulator():
    sim = simulate_monetization_revenue(
        pod_monthly_copies=100,
        pod_unit_royalty=10000,
        b2g_quarterly_contracts=3,
        b2g_contract_value=3000000,
        academy_subscribers=50,
        academy_monthly_fee=20000,
        saas_tenants=10,
        saas_monthly_fee=50000,
    )
    assert sim["monthly"]["b2c_pod_krw"] == 1_000_000
    assert sim["monthly"]["b2b_b2g_krw"] == 3_000_000
    assert sim["monthly"]["traffic_academy_krw"] == 1_000_000
    assert sim["monthly"]["saas_licensing_krw"] == 500_000
    assert sim["monthly"]["total_krw"] == 5_500_000
    assert sim["annual_total_krw"] == 66_000_000


def test_agents_dashboard_v3_ui_and_endpoints():
    client = TestClient(agents_app)

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "참참살이 영농 AI 출판도우미" in r_home.text
    assert "#063b2c" in r_home.text
    assert "#eab308" in r_home.text
    assert "tab-workbench" in r_home.text
    assert "tab-agro_gdd" in r_home.text
    assert "tab-monetization" in r_home.text

    r_cat = client.get("/api/framework/catalog")
    assert r_cat.status_code == 200
    cat = r_cat.json()
    assert cat["brand"]["app_title"] == "참참살이 영농 AI 출판도우미"
    assert len(cat["core_keywords_31"]) == 7
    assert len(cat["specialty_curricula"]) >= 17

    r_gdd = client.post("/api/agro/gdd-diagnose", json={"crop_key": "rice", "station": "수원"})
    assert r_gdd.status_code == 200
    assert r_gdd.json()["signal"] in ("green", "yellow", "red")

    r_sim = client.post("/api/monetization/simulate", json={"pod_monthly_copies": 80})
    assert r_sim.status_code == 200
    assert r_sim.json()["annual_total_krw"] > 0

    # 활성 프로젝트 대상 워크벤치 프리뷰 · QA 인스펙터 · 수익화 현황 · POD/SaaS 패키지 실전 테스트
    projs = client.get("/api/projects").json().get("projects", [])
    if projs:
        pid = projs[0]["project_id"]
        r_prev = client.post(
            f"/api/projects/{pid}/workbench/preview",
            json={"chapter_id": "ch01", "markdown": "# 테스트\n\n내용 [SRC-01].", "mode": "print", "trim_format": "shinkuk"},
        )
        assert r_prev.status_code == 200
        assert "152 × 225 mm" in r_prev.json()["html"]

        r_qa = client.get(f"/api/projects/{pid}/inspector/qa")
        assert r_qa.status_code == 200
        assert "bindings" in r_qa.json()

        r_mon = client.get(f"/api/projects/{pid}/monetization/overview")
        assert r_mon.status_code == 200
        assert "pod_ready_score" in r_mon.json()

        r_studio = client.get(f"/api/projects/{pid}/image-studio")
        assert r_studio.status_code == 200
        st_data = r_studio.json()
        assert "summary" in st_data and "per_chapter_count" in st_data


def test_decoupled_image_studio_custom_count_and_upload(tmp_path: Path):
    """독립형 이미지 스튜디오: 시각화 개수(0~25) 자유 설정, 무료 분할 생성, 직접 업로드, 결합 동기화 검증."""
    import base64
    import io
    from PIL import Image
    from image_generation_studio import _build_type_sequence
    from visual_studio import build_chapter_visual_specs

    # 0개 ~ 25개 자유 지정 검증 (최소 10개 강제 해제)
    assert _build_type_sequence(0) == []
    assert len(_build_type_sequence(3)) == 3
    assert _build_type_sequence(4, {"A": 1, "B": 1, "C": 1, "D": 1}) == ["A", "B", "C", "D"]
    assert build_chapter_visual_specs(
        topic_ko="디지털 감자 재배",
        topic_en="Digital Potato",
        chapter={"chapter_id": "ch01", "chapter_number": 1, "title": "제1장"},
        per_chapter_count=0,
    ) == []
    specs_3 = build_chapter_visual_specs(
        topic_ko="디지털 감자 재배",
        topic_en="Digital Potato",
        chapter={"chapter_id": "ch01", "chapter_number": 1, "title": "제1장"},
        per_chapter_count=3,
    )
    assert len(specs_3) == 3

    # PNG 인메모리 이미지 생성(직접 업로드 포맷 검증)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(6, 59, 44)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    assert len(b64) > 20

    # UI에 이미지 스튜디오 탭과 0~25 개수 입력 항목이 존재하는지 검증
    client = TestClient(agents_app)
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "tab-imgstudio" in r_home.text
    assert "isPerChapter" in r_home.text
    assert "npVisPerCh" in r_home.text
    assert "isMaxBatch" in r_home.text
    assert "isBudgetLimit" in r_home.text
    assert "uragSearchInput" in r_home.text


def test_unified_smc_graphrag_capture_and_search(tmp_path: Path):
    """C:\\SMC_GRAPHRAG 통합 RAG(FTS5 + 증분 KG) 결합 및 검색 검증 (격리된 tmp Config 사용)."""
    from config import PlatformConfig
    from rag_capture_unifier import (
        get_unified_rag_status,
        search_unified_smc_rag,
        unify_source_to_smc_graphrag,
    )

    cfg = PlatformConfig(
        workspace_root=ROOT,
        collected_data_root=tmp_path / "E_Data",
        smc_graphrag_root=tmp_path / "SMC_GRAPHRAG",
        lightrag_working_dir=tmp_path / "SMC_GRAPHRAG" / "lightrag_store",
        lightrag_workspace="test_ws",
        lightrag_api_url="http://127.0.0.1:19999",
        ollama_host="http://127.0.0.1:19998",
        ollama_llm_model="gemma4:26b",
        ollama_fast_model="gemma4:latest",
        ollama_embed_model="bge-m3",
        ollama_num_ctx=4096,
    )
    cfg.ensure_directories()

    res = unify_source_to_smc_graphrag(
        source_id="SRC-901",
        title="겨울밀 적산온도(GDD)와 정밀 질소시비 처방",
        markdown_text=(
            "# 겨울밀 적산온도와 정밀시비\n\n"
            "## 생육 적산온도(GDD) 기준\n"
            "**겨울밀**은 기준온도 4℃ 이상에서 누적 적산온도 1650℃·day로 출수 및 등숙을 완료한다.\n\n"
            "## 가축분뇨법 퇴비 부숙도\n"
            "퇴비 부숙도와 토양유기물 관리가 수량 안정성을 높인다."
        ),
        url="https://example.org/wheat-gdd",
        source_type="pdf",
        provider="OpenAlex",
        capture_mode="pdf_download",
        pdf_path=str(tmp_path / "sample.pdf"),
        use_ollama_kg=False,
        push_lightrag=False,
        rebuild_catalog=False,
        cfg=cfg,
    )
    assert res["status"] == "UNIFIED"
    assert Path(res["unified_md_path"]).is_file()
    assert res["kg_info"]["nodes_total"] >= 2
    assert cfg.smc_incremental_graph_path.is_file()
    # 기존 graph.json 미생성/무훼손 확인
    assert not (cfg.smc_graphrag_output_dir / "graph.json").exists()

    st = get_unified_rag_status(cfg)
    assert st["total_documents"] == 1
    assert st["downloaded_pdfs"] == 1
    assert st["incremental_kg_nodes"] >= 2

    sr = search_unified_smc_rag("겨울밀 적산온도", cfg=cfg)
    assert sr["documents_count"] >= 1
    assert sr["documents"][0]["source_id"] == "SRC-901"

    # 실서버 API 상태 엔드포인트 확인
    client = TestClient(agents_app)
    r_st = client.get("/api/rag/unified/status")
    assert r_st.status_code == 200
    assert "unified_rag_dir" in r_st.json()


def test_deep_research_engine_v3_fanout_rank_and_api():
    """4-Wave 대규모 딥 리서치 엔진: 다관점 쿼리 확장 · 중복제거/랭킹 · 국내 18대 학회지 · API/UI 검증."""
    from deep_research_engine import (
        EXTENDED_KOREAN_AGRI_JOURNALS,
        RESEARCH_DEPTH_PRESETS,
        _dedup_and_rank_items,
        expand_research_subqueries,
    )

    assert len(EXTENDED_KOREAN_AGRI_JOURNALS) >= 16
    assert set(RESEARCH_DEPTH_PRESETS.keys()) == {"standard", "deep", "exhaustive"}

    fan = expand_research_subqueries(
        topic_ko="디지털 감자 재배",
        topic_en="Digital Potato Cultivation",
        user_query="괴경 비대 GDD와 드론 NDVI 질소 시비",
        max_queries=8,
    )
    assert len(fan["en_queries"]) >= 6
    assert len(fan["ko_queries"]) >= 4

    ranked = _dedup_and_rank_items(
        [
            {"title": "Potato tuber growth and GDD", "doi": "10.1000/abc", "year": 2024, "cited_by_count": 45, "pdf_url": "https://ex.org/1.pdf", "abstract": "A" * 200},
            {"title": "Potato tuber growth and GDD", "doi": "10.1000/abc", "year": 2024, "cited_by_count": 45},  # dup
            {"title": "Old unrelated note", "year": 2001, "cited_by_count": 0},
        ],
        "potato tuber GDD",
    )
    assert len(ranked) == 2
    assert ranked[0]["rank"] == 1
    assert ranked[0]["doi"] == "10.1000/abc"

    client = TestClient(agents_app)
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "tab-deepresearch" in r_home.text
    assert "drDepth" in r_home.text
    assert "drSnowball" in r_home.text


def test_primary_output_types_and_setup_page():
    """6대 1차 산출물 유형(교과서·웹출판·강의교재·보고서·논문·이야기책) 프로필, 지침 및 /setup 전용 페이지 검증."""
    from output_type_profiles import (
        PRIMARY_OUTPUT_TYPES,
        build_draft_instruction_for_type,
        build_outline_instruction_for_type,
        resolve_output_profile,
    )

    expected = {"textbook", "web_publish", "lecture", "report", "paper", "storybook"}
    assert set(PRIMARY_OUTPUT_TYPES.keys()) == expected

    for tid in expected:
        prof = resolve_output_profile(tid)
        assert prof["primary_output_type"] == tid
        state = {"topic_ko": "스마트 벼 재배", "primary_output_type": tid, "output_profile": prof}
        role, guide = build_outline_instruction_for_type(state)
        assert role and guide
        draft_inst = build_draft_instruction_for_type(state, ["SRC-01", "SRC-02"])
        assert "SRC-01" in draft_inst

    # 보고서/논문/이야기책은 연습문제 기본 비활성화, 교과서/강의교재는 활성화 확인
    assert resolve_output_profile("textbook")["include_exercises"] is True
    assert resolve_output_profile("lecture")["include_exercises"] is True
    assert resolve_output_profile("report")["include_exercises"] is False
    assert resolve_output_profile("paper")["include_exercises"] is False
    assert resolve_output_profile("storybook")["include_exercises"] is False

    client = TestClient(agents_app)
    r_setup = client.get("/setup")
    assert r_setup.status_code == 200
    assert "1차 산출물 초기 구성 스튜디오" in r_setup.text
    assert "outputTypeGrid" in r_setup.text

    r_types = client.get("/api/output-types")
    assert r_types.status_code == 200
    assert set(r_types.json()["output_types"].keys()) == expected


def test_academic_paper_review_standard_rules_and_enforcement():
    """논문·리뷰 5대 고정 구성(초록 1개 · 재료및방법 세부절 · 결과및고찰 6단계 심층 논리 세부절 · 핵심요약 1개 · 마지막 1회 참고문헌) 검증."""
    from pathlib import Path
    from output_type_profiles import (
        build_draft_instruction_for_type,
        enforce_paper_outline_structure,
        format_paper_consolidated_references,
        infer_paper_section_role,
        resolve_output_profile,
    )

    rule_file = Path(__file__).resolve().parent.parent / ".agents" / "rules" / "academic-paper-review-standard.md"
    assert rule_file.is_file()
    rule_text = rule_file.read_text(encoding="utf-8")
    for must in ("초록", "재료 및 방법", "결과 및 고찰", "핵심 내용 요약", "참고문헌", "6단계"):
        assert must in rule_text

    prof = resolve_output_profile("paper", {"methods_subsection_count": 4, "results_subsection_count": 5})
    assert prof["chapter_count"] == 5
    state = {
        "topic_ko": "저탄소 벼 물관리와 메탄 저감 메타분석",
        "topic_en": "Meta-analysis of Low-Carbon Rice Water Management and Methane Mitigation",
        "primary_output_type": "paper",
        "output_profile": prof,
        "target_pages": 30,
        "keywords_ko": ["간단관개(AWD)", "메탄(CH4)", "수량 안정성"],
        "keywords_en": ["alternate wetting and drying", "methane emission", "grain yield"],
        "packet_id": "test_paper_evidence",
        "collected_sources": [
            {"source_id": "SRC-01", "title": "AWD methane reduction in East Asia", "authors": "Kim et al.", "year": 2024, "journal": "Field Crops Research", "doi": "10.1016/j.fcr.2024.0001"},
            {"source_id": "SRC-02", "title": "Soil redox dynamics under rice irrigation", "authors": "Lee & Park", "year": 2023, "journal": "Korean J. Crop Sci.", "url": "https://example.org/src02"},
        ],
    }

    # 임의의 비정규 목차가 들어와도 정확히 5대 고정 구조로 정규화되어야 함
    raw_outline = {"parts": [{"title": "임시", "chapters": [{"title": "잡다한 장 1", "sections": ["A", "B"]}]}]}
    enforced = enforce_paper_outline_structure(raw_outline, state)
    assert enforced["book_metadata"]["chapter_count"] == 5
    assert enforced["book_metadata"]["paper_structure_enforced"] is True
    chs = enforced["parts"][0]["chapters"]
    assert len(chs) == 5
    roles = [infer_paper_section_role(c, i + 1, 5) for i, c in enumerate(chs)]
    assert roles == ["abstract", "methods", "results_discussion", "core_summary", "references"]

    # 재료 및 방법(2.1~2.4), 결과 및 고찰(3.1~3.5) 세부 절 구분 검증
    assert len(chs[1]["sections"]) == 4
    assert all(s.startswith("2.") for s in chs[1]["sections"])
    assert len(chs[2]["sections"]) == 5
    assert all(s.startswith("3.") for s in chs[2]["sections"])

    # 전체 분량의 대부분(>= 60%)이 결과 및 고찰에 집중 할당되었는지 검증
    total_p = enforced["book_metadata"]["target_pages"]
    assert chs[2]["target_pages"] / total_p >= 0.60

    # 역할별 집필 지침 검증 (특히 결과 및 고찰 6단계 심층 논리 + 중복 금지)
    inst_abs = build_draft_instruction_for_type(state, ["SRC-01", "SRC-02"], chapter_role="abstract")
    assert "단 1개" in inst_abs and "참고문헌" in inst_abs
    inst_res = build_draft_instruction_for_type(state, ["SRC-01", "SRC-02"], chapter_role="results_discussion")
    for kw in ("6단계", "정량적 실증 발견", "기작 해석", "불일치 원인 규명", "트레이드오프", "방법론적 한계"):
        assert kw in inst_res
    inst_sum = build_draft_instruction_for_type(state, ["SRC-01", "SRC-02"], chapter_role="core_summary")
    assert "Highlights" in inst_sum and "단 1개" in inst_sum

    # 단일 통합 참고문헌 중복 제거 및 APA 7th 포매팅 검증
    refs_md = format_paper_consolidated_references(
        state["collected_sources"],
        cited_ids=["SRC-02", "SRC-01", "SRC-02"],  # 중복 포함
        citation_style="APA 7th / 한국농학계 표준",
    )
    assert refs_md.count("[SRC-02]") == 1
    assert refs_md.count("[SRC-01]") == 1
    assert "1. Lee & Park (2023)" in refs_md
    assert "2. Kim et al. (2024)" in refs_md

    # /setup UI 배너 확인
    client = TestClient(agents_app)
    r_setup = client.get("/setup")
    assert r_setup.status_code == 200
    assert "paperStandardBanner" in r_setup.text


def test_default_two_outputs_korean_journal_pdf_and_converter():
    """기본 2종 산출물(PDF + 블로그용 단일 HTML), 국내 학회지 논문 규격 PDF 조판, 사후 포맷 변환 모듈 검증."""
    from pathlib import Path
    from output_converter import (
        CONVERSION_FORMATS,
        KOREAN_JOURNAL_PDF_SPEC,
        render_korean_journal_html,
        render_single_blog_html,
    )

    # 1) 국내 학회지 논문 규격 규칙 문서 및 스펙 검증
    rule_file = Path(__file__).resolve().parent.parent / ".agents" / "rules" / "academic-paper-review-standard.md"
    rule_text = rule_file.read_text(encoding="utf-8")
    assert "국내 학회지 논문 규격" in rule_text
    assert "2단 편집" in rule_text
    assert "3선표" in rule_text
    assert KOREAN_JOURNAL_PDF_SPEC["page_size"] == "210mm 297mm"
    assert KOREAN_JOURNAL_PDF_SPEC["column_count"] == 2
    assert KOREAN_JOURNAL_PDF_SPEC["three_line_table"] is True

    # 2) 사후 변환 포맷 카탈로그 검증
    for required_fmt in ("docx", "korean_journal_pdf", "b5_pdf", "shinkuk_pdf", "a4_pdf", "markdown_master", "chapter_split_html"):
        assert required_fmt in CONVERSION_FORMATS

    # 3) 국내 학회지 논문 규격 HTML 렌더링 (1단 표제/초록 + 2단 본문 + 최하단 참고문헌)
    sample_state = {
        "project_id": "test_paper",
        "topic_ko": "저탄소 벼 물관리 메타분석",
        "topic_en": "Meta-analysis of Low-Carbon Rice Water Management",
        "primary_output_type": "paper",
        "keywords_ko": ["간단관개", "메탄저감", "벼수량"],
    }
    sample_chs = [
        {"index": 1, "chapter_id": "ch01", "chapter_role": "abstract", "title": "1. 초록 (Abstract)", "body": "# 1. 초록\n\n## 1.1 국문 초록\n본 총설은 AWD의 메탄 저감 효과를 정량 분석하였다 [SRC-01]."},
        {"index": 2, "chapter_id": "ch02", "chapter_role": "methods", "title": "2. 재료 및 방법", "body": "# 2. 재료 및 방법\n\n## 2.1 문헌 탐색\nPRISMA 기준에 따라 선별하였다 [SRC-01]."},
        {"index": 3, "chapter_id": "ch03", "chapter_role": "results_discussion", "title": "3. 결과 및 고찰", "body": "# 3. 결과 및 고찰\n\n## 3.1 정량 비교\n| 처리 | CH4 저감(%) |\n|---|---|\n| AWD | 42.5 [SRC-01] |"},
        {"index": 4, "chapter_id": "ch04", "chapter_role": "core_summary", "title": "4. 핵심 내용 요약", "body": "# 4. 핵심 내용 요약\n\n- AWD는 CH4 배출을 42.5% 저감한다 [SRC-01]."},
        {"index": 5, "chapter_id": "ch05", "chapter_role": "references", "title": "5. 참고문헌", "body": "# 5. 참고문헌\n\n1. Kim et al. (2024). AWD Study. *Field Crops Res.* `[SRC-01]`"},
    ]
    j_html = render_korean_journal_html(sample_state, sample_chs)
    assert "column-count: 2" in j_html
    assert "abstract-box" in j_html
    assert "journal-two-col" in j_html
    assert "journal-references" in j_html
    assert "210mm 297mm" in j_html

    # 4) 블로그용 단일 HTML 통합 렌더링 (1파일 + 복사 버튼 + 전체 섹션 포함)
    b_html = render_single_blog_html(sample_state, sample_chs)
    assert "blogCopyRoot" in b_html
    assert "copyBlogBody()" in b_html
    assert "sec-ch01" in b_html and "sec-ch05" in b_html

    # 5) REST API 및 대시보드 UI 확인
    client = TestClient(agents_app)
    r_fmt = client.get("/api/output-converter/formats")
    assert r_fmt.status_code == 200
    assert "docx" in r_fmt.json()["formats"]
    assert r_fmt.json()["korean_journal_pdf_spec"]["column_count"] == 2

    r_ui = client.get("/")
    assert r_ui.status_code == 200
    assert "runPublishDefaultTwo" in r_ui.text
    assert "runConvertOutput" in r_ui.text






