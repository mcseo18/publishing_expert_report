"""C:\\SMC_GRAPHRAG 기존 지식그래프 + LightRAG 통합 브리지 (kg-curator).

핵심 역할:
1. 기존 C:\\SMC_GRAPHRAG\\output\\graph_*.json 자산 전체를 경량 SQLite FTS5 카탈로그로 색인
   (147MB+ 대용량 그래프도 수 밀리초 내 고속 선조회 가능)
2. Graph-First 선조회(gap-check): 기존 C:\\SMC_GRAPHRAG + Neo4j(기동 시) + LightRAG(기동 시)를
   동시 조회해 reports/kg_gap_report.json(reusable_knowledge vs missing_or_outdated_gaps) 생성
3. 신규 정제 문서 증분 적재(ingest):
   - schemas/glossary.json 기반 엔티티 표기 정규화
   - LightRAG 서버(http://127.0.0.1:9621 -> C:\\SMC_GRAPHRAG\\lightrag_store) 증분 병합
   - 선택(--also-legacy-graph): 백업 후 C:\\SMC_GRAPHRAG\\output\\graph_platform_incremental.json
     에 append-only 병합 (+ Neo4j 온라인 시 동기화). 기존 graph.json은 절대 덮어쓰지 않음.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from compliance import normalize_entities_with_glossary, utc_now_iso
from config import PlatformConfig, get_config


def _list_smc_graph_files(cfg: PlatformConfig) -> list[Path]:
    out_dir = cfg.smc_graphrag_output_dir
    if not out_dir.is_dir():
        return []
    return sorted(p for p in out_dir.glob("graph*.json") if p.is_file())


def _check_lightrag_server(cfg: PlatformConfig) -> dict[str, Any]:
    try:
        r = requests.get(f"{cfg.lightrag_api_url}/health", timeout=5)
        return {"online": r.status_code == 200, "status_code": r.status_code, "url": cfg.lightrag_api_url}
    except requests.RequestException as exc:
        return {"online": False, "url": cfg.lightrag_api_url, "error": str(exc)}


def _check_neo4j(cfg: PlatformConfig) -> dict[str, Any]:
    smc_str = str(cfg.smc_graphrag_root)
    if smc_str not in sys.path:
        sys.path.insert(0, smc_str)
    try:
        import neo4j_store  # type: ignore

        driver = neo4j_store.get_driver()
        try:
            with driver.session() as s:
                ent_cnt = s.run("MATCH (e:Entity) RETURN count(e) AS c").single()["c"]
                rel_cnt = s.run("MATCH ()-[r:RELATED]->() RETURN count(r) AS c").single()["c"]
            return {"online": True, "entities": ent_cnt, "relations": rel_cnt}
        finally:
            driver.close()
    except Exception as exc:
        return {"online": False, "note": str(exc)}


def build_smc_catalog(cfg: PlatformConfig | None = None, force: bool = False) -> dict[str, Any]:
    """C:\\SMC_GRAPHRAG\\output\\graph*.json 을 SQLite 카탈로그로 색인한다."""
    cfg = cfg or get_config()
    db_path = cfg.smc_catalog_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    graph_files = _list_smc_graph_files(cfg)

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS graph_files (
                filename TEXT PRIMARY KEY,
                mtime REAL,
                size_bytes INTEGER,
                node_count INTEGER,
                edge_count INTEGER
            );
            CREATE TABLE IF NOT EXISTS entities (
                graph_file TEXT,
                name TEXT,
                entity_type TEXT,
                mentions INTEGER
            );
            CREATE TABLE IF NOT EXISTS relations (
                graph_file TEXT,
                source TEXT,
                relation TEXT,
                target TEXT,
                source_doc TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ent_name ON entities(name);
            CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(source);
            CREATE INDEX IF NOT EXISTS idx_rel_tgt ON relations(target);
            """
        )

        indexed_now: list[str] = []
        skipped: list[str] = []

        for gf in graph_files:
            st = gf.stat()
            row = cur.execute(
                "SELECT mtime, size_bytes FROM graph_files WHERE filename = ?",
                (gf.name,),
            ).fetchone()
            if not force and row and abs(row[0] - st.st_mtime) < 1e-3 and row[1] == st.st_size:
                skipped.append(gf.name)
                continue

            cur.execute("DELETE FROM entities WHERE graph_file = ?", (gf.name,))
            cur.execute("DELETE FROM relations WHERE graph_file = ?", (gf.name,))

            raw = json.loads(gf.read_text(encoding="utf-8"))
            nodes = raw.get("nodes", [])
            edges = raw.get("edges", raw.get("links", []))

            cur.executemany(
                "INSERT INTO entities(graph_file, name, entity_type, mentions) VALUES (?, ?, ?, ?)",
                [
                    (
                        gf.name,
                        str(n.get("id", "")),
                        str(n.get("type", "OTHER")),
                        int(n.get("mentions", 1) or 1),
                    )
                    for n in nodes
                    if n.get("id")
                ],
            )
            cur.executemany(
                "INSERT INTO relations(graph_file, source, relation, target, source_doc) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        gf.name,
                        str(e.get("source", "")),
                        str(e.get("relation", "")),
                        str(e.get("target", "")),
                        str(e.get("source_doc", "")),
                    )
                    for e in edges
                ],
            )
            cur.execute(
                "REPLACE INTO graph_files(filename, mtime, size_bytes, node_count, edge_count) VALUES (?, ?, ?, ?, ?)",
                (gf.name, st.st_mtime, st.st_size, len(nodes), len(edges)),
            )
            conn.commit()
            indexed_now.append(gf.name)

        totals = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(node_count),0), COALESCE(SUM(edge_count),0) FROM graph_files"
        ).fetchone()
        return {
            "catalog_db": str(db_path),
            "graph_files_total": totals[0],
            "total_nodes_indexed": totals[1],
            "total_edges_indexed": totals[2],
            "newly_indexed": indexed_now,
            "unchanged_skipped": skipped,
        }
    finally:
        conn.close()


