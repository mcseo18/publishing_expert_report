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
