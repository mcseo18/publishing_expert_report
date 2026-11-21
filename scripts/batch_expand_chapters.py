"""나머지 단원(ch02~ch06, ch08, ch09, ch12~ch16) 일괄 초안 집필 -> 인용 감사 -> 4종 멀티포맷 빌드 러너.

- 로컬 Ollama 모델로 $0 API 비용 대량 생산 (기본: gemma4:latest 100% GPU 고속 또는 --model gemma4:26b)
- 각 단원 완료 직후 verify_citations.py 로 감사 PASS 검증
- PASS 단원은 자동으로 Phase 3 4종 출판(교재 PDF·교과서 PDF·보고서 DOCX/PDF·인터랙티브 웹)까지 동시 빌드
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from build_outputs import build_chapter_outputs
from config import get_config
from draft_chapter import draft_chapter
from verify_citations import verify_target


DEFAULT_REMAINING = ["ch02", "ch03", "ch04", "ch05", "ch06", "ch08", "ch09", "ch12", "ch13", "ch14", "ch15", "ch16"]


def run_batch(chapters: list[str], model: str, build_4formats: bool = True, skip_existing: bool = True) -> dict[str, Any]:
    cfg = get_config()
    summary: list[dict[str, Any]] = []
    t_start = time.time()

    for cid in chapters:
        bp_path = cfg.blueprints_dir / f"{cid}.yaml"
        ev_path = cfg.evidence_dir / f"{cid}_evidence.json"
        out_mdx = cfg.chapters_dir / f"{cid}.mdx"
        audit_path = cfg.reports_dir / f"audit_{cid}.json"

        if not bp_path.is_file() or not ev_path.is_file():
            summary.append({"chapter_id": cid, "status": "SKIPPED_MISSING_INPUT"})
            continue

        item: dict[str, Any] = {"chapter_id": cid}
        if skip_existing and out_mdx.is_file():
            item["draft"] = {"status": "SKIPPED_EXISTING", "chars": len(out_mdx.read_text(encoding="utf-8"))}
        else:
            print(f"[DRAFT] {cid} ({model}) ...", flush=True)
            d_res = draft_chapter(bp_path, ev_path, out_mdx, model=model, think=False, cfg=cfg)
            item["draft"] = {"status": d_res["status"], "chars": d_res["total_chars"], "model": model}

        audit = verify_target(out_mdx, cfg=cfg)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        item["audit"] = {
            "status": audit["status"],
            "critical_errors": len(audit["critical_errors"]),
            "warnings": len(audit["warnings"]),
        }
        print(f"  [AUDIT] {cid}: {audit['status']} (crit={len(audit['critical_errors'])}, warn={len(audit['warnings'])})", flush=True)

        if build_4formats and audit["status"] == "PASS":
            b_res = build_chapter_outputs(cid, cfg=cfg)
            item["build"] = {"status": b_res["status"], "export_dir": b_res.get("export_dir")}
            print(f"  [BUILD 4-FORMAT] {cid}: {b_res['status']}", flush=True)

        summary.append(item)

    full_audit = verify_target(cfg.chapters_dir, cfg=cfg)
    (cfg.reports_dir / "audit_latest.json").write_text(json.dumps(full_audit, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "elapsed_seconds": round(time.time() - t_start, 2),
        "model": model,
        "chapters_processed": len(summary),
        "full_book_audit": {
            "status": full_audit["status"],
            "checked_files": full_audit["checked_files"],
            "critical_errors": len(full_audit["critical_errors"]),
            "warnings": len(full_audit["warnings"]),
        },
        "details": summary,
    }
    (cfg.reports_dir / "book_build_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="전 단원 일괄 초안 집필 + 감사 + 4종 출판")
    parser.add_argument("--chapters", default=",".join(DEFAULT_REMAINING))
    parser.add_argument("--model", default="gemma4:latest", help="로컬 Ollama 모델 (gemma4:latest 100% GPU 고속 / gemma4:26b)")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--force", action="store_true", help="이미 있는 초안도 덮어쓰기")
    args = parser.parse_args()

    chs = [c.strip() for c in args.chapters.split(",") if c.strip()]
    res = run_batch(chs, model=args.model, build_4formats=not args.no_build, skip_existing=not args.force)
    print(json.dumps(res["full_book_audit"], ensure_ascii=False, indent=2))
    return 0 if res["full_book_audit"]["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