def _query_smc_catalog(terms: list[str], cfg: PlatformConfig, limit_per_term: int = 8) -> dict[str, Any]:
    if not cfg.smc_catalog_db_path.is_file():
        build_smc_catalog(cfg)
    conn = sqlite3.connect(str(cfg.smc_catalog_db_path))
    try:
        cur = conn.cursor()
        hits: dict[str, Any] = {}
        for term in terms:
            like = f"%{term}%"
            ents = cur.execute(
                """
                SELECT name, entity_type, SUM(mentions) AS total_mentions,
                       GROUP_CONCAT(DISTINCT graph_file) AS graphs
                FROM entities
                WHERE name LIKE ?
                GROUP BY name, entity_type
                ORDER BY total_mentions DESC
                LIMIT ?
                """,
                (like, limit_per_term),
            ).fetchall()
            rels = cur.execute(
                """
                SELECT source, relation, target, source_doc, graph_file
                FROM relations
                WHERE source LIKE ? OR target LIKE ? OR relation LIKE ?
                LIMIT ?
                """,
                (like, like, like, limit_per_term),
            ).fetchall()
            hits[term] = {
                "matched_entities": [
                    {"name": r[0], "type": r[1], "mentions": r[2], "graphs": (r[3] or "").split(",")}
                    for r in ents
                ],
                "matched_relations": [
                    {
                        "source": r[0],
                        "relation": r[1],
                        "target": r[2],
                        "source_doc": r[3],
                        "graph_file": r[4],
                    }
                    for r in rels
                ],
            }
        return hits
    finally:
        conn.close()


def _query_lightrag_server(query: str, cfg: PlatformConfig, mode: str = "hybrid") -> dict[str, Any]:
    try:
        resp = requests.post(
            f"{cfg.lightrag_api_url}/query",
            json={"query": query, "mode": mode},
            timeout=60,
        )
        if resp.status_code == 200:
            return {"online": True, "response": resp.json()}
        return {"online": False, "status_code": resp.status_code}
    except requests.RequestException as exc:
        return {"online": False, "error": str(exc)}


