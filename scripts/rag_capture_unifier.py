"""검색 자료 최대 다운로드 · 웹페이지 캡쳐 · C:\\SMC_GRAPHRAG 통합 RAG 결합 엔진.

핵심 기능:
1. 검색된 모든 자료(학술 논문, 공식기관 웹페이지, 통계/기상 데이터, NotebookLM, BibTeX)에 대해:
   - 공개 PDF 다운로드 가능한 경우 최우선 다운로드 및 본문 텍스트 추출 (paywall 우회 절대 금지)
   - PDF가 없거나 웹페이지인 경우 원문 HTML + 헤드리스 Chromium 풀페이지 스크린샷(PNG) 캡쳐 저장
2. 저장된 모든 정제 문서·청크·캡쳐 메타데이터·엔티티 관계를 C:\\SMC_GRAPHRAG 에 통합 결합:
   - C:\\SMC_GRAPHRAG\\unified_rag\\documents\\ (정제 마크다운 통합 보관)
   - C:\\SMC_GRAPHRAG\\unified_rag\\captures\\ (웹 캡쳐 PNG 미러 보관)
   - C:\\SMC_GRAPHRAG\\unified_rag\\unified_rag_corpus.sqlite (SQLite FTS5 전문·청크 통합 RAG DB)
   - C:\\SMC_GRAPHRAG\\output\\graph_platform_incremental.json (+ .graphml, triples CSV 증분 병합;
     기존 graph.json은 절대 덮어쓰지 않고 갱신 전 backup/ 백업)
   - LightRAG 서버(127.0.0.1:9621) 및 Neo4j 온라인 시 동시 증분 적재 + 카탈로그 재색인
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import networkx as nx
import requests

from compliance import (
    USER_AGENT,
    SourcesRegistry,
    check_robots_txt,
    chunk_korean_text,
    mask_pii,
    normalize_entities_with_glossary,
    sha256_text,
    slugify,
    utc_now_iso,
)
from config import PlatformConfig, get_config

_CHROMIUM_CACHE: Path | None | bool = False


def _find_chromium_bin() -> Path | None:
    global _CHROMIUM_CACHE
    if _CHROMIUM_CACHE is not False:
        return _CHROMIUM_CACHE  # type: ignore[return-value]
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if c.is_file():
            _CHROMIUM_CACHE = c
            return c
    _CHROMIUM_CACHE = None
    return None


def _extract_pdf_text_pypdf(pdf_path: Path, max_pages: int = 25) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages[:max_pages], start=1):
            txt = (page.extract_text() or "").strip()
            if txt:
                pages.append(f"<!-- page: {idx} -->\n{txt}")
        return "\n\n".join(pages)
    except Exception:
        return ""


def _discover_oa_pdf_url(url: str = "", doi: str = "", html_text: str = "") -> str:
    """공개 HTML 메타태그(citation_pdf_url) 또는 Europe PMC/Unpaywall 공개 API로 합법적 OA PDF 링크를 탐색한다."""
    if html_text:
        m = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', html_text, re.I)
        if m:
            return urljoin(url, m.group(1).strip())
        m2 = re.search(r'<a[^>]+href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html_text, re.I)
        if m2:
            return urljoin(url, m2.group(1).strip())

    clean_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    if clean_doi and "/" in clean_doi:
        # 1) Unpaywall 공개 OA 조회 (페이월 우회 없음, 합법적 OA 링크만 반환)
        try:
            r = requests.get(
                f"https://api.unpaywall.org/v2/{clean_doi}",
                params={"email": "research-platform@example.org"},
                headers={"User-Agent": USER_AGENT},
                timeout=8,
            )
            if r.status_code == 200:
                best = r.json().get("best_oa_location") or {}
                pdf_u = best.get("url_for_pdf") or ""
                if pdf_u:
                    return str(pdf_u)
        except Exception:
            pass
    return ""


def capture_webpage_screenshot(
    url: str,
    out_png: Path,
    timeout: int = 22,
) -> bool:
    """공개 웹페이지를 헤드리스 Chromium(Edge/Chrome)으로 스크린샷(PNG) 캡쳐한다."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    chrome = _find_chromium_bin()
    if not chrome:
        return False
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--window-size=1366,2200",
        "--virtual-time-budget=6000",
        f"--screenshot={out_png}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0 and out_png.is_file() and out_png.stat().st_size > 2500
    except Exception:
        return False


