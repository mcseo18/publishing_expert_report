"""Google NotebookLM 수집 자료 가져오기(Import) 커넥터.

로컬에 인증·설치된 `nlm.exe` (NotebookLM Tools CLI)를 호출해:
1. 내 Google NotebookLM 계정 전체 노트북 목록 조회 (`nlm notebook list --json`)
2. 선택한 노트북의 수집 소스(PDF·웹페이지·문서 등) 및 스튜디오 노트 목록 조회 (`nlm source list`, `nlm note list`)
3. 체크 선택한 소스의 원문 텍스트(`nlm source content --json`)를 PII 마스킹 후:
   - `E:\\SMC_Report_Platform_Data\\projects\\<project_id>\\collected\\06_notebooklm_sources\\`
   - 및 해당 분류 폴더(`01~04`) + 프로젝트/공용 근거 패킷(`<packet_id>.json`) + `sources.jsonl`에 정식 `[SRC-NN]`으로 등록
4. 선택 시 즉시 `C:\\SMC_GRAPHRAG` 증분 지식그래프(RAG)에 적재한다 (기존 `graph.json` 무훼손).
5. 노트북에 직접 질문(`nlm notebook query`)해 근거 기반 요약 답변을 가져올 수도 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from compliance import (
    SourcesRegistry,
    chunk_korean_text,
    mask_pii,
    normalize_url,
    sha256_text,
    slugify,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config
from fetch_project_sources import TIER_DIRS, TIER_LABELS_KO, _ensure_duplicate_in_packet, _write_collection_index_md


def _resolve_nlm_bin() -> str | None:
    found = shutil.which("nlm") or shutil.which("nlm.exe")
    if found:
        return found
    cand = Path.home() / ".local" / "bin" / "nlm.exe"
    return str(cand) if cand.is_file() else None


def _run_nlm_json(args: list[str], timeout_sec: int = 60) -> Any:
    nlm_bin = _resolve_nlm_bin()
    if not nlm_bin:
        raise FileNotFoundError("NotebookLM CLI(nlm.exe)를 찾을 수 없습니다. (경로 확인: %USERPROFILE%\\.local\\bin\\nlm.exe)")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [nlm_bin, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        env=env,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0 and not out:
        raise RuntimeError(err or f"nlm command failed (code {proc.returncode})")
    # JSON 배열 또는 객체 시작 위치 추출 (CLI 경고 로그 혼입 방어)
    starts = [i for i in (out.find("["), out.find("{")) if i != -1]
    if not starts:
        if proc.returncode != 0:
            raise RuntimeError(err or out[:300])
        return {"raw_text": out}
    start = min(starts)
    end = max(out.rfind("]"), out.rfind("}"))
    json_str = out[start : end + 1] if end >= start else out[start:]
    return json.loads(json_str)


def check_nlm_status() -> dict[str, Any]:
    nlm_bin = _resolve_nlm_bin()
    if not nlm_bin:
        return {"installed": False, "authenticated": False, "path": "", "error": "nlm.exe 미설치"}
    try:
        nbs = list_notebooks()
        return {
            "installed": True,
            "authenticated": True,
            "path": nlm_bin,
            "notebook_count": len(nbs),
        }
    except Exception as exc:
        return {
            "installed": True,
            "authenticated": False,
            "path": nlm_bin,
            "error": str(exc)[:200],
        }


def list_notebooks(query: str = "") -> list[dict[str, Any]]:
    """내 NotebookLM 계정의 전체 노트북 목록을 조회한다."""
    data = _run_nlm_json(["notebook", "list", "--json"], timeout_sec=35)
    items = data if isinstance(data, list) else data.get("notebooks", [])
    ql = query.strip().lower()
    out: list[dict[str, Any]] = []
    for nb in items:
        title = (nb.get("title") or "").strip() or "(제목 없음)"
        if ql and ql not in title.lower():
            continue
        out.append(
            {
                "id": nb.get("id", ""),
                "title": title,
                "source_count": int(nb.get("source_count") or 0),
                "updated_at": nb.get("updated_at", ""),
                "url": f"https://notebooklm.google.com/notebook/{nb.get('id', '')}",
            }
        )
    return out


def list_notebook_sources(notebook_id: str) -> dict[str, Any]:
    """특정 NotebookLM 노트북 안의 전체 소스 목록과 스튜디오 노트 목록을 조회한다."""
    nb_id = notebook_id.strip()
    if not nb_id:
        raise ValueError("notebook_id가 필요합니다.")
    src_data = _run_nlm_json(["source", "list", nb_id, "--json"], timeout_sec=40)
    sources_raw = src_data if isinstance(src_data, list) else src_data.get("sources", [])
    sources = [
        {
            "id": s.get("id", ""),
            "title": (s.get("title") or "").strip() or "(제목 없음)",
            "type": s.get("type", "unknown"),
            "url": s.get("url") or "",
            "status": s.get("status"),
        }
        for s in sources_raw
        if s.get("id")
    ]
    notes: list[dict[str, Any]] = []
    try:
        note_data = _run_nlm_json(["note", "list", nb_id, "--json"], timeout_sec=25)
        raw_notes = note_data.get("notes", []) if isinstance(note_data, dict) else (note_data if isinstance(note_data, list) else [])
        for n in raw_notes:
            notes.append(
                {
                    "id": n.get("id", ""),
                    "title": n.get("title") or "(노트)",
                    "content": n.get("content") or "",
                    "updated_at": n.get("updated_at") or "",
                }
            )
    except Exception:
        pass
    return {"notebook_id": nb_id, "source_count": len(sources), "sources": sources, "note_count": len(notes), "notes": notes}


def read_notebook_source_content(source_id: str) -> dict[str, Any]:
    """NotebookLM 소스 1건의 원문 텍스트 전체를 추출한다."""
    data = _run_nlm_json(["source", "content", source_id.strip(), "--json"], timeout_sec=45)
    if not isinstance(data, dict):
        return {"content": str(data), "title": source_id, "source_type": "unknown", "url": "", "char_count": len(str(data))}
    return {
        "source_id": source_id.strip(),
        "title": (data.get("title") or "").strip() or source_id,
        "source_type": data.get("source_type") or "unknown",
        "url": data.get("url") or "",
        "content": data.get("content") or "",
        "char_count": int(data.get("char_count") or len(data.get("content") or "")),
    }


def query_notebooklm(notebook_id: str, question: str) -> dict[str, Any]:
    """NotebookLM 노트북에 직접 질문해 소스 기반 요약 답변을 가져온다."""
    data = _run_nlm_json(
        ["notebook", "query", notebook_id.strip(), question.strip(), "--json", "--new-conversation"],
        timeout_sec=120,
    )
    if isinstance(data, dict):
        answer = data.get("answer") or data.get("response") or data.get("text") or json.dumps(data, ensure_ascii=False, indent=2)
    else:
        answer = str(data)
    return {
        "notebook_id": notebook_id.strip(),
        "question": question.strip(),
        "answer": answer,
        "markdown": (
            f"# [NotebookLM 질의 응답] {question.strip()}\n\n"
            f"- **노트북 ID**: `{notebook_id.strip()}`\n"
            f"- **노트북 URL**: https://notebooklm.google.com/notebook/{notebook_id.strip()}\n"
            f"- **조회 시각**: `{utc_now_iso()}`\n\n"
            f"## NotebookLM 근거 기반 답변\n\n{answer}\n"
        ),
    }


def _classify_notebooklm_tier(title: str, url: str, src_type: str) -> str:
    has_ko = any("\uac00" <= ch <= "\ud7a3" for ch in title) or ".kr" in url.lower()
    is_paper = src_type == "pdf" or any(k in url.lower() for k in ("doi.org", "eric.ed.gov", "sciencedirect", "springer", "wiley", "mdpi", "ncbi", "arxiv", "conferences"))
    if has_ko:
        return "domestic_journals" if is_paper else "domestic_agencies"
    return "international_journals" if is_paper else "international_agencies"


def import_notebooklm_sources(
    *,
    project_id: str,
    notebook_id: str,
    notebook_title: str = "",
    source_ids: list[str],
    also_ingest_rag: bool = True,
    chapters: list[str] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """NotebookLM에서 선택한 소스들을 프로젝트 분리 폴더 + 근거 패킷 + (선택)RAG로 가져온다."""
    cfg = cfg or get_config()
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project {project_id} not found")

    packet_id = st.get("packet_id") or f"{project_id}_evidence"
    topic_ko = st.get("topic_ko", project_id)
    collected_root = cfg.project_collected_dir(project_id)
    nlm_dir = collected_root / "06_notebooklm_sources"
    nlm_dir.mkdir(parents=True, exist_ok=True)
    proj_e_ev = cfg.project_e_evidence_dir(project_id)
    proj_e_ev.mkdir(parents=True, exist_ok=True)
    ws_col = cfg.project_dir(project_id) / "collected"
    ws_col.mkdir(parents=True, exist_ok=True)

    registry = SourcesRegistry(cfg.sources_registry_path)
    existing_sources: list[dict[str, Any]] = list(st.get("collected_sources") or [])
    existing_sids = {s.get("source_id") for s in existing_sources if s.get("source_id")}
    curation_path = cfg.index_dir / "curation_state.json"
    curation = json.loads(curation_path.read_text(encoding="utf-8")) if curation_path.is_file() else {}

    imported: list[dict[str, Any]] = []
    errors: list[str] = []

    for nlm_sid in source_ids:
        nlm_sid = nlm_sid.strip()
        if not nlm_sid:
            continue
        try:
            raw = read_notebook_source_content(nlm_sid)
            title = raw["title"]
            src_url = raw["url"] or f"https://notebooklm.google.com/notebook/{notebook_id}#source={nlm_sid}"
            src_type = raw["source_type"]
            body_text = raw["content"].strip()
            if not body_text:
                errors.append(f"{title}: 추출된 본문이 비어 있습니다.")
                continue

            tier_key = _classify_notebooklm_tier(title, src_url, src_type)
            tier_dir = collected_root / TIER_DIRS[tier_key]
            tier_dir.mkdir(parents=True, exist_ok=True)

            md_text = (
                f"# {title}\n\n"
                f"- **수집 경로**: Google NotebookLM (`{notebook_title or notebook_id}`)\n"
                f"- **NotebookLM 소스 ID**: `{nlm_sid}` (유형: `{src_type}`)\n"
                f"- **원본 URL**: {src_url}\n"
                f"- **원문 문자 수**: {len(body_text):,}자\n"
                f"- **가져오기 시각**: `{utc_now_iso()}`\n\n"
                f"## 원문 추출 내용 (NotebookLM Indexed Content)\n\n"
                f"{body_text}\n"
            )
            cleaned_md, pii_count = mask_pii(md_text)
            content_hash = sha256_text(cleaned_md)
            norm_url = normalize_url(src_url) if src_url.startswith(("http://", "https://")) else src_url

            dup = registry.find_duplicate(content_sha256=content_hash) or (
                registry.find_duplicate(url=norm_url) if raw["url"] else None
            )
            if dup:
                sid = dup["source_id"]
                _ensure_duplicate_in_packet(existing_rec=dup, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                pp = dup.get("parsed_path", "")
                saved_files: list[str] = []
                if pp and Path(pp).is_file():
                    dst_nlm = nlm_dir / Path(pp).name
                    dst_tier = tier_dir / Path(pp).name
                    shutil.copy2(pp, dst_nlm)
                    shutil.copy2(pp, dst_tier)
                    saved_files = [str(dst_nlm), str(dst_tier)]
                rec_entry = {
                    "source_id": sid,
                    "tier": tier_key,
                    "tier_folder": TIER_DIRS[tier_key],
                    "tier_label": f"NotebookLM ({TIER_LABELS_KO[tier_key]})",
                    "title": title,
                    "journal": f"NotebookLM: {notebook_title or notebook_id}",
                    "year": datetime.now().year,
                    "cited_by_count": 0,
                    "url": src_url,
                    "provider": "Google NotebookLM (재연결)",
                    "status": "REUSED",
                    "saved_files": saved_files,
                }
                imported.append(rec_entry)
                if sid not in existing_sids:
                    existing_sids.add(sid)
                    existing_sources.append(rec_entry)
                continue

            sid = registry.next_source_id()
            slug = slugify(f"nlm_{title}", 48)
            parsed_path = cfg.parsed_dir / f"{sid}_{slug}.md"
            parsed_path.write_text(cleaned_md, encoding="utf-8")

            dst_nlm = nlm_dir / parsed_path.name
            dst_tier = tier_dir / parsed_path.name
            shutil.copy2(parsed_path, dst_nlm)
            shutil.copy2(parsed_path, dst_tier)
            saved_files = [str(dst_nlm), str(dst_tier)]

            chunks = chunk_korean_text(cleaned_md, default_section=f"NotebookLM:{notebook_title or notebook_id}")
            now = utc_now_iso()
            license_note = f"Google NotebookLM 수집 자료 가져오기 ({notebook_title or notebook_id}) - 변환적 분석 및 정식 인용"
            source_item = {
                "source_id": sid,
                "source_type": "pdf" if src_type == "pdf" else "web",
                "url": src_url,
                "title": title,
                "accessed_at": now,
                "robots_allowed": True,
                "robots_status": "notebooklm_user_library",
                "license_note": license_note,
                "page_or_section": f"NotebookLM ({src_type})",
                "raw_path": str(dst_nlm),
                "parsed_path": str(parsed_path),
                "pii_masked": True,
                "pii_redaction_count": pii_count,
                "prompt_injection_warnings": [],
                "sha256": content_hash,
                "extracted_facts": [],
                "tables": [],
                "chunks": chunks,
            }
            global_pkt = cfg.evidence_dir / f"{packet_id}.json"
            upsert_evidence_packet(
                packet_path=global_pkt,
                source_item=source_item,
                packet_id=packet_id,
                topic=topic_ko,
                storage_root=str(cfg.collected_data_root),
                kg_store_root=str(cfg.smc_graphrag_root),
                schema_path=cfg.evidence_schema_path,
            )
            shutil.copy2(global_pkt, proj_e_ev / f"{packet_id}.json")

            registry.append(
                {
                    "source_id": sid,
                    "source_type": source_item["source_type"],
                    "scholar_category": "notebooklm_import",
                    "provider": "Google NotebookLM",
                    "journal": f"NotebookLM: {notebook_title or notebook_id}",
                    "year": datetime.now().year,
                    "url": src_url,
                    "normalized_url": norm_url,
                    "title": title,
                    "accessed_at": now,
                    "robots_allowed": True,
                    "robots_status": "notebooklm_user_library",
                    "sha256": content_hash,
                    "raw_path": str(dst_nlm),
                    "parsed_path": str(parsed_path),
                    "packet_path": str(global_pkt),
                    "parser_engine": "notebooklm_nlm_cli",
                    "chunk_count": len(chunks),
                    "table_count": 0,
                }
            )
            curation[sid] = {
                "status": "approved",
                "tier": "NotebookLM 수집자료",
                "category": "notebooklm_import",
                "chapters": chapters or ["ch01"],
                "tags": ["NotebookLM", notebook_title or notebook_id],
                "notes": f"NotebookLM '{notebook_title or notebook_id}'에서 가져옴 ({len(body_text):,}자)",
                "rating": 5,
                "updated_at": now,
            }
            rec_entry = {
                "source_id": sid,
                "tier": tier_key,
                "tier_folder": TIER_DIRS[tier_key],
                "tier_label": f"NotebookLM ({TIER_LABELS_KO[tier_key]})",
                "title": title,
                "journal": f"NotebookLM: {notebook_title or notebook_id}",
                "year": datetime.now().year,
                "cited_by_count": 0,
                "url": src_url,
                "provider": "Google NotebookLM",
                "status": "OK",
                "char_count": len(body_text),
                "saved_files": saved_files,
            }
            imported.append(rec_entry)
            existing_sids.add(sid)
            existing_sources.append(rec_entry)
        except Exception as exc:
            errors.append(f"{nlm_sid}: {exc}")

    curation_path.write_text(json.dumps(curation, ensure_ascii=False, indent=2), encoding="utf-8")

    # 프로젝트 state.json & collection_manifest.json & INDEX.md 동기화
    breakdown = {k: sum(1 for s in existing_sources if s.get("tier") == k) for k in TIER_DIRS}
    st["collected_sources"] = existing_sources
    st["collection_breakdown"] = {**breakdown, "total": len(existing_sources)}
    save_project_state(st, cfg)

    manifest_path = collected_root / "collection_manifest.json"
    prev_m = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    global_pkt = cfg.evidence_dir / f"{packet_id}.json"
    manifest = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "topic_en": st.get("topic_en", topic_ko),
        "preset": prev_m.get("preset", "custom"),
        "generated_at": utc_now_iso(),
        "collected_root": str(collected_root),
        "tier_directories": {k: str(collected_root / v) for k, v in TIER_DIRS.items()},
        "notebooklm_dir": str(nlm_dir),
        "global_evidence_path": str(global_pkt),
        "project_evidence_path": str(proj_e_ev / f"{packet_id}.json"),
        "packet_id": packet_id,
        "total_collected": len(existing_sources),
        "pdf_downloaded_count": prev_m.get("pdf_downloaded_count", 0),
        "breakdown": breakdown,
        "source_ids": [s["source_id"] for s in existing_sources if s.get("source_id")],
        "sources": existing_sources,
        "blocked_or_failed": prev_m.get("blocked_or_failed", []),
    }
    m_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(m_json, encoding="utf-8")
    (ws_col / "collection_manifest.json").write_text(m_json, encoding="utf-8")
    _write_collection_index_md(manifest, collected_root / "INDEX.md")
    _write_collection_index_md(manifest, ws_col / "INDEX.md")

    imported_sids = [x["source_id"] for x in imported if x.get("source_id")]
    if imported_sids:
        append_event(
            project_id,
            "notebooklm-import",
            "stage2_web_scout",
            f"Google NotebookLM('{notebook_title or notebook_id}')에서 {len(imported_sids)}건 가져오기 완료 ({', '.join(imported_sids[:8])}) → 누적 {len(existing_sources)}건",
            cfg=cfg,
        )

    rag_delta = None
    if also_ingest_rag and imported_sids:
        from build_platform_kg import build_knowledge_graph_from_sources

        kg_model = st.get("options", {}).get("kg_model") or cfg.ollama_fast_model
        append_event(project_id, "kg-builder", "stage3_kg_builder", f"NotebookLM 가져온 자료 {len(imported_sids)}건 RAG(C:\\SMC_GRAPHRAG) 증분 적재 시작...", cfg=cfg)
        kg_res = build_knowledge_graph_from_sources(source_ids=imported_sids, model=kg_model, cfg=cfg)
        rag_delta = {
            "nodes_added": kg_res.get("nodes_after", 0) - kg_res.get("nodes_before", 0),
            "edges_added": kg_res.get("edges_after", 0) - kg_res.get("edges_before", 0),
            "nodes_after": kg_res.get("nodes_after", 0),
            "edges_after": kg_res.get("edges_after", 0),
        }
        append_event(
            project_id,
            "kg-builder",
            "stage3_kg_builder",
            f"NotebookLM 자료 RAG 적재 완료: +{rag_delta['nodes_added']}노드 / +{rag_delta['edges_added']}관계",
            cfg=cfg,
        )

    return {
        "status": "OK",
        "project_id": project_id,
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "imported_count": len(imported_sids),
        "imported_source_ids": imported_sids,
        "imported": imported,
        "notebooklm_dir": str(nlm_dir),
        "total_project_sources": len(existing_sources),
        "rag_ingested": bool(rag_delta),
        "rag_delta": rag_delta,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Google NotebookLM 수집 자료 가져오기 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="NotebookLM CLI 연결·인증 상태 점검")
    p_l = sub.add_parser("list-notebooks", help="내 NotebookLM 노트북 목록 조회")
    p_l.add_argument("--query", default="")
    p_s = sub.add_parser("list-sources", help="특정 노트북의 소스 목록 조회")
    p_s.add_argument("--notebook-id", required=True)
    p_i = sub.add_parser("import", help="선택 소스를 프로젝트 분리 폴더 + RAG로 가져오기")
    p_i.add_argument("--project-id", required=True)
    p_i.add_argument("--notebook-id", required=True)
    p_i.add_argument("--notebook-title", default="")
    p_i.add_argument("--source-ids", required=True, help="쉼표 구분 NotebookLM 소스 UUID")
    p_i.add_argument("--no-rag", action="store_true")

    args = parser.parse_args()
    if args.cmd == "status":
        print(json.dumps(check_nlm_status(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "list-notebooks":
        print(json.dumps(list_notebooks(args.query), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "list-sources":
        print(json.dumps(list_notebook_sources(args.notebook_id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "import":
        sids = [x.strip() for x in args.source_ids.split(",") if x.strip()]
        res = import_notebooklm_sources(
            project_id=args.project_id,
            notebook_id=args.notebook_id,
            notebook_title=args.notebook_title,
            source_ids=sids,
            also_ingest_rag=not args.no_rag,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
