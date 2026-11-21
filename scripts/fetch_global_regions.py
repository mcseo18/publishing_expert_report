"""일본·미국·유럽 공식 농업/토양 연구기관 웹사이트 크롤링 + 3개 권역 대표 학회지 논문 수집기.

대상 권역 및 출처 (robots.txt 100% 준수):
1. 일본 (japan_source):
   - 농림수산성(MAFF): 도도부현 시비·토양개량 기준, 지구온난화대책(바이오炭·농지토양탄소 링크 자동 탐색)
   - 농연기구(NARO) 농업환경연구부문(NIAES)
   - 일본토양비료학회 공식 영문학술지 Soil Science and Plant Nutrition (ISSN 0038-0768 / 1747-0765)
2. 미국 (usa_source):
   - 코넬대 토양건강연구소(Cornell Soil Health): CASH 매뉴얼 페이지 & 팩트시트 (오픈 PDF 자동 탐색)
   - 미국토양학회 공식 학술지 Soil Science Society of America Journal (ISSN 0361-5995 / 1435-0661)
3. 유럽 (europe_source):
   - 영국 로담스테드 연구소(Rothamsted Research): 공식 RothC 토양탄소 모델
   - 유럽환경청(EEA): EU 토양 및 토양유기탄소 심층 보고 페이지
   - 프랑스/국제 4 per 1000 이니셔티브(4p1000.org)
   - 유럽연합 EJP SOIL(ejpsoil.eu)
   - 유럽토양학회 공식 학술지 European Journal of Soil Science (ISSN 1351-0754 / 1365-2389)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from compliance import USER_AGENT, utc_now_iso
from config import PlatformConfig, get_config
from fetch_clean import fetch_and_clean_url
from fetch_scholar import _reconstruct_openalex_abstract, ingest_paper_record


def _set_curation(
    source_id: str,
    category: str,
    tier: str,
    chapters: list[str],
    tags: list[str],
    notes: str,
    rating: int = 5,
    cfg: PlatformConfig | None = None,
) -> None:
    cfg = cfg or get_config()
    p = cfg.index_dir / "curation_state.json"
    state: dict[str, Any] = {}
    if p.is_file():
        try:
            state = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state[source_id] = {
        "status": "approved",
        "category": category,
        "tier": tier,
        "chapters": chapters,
        "tags": tags,
        "notes": notes,
        "rating": rating,
        "updated_at": utc_now_iso(),
    }
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _discover_maff_biochar_link() -> str | None:
    """MAFF 지구온난화대책 페이지에서 바이오탄/농지토양탄소 관련 하위 HTML 링크를 자동 탐색한다."""
    try:
        base = "https://www.maff.go.jp/j/seisan/kankyo/ondanka/index.html"
        r = requests.get(base, headers={"User-Agent": USER_AGENT}, timeout=12)
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            txt = a.get_text(" ", strip=True)
            href = a["href"]
            if any(k in txt for k in ("バイオ炭", "炭素貯留", "土壌", "J-クレジット")) and href.endswith((".html", ".htm", "/")):
                return urljoin(base, href)
    except Exception:
        pass
    return None


def _search_journal_by_issn(
    query: str,
    issns: str,
    region_category: str,
    region_label: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "filter": f"primary_location.source.issn:{issns}",
        "sort": "cited_by_count:desc",
        "per-page": limit,
    }
    r = requests.get(
        "https://api.openalex.org/works",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    papers: list[dict[str, Any]] = []
    for w in r.json().get("results", []):
        primary = w.get("primary_location") or {}
        src = primary.get("source") or {}
        best_oa = w.get("best_oa_location") or {}
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:6]
        ]
        authors = [a for a in authors if a]
        doi = w.get("doi") or ""
        landing = best_oa.get("landing_page_url") or primary.get("landing_page_url") or doi or w.get("id", "")
        pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
        abstract = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
        papers.append(
            {
                "id": w.get("id", ""),
                "title": w.get("display_name") or w.get("title") or "",
                "authors": authors,
                "year": w.get("publication_year"),
                "journal": src.get("display_name") or region_label,
                "doi": doi,
                "url": landing,
                "pdf_url": pdf_url,
                "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
                "cited_by_count": int(w.get("cited_by_count") or 0),
                "language": w.get("language") or "en",
                "category": region_category,
                "abstract": abstract,
                "provider": f"OpenAlex ({region_label})",
            }
        )
    return papers


def run_global_collection(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    out: dict[str, Any] = {
        "japan_web": [],
        "japan_society_papers": [],
        "usa_web": [],
        "usa_society_papers": [],
        "europe_web": [],
        "europe_society_papers": [],
    }

    # ==================== 1. 일본 (JAPAN) ====================
    jp_pages: list[dict[str, Any]] = [
        {
            "url": "https://www.maff.go.jp/j/seisan/kankyo/hozen_type/h_sehi_kizyun/index.html",
            "packet": "ch10_evidence",
            "chapters": ["ch10", "ch11"],
            "tags": ["일본", "MAFF", "농림수산성", "시비기준", "토양개량"],
            "license": "일본 농림수산성(MAFF) 공식 공개 행정·기술 자료 - 변환적 분석 및 인용",
            "note": "일본 농림수산성(MAFF) 전국 도도부현 시비 기준 및 토양개량·지력증진 지침 (한국 흙토람 기준과 비교용).",
        },
        {
            "url": "https://www.maff.go.jp/j/seisan/kankyo/ondanka/index.html",
            "packet": "ch13_evidence",
            "chapters": ["ch12", "ch13"],
            "tags": ["일본", "MAFF", "농림수산성", "기후변화", "농지토양탄소", "J-Credit"],
            "license": "일본 농림수산성(MAFF) 공식 공개 기후변화·토양탄소 자료 - 변환적 분석 및 인용",
            "note": "일본 농림수산성 지구온난화 대책·녹색식량시스템전략·농지토양탄소저장(J-Credit) 정책 자료.",
        },
        {
            "url": "https://www.naro.go.jp/laboratory/niaes/index.html",
            "packet": "ch09_evidence",
            "chapters": ["ch09", "ch10", "ch13"],
            "tags": ["일본", "NARO", "농연기구", "NIAES", "농업환경연구"],
            "license": "일본 농연기구(NARO) 농업환경연구부문 공식 공개 자료 - 변환적 분석 및 인용",
            "note": "일본 국립농연기구(NARO) 농업환경연구부문(NIAES) 토양유기탄소·온실가스·토양정보시스템 연구 개요.",
        },
    ]
    biochar_url = _discover_maff_biochar_link()
    if biochar_url and biochar_url not in [p["url"] for p in jp_pages]:
        jp_pages.append(
            {
                "url": biochar_url,
                "packet": "ch12_evidence",
                "chapters": ["ch12", "ch13"],
                "tags": ["일본", "MAFF", "바이오차", "J-Credit", "토양탄소격리"],
                "license": "일본 농림수산성(MAFF) 바이오탄·농지토양탄소 공식 공개 자료",
                "note": "일본 농림수산성 공식 바이오탄(Biochar) 농지시용 및 토양탄소저장 J-Credit 연계 페이지.",
            }
        )

    for item in jp_pages:
        try:
            res = fetch_and_clean_url(
                url=item["url"],
                packet_id=item["packet"],
                topic="일본 농림수산성·농연기구 토양유기물·탄소 자료",
                license_note=item["license"],
                use_crawl4ai=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                _set_curation(res["source_id"], "japan_source", "일본 공식기관", item["chapters"], item["tags"], item["note"], 5, cfg)
            out["japan_web"].append(res)
        except Exception as exc:
            out["japan_web"].append({"status": "ERROR", "url": item["url"], "error": str(exc)})

    # 일본토양비료학회 공식 학술지 (Soil Science and Plant Nutrition) 논문 3편
    try:
        jp_papers = _search_journal_by_issn(
            query="soil organic carbon paddy humic biochar",
            issns="0038-0768|1747-0765",
            region_category="japan_source",
            region_label="일본토양비료학회(SSPN)",
            limit=3,
        )
        for p in jp_papers:
            r = ingest_paper_record(p, packet_id="ch10_evidence", topic="일본토양비료학회지 토양유기물·논토양 탄소 논문", cfg=cfg)
            if r.get("status") == "OK":
                _set_curation(
                    r["source_id"],
                    "japan_source",
                    "일본 학회지(SSPN)",
                    ["ch03", "ch09", "ch10"],
                    ["일본", "일본토양비료학회", "SSPN", "논토양", "토양유기탄소"],
                    f"일본토양비료학회 공식 학술지(Soil Science and Plant Nutrition) 피인용 {p.get('cited_by_count',0)}회 논문.",
                    5,
                    cfg,
                )
            out["japan_society_papers"].append(r)
    except Exception as exc:
        out["japan_society_papers"].append({"status": "ERROR", "error": str(exc)})

    # ==================== 2. 미국 (USA) ====================
    us_pages = [
        {
            "url": "https://soilhealth.cals.cornell.edu/manual/",
            "packet": "ch08_evidence",
            "chapters": ["ch01", "ch08"],
            "tags": ["미국", "Cornell", "CASH매뉴얼", "토양건강평가", "활성탄소POXC"],
            "license": "Cornell University Soil Health 공식 공개 매뉴얼 안내 - 변환적 분석 및 인용",
            "note": "미국 코넬대 종합토양건강평가(CASH) 공식 프레임워크 매뉴얼(유기물·활성탄소 POXC·토양단립 평가 기준).",
        },
        {
            "url": "https://blogs.cornell.edu/soilhealthllab/resources/soil-health-manual-series-fact-sheets-2/",
            "packet": "ch08_evidence",
            "chapters": ["ch01", "ch04", "ch08"],
            "tags": ["미국", "Cornell", "SoilHealth", "팩트시트", "지표해설"],
            "license": "Cornell Soil Health Lab 공식 공개 팩트시트 시리즈 - 변환적 분석 및 인용",
            "note": "미국 코넬대 토양건강연구소 토양유기물·단립안정성·활성탄소(POXC) 2페이지 핵심 팩트시트 모음.",
        },
    ]
    for item in us_pages:
        try:
            res = fetch_and_clean_url(
                url=item["url"],
                packet_id=item["packet"],
                topic="미국 코넬대 토양건강·유기물 평가 매뉴얼",
                license_note=item["license"],
                use_crawl4ai=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                _set_curation(res["source_id"], "usa_source", "미국 대학·기관", item["chapters"], item["tags"], item["note"], 5, cfg)
            out["usa_web"].append(res)
        except Exception as exc:
            out["usa_web"].append({"status": "ERROR", "url": item["url"], "error": str(exc)})

    # 미국토양학회 공식 학술지 (Soil Science Society of America Journal, SSSAJ) 핵심 논문 3편
    try:
        us_papers = _search_journal_by_issn(
            query="particulate organic matter aggregate soil organic carbon",
            issns="0361-5995|1435-0661",
            region_category="usa_source",
            region_label="미국토양학회(SSSAJ)",
            limit=3,
        )
        for p in us_papers:
            r = ingest_paper_record(p, packet_id="ch04_evidence", topic="미국토양학회지(SSSAJ) POM·단립·유기물 핵심 논문", cfg=cfg)
            if r.get("status") == "OK":
                _set_curation(
                    r["source_id"],
                    "usa_source",
                    "미국 학회지(SSSAJ)",
                    ["ch01", "ch04", "ch08"],
                    ["미국", "미국토양학회", "SSSAJ", "POM", "단립안정성"],
                    f"미국토양학회 공식 학술지(SSSAJ) 고인용 핵심 논문 (피인용 {p.get('cited_by_count',0)}회).",
                    5,
                    cfg,
                )
            out["usa_society_papers"].append(r)
    except Exception as exc:
        out["usa_society_papers"].append({"status": "ERROR", "error": str(exc)})

    # ==================== 3. 유럽 (EUROPE) ====================
    eu_pages = [
        {
            "url": "https://www.rothamsted.ac.uk/rothamsted-carbon-model-rothc",
            "packet": "ch09_evidence",
            "chapters": ["ch09", "ch13"],
            "tags": ["유럽", "영국", "Rothamsted", "RothC", "토양탄소모델"],
            "license": "영국 Rothamsted Research 공식 공개 RothC 모델 문서 - 변환적 분석 및 인용",
            "note": "영국 로담스테드 연구소(Rothamsted Research) 공식 RothC 토양유기탄소 동역학 모델(5-풀 구조·정/역방향 시뮬레이션) 설명.",
        },
        {
            "url": "https://www.eea.europa.eu/en/topics/in-depth/soil",
            "packet": "ch13_evidence",
            "chapters": ["ch01", "ch13"],
            "tags": ["유럽", "EU", "EEA", "유럽환경청", "EU토양전략"],
            "license": "유럽환경청(EEA) 공공 오픈 콘텐츠(CC-BY 4.0) - 변환적 분석 및 인용",
            "note": "유럽환경청(EEA) EU 토양 건강·토양유기탄소 감소 위협·EU Soil Strategy 2030 심층 평가 페이지.",
        },
        {
            "url": "https://4p1000.org/?lang=en",
            "packet": "ch13_evidence",
            "chapters": ["ch13"],
            "tags": ["유럽", "프랑스", "4per1000", "탄소격리", "기후정책"],
            "license": "4 per 1000 Initiative 공식 공개 자료 - 변환적 분석 및 인용",
            "note": "프랑스 주도 국제 '4 per 1000' 이니셔티브(연간 표토 유기탄소 0.4% 증진) 공식 목적 및 정책 개요.",
        },
        {
            "url": "https://ejpsoil.eu/",
            "packet": "ch09_evidence",
            "chapters": ["ch09", "ch13"],
            "tags": ["유럽", "EU", "EJPSOIL", "Horizon2020", "농경지토양탄소"],
            "license": "EU EJP SOIL 컨소시엄 공식 공개 자료 - 변환적 분석 및 인용",
            "note": "유럽 24개국 공동 농경지 토양관리 연구 프로그램(EJP SOIL) — 유럽 토양유기탄소 매핑·MRV·기후적응 연구.",
        },
    ]
    for item in eu_pages:
        try:
            res = fetch_and_clean_url(
                url=item["url"],
                packet_id=item["packet"],
                topic="유럽 공식 토양연구기관·EU 토양유기탄소 정책 및 RothC 모델",
                license_note=item["license"],
                use_crawl4ai=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                _set_curation(res["source_id"], "europe_source", "유럽 공식기관", item["chapters"], item["tags"], item["note"], 5, cfg)
            out["europe_web"].append(res)
        except Exception as exc:
            out["europe_web"].append({"status": "ERROR", "url": item["url"], "error": str(exc)})

    # 유럽토양학회 공식 학술지 (European Journal of Soil Science, EJSS) 핵심 논문 3편
    try:
        eu_papers = _search_journal_by_issn(
            query="soil organic matter stabilization mineral carbon",
            issns="1351-0754|1365-2389",
            region_category="europe_source",
            region_label="유럽토양학회(EJSS)",
            limit=3,
        )
        for p in eu_papers:
            r = ingest_paper_record(p, packet_id="ch03_evidence", topic="유럽토양학회지(EJSS) 유기물 안정화·광물결합 핵심 논문", cfg=cfg)
            if r.get("status") == "OK":
                _set_curation(
                    r["source_id"],
                    "europe_source",
                    "유럽 학회지(EJSS)",
                    ["ch03", "ch07", "ch13"],
                    ["유럽", "유럽토양학회", "EJSS", "유기물안정화", "광물결합"],
                    f"유럽토양학회 공식 학술지(European Journal of Soil Science) 고인용 핵심 논문 (피인용 {p.get('cited_by_count',0)}회).",
                    5,
                    cfg,
                )
            out["europe_society_papers"].append(r)
    except Exception as exc:
        out["europe_society_papers"].append({"status": "ERROR", "error": str(exc)})

    return out


if __name__ == "__main__":
    print(json.dumps(run_global_collection(), ensure_ascii=False, indent=2))
