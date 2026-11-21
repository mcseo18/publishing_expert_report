"""대시보드 큐레이션(curation_state.json)의 단원 배정(chapters)을 기준으로
단원별 근거 패킷(E:\\SMC_Report_Platform_Data\\evidence\\chNN_evidence.json)을 자동 동기화한다.

예: SRC-45(Rothamsted RothC)가 ch09, ch10, ch11에 배정되어 있으면
ch10_evidence.json과 ch11_evidence.json 모두에 해당 검증 근거를 포함시켜
domain-drafter가 단원별 모든 관련 출처를 누락 없이 인용할 수 있게 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from compliance import upsert_evidence_packet
from config import PlatformConfig, get_config


def sync_packets(target_chapters: list[str] | None = None, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    cur_path = cfg.index_dir / "curation_state.json"
    curation: dict[str, dict[str, Any]] = (
        json.loads(cur_path.read_text(encoding="utf-8")) if cur_path.is_file() else {}
    )

    # 모든 evidence JSON에서 source_id -> source_item 수집
    source_pool: dict[str, dict[str, Any]] = {}
    for p in sorted(cfg.evidence_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            for s in d.get("sources", []):
                sid = s.get("source_id")
                if sid:
                    source_pool[sid] = s
        except Exception:
            continue

    # 단원별 배정 source_id 집합 구성
    chapter_map: dict[str, list[str]] = {}
    for sid, cur in curation.items():
        if cur.get("status") == "rejected":
            continue
        if sid not in source_pool:
            continue
        for ch in cur.get("chapters") or []:
            chapter_map.setdefault(ch, []).append(sid)

    summary: dict[str, Any] = {}
    chapters_to_sync = target_chapters or sorted(chapter_map.keys())
    for ch in chapters_to_sync:
        sids = sorted(set(chapter_map.get(ch, [])), key=lambda x: int(x.split("-")[1]) if "-" in x and x.split("-")[1].isdigit() else 9999)
        packet_id = f"{ch}_evidence"
        packet_path = cfg.evidence_dir / f"{packet_id}.json"
        added = 0
        for sid in sids:
            upsert_evidence_packet(
                packet_path=packet_path,
                source_item=source_pool[sid],
                packet_id=packet_id,
                topic=f"토양 유기물학 {ch} 통합 근거 패킷",
                storage_root=str(cfg.collected_data_root),
                kg_store_root=str(cfg.smc_graphrag_root),
                schema_path=cfg.evidence_schema_path,
            )
            added += 1
        final_cnt = len(json.loads(packet_path.read_text(encoding="utf-8")).get("sources", [])) if packet_path.is_file() else 0
        summary[ch] = {"packet_path": str(packet_path), "synced_from_curation": added, "total_sources_in_packet": final_cnt, "source_ids": sids}

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="단원별 근거 패킷 자동 동기화")
    parser.add_argument("--chapters", default="", help="쉼표 구분 단원 ID (예: ch07,ch10,ch11)")
    args = parser.parse_args()
    chs = [c.strip() for c in args.chapters.split(",") if c.strip()] or None
    print(json.dumps(sync_packets(chs), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