def download_or_capture_resource(
    *,
    url: str = "",
    pdf_url: str = "",
    doi: str = "",
    html_text: str = "",
    source_id: str = "SRC",
    slug: str = "doc",
    download_pdf: bool = True,
    capture_screenshot: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """검색·수집 자료 1건에 대해 PDF 다운로드 또는 웹페이지 스크린샷 캡쳐를 최대한 확보한다."""
    cfg = cfg or get_config()
    cfg.raw_docs_dir.mkdir(parents=True, exist_ok=True)
    cfg.raw_captures_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "capture_mode": "metadata_only",
        "pdf_path": "",
        "pdf_text": "",
        "capture_png_path": "",
        "unified_capture_path": "",
    }

    # 1) PDF 후보 다운로드 시도 (합법적 공개 PDF만)
    if download_pdf:
        pdf_candidates: list[str] = []
        if pdf_url and pdf_url.startswith(("http://", "https://")):
            pdf_candidates.append(pdf_url)
        if url and url.lower().split("?")[0].endswith(".pdf"):
            pdf_candidates.append(url)
        discovered = _discover_oa_pdf_url(url=url, doi=doi, html_text=html_text)
        if discovered and discovered not in pdf_candidates:
            pdf_candidates.append(discovered)

        for cand in pdf_candidates[:3]:
            try:
                allowed, _ = check_robots_txt(cand)
                if not allowed:
                    continue
                r = requests.get(cand, headers={"User-Agent": USER_AGENT}, timeout=25, allow_redirects=True)
                ctype = (r.headers.get("content-type") or "").lower()
                is_pdf_bytes = r.content[:5] == b"%PDF-"
                if r.status_code == 200 and ("pdf" in ctype or is_pdf_bytes) and len(r.content) > 1500:
                    dest_pdf = cfg.raw_docs_dir / f"{source_id}_{slug}.pdf"
                    dest_pdf.write_bytes(r.content)
                    extracted = _extract_pdf_text_pypdf(dest_pdf)
                    result["pdf_path"] = str(dest_pdf)
                    result["pdf_text"] = extracted
                    result["capture_mode"] = "pdf_download"
                    break
            except Exception:
                continue

    # 2) 웹페이지 풀페이지 스크린샷 캡쳐 (PDF가 없거나 웹 출처일 때 시각 원문 증빙 확보)
    if capture_screenshot and url and url.startswith(("http://", "https://")) and not result["pdf_path"]:
        try:
            allowed, _ = check_robots_txt(url)
            if allowed:
                cap_png = cfg.raw_captures_dir / f"{source_id}_{slug}.png"
                if capture_webpage_screenshot(url, cap_png):
                    result["capture_png_path"] = str(cap_png)
                    result["capture_mode"] = "web_capture_png"
                    # C:\SMC_GRAPHRAG\unified_rag\captures\ 미러 보관
                    u_cap_dir = cfg.smc_unified_rag_dir / "captures"
                    u_cap_dir.mkdir(parents=True, exist_ok=True)
                    u_cap_png = u_cap_dir / cap_png.name
                    shutil.copy2(cap_png, u_cap_png)
                    result["unified_capture_path"] = str(u_cap_png)
        except Exception:
            pass

    return result


