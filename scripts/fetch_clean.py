"""웹 URL -> 정제 마크다운 + 표 JSON + 근거 패킷 변환기 (doc-ingestor 웹 수집 파이프라인).

저장 위치 (E:\\SMC_Report_Platform_Data):
- 원시 HTML: E:\\SMC_Report_Platform_Data\\raw\\web\\<source_id>_<slug>.html
- 정제 마크다운: E:\\SMC_Report_Platform_Data\\parsed\\<source_id>_<slug>.md
- 표 JSON: E:\\SMC_Report_Platform_Data\\parsed\\<source_id>_<slug>_tables.json
- 근거 패킷: E:\\SMC_Report_Platform_Data\\evidence\\<packet_id>.json
- 중복 방지 레지스트리: E:\\SMC_Report_Platform_Data\\index\\sources.jsonl

사용 예:
    .venv\\Scripts\\python.exe scripts\\fetch_clean.py --url https://example.com --packet ch01_evidence
    .venv\\Scripts\\python.exe scripts\\fetch_clean.py --url https://example.com --extract-facts
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from compliance import (
    USER_AGENT,
    SourcesRegistry,
    check_robots_txt,
    chunk_korean_text,
    detect_prompt_injection,
    mask_pii,
    normalize_url,
    sha256_text,
    slugify,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config


def _extract_tables_from_html(html: str) -> list[dict[str, Any]]:
    """HTML <table> 요소를 행·열 경계가 보존된 표준 표 JSON으로 추출한다."""
    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
    tables_out: list[dict[str, Any]] = []
    for idx, tbl in enumerate(soup.find_all("table"), start=1):
        caption_el = tbl.find("caption")
        caption = caption_el.get_text(" ", strip=True) if caption_el else f"Table {idx}"
        headers: list[str] = []
        rows: list[list[str]] = []

        thead = tbl.find("thead")
        if thead:
            header_cells = thead.find_all(["th", "td"])
            headers = [c.get_text(" ", strip=True) for c in header_cells]

        for tr in tbl.find_all("tr"):
            if thead and tr.find_parent("thead"):
                continue
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not any(cells):
                continue
            if not headers and tr.find_all("th"):
                headers = cells
            else:
                rows.append(cells)

        if headers or rows:
            tables_out.append(
                {
                    "table_id": f"T{idx:02d}",
                    "caption": caption,
                    "page_or_section": "본문",
                    "headers": headers,
                    "rows": rows,
                }
            )
    return tables_out


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False


def _html_to_clean_markdown(html: str) -> tuple[str, str]:
    """BeautifulSoup 기반 경량 HTML -> 마크다운 정제 폴백."""
    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for tag in soup(["script", "style", "noscript", "iframe", "svg", "nav", "footer", "aside"]):
        tag.decompose()

    main = soup.find("article") or soup.find("main") or soup.body or soup
    lines: list[str] = []
    if title:
        lines.append(f"# {title}\n")

    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name == "h1":
            lines.append(f"# {txt}")
        elif el.name == "h2":
            lines.append(f"## {txt}")
        elif el.name == "h3":
            lines.append(f"### {txt}")
        elif el.name == "h4":
            lines.append(f"#### {txt}")
        elif el.name == "li":
            lines.append(f"- {txt}")
        elif el.name == "blockquote":
            lines.append(f"> {txt}")
        else:
            lines.append(txt)

    md = "\n\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return title, md


async def _fetch_with_crawl4ai(url: str) -> tuple[str, str, str, list[dict[str, Any]]] | None:
    """Crawl4AI를 우선 시도해 정제 마크다운과 표를 추출한다."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig  # type: ignore

        run_cfg = CrawlerRunConfig()
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
            if not result or not getattr(result, "success", False):
                return None
            html = getattr(result, "html", "") or ""
            md_obj = getattr(result, "markdown", "")
            md_text = getattr(md_obj, "raw_markdown", None) or str(md_obj or "")
            meta = getattr(result, "metadata", None) or {}
            title = meta.get("title") or ""
            tables = _extract_tables_from_html(html) if html else []
            return title, html, md_text, tables
    except Exception:
        return None


def _fetch_with_requests(url: str, timeout: int = 30) -> tuple[str, str, str, list[dict[str, Any]]]:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text
    title, md_text = _html_to_clean_markdown(html)
    tables = _extract_tables_from_html(html)
    return title, html, md_text, tables


