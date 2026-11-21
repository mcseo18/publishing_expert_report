"""컴플라이언스·보안·한국어 청킹·중복 제거 공용 모듈.

기능:
- URL 정규화 및 SHA-256 해시
- robots.txt 사전 점검 (RFC 9309)
- 개인정보(PII: 주민번호·전화번호·이메일·카드번호) 자동 마스킹
- 웹 프롬프트 인젝션 의심 패턴 탐지
- 한국어 문맥 보존 청킹 (300~500자, 오버랩 50~100자, kss 지원 + 폴백)
- 도메인 용어집(schemas/glossary.json) 기반 엔티티 표기 정규화
- sources.jsonl 레지스트리(중복 차단 및 SRC-NN 번호 자동 채번)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import robotparser
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

USER_AGENT = "SMCReportPlatformBot/1.0 (+local-research)"

# 추적 쿼리 파라미터 제거 목록
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}

# 개인정보(PII) 탐지 정규식
_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "RRN",
        re.compile(r"\b\d{6}\s*-\s*[1-8]\d{6}\b"),
        "[REDACTED_RRN]",
    ),
    (
        "MOBILE",
        re.compile(r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b"),
        "[REDACTED_PHONE]",
    ),
    (
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "CARD",
        re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"),
        "[REDACTED_CARD]",
    ),
]

# 웹/문서 본문 프롬프트 인젝션 의심 패턴
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions_en", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("ignore_instructions_ko", re.compile(r"(이전|기존|위의)\s*(지시|명령|규칙).{0,15}(무시|잊어)")),
    ("env_exfil", re.compile(r"(\.env\b|api[_\s-]?key|secret[_\s-]?key).{0,40}(read|print|send|exfiltrate|읽어|출력|전송)", re.I)),
    ("shell_exec", re.compile(r"(curl|wget|powershell|bash).{0,40}(\|\s*sh|iex|rm\s+-rf)", re.I)),
    ("system_override", re.compile(r"(you\s+are\s+now\s+a|new\s+system\s+prompt|jailbreak)", re.I)),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query_pairs.sort()
    path = parsed.path or "/"
    return urlunparse((scheme, netloc, path, "", urlencode(query_pairs), ""))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def check_robots_txt(url: str, user_agent: str = USER_AGENT, timeout: int = 10) -> tuple[bool, str]:
    """대상 URL의 robots.txt 허용 여부를 사전 점검한다."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return True, "local_or_non_http"
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        resp = requests.get(
            robots_url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
        )
        if resp.status_code == 404:
            return True, f"robots_not_found_404 ({robots_url})"
        if resp.status_code >= 500:
            return False, f"robots_server_error_{resp.status_code} ({robots_url})"
        if resp.status_code in (401, 403):
            return False, f"robots_access_restricted_{resp.status_code} ({robots_url})"
        rp.parse(resp.text.splitlines())
        allowed = rp.can_fetch(user_agent, url) and rp.can_fetch("*", url)
        status = "allowed" if allowed else "disallowed_by_robots"
        return allowed, f"{status} ({robots_url})"
    except requests.RequestException as exc:
        return True, f"robots_unreachable_warn: {exc}"


def mask_pii(text: str) -> tuple[str, int]:
    """한국어/일반 개인정보 패턴을 자동 마스킹하고 치환 건수를 반환한다."""
    masked = text
    total = 0
    for _, pattern, replacement in _PII_PATTERNS:
        masked, count = pattern.subn(replacement, masked)
        total += count
    return masked, total


def detect_prompt_injection(text: str) -> list[str]:
    """수집 원문 내 프롬프트 인젝션 의심 문구를 탐지해 경고 목록을 반환한다."""
    warnings: list[str] = []
    for name, pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            snippet = match.group(0)[:100].replace("\n", " ")
            warnings.append(f"{name}: {snippet}")
    return warnings


