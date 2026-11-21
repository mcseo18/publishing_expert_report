"""수집된 검색·논문·교재 결과를 C:\\SMC_GRAPHRAG 통합 지식그래프로 구축(증분 병합)하는 빌더.

규칙 준수 (C:\\SMC_GRAPHRAG\\.agents\\rules\\graphrag-append.md):
1. 기존 C:\\SMC_GRAPHRAG\\output\\graph.json 은 절대 덮어쓰지 않는다.
2. 갱신 전 C:\\SMC_GRAPHRAG\\output\\backup\\platform_<YYYYMMDD_HHMMSS>\\ 에 자동 백업한다.
3. 로컬 Ollama(gemma4:latest 또는 gemma4:26b, think=false + JSON Schema)로 엔티티·관계를 추출해
   C:\\SMC_GRAPHRAG\\output\\graph_platform_incremental.json (+ .graphml, triples_platform_incremental.csv)에
   증분 병합(append)한다.
4. 완료 후 E:\\SMC_Report_Platform_Data\\index\\smc_graphrag_catalog.sqlite 를 자동 재색인하고,
   LightRAG 서버(127.0.0.1:9621) 또는 Neo4j가 기동 중이면 함께 동기화한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx
import requests

from compliance import SourcesRegistry, normalize_entities_with_glossary, utc_now_iso
from config import PlatformConfig, get_config
from local_gemma import LocalGemmaClient
from smc_kg_bridge import build_smc_catalog


def _backup_existing(cfg: PlatformConfig) -> str | None:
    targets = [
        cfg.smc_incremental_graph_path,
        cfg.smc_graphrag_output_dir / "graph_platform_incremental.graphml",
        cfg.smc_graphrag_output_dir / "triples_platform_incremental.csv",
    ]
    existing = [p for p in targets if p.is_file()]
    if not existing:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = cfg.smc_graphrag_backup_dir / f"platform_{stamp}"
    bdir.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, bdir / p.name)
    return str(bdir)


def _load_or_init_graph(inc_path: Path) -> nx.MultiDiGraph:
    if inc_path.is_file():
        raw = json.loads(inc_path.read_text(encoding="utf-8"))
        return nx.node_link_graph(raw, edges="edges" if "edges" in raw else "links")
    return nx.MultiDiGraph()


def _load_processed_ids(meta_path: Path) -> set[str]:
    if not meta_path.is_file():
        return set()
    try:
        return set(json.loads(meta_path.read_text(encoding="utf-8")).get("ingested_source_ids", []))
    except Exception:
        return set()


def _save_processed_meta(meta_path: Path, ingested_ids: set[str], stats: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "updated_at": utc_now_iso(),
                "ingested_source_ids": sorted(ingested_ids),
                "stats": stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_knowledge_graph_from_sources(
    source_ids: list[str] | None = None,
    categories: list[str] | None = None,
    model: str | None = None,
    max_chars_per_source: int = 3800,
    force: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    gemma = LocalGemmaClient(cfg)
    target_model = model or cfg.ollama_fast_model  # 100% GPU 고속 구조화 추출 기본 (gemma4:latest)

    reg = SourcesRegistry(cfg.sources_registry_path)
    cur_path = cfg.index_dir / "curation_state.json"
    curation = json.loads(cur_path.read_text(encoding="utf-8")) if cur_path.is_file() else {}

    meta_path = cfg.index_dir / "kg_ingested_sources.json"
    already_ingested = set() if force else _load_processed_ids(meta_path)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rec in reg.records:
        sid = rec.get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        if sid in already_ingested:
            continue
        if rec.get("source_type") == "kg_reuse":
            continue  # 이미 C:\SMC_GRAPHRAG에 존재하는 자산
        cur = curation.get(sid, {})
        cat = cur.get("category") or rec.get("scholar_category") or ""
        if source_ids and sid not in source_ids:
            continue
        if categories and cat not in categories:
            continue
        pp = rec.get("parsed_path")
        if pp and Path(pp).is_file():
            selected.append({"source_id": sid, "title": rec.get("title", sid), "parsed_path": Path(pp), "category": cat})

    inc_path = cfg.smc_incremental_graph_path
    backup_dir = _backup_existing(cfg)
    G = _load_or_init_graph(inc_path)
    before_nodes, before_edges = G.number_of_nodes(), G.number_of_edges()

    processed_now: list[dict[str, Any]] = []
    lightrag_online = False
    try:
        lightrag_online = requests.get(f"{cfg.lightrag_api_url}/health", timeout=3).status_code == 200
    except Exception:
        lightrag_online = False

    for item in selected:
        sid = item["source_id"]
        doc_label = f"{sid} | {item['title'][:80]}"
        raw_text = item["parsed_path"].read_text(encoding="utf-8", errors="ignore")
        norm_text = normalize_entities_with_glossary(raw_text, cfg.glossary_path)
        excerpt = norm_text[:max_chars_per_source]

        try:
            triples = gemma.extract_triples(excerpt, model=target_model)
            ent_added = 0
            rel_added = 0
            valid_names: set[str] = set()
            for ent in triples.get("entities", []):
                name = (ent.get("name") or "").strip()
                etype = (ent.get("type") or "CONCEPT").strip()
                if not name or len(name) > 120:
                    continue
                valid_names.add(name)
                if G.has_node(name):
                    G.nodes[name]["mentions"] = int(G.nodes[name].get("mentions", 1)) + 1
                    srcs = set(str(G.nodes[name].get("source_ids", "")).split(",")) - {""}
                    srcs.add(sid)
                    G.nodes[name]["source_ids"] = ",".join(sorted(srcs))
                else:
                    G.add_node(name, type=etype, mentions=1, source_ids=sid, category=item["category"] or "platform")
                    ent_added += 1

            for rel in triples.get("relations", []):
                s = (rel.get("source") or "").strip()
                r = (rel.get("relation") or "").strip()
                t = (rel.get("target") or "").strip()
                if s in valid_names and t in valid_names and r and s != t:
                    G.add_edge(s, t, relation=r, source_doc=doc_label, source_id=sid)
                    rel_added += 1

            # LightRAG 서버 기동 중이면 동시 증분 적재
            lr_pushed = False
            if lightrag_online:
                try:
                    resp = requests.post(
                        f"{cfg.lightrag_api_url}/documents/text",
                        json={"text": norm_text[:20000], "file_source": doc_label},
                        timeout=60,
                    )
                    lr_pushed = resp.status_code in (200, 201, 202)
                except Exception:
                    lr_pushed = False

            already_ingested.add(sid)
            cur_entry = curation.get(sid, {})
            cur_entry["kg_ingested"] = True
            cur_entry["updated_at"] = utc_now_iso()
            curation[sid] = cur_entry

            processed_now.append(
                {
                    "source_id": sid,
                    "entities_extracted": len(valid_names),
                    "new_nodes": ent_added,
                    "new_edges": rel_added,
                    "lightrag_pushed": lr_pushed,
                }
            )
        except Exception as exc:
            processed_now.append({"source_id": sid, "error": str(exc)})

    # 그래프 저장 (JSON + GraphML + triples CSV)
    inc_path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G, edges="edges")
    inc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # GraphML 저장 (문자열 속성으로 안전 직렬화)
    graphml_path = cfg.smc_graphrag_output_dir / "graph_platform_incremental.graphml"
    nx.write_graphml(G, str(graphml_path))

    # Triples CSV 저장
    csv_path = cfg.smc_graphrag_output_dir / "triples_platform_incremental.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "relation", "target", "source_id", "source_doc"])
        for u, v, d in G.edges(data=True):
            w.writerow([u, d.get("relation", ""), v, d.get("source_id", ""), d.get("source_doc", "")])

    # Curation 상태 및 이력 저장
    cur_path.write_text(json.dumps(curation, ensure_ascii=False, indent=2), encoding="utf-8")

    # Neo4j 기동 시 동기화
    neo4j_synced = False
    try:
        smc_str = str(cfg.smc_graphrag_root)
        if smc_str not in sys.path:
            sys.path.insert(0, smc_str)
        import neo4j_store  # type: ignore

        driver = neo4j_store.get_driver()
        try:
            neo4j_store.save_entity_graph(G, driver)
            neo4j_synced = True
        finally:
            driver.close()
    except Exception:
        neo4j_synced = False

    # C:\SMC_GRAPHRAG 전체 SQLite 카탈로그 증분 재색인
    cat_stats = build_smc_catalog(cfg)

    stats = {
        "model": target_model,
        "backup_dir": backup_dir,
        "graph_path": str(inc_path),
        "graphml_path": str(graphml_path),
        "triples_csv_path": str(csv_path),
        "sources_processed": len(processed_now),
        "nodes_before": before_nodes,
        "nodes_after": G.number_of_nodes(),
        "edges_before": before_edges,
        "edges_after": G.number_of_edges(),
        "neo4j_synced": neo4j_synced,
        "lightrag_server_online": lightrag_online,
        "catalog_total_nodes": cat_stats["total_nodes_indexed"],
        "catalog_total_edges": cat_stats["total_edges_indexed"],
        "details": processed_now,
    }
    _save_processed_meta(meta_path, already_ingested, stats)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="수집된 검색 결과를 C:\\SMC_GRAPHRAG 지식그래프로 증분 구축")
    parser.add_argument("--source-ids", default="", help="특정 source_id 목록 (쉼표 구분, 비우면 미적재 전체)")
    parser.add_argument("--categories", default="", help="특정 category 필터 (예: cn_model,japan_source)")
    parser.add_argument("--model", default=None, help="Ollama 모델 (기본 gemma4:latest 고속 100% GPU)")
    parser.add_argument("--force", action="store_true", help="이미 적재된 source_id도 다시 추출")
    args = parser.parse_args()

    sids = [s.strip() for s in args.source_ids.split(",") if s.strip()] or None
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None
    res = build_knowledge_graph_from_sources(
        source_ids=sids,
        categories=cats,
        model=args.model,
        force=args.force,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
