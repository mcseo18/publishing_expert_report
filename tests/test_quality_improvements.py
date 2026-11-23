"""2026-11-23 품질 개선 방안(P1~P15, C1~C9, V1~V9) 단위·통합 회귀 테스트."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_c1_domain_preset_and_portal_homepage_exclusion() -> None:
    from fetch_project_sources import detect_domain_preset, is_portal_homepage_url

    # 양파 재배 목차에 '수확·저장' 키워드가 포함되어도 postharvest가 아닌 onion 프리셋을 선택해야 함 (P1/C1)
    preset = detect_domain_preset(
        topic_ko="스마트 팜 양파 재배",
        topic_en="Smart Farm Onion Cultivation",
        keywords_ko=["양파", "점적관개", "수확", "저장", "품질평가"],
        keywords_en=["onion", "drip irrigation", "harvest", "storage"],
    )
    assert preset == "onion"

    # 3차원 이미지 모델 논문이 postharvest에 오염되지 않고 3d_vision 선택
    assert detect_domain_preset("작물 대상 3차원 이미지 모델 개발", "Development of 3D image model for crops") == "3d_vision"

    # 기관 첫 화면 및 위키 개괄은 근거 목록 제외 판정 (C1)
    assert is_portal_homepage_url("https://www.rda.go.kr/") is True
    assert is_portal_homepage_url("https://www.krei.re.kr/krei/index.do") is True
    assert is_portal_homepage_url("https://www.naro.go.jp/english/laboratory/nfri/index.html") is True
    assert is_portal_homepage_url("https://ko.wikipedia.org/wiki/%EC%97%90%ED%8B%B8%EB%A0%8C") is True
    # 실제 학술 논문 DOI는 근거로 허용
    assert is_portal_homepage_url("https://doi.org/10.1016/j.agwat.2022.107500") is False


def test_c7_standard_equation_library_and_error_detection() -> None:
    from math_typography import format_equations_for_prompt, load_standard_equations, validate_known_formulas

    eqs = load_standard_equations()
    ids = {e["id"] for e in eqs}
    for req in ("fao56_penman_monteith", "crop_evapotranspiration", "christiansen_cu", "drip_emission_uniformity", "cwsi_idso_jackson", "mad_raw_soil_water", "gdd_thermal_time", "q10_respiration"):
        assert req in ids

    prompt_blk = format_equations_for_prompt("Penman-Monteith 증발산량 ET0 점적관개 CU CWSI")
    assert "0.34 u" in prompt_blk
    assert "Allen" in prompt_blk

    # P2~P5 실제 오류 원고 패턴을 모두 탐지해야 함
    bogus_md = """
    ET_0 = 0.408 Δ (R_n - G) + γ (900 e_s (1 - u/2c_a)) / (Δ + γ (1 - 0.35))
    작물 증발산량은 ET<sub>c</sub> = K<sub>c</sub> × E 로 계산된다.
    CU = Average Application Rate / Maximum Application Rate
    CWSI = f(θ_actual, θ_wilting_point, ET_c)
    """
    issues = validate_known_formulas(bogus_md)
    found_eq_ids = {i["equation_id"] for i in issues}
    assert "fao56_penman_monteith" in found_eq_ids
    assert "crop_evapotranspiration" in found_eq_ids
    assert "christiansen_cu" in found_eq_ids
    assert "cwsi_idso_jackson" in found_eq_ids


def test_c6_p15_verify_citations_format_label_and_formula_gate(tmp_path: Path) -> None:
    from verify_citations import audit_file

    bad_ch = tmp_path / "ch05_bad.mdx"
    bad_ch.write_text(
        "# 제5장 테스트\n\nET<sub>c</sub> = K<sub>c</sub> × E [SRC-01]\n",
        encoding="utf-8",
    )
    res = audit_file(
        bad_ch,
        valid_ids={"SRC-01"},
        ngram_index={},
        source_docs={"SRC-01": {"source_id": "SRC-01", "title": "Plum ethylene postharvest", "text": "plum fruit ethylene storage", "tokens": {"plum", "fruit", "ethylene", "storage"}, "citable": True}},
        semantic=True,
        cfg=None,
    )
    assert any(e["type"] == "INVALID_FORMULA_PATTERN" for e in res["critical_errors"])
    assert res["content_audit"] is not None
    assert res["content_audit"]["unrelated"] == 1


def test_c8_p14_clean_manuscripts_strips_duplicate_h1_h2() -> None:
    from clean_manuscripts import _clean_single_chapter

    raw = (
        "---\nchapter_id: \"ch04\"\n---\n\n"
        "# 4. 핵심 내용 요약 (Core Summary & Highlights)\n\n"
        "## 4. 핵심 내용 요약 (Core Summary & Highlights)\n\n"
        "### 4.1 핵심 연구 발견\n내용 본문.\n"
    )
    cleaned, stats = _clean_single_chapter(raw)
    assert stats["dup_h1_removed"] == 1
    assert "## 4. 핵심 내용 요약" not in cleaned
    assert "# 4. 핵심 내용 요약" in cleaned


def test_v2_v4_v6_v8_visual_studio_no_fake_charts_and_no_placeholders(tmp_path: Path) -> None:
    from figure_registry import _is_placeholder_or_fake_visual
    from visual_studio import build_chapter_visual_specs, format_three_sentence_narrative, render_content_diagram_svg

    # V2: 가짜 수치 차트(comparison_bar, response_curve) 생성 시도 시 예외 발생
    with pytest.raises(ValueError):
        render_content_diagram_svg({"style": "comparison_bar", "title_ko": "test"})
    with pytest.raises(ValueError):
        render_content_diagram_svg({"style": "response_curve", "title_ko": "test"})

    # V4: 내용 기반 구조도 정상 렌더링 (반복 틀 문구 미포함)
    svg = render_content_diagram_svg(
        {
            "style": "content_diagram",
            "title_ko": "그림 5-5. 스마트 관개 제어 루프",
            "claim_ko": "토양장력과 CWSI로 밸브를 자동 제어한다",
            "data_source": "FAO-56",
            "diagram_nodes": [
                {"tag": "1. 계측", "label": "토양장력 15 cm"},
                {"tag": "2. 제어", "label": "밸브 자동 개방"},
            ],
            "feedback_label": "포장용수량 도달 시 종료",
        }
    )
    assert "정량 계측 → 임계 판정 → 현장 처방" not in svg
    assert "실사진/도해 생성 프롬프트 준비됨" not in svg
    assert "자료: FAO-56" in svg

    # V8/V9: 간결한 제목(장 제목 미반복) + 3문장 해설(반복 클리셰 미포함)
    specs = build_chapter_visual_specs(
        topic_ko="스마트 팜 양파 재배",
        topic_en="Smart Farm Onion",
        chapter={"chapter_id": "ch05", "chapter_number": 5, "title": "제5장. 관개", "sections": ["5.1 센서 원리"]},
        per_chapter_count=3,
    )
    assert len(specs) == 3
    for sp in specs:
        assert "제5장. 관개 —" not in sp["title_ko"]
        assert "독자는 이 도해를 통해" not in sp["narrative_ko"]
        assert "(자료:" in sp["narrative_ko"]

    # V6/P8/P9: 빈 틀 SVG 및 가짜 92·84·76·68% SVG는 출판 제외 판정
    fake_svg = tmp_path / "fake.svg"
    fake_svg.write_text("<svg><text>92%</text><text>84%</text><text>76%</text><text>68%</text></svg>", encoding="utf-8")
    assert _is_placeholder_or_fake_visual({"status": "OK", "engine": "vector_svg"}, fake_svg) is True
    assert _is_placeholder_or_fake_visual({"status": "UNGENERATED", "engine": "unrendered_no_api_or_failed"}, fake_svg) is True
    assert _is_placeholder_or_fake_visual({"status": "OK", "engine": "svg_blueprint_ready"}, fake_svg) is True


def test_v2_v8_academic_matplotlib_chart_requires_real_data(tmp_path: Path) -> None:
    from academic_plot_style import generate_drip_hydraulics_chart, generate_swrc_chart, render_data_chart_png

    # 출처 누락 시 거부
    with pytest.raises(ValueError):
        render_data_chart_png(
            out_png=tmp_path / "no_src.png",
            chart_type="line",
            title="Test",
            x_label="x (m)",
            y_label="y (mm)",
            source_note="",
            series=[{"label": "A", "y": [1, 2]}],
            x_values=[1, 2],
        )

    swrc_png = tmp_path / "swrc.png"
    swrc_csv = tmp_path / "swrc.csv"
    generate_swrc_chart(swrc_png, csv_out_path=swrc_csv)
    assert swrc_png.is_file() and swrc_png.stat().st_size > 20_000
    assert swrc_csv.is_file()

    drip_png = tmp_path / "drip.png"
    generate_drip_hydraulics_chart(drip_png)
    assert drip_png.is_file() and drip_png.stat().st_size > 20_000


def test_c4_default_draft_model_is_26b() -> None:
    from config import get_config

    cfg = get_config()
    assert cfg.ollama_llm_model == "gemma4:26b"
    assert cfg.ollama_fast_model == "gemma4:latest"


def test_gemini_cost_leak_guards_and_track_separation() -> None:
    import inspect
    from context_visual_director import NANO_BANANA_MODEL_CHAIN, rebuild_project_visuals_with_nano_banana
    from image_generation_studio import ENGINE_UNIT_COST_USD, start_batch_generation_async
    from output_type_profiles import resolve_output_profile
    from visual_studio import _generate_with_nano_banana

    # 1) 기본 이미지 모델은 저비용 gemini-2.5-flash-image이며 Pro로 자동 에스컬레이션되지 않아야 함
    assert inspect.signature(_generate_with_nano_banana).parameters["model"].default == "gemini-2.5-flash-image"
    assert NANO_BANANA_MODEL_CHAIN[0] == "gemini-2.5-flash-image"
    assert "nano-banana-pro-preview" not in NANO_BANANA_MODEL_CHAIN
    assert inspect.signature(rebuild_project_visuals_with_nano_banana).parameters["primary_model"].default == "gemini-2.5-flash-image"

    # 2) 실제 단가 반영 및 기본 예산 상한 $1.00
    assert ENGINE_UNIT_COST_USD["cited_redraw"] == 0.0
    assert ENGINE_UNIT_COST_USD["nano_banana"] == pytest.approx(0.039)
    assert ENGINE_UNIT_COST_USD["nano_banana_pro"] == pytest.approx(0.134)
    assert inspect.signature(start_batch_generation_async).parameters["budget_limit_usd"].default == pytest.approx(1.0)

    # 3) 논문 리뷰 vs 교과서 시작 트랙 분리 검증
    p_paper = resolve_output_profile("paper")
    p_tb = resolve_output_profile("textbook")
    assert p_paper["workflow_track"] == "paper_review"
    assert p_paper["visual_generation_mode"] == "cited_and_redrawn_only"
    assert p_paper["default_use_nano_banana"] is False
    assert p_paper["visual_priority"]["A"] == 0 and p_paper["visual_priority"]["B"] == 0
    assert p_tb["workflow_track"] == "textbook"
    assert p_tb["visual_generation_mode"] == "hybrid_cited"
    assert p_tb["default_use_nano_banana"] is False


def test_source_visual_harvester_jats_redraw_and_license_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config import PlatformConfig
    from PIL import Image
    from source_visual_harvester import (
        adopt_direct_reuse_figure,
        build_provenance_caption,
        classify_reuse_policy,
        parse_jats_xml_tables_and_figures,
        redraw_chart_from_harvested_table,
        synthesize_multi_source_comparison_chart,
    )

    # 1) 라이선스 판정 검증 (CC-BY 허용, ND/All Rights Reserved 차단)
    assert classify_reuse_policy(license_str="cc-by-4.0", is_oa=True)["can_direct_reuse"] is True
    assert classify_reuse_policy(license_str="CC0", is_oa=True)["can_direct_reuse"] is True
    assert classify_reuse_policy(license_str="공공누리 제1유형", is_oa=True)["can_direct_reuse"] is True
    assert classify_reuse_policy(license_str="cc-by-nd-4.0", is_oa=True)["can_direct_reuse"] is False
    assert classify_reuse_policy(license_str="All Rights Reserved", is_oa=False)["can_direct_reuse"] is False
    assert classify_reuse_policy(license_str="", is_oa=False)["reuse_policy"] == "REDRAW_DATA_ONLY"

    # 2) JATS XML 표·그림 파싱 검증
    sample_jats = """<?xml version="1.0" encoding="UTF-8"?>
    <article xmlns:xlink="http://www.w3.org/1999/xlink">
      <front><article-meta><permissions>
        <license license-type="open-access" xlink:href="https://creativecommons.org/licenses/by/4.0/">
          <license-p>CC-BY 4.0</license-p>
        </license>
      </permissions></article-meta></front>
      <body>
        <table-wrap id="T1">
          <label>Table 1</label>
          <caption><p>3D crop reconstruction accuracy by sensor modality</p></caption>
          <table>
            <thead><tr><th>Method</th><th>RMSE (mm)</th><th>R2</th></tr></thead>
            <tbody>
              <tr><td>LiDAR</td><td>2.4 ± 0.3</td><td>0.96</td></tr>
              <tr><td>SfM-MVS</td><td>4.8 ± 0.7</td><td>0.91</td></tr>
              <tr><td>RGB-D</td><td>6.2 ± 0.9</td><td>0.87</td></tr>
            </tbody>
          </table>
        </table-wrap>
        <fig id="F1">
          <label>Fig. 1</label>
          <caption><p>Multi-view camera rig for tomato canopy 3D modeling</p></caption>
          <graphic xlink:href="agronomy-14-00312-g001.jpg"/>
        </fig>
      </body>
    </article>"""

    out_dir = tmp_path / "extracted"
    parsed = parse_jats_xml_tables_and_figures(
        xml_text=sample_jats,
        source_meta={
            "source_id": "SRC-901",
            "title": "3D Crop Phenotyping",
            "authors": "Kim, J., Lee, S.",
            "year": 2024,
            "journal": "Agronomy",
            "doi": "https://doi.org/10.3390/agronomy14020312",
            "is_oa": True,
        },
        out_dir=out_dir,
        pmcid="PMC10888888",
    )
    assert parsed["policy"]["can_direct_reuse"] is True
    assert len(parsed["tables"]) == 1
    assert parsed["tables"][0]["plottable"] is True
    assert len(parsed["figures"]) == 1
    assert "PMC10888888" in parsed["figures"][0]["remote_image_url"]

    # 3) 격리된 임시 프로젝트 환경에서 표 → 300 DPI 그래프 재작성, 메타 통합, CC-BY 직접 인용 & 비-CC-BY 차단 검증
    cfg = PlatformConfig(
        workspace_root=tmp_path / "ws",
        collected_data_root=tmp_path / "e_data",
        smc_graphrag_root=tmp_path / "kg",
        lightrag_working_dir=tmp_path / "kg" / "lightrag_store",
        lightrag_workspace="test_ws",
        lightrag_api_url="http://127.0.0.1:9621",
        ollama_host="http://127.0.0.1:11434",
        ollama_llm_model="gemma4:26b",
        ollama_fast_model="gemma4:latest",
        ollama_embed_model="bge-m3",
        ollama_num_ctx=8192,
        active_project="paper_test",
    )
    cfg.ensure_directories()
    pid = "paper_test"
    (cfg.project_dir(pid) / "assets").mkdir(parents=True, exist_ok=True)
    state_dir = cfg.index_dir / "subagent_runs" / pid
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps({"project_id": pid, "primary_output_type": "paper", "workspace_dir": str(cfg.project_dir(pid))}, ensure_ascii=False),
        encoding="utf-8",
    )

    # 로컬 CC-BY 테스트 PNG와 비-CC-BY 차단 테스트 그림 자산 구성
    cc_png = tmp_path / "cc_fig.png"
    Image.new("RGB", (320, 240), (240, 248, 255)).save(cc_png)
    fig_cc = dict(parsed["figures"][0])
    fig_cc["local_image_path"] = str(cc_png)
    fig_blocked = dict(parsed["figures"][0])
    fig_blocked["asset_id"] = "src-902_blocked_f01"
    fig_blocked["can_direct_reuse"] = False
    fig_blocked["reuse_policy"] = "REDRAW_DATA_ONLY"
    fig_blocked["license_normalized"] = "All Rights Reserved"

    idx_payload = {"project_id": pid, "assets": [parsed["tables"][0], fig_cc, fig_blocked]}
    (cfg.project_dir(pid) / "assets" / "harvested_visual_assets.json").write_text(
        json.dumps(idx_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # (a) 출처 표 → 300 DPI 논문 흑백 대응 그래프 재작성 (0원)
    redrawn = redraw_chart_from_harvested_table(
        project_id=pid,
        asset_id=parsed["tables"][0]["asset_id"],
        chapter_id="ch03",
        figure_no="그림 3-1",
        title_ko="센서별 3D 작물 복원 정확도 비교",
        cfg=cfg,
    )
    assert Path(redrawn["visual"]["path"]).is_file()
    assert Path(redrawn["visual"]["data_csv_path"]).is_file()
    assert "[SRC-901]" in redrawn["visual"]["source_note"]
    assert "Adapted from" in redrawn["visual"]["source_note"]

    # (b) 다중 문헌 메타 비교 차트 통합 재작성 (0원)
    meta_res = synthesize_multi_source_comparison_chart(
        project_id=pid,
        chapter_id="ch03",
        figure_no="그림 3-2",
        title_ko="선행 연구별 3D 초고 추정 오차 비교",
        x_label="연구 (기법)",
        y_label="RMSE (mm)",
        records=[
            {"label": "Kim et al. (LiDAR)", "value": 2.4, "yerr": 0.3, "source_id": "SRC-901"},
            {"label": "Park et al. (SfM)", "value": 4.5, "yerr": 0.6, "source_id": "SRC-905"},
        ],
        cfg=cfg,
    )
    assert Path(meta_res["visual"]["path"]).is_file()
    assert "SRC-901" in meta_res["visual"]["source_note"] and "SRC-905" in meta_res["visual"]["source_note"]

    # (c) CC-BY 그림 직접 인용 허용 & 비-CC-BY 그림 차단 검증
    adopted = adopt_direct_reuse_figure(project_id=pid, asset_id=fig_cc["asset_id"], chapter_id="ch03", cfg=cfg)
    assert Path(adopted["visual"]["path"]).is_file()
    assert "CC-BY" in adopted["visual"]["source_note"].upper()
    assert "[SRC-901]" in adopted["visual"]["source_note"]

    with pytest.raises(PermissionError):
        adopt_direct_reuse_figure(project_id=pid, asset_id=fig_blocked["asset_id"], chapter_id="ch03", cfg=cfg)

    cap = build_provenance_caption(provenance_type="direct_reuse", title_ko="제목", source_meta=fig_cc, orig_label="Fig. 1")
    assert "Fig. 1" in cap and "[SRC-901]" in cap


def test_universal_scientific_typography_across_all_formats(tmp_path: Path) -> None:
    from docx import Document
    from math_typography import (
        add_rich_runs_to_docx_paragraph,
        detect_unformatted_math_leaks,
        normalize_scientific_typography,
    )

    sample = (
        "이방성 3D 가우시안 타원체(위치 $\\boldsymbol{\\mu}$, 공분산 $\\boldsymbol{\\Sigma}$, 불투명도 $\\alpha$, "
        "시선 $(\\theta, \\phi)$, 관련도 $\\ge 0.44$, 결정계수 $R^2 > 0.94$, 인스턴스 $AP_{50}$ = 0.924)와 "
        "토양 화학 반응 $\\ce{NH4+ + 2 O2 -> NO3- + H2O + 2 H+}$ 및 평문 CO2, CH4, NO3-, Ca2+, PO4^3-, "
        "엽면적 8.98 cm2, LAI 1.45 m2/m2, 비용 $0.039/장, 모델 F2DMAS/Plant3R/CLCFM3, "
        "URL https://doi.org/10.1016/j.plaphe.2026.100200 [SRC-393].\n\n"
        "$$\\mathrm{CD}(P, Q) = \\frac{1}{|P|} \\sum_{\\mathbf{p} \\in P} \\min_{\\mathbf{q} \\in Q} \\|\\mathbf{p} - \\mathbf{q}\\|_2^2, "
        "\\qquad \\mathrm{RMSE} = \\sqrt{\\frac{1}{n} \\sum_{i=1}^{n} (\\hat{y}_i - \\bar{y})^2}$$"
    )

    # 1) HTML / Blog HTML / DOCX / Plain 4개 포맷 모두 미변환 LaTeX 누수 0건
    for fmt in ("html", "blog_html", "docx", "plain"):
        out = normalize_scientific_typography(sample, target_format=fmt)
        leaks = detect_unformatted_math_leaks(out)
        assert leaks == [], f"Leak in format={fmt}: {leaks}"
        assert "μ" in out and "Σ" in out and "α" in out and "≥" in out
        assert "‖" in out and "∑" in out and "∈" in out and "√" in out
        assert "ŷ" in out and "ȳ" in out
        # URL·달러 통화·모델명은 손상되지 않아야 함
        assert "$0.039" in out
        assert "F2DMAS/Plant3R/CLCFM3" in out
        assert "https://doi.org/10.1016/j.plaphe.2026.100200" in out
        assert "[SRC-393]" in out

    # 2) HTML 화학식·단위 첨자 확인
    html_out = normalize_scientific_typography(sample, target_format="html")
    assert "CO<sub>2</sub>" in html_out
    assert "NO<sub>3</sub><sup>−</sup>" in html_out
    assert "Ca<sup>2+</sup>" in html_out
    assert "cm<sup>2</sup>" in html_out
    assert "m<sup>2</sup>/m<sup>2</sup>" in html_out
    assert "AP<sub>50</sub>" in html_out

    # 3) Plain 텍스트에는 HTML 태그도 0개여야 하며 유니코드 첨자 변환
    plain_out = normalize_scientific_typography(sample, target_format="plain")
    assert "<sub>" not in plain_out and "<sup>" not in plain_out and "<b>" not in plain_out
    assert "CO₂" in plain_out and "cm²" in plain_out and "R²" in plain_out

    # 4) 네이티브 Word(.docx) Run 위첨자·아래첨자·볼드 검증
    doc = Document()
    p = doc.add_paragraph()
    add_rich_runs_to_docx_paragraph(p, sample.splitlines()[0])
    full_docx_txt = "".join(r.text for r in p.runs)
    assert detect_unformatted_math_leaks(full_docx_txt) == []
    assert any(r.bold and "μ" in r.text for r in p.runs)
    assert any(r.bold and "Σ" in r.text for r in p.runs)
    assert any(r.font.superscript and "2" in r.text for r in p.runs)
    assert any(r.font.subscript and "50" in r.text for r in p.runs)
    assert any(r.font.subscript and "2" in r.text for r in p.runs)
    docx_p = tmp_path / "math_check.docx"
    doc.save(str(docx_p))
    assert docx_p.is_file()
