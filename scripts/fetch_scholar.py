"""국내외 학술 논문·학회지·구글 스칼라(BibTeX) 수집 및 근거 패킷 통합 모듈.

지원 수집 경로 (법적 컴플라이언스 준수 — CAPTCHA/페이월 우회 금지):
1. 국제 학술 DB (OpenAlex + Crossref REST API):
   - Nature, Global Change Biology, Geoderma, Soil Biology & Biochemistry, SSSAJ 등
   - 피인용수(cited_by_count), DOI, 저자, 발행연도, 초록(Abstract), 오픈액세스 PDF 자동 확보
2. 국내 학회지·학술 논문 (한국토양비료학회지 Korean Journal of Soil Science and Fertilizer 등):
   - OpenAlex(ISSN/기관/한국어 필터) + Crossref(국내 학회 접두사/저널명) 교차 검색
   - 대표 국내 학회지: 한국토양비료학회지(ISSN 0367-6315 / 2288-2162), 한국환경농학회지, 한국작물학회지, 한국농림기상학회지
3. Google Scholar / RISS / KCI / DBpia BibTeX 일괄 가져오기:
   - 사용자가 Google Scholar 또는 ego-browser 세션에서 내보낸 BibTeX 텍스트를 파싱해
     E:\\SMC_Report_Platform_Data\\evidence\\ 및 sources.jsonl 에 정식 [SRC-NN]으로 등록
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

from compliance import (
    USER_AGENT,
    SourcesRegistry,
    chunk_korean_text,
    mask_pii,
    normalize_url,
    sha256_text,
    slugify,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config

# 농학·작물·원예·토양·식품·잡초·농공학·기상 주요 국내 18대 학회지 ISSN 및 학회명 매핑
KOREAN_SOCIETY_JOURNALS: list[dict[str, str]] = [
    {"society": "한국토양비료학회", "journal_ko": "한국토양비료학회지", "journal_en": "Korean Journal of Soil Science and Fertilizer", "issn": "0367-6315", "eissn": "2288-2162"},
    {"society": "한국작물학회", "journal_ko": "한국작물학회지", "journal_en": "Korean Journal of Crop Science", "issn": "0252-9777", "eissn": "2287-8432"},
    {"society": "한국원예학회", "journal_ko": "원예과학기술지", "journal_en": "Horticultural Science and Technology", "issn": "1226-8763", "eissn": "2465-8588"},
    {"society": "한국환경농학회", "journal_ko": "한국환경농학회지", "journal_en": "Korean Journal of Environmental Agriculture", "issn": "1225-3537", "eissn": "2233-4173"},
    {"society": "한국농림기상학회", "journal_ko": "한국농림기상학회지", "journal_en": "Korean Journal of Agricultural and Forest Meteorology", "issn": "1229-5671", "eissn": "2288-1859"},
    {"society": "한국잡초학회", "journal_ko": "잡초·잔디학회지", "journal_en": "Weed & Turfgrass Science", "issn": "2287-7924", "eissn": "2288-7997"},
    {"society": "한국식물병리학회", "journal_ko": "식물병연구", "journal_en": "Research in Plant Disease", "issn": "1598-2262", "eissn": "2233-9191"},
    {"society": "한국응용곤충학회", "journal_ko": "한국응용곤충학회지", "journal_en": "Korean Journal of Applied Entomology", "issn": "1225-0171", "eissn": "2287-545X"},
    {"society": "한국생물환경조절학회", "journal_ko": "생물환경조절학회지", "journal_en": "Journal of Bio-Environment Control", "issn": "1229-4675", "eissn": "2765-3641"},
    {"society": "한국농업기계학회", "journal_ko": "바이오시스템공학", "journal_en": "Journal of Biosystems Engineering", "issn": "1738-1266", "eissn": "2234-1862"},
    {"society": "한국식품저장유통학회", "journal_ko": "한국식품저장유통학회지", "journal_en": "Korean Journal of Food Preservation", "issn": "1738-7248", "eissn": "2287-7428"},
    {"society": "한국식품과학회", "journal_ko": "한국식품과학회지", "journal_en": "Korean Journal of Food Science and Technology", "issn": "0367-6293", "eissn": "2383-9635"},
    {"society": "한국유기농업학회", "journal_ko": "한국유기농업학회지", "journal_en": "Korean Journal of Organic Agriculture", "issn": "1229-3571", "eissn": "2287-819X"},
    {"society": "한국육종학회", "journal_ko": "한국육종학회지", "journal_en": "Korean Journal of Breeding Science", "issn": "0250-3360", "eissn": "2287-5174"},
    {"society": "한국농공학회", "journal_ko": "한국농공학회논문집", "journal_en": "Journal of the Korean Society of Agricultural Engineers", "issn": "1738-3692", "eissn": "2093-7709"},
    {"society": "한국농약과학회", "journal_ko": "농약과학회지", "journal_en": "The Korean Journal of Pesticide Science", "issn": "1226-6183", "eissn": "2287-2051"},
]


def _reconstruct_openalex_abstract(inv_idx: dict[str, list[int]] | None) -> str:
    if not inv_idx or not isinstance(inv_idx, dict):
        return ""
    pos_map: dict[int, str] = {}
    for word, positions in inv_idx.items():
        for p in positions:
            pos_map[p] = word
    if not pos_map:
        return ""
    return " ".join(pos_map[i] for i in sorted(pos_map.keys()))


def _clean_crossref_abstract(raw: str) -> str:
    if not raw:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", cleaned).strip()


def _polite_mailto() -> str:
    return os.environ.get("OPENALEX_MAILTO", "research@smc-report-platform.local").strip()


def _request_with_retry(
    url: str,
    params: dict[str, Any],
    *,
    retries: int = 2,
    timeout: int = 16,
) -> requests.Response:
    last_exc: Exception | None = None
    headers = {"User-Agent": f"{USER_AGENT} (mailto:{_polite_mailto()})"}
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = requests.HTTPError(f"{resp.status_code} Server Error for {url}", response=resp)
                if attempt < retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


def search_europepmc_papers(
    query: str,
    limit: int = 10,
    open_access_only: bool = False,
    year_from: int | None = None,
    affiliation_hint: str = "",
) -> list[dict[str, Any]]:
    """Europe PMC 공식 REST API로 생명과학·농학·식품 논문(초록 + OA PDF)을 정밀 검색한다."""
    stop_words = {"and", "or", "of", "the", "in", "on", "for", "to", "with", "based", "its", "by", "from", "as", "a", "an", "fundamentals", "introduction", "overview", "management"}
    tokens = [w for w in re.findall(r"[A-Za-z0-9\-가-힣]+", query) if w.lower() not in stop_words and len(w) >= 2]
    if len(tokens) >= 2:
        core_q = " AND ".join(f'TITLE_ABS:"{t}"' for t in tokens[:4])
    elif tokens:
        core_q = f'TITLE_ABS:"{tokens[0]}"'
    else:
        core_q = query.strip()
    q_parts = [f"({core_q})"]
    if open_access_only:
        q_parts.append("OPEN_ACCESS:Y")
    if year_from:
        q_parts.append(f"PUB_YEAR:[{year_from} TO 2030]")
    if affiliation_hint:
        q_parts.append(f"AFF:({affiliation_hint})")
    full_q = " AND ".join(q_parts)

    resp = _request_with_retry(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": full_q,
            "format": "json",
            "resultType": "core",
            "pageSize": min(max(limit * 2, 10), 25),
        },
        retries=1,
        timeout=16,
    )
    items = (resp.json().get("resultList") or {}).get("result") or []
    results: list[dict[str, Any]] = []
    for it in items:
        title = (it.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        author_list = (it.get("authorList") or {}).get("author") or []
        authors = [a.get("fullName") or a.get("lastName") or "" for a in author_list[:6]]
        authors = [a for a in authors if a]
        pub_yr = it.get("pubYear")
        year = int(pub_yr) if str(pub_yr or "").isdigit() else None
        jinfo = (it.get("journalInfo") or {}).get("journal") or {}
        journal = jinfo.get("title") or it.get("bookOrReportDetails", {}).get("publisher") or "Europe PMC"
        doi_raw = (it.get("doi") or "").strip()
        doi = f"https://doi.org/{doi_raw}" if doi_raw and not doi_raw.startswith("http") else doi_raw
        pmcid = (it.get("pmcid") or "").strip()
        is_oa = str(it.get("isOpenAccess", "")).upper() == "Y" or bool(pmcid)
        pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render" if pmcid else ""
        url = doi or (f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else f"https://europepmc.org/article/MED/{it.get('pmid','')}")
        abstract = _clean_crossref_abstract(it.get("abstractText") or "")
        is_kr = (affiliation_hint.lower() == "korea") or any("\uac00" <= ch <= "\ud7a3" for ch in title)
        results.append(
            {
                "id": f"epmc:{pmcid or it.get('pmid') or doi_raw}",
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": doi,
                "url": url,
                "pdf_url": pdf_url,
                "is_oa": is_oa,
                "cited_by_count": int(it.get("citedByCount") or 0),
                "language": "ko" if is_kr else "en",
                "category": "korean_society" if is_kr else "international_journal",
                "abstract": abstract,
                "provider": "Europe PMC",
            }
        )
    return results


def search_crossref_general(
    query: str,
    limit: int = 10,
    scope: str = "all",
    year_from: int | None = None,
    sort: str = "relevance",
) -> list[dict[str, Any]]:
    """Crossref 공식 REST API 범용 검색 (OpenAlex 503 장애 시 자동 폴백 포함)."""
    params: dict[str, Any] = {
        "query.bibliographic": query,
        "rows": min(max(limit * 2, 10), 25),
        "sort": "relevance",
        "mailto": _polite_mailto(),
    }
    filters: list[str] = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if scope == "korean_societies":
        for j in KOREAN_SOCIETY_JOURNALS:
            filters.append(f"issn:{j['issn']}")
    if filters:
        params["filter"] = ",".join(filters)

    resp = _request_with_retry("https://api.crossref.org/works", params=params, retries=1, timeout=16)
    items = resp.json().get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []
    for it in items:
        titles = it.get("title") or [""]
        title = re.sub(r"\s+", " ", titles[0]).strip() if titles else ""
        if not title:
            continue
        authors = []
        for a in (it.get("author") or [])[:6]:
            nm = " ".join(p for p in [a.get("family", ""), a.get("given", "")] if p).strip()
            if nm:
                authors.append(nm)
        issued = (it.get("issued") or {}).get("date-parts") or [[None]]
        year = issued[0][0] if issued and issued[0] else None
        containers = it.get("container-title") or ["Crossref 학술 문헌"]
        journal = containers[0] if containers else "Crossref 학술 문헌"
        doi_raw = it.get("DOI") or ""
        doi = f"https://doi.org/{doi_raw}" if doi_raw and not doi_raw.startswith("http") else doi_raw
        url = it.get("URL") or doi
        pdf_url = ""
        for lk in it.get("link") or []:
            if "pdf" in str(lk.get("content-type", "")).lower() and lk.get("URL"):
                pdf_url = lk["URL"]
                break
        abstract = _clean_crossref_abstract(it.get("abstract") or "")
        is_kr = (scope in ("korean_societies", "korea_all")) or any(
            j["journal_en"].lower() in journal.lower() or j["journal_ko"] in journal for j in KOREAN_SOCIETY_JOURNALS
        )
        results.append(
            {
                "id": f"crossref:{doi_raw}",
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": doi,
                "url": url,
                "pdf_url": pdf_url,
                "is_oa": bool(pdf_url),
                "cited_by_count": int(it.get("is-referenced-by-count") or 0),
                "language": "ko" if is_kr else "en",
                "category": "korean_society" if is_kr else "international_journal",
                "abstract": abstract,
                "provider": "Crossref",
            }
        )
    return results


def _fallback_academic_search(
    query: str,
    limit: int = 10,
    scope: str = "all",
    year_from: int | None = None,
    sort: str = "cited_by_count:desc",
) -> list[dict[str, Any]]:
    """OpenAlex 일시 장애(503/429 등) 시 Europe PMC + Crossref로 자동 무중단 대체 검색한다."""
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _add_list(items: list[dict[str, Any]], tag: str) -> None:
        for p in items:
            key = (p.get("doi") or p.get("title") or "").strip().lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            p_copy = dict(p)
            p_copy["provider"] = f"{p.get('provider', tag)} (OpenAlex 자동대체)"
            merged.append(p_copy)

    if scope == "korean_societies":
        try:
            _add_list(search_crossref_general(query, limit=limit, scope="korean_societies", year_from=year_from, sort=sort), "Crossref")
        except Exception:
            pass
    else:
        aff = "Korea" if scope == "korea_all" else ""
        # 1) 제목/서지 정밀도가 높은 Crossref 우선 (open_access 전용일 때는 Europe PMC 우선)
        if scope != "open_access":
            try:
                q_cr = f"{query} Korea" if scope == "korea_all" else query
                _add_list(search_crossref_general(q_cr, limit=limit, scope=scope, year_from=year_from, sort=sort), "Crossref")
            except Exception:
                pass
        # 2) Europe PMC TITLE_ABS 정밀 검색으로 초록·OA PDF 보강
        try:
            _add_list(
                search_europepmc_papers(
                    query=query,
                    limit=limit,
                    open_access_only=(scope == "open_access"),
                    year_from=year_from,
                    affiliation_hint=aff,
                ),
                "Europe PMC",
            )
        except Exception:
            pass

    if "cited" in sort:
        merged.sort(key=lambda x: int(x.get("cited_by_count") or 0), reverse=True)
    return merged[:limit]


def search_openalex_papers(
    query: str,
    limit: int = 10,
    scope: str = "all",
    year_from: int | None = None,
    sort: str = "cited_by_count:desc",
) -> list[dict[str, Any]]:
    """OpenAlex API로 국제·국내 학술 논문을 검색하며, 503/429 장애 시 Europe PMC·Crossref로 자동 폴백한다."""
    filters: list[str] = []
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if scope == "korean_societies":
        issns = "|".join(
            [j["issn"] for j in KOREAN_SOCIETY_JOURNALS]
            + [j["eissn"] for j in KOREAN_SOCIETY_JOURNALS]
        )
        filters.append(f"primary_location.source.issn:{issns}")
    elif scope == "korea_all":
        filters.append("authorships.institutions.country_code:KR")
    elif scope == "open_access":
        filters.append("is_oa:true")

    params: dict[str, Any] = {
        "search": query,
        "per-page": min(max(limit, 1), 25),
        "sort": sort,
        "mailto": _polite_mailto(),
    }
    if filters:
        params["filter"] = ",".join(filters)

    try:
        resp = _request_with_retry("https://api.openalex.org/works", params=params, retries=1, timeout=14)
    except Exception:
        # OpenAlex 503/429/네트워크 장애 시 Europe PMC + Crossref 자동 무중단 폴백
        return _fallback_academic_search(query=query, limit=limit, scope=scope, year_from=year_from, sort=sort)

    results = []
    for w in resp.json().get("results", []):
        primary = (w.get("primary_location") or {})
        src = (primary.get("source") or {})
        best_oa = (w.get("best_oa_location") or {})
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:6]
        ]
        authors = [a for a in authors if a]
        doi = w.get("doi") or ""
        landing = best_oa.get("landing_page_url") or primary.get("landing_page_url") or doi or w.get("id", "")
        pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
        abstract = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
        journal_name = src.get("display_name") or "학술 논문"
        is_kr = (
            scope in ("korean_societies", "korea_all")
            or any(j["journal_en"].lower() in journal_name.lower() or j["journal_ko"] in journal_name for j in KOREAN_SOCIETY_JOURNALS)
            or (w.get("language") == "ko")
        )
        results.append(
            {
                "id": w.get("id", ""),
                "title": w.get("display_name") or w.get("title") or "",
                "authors": authors,
                "year": w.get("publication_year"),
                "journal": journal_name,
                "doi": doi,
                "url": landing,
                "pdf_url": pdf_url,
                "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
                "cited_by_count": int(w.get("cited_by_count") or 0),
                "language": w.get("language") or ("ko" if is_kr else "en"),
                "category": "korean_society" if is_kr else "international_journal",
                "abstract": abstract,
                "provider": "OpenAlex",
            }
        )
    return results


def search_crossref_korean_society(
    query: str,
    limit: int = 8,
    journal_name: str = "Korean Journal of Soil Science and Fertilizer",
) -> list[dict[str, Any]]:
    """Crossref API로 한국토양비료학회지 등 국내 학회지 논문을 정밀 검색한다."""
    params = {
        "query.bibliographic": query,
        "query.container-title": journal_name,
        "rows": min(max(limit, 1), 20),
        "sort": "relevance",
    }
    resp = requests.get(
        "https://api.crossref.org/works",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []
    for it in items:
        titles = it.get("title") or [""]
        title = titles[0] if titles else ""
        if not title:
            continue
        authors = []
        for a in (it.get("author") or [])[:6]:
            name = " ".join(p for p in [a.get("family", ""), a.get("given", "")] if p).strip()
            if name:
                authors.append(name)
        issued = (it.get("issued") or {}).get("date-parts") or [[None]]
        year = issued[0][0] if issued and issued[0] else None
        containers = it.get("container-title") or [journal_name]
        journal = containers[0] if containers else journal_name
        doi = it.get("DOI") or ""
        url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        abstract = _clean_crossref_abstract(it.get("abstract") or "")
        results.append(
            {
                "id": f"crossref:{doi}",
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": f"https://doi.org/{doi}" if doi and not doi.startswith("http") else doi,
                "url": url,
                "pdf_url": "",
                "is_oa": False,
                "cited_by_count": int(it.get("is-referenced-by-count") or 0),
                "language": "ko",
                "category": "korean_society",
                "abstract": abstract,
                "provider": "Crossref",
            }
        )
    return results


def parse_bibtex_entries(bibtex_text: str) -> list[dict[str, Any]]:
    """Google Scholar / RISS / KCI / DBpia 에서 내보낸 BibTeX 문자열을 논문 목록으로 파싱한다."""
    entries: list[dict[str, Any]] = []
    raw_blocks = re.split(r"(?=@[A-Za-z]+\s*\{)", bibtex_text.strip())
    for block in raw_blocks:
        block = block.strip()
        if not block.startswith("@"):
            continue
        header_m = re.match(r"@([A-Za-z]+)\s*\{\s*([^,]+),([\s\S]*)\}\s*$", block)
        if not header_m:
            continue
        entry_type, cite_key, body = header_m.group(1).lower(), header_m.group(2).strip(), header_m.group(3)
        fields: dict[str, str] = {}
        for fm in re.finditer(r"([A-Za-z0-9_\-]+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|\"([^\"]*)\"|(\d+))", body):
            k = fm.group(1).lower()
            v = fm.group(2) if fm.group(2) is not None else (fm.group(3) if fm.group(3) is not None else (fm.group(4) or ""))
            fields[k] = re.sub(r"\s+", " ", v).strip()
        title = fields.get("title", "").strip("{}")
        if not title:
            continue
        authors = [a.strip() for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
        year_str = fields.get("year", "")
        year = int(year_str) if year_str.isdigit() else None
        doi = fields.get("doi", "")
        url = fields.get("url") or (f"https://doi.org/{doi}" if doi else f"bibtex://{cite_key}")
        journal = fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or entry_type
        is_kr = any("\uac00" <= ch <= "\ud7a3" for ch in (title + journal))
        entries.append(
            {
                "id": f"bibtex:{cite_key}",
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": f"https://doi.org/{doi}" if doi and not doi.startswith("http") else doi,
                "url": url,
                "pdf_url": "",
                "is_oa": False,
                "cited_by_count": 0,
                "language": "ko" if is_kr else "en",
                "category": "google_scholar_bibtex" if not is_kr else "korean_society_bibtex",
                "abstract": fields.get("abstract", ""),
                "provider": "Google Scholar / BibTeX",
            }
        )
    return entries


def ingest_paper_record(
    paper: dict[str, Any],
    packet_id: str = "ch01_evidence",
    topic: str = "",
    download_oa_pdf: bool = True,
    capture_webpage: bool = True,
    auto_unify_rag: bool = True,
    force: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """검색 또는 BibTeX로 확보한 논문 1편을 최대한 다운로드(OA PDF) 또는 웹 캡쳐해 E:\\ 및 C:\\SMC_GRAPHRAG 통합 RAG에 결합한다."""
    from rag_capture_unifier import download_or_capture_resource, unify_source_to_smc_graphrag

    cfg = cfg or get_config()
    registry = SourcesRegistry(cfg.sources_registry_path)

    title = (paper.get("title") or "Untitled Paper").strip()
    url = (paper.get("url") or paper.get("doi") or f"paper://{slugify(title)}").strip()
    norm_url = normalize_url(url) if url.startswith(("http://", "https://")) else url

    if not force:
        dup = registry.find_duplicate(url=norm_url)
        if dup:
            return {"status": "SKIPPED_DUPLICATE", "existing": dup}

    authors_str = ", ".join(paper.get("authors") or []) or "저자 미상"
    year = paper.get("year") or "연도 미상"
    journal = paper.get("journal") or "학술지 미상"
    doi = paper.get("doi") or ""
    cited = paper.get("cited_by_count", 0)
    category = paper.get("category") or "international_journal"
    provider = paper.get("provider") or "Scholar"
    abstract = (paper.get("abstract") or "").strip()

    md_lines = [
        f"# {title}",
        "",
        f"- **저자**: {authors_str}",
        f"- **발행연도**: {year}",
        f"- **학술지 / 학회**: {journal}",
        f"- **DOI / URL**: {doi or url}",
        f"- **피인용수**: {cited}회 ({provider})",
        f"- **분류**: {category} | **오픈액세스**: {'예' if paper.get('is_oa') else '메타데이터/초록'}",
        "",
        "## 초록 (Abstract)",
        abstract if abstract else "(오픈 초록 미제공 — 학술지 원문 또는 캡쳐/기관 세션으로 보강)",
    ]

    source_id = registry.next_source_id()
    slug = slugify(f"{year}_{title}", 46)

    # 최대한 공개 PDF 다운로드 또는 논문 랜딩페이지 스크린샷(PNG) 캡쳐
    cap_res = download_or_capture_resource(
        url=url if url.startswith(("http://", "https://")) else "",
        pdf_url=str(paper.get("pdf_url") or ""),
        doi=doi,
        source_id=source_id,
        slug=slug,
        download_pdf=download_oa_pdf,
        capture_screenshot=capture_webpage,
        cfg=cfg,
    )
    pdf_saved_path = cap_res.get("pdf_path") or ""
    cap_png_path = cap_res.get("capture_png_path") or ""
    cap_mode = cap_res.get("capture_mode") or "metadata_only"
    if cap_res.get("pdf_text"):
        md_lines.append("")
        md_lines.append("## 오픈액세스 본문 발췌 (PDF 다운로드)")
        md_lines.append(cap_res["pdf_text"])

    raw_md = "\n".join(md_lines)
    cleaned_md, pii_count = mask_pii(raw_md)
    content_hash = sha256_text(cleaned_md)

    if not force:
        dup_h = registry.find_duplicate(content_sha256=content_hash)
        if dup_h:
            return {"status": "SKIPPED_DUPLICATE", "existing": dup_h}

    raw_json_path = cfg.raw_web_dir / f"{source_id}_{slug}_meta.json"
    parsed_md_path = cfg.parsed_dir / f"{source_id}_{slug}.md"

    raw_json_path.write_text(json.dumps(paper, ensure_ascii=False, indent=2), encoding="utf-8")
    parsed_md_path.write_text(cleaned_md, encoding="utf-8")

    chunks = chunk_korean_text(cleaned_md, default_section=f"{journal} ({year})")
    extracted_facts = [
        {
            "claim": f"{authors_str} ({year}), '{title}' — {journal} (피인용 {cited}회)",
            "page_or_section": f"{journal} ({year})",
            "evidence_quote_short": (abstract[:220] if abstract else title[:220]),
        }
    ]

    now = utc_now_iso()
    license_note = (
        f"학술 논문 오픈액세스({provider}) - 변환적 분석 및 정식 학술 인용"
        if paper.get("is_oa") or pdf_saved_path
        else f"학술 서지 메타데이터·초록({provider}) - 정식 인용 목적(원문 무단 복제 금지)"
    )
    source_item = {
        "source_id": source_id,
        "source_type": "pdf" if pdf_saved_path else "web",
        "url": url,
        "title": f"[{year}] {title} ({journal})",
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": f"api_or_bibtex ({provider})",
        "license_note": license_note,
        "page_or_section": f"{journal}, {year}",
        "raw_path": pdf_saved_path or str(raw_json_path),
        "parsed_path": str(parsed_md_path),
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": [],
        "sha256": content_hash,
        "extracted_facts": extracted_facts,
        "tables": [],
        "chunks": chunks,
    }

    packet_path = cfg.evidence_dir / f"{packet_id}.json"
    upsert_evidence_packet(
        packet_path=packet_path,
        source_item=source_item,
        packet_id=packet_id,
        topic=topic,
        storage_root=str(cfg.collected_data_root),
        kg_store_root=str(cfg.smc_graphrag_root),
        schema_path=cfg.evidence_schema_path,
    )

    registry.append(
        {
            "source_id": source_id,
            "source_type": "pdf" if pdf_saved_path else "web",
            "scholar_category": category,
            "provider": provider,
            "authors": authors_str,
            "year": year,
            "journal": journal,
            "doi": doi,
            "cited_by_count": cited,
            "is_oa": bool(paper.get("is_oa") or pdf_saved_path),
            "url": url,
            "normalized_url": norm_url,
            "title": source_item["title"],
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": source_item["robots_status"],
            "sha256": content_hash,
            "raw_path": source_item["raw_path"],
            "pdf_path": pdf_saved_path,
            "capture_png_path": cap_png_path,
            "capture_mode": cap_mode,
            "parsed_path": str(parsed_md_path),
            "packet_path": str(packet_path),
            "parser_engine": f"scholar_{provider.lower()}",
            "chunk_count": len(chunks),
            "table_count": 0,
        }
    )

    rag_unified = None
    if auto_unify_rag:
        try:
            rag_unified = unify_source_to_smc_graphrag(
                source_id=source_id,
                title=source_item["title"],
                markdown_text=cleaned_md,
                parsed_path=parsed_md_path,
                url=url,
                source_type=source_item["source_type"],
                provider=provider,
                capture_mode=cap_mode,
                raw_path=source_item["raw_path"],
                pdf_path=pdf_saved_path,
                capture_png_path=cap_png_path,
                cfg=cfg,
            )
        except Exception:
            rag_unified = None

    return {
        "status": "OK",
        "source_id": source_id,
        "title": source_item["title"],
        "journal": journal,
        "year": year,
        "cited_by_count": cited,
        "category": category,
        "pdf_downloaded": bool(pdf_saved_path),
        "pdf_path": pdf_saved_path,
        "capture_png_path": cap_png_path,
        "capture_mode": cap_mode,
        "parsed_path": str(parsed_md_path),
        "packet_path": str(packet_path),
        "rag_unified": bool(rag_unified),
        "rag_summary": rag_unified.get("unified_totals") if isinstance(rag_unified, dict) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="국내외 학회지·학술 논문·Google Scholar BibTeX 수집기")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="국제 저널 / 국내 학회지 검색 및 선택적 수집")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--scope", choices=["all", "korean_societies", "korea_all", "open_access", "crossref_ksssf"], default="all")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--year-from", type=int, default=None)
    p_search.add_argument("--ingest", action="store_true", help="검색 결과를 즉시 근거 패킷에 수집·등록")
    p_search.add_argument("--download-pdf", action="store_true", help="오픈액세스 PDF 자동 다운로드")
    p_search.add_argument("--packet", default="ch01_evidence")
    p_search.add_argument("--topic", default="")

    p_bib = sub.add_parser("import-bibtex", help="Google Scholar / RISS / KCI BibTeX 파일 일괄 등록")
    p_bib.add_argument("--file", type=Path, required=True)
    p_bib.add_argument("--packet", default="ch01_evidence")
    p_bib.add_argument("--topic", default="")

    args = parser.parse_args()
    if args.cmd == "search":
        if args.scope == "crossref_ksssf":
            papers = search_crossref_korean_society(args.query, limit=args.limit)
        else:
            papers = search_openalex_papers(
                query=args.query,
                limit=args.limit,
                scope=args.scope,
                year_from=args.year_from,
            )
        if args.ingest:
            ingested = [
                ingest_paper_record(p, packet_id=args.packet, topic=args.topic, download_oa_pdf=args.download_pdf)
                for p in papers
            ]
            print(json.dumps({"found": len(papers), "ingested": ingested}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"found": len(papers), "papers": papers}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "import-bibtex":
        bib_text = args.file.read_text(encoding="utf-8")
        papers = parse_bibtex_entries(bib_text)
        ingested = [ingest_paper_record(p, packet_id=args.packet, topic=args.topic) for p in papers]
        print(json.dumps({"parsed": len(papers), "ingested": ingested}, ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
