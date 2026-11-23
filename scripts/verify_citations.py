"""결정론적 인용 형식 무결성 + 내용 일치율(Semantic Alignment) + 표준 수식 오류 검증 게이트 (P15, C6, C7).

Claude Code Stop 훅(.claude/settings.json) 및 CLI에서 호출:
    .venv\\Scripts\\python.exe scripts\\verify_citations.py content/chapters/
    .venv\\Scripts\\python.exe scripts\\verify_citations.py projects/<pid>/chapters/ --semantic

검증 항목:
1. [형식 검사] 본문의 모든 [SRC-NN] 인용키가 근거 패킷에 실제 존재하는지 확인
2. [저작권 검사] 출처 원문과 연속 15어절 이상 동일한 무단 복사 문장 탐지
3. [수식 오류 검사] 알려진 오류 수식 패턴(예: 잘못된 Penman-Monteith, ETc=Kc×E, 평균/최대 CU, 토양수분 함수 CWSI) 탐지
4. [내용 일치 감사 (--semantic)] 인용된 문장마다 출처 원문 조각에 그 내용이 있는지 '지지·부분·무관' 판정 및 무관 비율 산출
5. 미해결 <!-- NEED_EVIDENCE: ... --> 주석 및 수치 문장 인용 누락 점검

주의 (P15):
- 기본 검사는 '형식 검사 PASS/FAIL'로 명기하여 인용 내용 일치 보증과 혼동되지 않도록 한다.
- 내용 일치율과 무관 비율은 `content_audit` 필드에 별도 보고한다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from config import PlatformConfig, get_config
from math_typography import validate_known_formulas

CITATION_RE = re.compile(r"\[(SRC-\d{2,4})(?:,\s*[^\]]+)?\]")
NEED_EVIDENCE_RE = re.compile(r"<!--\s*NEED_EVIDENCE:\s*(.*?)-->", re.I | re.S)
NUMERIC_CLAIM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|억원|조원|만원|명|건|MW|GW|kWh|톤|ha|mg/kg|ppm|℃|kPa|mm/day|mm|L/h)")


def _tokenize_words(text: str) -> list[str]:
    cleaned = re.sub(r"\[SRC-\d{2,4}[^\]]*\]", " ", text)
    cleaned = re.sub(r"[^\w가-힣]+", " ", cleaned).lower()
    return [tok for tok in cleaned.split() if tok]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return (dot / (na * nb)) if (na > 0 and nb > 0) else 0.0


def _load_evidence_corpus(
    cfg: PlatformConfig,
) -> tuple[set[str], dict[str, set[tuple[str, ...]]], dict[str, dict[str, Any]]]:
    """근거 패킷에서 유효한 source_id 집합, 15어절 n-gram 지문, 내용 일치 검사용 출처 텍스트 사전을 로드한다."""
    valid_ids: set[str] = set()
    ngram_index: dict[str, set[tuple[str, ...]]] = {}
    source_docs: dict[str, dict[str, Any]] = {}

    evidence_dirs = [cfg.evidence_dir]
    local_ev = cfg.workspace_root / "data" / "evidence"
    if local_ev.exists() and local_ev.resolve() != cfg.evidence_dir.resolve():
        evidence_dirs.append(local_ev)
    if cfg.e_projects_dir.is_dir():
        for proj_ev in sorted(cfg.e_projects_dir.glob("*/evidence")):
            if proj_ev.is_dir():
                evidence_dirs.append(proj_ev)

    seen_files: set[Path] = set()
    for ev_dir in evidence_dirs:
        if not ev_dir.is_dir():
            continue
        for p in sorted(ev_dir.glob("*.json")):
            rp = p.resolve()
            if rp in seen_files:
                continue
            seen_files.add(rp)
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for src in data.get("sources", []):
                sid = src.get("source_id")
                if not sid:
                    continue
                valid_ids.add(sid)
                corpus_parts: list[str] = []
                title = str(src.get("title") or "").strip()
                if title:
                    corpus_parts.append(title)
                for ch in src.get("chunks", []):
                    t = str(ch.get("text") or "").strip()
                    if t:
                        corpus_parts.append(t)
                parsed_p = src.get("parsed_path")
                if parsed_p and Path(parsed_p).is_file():
                    try:
                        corpus_parts.append(Path(parsed_p).read_text(encoding="utf-8", errors="ignore")[:18000])
                    except Exception:
                        pass
                full_text = "\n".join(corpus_parts)
                if sid not in source_docs or len(full_text) > len(source_docs[sid].get("text", "")):
                    source_docs[sid] = {
                        "source_id": sid,
                        "title": title,
                        "url": str(src.get("url") or ""),
                        "citable": src.get("citable", True),
                        "is_anchor": bool(src.get("is_anchor", False)),
                        "text": full_text[:20000],
                        "tokens": set(t for t in _tokenize_words(full_text[:12000]) if len(t) >= 2),
                    }
                if src.get("source_type") == "kg_reuse":
                    continue
                tokens = _tokenize_words(full_text)
                grams: set[tuple[str, ...]] = set()
                if len(tokens) >= 15:
                    for i in range(len(tokens) - 14):
                        grams.add(tuple(tokens[i : i + 15]))
                ngram_index[sid] = grams
    return valid_ids, ngram_index, source_docs


def _evaluate_citation_alignment(
    chapter_path: Path,
    body_text: str,
    source_docs: dict[str, dict[str, Any]],
    *,
    use_embeddings: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """인용된 문장마다 출처 원문 조각과의 내용 일치 여부를 '지지·부분·무관'으로 판정한다 (C6)."""
    lines = body_text.splitlines()
    claims: list[tuple[int, str, str]] = []
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "|", "```", "<!--", "---")):
            continue
        if not CITATION_RE.search(line):
            continue
        # 문단 내 개별 문장 단위로 분리해 각 문장에 부착된 [SRC-NN]만 해당 문장과 대조 (C6 정밀화)
        sentences = re.split(r"(?<=\])\s*(?:\.\s*|\s+)|(?<=[.!?])\s+(?=[가-힣A-Za-z0-9\*])", line)
        for seg in sentences:
            sids = CITATION_RE.findall(seg)
            if not sids:
                continue
            clean_sent = re.sub(r"\[SRC-\d{2,4}[^\]]*\]", "", seg).strip()
            if len(clean_sent) < 12:
                continue
            for sid in dict.fromkeys(sids):
                claims.append((lineno, clean_sent[:380], sid))

    if not claims:
        return {
            "checked_claims": 0,
            "supported": 0,
            "partial": 0,
            "unrelated": 0,
            "alignment_rate_pct": 100.0,
            "unrelated_ratio_pct": 0.0,
            "method": "none",
            "details": [],
        }

    # 임베딩 가능 시 bge-m3 배치 유사도 계산
    sent_vecs: list[list[float]] = []
    src_vecs: dict[str, list[float]] = {}
    method = "lexical"
    if use_embeddings and cfg is not None:
        try:
            from local_gemma import LocalGemmaClient

            client = LocalGemmaClient(cfg)
            unique_sids = sorted({sid for _, _, sid in claims if sid in source_docs})
            src_texts = [
                f"{source_docs[sid]['title']}\n{source_docs[sid]['text'][:1400]}".strip()
                for sid in unique_sids
            ]
            if src_texts:
                s_embs = client.embed(src_texts, timeout=60)
                src_vecs = dict(zip(unique_sids, s_embs))
                c_embs = client.embed([c[1] for c in claims], timeout=60)
                sent_vecs = c_embs
                method = "bge-m3+lexical"
        except Exception:
            sent_vecs = []
            src_vecs = {}

    supported = 0
    partial = 0
    unrelated = 0
    details: list[dict[str, Any]] = []

    for idx, (lineno, sent, sid) in enumerate(claims):
        sdoc = source_docs.get(sid)
        if not sdoc:
            unrelated += 1
            details.append({"line": lineno, "source_id": sid, "verdict": "무관", "score": 0.0, "reason": "출처 원문 없음", "snippet": sent[:110]})
            continue

        # 포털 첫 화면 등 비인용 자료인 경우 경고성 무관 감점
        is_non_citable = sdoc.get("citable") is False
        sent_toks = set(t for t in _tokenize_words(sent) if len(t) >= 2)
        src_toks = sdoc.get("tokens") or set()
        overlap = len(sent_toks & src_toks) / max(1, min(len(sent_toks), 12))

        cos = 0.0
        if sent_vecs and idx < len(sent_vecs) and sid in src_vecs:
            cos = _cosine_sim(sent_vecs[idx], src_vecs[sid])
            # 교차 언어(한글 문장 -> 영문 SCI 논문 초록) 인용 시 어휘 중복 부족으로 불이익 받지 않도록 bge-m3 유사도를 하한 보장
            combined = max(cos, 0.78 * cos + 0.22 * min(1.0, overlap * 1.5))
        else:
            combined = min(1.0, overlap * 1.45)

        if is_non_citable:
            combined *= 0.55

        if method == "bge-m3+lexical":
            if combined >= 0.48:
                verdict = "지지"
                supported += 1
            elif combined >= 0.36:
                verdict = "부분"
                partial += 1
            else:
                verdict = "무관"
                unrelated += 1
        else:
            if combined >= 0.30:
                verdict = "지지"
                supported += 1
            elif combined >= 0.14:
                verdict = "부분"
                partial += 1
            else:
                verdict = "무관"
                unrelated += 1

        details.append(
            {
                "line": lineno,
                "source_id": sid,
                "source_title": sdoc.get("title", "")[:80],
                "verdict": verdict,
                "score": round(combined, 3),
                "cos_sim": round(cos, 3),
                "lexical_overlap": round(overlap, 3),
                "snippet": sent[:110],
            }
        )

    total_c = len(claims)
    align_pct = round(((supported + 0.5 * partial) / max(1, total_c)) * 100.0, 1)
    unrel_pct = round((unrelated / max(1, total_c)) * 100.0, 1)
    return {
        "checked_claims": total_c,
        "supported": supported,
        "partial": partial,
        "unrelated": unrelated,
        "alignment_rate_pct": align_pct,
        "unrelated_ratio_pct": unrel_pct,
        "method": method,
        "details": details[:60],
    }


def audit_file(
    chapter_path: Path,
    valid_ids: set[str],
    ngram_index: dict[str, set[tuple[str, ...]]],
    *,
    source_docs: dict[str, dict[str, Any]] | None = None,
    semantic: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    text = chapter_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    critical_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    line_refs: list[int] = []
    cited_ids: set[str] = set()

    # 1. 인용키 존재 검증 & 수치 누락 경고
    for lineno, line in enumerate(lines, start=1):
        matches = CITATION_RE.findall(line)
        for sid in matches:
            cited_ids.add(sid)
            if sid not in valid_ids:
                critical_errors.append(
                    {
                        "type": "MISSING_SOURCE_ID",
                        "file": str(chapter_path),
                        "line": lineno,
                        "source_id": sid,
                        "message": f"미등록 인용키 [{sid}]가 근거 패킷에 존재하지 않습니다.",
                    }
                )
                line_refs.append(lineno)

        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith(("#", "|", "```", "<!--", "---"))
            and NUMERIC_CLAIM_RE.search(stripped)
            and not matches
        ):
            warnings.append(
                {
                    "type": "UNCITED_NUMERIC_CLAIM",
                    "file": str(chapter_path),
                    "line": lineno,
                    "snippet": stripped[:100],
                    "message": "수치·통계 표현이 포함된 줄에 [SRC-NN] 인용키가 없습니다.",
                }
            )

        for m in NEED_EVIDENCE_RE.finditer(line):
            warnings.append(
                {
                    "type": "NEED_EVIDENCE_MARKER",
                    "file": str(chapter_path),
                    "line": lineno,
                    "detail": m.group(1).strip(),
                    "message": "미충족 근거 주석이 남아 있습니다.",
                }
            )

    # 2. 15어절 연속 원문 복사(표절·저작권 위험) 검사 (참고문헌 목록 섹션은 정식 논문 제목 표기이므로 제외)
    body_for_copy_check = re.split(r"(?m)^##\s*참고문헌", text, maxsplit=1)[0]
    chapter_tokens = _tokenize_words(body_for_copy_check)
    if len(chapter_tokens) >= 15 and ngram_index:
        seen_overlap_sources: set[str] = set()
        for i in range(len(chapter_tokens) - 14):
            gram = tuple(chapter_tokens[i : i + 15])
            for sid, src_grams in ngram_index.items():
                if sid in seen_overlap_sources:
                    continue
                if gram in src_grams:
                    seen_overlap_sources.add(sid)
                    critical_errors.append(
                        {
                            "type": "VERBATIM_COPY_15_WORDS",
                            "file": str(chapter_path),
                            "source_id": sid,
                            "excerpt": " ".join(gram),
                            "message": f"[{sid}] 출처 원문과 연속 15어절 이상 동일한 문장이 발견되었습니다.",
                        }
                    )

    # 3. 검증 표준 수식 라이브러리 기반 오류 수식 탐지 (C7, P2~P5)
    formula_issues = validate_known_formulas(body_for_copy_check)
    for fi in formula_issues:
        critical_errors.append({**fi, "file": str(chapter_path)})
        line_refs.append(int(fi.get("line") or 0))

    # 4. 내용 일치 감사 (C6)
    content_audit: dict[str, Any] | None = None
    if semantic and source_docs is not None:
        content_audit = _evaluate_citation_alignment(
            chapter_path,
            body_for_copy_check,
            source_docs,
            use_embeddings=True,
            cfg=cfg,
        )
        if content_audit["unrelated"] > 0:
            warnings.append(
                {
                    "type": "UNRELATED_CITATION_DETECTED",
                    "file": str(chapter_path),
                    "unrelated_count": content_audit["unrelated"],
                    "unrelated_ratio_pct": content_audit["unrelated_ratio_pct"],
                    "message": (
                        f"인용 내용 일치 검사에서 출처와 무관한 인용 {content_audit['unrelated']}건"
                        f"({content_audit['unrelated_ratio_pct']}%)이 탐지되었습니다."
                    ),
                }
            )

    return {
        "file": str(chapter_path),
        "cited_ids": sorted(cited_ids),
        "critical_errors": critical_errors,
        "warnings": warnings,
        "formula_errors": formula_issues,
        "content_audit": content_audit,
        "line_refs": sorted(set(x for x in line_refs if x > 0)),
    }


def verify_target(
    target: Path,
    strict: bool = False,
    semantic: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    valid_ids, ngram_index, source_docs = _load_evidence_corpus(cfg)

    if target.is_file():
        files = [target]
    elif target.is_dir():
        if target.resolve() == cfg.projects_dir.resolve():
            files = sorted(
                p
                for ch_dir in sorted(target.glob("*/chapters"))
                if ch_dir.is_dir()
                for p in ch_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in (".md", ".mdx", ".qmd")
            )
        else:
            files = sorted(
                p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".mdx", ".qmd")
            )
    else:
        files = []

    all_critical: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    all_line_refs: list[int] = []
    file_results: list[dict[str, Any]] = []
    tot_claims = 0
    tot_sup = 0
    tot_part = 0
    tot_unrel = 0

    for f in files:
        res = audit_file(
            f,
            valid_ids,
            ngram_index,
            source_docs=source_docs if semantic else None,
            semantic=semantic,
            cfg=cfg,
        )
        file_results.append(res)
        all_critical.extend(res["critical_errors"])
        all_warnings.extend(res["warnings"])
        all_line_refs.extend(res["line_refs"])
        ca = res.get("content_audit")
        if ca:
            tot_claims += ca["checked_claims"]
            tot_sup += ca["supported"]
            tot_part += ca["partial"]
            tot_unrel += ca["unrelated"]

    need_ev_warnings = [w for w in all_warnings if w.get("type") == "NEED_EVIDENCE_MARKER"]
    failed = bool(all_critical) or (strict and bool(need_ev_warnings))
    status = "FAIL" if failed else "PASS"
    format_label = "형식 검사 FAIL" if failed else "형식 검사 PASS"

    content_summary: dict[str, Any] | None = None
    if semantic:
        content_summary = {
            "checked_claims": tot_claims,
            "supported": tot_sup,
            "partial": tot_part,
            "unrelated": tot_unrel,
            "alignment_rate_pct": round(((tot_sup + 0.5 * tot_part) / max(1, tot_claims)) * 100.0, 1) if tot_claims else 100.0,
            "unrelated_ratio_pct": round((tot_unrel / max(1, tot_claims)) * 100.0, 1) if tot_claims else 0.0,
        }

    return {
        "status": status,
        "format_check_status": format_label,
        "display_status": format_label,
        "checked_files": len(files),
        "loaded_evidence_sources": sorted(valid_ids),
        "critical_errors": all_critical,
        "warnings": all_warnings,
        "content_audit": content_summary,
        "line_refs": sorted(set(all_line_refs)),
        "files": file_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="인용 형식 무결성 · 표준 수식 오류 · 내용 일치율 검증 게이트")
    parser.add_argument("target", nargs="?", default="", help="검사 대상 파일 또는 폴더 (미지정 시 활성 프로젝트 chapters 폴더)")
    parser.add_argument("--strict", action="store_true", help="NEED_EVIDENCE 미해결 시에도 FAIL 처리")
    parser.add_argument("--semantic", action="store_true", help="인용 문장-출처 내용 일치율(지지/부분/무관) 감사 포함")
    parser.add_argument("--out", type=Path, default=None, help="감사 리포트 JSON 저장 경로")
    args = parser.parse_args()

    cfg = get_config()
    if not args.target:
        target_path = cfg.chapters_dir
    else:
        target_path = Path(args.target)
        if not target_path.is_absolute():
            target_path = cfg.workspace_root / target_path

    report = verify_target(target_path, strict=args.strict, semantic=args.semantic, cfg=cfg)
    out_path = args.out or (cfg.reports_dir / "audit_latest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": report["status"],
                "format_check_status": report["format_check_status"],
                "checked_files": report["checked_files"],
                "loaded_evidence_sources": len(report["loaded_evidence_sources"]),
                "critical_error_count": len(report["critical_errors"]),
                "warning_count": len(report["warnings"]),
                "content_audit": report.get("content_audit"),
                "report_path": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
