"""결정론적 인용 무결성 및 저작권(원문 복사율) 검증 게이트.

Claude Code Stop 훅(.claude/settings.json) 및 CLI에서 호출:
    .venv\\Scripts\\python.exe scripts\\verify_citations.py content/chapters/

검증 항목:
1. 본문의 모든 [SRC-NN] (또는 [SRC-NN, p.XX]) 인용키가 E:\\SMC_Report_Platform_Data\\evidence\\ 근거 패킷에 실제 존재하는지 확인
2. 출처 원문과 연속 15어절 이상 동일한 무단 복사 문장 탐지 (저작권 공정이용 안전 게이트)
3. 미해결 <!-- NEED_EVIDENCE: ... --> 주석 점검
4. 주요 수치·통계 문장에 인용키가 누락된 경우 경고 출력

종료 코드:
- 0: PASS (치명적 오류 0건)
- 2: FAIL (미등록 인용키 또는 15어절 이상 원문 복사 발견 -> Claude Code Stop 훅 차단)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from config import PlatformConfig, get_config

CITATION_RE = re.compile(r"\[(SRC-\d{2,4})(?:,\s*[^\]]+)?\]")
NEED_EVIDENCE_RE = re.compile(r"<!--\s*NEED_EVIDENCE:\s*(.*?)-->", re.I | re.S)
NUMERIC_CLAIM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|억원|조원|만원|명|건|MW|GW|kWh|톤|ha|mg/kg|ppm|℃)")


def _tokenize_words(text: str) -> list[str]:
    cleaned = re.sub(r"\[SRC-\d{2,4}[^\]]*\]", " ", text)
    cleaned = re.sub(r"[^\w가-힣]+", " ", cleaned).lower()
    return [tok for tok in cleaned.split() if tok]


def _load_evidence_corpus(cfg: PlatformConfig) -> tuple[set[str], dict[str, set[tuple[str, ...]]]]:
    """근거 패킷에서 유효한 source_id 집합과 15어절 n-gram 지문을 로드한다."""
    valid_ids: set[str] = set()
    ngram_index: dict[str, set[tuple[str, ...]]] = {}

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
                if src.get("source_type") == "kg_reuse":
                    continue  # 사용자 자체 C:\SMC_GRAPHRAG 내부 요약은 외부 저작권 원문 복사 대상에서 제외
                corpus_parts: list[str] = []
                for ch in src.get("chunks", []):
                    corpus_parts.append(ch.get("text", ""))
                parsed_p = src.get("parsed_path")
                if parsed_p and Path(parsed_p).is_file():
                    try:
                        corpus_parts.append(Path(parsed_p).read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass
                tokens = _tokenize_words("\n".join(corpus_parts))
                grams: set[tuple[str, ...]] = set()
                if len(tokens) >= 15:
                    for i in range(len(tokens) - 14):
                        grams.add(tuple(tokens[i : i + 15]))
                ngram_index[sid] = grams
    return valid_ids, ngram_index


def audit_file(
    chapter_path: Path,
    valid_ids: set[str],
    ngram_index: dict[str, set[tuple[str, ...]]],
) -> dict[str, Any]:
    text = chapter_path.read_text(encoding="utf-8")
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

    return {
        "file": str(chapter_path),
        "cited_ids": sorted(cited_ids),
        "critical_errors": critical_errors,
        "warnings": warnings,
        "line_refs": sorted(set(line_refs)),
    }


def verify_target(target: Path, strict: bool = False, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    valid_ids, ngram_index = _load_evidence_corpus(cfg)

    if target.is_file():
        files = [target]
    elif target.is_dir():
        if target.resolve() == cfg.projects_dir.resolve():
            # projects/ 루트 대상 시 각 프로젝트의 chapters/ 원고만 정밀 감사 (INDEX.md·가이드 제외)
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

    for f in files:
        res = audit_file(f, valid_ids, ngram_index)
        file_results.append(res)
        all_critical.extend(res["critical_errors"])
        all_warnings.extend(res["warnings"])
        all_line_refs.extend(res["line_refs"])

    need_ev_warnings = [w for w in all_warnings if w.get("type") == "NEED_EVIDENCE_MARKER"]
    failed = bool(all_critical) or (strict and bool(need_ev_warnings))
    return {
        "status": "FAIL" if failed else "PASS",
        "checked_files": len(files),
        "loaded_evidence_sources": sorted(valid_ids),
        "critical_errors": all_critical,
        "warnings": all_warnings,
        "line_refs": sorted(set(all_line_refs)),
        "files": file_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="인용키 무결성 및 15어절 원문 복사 검증 게이트")
    parser.add_argument("target", nargs="?", default="", help="검사 대상 파일 또는 폴더 (미지정 시 활성 프로젝트 chapters 폴더)")
    parser.add_argument("--strict", action="store_true", help="NEED_EVIDENCE 미해결 시에도 FAIL 처리")
    parser.add_argument("--out", type=Path, default=None, help="감사 리포트 JSON 저장 경로")
    args = parser.parse_args()

    cfg = get_config()
    if not args.target:
        target_path = cfg.chapters_dir
    else:
        target_path = Path(args.target)
        if not target_path.is_absolute():
            target_path = cfg.workspace_root / target_path

    report = verify_target(target_path, strict=args.strict, cfg=cfg)
    out_path = args.out or (cfg.reports_dir / "audit_latest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": report["status"],
                "checked_files": report["checked_files"],
                "loaded_evidence_sources": len(report["loaded_evidence_sources"]),
                "critical_error_count": len(report["critical_errors"]),
                "warning_count": len(report["warnings"]),
                "report_path": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
