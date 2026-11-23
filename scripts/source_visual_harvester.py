"""심층 검색 OA 논문·PDF 표/그림 자동 수집(Harvester) 및 0원 출처 기반 재작성·직접 인용 엔진.

설계 원칙 (저작권·비용·신뢰성 동시 충족):
1. 라이선스 기반 2트랙 분기 (copyright-and-citation.md 준수):
   - DIRECT_REUSE_ALLOWED (CC-BY / CC0 / Public Domain / 공공누리 제1유형 / 저자 소유):
     원논문 그림·사진 직접 인용(저자·연도·그림번호·DOI·라이선스·[SRC-NN] 필수) + 데이터 재작성 모두 허용.
   - REDRAW_DATA_ONLY (All Rights Reserved / CC-BY-ND / 라이선스 미확인):
     원본 그림 복제를 원천 차단하고, 표·정량 수치·구조를 추출해 300 DPI matplotlib 차트·비교표·SVG로 재작성(Adapted from)만 허용.
2. 비용 0원 학술 시각화:
   - Europe PMC 공식 JATS Full-Text XML(<table-wrap>, <fig>) 파싱
   - 다운로드/앵커 PDF의 IBM Docling TableFormer 표 추출 (+ CC-BY 한정 그림 추출)
   - 추출 CSV/JSON → academic_plot_style.py 300 DPI 출판급 그래프 재작성(논문 흑백 인쇄 대응)
3. 물리 저장소 규약 준수:
   - E:\\SMC_Report_Platform_Data\\projects\\<pid>\\extracted_assets\\ 에 원본 CSV·메타·CC-BY 그림 보관
   - 워크스페이스 projects/<pid>/assets/harvested_visual_assets.json 에 인덱스 저장
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

from compliance import USER_AGENT, slugify, utc_now_iso
from config import PlatformConfig, get_config

DIRECT_REUSE_LICENSES = (
    "cc-by",
    "cc by",
    "cc-by-4.0",
    "cc-by-3.0",
    "cc-by-2.0",
    "cc0",
    "cc-0",
    "public-domain",
    "public domain",
    "pd",
    "kogl-1",
    "kogl type 1",
    "공공누리 제1유형",
    "공공누리 1유형",
    "usda",
)

BLOCKED_DIRECT_REUSE_MARKERS = (
    "nd",
    "no-deriv",
    "noderiv",
    "all rights reserved",
    "all-rights-reserved",
    "publisher-specific",
)


def classify_reuse_policy(
    *,
    license_str: str = "",
    is_oa: bool = False,
    url: str = "",
    is_user_owned: bool = False,
) -> dict[str, Any]:
    """문헌/자산의 라이선스를 판정해 원본 그림 직접 인용 허용 여부(DIRECT_REUSE_ALLOWED vs REDRAW_DATA_ONLY)를 반환한다."""
    raw_lic = (license_str or "").strip()
    low = raw_lic.lower()
    url_low = (url or "").lower()

    if is_user_owned:
        return {
            "reuse_policy": "DIRECT_REUSE_ALLOWED",
            "license_normalized": raw_lic or "Author-Owned / Institutional",
            "badge_ko": "저자·기관 보유 자료 (직접 인용·재작성 가능)",
            "can_direct_reuse": True,
            "can_redraw_data": True,
            "reason": "사용자가 직접 업로드하거나 저작권을 보유한 자료",
        }

    # ND(변경금지) 또는 저작권 유보 명시 시 직접 인용 차단
    if any(b in low for b in BLOCKED_DIRECT_REUSE_MARKERS):
        return {
            "reuse_policy": "REDRAW_DATA_ONLY",
            "license_normalized": raw_lic or "Restricted",
            "badge_ko": "수치 재작성 전용 (원본 그림 복제 차단)",
            "can_direct_reuse": False,
            "can_redraw_data": True,
            "reason": f"라이선스({raw_lic})가 원본 전재/변형을 제한하므로 수치·구조 재작성만 허용",
        }

    # CC-BY / CC0 / Public Domain / 공공누리 1유형 / USDA ARS / Wikimedia CC
    if any(tok in low for tok in DIRECT_REUSE_LICENSES):
        norm = raw_lic.upper() if low.startswith("cc") else raw_lic
        return {
            "reuse_policy": "DIRECT_REUSE_ALLOWED",
            "license_normalized": norm,
            "badge_ko": f"{norm} 직접 인용 가능",
            "can_direct_reuse": True,
            "can_redraw_data": True,
            "reason": "개방형 학술/공공 라이선스 확인",
        }

    # URL 기반 대표 오픈 퍼블릭 도메인/CC-BY 출처 보조 판정 (USDA ARS 등)
    if is_oa and any(dom in url_low for dom in ("ars.usda.gov/oc/images", "commons.wikimedia.org", "mdpi.com/", "frontiersin.org/", "journals.plos.org/")):
        inferred = "CC-BY 4.0 (OA Journal)" if "usda" not in url_low else "Public Domain (USDA ARS)"
        return {
            "reuse_policy": "DIRECT_REUSE_ALLOWED",
            "license_normalized": inferred,
            "badge_ko": f"{inferred} 직접 인용 가능",
            "can_direct_reuse": True,
            "can_redraw_data": True,
            "reason": "검증된 오픈액세스(CC-BY/PD) 출처",
        }

    return {
        "reuse_policy": "REDRAW_DATA_ONLY",
        "license_normalized": raw_lic or ("OA (라이선스 미확인)" if is_oa else "All Rights Reserved / 미확인"),
        "badge_ko": "수치 재작성 전용 (Adapted from)",
        "can_direct_reuse": False,
        "can_redraw_data": True,
        "reason": "명시적 CC-BY/CC0 라이선스가 확인되지 않아 원본 그림 복제를 차단하고 데이터 기반 재작성만 허용",
    }


def build_provenance_caption(
    *,
    provenance_type: str,  # direct_reuse | adapted_redrawn | synthesized_meta
    title_ko: str,
    source_meta: dict[str, Any] | None = None,
    source_list: list[dict[str, Any]] | None = None,
    orig_label: str = "",
    extra_note: str = "",
) -> str:
    """학술 표준 3종 출처·라이선스 캡션을 생성한다."""
    sm = source_meta or {}
    sid = str(sm.get("source_id") or "").strip()
    sid_tag = f"[{sid}]" if sid else ""
    authors = str(sm.get("authors") or sm.get("author") or "").strip()
    if authors and "," in authors:
        first_a = authors.split(",")[0].strip()
        short_author = f"{first_a} et al."
    else:
        short_author = authors or str(sm.get("journal") or "원문 문헌").strip()
    year = str(sm.get("year") or "").strip()
    journal = str(sm.get("journal") or "").strip()
    doi = str(sm.get("doi") or "").strip()
    lic = str(sm.get("license_normalized") or sm.get("license") or "").strip()
    orig_part = f", {orig_label}" if orig_label else ""
    doi_part = f", {doi}" if doi else ""
    yr_part = f" ({year})" if year else ""
    j_part = f", {journal}" if journal else ""

    if provenance_type == "direct_reuse":
        lic_part = f", {lic}" if lic else ""
        base = f"출처: {short_author}{yr_part}{j_part}{orig_part}{doi_part}{lic_part} {sid_tag}.".strip()
    elif provenance_type == "synthesized_meta":
        sids = sorted({str(x.get("source_id") or "").strip() for x in (source_list or []) if x.get("source_id")})
        sids_str = ", ".join(sids) if sids else sid
        n_studies = len(source_list or [])
        n_txt = f" (n = {n_studies}편)" if n_studies else ""
        base = f"자료: [{sids_str}]의 보고 수치를 통합 재작성{n_txt} (Synthesized from cited literature)."
    else:
        base = f"자료: {short_author}{yr_part}{j_part}{orig_part} {sid_tag} 데이터를 바탕으로 재작성 (Adapted from).".strip()

    if extra_note:
        base = f"{base} {extra_note}".strip()
    return f"{title_ko}. {base}" if title_ko else base


def _xml_text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


def _parse_numeric_cell(raw: Any) -> tuple[float | None, float | None]:
    """'92.4 ± 1.2', '85.3%', '12.5 (0.8)' 등에서 중심 수치와 선택 오차(±SD/SE)를 파싱한다."""
    s = str(raw or "").strip()
    if not s or s in ("-", "—", "N/A", "NA", "n.d.", "nd"):
        return None, None
    s_clean = s.replace(",", "").replace("−", "-")
    m_pm = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?)", s_clean)
    if m_pm:
        return float(m_pm.group(1)), float(m_pm.group(2))
    m_num = re.search(r"-?\d+(?:\.\d+)?", s_clean)
    if m_num:
        return float(m_num.group(0)), None
    return None, None


def _profile_table_columns(headers: list[str], rows: list[list[str]]) -> dict[str, Any]:
    """표의 각 열에서 수치 비율을 검사해 자동 차트 재작성 적합성(plottable)을 판정한다."""
    if not headers or not rows:
        return {"plottable": False, "numeric_cols": [], "category_col": 0, "row_count": len(rows)}
    n_cols = len(headers)
    numeric_cols: list[int] = []
    for c in range(n_cols):
        vals = [r[c] if c < len(r) else "" for r in rows]
        parsed = [_parse_numeric_cell(v)[0] for v in vals]
        valid = [v for v in parsed if v is not None]
        if len(valid) >= max(2, int(len(rows) * 0.6)):
            numeric_cols.append(c)
    cat_col = next((c for c in range(n_cols) if c not in numeric_cols), 0)
    # 최소 2행 이상 + 수치 열 1개 이상이면 차트 재작성 가능
    plottable = len(rows) >= 2 and len(numeric_cols) >= 1 and (len(numeric_cols) < n_cols or n_cols >= 2)
    return {
        "plottable": plottable,
        "numeric_cols": numeric_cols,
        "category_col": cat_col,
        "row_count": len(rows),
        "col_count": n_cols,
    }


def _save_table_csv_json(
    *,
    out_dir: Path,
    asset_id: str,
    headers: list[str],
    rows: list[list[str]],
    meta: dict[str, Any],
) -> tuple[Path, Path]:
    tbl_dir = out_dir / "tables"
    tbl_dir.mkdir(parents=True, exist_ok=True)
    csv_path = tbl_dir / f"{asset_id}.csv"
    json_path = tbl_dir / f"{asset_id}.json"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    payload = {**meta, "headers": headers, "rows": rows, "csv_path": str(csv_path)}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def parse_jats_xml_tables_and_figures(
    *,
    xml_text: str,
    source_meta: dict[str, Any],
    out_dir: Path,
    pmcid: str = "",
) -> dict[str, Any]:
    """Europe PMC / PMC JATS Full-Text XML에서 <table-wrap> 표와 <fig> 그림 메타를 정밀 추출한다."""
    root = ET.fromstring(xml_text)

    # XML 내부의 <license> 확인으로 라이선스 정보 보강
    lic_text = str(source_meta.get("license") or "")
    if not lic_text:
        for lic_el in root.iter():
            tag = lic_el.tag.split("}")[-1].lower()
            if tag == "license":
                href = ""
                for k, v in lic_el.attrib.items():
                    if k.endswith("href") or "license-type" in k:
                        href += " " + str(v)
                lic_text = (href + " " + _xml_text(lic_el))[:200].strip()
                break

    policy = classify_reuse_policy(
        license_str=lic_text,
        is_oa=bool(source_meta.get("is_oa", True)),
        url=str(source_meta.get("url") or ""),
    )
    sid = str(source_meta.get("source_id") or "SRC-00")

    tables_out: list[dict[str, Any]] = []
    figures_out: list[dict[str, Any]] = []

    t_idx = 0
    f_idx = 0
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        if tag == "table-wrap":
            t_idx += 1
            label = ""
            caption = ""
            headers: list[str] = []
            rows: list[list[str]] = []
            for ch in elem:
                ctag = ch.tag.split("}")[-1].lower()
                if ctag == "label":
                    label = _xml_text(ch)
                elif ctag == "caption":
                    caption = _xml_text(ch)
            for tbl in elem.iter():
                if tbl.tag.split("}")[-1].lower() != "table":
                    continue
                for tr in tbl.iter():
                    if tr.tag.split("}")[-1].lower() != "tr":
                        continue
                    ths = [_xml_text(c) for c in tr if c.tag.split("}")[-1].lower() == "th"]
                    tds = [_xml_text(c) for c in tr if c.tag.split("}")[-1].lower() == "td"]
                    if ths and not headers:
                        headers = ths
                    elif tds:
                        rows.append(tds)
                    elif ths and headers:
                        rows.append(ths)
                break
            if not headers and rows:
                headers = rows[0]
                rows = rows[1:]
            if not headers or not rows:
                continue
            # 열 개수 정규화
            n_c = max(len(headers), max((len(r) for r in rows), default=0))
            headers = headers + [f"Col{i+1}" for i in range(len(headers), n_c)]
            norm_rows = [r[:n_c] + [""] * max(0, n_c - len(r)) for r in rows]

            asset_id = f"{sid.lower()}_jats_t{t_idx:02d}"
            prof = _profile_table_columns(headers, norm_rows)
            rec = {
                "asset_id": asset_id,
                "asset_kind": "table",
                "extractor": "europepmc_jats_xml",
                "source_id": sid,
                "source_title": source_meta.get("title", ""),
                "authors": source_meta.get("authors", ""),
                "year": source_meta.get("year", ""),
                "journal": source_meta.get("journal", ""),
                "doi": source_meta.get("doi", ""),
                "pmcid": pmcid,
                "url": source_meta.get("url", ""),
                "orig_label": label or f"Table {t_idx}",
                "caption": caption[:600],
                "headers": headers,
                "row_count": len(norm_rows),
                "preview_rows": norm_rows[:5],
                **prof,
                **policy,
                "harvested_at": utc_now_iso(),
            }
            csv_p, json_p = _save_table_csv_json(out_dir=out_dir, asset_id=asset_id, headers=headers, rows=norm_rows, meta=rec)
            rec["csv_path"] = str(csv_p)
            rec["json_path"] = str(json_p)
            tables_out.append(rec)

        elif tag == "fig":
            f_idx += 1
            label = ""
            caption = ""
            graphic_href = ""
            for ch in elem.iter():
                ctag = ch.tag.split("}")[-1].lower()
                if ctag == "label" and not label:
                    label = _xml_text(ch)
                elif ctag == "caption" and not caption:
                    caption = _xml_text(ch)
                elif ctag == "graphic" and not graphic_href:
                    for k, v in ch.attrib.items():
                        if k.endswith("href") and v:
                            graphic_href = str(v).strip()
                            break
            if not caption and not graphic_href:
                continue
            asset_id = f"{sid.lower()}_jats_f{f_idx:02d}"
            image_url = ""
            if pmcid and graphic_href:
                fname = graphic_href if "." in graphic_href else f"{graphic_href}.jpg"
                image_url = f"https://europepmc.org/articles/{pmcid}/bin/{fname}"
            figures_out.append(
                {
                    "asset_id": asset_id,
                    "asset_kind": "figure",
                    "extractor": "europepmc_jats_xml",
                    "source_id": sid,
                    "source_title": source_meta.get("title", ""),
                    "authors": source_meta.get("authors", ""),
                    "year": source_meta.get("year", ""),
                    "journal": source_meta.get("journal", ""),
                    "doi": source_meta.get("doi", ""),
                    "pmcid": pmcid,
                    "url": source_meta.get("url", ""),
                    "orig_label": label or f"Fig. {f_idx}",
                    "caption": caption[:600],
                    "graphic_href": graphic_href,
                    "remote_image_url": image_url if policy["can_direct_reuse"] else "",
                    "local_image_path": "",
                    **policy,
                    "harvested_at": utc_now_iso(),
                }
            )

    return {
        "pmcid": pmcid,
        "policy": policy,
        "tables": tables_out,
        "figures": figures_out,
    }


def fetch_europepmc_jats_assets(
    *,
    pmcid: str,
    source_meta: dict[str, Any],
    out_dir: Path,
    timeout: int = 20,
) -> dict[str, Any]:
    """Europe PMC REST API에서 JATS Full-Text XML을 받아 표·그림 자산을 추출한다."""
    clean_pmc = pmcid.strip().upper()
    if not clean_pmc.startswith("PMC"):
        clean_pmc = f"PMC{clean_pmc}"
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{clean_pmc}/fullTextXML"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return parse_jats_xml_tables_and_figures(
        xml_text=resp.text,
        source_meta=source_meta,
        out_dir=out_dir,
        pmcid=clean_pmc,
    )


def extract_pdf_tables_and_figures(
    *,
    pdf_path: Path,
    source_meta: dict[str, Any],
    out_dir: Path,
    is_user_owned: bool = False,
    extract_figures_if_allowed: bool = True,
) -> dict[str, Any]:
    """로컬/다운로드 PDF에서 Docling TableFormer로 표를 추출하고, CC-BY/소유 문서 한정으로 그림을 추출한다."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    policy = classify_reuse_policy(
        license_str=str(source_meta.get("license") or source_meta.get("license_note") or ""),
        is_oa=bool(source_meta.get("is_oa", False)),
        url=str(source_meta.get("url") or ""),
        is_user_owned=is_user_owned,
    )
    sid = str(source_meta.get("source_id") or slugify(pdf_path.stem, 16))
    tables_out: list[dict[str, Any]] = []
    figures_out: list[dict[str, Any]] = []

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipe_opts = PdfPipelineOptions()
        # 저작권 안전 가드: 직접 인용이 허용된 문서만 PDF 그림 crop 생성!
        do_pic = bool(extract_figures_if_allowed and policy["can_direct_reuse"])
        if hasattr(pipe_opts, "generate_picture_images"):
            pipe_opts.generate_picture_images = do_pic
        if hasattr(pipe_opts, "images_scale"):
            pipe_opts.images_scale = 2.0

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipe_opts)}
        )
        conv = converter.convert(str(pdf_path))
        doc = conv.document

        for idx, tbl in enumerate(getattr(doc, "tables", []) or [], 1):
            try:
                df = tbl.export_to_dataframe(doc=doc)
                headers = [str(c).strip() for c in df.columns.tolist()]
                rows = [[str(v).strip() for v in row] for row in df.values.tolist()]
                if not headers or not rows:
                    continue
                prov = getattr(tbl, "prov", None) or []
                page_no = f"p.{prov[0].page_no}" if prov and hasattr(prov[0], "page_no") else "본문"
                caption = ""
                if hasattr(tbl, "caption_text"):
                    try:
                        caption = str(tbl.caption_text(doc) or "").strip()
                    except Exception:
                        caption = ""
                asset_id = f"{sid.lower()}_pdf_t{idx:02d}"
                prof = _profile_table_columns(headers, rows)
                rec = {
                    "asset_id": asset_id,
                    "asset_kind": "table",
                    "extractor": "docling_pdf_tableformer",
                    "source_id": sid,
                    "source_title": source_meta.get("title", pdf_path.stem),
                    "authors": source_meta.get("authors", ""),
                    "year": source_meta.get("year", ""),
                    "journal": source_meta.get("journal", ""),
                    "doi": source_meta.get("doi", ""),
                    "url": source_meta.get("url", ""),
                    "orig_label": f"Table {idx} ({page_no})",
                    "caption": caption[:600],
                    "headers": headers,
                    "row_count": len(rows),
                    "preview_rows": rows[:5],
                    **prof,
                    **policy,
                    "harvested_at": utc_now_iso(),
                }
                csv_p, json_p = _save_table_csv_json(out_dir=out_dir, asset_id=asset_id, headers=headers, rows=rows, meta=rec)
                rec["csv_path"] = str(csv_p)
                rec["json_path"] = str(json_p)
                tables_out.append(rec)
            except Exception:
                continue

        fig_dir = out_dir / "figures"
        for idx, pic in enumerate(getattr(doc, "pictures", []) or [], 1):
            prov = getattr(pic, "prov", None) or []
            page_no = f"p.{prov[0].page_no}" if prov and hasattr(prov[0], "page_no") else "본문"
            caption = ""
            if hasattr(pic, "caption_text"):
                try:
                    caption = str(pic.caption_text(doc) or "").strip()
                except Exception:
                    caption = ""
            asset_id = f"{sid.lower()}_pdf_f{idx:02d}"
            local_img = ""
            if do_pic and hasattr(pic, "get_image"):
                try:
                    im = pic.get_image(doc)
                    if im is not None and im.width >= 160 and im.height >= 120:
                        fig_dir.mkdir(parents=True, exist_ok=True)
                        p_img = fig_dir / f"{asset_id}.png"
                        im.save(p_img, format="PNG")
                        local_img = str(p_img)
                except Exception:
                    local_img = ""
            figures_out.append(
                {
                    "asset_id": asset_id,
                    "asset_kind": "figure",
                    "extractor": "docling_pdf_picture",
                    "source_id": sid,
                    "source_title": source_meta.get("title", pdf_path.stem),
                    "authors": source_meta.get("authors", ""),
                    "year": source_meta.get("year", ""),
                    "journal": source_meta.get("journal", ""),
                    "doi": source_meta.get("doi", ""),
                    "url": source_meta.get("url", ""),
                    "orig_label": f"Fig. {idx} ({page_no})",
                    "caption": caption[:600],
                    "remote_image_url": "",
                    "local_image_path": local_img,
                    **policy,
                    "harvested_at": utc_now_iso(),
                }
            )
    except Exception as exc:
        return {"error": str(exc)[:220], "policy": policy, "tables": tables_out, "figures": figures_out}

    return {"policy": policy, "tables": tables_out, "figures": figures_out}


