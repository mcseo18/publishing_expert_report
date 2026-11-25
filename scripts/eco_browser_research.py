"""eco-browser 기반 심층 웹 크롤링 · 풀페이지 캡처 · 참고 이미지 수집 · NotebookLM급 근거 Q&A 엔진.

핵심 기능:
1. eco-browser(Playwright Chromium 렌더링 엔진) 기반 웹 크롤링:
   - 공개 웹 URL 또는 검색 키워드로 관련 웹사이트/학술 페이지를 탐색하고 robots.txt 준수 확인
   - 실제 브라우저 렌더링 텍스트 추출 → PII 마스킹 → 정제 마크다운(`publishing_DB/<pid>/web_pages/`)
   - 풀페이지/뷰포트 고해상도 PNG 캡처(`publishing_DB/<pid>/captures/`)
   - 페이지 내 본문 참고 이미지(도표·실사·다이어그램, 최소 240×160px, 광고/아이콘 제외) 자동 추출 저장(`publishing_DB/<pid>/reference_images/`)
   - 페이지 내 공개 PDF 자동 다운로드(`publishing_DB/<pid>/pdfs/`)
   - 수집 즉시 프로젝트 근거 패킷(`[SRC-NN]`), `E:\\`, `C:\\SMC_GRAPHRAG` 통합 RAG, `publishing_DB` 지식그래프에 동시 적재
2. Gemini NotebookLM급 멀티소스 근거 Q&A & 스튜디오 브리핑:
   - 사용자가 선택한 출처(`selected_source_ids`) + `C:\\SMC_GRAPHRAG` 통합 RAG를 기반으로
     정확한 인라인 `[SRC-NN]` 인용이 부착된 답변·브리핑 문서·학습 가이드·FAQ를 즉시 생성
"""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import requests

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

_ECO_JOBS: dict[str, dict[str, Any]] = {}
_ECO_STOPS: dict[str, threading.Event] = {}


def _discover_web_urls_for_query(query: str, max_urls: int = 6) -> list[dict[str, str]]:
    """검색어로 공개 웹 URL과 학술 오픈액세스 랜딩 URL을 안전하게 발굴한다."""
    q = (query or "").strip()
    if not q:
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(url: str, title: str = "", provider: str = "web") -> None:
        u = (url or "").strip()
        if not u.startswith(("http://", "https://")):
            return
        nu = normalize_url(u)
        if nu in seen:
            return
        seen.add(nu)
        found.append({"url": u, "title": title or u, "provider": provider})

    # 1) DuckDuckGo HTML 검색 (무키 공개 웹 URL 발굴)
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": q},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        if r.status_code == 200:
            for m in re.finditer(r'class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', r.text, re.I):
                raw_href = m.group(1)
                title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                if "uddg=" in raw_href:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                    real_u = urllib.parse.unquote((qs.get("uddg") or [""])[0])
                else:
                    real_u = raw_href
                if real_u.startswith(("http://", "https://")) and not any(
                    bad in real_u.lower() for bad in ("duckduckgo.com", "youtube.com", "instagram.com", "facebook.com")
                ):
                    _add(real_u, title, "eco-browser Web")
                    if len(found) >= max_urls:
                        break
    except Exception:
        pass

    # 2) 학술 OA URL 보강 (OpenAlex + Europe PMC)
    if len(found) < max_urls:
        try:
            from fetch_scholar import search_europepmc_papers, search_openalex_papers

            for p in search_openalex_papers(query=q, limit=max_urls, scope="open_access")[:max_urls]:
                u = p.get("pdf_url") or p.get("url") or ""
                if u:
                    _add(u, str(p.get("title") or ""), "OpenAlex OA")
                if len(found) >= max_urls:
                    break
            if len(found) < max_urls:
                for p in search_europepmc_papers(query=q, limit=max_urls, open_access_only=True)[:max_urls]:
                    u = p.get("pdf_url") or p.get("url") or ""
                    if u:
                        _add(u, str(p.get("title") or ""), "Europe PMC OA")
                    if len(found) >= max_urls:
                        break
        except Exception:
            pass

    return found[:max_urls]


