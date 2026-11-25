"""publishing_DB 통합 데이터 저장소 및 프로젝트별 인터랙티브 지식그래프 빌더.

설계 규약:
- 워크스페이스 루트 `publishing_DB/<project_id>/` 하위에 `projects_v2/<project_id>/`와 동일한
  프로젝트 ID 폴더를 자동 생성하고 다음 6개 하위 폴더를 관리한다:
    ├── captures/          (eco-browser / Chromium 웹페이지 PNG 캡처)
    ├── pdfs/              (다운로드 OA PDF · 사용자 앵커 PDF)
    ├── reference_images/  (크롤링 추출 참고 이미지 · 도표 · CC-BY 그림)
    ├── web_pages/         (eco-browser 크롤링 정제 마크다운 · 원문 HTML)
    ├── knowledge_graph/   (프로젝트 인터랙티브 지식그래프 JSON/GraphML)
    └── evidence/          (근거 패킷 JSON 미러)
- `C:\\SMC_GRAPHRAG` (48만+ 노드 카탈로그 + 통합 RAG)와 연계하여 웹 프론트엔드에서
  인터랙티브 지식그래프를 바로 탐색·시각화할 수 있는 JSON을 생성한다.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from compliance import utc_now_iso
from config import PlatformConfig, get_config

PUBLISHING_DB_SUBDIRS = (
    "captures",
    "pdfs",
    "reference_images",
    "web_pages",
    "knowledge_graph",
    "evidence",
)


def init_publishing_db_project(project_id: str, cfg: PlatformConfig | None = None) -> Path:
    """`publishing_DB/<project_id>/`와 하위 6개 표준 폴더를 초기화한다."""
    cfg = cfg or get_config()
    root = cfg.project_publishing_db_dir(project_id)
    for sub in PUBLISHING_DB_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    manifest_p = root / "db_manifest.json"
    if not manifest_p.is_file():
        manifest_p.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                    "items": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return root


def mirror_file_to_publishing_db(
    *,
    project_id: str,
    category: str,  # captures | pdfs | reference_images | web_pages | evidence | knowledge_graph
    src_path: Path,
    dest_name: str | None = None,
    meta: dict[str, Any] | None = None,
    cfg: PlatformConfig | None = None,
) -> Path | None:
    """수집된 파일(캡처/PDF/참고이미지/웹페이지/근거)을 publishing_DB/<project_id>/<category>/에 미러링한다."""
    cfg = cfg or get_config()
    if not src_path.is_file():
        return None
    if category not in PUBLISHING_DB_SUBDIRS:
        category = "web_pages"
    root = init_publishing_db_project(project_id, cfg)
    dst = root / category / (dest_name or src_path.name)
    try:
        if src_path.resolve() != dst.resolve():
            shutil.copy2(src_path, dst)
    except Exception:
        shutil.copy2(src_path, dst)

    if meta:
        _upsert_db_manifest_item(
            root,
            {
                "category": category,
                "filename": dst.name,
                "rel_url": f"/publishing-db/{project_id}/{category}/{dst.name}",
                "size_bytes": dst.stat().st_size,
                "updated_at": utc_now_iso(),
                **meta,
            },
        )
    return dst


def _upsert_db_manifest_item(root: Path, item: dict[str, Any]) -> None:
    mp = root / "db_manifest.json"
    try:
        data = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else {"project_id": root.name, "items": []}
    except Exception:
        data = {"project_id": root.name, "items": []}
    items = list(data.get("items") or [])
    key = (item.get("category"), item.get("filename"))
    replaced = False
    for idx, cur in enumerate(items):
        if (cur.get("category"), cur.get("filename")) == key:
            items[idx] = {**cur, **item}
            replaced = True
            break
    if not replaced:
        items.append(item)
    data["items"] = items
    data["updated_at"] = utc_now_iso()
    mp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_existing_project_sources_to_publishing_db(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, int]:
    """프로젝트의 근거 패킷·수집 폴더에 저장된 PDF·캡처·정제 문서를 publishing_DB/<project_id>/에 자동 동기화한다."""
    cfg = cfg or get_config()
    root = init_publishing_db_project(project_id, cfg)
    counts = {"captures": 0, "pdfs": 0, "reference_images": 0, "web_pages": 0, "evidence": 0}

    # 1) 근거 패킷 미러링 + 각 출처의 raw/pdf/capture/parsed 파일 동기화
    pkt_candidates = [
        cfg.evidence_dir / f"{project_id}_evidence.json",
        cfg.project_e_evidence_dir(project_id) / f"{project_id}_evidence.json",
    ]
    seen_sids: set[str] = set()
    for pkt_p in pkt_candidates:
        if not pkt_p.is_file():
            continue
        mirror_file_to_publishing_db(project_id=project_id, category="evidence", src_path=pkt_p, cfg=cfg)
        counts["evidence"] += 1
        try:
            pkt = json.loads(pkt_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for src in pkt.get("sources") or []:
            sid = str(src.get("source_id") or "")
            if sid in seen_sids:
                continue
            seen_sids.add(sid)
            title = str(src.get("title") or sid)
            url = str(src.get("url") or "")
            for field, cat in (("parsed_path", "web_pages"), ("raw_path", "pdfs")):
                fp_str = str(src.get(field) or "")
                if not fp_str:
                    continue
                fp = Path(fp_str)
                if not fp.is_file():
                    continue
                if cat == "pdfs" and fp.suffix.lower() != ".pdf":
                    if fp.suffix.lower() in (".html", ".htm", ".md", ".txt"):
                        cat = "web_pages"
                    else:
                        continue
                mirror_file_to_publishing_db(
                    project_id=project_id,
                    category=cat,
                    src_path=fp,
                    meta={"source_id": sid, "title": title, "url": url},
                    cfg=cfg,
                )
                counts[cat] += 1

    # 2) sources.jsonl에서 이 프로젝트의 source_id에 해당하는 capture_png_path / pdf_path 보강
    if seen_sids and cfg.sources_registry_path.is_file():
        for line in cfg.sources_registry_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sid = str(rec.get("source_id") or "")
            if sid not in seen_sids:
                continue
            cap_p = Path(str(rec.get("capture_png_path") or ""))
            if cap_p.is_file():
                mirror_file_to_publishing_db(
                    project_id=project_id,
                    category="captures",
                    src_path=cap_p,
                    meta={"source_id": sid, "title": rec.get("title", sid), "url": rec.get("url", "")},
                    cfg=cfg,
                )
                counts["captures"] += 1
            pdf_p = Path(str(rec.get("pdf_path") or ""))
            if pdf_p.is_file():
                mirror_file_to_publishing_db(
                    project_id=project_id,
                    category="pdfs",
                    src_path=pdf_p,
                    meta={"source_id": sid, "title": rec.get("title", sid), "url": rec.get("url", "")},
                    cfg=cfg,
                )
                counts["pdfs"] += 1
    return counts


def list_publishing_db_assets(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """`publishing_DB/<project_id>/` 내 모든 캡처·PDF·참고이미지·웹페이지·지식그래프 에셋 목록을 반환한다."""
    cfg = cfg or get_config()
    root = init_publishing_db_project(project_id, cfg)
    sync_existing_project_sources_to_publishing_db(project_id, cfg=cfg)

    meta_map: dict[tuple[str, str], dict[str, Any]] = {}
    mp = root / "db_manifest.json"
    if mp.is_file():
        try:
            mdata = json.loads(mp.read_text(encoding="utf-8"))
            for it in mdata.get("items") or []:
                meta_map[(str(it.get("category") or ""), str(it.get("filename") or ""))] = it
        except Exception:
            pass

    assets: dict[str, list[dict[str, Any]]] = {}
    for sub in PUBLISHING_DB_SUBDIRS:
        d = root / sub
        entries: list[dict[str, Any]] = []
        if d.is_dir():
            for fp in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if not fp.is_file() or fp.name.endswith(".tmp"):
                    continue
                extra = meta_map.get((sub, fp.name)) or {}
                entries.append(
                    {
                        "filename": fp.name,
                        "category": sub,
                        "rel_url": f"/publishing-db/{project_id}/{sub}/{fp.name}",
                        "abs_path": str(fp),
                        "size_kb": round(fp.stat().st_size / 1024.0, 1),
                        "ext": fp.suffix.lower(),
                        "source_id": extra.get("source_id", ""),
                        "title": extra.get("title") or fp.stem,
                        "url": extra.get("url", ""),
                        "caption": extra.get("caption", ""),
                    }
                )
        assets[sub] = entries

    return {
        "project_id": project_id,
        "db_root": str(root),
        "counts": {k: len(v) for k, v in assets.items()},
        "assets": assets,
    }


def build_project_knowledge_graph(
    project_id: str,
    *,
    max_nodes: int = 75,
    max_edges: int = 120,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 수집 자료 + C:\\SMC_GRAPHRAG(48만+ 노드 카탈로그)를 통합해 인터랙티브 지식그래프 JSON을 구축한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    root = init_publishing_db_project(project_id, cfg)
    st = load_project_state(project_id, cfg) or {}
    topic_ko = str(st.get("topic_ko") or project_id).strip()
    topic_en = str(st.get("topic_en") or "").strip()
    kws_ko = [str(k).strip() for k in (st.get("keywords_ko") or []) if str(k).strip()]
    kws_en = [str(k).strip() for k in (st.get("keywords_en") or []) if str(k).strip()]

    nodes_map: dict[str, dict[str, Any]] = {}
    edges_list: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def _add_node(nid: str, label: str, group: str, weight: int = 2, meta: dict[str, Any] | None = None) -> str:
        clean_id = re.sub(r"\s+", " ", nid).strip()[:70]
        if not clean_id:
            return ""
        if clean_id not in nodes_map:
            nodes_map[clean_id] = {
                "id": clean_id,
                "label": label[:46],
                "group": group,  # topic | keyword | source | concept | smc_kg
                "weight": weight,
                "meta": meta or {},
            }
        else:
            nodes_map[clean_id]["weight"] = min(20, int(nodes_map[clean_id]["weight"]) + 1)
        return clean_id

    def _add_edge(src: str, tgt: str, relation: str, origin: str = "project") -> None:
        if not src or not tgt or src == tgt:
            return
        k = (src, relation, tgt)
        if k in seen_edges:
            return
        seen_edges.add(k)
        edges_list.append({"source": src, "target": tgt, "relation": relation[:28], "origin": origin})

    # 1) 중심 주제 노드 + 핵심 키워드 노드
    center_id = _add_node(topic_ko, topic_ko, "topic", weight=12, meta={"topic_en": topic_en})
    for kw in kws_ko[:10]:
        kid = _add_node(kw, kw, "keyword", weight=6)
        _add_edge(center_id, kid, "핵심영역", "outline")

    # 2) 프로젝트 근거 패킷 출처 & 추출 개념/사실 연결
    pkt_path = cfg.evidence_dir / f"{project_id}_evidence.json"
    if not pkt_path.is_file():
        pkt_path = root / "evidence" / f"{project_id}_evidence.json"
    project_sids: set[str] = set()
    if pkt_path.is_file():
        try:
            pkt = json.loads(pkt_path.read_text(encoding="utf-8"))
            for src in (pkt.get("sources") or [])[:25]:
                sid = str(src.get("source_id") or "")
                title = str(src.get("title") or sid).strip()
                if not sid:
                    continue
                project_sids.add(sid)
                sn_id = _add_node(sid, f"{sid} · {title[:26]}", "source", weight=5, meta={"title": title, "url": src.get("url", ""), "source_type": src.get("source_type", "web")})
                # 어떤 키워드와 매칭되는지 연결
                hay = f"{title} {src.get('page_or_section', '')}".lower()
                linked_kw = False
                for kw in kws_ko[:10]:
                    if kw.lower() in hay:
                        _add_edge(sn_id, kw, "근거제공", "evidence")
                        linked_kw = True
                if not linked_kw:
                    _add_edge(center_id, sn_id, "참고문헌", "evidence")
                for fct in (src.get("extracted_facts") or [])[:2]:
                    metric = str(fct.get("metric") or "").strip()
                    if metric and len(metric) >= 2:
                        cid_n = _add_node(metric, metric, "concept", weight=4)
                        _add_edge(sn_id, cid_n, "핵심지표", "evidence")
        except Exception:
            pass

    # 3) C:\SMC_GRAPHRAG 48만+ 노드 카탈로그에서 주제·키워드 직접 관련 트리플 병합
    smc_triples_added = 0
    try:
        from agro_framework import query_kg_triples_for_chapter

        probe_title = f"{topic_ko} {' '.join(kws_ko[:5])}"
        probe_text = f"{topic_en} {' '.join(kws_en[:5])}"
        triples = query_kg_triples_for_chapter(
            chapter_title=probe_title,
            chapter_text=probe_text,
            project_source_ids=project_sids or None,
            limit=32,
            cfg=cfg,
        )
        for tr in triples:
            if len(nodes_map) >= max_nodes or len(edges_list) >= max_edges:
                break
            h = str(tr.get("head") or "").strip()
            r = str(tr.get("relation") or "관련").strip()
            t = str(tr.get("tail") or "").strip()
            if not h or not t:
                continue
            hid = _add_node(h, h, "smc_kg", weight=4, meta={"source_doc": tr.get("source_doc", ""), "origin": tr.get("origin", "C:\\SMC_GRAPHRAG")})
            tid = _add_node(t, t, "smc_kg", weight=4, meta={"source_doc": tr.get("source_doc", ""), "origin": tr.get("origin", "C:\\SMC_GRAPHRAG")})
            _add_edge(hid, tid, r, "smc_graphrag")
            # 주제/키워드와 연결고리 형성
            for kw in [topic_ko] + kws_ko[:8]:
                if kw.lower() in h.lower() and hid != kw:
                    _add_edge(kw, hid, "지식연계", "smc_graphrag")
                    break
                if kw.lower() in t.lower() and tid != kw:
                    _add_edge(kw, tid, "지식연계", "smc_graphrag")
                    break
            smc_triples_added += 1
    except Exception:
        pass

    # 4) publishing_DB/<pid>/knowledge_graph/kg_graph.json 저장
    kg_dir = root / "knowledge_graph"
    kg_dir.mkdir(parents=True, exist_ok=True)
    kg_json_p = kg_dir / "kg_graph.json"
    final_nodes = list(nodes_map.values())[:max_nodes]
    final_edges = edges_list[:max_edges]
    graph_payload = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "generated_at": utc_now_iso(),
        "graph_path": str(kg_json_p),
        "stats": {
            "nodes": len(final_nodes),
            "edges": len(final_edges),
            "sources": len(project_sids),
            "smc_kg_triples": smc_triples_added,
            "node_count": len(final_nodes),
            "edge_count": len(final_edges),
            "project_sources": len(project_sids),
            "smc_graphrag_triples": smc_triples_added,
        },
        "nodes": final_nodes,
        "edges": final_edges,
    }
    kg_json_p.write_text(json.dumps(graph_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph_payload


def load_or_build_project_knowledge_graph(project_id: str, *, force_rebuild: bool = False, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    kg_json_p = cfg.project_publishing_db_dir(project_id) / "knowledge_graph" / "kg_graph.json"
    if not force_rebuild and kg_json_p.is_file():
        try:
            data = json.loads(kg_json_p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("nodes"):
                return data
        except Exception:
            pass
    return build_project_knowledge_graph(project_id, cfg=cfg)