def fetch_and_clean_url(
    url: str,
    packet_id: str = "default_evidence",
    topic: str = "",
    license_note: str = "공개 웹 자료 - 변환적 분석 및 인용 목적(원본 미재게시)",
    use_crawl4ai: bool = True,
    extract_facts: bool = False,
    capture_screenshot: bool = True,
    auto_unify_rag: bool = True,
    force: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    from rag_capture_unifier import download_or_capture_resource, unify_source_to_smc_graphrag

    cfg = cfg or get_config()
    norm_url = normalize_url(url)
    registry = SourcesRegistry(cfg.sources_registry_path)

    if not force:
        dup = registry.find_duplicate(url=norm_url)
        if dup:
            return {
                "status": "SKIPPED_DUPLICATE",
                "reason": "URL already collected",
                "existing": dup,
            }

    robots_allowed, robots_status = check_robots_txt(url)
    if not robots_allowed:
        return {
            "status": "BLOCKED_BY_ROBOTS",
            "url": url,
            "robots_allowed": False,
            "robots_status": robots_status,
        }

    # 직접 PDF 링크인 경우 먼저 다운로드·파싱 시도
    direct_pdf_mode = url.lower().split("?")[0].endswith(".pdf")
    fetched = None
    parser_engine = "requests_bs4"
    if not direct_pdf_mode:
        if use_crawl4ai:
            try:
                fetched = asyncio.run(_fetch_with_crawl4ai(url))
                if fetched is not None:
                    parser_engine = "crawl4ai"
            except Exception:
                fetched = None

        if fetched is None:
            try:
                fetched = _fetch_with_requests(url)
            except Exception:
                if direct_pdf_mode:
                    fetched = ("", "", "", [])
                else:
                    raise

    title, raw_html, raw_md, tables = fetched if fetched else ("", "", "", [])
    if not title:
        title = urlparse(url).netloc + urlparse(url).path

    source_id = registry.next_source_id()
    slug = slugify(title)

    # 최대한 PDF 다운로드 또는 웹페이지 스크린샷(PNG) 캡쳐 확보
    cap_res = download_or_capture_resource(
        url=url,
        html_text=raw_html,
        source_id=source_id,
        slug=slug,
        download_pdf=True,
        capture_screenshot=capture_screenshot,
        cfg=cfg,
    )
    if cap_res.get("pdf_text"):
        parser_engine = "pdf_download_pypdf"
        raw_md = (raw_md + "\n\n## 다운로드 PDF 본문\n\n" + cap_res["pdf_text"]).strip() if raw_md else f"# {title}\n\n{cap_res['pdf_text']}"

    cleaned_md, pii_count = mask_pii(raw_md)
    injection_warnings = detect_prompt_injection(cleaned_md)
    content_hash = sha256_text(cleaned_md)

    if not force:
        dup_hash = registry.find_duplicate(content_sha256=content_hash)
        if dup_hash:
            return {
                "status": "SKIPPED_DUPLICATE",
                "reason": "Identical content sha256 already collected",
                "existing": dup_hash,
            }

    raw_html_path = cfg.raw_web_dir / f"{source_id}_{slug}.html"
    parsed_md_path = cfg.parsed_dir / f"{source_id}_{slug}.md"
    tables_json_path = cfg.parsed_dir / f"{source_id}_{slug}_tables.json"

    if raw_html:
        raw_html_path.write_text(raw_html, encoding="utf-8")
    parsed_md_path.write_text(cleaned_md, encoding="utf-8")
    tables_json_path.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")

    chunks = chunk_korean_text(cleaned_md, default_section="웹 본문")
    extracted_facts: list[dict[str, Any]] = []

    if extract_facts and cleaned_md.strip():
        from local_gemma import LocalGemmaClient

        gemma = LocalGemmaClient(cfg)
        fact_res = gemma.extract_facts(source_id=source_id, markdown_text=cleaned_md)
        for kc in fact_res.get("key_concepts", []):
            extracted_facts.append(
                {
                    "claim": f"{kc.get('term', '')}: {kc.get('definition_ko', '')}".strip(": "),
                    "page_or_section": kc.get("page_or_section", "본문"),
                    "evidence_quote_short": kc.get("evidence_quote_short", ""),
                }
            )
        for vm in fact_res.get("verified_metrics", []):
            extracted_facts.append(
                {
                    "claim": f"{vm.get('metric', '')} = {vm.get('value', '')}",
                    "metric": vm.get("metric", ""),
                    "value": vm.get("value", ""),
                    "as_of_date": vm.get("as_of_date", ""),
                    "page_or_section": "본문",
                }
            )

    now = utc_now_iso()
    pdf_path = cap_res.get("pdf_path") or ""
    cap_png = cap_res.get("capture_png_path") or ""
    cap_mode = cap_res.get("capture_mode") if cap_res.get("capture_mode") != "metadata_only" else "html_archive"
    source_item = {
        "source_id": source_id,
        "source_type": "pdf" if pdf_path else "web",
        "url": url,
        "title": title,
        "accessed_at": now,
        "robots_allowed": robots_allowed,
        "robots_status": robots_status,
        "license_note": license_note,
        "page_or_section": "웹 본문 전체",
        "raw_path": pdf_path or (str(raw_html_path) if raw_html else str(parsed_md_path)),
        "parsed_path": str(parsed_md_path),
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": injection_warnings,
        "sha256": content_hash,
        "extracted_facts": extracted_facts,
        "tables": tables,
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
            "source_type": source_item["source_type"],
            "url": url,
            "normalized_url": norm_url,
            "title": title,
            "accessed_at": now,
            "robots_allowed": robots_allowed,
            "robots_status": robots_status,
            "sha256": content_hash,
            "raw_path": source_item["raw_path"],
            "pdf_path": pdf_path,
            "capture_png_path": cap_png,
            "capture_mode": cap_mode,
            "parsed_path": str(parsed_md_path),
            "packet_path": str(packet_path),
            "parser_engine": parser_engine,
            "pii_redaction_count": pii_count,
            "prompt_injection_warnings": injection_warnings,
            "chunk_count": len(chunks),
            "table_count": len(tables),
        }
    )

    rag_unified = None
    if auto_unify_rag:
        try:
            rag_unified = unify_source_to_smc_graphrag(
                source_id=source_id,
                title=title,
                markdown_text=cleaned_md,
                parsed_path=parsed_md_path,
                url=url,
                source_type=source_item["source_type"],
                provider="web_fetch",
                capture_mode=cap_mode,
                raw_path=source_item["raw_path"],
                pdf_path=pdf_path,
                capture_png_path=cap_png,
                cfg=cfg,
            )
        except Exception:
            rag_unified = None

    return {
        "status": "OK",
        "source_id": source_id,
        "source": source_item,
        "parser_engine": parser_engine,
        "title": title,
        "raw_path": source_item["raw_path"],
        "pdf_path": pdf_path,
        "capture_png_path": cap_png,
        "capture_mode": cap_mode,
        "parsed_path": str(parsed_md_path),
        "packet_path": str(packet_path),
        "robots_status": robots_status,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": injection_warnings,
        "chunk_count": len(chunks),
        "table_count": len(tables),
        "fact_count": len(extracted_facts),
        "rag_unified": bool(rag_unified),
        "rag_summary": rag_unified.get("unified_totals") if isinstance(rag_unified, dict) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="웹 URL 수집·정제·근거 패킷 생성기 (E:\\ 저장)")
    parser.add_argument("--url", required=True, help="수집할 공개 웹 URL")
    parser.add_argument("--packet", default="default_evidence", help="근거 패킷 ID (예: ch01_evidence)")
    parser.add_argument("--topic", default="", help="주제 또는 단원명")
    parser.add_argument("--license-note", default="공개 웹 자료 - 변환적 분석 및 인용 목적(원본 미재게시)")
    parser.add_argument("--no-crawl4ai", action="store_true", help="Crawl4AI 생략하고 경량 requests+BS4 사용")
    parser.add_argument("--extract-facts", action="store_true", help="로컬 Gemma 4로 핵심 개념·수치 자동 추출")
    parser.add_argument("--force", action="store_true", help="중복 URL/해시여도 강제 재수집")
    args = parser.parse_args()

    result = fetch_and_clean_url(
        url=args.url,
        packet_id=args.packet,
        topic=args.topic,
        license_note=args.license_note,
        use_crawl4ai=not args.no_crawl4ai,
        extract_facts=args.extract_facts,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("OK", "SKIPPED_DUPLICATE") else 1


if __name__ == "__main__":
    sys.exit(main())