def crawl_single_url_with_eco_browser(
    *,
    project_id: str,
    url: str,
    topic: str = "",
    capture_full_page: bool = True,
    extract_ref_images: bool = True,
    max_ref_images: int = 4,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """단일 URL을 eco-browser(Playwright Chromium)로 방문해 텍스트·캡처 PNG·참고 이미지·PDF를 publishing_DB에 저장한다."""
    from publishing_db import init_publishing_db_project, mirror_file_to_publishing_db
    from rag_capture_unifier import download_or_capture_resource, unify_source_to_smc_graphrag

    cfg = cfg or get_config()
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        raise ValueError(f"올바른 http(s) URL이 아닙니다: {u}")

    allowed, robots_status = check_robots_txt(u)
    if not allowed:
        return {"status": "BLOCKED_BY_ROBOTS", "url": u, "robots_status": robots_status}

    pdb_root = init_publishing_db_project(project_id, cfg)
    reg = SourcesRegistry(cfg.sources_registry_path)
    sid = reg.next_source_id()
    parsed_u = urllib.parse.urlparse(u)
    base_slug = slugify(parsed_u.netloc + "_" + parsed_u.path.strip("/"), 42)

    title = ""
    raw_html = ""
    body_text = ""
    cap_png_path: Path | None = None
    ref_images_saved: list[dict[str, Any]] = []
    pdf_links: list[str] = []

    is_direct_pdf = parsed_u.path.lower().endswith(".pdf")

    # 1) eco-browser (Playwright Chromium) 렌더링 · 텍스트 추출 · 풀페이지 캡처 · 참고 이미지 추출
    if not is_direct_pdf:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1366, "height": 900},
                    user_agent=USER_AGENT,
                    locale="ko-KR",
                )
                page = context.new_page()
                page.goto(u, wait_until="domcontentloaded", timeout=22000)
                page.wait_for_timeout(1400)

                title = (page.title() or "").strip()
                raw_html = page.content() or ""
                # 불필요 네비게이션/스크립트 제거 후 본문 텍스트 추출
                body_text = page.evaluate(
                    """() => {
                        const clone = document.body ? document.body.cloneNode(true) : null;
                        if (!clone) return '';
                        clone.querySelectorAll('script,style,noscript,iframe,nav,footer,header,aside').forEach(el => el.remove());
                        return (clone.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim();
                    }"""
                ) or ""

                # 풀페이지/뷰포트 PNG 캡처 → publishing_DB/<pid>/captures/ + E:\raw\captures\
                cap_name = f"{sid}_{base_slug}.png"
                cap_dst = pdb_root / "captures" / cap_name
                page.screenshot(path=str(cap_dst), full_page=capture_full_page)
                if cap_dst.is_file() and cap_dst.stat().st_size > 1500:
                    cap_png_path = cap_dst
                    cfg.raw_captures_dir.mkdir(parents=True, exist_ok=True)
                    (cfg.raw_captures_dir / cap_name).write_bytes(cap_dst.read_bytes())

                # PDF 링크 탐색
                pdf_links = page.evaluate(
                    """() => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h && h.toLowerCase().split('?')[0].endsWith('.pdf'))
                        .slice(0, 3)"""
                ) or []

                # 본문 참고 이미지(도표·실사·다이어그램) 추출 → publishing_DB/<pid>/reference_images/
                if extract_ref_images and max_ref_images > 0:
                    img_cands = page.evaluate(
                        """() => {
                            const out = [];
                            for (const img of document.querySelectorAll('img')) {
                                const r = img.getBoundingClientRect();
                                const w = Math.max(img.naturalWidth || 0, Math.round(r.width || 0));
                                const h = Math.max(img.naturalHeight || 0, Math.round(r.height || 0));
                                const src = img.currentSrc || img.src || '';
                                if (!src.startsWith('http')) continue;
                                if (w < 240 || h < 160) continue;
                                if (/logo|icon|avatar|banner|sprite|pixel|ad/i.test(src + ' ' + (img.alt || ''))) continue;
                                const fig = img.closest('figure');
                                const cap = fig ? (fig.innerText || '').trim().slice(0, 180) : (img.alt || '').trim().slice(0, 180);
                                out.push({ src, alt: (img.alt || '').trim(), caption: cap, w, h });
                                if (out.length >= 10) break;
                            }
                            return out;
                        }"""
                    ) or []
                    for i_idx, ic in enumerate(img_cands[:max_ref_images], 1):
                        try:
                            ir = requests.get(ic["src"], headers={"User-Agent": USER_AGENT, "Referer": u}, timeout=10)
                            ctype = (ir.headers.get("content-type") or "").lower()
                            if ir.status_code == 200 and "image" in ctype and len(ir.content) > 6000:
                                ext = ".png" if "png" in ctype else (".webp" if "webp" in ctype else ".jpg")
                                ref_name = f"{sid}_ref{i_idx:02d}{ext}"
                                ref_p = pdb_root / "reference_images" / ref_name
                                ref_p.write_bytes(ir.content)
                                mirror_file_to_publishing_db(
                                    project_id=project_id,
                                    category="reference_images",
                                    src_path=ref_p,
                                    meta={
                                        "source_id": sid,
                                        "title": ic.get("alt") or f"{title[:40]} 참고이미지 {i_idx}",
                                        "caption": ic.get("caption") or ic.get("alt") or "",
                                        "url": ic["src"],
                                        "page_url": u,
                                    },
                                    cfg=cfg,
                                )
                                ref_images_saved.append(
                                    {
                                        "filename": ref_name,
                                        "rel_url": f"/publishing-db/{project_id}/reference_images/{ref_name}",
                                        "caption": ic.get("caption") or ic.get("alt") or "",
                                    }
                                )
                        except Exception:
                            continue

                browser.close()
        except Exception:
            # Playwright 실패 시 경량 requests 폴백
            try:
                from fetch_clean import _fetch_with_requests

                title, raw_html, body_text, _ = _fetch_with_requests(u, timeout=20)
            except Exception as exc:
                return {"status": "ERROR", "url": u, "error": str(exc)[:180]}

    # 2) 공개 PDF 다운로드 및 텍스트 병합
    pdf_saved_path = ""
    cap_res = download_or_capture_resource(
        url=u,
        pdf_url=(pdf_links[0] if pdf_links else (u if is_direct_pdf else "")),
        html_text=raw_html,
        source_id=sid,
        slug=base_slug,
        download_pdf=True,
        capture_screenshot=False,
        cfg=cfg,
    )
    if cap_res.get("pdf_path") and Path(cap_res["pdf_path"]).is_file():
        pdf_p = Path(cap_res["pdf_path"])
        pdf_saved_path = str(pdf_p)
        mirror_file_to_publishing_db(
            project_id=project_id,
            category="pdfs",
            src_path=pdf_p,
            meta={"source_id": sid, "title": title or pdf_p.stem, "url": u},
            cfg=cfg,
        )
        if cap_res.get("pdf_text"):
            body_text = (body_text + "\n\n## 다운로드 PDF 원문\n\n" + cap_res["pdf_text"]).strip()

    if not title:
        title = parsed_u.netloc + parsed_u.path
    raw_md = f"# {title}\n\n- **수집 엔진**: eco-browser (Chromium 렌더링·캡처)\n- **URL**: {u}\n- **수집 시각**: {utc_now_iso()}\n\n{body_text[:28000]}"
    cleaned_md, pii_count = mask_pii(raw_md)
    inj_warns = detect_prompt_injection(cleaned_md)
    content_hash = sha256_text(cleaned_md)

    # 3) 정제 마크다운 저장 (E:\parsed + publishing_DB/<pid>/web_pages/)
    parsed_md_path = cfg.parsed_dir / f"{sid}_{base_slug}.md"
    parsed_md_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_md_path.write_text(cleaned_md, encoding="utf-8")
    mirror_file_to_publishing_db(
        project_id=project_id,
        category="web_pages",
        src_path=parsed_md_path,
        meta={"source_id": sid, "title": title, "url": u},
        cfg=cfg,
    )
    if cap_png_path and cap_png_path.is_file():
        mirror_file_to_publishing_db(
            project_id=project_id,
            category="captures",
            src_path=cap_png_path,
            meta={"source_id": sid, "title": title, "url": u},
            cfg=cfg,
        )

    chunks = chunk_korean_text(cleaned_md, default_section="eco-browser 웹 본문")
    now = utc_now_iso()
    source_item = {
        "source_id": sid,
        "source_type": "pdf" if pdf_saved_path else "web",
        "url": u,
        "title": title,
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": robots_status,
        "license_note": "eco-browser 공개 웹 크롤링·캡처 - 변환적 분석 및 정식 인용",
        "page_or_section": "eco-browser 웹 본문",
        "raw_path": pdf_saved_path or str(parsed_md_path),
        "parsed_path": str(parsed_md_path),
        "capture_png_path": str(cap_png_path) if cap_png_path else "",
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": inj_warns,
        "sha256": content_hash,
        "extracted_facts": [],
        "tables": [],
        "chunks": chunks,
    }

    # 프로젝트 마스터 패킷 + publishing_DB/evidence 동시 등록
    packet_id = f"{project_id}_evidence"
    for pkt_p in (
        cfg.evidence_dir / f"{packet_id}.json",
        cfg.project_e_evidence_dir(project_id) / f"{packet_id}.json",
        pdb_root / "evidence" / f"{packet_id}.json",
    ):
        upsert_evidence_packet(
            packet_path=pkt_p,
            source_item=source_item,
            packet_id=packet_id,
            topic=topic or title,
            storage_root=str(cfg.collected_data_root),
            kg_store_root=str(cfg.smc_graphrag_root),
            schema_path=cfg.evidence_schema_path,
        )

    reg.append(
        {
            "source_id": sid,
            "source_type": source_item["source_type"],
            "provider": "eco-browser",
            "url": u,
            "normalized_url": normalize_url(u),
            "title": title,
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": robots_status,
            "sha256": content_hash,
            "raw_path": source_item["raw_path"],
            "pdf_path": pdf_saved_path,
            "capture_png_path": str(cap_png_path) if cap_png_path else "",
            "capture_mode": "eco_browser_capture" if cap_png_path else "eco_browser_text",
            "parsed_path": str(parsed_md_path),
            "packet_path": str(cfg.evidence_dir / f"{packet_id}.json"),
            "chunk_count": len(chunks),
        }
    )

    # C:\SMC_GRAPHRAG 통합 RAG 증분 결합
    try:
        unify_source_to_smc_graphrag(
            source_id=sid,
            title=title,
            markdown_text=cleaned_md,
            parsed_path=parsed_md_path,
            url=u,
            source_type=source_item["source_type"],
            provider="eco-browser",
            capture_mode="eco_browser_capture" if cap_png_path else "eco_browser_text",
            raw_path=source_item["raw_path"],
            pdf_path=pdf_saved_path,
            capture_png_path=str(cap_png_path) if cap_png_path else "",
            cfg=cfg,
        )
    except Exception:
        pass

    return {
        "status": "OK",
        "source_id": sid,
        "title": title,
        "url": u,
        "chars": len(cleaned_md),
        "chunks": len(chunks),
        "capture_url": f"/publishing-db/{project_id}/captures/{cap_png_path.name}" if cap_png_path else "",
        "pdf_downloaded": bool(pdf_saved_path),
        "reference_images": ref_images_saved,
    }