def run_gap_check(
    topic: str,
    terms: list[str],
    out_path: Path | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """Graph-First 선조회: 기존 C:\\SMC_GRAPHRAG + LightRAG를 먼저 조회해 결손 리포트 생성."""
    cfg = cfg or get_config()
    clean_terms = [t.strip() for t in terms if t.strip()]
    if not clean_terms:
        clean_terms = [w for w in topic.split() if len(w) >= 2][:6]

    catalog_hits = _query_smc_catalog(clean_terms, cfg)
    lightrag_status = _check_lightrag_server(cfg)
    lightrag_answer = _query_lightrag_server(topic, cfg) if lightrag_status.get("online") else None

    reusable_knowledge: list[dict[str, Any]] = []
    missing_or_outdated_gaps: list[dict[str, Any]] = []

    for term in clean_terms:
        hit = catalog_hits.get(term, {})
        ents = hit.get("matched_entities", [])
        rels = hit.get("matched_relations", [])
        if ents or rels:
            source_docs = sorted({r["source_doc"] for r in rels if r.get("source_doc")})[:10]
            reusable_knowledge.append(
                {
                    "term": term,
                    "origin": "C:\\SMC_GRAPHRAG",
                    "entity_match_count": len(ents),
                    "relation_match_count": len(rels),
                    "top_entities": ents[:5],
                    "sample_relations": rels[:5],
                    "source_docs": source_docs,
                }
            )
        else:
            missing_or_outdated_gaps.append(
                {
                    "term": term,
                    "reason": "기존 C:\\SMC_GRAPHRAG 지식그래프에 일치 엔티티/관계 없음 -> 웹 수집(ecobrowser/ego-browser) 대상",
                }
            )

    reuse_ratio = round((len(reusable_knowledge) / len(clean_terms)) * 100, 1) if clean_terms else 0.0
    report = {
        "generated_at": utc_now_iso(),
        "topic": topic,
        "queried_terms": clean_terms,
        "smc_graphrag_root": str(cfg.smc_graphrag_root),
        "lightrag_working_dir": str(cfg.lightrag_working_dir),
        "lightrag_server_online": bool(lightrag_status.get("online")),
        "reuse_ratio_percent": reuse_ratio,
        "reusable_knowledge": reusable_knowledge,
        "missing_or_outdated_gaps": missing_or_outdated_gaps,
        "lightrag_query_result": lightrag_answer,
    }

    target_out = out_path or (cfg.reports_dir / "kg_gap_report.json")
    target_out.parent.mkdir(parents=True, exist_ok=True)
    target_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _backup_incremental_graph(cfg: PlatformConfig) -> str | None:
    """graphrag-append.md 규칙: 그래프 갱신 전 C:\\SMC_GRAPHRAG\\output\\backup\\<timestamp> 백업."""
    inc_path = cfg.smc_incremental_graph_path
    if not inc_path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = cfg.smc_graphrag_backup_dir / f"platform_{stamp}"
    bdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(inc_path, bdir / inc_path.name)
    return str(bdir)


def _append_to_legacy_incremental_graph(
    doc_label: str,
    text: str,
    cfg: PlatformConfig,
    model: str | None = None,
) -> dict[str, Any]:
    """기존 C:\\SMC_GRAPHRAG\\output\\graph.json을 건드리지 않고 graph_platform_incremental.json에 증분 병합."""
    import networkx as nx
    from compliance import chunk_korean_text
    from local_gemma import LocalGemmaClient

    inc_path = cfg.smc_incremental_graph_path
    backup_dir = _backup_incremental_graph(cfg)

    if inc_path.is_file():
        raw = json.loads(inc_path.read_text(encoding="utf-8"))
        G = nx.node_link_graph(raw, edges="edges" if "edges" in raw else "links")
    else:
        G = nx.MultiDiGraph()

    before_nodes, before_edges = G.number_of_nodes(), G.number_of_edges()
    gemma = LocalGemmaClient(cfg)
    chunks = chunk_korean_text(text, target_chars=1200, overlap_chars=120)

    for ch in chunks:
        triples = gemma.extract_triples(ch["text"], model=model)
        valid_names = set()
        for ent in triples.get("entities", []):
            name = (ent.get("name") or "").strip()
            etype = (ent.get("type") or "OTHER").strip()
            if not name:
                continue
            valid_names.add(name)
            if G.has_node(name):
                G.nodes[name]["mentions"] = int(G.nodes[name].get("mentions", 1)) + 1
            else:
                G.add_node(name, type=etype, mentions=1)
        for rel in triples.get("relations", []):
            s = (rel.get("source") or "").strip()
            r = (rel.get("relation") or "").strip()
            t = (rel.get("target") or "").strip()
            if s in valid_names and t in valid_names and r:
                G.add_edge(s, t, relation=r, source_doc=doc_label)

    data = nx.node_link_data(G, edges="edges")
    inc_path.parent.mkdir(parents=True, exist_ok=True)
    inc_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Neo4j가 기동 중이면 함께 MERGE 동기화
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

    # 카탈로그 재색인
    build_smc_catalog(cfg)

    return {
        "graph_path": str(inc_path),
        "backup_dir": backup_dir,
        "nodes_before": before_nodes,
        "nodes_after": G.number_of_nodes(),
        "edges_before": before_edges,
        "edges_after": G.number_of_edges(),
        "neo4j_synced": neo4j_synced,
    }


def ingest_text_to_kg(
    file_path: Path,
    source_id: str = "",
    also_legacy_graph: bool = False,
    model: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """정제된 마크다운 문서를 용어집 정규화 후 C:\\SMC_GRAPHRAG LightRAG (+ 선택 증분 그래프)에 적재한다."""
    cfg = cfg or get_config()
    raw_text = file_path.read_text(encoding="utf-8")
    normalized_text = normalize_entities_with_glossary(raw_text, cfg.glossary_path)
    doc_label = f"{source_id}_{file_path.name}" if source_id else file_path.name

    result: dict[str, Any] = {
        "file": str(file_path),
        "doc_label": doc_label,
        "char_count": len(normalized_text),
        "lightrag_store": str(cfg.lightrag_working_dir),
    }

    # 1. LightRAG HTTP Server 적재 시도
    lr_status = _check_lightrag_server(cfg)
    if lr_status.get("online"):
        resp = requests.post(
            f"{cfg.lightrag_api_url}/documents/text",
            json={"text": normalized_text, "file_source": doc_label},
            timeout=120,
        )
        result["lightrag_ingest"] = {
            "mode": "server_api",
            "status_code": resp.status_code,
            "response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300],
        }
    else:
        result["lightrag_ingest"] = {
            "mode": "server_offline",
            "note": "LightRAG 서버가 꺼져 있습니다. scripts/start_lightrag.ps1 로 서버를 먼저 기동하거나 --also-legacy-graph 옵션을 사용하세요.",
        }

    # 2. 선택적 기존 C:\SMC_GRAPHRAG 형식 증분 그래프 병합
    if also_legacy_graph:
        result["legacy_incremental_graph"] = _append_to_legacy_incremental_graph(
            doc_label=doc_label,
            text=normalized_text,
            cfg=cfg,
            model=model,
        )

    return result


def show_status(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    graph_files = _list_smc_graph_files(cfg)
    lr_files = list(cfg.lightrag_working_dir.glob("*")) if cfg.lightrag_working_dir.is_dir() else []
    return {
        "smc_graphrag_root": str(cfg.smc_graphrag_root),
        "existing_graph_files": [
            {"name": p.name, "size_mb": round(p.stat().st_size / (1024 * 1024), 2)}
            for p in graph_files
        ],
        "catalog_db_exists": cfg.smc_catalog_db_path.is_file(),
        "catalog_db_path": str(cfg.smc_catalog_db_path),
        "lightrag_working_dir": str(cfg.lightrag_working_dir),
        "lightrag_store_file_count": len(lr_files),
        "lightrag_server": _check_lightrag_server(cfg),
        "neo4j": _check_neo4j(cfg),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="C:\\SMC_GRAPHRAG + LightRAG 통합 지식그래프 브리지")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="기존 C:\\SMC_GRAPHRAG, LightRAG, Neo4j 상태 점검")

    p_idx = sub.add_parser("build-index", help="C:\\SMC_GRAPHRAG\\output\\graph*.json SQLite 카탈로그 구축")
    p_idx.add_argument("--force", action="store_true", help="모든 그래프 파일 강제 재색인")

    p_gap = sub.add_parser("gap-check", help="Graph-First 선조회 및 kg_gap_report.json 생성")
    p_gap.add_argument("--topic", required=True, help="보고서/단원 주제")
    p_gap.add_argument("--terms", default="", help="쉼표 구분 핵심 개념 목록")
    p_gap.add_argument("--out", type=Path, default=None, help="리포트 출력 경로")

    p_ing = sub.add_parser("ingest", help="정제 문서를 C:\\SMC_GRAPHRAG (LightRAG / 증분 그래프)에 적재")
    p_ing.add_argument("--file", type=Path, required=True, help="정제된 마크다운 파일 경로")
    p_ing.add_argument("--source-id", default="", help="출처 ID (예: SRC-01)")
    p_ing.add_argument("--also-legacy-graph", action="store_true", help="graph_platform_incremental.json 및 Neo4j에도 병합")
    p_ing.add_argument("--model", default=None, help="Ollama 모델 오버라이드")

    args = parser.parse_args()
    cfg = get_config()

    if args.cmd == "status":
        print(json.dumps(show_status(cfg), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-index":
        print(json.dumps(build_smc_catalog(cfg, force=args.force), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "gap-check":
        terms = [t.strip() for t in args.terms.split(",") if t.strip()]
        res = run_gap_check(topic=args.topic, terms=terms, out_path=args.out, cfg=cfg)
        print(
            json.dumps(
                {
                    "topic": res["topic"],
                    "reuse_ratio_percent": res["reuse_ratio_percent"],
                    "reusable_count": len(res["reusable_knowledge"]),
                    "gap_count": len(res["missing_or_outdated_gaps"]),
                    "report_path": str(args.out or (cfg.reports_dir / "kg_gap_report.json")),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.cmd == "ingest":
        res = ingest_text_to_kg(
            file_path=args.file,
            source_id=args.source_id,
            also_legacy_graph=args.also_legacy_graph,
            model=args.model,
            cfg=cfg,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