# ============================================================
# C:\SMC_GRAPHRAG 통합 RAG SQLite FTS5 + 증분 지식그래프 결합
# ============================================================
def _init_unified_rag_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            source_id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            source_type TEXT,
            provider TEXT,
            project_id TEXT,
            capture_mode TEXT,
            raw_path TEXT,
            pdf_path TEXT,
            capture_png_path TEXT,
            parsed_path TEXT,
            unified_md_path TEXT,
            sha256 TEXT,
            char_count INTEGER,
            chunk_count INTEGER,
            kg_synced INTEGER DEFAULT 0,
            lightrag_synced INTEGER DEFAULT 0,
            ingested_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_uid TEXT PRIMARY KEY,
            source_id TEXT,
            chunk_index INTEGER,
            page_or_section TEXT,
            text TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            source_id,
            title,
            page_or_section,
            text,
            tokenize='unicode61'
        )
        """
    )
    conn.commit()
    return conn


def _heuristic_extract_triples(title: str, text: str, cfg: PlatformConfig) -> dict[str, Any]:
    """Ollama 오프라인 시에도 100% 누락 없이 C:\\SMC_GRAPHRAG 증분 그래프에 결합하기 위한 결정론적 트리플 추출기."""
    entities: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    seen_names: set[str] = set()

    def _add_ent(name: str, etype: str = "CONCEPT") -> str:
        clean = re.sub(r"\s+", " ", name).strip("[]()<>-·:;,.\"' ")
        if len(clean) < 2 or len(clean) > 80:
            return ""
        if clean not in seen_names:
            seen_names.add(clean)
            entities.append({"name": clean, "type": etype})
        return clean

    root_ent = _add_ent(re.sub(r"^\[?\d{4}\]?\s*", "", title)[:64], "DOCUMENT_TOPIC")

    # 1) 용어집(glossary.json) 매칭 엔티티
    if cfg.glossary_path.is_file():
        try:
            gdata = json.loads(cfg.glossary_path.read_text(encoding="utf-8"))
            terms = gdata.get("terms") or gdata.get("entries") or (gdata if isinstance(gdata, list) else [])
            low_txt = text.lower()
            for t in terms:
                if isinstance(t, dict):
                    canon = str(t.get("canonical") or t.get("term") or "").strip()
                    if canon and canon.lower() in low_txt:
                        e = _add_ent(canon, "DOMAIN_TERM")
                        if root_ent and e and e != root_ent:
                            relations.append({"source": root_ent, "relation": "다룬다", "target": e})
        except Exception:
            pass

    # 2) 마크다운 헤딩(##, ###) 및 굵은 핵심어(**...**) 추출
    for m in re.finditer(r"(?m)^#{2,3}\s+(.+)$", text):
        h = m.group(1).strip()
        if any(skip in h for skip in ("참고문헌", "초록", "Abstract")):
            continue
        e = _add_ent(h, "SECTION_CONCEPT")
        if root_ent and e and e != root_ent:
            relations.append({"source": root_ent, "relation": "포함한다", "target": e})
        if len(entities) >= 18:
            break

    for m in re.finditer(r"\*\*([가-힣A-Za-z0-9\s\-/()]{2,32})\*\*", text):
        e = _add_ent(m.group(1), "KEY_TERM")
        if root_ent and e and e != root_ent:
            relations.append({"source": root_ent, "relation": "관련개념", "target": e})
        if len(entities) >= 24:
            break

    # 3) 농업 핵심 31 키워드 교차 매칭
    try:
        from agro_framework import AGRO_CORE_KEYWORDS_31

        for dom in AGRO_CORE_KEYWORDS_31:
            for kw in dom.get("keywords", []):
                ko = kw.get("ko", "")
                short_ko = re.split(r"[·(]", ko)[0].strip()
                if short_ko and len(short_ko) >= 2 and short_ko in text:
                    e = _add_ent(ko, dom.get("domain_ko", "AGRO_CONCEPT"))
                    if root_ent and e and e != root_ent:
                        relations.append({"source": root_ent, "relation": "적용분야", "target": e})
    except Exception:
        pass

    return {"entities": entities[:28], "relations": relations[:36]}


def _append_single_source_to_incremental_kg(
    *,
    source_id: str,
    title: str,
    normalized_text: str,
    category: str = "unified_rag",
    use_ollama: bool = False,
    cfg: PlatformConfig,
) -> dict[str, Any]:
    """기존 C:\\SMC_GRAPHRAG\\output\\graph.json을 절대 건드리지 않고 graph_platform_incremental.json에 안전 증분 병합한다."""
    inc_path = cfg.smc_incremental_graph_path
    inc_path.parent.mkdir(parents=True, exist_ok=True)

    # 갱신 전 백업 (1시간 내 중복 백업 폭증 방지: 같은 분 단위 1회)
    if inc_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        bdir = cfg.smc_graphrag_backup_dir / f"unified_{stamp}"
        if not bdir.exists():
            bdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(inc_path, bdir / inc_path.name)

    if inc_path.is_file():
        try:
            raw = json.loads(inc_path.read_text(encoding="utf-8"))
            G = nx.node_link_graph(raw, edges="edges" if "edges" in raw else "links")
        except Exception:
            G = nx.MultiDiGraph()
    else:
        G = nx.MultiDiGraph()

    before_nodes, before_edges = G.number_of_nodes(), G.number_of_edges()

    triples: dict[str, Any] | None = None
    if use_ollama:
        try:
            from local_gemma import LocalGemmaClient

            gemma = LocalGemmaClient(cfg)
            triples = gemma.extract_triples(normalized_text[:3600], model=cfg.ollama_fast_model)
        except Exception:
            triples = None

    if not triples or not triples.get("entities"):
        triples = _heuristic_extract_triples(title, normalized_text[:12000], cfg)

    doc_label = f"{source_id} | {title[:80]}"
    valid_names: set[str] = set()
    for ent in triples.get("entities", []):
        name = (ent.get("name") or "").strip()
        etype = (ent.get("type") or "CONCEPT").strip()
        if not name or len(name) > 120:
            continue
        valid_names.add(name)
        if G.has_node(name):
            G.nodes[name]["mentions"] = int(G.nodes[name].get("mentions", 1) or 1) + 1
            srcs = set(str(G.nodes[name].get("source_ids", "")).split(",")) - {""}
            srcs.add(source_id)
            G.nodes[name]["source_ids"] = ",".join(sorted(srcs))
        else:
            G.add_node(name, type=etype, mentions=1, source_ids=source_id, category=category)

    for rel in triples.get("relations", []):
        s = (rel.get("source") or "").strip()
        r = (rel.get("relation") or "관련").strip()
        t = (rel.get("target") or "").strip()
        if s in valid_names and t in valid_names and r and s != t:
            G.add_edge(s, t, relation=r, source_doc=doc_label, source_id=source_id)

    data = nx.node_link_data(G, edges="edges")
    tmp = inc_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(inc_path)

    # GraphML + Triples CSV도 동시 갱신
    try:
        nx.write_graphml(G, str(cfg.smc_graphrag_output_dir / "graph_platform_incremental.graphml"))
        csv_p = cfg.smc_graphrag_output_dir / "triples_platform_incremental.csv"
        with csv_p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source", "relation", "target", "source_id", "source_doc"])
            for u, v, d in G.edges(data=True):
                w.writerow([u, d.get("relation", ""), v, d.get("source_id", ""), d.get("source_doc", "")])
    except Exception:
        pass

    return {
        "nodes_added": G.number_of_nodes() - before_nodes,
        "edges_added": G.number_of_edges() - before_edges,
        "nodes_total": G.number_of_nodes(),
        "edges_total": G.number_of_edges(),
    }


def _write_unified_manifest(cfg: PlatformConfig) -> dict[str, Any]:
    db_path = cfg.smc_unified_rag_db_path
    conn = _init_unified_rag_db(db_path)
    cur = conn.cursor()
    tot_docs = cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    tot_chunks = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    pdf_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE pdf_path IS NOT NULL AND pdf_path != ''").fetchone()[0]
    cap_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE capture_png_path IS NOT NULL AND capture_png_path != ''").fetchone()[0]
    kg_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE kg_synced = 1").fetchone()[0]
    lr_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE lightrag_synced = 1").fetchone()[0]
    conn.close()

    inc_nodes, inc_edges = 0, 0
    if cfg.smc_incremental_graph_path.is_file():
        try:
            raw = json.loads(cfg.smc_incremental_graph_path.read_text(encoding="utf-8"))
            inc_nodes = len(raw.get("nodes") or [])
            inc_edges = len(raw.get("edges") or raw.get("links") or [])
        except Exception:
            pass

    manifest = {
        "updated_at": utc_now_iso(),
        "smc_graphrag_root": str(cfg.smc_graphrag_root),
        "unified_rag_dir": str(cfg.smc_unified_rag_dir),
        "unified_db_path": str(db_path),
        "incremental_graph_path": str(cfg.smc_incremental_graph_path),
        "total_documents": tot_docs,
        "total_chunks": tot_chunks,
        "downloaded_pdfs": pdf_docs,
        "captured_web_pngs": cap_docs,
        "kg_synced_documents": kg_docs,
        "lightrag_synced_documents": lr_docs,
        "incremental_kg_nodes": inc_nodes,
        "incremental_kg_edges": inc_edges,
    }
    (cfg.smc_unified_rag_dir / "unified_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def unify_source_to_smc_graphrag(
    *,
    source_id: str,
    title: str,
    markdown_text: str = "",
    parsed_path: str | Path | None = None,
    url: str = "",
    source_type: str = "web",
    provider: str = "",
    project_id: str = "",
    capture_mode: str = "html_archive",
    raw_path: str = "",
    pdf_path: str = "",
    capture_png_path: str = "",
    use_ollama_kg: bool = False,
    push_lightrag: bool = True,
    rebuild_catalog: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """수집·다운로드·캡쳐된 자료 1건을 C:\\SMC_GRAPHRAG 통합 RAG 저장소(FTS5 + 증분 KG + LightRAG)에 즉시 결합한다."""
    cfg = cfg or get_config()
    docs_dir = cfg.smc_unified_rag_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    text = markdown_text
    if not text and parsed_path and Path(parsed_path).is_file():
        text = Path(parsed_path).read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        text = f"# {title}\n\n- 출처 URL: {url}\n- 출처 ID: {source_id}\n"

    masked_text, _ = mask_pii(text)
    normalized_text = normalize_entities_with_glossary(masked_text, cfg.glossary_path)
    content_hash = sha256_text(normalized_text)

    slug = slugify(title or source_id, 48)
    unified_md_path = docs_dir / f"{source_id}_{slug}.md"
    header_meta = (
        f"---\n"
        f"source_id: \"{source_id}\"\n"
        f"title: \"{title.replace(chr(34), chr(39))}\"\n"
        f"url: \"{url}\"\n"
        f"capture_mode: \"{capture_mode}\"\n"
        f"pdf_path: \"{pdf_path}\"\n"
        f"capture_png_path: \"{capture_png_path}\"\n"
        f"ingested_at: \"{utc_now_iso()}\"\n"
        f"---\n\n"
    )
    unified_md_path.write_text(header_meta + normalized_text, encoding="utf-8")

    # 1) SQLite FTS5 통합 RAG DB 업서트
    chunks = chunk_korean_text(normalized_text, target_chars=1000, overlap_chars=120, default_section=title[:60])
    conn = _init_unified_rag_db(cfg.smc_unified_rag_db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    cur.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
    for idx, ch in enumerate(chunks, 1):
        uid = f"{source_id}_c{idx:03d}"
        sec = ch.get("page_or_section", "본문")
        ctext = ch.get("text", "")
        cur.execute(
            "INSERT OR REPLACE INTO chunks (chunk_uid, source_id, chunk_index, page_or_section, text) VALUES (?, ?, ?, ?, ?)",
            (uid, source_id, idx, sec, ctext),
        )
        cur.execute(
            "INSERT INTO chunks_fts (source_id, title, page_or_section, text) VALUES (?, ?, ?, ?)",
            (source_id, title, sec, ctext),
        )

    # 2) C:\SMC_GRAPHRAG\output\graph_platform_incremental.json 안전 증분 결합
    kg_info = _append_single_source_to_incremental_kg(
        source_id=source_id,
        title=title,
        normalized_text=normalized_text,
        category=provider or source_type or "unified_rag",
        use_ollama=use_ollama_kg,
        cfg=cfg,
    )
    kg_synced = 1

    # 3) LightRAG 서버(127.0.0.1:9621) 온라인 시 자동 푸시
    lr_synced = 0
    if push_lightrag:
        try:
            hr = requests.get(f"{cfg.lightrag_api_url}/health", timeout=2)
            if hr.status_code == 200:
                pr = requests.post(
                    f"{cfg.lightrag_api_url}/documents/text",
                    json={"text": normalized_text[:20000], "file_source": f"{source_id} | {title[:80]}"},
                    timeout=30,
                )
                if pr.status_code in (200, 201, 202):
                    lr_synced = 1
        except Exception:
            lr_synced = 0

    cur.execute(
        """
        INSERT OR REPLACE INTO documents (
            source_id, title, url, source_type, provider, project_id, capture_mode,
            raw_path, pdf_path, capture_png_path, parsed_path, unified_md_path,
            sha256, char_count, chunk_count, kg_synced, lightrag_synced, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            title,
            url,
            source_type,
            provider,
            project_id,
            capture_mode,
            raw_path,
            pdf_path,
            capture_png_path,
            str(parsed_path or ""),
            str(unified_md_path),
            content_hash,
            len(normalized_text),
            len(chunks),
            kg_synced,
            lr_synced,
            utc_now_iso(),
        ),
    )
    conn.commit()
    conn.close()

    if rebuild_catalog:
        try:
            from smc_kg_bridge import build_smc_catalog

            build_smc_catalog(cfg)
        except Exception:
            pass

    manifest = _write_unified_manifest(cfg)
    return {
        "status": "UNIFIED",
        "source_id": source_id,
        "unified_md_path": str(unified_md_path),
        "chunk_count": len(chunks),
        "capture_mode": capture_mode,
        "kg_info": kg_info,
        "lightrag_synced": bool(lr_synced),
        "unified_totals": {
            "documents": manifest["total_documents"],
            "chunks": manifest["total_chunks"],
            "incremental_kg_nodes": manifest["incremental_kg_nodes"],
            "incremental_kg_edges": manifest["incremental_kg_edges"],
        },
    }


