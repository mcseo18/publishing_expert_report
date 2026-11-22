"""Phase 2 (학술 논문 수집기 + 자료 정리 대시보드 API) 단위·통합 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard.app import app  # noqa: E402
from fetch_scholar import parse_bibtex_entries  # noqa: E402


def test_bibtex_parser_google_scholar():
    sample = """
    @article{lehmann2015contentious,
      title={The contentious nature of soil organic matter},
      author={Lehmann, Johannes and Kleber, Markus},
      journal={Nature},
      volume={528},
      pages={60--68},
      year={2015},
      doi={10.1038/nature16069}
    }
    @article{kim2023som,
      title={국내 농경지 토양 유기물 분획 변동 연구},
      author={김토양 and 이비료},
      journal={한국토양비료학회지},
      year={2023}
    }
    """
    entries = parse_bibtex_entries(sample)
    assert len(entries) == 2
    assert entries[0]["year"] == 2015
    assert entries[0]["category"] == "google_scholar_bibtex"
    assert entries[1]["category"] == "korean_society_bibtex"
    assert "한국토양비료학회지" in entries[1]["journal"]


def test_dashboard_api_endpoints():
    client = TestClient(app)

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "자료 수집 · 큐레이션 · 지식그래프 대시보드" in r_home.text
    assert "projectSwitcher" in r_home.text

    r_ov = client.get("/api/overview?project=soil_organic_matter_500p")
    assert r_ov.status_code == 200
    ov = r_ov.json()
    assert ov["total_sources"] >= 10
    assert ov["catalog_summary"]["total_nodes"] > 100000

    r_src = client.get("/api/sources?project=soil_organic_matter_500p")
    assert r_src.status_code == 200
    srcs = r_src.json()["sources"]
    assert any(s["category"] == "korean_society" for s in srcs)
    assert any(s["category"] == "kg_reuse" for s in srcs)

    r_det = client.get("/api/sources/SRC-01")
    assert r_det.status_code == 200
    assert r_det.json()["source_id"] == "SRC-01"

    r_bp = client.get("/api/blueprint?project=soil_organic_matter_500p")
    assert r_bp.status_code == 200
    assert r_bp.json()["book_metadata"]["target_total_pages"] >= 500
    assert len(r_bp.json()["parts"]) == 5

    r_pg = client.get("/api/kg/platform-graph")
    assert r_pg.status_code == 200

    r_bib = client.get("/api/export/bibliography?fmt=bibtex&status=all")
    assert r_bib.status_code == 200
    assert "@article{SRC_01" in r_bib.text


def test_crop_visual_matcher_no_wheat_hijack():
    """'정밀재배'·'밀도' 등의 '밀' 부분 문자열이 옥수수·딸기 등 타 작물을 밀(wheat)로 오매칭하지 않는지 검증."""
    from visual_studio import _resolve_english_visual_scenes

    ch = {"title": "제1장. 기원과 형태생리", "summary_ko": "C4 광합성과 이삭 발달", "sections": ["1.1 기초"]}
    corn_field, corn_diag, _ = _resolve_english_visual_scenes(
        "디지털 옥수수 재배학: 데이터 기반 작물생리·정밀재배 및 스마트 농기계 공학",
        "Digital Corn Cultivation",
        ch,
    )
    assert "Zea mays" in corn_field and "wheat" not in corn_field.lower()
    assert "Zea mays" in corn_diag and "wheat" not in corn_diag.lower()

    berry_field, _, _ = _resolve_english_visual_scenes("스마트팜 딸기 정밀재배", "Smart Farm Strawberry", ch)
    assert "strawberry" in berry_field.lower() and "wheat" not in berry_field.lower()

    wheat_field, _, _ = _resolve_english_visual_scenes("디지털 밀 재배", "Digital Wheat Cultivation", ch)
    assert "wheat" in wheat_field.lower()