def normalize_entities_with_glossary(text: str, glossary_path: Path) -> str:
    """도메인 용어집에 따라 약어·동의어를 대표 표기로 통일한다 (한국어 조사 결합 지원)."""
    if not glossary_path.is_file():
        return text
    data = json.loads(glossary_path.read_text(encoding="utf-8"))
    synonyms: dict[str, str] = data.get("synonyms", {})
    normalized = text
    # 긴 표현부터 치환하여 부분 충돌 방지
    for src in sorted(synonyms.keys(), key=len, reverse=True):
        dst = synonyms[src]
        if src == dst or dst in src:
            continue
        # 먼저 이미 대표 표기로 쓰인 부분을 임시 토큰으로 보호
        placeholder = f"__GLOSS_{abs(hash(dst)) % 1000000}__"
        normalized = normalized.replace(dst, placeholder)
        if src.isascii():
            # 영문 약어(ESS, EC 등): 앞뒤 영문·숫자만 경계로 삼아 'ESS와', 'ESS의' 허용
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(src)}(?![A-Za-z0-9_])")
        else:
            # 한국어 용어(스마트팜, 피노믹스 등): 뒤에 조사(은/는/이/가/의/와 등) 허용
            pattern = re.compile(rf"(?<![가-힣A-Za-z0-9_]){re.escape(src)}")
        normalized = pattern.sub(dst, normalized)
        normalized = normalized.replace(placeholder, dst)
    return normalized


def _split_sentences_korean(paragraph: str) -> list[str]:
    """한국어 비중이 높은 짧은 문단에는 kss를 사용하고, 영문·장문에는 고속 정규식 분할을 사용한다."""
    stripped = paragraph.strip()
    if not stripped:
        return []
    hangul_count = sum(1 for ch in stripped if "\uac00" <= ch <= "\ud7a3")
    hangul_ratio = hangul_count / max(len(stripped), 1)
    if hangul_ratio >= 0.25 and len(stripped) <= 2000:
        try:
            import kss  # type: ignore

            sents = kss.split_sentences(stripped)
            return [s.strip() for s in sents if s.strip()]
        except Exception:
            pass
    # 고속 폴백: 한국어/영문 문장 경계 분할
    parts = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", stripped)
    return [p.strip() for p in parts if p.strip()]


def chunk_korean_text(
    text: str,
    target_chars: int = 450,
    overlap_chars: int = 80,
    default_section: str = "본문",
) -> list[dict[str, Any]]:
    """한국어 문맥을 보존하며 300~500자(오버랩 50~100자) 단위로 청킹한다.

    마크다운 헤딩(#, ##, ###)과 페이지 주석(<!-- page: N -->)을 추적해 각 청크의
    page_or_section 메타데이터를 자동 부착한다.
    """
    chunks: list[dict[str, Any]] = []
    current_heading = default_section
    current_page: str | None = None
    buffer = ""

    def _section_label() -> str:
        if current_page and current_heading and current_heading != default_section:
            return f"{current_page} / {current_heading}"
        if current_page:
            return current_page
        return current_heading

    def _flush() -> None:
        nonlocal buffer
        cleaned = buffer.strip()
        if not cleaned:
            buffer = ""
            return
        chunks.append(
            {
                "chunk_id": f"c{len(chunks) + 1:04d}",
                "text": cleaned,
                "page_or_section": _section_label(),
                "char_count": len(cleaned),
            }
        )
        if overlap_chars > 0 and len(cleaned) > overlap_chars:
            buffer = cleaned[-overlap_chars:].lstrip()
        else:
            buffer = ""

    page_marker_re = re.compile(r"<!--\s*page:\s*([0-9A-Za-z\-]+)\s*-->", re.I)

    for raw_block in re.split(r"\n{2,}", text):
        block = raw_block.strip()
        if not block:
            continue
        page_m = page_marker_re.search(block)
        if page_m:
            if buffer.strip():
                _flush()
                buffer = ""
            current_page = f"p.{page_m.group(1)}"
            block = page_marker_re.sub("", block).strip()
            if not block:
                continue

        if block.startswith("#"):
            if buffer.strip():
                _flush()
                buffer = ""
            current_heading = block.lstrip("#").strip()[:80] or default_section
            buffer = f"{block}\n"
            continue

        sentences = _split_sentences_korean(block)
        for sent in sentences:
            if len(buffer) + len(sent) + 1 <= target_chars:
                buffer = f"{buffer} {sent}".strip() if buffer else sent
            else:
                if buffer.strip():
                    _flush()
                if len(sent) > target_chars:
                    # 단일 문장이 매우 긴 경우 슬라이딩 분할
                    step = max(target_chars - overlap_chars, 100)
                    for start in range(0, len(sent), step):
                        piece = sent[start : start + target_chars].strip()
                        if piece:
                            chunks.append(
                                {
                                    "chunk_id": f"c{len(chunks) + 1:04d}",
                                    "text": piece,
                                    "page_or_section": _section_label(),
                                    "char_count": len(piece),
                                }
                            )
                    buffer = ""
                else:
                    buffer = f"{buffer} {sent}".strip() if buffer else sent

    if buffer.strip():
        _flush()
    return chunks


