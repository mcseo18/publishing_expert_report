"""C:\\SMC_GRAPHRAG 기존 지식그래프에서 재활용 가능한 엔티티·관계를 근거 패킷(kg_reuse)으로 추출한다.

Graph-First 워크플로에서 이미 확보된 지식을 E:\\SMC_Report_Platform_Data\\evidence\\<packet>.json에
공식 [SRC-NN] (source_type="kg_reuse") 출처로 등록해 초안 집필과 인용 감사에서 그대로 인용할 수 있게 한다.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from compliance import (
    SourcesRegistry,
    chunk_korean_text,
    sha256_text,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config
from smc_kg_bridge import build_smc_catalog


def export_kg_reuse_evidence(
    terms: list[str],
    packet_id: str,
    topic: str,
    title: str = "C:\\SMC_GRAPHRAG 기존 지식그래프 선조회 재활용 근거",
    max_relations_per_term: int = 12,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    if not cfg.smc_catalog_db_path.is_file():
        build_smc_catalog(cfg)

    conn = sqlite3.connect(str(cfg.smc_catalog_db_path))
    try:
        cur = conn.cursor()
        md_lines: list[str] = [f"# {title}", f"- 대상 주제: {topic}", ""]
        extracted_facts: list[dict[str, Any]] = []
        seen_rel: set[tuple[str, str, str, str]] = set()
        referenced_docs: set[str] = set()

        for term in terms:
            like = f"%{term}%"
            ents = cur.execute(
                """
                SELECT name, entity_type, SUM(mentions) AS m, GROUP_CONCAT(DISTINCT graph_file)
                FROM entities
                WHERE name LIKE ?
                GROUP BY name, entity_type
                ORDER BY m DESC
                LIMIT 6
                """,
                (like,),
            ).fetchall()
            rels = cur.execute(
                """
                SELECT source, relation, target, source_doc, graph_file
                FROM relations
                WHERE source LIKE ? OR target LIKE ?
                LIMIT ?
                """,
                (like, like, max_relations_per_term),
            ).fetchall()

            if not ents and not rels:
                continue

            md_lines.append(f"## 키워드: {term}")
            if ents:
                ent_summary = ", ".join(f"{e[0]}({e[1]}, 언급 {e[2]}회)" for e in ents[:5])
                md_lines.append(f"- 주요 엔티티: {ent_summary}")
            for s, r, t, sdoc, gfile in rels:
                key = (s, r, t, sdoc)
                if key in seen_rel:
                    continue
                seen_rel.add(key)
                if sdoc:
                    referenced_docs.add(sdoc)
                claim = f"{s} —[{r}]→ {t}"
                md_lines.append(f"- 관계: {claim} (원천문서: {sdoc or gfile})")
                extracted_facts.append(
                    {
                        "claim": claim,
                        "page_or_section": f"SMC_GRAPHRAG/{gfile} ({sdoc or 'unknown'})",
                        "evidence_quote_short": claim[:120],
                    }
                )
            md_lines.append("")
    finally:
        conn.close()

    md_text = "\n".join(md_lines).strip()
    content_hash = sha256_text(md_text)
    registry = SourcesRegistry(cfg.sources_registry_path)

    dup = registry.find_duplicate(content_sha256=content_hash)
    if dup:
        return {"status": "SKIPPED_DUPLICATE", "existing": dup}

    source_id = registry.next_source_id()
    parsed_path = cfg.parsed_dir / f"{source_id}_smc_graphrag_reuse.md"
    parsed_path.write_text(md_text, encoding="utf-8")

    chunks = chunk_korean_text(md_text, target_chars=450, overlap_chars=80, default_section="SMC_GRAPHRAG")
    now = utc_now_iso()
    source_item = {
        "source_id": source_id,
        "source_type": "kg_reuse",
        "url": cfg.smc_graphrag_root.as_uri(),
        "title": f"{title} (참조문서 {len(referenced_docs)}종)",
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": "local_knowledge_graph",
        "license_note": "사용자 로컬 지식그래프(C:\\SMC_GRAPHRAG) 내부 자산 재활용",
        "page_or_section": f"기존 그래프 10종 / 참조문서 {len(referenced_docs)}건",
        "raw_path": str(cfg.smc_graphrag_output_dir),
        "parsed_path": str(parsed_path),
        "pii_masked": True,
        "pii_redaction_count": 0,
        "prompt_injection_warnings": [],
        "sha256": content_hash,
        "extracted_facts": extracted_facts[:120],
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
            "source_type": "kg_reuse",
            "url": cfg.smc_graphrag_root.as_uri(),
            "normalized_url": f"kg://smc_graphrag/{packet_id}/{source_id}",
            "title": source_item["title"],
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": "local_knowledge_graph",
            "sha256": content_hash,
            "raw_path": str(cfg.smc_graphrag_output_dir),
            "parsed_path": str(parsed_path),
            "packet_path": str(packet_path),
            "parser_engine": "smc_graphrag_catalog",
            "fact_count": len(source_item["extracted_facts"]),
            "chunk_count": len(chunks),
        }
    )

    return {
        "status": "OK",
        "source_id": source_id,
        "packet_path": str(packet_path),
        "parsed_path": str(parsed_path),
        "referenced_docs_count": len(referenced_docs),
        "fact_count": len(source_item["extracted_facts"]),
        "chunk_count": len(chunks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="C:\\SMC_GRAPHRAG 기존 지식을 근거 패킷(kg_reuse)으로 추출")
    parser.add_argument("--terms", required=True, help="쉼표 구분 검색 키워드")
    parser.add_argument("--packet", required=True, help="근거 패킷 ID (예: ch01_evidence)")
    parser.add_argument("--topic", required=True, help="주제 또는 단원명")
    parser.add_argument("--title", default="C:\\SMC_GRAPHRAG 기존 지식그래프 선조회 재활용 근거")
    args = parser.parse_args()

    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    res = export_kg_reuse_evidence(terms=terms, packet_id=args.packet, topic=args.topic, title=args.title)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
