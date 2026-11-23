"""로컬 PDF/DOCX/HWP/HWPX/XLSX/MD 문서 -> 페이지 출처 포함 마크다운·표 JSON·근거 패킷 파서.

특징:
- PDF/DOCX/PPTX/XLSX: IBM Docling(TableFormer + 페이지/절 출처) 우선 사용 + pypdf/python-docx 폴백
- 한국어 문서(.hwp, .hwpx, .doc, .xls): 기존 C:\\SMC_GRAPHRAG\\kg_extract.py 로더 재활용
- 스캔/저텍스트 한글 PDF 감지 시 MinerU 분기 권고 경고 자동 출력
- 원본 파일은 E:\\SMC_Report_Platform_Data\\raw\\docs\\ 에 보관, 정제 산출물은 E:\\...\\parsed\\, 근거 패킷은 E:\\...\\evidence\\ 에 저장
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from compliance import (
    SourcesRegistry,
    chunk_korean_text,
    detect_prompt_injection,
    mask_pii,
    sha256_file,
    sha256_text,
    slugify,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config


def _parse_with_docling(file_path: Path) -> tuple[str, list[dict[str, Any]], int] | None:
    """Docling으로 문서 마크다운·표·페이지 출처를 추출한다."""
    try:
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        conv = converter.convert(str(file_path))
        doc = conv.document

        md_parts: list[str] = []
        pages = getattr(doc, "pages", None) or {}
        page_count = len(pages) if pages else 1

        if page_count > 1 and hasattr(doc, "export_to_markdown"):
            try:
                for pno in sorted(pages.keys()):
                    page_md = doc.export_to_markdown(page_no=pno)
                    if page_md and page_md.strip():
                        md_parts.append(f"<!-- page: {pno} -->\n{page_md.strip()}")
            except TypeError:
                md_parts = [doc.export_to_markdown()]
        else:
            md_parts = [doc.export_to_markdown()]

        tables_out: list[dict[str, Any]] = []
        for idx, tbl in enumerate(getattr(doc, "tables", []) or [], start=1):
            try:
                df = tbl.export_to_dataframe(doc=doc)
                headers = [str(c) for c in df.columns.tolist()]
                rows = [[str(v) for v in row] for row in df.values.tolist()]
                prov = getattr(tbl, "prov", None) or []
                page_no = f"p.{prov[0].page_no}" if prov and hasattr(prov[0], "page_no") else "본문"
                tables_out.append(
                    {
                        "table_id": f"T{idx:02d}",
                        "caption": f"Table {idx}",
                        "page_or_section": page_no,
                        "headers": headers,
                        "rows": rows,
                    }
                )
            except Exception:
                continue

        return "\n\n".join(md_parts), tables_out, page_count
    except Exception:
        return None


def _parse_pdf_pypdf(file_path: Path) -> tuple[str, list[dict[str, Any]], int]:
    from pypdf import PdfReader

    reader = PdfReader(str(file_path))
    parts: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        parts.append(f"<!-- page: {idx} -->\n{txt}")
    return "\n\n".join(parts), [], len(reader.pages)


def _parse_docx_python(file_path: Path) -> tuple[str, list[dict[str, Any]], int]:
    from docx import Document

    doc = Document(str(file_path))
    parts: list[str] = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        style = (p.style.name if p.style else "") or ""
        if "Heading 1" in style:
            parts.append(f"# {txt}")
        elif "Heading 2" in style:
            parts.append(f"## {txt}")
        elif "Heading 3" in style:
            parts.append(f"### {txt}")
        else:
            parts.append(txt)

    tables_out: list[dict[str, Any]] = []
    for idx, tbl in enumerate(doc.tables, start=1):
        rows_raw = [[c.text.strip() for c in row.cells] for row in tbl.rows]
        if not rows_raw:
            continue
        headers = rows_raw[0]
        rows = rows_raw[1:]
        tables_out.append(
            {
                "table_id": f"T{idx:02d}",
                "caption": f"Table {idx}",
                "page_or_section": "본문",
                "headers": headers,
                "rows": rows,
            }
        )
    return "\n\n".join(parts), tables_out, 1


def _parse_with_smc_legacy_loader(file_path: Path, cfg: PlatformConfig) -> tuple[str, list[dict[str, Any]], int]:
    """기존 C:\\SMC_GRAPHRAG\\kg_extract.py 의 HWP/HWPX/DOC/XLS/TXT 로더를 재사용한다."""
    smc_str = str(cfg.smc_graphrag_root)
    if smc_str not in sys.path:
        sys.path.insert(0, smc_str)
    import kg_extract  # type: ignore

    ext = file_path.suffix.lower()
    if ext == ".hwp":
        return kg_extract.read_hwp(file_path), [], 1
    if ext == ".hwpx":
        return kg_extract.read_hwpx(file_path), [], 1
    if ext == ".doc":
        return kg_extract.read_doc(file_path), [], 1
    if ext == ".xls":
        return kg_extract.read_xls(file_path), [], 1
    if ext == ".xlsx":
        return kg_extract.read_xlsx(file_path), [], 1
    if ext in (".txt", ".md"):
        return kg_extract.read_txt(file_path), [], 1
    raise ValueError(f"Unsupported extension for legacy loader: {ext}")


def parse_document(
    file_path: Path,
    packet_id: str = "default_evidence",
    topic: str = "",
    license_note: str = "로컬 확보 문서 - 변환적 분석 및 인용 목적",
    use_docling: bool = True,
    extract_facts: bool = False,
    force: bool = False,
    is_anchor: bool = False,
    anchor_citation: str = "",
    title_override: str = "",
    project_id: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    src_path = file_path.resolve()
    if not src_path.is_file():
        raise FileNotFoundError(f"File not found: {src_path}")

    ext = src_path.suffix.lower()
    source_type_map = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "docx",
        ".hwp": "hwp",
        ".hwpx": "hwpx",
        ".xlsx": "xlsx",
        ".xls": "xlsx",
        ".pptx": "pptx",
        ".txt": "txt",
        ".md": "md",
    }
    source_type = source_type_map.get(ext, "txt")
    raw_file_sha = sha256_file(src_path)

    registry = SourcesRegistry(cfg.sources_registry_path)
    if not force:
        dup = registry.find_duplicate(content_sha256=raw_file_sha)
        if dup:
            return {
                "status": "SKIPPED_DUPLICATE",
                "reason": "Identical raw file sha256 already ingested",
                "existing": dup,
            }

    parser_engine = ""
    parsed_result: tuple[str, list[dict[str, Any]], int] | None = None

    if use_docling and ext in (".pdf", ".docx", ".pptx", ".xlsx"):
        parsed_result = _parse_with_docling(src_path)
        if parsed_result is not None:
            parser_engine = "docling"

    if parsed_result is None:
        if ext == ".pdf":
            parsed_result = _parse_pdf_pypdf(src_path)
            parser_engine = "pypdf_fallback"
        elif ext == ".docx":
            parsed_result = _parse_docx_python(src_path)
            parser_engine = "python_docx_fallback"
        elif ext in (".txt", ".md"):
            text = src_path.read_text(encoding="utf-8", errors="replace")
            parsed_result = (text, [], 1)
            parser_engine = "plain_text"
        else:
            parsed_result = _parse_with_smc_legacy_loader(src_path, cfg)
            parser_engine = "smc_graphrag_legacy"

    raw_md, tables, page_count = parsed_result
    cleaned_md, pii_count = mask_pii(raw_md)
    injection_warnings = detect_prompt_injection(cleaned_md)

    mineru_hint = False
    if ext == ".pdf" and page_count > 0:
        avg_chars = len(cleaned_md.strip()) / page_count
        if avg_chars < 40:
            mineru_hint = True

    content_hash = sha256_text(cleaned_md) if cleaned_md.strip() else raw_file_sha
    source_id = registry.next_source_id()
    slug = slugify(src_path.stem)

    # E:\SMC_Report_Platform_Data\raw\docs\ 에 원본 보관 (이미 내부에 있으면 복사 생략)
    archived_raw = cfg.raw_docs_dir / f"{source_id}_{src_path.name}"
    if src_path.parent.resolve() != cfg.raw_docs_dir.resolve():
        shutil.copy2(src_path, archived_raw)
    else:
        archived_raw = src_path

    parsed_md_path = cfg.parsed_dir / f"{source_id}_{slug}.md"
    tables_json_path = cfg.parsed_dir / f"{source_id}_{slug}_tables.json"
    parsed_md_path.write_text(cleaned_md, encoding="utf-8")
    tables_json_path.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")

    chunks = chunk_korean_text(cleaned_md, default_section=f"p.1-{page_count}" if page_count > 1 else "본문")
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
    page_range = f"p.1-{page_count}" if page_count > 1 else "p.1"
    eff_title = (title_override or "").strip() or src_path.stem
    source_item = {
        "source_id": source_id,
        "source_type": source_type,
        "url": src_path.as_uri(),
        "title": eff_title,
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": "local_anchor_file" if is_anchor else "local_file",
        "license_note": license_note,
        "page_or_section": page_range,
        "raw_path": str(archived_raw),
        "parsed_path": str(parsed_md_path),
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": injection_warnings,
        "sha256": content_hash,
        "is_anchor": bool(is_anchor),
        "priority_weight": 3.0 if is_anchor else 1.0,
        "anchor_citation": anchor_citation.strip(),
        "citable": True,
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
    if project_id:
        proj_pkt_dir = cfg.project_e_evidence_dir(project_id)
        proj_pkt_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packet_path, proj_pkt_dir / f"{packet_id}.json")

    registry.append(
        {
            "source_id": source_id,
            "source_type": source_type,
            "url": src_path.as_uri(),
            "normalized_url": src_path.as_uri(),
            "title": eff_title,
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": "local_anchor_file" if is_anchor else "local_file",
            "is_anchor": bool(is_anchor),
            "anchor_citation": anchor_citation.strip(),
            "sha256": raw_file_sha,
            "parsed_sha256": content_hash,
            "raw_path": str(archived_raw),
            "parsed_path": str(parsed_md_path),
            "packet_path": str(packet_path),
            "parser_engine": parser_engine,
            "page_count": page_count,
            "pii_redaction_count": pii_count,
            "prompt_injection_warnings": injection_warnings,
            "mineru_recommended": mineru_hint,
            "chunk_count": len(chunks),
            "table_count": len(tables),
        }
    )

    return {
        "status": "OK",
        "source_id": source_id,
        "parser_engine": parser_engine,
        "title": eff_title,
        "is_anchor": bool(is_anchor),
        "anchor_citation": anchor_citation.strip(),
        "page_count": page_count,
        "raw_path": str(archived_raw),
        "parsed_path": str(parsed_md_path),
        "packet_path": str(packet_path),
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": injection_warnings,
        "mineru_recommended": mineru_hint,
        "chunk_count": len(chunks),
        "table_count": len(tables),
        "fact_count": len(extracted_facts),
        "source": source_item,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 PDF/DOCX/HWP 문서 파서 및 근거 패킷 생성기 (E:\\ 저장)")
    parser.add_argument("--file", type=Path, required=True, help="파싱할 로컬 문서 경로")
    parser.add_argument("--packet", default="default_evidence", help="근거 패킷 ID")
    parser.add_argument("--topic", default="", help="주제 또는 단원명")
    parser.add_argument("--license-note", default="로컬 확보 문서 - 변환적 분석 및 인용 목적")
    parser.add_argument("--no-docling", action="store_true", help="Docling 건너뛰고 경량 파서 사용")
    parser.add_argument("--extract-facts", action="store_true", help="로컬 Gemma 4로 핵심 개념·수치 자동 추출")
    parser.add_argument("--force", action="store_true", help="중복 해시여도 강제 재파싱")
    args = parser.parse_args()

    result = parse_document(
        file_path=args.file,
        packet_id=args.packet,
        topic=args.topic,
        license_note=args.license_note,
        use_docling=not args.no_docling,
        extract_facts=args.extract_facts,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