def start_eco_browser_crawl_async(
    *,
    project_id: str,
    query: str = "",
    urls: list[str] | None = None,
    max_pages: int = 5,
    capture_full_page: bool = True,
    extract_ref_images: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """키워드 검색 또는 직접 입력 URL을 백그라운드 eco-browser 워커로 크롤링·캡처·DB 저장한다."""
    from publishing_db import build_project_knowledge_graph
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    cfg = cfg or get_config()
    cur = _ECO_JOBS.get(project_id)
    if cur and cur.get("running"):
        return {"status": "ALREADY_RUNNING", "job": cur}

    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    target_urls: list[dict[str, str]] = []
    for raw_u in (urls or []):
        u = str(raw_u).strip()
        if u.startswith(("http://", "https://")):
            target_urls.append({"url": u, "title": u, "provider": "직접 URL"})
    if query.strip():
        target_urls.extend(_discover_web_urls_for_query(query.strip(), max_urls=max_pages))

    # 중복 제거
    dedup: list[dict[str, str]] = []
    seen_u: set[str] = set()
    for item in target_urls:
        nu = normalize_url(item["url"])
        if nu not in seen_u:
            seen_u.add(nu)
            dedup.append(item)
    dedup = dedup[: max(1, min(15, int(max_pages)))]
    if not dedup:
        raise ValueError("탐색된 URL이 없습니다. 검색어 또는 https:// URL을 입력해 주세요.")

    stop_ev = _ECO_STOPS.setdefault(project_id, threading.Event())
    stop_ev.clear()
    job = {
        "running": True,
        "query": query,
        "total": len(dedup),
        "processed": 0,
        "succeeded": 0,
        "captures": 0,
        "pdfs": 0,
        "ref_images": 0,
        "current_url": "",
        "message": f"eco-browser 크롤링 시작 ({len(dedup)}개 페이지)...",
        "results": [],
    }
    _ECO_JOBS[project_id] = job

    def _worker() -> None:
        try:
            for idx, item in enumerate(dedup, 1):
                if stop_ev.is_set():
                    job["message"] = f"사용자 중단 ({job['succeeded']}/{len(dedup)}건 완료)"
                    break
                job["current_url"] = item["url"]
                job["message"] = f"[{idx}/{len(dedup)}] eco-browser 방문·캡처 중: {item['title'][:50]}"
                try:
                    res = crawl_single_url_with_eco_browser(
                        project_id=project_id,
                        url=item["url"],
                        topic=st.get("topic_ko", ""),
                        capture_full_page=capture_full_page,
                        extract_ref_images=extract_ref_images,
                        cfg=cfg,
                    )
                    job["results"].append(res)
                    if res.get("status") == "OK":
                        job["succeeded"] += 1
                        if res.get("capture_url"):
                            job["captures"] += 1
                        if res.get("pdf_downloaded"):
                            job["pdfs"] += 1
                        job["ref_images"] += len(res.get("reference_images") or [])
                        # 프로젝트 상태 collected_sources에도 즉시 추가
                        st_live = load_project_state(project_id, cfg)
                        if st_live:
                            cols = list(st_live.get("collected_sources") or [])
                            if not any(c.get("source_id") == res["source_id"] for c in cols):
                                cols.append(
                                    {
                                        "source_id": res["source_id"],
                                        "title": res["title"],
                                        "url": res["url"],
                                        "provider": "eco-browser",
                                        "tier_folder": "01_domestic_agencies",
                                        "capture_url": res.get("capture_url", ""),
                                    }
                                )
                                st_live["collected_sources"] = cols
                                save_project_state(st_live, cfg)
                except Exception as exc:
                    job["results"].append({"status": "ERROR", "url": item["url"], "error": str(exc)[:140]})
                job["processed"] = idx

            # 크롤링 완료 후 publishing_DB 지식그래프 자동 갱신
            if job["succeeded"] > 0:
                job["message"] = "publishing_DB 지식그래프 자동 구축 중..."
                try:
                    build_project_knowledge_graph(project_id, cfg=cfg)
                except Exception:
                    pass
                append_event(
                    project_id,
                    "web-scout",
                    "stage2_source_collect",
                    f"eco-browser 크롤링 완료: {job['succeeded']}건 수집 · 캡처 {job['captures']}장 · 참고이미지 {job['ref_images']}장 · PDF {job['pdfs']}건 → publishing_DB 저장",
                    cfg=cfg,
                )
            if not stop_ev.is_set():
                job["message"] = f"완료: {job['succeeded']}건 수집 · 캡처 {job['captures']}장 · 참고이미지 {job['ref_images']}장 · PDF {job['pdfs']}건"
        finally:
            job["running"] = False
            job["current_url"] = ""

    threading.Thread(target=_worker, daemon=True, name=f"eco-crawl-{project_id}").start()
    return {"status": "STARTED", "job": job}


def get_eco_crawl_status(project_id: str) -> dict[str, Any]:
    return {"job": _ECO_JOBS.get(project_id)}


def notebook_ask_sources(
    *,
    project_id: str,
    question: str,
    selected_source_ids: list[str] | None = None,
    include_smc_graphrag: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """NotebookLM급 멀티소스 근거 Q&A: 선택된 프로젝트 출처 + C:\\SMC_GRAPHRAG를 근거로 [SRC-NN] 인용 답변 생성."""
    from agro_framework import format_triples_for_prompt, query_kg_triples_for_chapter
    from local_gemma import LocalGemmaClient
    from subagent_orchestrator import build_subsection_evidence_checked, load_project_state

    cfg = cfg or get_config()
    q = (question or "").strip()
    if not q:
        raise ValueError("질문을 입력해 주세요.")

    st = load_project_state(project_id, cfg) or {}
    pkt_p = cfg.evidence_dir / f"{project_id}_evidence.json"
    if not pkt_p.is_file():
        pkt_p = cfg.project_publishing_db_dir(project_id) / "evidence" / f"{project_id}_evidence.json"
    all_sources: list[dict[str, Any]] = []
    if pkt_p.is_file():
        try:
            all_sources = json.loads(pkt_p.read_text(encoding="utf-8")).get("sources") or []
        except Exception:
            all_sources = []

    if selected_source_ids:
        sel_set = set(selected_source_ids)
        target_sources = [s for s in all_sources if s.get("source_id") in sel_set]
    else:
        target_sources = all_sources

    ev = build_subsection_evidence_checked(
        target_sources,
        f"{st.get('topic_ko', '')} {q}",
        cfg,
        max_chunks=12,
        max_chars_per_chunk=780,
        min_relevant_score=1,
    )
    kg_triples = (
        query_kg_triples_for_chapter(
            chapter_title=f"{st.get('topic_ko', '')} {q}",
            chapter_text=q,
            project_source_ids={str(s.get("source_id")) for s in target_sources if s.get("source_id")},
            limit=10,
            cfg=cfg,
        )
        if include_smc_graphrag
        else []
    )
    kg_block = format_triples_for_prompt(kg_triples, max_items=8)

    sys_prompt = (
        "당신은 Google NotebookLM 수준의 전문 학술 리서치 어시스턴트입니다. "
        "반드시 제공된 근거 자료와 로컬 지식그래프(C:\\SMC_GRAPHRAG) 내용에 기반해 한국어로 명료하고 구조적으로 답변하십시오. "
        "모든 핵심 사실·수치 뒤에는 반드시 제공된 출처키([SRC-NN])를 정확히 표기하고, 근거가 없는 내용은 추측하지 말고 명시하십시오."
    )
    user_prompt = (
        f"프로젝트 주제: {st.get('topic_ko', project_id)}\n"
        f"사용자 질문: {q}\n\n"
        + (f"{kg_block}\n\n" if kg_block else "")
        + f"[선택된 근거 자료 ({len(target_sources)}개 출처 중 핵심 발췌)]\n{ev['text'] or '(수집된 프로젝트 출처가 아직 없습니다. 위 로컬 지식그래프 참고 범위 내에서만 안내하세요.)'}\n\n"
        "위 자료를 바탕으로 ① 핵심 요약, ② 상세 근거 분석(표·수치 포함), ③ 후속 탐구 제안을 정리해 주세요."
    )

    answer = ""
    model_used = cfg.ollama_llm_model
    try:
        client = LocalGemmaClient(cfg)
        answer = client.draft_text(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            model=cfg.ollama_llm_model,
            think=False,
            num_predict=2048,
            timeout=150,
        )
    except Exception as exc:
        answer = f"⚠️ 로컬 LLM 응답 지연으로 근거 발췌 요약으로 대체합니다 ({str(exc)[:80]}).\n\n{ev['text'][:2400]}\n\n{kg_block}"
        model_used = "evidence_fallback"

    used_sids = ev.get("used_ids") or []
    src_by_id = {str(s.get("source_id")): s for s in all_sources}
    citations = [
        {"source_id": sid, "title": src_by_id[sid].get("title", sid), "url": src_by_id[sid].get("url", "")}
        for sid in used_sids
        if sid in src_by_id
    ]
    return {
        "question": q,
        "answer_md": answer,
        "model": model_used,
        "citations": citations,
        "kg_triples_count": len(kg_triples),
        "kg_triples": kg_triples[:8],
    }


def notebook_generate_brief(
    *,
    project_id: str,
    mode: str = "briefing",  # briefing | study_guide | faq
    selected_source_ids: list[str] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """NotebookLM 스튜디오 카드: 브리핑 문서 · 학습 가이드 · FAQ/오해 정리를 원클릭 생성한다."""
    prompts = {
        "briefing": "수집된 모든 출처를 종합해 경영진/연구책임자용 1페이지 핵심 브리핑 문서(핵심 발견 5가지, 정량 지표 비교표, 전략적 시사점)를 작성해 주세요.",
        "study_guide": "전공 학생·실무자를 위한 학습 가이드(핵심 용어 정의표 8선, 핵심 원리·인과 사슬 요약, 자가 점검 질문 5문항)를 작성해 주세요.",
        "faq": "현장·연구에서 가장 자주 묻는 핵심 질문(FAQ) 6개와 흔한 오해 vs 과학적 진실 3선을 출처 인용과 함께 정리해 주세요.",
    }
    q = prompts.get(mode, prompts["briefing"])
    res = notebook_ask_sources(
        project_id=project_id,
        question=q,
        selected_source_ids=selected_source_ids,
        include_smc_graphrag=True,
        cfg=cfg,
    )
    res["mode"] = mode
    return res
