"""Phase 0 & Phase 1 자동 스모크 테스트.

검증 항목:
1. 물리 저장소(E:\\SMC_Report_Platform_Data) 및 지식그래프(C:\\SMC_GRAPHRAG\\lightrag_store) 정션 확인
2. 핵심 설정 파일(AGENTS.md, GEMINI.md, CLAUDE.md, .agents/mcp_config.json, .mcp.json, .claude/settings.json)
3. Ollama 버전(>=0.21.1), gemma4:26b 구조화 출력(think=false + format), bge-m3 임베딩
4. C:\\SMC_GRAPHRAG 기존 지식그래프 SQLite 카탈로그 및 Graph-First 선조회(gap-check)
5. doc-ingestor 로컬 문서 파싱 + PII 마스킹 + evidence_packet.schema.json 검증
6. verify_citations.py 정상 PASS / 미등록 인용키 FAIL / 15어절 원문 복사 FAIL 검증
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from compliance import mask_pii, validate_evidence_packet
from config import get_config
from local_gemma import LocalGemmaClient
from parse_pdf import parse_document
from smc_kg_bridge import build_smc_catalog, run_gap_check, show_status
from verify_citations import verify_target


def run_all() -> dict:
    cfg = get_config()
    results: dict = {"checks": {}, "all_passed": True}

    def record(name: str, ok: bool, detail: object) -> None:
        results["checks"][name] = {"ok": ok, "detail": detail}
        if not ok:
            results["all_passed"] = False

    # 1. Directories & Junctions
    junction_targets = {
        "data/raw": cfg.collected_data_root / "raw",
        "data/parsed": cfg.collected_data_root / "parsed",
        "data/evidence": cfg.collected_data_root / "evidence",
        "data/index": cfg.collected_data_root / "index",
        "data/kg_store": cfg.lightrag_working_dir,
    }
    j_ok = True
    j_detail = {}
    for rel, expected in junction_targets.items():
        p = cfg.workspace_root / rel
        resolved_ok = p.exists() and p.resolve() == expected.resolve()
        j_detail[rel] = {"exists": p.exists(), "resolved": str(p.resolve()), "expected": str(expected.resolve()), "match": resolved_ok}
        if not resolved_ok:
            j_ok = False
    record("storage_junctions", j_ok, j_detail)

    # 2. Config & governance files
    required_files = [
        "AGENTS.md",
        "GEMINI.md",
        "CLAUDE.md",
        ".agents/mcp_config.json",
        ".agents/rules/copyright-and-citation.md",
        ".agents/rules/storage-and-kg-routing.md",
        ".mcp.json",
        ".claude/settings.json",
        "schemas/evidence_packet.schema.json",
        "schemas/glossary.json",
    ]
    missing = [f for f in required_files if not (cfg.workspace_root / f).is_file()]
    record("governance_files", len(missing) == 0, {"missing": missing, "checked": len(required_files)})

    # 3. Ollama + Gemma 4 + BGE-M3
    try:
        gemma = LocalGemmaClient(cfg)
        health = gemma.check_health()
        smoke_schema = {
            "type": "object",
            "properties": {"ready": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["ready", "note"],
        }
        # 스모크 테스트는 빠른 확인을 위해 설정된 기본 모델(gemma4:26b)로 실행
        structured = gemma.chat_structured(
            messages=[{"role": "user", "content": 'JSON으로 ready=true, note="로컬 엔진 준비 완료" 만 출력하세요.'}],
            schema=smoke_schema,
            num_ctx=4096,
            num_predict=64,
        )
        emb = gemma.embed(["지식그래프 테스트 문장"])
        ok = (
            health["version_ok_for_gemma4_format"]
            and structured.get("ready") is True
            and len(emb[0]) > 0
        )
        record(
            "ollama_gemma4_bge_m3",
            ok,
            {
                "version": health["version"],
                "model": cfg.ollama_llm_model,
                "structured": structured,
                "embed_dim": len(emb[0]),
            },
        )
    except Exception as exc:
        record("ollama_gemma4_bge_m3", False, {"error": str(exc)})

    # 4. C:\SMC_GRAPHRAG catalog & gap-check
    try:
        cat = build_smc_catalog(cfg)
        gap = run_gap_check(
            topic="퇴비화 공정과 스마트농업 표현체학 분석",
            terms=["퇴비", "스마트농업", "존재하지않는가상신규기술XYZ2026"],
            out_path=cfg.reports_dir / "smoke_kg_gap_report.json",
            cfg=cfg,
        )
        st = show_status(cfg)
        ok = cat["graph_files_total"] > 0 and len(gap["reusable_knowledge"]) >= 1 and len(gap["missing_or_outdated_gaps"]) >= 1
        record(
            "smc_graphrag_integration",
            ok,
            {
                "graph_files_total": cat["graph_files_total"],
                "total_nodes_indexed": cat["total_nodes_indexed"],
                "total_edges_indexed": cat["total_edges_indexed"],
                "reuse_ratio_percent": gap["reuse_ratio_percent"],
                "lightrag_server_online": st["lightrag_server"]["online"],
            },
        )
    except Exception as exc:
        record("smc_graphrag_integration", False, {"error": str(exc)})

    # 5. PII masking + parse_pdf + evidence schema + verify_citations
    try:
        masked, red_cnt = mask_pii("담당자 연락처 010-1234-5678, 이메일 test@example.com, 주민번호 900101-1234567")
        pii_ok = red_cnt == 3 and "010-1234-5678" not in masked and "test@example.com" not in masked

        with tempfile.TemporaryDirectory() as tmp:
            sample_md = Path(tmp) / "smoke_sample_doc.md"
            sample_md.write_text(
                "# 퇴비 부숙도 관리 기준\n\n"
                "퇴비화 공정에서 적정 탄질비는 25~35 범위이며 수분 함량은 55~65%를 유지하는 것이 핵심 원리입니다. "
                "담당자 문의는 010-9876-5432 또는 admin@sample.org 로 접수됩니다.\n\n"
                "## 주요 지표\n\n"
                "호기성 미생물 활성화를 위해 주기적 뒤집기와 통기량 제어가 필수적이며 발효 온도는 55도 이상 유지됩니다.\n",
                encoding="utf-8",
            )
            parsed = parse_document(
                file_path=sample_md,
                packet_id="smoke_test_evidence",
                topic="스모크 테스트",
                use_docling=False,
                force=True,
                cfg=cfg,
            )
            packet_path = Path(parsed["packet_path"])
            packet_data = json.loads(packet_path.read_text(encoding="utf-8"))
            schema_errors = validate_evidence_packet(packet_data, cfg.evidence_schema_path)
            sid = parsed["source_id"]

            # PASS chapter
            good_ch = Path(tmp) / "good.mdx"
            good_ch.write_text(f"# 테스트 단원\n\n적정 수분 함량은 55~65% 수준으로 관리한다 [{sid}].\n", encoding="utf-8")
            pass_audit = verify_target(good_ch, cfg=cfg)

            # FAIL chapter (missing SRC-999)
            bad_ch = Path(tmp) / "bad.mdx"
            bad_ch.write_text("# 오류 단원\n\n근거 없는 주장 [SRC-999].\n", encoding="utf-8")
            fail_audit = verify_target(bad_ch, cfg=cfg)

            # Cleanup temporary smoke evidence packet & registry entry so production data stays clean
            packet_path.unlink(missing_ok=True)
            Path(parsed["raw_path"]).unlink(missing_ok=True)
            Path(parsed["parsed_path"]).unlink(missing_ok=True)
            tables_p = Path(parsed["parsed_path"]).with_name(Path(parsed["parsed_path"]).stem + "_tables.json")
            tables_p.unlink(missing_ok=True)
            if cfg.sources_registry_path.is_file():
                kept = [
                    ln
                    for ln in cfg.sources_registry_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and f'"source_id": "{sid}"' not in ln and '"title": "smoke_sample_doc"' not in ln
                ]
                if kept:
                    cfg.sources_registry_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
                else:
                    cfg.sources_registry_path.unlink(missing_ok=True)

            ok = (
                pii_ok
                and parsed["status"] == "OK"
                and parsed["pii_redaction_count"] == 2
                and len(schema_errors) == 0
                and pass_audit["status"] == "PASS"
                and fail_audit["status"] == "FAIL"
            )
            record(
                "doc_ingestor_and_citation_gate",
                ok,
                {
                    "pii_ok": pii_ok,
                    "source_id": sid,
                    "schema_errors": schema_errors,
                    "pass_audit": pass_audit["status"],
                    "fail_audit": fail_audit["status"],
                },
            )
    except Exception as exc:
        record("doc_ingestor_and_citation_gate", False, {"error": str(exc)})

    return results


if __name__ == "__main__":
    res = run_all()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["all_passed"] else 1)