def sync_all_existing_sources_to_smc_graphrag(
    *,
    capture_missing_web: bool = False,
    use_ollama_kg: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """E:\\SMC_Report_Platform_Data\\index\\sources.jsonl의 모든 기존 수집 자료를 C:\\SMC_GRAPHRAG 통합 RAG에 일괄 결합한다."""
    cfg = cfg or get_config()
    reg = SourcesRegistry(cfg.sources_registry_path)

    conn = _init_unified_rag_db(cfg.smc_unified_rag_db_path)
    already = {r[0] for r in conn.execute("SELECT source_id FROM documents").fetchall()}
    conn.close()

    synced_now = 0
    skipped = 0
    errors: list[str] = []
    seen: set[str] = set()

    for rec in reg.records:
        sid = rec.get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        if sid in already:
            skipped += 1
            continue
        pp = rec.get("parsed_path") or ""
        if not pp or not Path(pp).is_file():
            continue
        raw_p = str(rec.get("raw_path") or "")
        pdf_p = raw_p if raw_p.lower().endswith(".pdf") and Path(raw_p).is_file() else str(rec.get("pdf_path") or "")
        cap_p = str(rec.get("capture_png_path") or "")
        cap_mode = "pdf_download" if pdf_p else ("web_capture_png" if cap_p else ("html_archive" if raw_p.lower().endswith(".html") else "parsed_markdown"))

        if capture_missing_web and not pdf_p and not cap_p and str(rec.get("url", "")).startswith(("http://", "https://")):
            cap_res = download_or_capture_resource(
                url=rec["url"],
                source_id=sid,
                slug=slugify(rec.get("title", sid), 42),
                download_pdf=True,
                capture_screenshot=True,
                cfg=cfg,
            )
            pdf_p = cap_res.get("pdf_path") or pdf_p
            cap_p = cap_res.get("capture_png_path") or cap_p
            if cap_res.get("capture_mode") != "metadata_only":
                cap_mode = cap_res["capture_mode"]

        try:
            unify_source_to_smc_graphrag(
                source_id=sid,
                title=str(rec.get("title") or sid),
                parsed_path=pp,
                url=str(rec.get("url") or ""),
                source_type=str(rec.get("source_type") or "web"),
                provider=str(rec.get("provider") or rec.get("scholar_category") or ""),
                capture_mode=cap_mode,
                raw_path=raw_p,
                pdf_path=pdf_p,
                capture_png_path=cap_p,
                use_ollama_kg=use_ollama_kg,
                push_lightrag=True,
                rebuild_catalog=False,
                cfg=cfg,
            )
            synced_now += 1
        except Exception as exc:
            errors.append(f"{sid}: {exc}")

    # 전체 완료 후 C:\SMC_GRAPHRAG SQLite 카탈로그 1회 증분 재색인
    try:
        from smc_kg_bridge import build_smc_catalog

        build_smc_catalog(cfg)
    except Exception:
        pass

    manifest = _write_unified_manifest(cfg)
    return {
        "status": "OK",
        "synced_now": synced_now,
        "already_synced": skipped,
        "errors_count": len(errors),
        "errors": errors[:15],
        "manifest": manifest,
    }


def search_unified_smc_rag(
    query: str,
    limit: int = 12,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """C:\\SMC_GRAPHRAG 통합 RAG(FTS5 문서·청크 + 기존 SMC_GRAPHRAG 지식그래프 카탈로그)를 통합 검색한다."""
    cfg = cfg or get_config()
    q = (query or "").strip()
    if not q:
        return {"query": "", "documents": [], "kg_nodes": []}

    # FTS5 안전 쿼리 토큰화
    toks = [t for t in re.findall(r"[가-힣A-Za-z0-9_]{2,}", q)][:8]
    fts_expr = " OR ".join(f'"{t}"' for t in toks) if toks else f'"{q}"'

    conn = _init_unified_rag_db(cfg.smc_unified_rag_db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    docs_out: list[dict[str, Any]] = []
    try:
        rows = cur.execute(
            """
            SELECT f.source_id, f.title, f.page_or_section,
                   snippet(chunks_fts, 3, '【', '】', '...', 24) AS snippet,
                   d.url, d.capture_mode, d.pdf_path, d.capture_png_path, d.unified_md_path, d.ingested_at
            FROM chunks_fts f
            LEFT JOIN documents d ON d.source_id = f.source_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_expr, limit),
        ).fetchall()
        for r in rows:
            docs_out.append(dict(r))
    except Exception:
        # LIKE 폴백
        like_pat = f"%{toks[0] if toks else q}%"
        rows = cur.execute(
            """
            SELECT c.source_id, d.title, c.page_or_section, substr(c.text, 1, 240) AS snippet,
                   d.url, d.capture_mode, d.pdf_path, d.capture_png_path, d.unified_md_path, d.ingested_at
            FROM chunks c
            LEFT JOIN documents d ON d.source_id = c.source_id
            WHERE c.text LIKE ? OR d.title LIKE ?
            LIMIT ?
            """,
            (like_pat, like_pat, limit),
        ).fetchall()
        for r in rows:
            docs_out.append(dict(r))
    conn.close()

    # 기존 C:\SMC_GRAPHRAG 카탈로그 엔티티·관계 검색 병합 (12개 그래프, 48만+ 노드 / 96만+ 관계)
    kg_nodes: list[dict[str, Any]] = []
    kg_relations: list[dict[str, Any]] = []
    try:
        from smc_kg_bridge import _query_smc_catalog

        cat_res = _query_smc_catalog(toks or [q], cfg, limit_per_term=5)
        seen_ents: set[str] = set()
        seen_rels: set[tuple[str, str, str]] = set()
        for hits in cat_res.values():
            if not isinstance(hits, dict):
                continue
            for ent in hits.get("matched_entities") or []:
                ename = str(ent.get("name") or "")
                if ename and ename not in seen_ents:
                    seen_ents.add(ename)
                    kg_nodes.append(ent)
            for rel in hits.get("matched_relations") or []:
                rk = (str(rel.get("source") or ""), str(rel.get("relation") or ""), str(rel.get("target") or ""))
                if rk[0] and rk[2] and rk not in seen_rels:
                    seen_rels.add(rk)
                    kg_relations.append(rel)
    except Exception:
        pass

    return {
        "query": q,
        "unified_rag_dir": str(cfg.smc_unified_rag_dir),
        "documents_count": len(docs_out),
        "documents": docs_out,
        "kg_nodes_count": len(kg_nodes),
        "kg_nodes": kg_nodes[:20],
        "kg_relations_count": len(kg_relations),
        "kg_relations": kg_relations[:24],
    }


# 하위 호환 별칭 (구 코드에서 search_unified_rag 이름으로 호출하는 경우 대응)
search_unified_rag = search_unified_smc_rag


def get_unified_rag_status(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """C:\\SMC_GRAPHRAG 통합 RAG + 다운로드/캡쳐 아카이브 현황을 반환한다."""
    cfg = cfg or get_config()
    manifest = _write_unified_manifest(cfg)
    reg = SourcesRegistry(cfg.sources_registry_path)
    total_registry = len({r.get("source_id") for r in reg.records if r.get("source_id")})
    unsynced = max(0, total_registry - int(manifest.get("total_documents") or 0))
    return {
        **manifest,
        "registry_total_sources": total_registry,
        "unsynced_sources_est": unsynced,
        "chromium_capture_ready": _find_chromium_bin() is not None,
    }