class SourcesRegistry:
    """E:\\SMC_Report_Platform_Data\\index\\sources.jsonl 기반 중복 제거 및 SRC-NN 채번기."""

    def __init__(self, registry_path: Path):
        self.path = registry_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        self._records.clear()
        if not self.path.is_file():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def find_duplicate(self, url: str | None = None, content_sha256: str | None = None) -> dict[str, Any] | None:
        norm = normalize_url(url) if url and url.startswith(("http://", "https://")) else url
        for rec in self._records:
            if content_sha256 and rec.get("sha256") == content_sha256:
                return rec
            if norm and rec.get("normalized_url") == norm:
                return rec
        return None

    def next_source_id(self) -> str:
        max_num = 0
        for rec in self._records:
            sid = str(rec.get("source_id", ""))
            m = re.match(r"^SRC-(\d+)$", sid)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"SRC-{max_num + 1:02d}"

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._records.append(record)


def slugify(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^\w가-힣\-]+", "_", text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned or "source")[:max_len]


def validate_evidence_packet(packet: dict[str, Any], schema_path: Path) -> list[str]:
    """evidence_packet.schema.json으로 패킷을 검증하고 오류 메시지 목록을 반환한다."""
    try:
        import jsonschema
    except ImportError:
        return []
    if not schema_path.is_file():
        return [f"Schema not found: {schema_path}"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{list(err.path)}: {err.message}" for err in validator.iter_errors(packet)]


def upsert_evidence_packet(
    packet_path: Path,
    source_item: dict[str, Any],
    packet_id: str,
    topic: str,
    storage_root: str,
    kg_store_root: str,
    schema_path: Path,
) -> dict[str, Any]:
    """기존 근거 패킷에 source_item을 추가/갱신하고 스키마 검증 후 저장한다."""
    now = utc_now_iso()
    if packet_path.is_file():
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    else:
        packet = {
            "packet_id": packet_id,
            "topic": topic,
            "created_at": now,
            "updated_at": now,
            "storage_root": storage_root,
            "kg_store_root": kg_store_root,
            "sources": [],
        }

    packet["updated_at"] = now
    if topic:
        packet["topic"] = topic
    sources: list[dict[str, Any]] = packet.setdefault("sources", [])
    replaced = False
    for idx, existing in enumerate(sources):
        if existing.get("source_id") == source_item.get("source_id") or existing.get("sha256") == source_item.get("sha256"):
            sources[idx] = source_item
            replaced = True
            break
    if not replaced:
        sources.append(source_item)

    errors = validate_evidence_packet(packet, schema_path)
    if errors:
        raise ValueError("Evidence packet schema validation failed:\n" + "\n".join(errors))

    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    return packet