def _extract_pmcid_from_source(src: dict[str, Any]) -> str:
    for field in ("pmcid", "url", "pdf_url", "id", "title"):
        val = str(src.get(field) or "")
        m = re.search(r"(PMC\d{5,10})", val, re.I)
        if m:
            return m.group(1).upper()
    return ""


def _harvested_index_paths(project_id: str, cfg: PlatformConfig) -> tuple[Path, Path]:
    ws_idx = cfg.project_dir(project_id) / "assets" / "harvested_visual_assets.json"
    e_dir = cfg.e_projects_dir / project_id / "extracted_assets"
    e_dir.mkdir(parents=True, exist_ok=True)
    ws_idx.parent.mkdir(parents=True, exist_ok=True)
    return ws_idx, e_dir


def load_harvested_assets(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    ws_idx, _ = _harvested_index_paths(project_id, cfg)
    if ws_idx.is_file():
        try:
            return json.loads(ws_idx.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "project_id": project_id,
        "updated_at": "",
        "summary": {"total_assets": 0, "tables": 0, "plottable_tables": 0, "figures": 0, "direct_reuse_figures": 0, "redraw_only_assets": 0},
        "assets": [],
    }


def harvest_project_visual_assets(
    project_id: str,
    *,
    max_jats: int = 8,
    max_pdfs: int = 4,
    fetch_remote_jats: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트의 수집 논문(Europe PMC JATS XML + 다운로드/앵커 PDF + 기존 파싱 표)에서 인용·재작성 가능한 표와 그림을 일괄 추출한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws_idx, e_dir = _harvested_index_paths(project_id, cfg)
    assets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    errors: list[str] = []

    def _add(item: dict[str, Any]) -> None:
        aid = item.get("asset_id", "")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            assets.append(item)

    # 1) 프로젝트 근거 패킷(evidence/*.json)에 이미 파싱된 표(parse_pdf.py 앵커 PDF 포함) 즉시 수집
    ev_dirs = [cfg.project_e_evidence_dir(project_id)]
    sources_map: dict[str, dict[str, Any]] = {}
    for s in st.get("collected_sources") or []:
        sid = str(s.get("source_id") or "").strip()
        if sid:
            sources_map[sid] = dict(s)

    for ev_d in ev_dirs:
        if not ev_d.is_dir():
            continue
        for jp in sorted(ev_d.glob("*.json")):
            try:
                pkt = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for src in pkt.get("sources") or []:
                sid = str(src.get("source_id") or "").strip()
                if not sid:
                    continue
                if sid not in sources_map:
                    sources_map[sid] = dict(src)
                else:
                    merged = dict(src)
                    merged.update({k: v for k, v in sources_map[sid].items() if v})
                    sources_map[sid] = merged

                policy = classify_reuse_policy(
                    license_str=str(src.get("license") or src.get("license_note") or ""),
                    is_oa=bool(src.get("is_oa", False)),
                    url=str(src.get("url") or ""),
                    is_user_owned=bool(src.get("is_anchor", False)),
                )
                for tidx, tbl in enumerate(src.get("tables") or [], 1):
                    headers = [str(c) for c in (tbl.get("headers") or [])]
                    rows = [[str(v) for v in r] for r in (tbl.get("rows") or [])]
                    if not headers or not rows:
                        continue
                    aid = f"{sid.lower()}_ev_t{tidx:02d}"
                    prof = _profile_table_columns(headers, rows)
                    rec = {
                        "asset_id": aid,
                        "asset_kind": "table",
                        "extractor": "evidence_packet_table",
                        "source_id": sid,
                        "source_title": src.get("title", ""),
                        "authors": src.get("authors", ""),
                        "year": src.get("year", ""),
                        "journal": src.get("journal", ""),
                        "doi": src.get("doi", ""),
                        "url": src.get("url", ""),
                        "orig_label": f"{tbl.get('caption') or tbl.get('table_id') or f'Table {tidx}'} ({tbl.get('page_or_section', '본문')})",
                        "caption": str(tbl.get("caption") or "")[:500],
                        "headers": headers,
                        "row_count": len(rows),
                        "preview_rows": rows[:5],
                        **prof,
                        **policy,
                        "harvested_at": utc_now_iso(),
                    }
                    csv_p, json_p = _save_table_csv_json(out_dir=e_dir, asset_id=aid, headers=headers, rows=rows, meta=rec)
                    rec["csv_path"] = str(csv_p)
                    rec["json_path"] = str(json_p)
                    _add(rec)

    # 2) Europe PMC JATS Full-Text XML 추출 (PMCID가 있는 OA 논문 우선)
    jats_done = 0
    if fetch_remote_jats and max_jats > 0:
        for sid, src in sources_map.items():
            if jats_done >= max_jats:
                break
            pmcid = _extract_pmcid_from_source(src)
            if not pmcid:
                continue
            try:
                res = fetch_europepmc_jats_assets(pmcid=pmcid, source_meta=src, out_dir=e_dir)
                for t in res.get("tables") or []:
                    _add(t)
                for f in res.get("figures") or []:
                    _add(f)
                jats_done += 1
            except Exception as exc:
                errors.append(f"{sid} ({pmcid}): {str(exc)[:100]}")

    # 3) 로컬 저장된 다운로드/앵커 PDF에서 Docling 표·그림(CC-BY 한정) 추출
    pdfs_done = 0
    if max_pdfs > 0:
        for sid, src in sources_map.items():
            if pdfs_done >= max_pdfs:
                break
            raw_p = Path(str(src.get("pdf_path") or src.get("raw_path") or ""))
            if not raw_p.is_file() or raw_p.suffix.lower() != ".pdf":
                continue
            # 이미 해당 source_id로 표가 추출되었으면 생략
            if any(a.get("source_id") == sid and a.get("asset_kind") == "table" for a in assets):
                continue
            try:
                res = extract_pdf_tables_and_figures(
                    pdf_path=raw_p,
                    source_meta=src,
                    out_dir=e_dir,
                    is_user_owned=bool(src.get("is_anchor", False)),
                )
                for t in res.get("tables") or []:
                    _add(t)
                for f in res.get("figures") or []:
                    _add(f)
                pdfs_done += 1
            except Exception as exc:
                errors.append(f"{sid} PDF: {str(exc)[:100]}")

    summary = {
        "total_assets": len(assets),
        "tables": sum(1 for a in assets if a.get("asset_kind") == "table"),
        "plottable_tables": sum(1 for a in assets if a.get("asset_kind") == "table" and a.get("plottable")),
        "figures": sum(1 for a in assets if a.get("asset_kind") == "figure"),
        "direct_reuse_figures": sum(1 for a in assets if a.get("asset_kind") == "figure" and a.get("can_direct_reuse")),
        "redraw_only_assets": sum(1 for a in assets if not a.get("can_direct_reuse")),
        "jats_papers_parsed": jats_done,
        "pdfs_parsed": pdfs_done,
        "errors_count": len(errors),
    }
    payload = {
        "project_id": project_id,
        "updated_at": utc_now_iso(),
        "storage_dir": str(e_dir),
        "summary": summary,
        "errors": errors[:20],
        "assets": assets,
    }
    ws_idx.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (e_dir / "harvested_visual_assets.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _register_visual_into_plan(
    *,
    project_id: str,
    chapter_id: str,
    record: dict[str, Any],
    cfg: PlatformConfig,
) -> None:
    """재작성 또는 직접 인용한 도판을 프로젝트의 visuals_plan.json에 추가/갱신한다."""
    ws = cfg.project_dir(project_id)
    plan_p = ws / "assets" / "visuals_plan.json"
    if plan_p.is_file():
        try:
            plan = json.loads(plan_p.read_text(encoding="utf-8"))
        except Exception:
            plan = {"project_id": project_id, "visuals": []}
    else:
        plan = {"project_id": project_id, "visuals": []}

    vis_list = list(plan.get("visuals") or plan.get("items") or [])
    fid = record["figure_id"]
    vis_list = [v for v in vis_list if v.get("figure_id") != fid]
    vis_list.append(record)
    vis_list.sort(key=lambda x: (int(x.get("chapter_number") or 0), str(x.get("figure_id") or "")))
    plan["visuals"] = vis_list
    plan["total_visuals"] = len(vis_list)
    plan["updated_at"] = utc_now_iso()
    plan_p.parent.mkdir(parents=True, exist_ok=True)
    plan_p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def redraw_chart_from_harvested_table(
    *,
    project_id: str,
    asset_id: str,
    chapter_id: str = "ch03",
    figure_no: str = "",
    title_ko: str = "",
    chart_type: str = "bar",
    x_col: int | None = None,
    y_cols: list[int] | None = None,
    x_label: str = "",
    y_label: str = "",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """수집된 원논문 표(CSV/JSON)로부터 300 DPI 출판급 matplotlib 차트를 0원으로 재작성하고 출처 캡션을 부착한다."""
    from academic_plot_style import render_data_chart_png
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    idx = load_harvested_assets(project_id, cfg)
    asset = next((a for a in idx.get("assets") or [] if a.get("asset_id") == asset_id), None)
    if not asset or asset.get("asset_kind") != "table":
        raise FileNotFoundError(f"Harvested table asset not found: {asset_id}")

    json_p = Path(asset.get("json_path") or "")
    if not json_p.is_file():
        raise FileNotFoundError(f"Table JSON missing: {json_p}")
    tbl_data = json.loads(json_p.read_text(encoding="utf-8"))
    headers: list[str] = list(tbl_data.get("headers") or [])
    rows: list[list[str]] = list(tbl_data.get("rows") or [])

    prof = _profile_table_columns(headers, rows)
    num_cols = prof["numeric_cols"]
    if not num_cols:
        raise ValueError("선택한 표에 그래프화할 수치 열이 없습니다.")

    xc = int(x_col) if x_col is not None else int(prof["category_col"])
    selected_ys = [int(c) for c in y_cols] if y_cols else [c for c in num_cols if c != xc][:3]
    if not selected_ys:
        selected_ys = num_cols[:2]

    x_vals_raw: list[Any] = []
    series_vals: dict[int, list[float]] = {c: [] for c in selected_ys}
    series_errs: dict[int, list[float]] = {c: [] for c in selected_ys}
    has_err: dict[int, bool] = {c: False for c in selected_ys}

    for r in rows[:18]:
        xv = r[xc] if xc < len(r) else ""
        row_nums: dict[int, tuple[float | None, float | None]] = {}
        ok_row = True
        for yc in selected_ys:
            val, err = _parse_numeric_cell(r[yc] if yc < len(r) else "")
            if val is None:
                ok_row = False
                break
            row_nums[yc] = (val, err)
        if not ok_row:
            continue
        x_vals_raw.append(str(xv)[:22] if not _parse_numeric_cell(xv)[0] else str(xv)[:18])
        for yc in selected_ys:
            val, err = row_nums[yc]
            assert val is not None
            series_vals[yc].append(val)
            if err is not None:
                has_err[yc] = True
            series_errs[yc].append(err or 0.0)

    if len(x_vals_raw) < 2:
        raise ValueError("유효한 수치 행이 2개 미만이어서 그래프를 재작성할 수 없습니다.")

    series_payload = []
    for yc in selected_ys:
        s_item: dict[str, Any] = {
            "label": headers[yc] if yc < len(headers) else f"Series {yc+1}",
            "y": series_vals[yc],
            "kind": "line" if chart_type == "line" else "bar",
        }
        if has_err[yc]:
            s_item["yerr"] = series_errs[yc]
        series_payload.append(s_item)

    m_num = re.search(r"(\d+)", chapter_id)
    ch_num = int(m_num.group(1)) if m_num else 1
    fig_id = f"fig_{chapter_id}_redraw_{slugify(asset_id, 24)}"
    fig_label = figure_no or f"그림 {ch_num}-{slugify(asset_id, 8)}"
    clean_title = title_ko.strip() or (asset.get("caption") or asset.get("orig_label") or asset_id)[:52]
    full_title = f"{fig_label}. {clean_title}"

    source_note = build_provenance_caption(
        provenance_type="adapted_redrawn",
        title_ko="",
        source_meta=asset,
        orig_label=str(asset.get("orig_label") or ""),
    )
    paper_mode = (st.get("primary_output_type") == "paper")

    ws = cfg.project_dir(project_id)
    by_ch_dir = ws / "assets" / "by_chapter" / chapter_id
    chart_data_dir = ws / "assets" / "chart_data"
    e_ch_dir = cfg.e_projects_dir / project_id / "visuals" / "by_chapter" / chapter_id
    for d in (by_ch_dir, chart_data_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    out_png = by_ch_dir / f"{fig_id}.png"
    csv_out = chart_data_dir / f"{fig_id}.csv"
    render_res = render_data_chart_png(
        out_png=out_png,
        chart_type="line" if chart_type == "line" else "bar",
        title=full_title,
        x_label=x_label.strip() or (headers[xc] if xc < len(headers) else "구분"),
        y_label=y_label.strip() or ", ".join(headers[c] for c in selected_ys if c < len(headers))[:40],
        source_note=source_note,
        series=series_payload,
        x_values=x_vals_raw,
        paper_mode=paper_mode,
        csv_out_path=csv_out,
    )
    shutil.copy2(out_png, e_ch_dir / out_png.name)
    if csv_out.is_file():
        shutil.copy2(csv_out, e_ch_dir / csv_out.name)

    rel_url = f"/project-files/{project_id}/assets/by_chapter/{chapter_id}/{out_png.name}"
    narrative = (
        f"{full_title}은(는) {asset.get('source_title') or asset.get('source_id')}의 원문 표({asset.get('orig_label')})에서 추출한 "
        f"실측 수치를 바탕으로 재작성한 정량 그래프이다. "
        f"가로축({x_label or headers[xc]})별 지표 변화와 오차 범위를 비교해 읽는다. ({source_note})"
    )
    vis_record = {
        "figure_id": fig_id,
        "figure_no": fig_label,
        "chapter_id": chapter_id,
        "chapter_number": ch_num,
        "type": "D",
        "visual_type": "quantitative_chart",
        "kind": "matplotlib_redrawn_from_table",
        "title_ko": full_title,
        "narrative_ko": narrative,
        "source_note": source_note,
        "provenance_type": "adapted_redrawn",
        "source_id": asset.get("source_id", ""),
        "source_doi": asset.get("doi", ""),
        "orig_label": asset.get("orig_label", ""),
        "license": asset.get("license_normalized", ""),
        "data_csv_path": str(csv_out),
        "path": str(out_png),
        "docx_image_path": str(out_png),
        "rel_url": rel_url,
        "png_url": rel_url,
        "filename": out_png.name,
        "engine": "Matplotlib 300 DPI Redrawn (0원 · 출처 표 재작성)",
        "is_ai_image": False,
        "status": "GENERATED",
        "exclude_from_publish": False,
        "updated_at": utc_now_iso(),
    }
    _register_visual_into_plan(project_id=project_id, chapter_id=chapter_id, record=vis_record, cfg=cfg)
    return {"status": "OK", "visual": vis_record, "render": render_res}


def synthesize_multi_source_comparison_chart(
    *,
    project_id: str,
    chapter_id: str,
    figure_no: str,
    title_ko: str,
    x_label: str,
    y_label: str,
    records: list[dict[str, Any]],
    chart_type: str = "bar",
    series_label: str = "보고 지표",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """다중 논문(리뷰 문헌 비교표) 수치를 하나의 300 DPI 메타 비교 그래프로 통합 재작성한다 (비용 0원)."""
    from academic_plot_style import render_data_chart_png
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    if len(records) < 2:
        raise ValueError("다중 문헌 비교 그래프는 최소 2개 이상의 문헌 수치 레코드가 필요합니다.")

    x_vals = [str(r["label"])[:26] for r in records]
    y_vals = [float(r["value"]) for r in records]
    y_errs = [float(r["yerr"]) for r in records] if any(r.get("yerr") is not None for r in records) else None
    series_item: dict[str, Any] = {"label": series_label, "y": y_vals, "kind": chart_type}
    if y_errs:
        series_item["yerr"] = [float(r.get("yerr") or 0.0) for r in records]

    m_num = re.search(r"(\d+)", chapter_id)
    ch_num = int(m_num.group(1)) if m_num else 3
    fig_id = f"fig_{chapter_id}_meta_{slugify(title_ko, 20)}"
    full_title = f"{figure_no}. {title_ko}"
    source_note = build_provenance_caption(
        provenance_type="synthesized_meta",
        title_ko="",
        source_list=records,
    )
    paper_mode = (st.get("primary_output_type") == "paper")

    ws = cfg.project_dir(project_id)
    by_ch_dir = ws / "assets" / "by_chapter" / chapter_id
    chart_data_dir = ws / "assets" / "chart_data"
    e_ch_dir = cfg.e_projects_dir / project_id / "visuals" / "by_chapter" / chapter_id
    for d in (by_ch_dir, chart_data_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    out_png = by_ch_dir / f"{fig_id}.png"
    csv_out = chart_data_dir / f"{fig_id}.csv"
    render_res = render_data_chart_png(
        out_png=out_png,
        chart_type=chart_type,
        title=full_title,
        x_label=x_label,
        y_label=y_label,
        source_note=source_note,
        series=[series_item],
        x_values=x_vals,
        paper_mode=paper_mode,
        csv_out_path=csv_out,
    )
    shutil.copy2(out_png, e_ch_dir / out_png.name)
    if csv_out.is_file():
        shutil.copy2(csv_out, e_ch_dir / csv_out.name)

    rel_url = f"/project-files/{project_id}/assets/by_chapter/{chapter_id}/{out_png.name}"
    vis_record = {
        "figure_id": fig_id,
        "figure_no": figure_no,
        "chapter_id": chapter_id,
        "chapter_number": ch_num,
        "type": "D",
        "visual_type": "quantitative_chart",
        "kind": "matplotlib_meta_synthesis",
        "title_ko": full_title,
        "narrative_ko": f"{full_title}은(는) {len(records)}개 선행 연구의 정량 수치를 동일 척도로 통합 비교한 그래프이다. 각 항목별 수치와 오차 범위를 비교해 읽는다. ({source_note})",
        "source_note": source_note,
        "provenance_type": "synthesized_meta",
        "source_ids": sorted({str(r.get("source_id") or "") for r in records if r.get("source_id")}),
        "data_csv_path": str(csv_out),
        "path": str(out_png),
        "docx_image_path": str(out_png),
        "rel_url": rel_url,
        "png_url": rel_url,
        "filename": out_png.name,
        "engine": "Matplotlib 300 DPI Meta-Synthesis (0원 · 다중 문헌 통합)",
        "is_ai_image": False,
        "status": "GENERATED",
        "exclude_from_publish": False,
        "updated_at": utc_now_iso(),
    }
    _register_visual_into_plan(project_id=project_id, chapter_id=chapter_id, record=vis_record, cfg=cfg)
    return {"status": "OK", "visual": vis_record, "render": render_res}


def adopt_direct_reuse_figure(
    *,
    project_id: str,
    asset_id: str,
    chapter_id: str = "ch03",
    figure_no: str = "",
    title_ko: str = "",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """CC-BY/CC0/공공누리1유형 등 개방 라이선스가 검증된 원논문 그림만 직접 인용으로 채택한다 (비-OA 차단)."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    idx = load_harvested_assets(project_id, cfg)
    asset = next((a for a in idx.get("assets") or [] if a.get("asset_id") == asset_id), None)
    if not asset or asset.get("asset_kind") != "figure":
        raise FileNotFoundError(f"Harvested figure asset not found: {asset_id}")
    if not asset.get("can_direct_reuse"):
        raise PermissionError(
            f"저작권 보호 차단: {asset_id}의 라이선스({asset.get('license_normalized')})는 원본 그림 직접 인용을 허용하지 않습니다. "
            "수치 재작성(redraw) 또는 구조 재도해를 사용해 주세요."
        )

    m_num = re.search(r"(\d+)", chapter_id)
    ch_num = int(m_num.group(1)) if m_num else 1
    fig_id = f"fig_{chapter_id}_cited_{slugify(asset_id, 24)}"
    ws = cfg.project_dir(project_id)
    by_ch_dir = ws / "assets" / "by_chapter" / chapter_id
    e_ch_dir = cfg.e_projects_dir / project_id / "visuals" / "by_chapter" / chapter_id
    for d in (by_ch_dir, e_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    local_src = Path(asset.get("local_image_path") or "")
    out_img: Path
    if local_src.is_file():
        out_img = by_ch_dir / f"{fig_id}{local_src.suffix.lower() or '.png'}"
        shutil.copy2(local_src, out_img)
    elif asset.get("remote_image_url"):
        resp = requests.get(asset["remote_image_url"], headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        ext = ".png" if "png" in resp.headers.get("content-type", "").lower() else ".jpg"
        out_img = by_ch_dir / f"{fig_id}{ext}"
        out_img.write_bytes(resp.content)
    else:
        raise FileNotFoundError("직접 인용할 로컬/원격 이미지 파일 경로가 없습니다.")

    shutil.copy2(out_img, e_ch_dir / out_img.name)

    fig_label = figure_no or f"그림 {ch_num}-{slugify(asset_id, 8)}"
    clean_title = title_ko.strip() or (asset.get("caption") or asset.get("orig_label") or asset_id)[:52]
    full_title = f"{fig_label}. {clean_title}"
    source_note = build_provenance_caption(
        provenance_type="direct_reuse",
        title_ko="",
        source_meta=asset,
        orig_label=str(asset.get("orig_label") or ""),
    )
    rel_url = f"/project-files/{project_id}/assets/by_chapter/{chapter_id}/{out_img.name}"
    vis_record = {
        "figure_id": fig_id,
        "figure_no": fig_label,
        "chapter_id": chapter_id,
        "chapter_number": ch_num,
        "type": "A",
        "visual_type": "cited_open_access_figure",
        "kind": "cited_direct_reuse",
        "title_ko": full_title,
        "narrative_ko": f"{full_title}은(는) 개방형 학술 라이선스({asset.get('license_normalized')})로 공개된 선행 연구의 원 도판을 정식 출처와 함께 직접 인용한 자료이다. 원문 그림 번호와 본문 설명을 대조해 읽는다. ({source_note})",
        "source_note": source_note,
        "provenance_type": "direct_reuse",
        "source_id": asset.get("source_id", ""),
        "source_doi": asset.get("doi", ""),
        "orig_label": asset.get("orig_label", ""),
        "license": asset.get("license_normalized", ""),
        "path": str(out_img),
        "docx_image_path": str(out_img),
        "rel_url": rel_url,
        "png_url": rel_url,
        "filename": out_img.name,
        "engine": f"Direct Cited Figure (0원 · {asset.get('license_normalized')})",
        "is_ai_image": False,
        "status": "GENERATED",
        "exclude_from_publish": False,
        "updated_at": utc_now_iso(),
    }
    _register_visual_into_plan(project_id=project_id, chapter_id=chapter_id, record=vis_record, cfg=cfg)
    return {"status": "OK", "visual": vis_record}
