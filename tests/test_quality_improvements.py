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
