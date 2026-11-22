"""대화형 다회차 심층 자료 조사 & 프로젝트 분리 폴더 누적 추가 엔진.

지원 검색 소스 (기본 전체 연동, 대화 턴별 선택 가능):
1. local_rag       : 내 컴퓨터 C:\\SMC_GRAPHRAG (46만+ 노드 SQLite 카탈로그 + LightRAG 서버)
2. scholar_intl    : 국제 SCI·오픈액세스 학술 문헌 (OpenAlex 정밀 검색)
3. scholar_kr      : 국내 학회지(Crossref) + 한국 대학·연구소 논문(OpenAlex KR)
4. agencies_kr     : 농촌진흥청(RDA)·한국식품연구원·농식품부·식약처·국립식량과학원·KREI 등 국내 관계기관
5. agencies_global : 미국(USDA ARS·UF/IFAS·US 대학), 일본(NARO·MAFF·JP 대학), 유럽(FAO·Codex·EU 대학·기관)
6. statistics_api  : World Bank Open Data API + UN FAO FLW 통계 + KOSIS API(환경변수 설정 시)
7. 직접 추가       : 사용자 URL 직접 수집(robots.txt 준수) 및 Google Scholar/RISS/KCI BibTeX 즉시 임포트

선택된 검색 결과는 프로젝트 전용 분리 폴더(E:\\SMC_Report_Platform_Data\\projects\\<pid>\\collected\\)와
근거 패킷에 누적 저장되며, 원할 경우 즉시 C:\\SMC_GRAPHRAG 증분 지식그래프에 반영된다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from compliance import (
    USER_AGENT,
    SourcesRegistry,
    chunk_korean_text,
    mask_pii,
    sha256_text,
    slugify,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config
from fetch_clean import fetch_and_clean_url
from fetch_project_sources import (
    DOMAIN_PRESETS,
    TIER_DIRS,
    TIER_LABELS_KO,
    _copy_source_files_to_tier,
    _ensure_duplicate_in_packet,
    _write_collection_index_md,
    detect_domain_preset,
)
from fetch_scholar import (
    ingest_paper_record,
    parse_bibtex_entries,
    search_crossref_korean_society,
    search_openalex_papers,
)
from smc_kg_bridge import _check_lightrag_server, _query_lightrag_server, _query_smc_catalog

_CHAT_LOCK = threading.Lock()

# World Bank 공개 농업·식품·기후 통계 지표 (무인증 REST API)
WORLD_BANK_AGRI_INDICATORS: list[dict[str, str]] = [
    {"code": "AG.PRD.FOOD.XD", "name_ko": "식량 생산 지수 (Food production index, 2014-2016=100)", "tags": "식량 수확 농산물 생산 postharvest food harvest crop"},
    {"code": "AG.PRD.CROP.XD", "name_ko": "작물 생산 지수 (Crop production index, 2014-2016=100)", "tags": "작물 원예 수확 crop fruit vegetable harvest"},
    {"code": "AG.YLD.CREL.KG", "name_ko": "곡물 단위면적당 수량 (Cereal yield, kg/ha)", "tags": "수량 곡물 쌀 밀 토양 비료 yield soil cereal"},
    {"code": "NV.AGR.TOTL.ZS", "name_ko": "농림어업 GDP 비중 (Agriculture, forestry, and fishing value added, % of GDP)", "tags": "농업 경제 유통 통계 GDP agriculture policy"},
    {"code": "AG.LND.AGRI.ZS", "name_ko": "국토 대비 농경지 비율 (Agricultural land, % of land area)", "tags": "농경지 토양 토지 land soil"},
    {"code": "AG.CON.FERT.ZS", "name_ko": "경지당 비료 소비량 (Fertilizer consumption, kg/ha)", "tags": "비료 토양 유기물 양분 fertilizer soil nutrient"},
]

WB_COUNTRIES = [("KOR", "대한민국"), ("USA", "미국"), ("JPN", "일본"), ("DEU", "독일(EU)"), ("NLD", "네덜란드(EU)")]


def _chat_path(project_id: str, cfg: PlatformConfig) -> Path:
    d = cfg.index_dir / "subagent_runs" / re.sub(r"[^a-zA-Z0-9_\-]", "_", project_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "research_chat.jsonl"


def load_research_chat(project_id: str, limit: int = 40, cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    cfg = cfg or get_config()
    p = _chat_path(project_id, cfg)
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def append_research_chat(project_id: str, entry: dict[str, Any], cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    p = _chat_path(project_id, cfg)
    with _CHAT_LOCK:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _decompose_query(
    message: str,
    topic_ko: str,
    topic_en: str,
    keywords_ko: list[str],
    keywords_en: list[str],
    cfg: PlatformConfig,
) -> dict[str, Any]:
    """사용자 자연어 조사 질의를 국문/영문 세부 검색어와 지역 쿼리로 분해한다."""
    # 로컬 Ollama Gemma 4(고속)로 1차 시도, 바쁘거나 실패 시 결정론적 키워드 추출 폴백
    schema = {
        "type": "object",
        "properties": {
            "ko_terms": {"type": "array", "items": {"type": "string"}},
            "en_queries": {"type": "array", "items": {"type": "string"}},
            "focus_summary_ko": {"type": "string"},
        },
        "required": ["ko_terms", "en_queries", "focus_summary_ko"],
    }
    try:
        from local_gemma import LocalGemmaClient

        client = LocalGemmaClient(cfg)
        prompt = (
            f"교재 주제: {topic_ko} ({topic_en})\n"
            f"사용자 추가 조사 요청: {message}\n\n"
            "위 요청을 심층 검색하기 위해:\n"
            "1. ko_terms: 로컬 RAG·국내 기관 검색용 한국어 핵심 용어 3~6개\n"
            "2. en_queries: 국제 SCI·미국/일본/유럽 대학·기관 학술 검색용 정밀 영문 쿼리 2개 (반드시 해당 농학/식품/수확후 전문어 포함)\n"
            "3. focus_summary_ko: 이번 라운드 탐색 전략 한 줄 한국어 요약\n"
            "순수 JSON으로만 출력하세요."
        )
        res = client.chat_structured(
            messages=[
                {"role": "system", "content": "당신은 농학·생명과학 전문 문헌정보 사서입니다."},
                {"role": "user", "content": prompt},
            ],
            schema=schema,
            model=cfg.ollama_fast_model,
            num_ctx=4096,
            num_predict=512,
            max_retries=1,
            timeout=25,
        )
        ko_t = [x.strip() for x in res.get("ko_terms", []) if x.strip()][:6]
        en_q = [x.strip() for x in res.get("en_queries", []) if x.strip()][:2]
        if ko_t or en_q:
            return {
                "ko_terms": ko_t or keywords_ko[:5],
                "en_queries": en_q or [f"{topic_en} {message}"],
                "focus_summary_ko": res.get("focus_summary_ko") or f"'{message}' 기반 국내외 다중 소스 심층 탐색",
                "decomposer": cfg.ollama_fast_model,
            }
    except Exception:
        pass

    # 결정론적 폴백
    ko_tokens = re.findall(r"[가-힣A-Za-z0-9\-]{2,}", message)
    ko_terms = list(dict.fromkeys([t for t in ko_tokens if len(t) >= 2][:5] + keywords_ko[:3]))[:6]
    en_tokens = re.findall(r"[A-Za-z0-9\-]{3,}", message)
    base_en = " ".join(en_tokens[:5]) if en_tokens else " ".join(keywords_en[:4])
    en_q1 = f"{base_en} {topic_en}".strip() if topic_en and topic_en.lower() not in base_en.lower() else base_en
    en_queries = [en_q1 or topic_en or message]
    return {
        "ko_terms": ko_terms or [topic_ko],
        "en_queries": en_queries,
        "focus_summary_ko": f"'{message}' 요청에 대해 로컬 RAG·국내외 학술·관계기관·통계 API를 교차 탐색합니다.",
        "decomposer": "rule_fallback",
    }


def _search_openalex_by_region(query: str, country_codes: str, limit: int = 4) -> list[dict[str, Any]]:
    """OpenAlex 지역별 대학·연구기관 검색 (503 장애 시 Europe PMC/Crossref 지역 폴백 자동 동작)."""
    from fetch_scholar import _polite_mailto, search_crossref_general, search_europepmc_papers

    params = {
        "search": query,
        "filter": f"authorships.institutions.country_code:{country_codes}",
        "per-page": min(max(limit, 1), 15),
        "sort": "relevance_score:desc",
        "mailto": _polite_mailto(),
    }
    try:
        resp = requests.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": f"{USER_AGENT} (mailto:{_polite_mailto()})"},
            timeout=14,
        )
        resp.raise_for_status()
    except Exception:
        aff_map = {"KR": "Korea", "US": "USA", "JP": "Japan"}
        aff = aff_map.get(country_codes, "Netherlands OR Germany OR France OR United Kingdom")
        try:
            ep = search_europepmc_papers(query=query, limit=limit, affiliation_hint=aff)
            if ep:
                return [{**p, "institutions": [aff], "provider": "Europe PMC (OpenAlex 자동대체)"} for p in ep]
        except Exception:
            pass
        return [{**p, "institutions": [aff], "provider": "Crossref (OpenAlex 자동대체)"} for p in search_crossref_general(f"{query} {aff.split()[0]}", limit=limit)]
    out: list[dict[str, Any]] = []
    for w in resp.json().get("results", []):
        primary = w.get("primary_location") or {}
        src = primary.get("source") or {}
        best_oa = w.get("best_oa_location") or {}
        authors = [(a.get("author") or {}).get("display_name", "") for a in (w.get("authorships") or [])[:5]]
        insts = []
        for a in (w.get("authorships") or [])[:4]:
            for inst in (a.get("institutions") or [])[:2]:
                nm = inst.get("display_name")
                cc = inst.get("country_code")
                if nm:
                    insts.append(f"{nm}({cc})" if cc else nm)
        insts = list(dict.fromkeys(insts))[:3]
        inv = w.get("abstract_inverted_index") or {}
        pos_map = {p: word for word, positions in inv.items() for p in positions} if isinstance(inv, dict) else {}
        abstract = " ".join(pos_map[i] for i in sorted(pos_map.keys())) if pos_map else ""
        doi = w.get("doi") or ""
        landing = best_oa.get("landing_page_url") or primary.get("landing_page_url") or doi or w.get("id", "")
        pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
        out.append(
            {
                "id": w.get("id", ""),
                "title": w.get("display_name") or w.get("title") or "",
                "authors": [a for a in authors if a],
                "institutions": insts,
                "year": w.get("publication_year"),
                "journal": src.get("display_name") or "국제 대학·연구기관 문헌",
                "doi": doi,
                "url": landing,
                "pdf_url": pdf_url,
                "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
                "cited_by_count": int(w.get("cited_by_count") or 0),
                "abstract": abstract,
                "provider": "OpenAlex",
            }
        )
    return out


def _fetch_world_bank_statistics(query_blob: str, max_indicators: int = 2) -> list[dict[str, Any]]:
    """World Bank Open Data API에서 한국·미국·일본·유럽 최신 농업·식량 공식 통계를 조회한다."""
    q_low = query_blob.lower()
    scored = []
    for ind in WORLD_BANK_AGRI_INDICATORS:
        sc = sum(1 for tok in ind["tags"].split() if tok.lower() in q_low)
        scored.append((sc, ind))
    scored.sort(key=lambda x: x[0], reverse=True)
    chosen = [x[1] for x in scored[:max_indicators]]

    country_str = ";".join(c[0] for c in WB_COUNTRIES)
    name_map = dict(WB_COUNTRIES)
    results: list[dict[str, Any]] = []

    for ind in chosen:
        code = ind["code"]
        url = f"https://api.worldbank.org/v2/country/{country_str}/indicator/{code}"
        try:
            r = requests.get(
                url,
                params={"format": "json", "per_page": 60, "date": "2018:2025"},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
                continue
            latest_by_country: dict[str, dict[str, Any]] = {}
            for row in payload[1]:
                val = row.get("value")
                iso3 = row.get("countryiso3code") or ""
                yr = row.get("date") or ""
                if val is None or iso3 not in name_map:
                    continue
                if iso3 not in latest_by_country or yr > latest_by_country[iso3]["year"]:
                    latest_by_country[iso3] = {"country": name_map[iso3], "iso3": iso3, "year": yr, "value": round(float(val), 2)}
            if not latest_by_country:
                continue
            rows_sorted = [latest_by_country[c[0]] for c in WB_COUNTRIES if c[0] in latest_by_country]
            summary_parts = [f"{x['country']} {x['value']} ({x['year']})" for x in rows_sorted]
            md_table = [
                f"# World Bank 공식 통계: {ind['name_ko']} ({code})",
                "",
                f"- **출처 API**: World Bank Open Data API (`{url}?format=json&date=2018:2025`)",
                f"- **조회 시각**: {utc_now_iso()}",
                "- **라이선스**: CC BY 4.0 (World Bank Open Data)",
                "",
                "| 국가 | ISO3 | 최신 기준연도 | 지표 수치 |",
                "| :--- | :---: | :---: | :---: |",
            ]
            for x in rows_sorted:
                md_table.append(f"| {x['country']} | {x['iso3']} | {x['year']} | {x['value']} |")
            results.append(
                {
                    "indicator_code": code,
                    "title": f"[World Bank API 통계] {ind['name_ko']}",
                    "url": f"https://data.worldbank.org/indicator/{code}",
                    "api_url": f"{url}?format=json&date=2018:2025",
                    "summary": " · ".join(summary_parts),
                    "rows": rows_sorted,
                    "markdown": "\n".join(md_table),
                    "year": max(int(x["year"]) for x in rows_sorted if str(x["year"]).isdigit()),
                }
            )
        except Exception:
            continue
    return results


def _fetch_kosis_if_configured(query: str) -> list[dict[str, Any]]:
    """환경변수 KOSIS_API_KEY가 설정된 경우 국가통계포털(KOSIS) 통계 목록을 조회한다."""
    api_key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        r = requests.get(
            "https://kosis.kr/openapi/statisticsSearch.do",
            params={"method": "getList", "apiKey": api_key, "searchNm": query[:40], "format": "json", "jsonVD": "Y", "startCount": 1, "resultCount": 4},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        out = []
        for item in data[:4]:
            title = item.get("TBL_NM") or item.get("STAT_NM") or ""
            org = item.get("ORG_NM") or "통계청 KOSIS"
            if not title:
                continue
            out.append(
                {
                    "title": f"[KOSIS 국가통계] {title} ({org})",
                    "org": org,
                    "url": item.get("LINK_URL") or "https://kosis.kr/",
                    "summary": f"기관: {org} | 기간: {item.get('STRT_PRD_DE','')}~{item.get('END_PRD_DE','')}",
                    "markdown": f"# [KOSIS 국가통계] {title}\n\n- **제공 기관**: {org}\n- **수록 기간**: {item.get('STRT_PRD_DE','')} ~ {item.get('END_PRD_DE','')}\n- **통계표 ID**: {item.get('TBL_ID','')}\n- **URL**: {item.get('LINK_URL','https://kosis.kr/')}\n",
                }
            )
        return out
    except Exception:
        return []


def run_research_turn(
    *,
    project_id: str,
    message: str,
    channels: list[str] | None = None,
    limit_per_channel: int = 4,
    state: dict[str, Any] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """대화형 심층 자료 조사 1회 라운드를 실행해 다중 소스 후보 자료를 반환·기록한다."""
    cfg = cfg or get_config()
    from subagent_orchestrator import load_project_state

    st = state or load_project_state(project_id, cfg) or {}
    topic_ko = st.get("topic_ko", project_id)
    topic_en = st.get("topic_en", "")
    keywords_ko = st.get("keywords_ko", [])
    keywords_en = st.get("keywords_en", [])
    active_channels = channels or [
        "local_rag",
        "scholar_intl",
        "scholar_kr",
        "agencies_kr",
        "agencies_global",
        "statistics_api",
    ]
    turn_id = f"turn_{datetime.now().strftime('%H%M%S')}"

    # 사용자 메시지 기록
    append_research_chat(
        project_id,
        {
            "turn_id": turn_id,
            "role": "user",
            "timestamp": utc_now_iso(),
            "local_time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "channels": active_channels,
        },
        cfg=cfg,
    )

    plan = _decompose_query(message, topic_ko, topic_en, keywords_ko, keywords_en, cfg)
    ko_terms = plan["ko_terms"]
    en_queries = plan["en_queries"]
    primary_en = en_queries[0]
    preset_name = detect_domain_preset(f"{topic_ko} {message}", f"{topic_en} {primary_en}", ko_terms, en_queries)
    preset = DOMAIN_PRESETS[preset_name]

    candidates: list[dict[str, Any]] = []
    channel_stats: dict[str, int] = {}
    warnings: list[str] = []
    idx_counter = 0

    def _add_cand(
        *,
        channel: str,
        tier: str,
        title: str,
        org_or_journal: str,
        url: str,
        summary: str,
        payload_type: str,
        payload: dict[str, Any],
        year: int | str | None = None,
        cited_by_count: int = 0,
    ) -> None:
        nonlocal idx_counter
        idx_counter += 1
        candidates.append(
            {
                "cand_id": f"{turn_id}_c{idx_counter:02d}",
                "channel": channel,
                "tier": tier,
                "tier_folder": TIER_DIRS.get(tier, "04_international_journals"),
                "tier_label": TIER_LABELS_KO.get(tier, tier),
                "title": title,
                "org_or_journal": org_or_journal,
                "year": year,
                "cited_by_count": cited_by_count,
                "url": url,
                "summary": summary[:320],
                "payload_type": payload_type,  # paper | web_url | inline_markdown
                "payload": payload,
                "added_source_id": "",
            }
        )
        channel_stats[channel] = channel_stats.get(channel, 0) + 1

    # 1. 내 컴퓨터 로컬 RAG (C:\SMC_GRAPHRAG + LightRAG)
    if "local_rag" in active_channels:
        try:
            atomic_rag_terms: list[str] = []
            for t in ko_terms[:6]:
                atomic_rag_terms.append(t)
                for tok in re.split(r"[\s·,/()]+", t):
                    if len(tok) >= 2 and tok not in atomic_rag_terms:
                        atomic_rag_terms.append(tok)
            rag_query_terms = list(dict.fromkeys(atomic_rag_terms + keywords_ko[:3]))[:10]
            hits = _query_smc_catalog(rag_query_terms, cfg, limit_per_term=6)
            lr_online = _check_lightrag_server(cfg).get("online", False)
            lr_ans = _query_lightrag_server(f"{topic_ko} {message}", cfg) if lr_online else None

            matched_ents: list[dict[str, Any]] = []
            matched_rels: list[dict[str, Any]] = []
            for term, h in hits.items():
                for e in h.get("matched_entities", [])[:4]:
                    matched_ents.append({"term": term, **e})
                for r in h.get("matched_relations", [])[:4]:
                    matched_rels.append({"term": term, **r})

            if matched_ents or matched_rels:
                md_lines = [
                    f"# [로컬 RAG 조회] {message}",
                    "",
                    f"- **조회 저장소**: `C:\\SMC_GRAPHRAG` (SQLite 통합 카탈로그{' + LightRAG' if lr_online else ''})",
                    f"- **조회 키워드**: {', '.join(ko_terms[:6])}",
                    f"- **조회 시각**: {utc_now_iso()}",
                    "",
                    "## 핵심 매칭 엔티티",
                ]
                for e in matched_ents[:15]:
                    md_lines.append(f"- **{e['name']}** ({e.get('type','CONCEPT')}, 언급 {e.get('mentions',1)}회, 출처그래프: {', '.join(e.get('graphs',[]))})")
                md_lines.append("")
                md_lines.append("## 핵심 지식 관계 (Triples)")
                for r in matched_rels[:15]:
                    md_lines.append(f"- `{r['source']}` —[{r['relation']}]→ `{r['target']}` *(문헌: {r.get('source_doc','')})*")
                if lr_ans and lr_ans.get("online"):
                    md_lines.extend(["", "## LightRAG 하이브리드 응답", str(lr_ans.get("response", ""))[:1800]])

                _add_cand(
                    channel="local_rag",
                    tier="domestic_agencies",
                    title=f"[내 PC 로컬 RAG] '{message[:45]}' 지식그래프 매칭 ({len(matched_ents)}노드·{len(matched_rels)}관계)",
                    org_or_journal="C:\\SMC_GRAPHRAG 로컬 지식그래프",
                    url=f"local-rag://{project_id}/{turn_id}",
                    summary=f"엔티티 {len(matched_ents)}건 · 관계 {len(matched_rels)}건 매칭: "
                    + ", ".join(dict.fromkeys(e["name"] for e in matched_ents[:6])),
                    payload_type="inline_markdown",
                    payload={
                        "title": f"[로컬 RAG] {message[:60]}",
                        "url": f"local-rag://{project_id}/{turn_id}",
                        "source_type": "kg_reuse",
                        "license_note": "사용자 자체 구축 C:\\SMC_GRAPHRAG 지식그래프 내부 재활용",
                        "markdown": "\n".join(md_lines),
                    },
                    year=datetime.now().year,
                )
        except Exception as exc:
            warnings.append(f"로컬 RAG 조회 경고: {exc}")

    # 2. 국내 학회지 & 한국 대학·연구소 논문 (Crossref + OpenAlex KR)
    if "scholar_kr" in active_channels:
        seen_urls_kr: set[str] = set()
        for spec in preset.get("domestic_journals", [])[:3]:
            jname = spec["journal"]
            try:
                papers = search_crossref_korean_society(query=primary_en, limit=max(2, limit_per_channel // 2), journal_name=jname)
                for p in papers:
                    u = p.get("url", "")
                    if u in seen_urls_kr:
                        continue
                    seen_urls_kr.add(u)
                    _add_cand(
                        channel="scholar_kr",
                        tier="domestic_journals",
                        title=p.get("title", ""),
                        org_or_journal=p.get("journal", jname),
                        url=u,
                        summary=p.get("abstract") or f"국내 학회지({jname}) · 저자: {', '.join(p.get('authors', [])[:3])}",
                        payload_type="paper",
                        payload=p,
                        year=p.get("year"),
                        cited_by_count=p.get("cited_by_count", 0),
                    )
            except Exception as exc:
                warnings.append(f"국내 학회({jname}) 검색 경고: {exc}")

        try:
            kr_papers = _search_openalex_by_region(primary_en, "KR", limit=limit_per_channel)
            for p in kr_papers:
                u = p.get("url", "")
                if u in seen_urls_kr:
                    continue
                seen_urls_kr.add(u)
                inst_txt = f" | {', '.join(p.get('institutions', []))}" if p.get("institutions") else ""
                _add_cand(
                    channel="scholar_kr",
                    tier="domestic_journals",
                    title=p.get("title", ""),
                    org_or_journal=f"{p.get('journal','')}{inst_txt}",
                    url=u,
                    summary=p.get("abstract") or f"한국 연구기관·대학 논문{inst_txt}",
                    payload_type="paper",
                    payload={**p, "category": "korean_society", "provider": "OpenAlex (국내 대학·기관)"},
                    year=p.get("year"),
                    cited_by_count=p.get("cited_by_count", 0),
                )
        except Exception as exc:
            warnings.append(f"OpenAlex 국내 기관 검색 경고: {exc}")

    # 3. 국제 SCI·구글스칼라 호환 학술 논문 (OpenAlex 정밀 relevance)
    if "scholar_intl" in active_channels:
        seen_urls_intl: set[str] = set()
        for q in en_queries[:2]:
            try:
                papers = search_openalex_papers(query=q, limit=limit_per_channel, scope="all", sort="relevance_score:desc")
                for p in papers:
                    u = p.get("url", "")
                    if u in seen_urls_intl:
                        continue
                    seen_urls_intl.add(u)
                    oa_tag = " [OA PDF]" if p.get("pdf_url") else ""
                    _add_cand(
                        channel="scholar_intl",
                        tier="international_journals",
                        title=f"{p.get('title','')}{oa_tag}",
                        org_or_journal=p.get("journal", "국제 SCI"),
                        url=u,
                        summary=p.get("abstract") or f"국제 학술 문헌 · 피인용 {p.get('cited_by_count',0)}회",
                        payload_type="paper",
                        payload=p,
                        year=p.get("year"),
                        cited_by_count=p.get("cited_by_count", 0),
                    )
            except Exception as exc:
                warnings.append(f"OpenAlex 국제 검색 경고: {exc}")

    # 4. 농촌진흥청 등 국내 관계기관·웹사이트
    if "agencies_kr" in active_channels:
        for ag in preset.get("domestic_agencies", [])[:5]:
            _add_cand(
                channel="agencies_kr",
                tier="domestic_agencies",
                title=ag["name"],
                org_or_journal="대한민국 공식기관·웹사이트 (robots.txt 허용)",
                url=ag["url"],
                summary=ag.get("license_note", "국내 공식기관 공개 웹 자료"),
                payload_type="web_url",
                payload={"url": ag["url"], "name": ag["name"], "license_note": ag.get("license_note", "")},
            )

    # 5. 미국·일본·유럽 농업기관 및 대학·웹사이트 (기관 웹 + 미/일/EU 대학·연구소 문헌)
    if "agencies_global" in active_channels:
        for ag in preset.get("international_agencies", [])[:6]:
            _add_cand(
                channel="agencies_global",
                tier="international_agencies",
                title=ag["name"],
                org_or_journal="국제기구·미/일/유럽 공식기관 (robots.txt 허용)",
                url=ag["url"],
                summary=ag.get("license_note", "해외 공식기관·대학 확장 자료"),
                payload_type="web_url",
                payload={"url": ag["url"], "name": ag["name"], "license_note": ag.get("license_note", "")},
            )
        # 미국(US) · 일본(JP) · 유럽(NL|DE|FR|GB|IT|ES|DK) 대학·농업연구기관 논문 보강
        for reg_label, codes in [("미국 대학·USDA 연구", "US"), ("일본 대학·NARO 연구", "JP"), ("유럽 대학·기관 연구", "NL|DE|FR|GB|IT|ES|DK")]:
            try:
                rpapers = _search_openalex_by_region(primary_en, codes, limit=2)
                for p in rpapers:
                    inst_txt = f" ({', '.join(p.get('institutions', [])[:2])})" if p.get("institutions") else ""
                    _add_cand(
                        channel="agencies_global",
                        tier="international_journals",
                        title=p.get("title", ""),
                        org_or_journal=f"{reg_label}{inst_txt} — {p.get('journal','')}",
                        url=p.get("url", ""),
                        summary=p.get("abstract") or f"{reg_label}{inst_txt}",
                        payload_type="paper",
                        payload={**p, "provider": f"OpenAlex ({reg_label})"},
                        year=p.get("year"),
                        cited_by_count=p.get("cited_by_count", 0),
                    )
            except Exception as exc:
                warnings.append(f"{reg_label} 검색 경고: {exc}")

    # 6. 공식 통계자료 API (World Bank Open Data + UN FAO FLW + KOSIS API)
    if "statistics_api" in active_channels:
        wb_stats = _fetch_world_bank_statistics(f"{topic_ko} {topic_en} {message}", max_indicators=2)
        for st_item in wb_stats:
            _add_cand(
                channel="statistics_api",
                tier="international_agencies",
                title=st_item["title"],
                org_or_journal="World Bank Open Data API (실시간 공식 통계)",
                url=st_item["url"],
                summary=st_item["summary"],
                payload_type="inline_markdown",
                payload={
                    "title": st_item["title"],
                    "url": st_item["api_url"],
                    "source_type": "web",
                    "license_note": "World Bank Open Data API (CC BY 4.0) - 공식 통계 인용",
                    "markdown": st_item["markdown"],
                },
                year=st_item.get("year"),
            )
        kosis_items = _fetch_kosis_if_configured(" ".join(ko_terms[:2]) or topic_ko)
        for ks in kosis_items:
            _add_cand(
                channel="statistics_api",
                tier="domestic_agencies",
                title=ks["title"],
                org_or_journal=f"KOSIS 국가통계포털 API ({ks['org']})",
                url=ks["url"],
                summary=ks["summary"],
                payload_type="inline_markdown",
                payload={
                    "title": ks["title"],
                    "url": ks["url"],
                    "source_type": "web",
                    "license_note": "대한민국 통계청 KOSIS 공개 통계 API",
                    "markdown": ks["markdown"],
                },
                year=datetime.now().year,
            )

    assistant_entry = {
        "turn_id": turn_id,
        "role": "assistant",
        "timestamp": utc_now_iso(),
        "local_time": datetime.now().strftime("%H:%M:%S"),
        "focus_summary_ko": plan["focus_summary_ko"],
        "decomposed_ko_terms": ko_terms,
        "decomposed_en_queries": en_queries,
        "channel_stats": channel_stats,
        "total_candidates": len(candidates),
        "candidates": candidates,
        "warnings": warnings,
        "kosis_api_configured": bool(os.environ.get("KOSIS_API_KEY", "").strip()),
    }
    append_research_chat(project_id, assistant_entry, cfg=cfg)
    return assistant_entry


def _ingest_inline_markdown(
    *,
    title: str,
    url: str,
    markdown_text: str,
    source_type: str,
    license_note: str,
    packet_id: str,
    topic: str,
    tier_dir: Path,
    cfg: PlatformConfig,
) -> dict[str, Any]:
    """로컬 RAG 매칭 리포트나 World Bank/KOSIS 실시간 통계 API 표를 정식 [SRC-NN]으로 분리 폴더에 저장한다."""
    registry = SourcesRegistry(cfg.sources_registry_path)
    cleaned_md, pii_count = mask_pii(markdown_text)
    content_hash = sha256_text(cleaned_md)
    dup = registry.find_duplicate(content_sha256=content_hash)
    if dup:
        sid = dup["source_id"]
        _ensure_duplicate_in_packet(existing_rec=dup, packet_id=packet_id, topic=topic, cfg=cfg)
        saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=dup.get("parsed_path"))
        return {"status": "REUSED", "source_id": sid, "saved_files": saved, "parsed_path": dup.get("parsed_path", "")}

    sid = registry.next_source_id()
    slug = slugify(title, 46)
    parsed_path = cfg.parsed_dir / f"{sid}_{slug}.md"
    parsed_path.write_text(cleaned_md, encoding="utf-8")
    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=str(parsed_path))

    chunks = chunk_korean_text(cleaned_md, default_section=title[:60])
    now = utc_now_iso()
    source_item = {
        "source_id": sid,
        "source_type": source_type if source_type in ("web", "pdf", "kg_reuse", "local_doc") else "web",
        "url": url,
        "title": title,
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": "api_or_local_rag",
        "license_note": license_note,
        "page_or_section": "API/로컬RAG 전체",
        "raw_path": str(parsed_path),
        "parsed_path": str(parsed_path),
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": [],
        "sha256": content_hash,
        "extracted_facts": [],
        "tables": [],
        "chunks": chunks,
    }
    pkt_path = cfg.evidence_dir / f"{packet_id}.json"
    upsert_evidence_packet(
        packet_path=pkt_path,
        source_item=source_item,
        packet_id=packet_id,
        topic=topic,
        storage_root=str(cfg.collected_data_root),
        kg_store_root=str(cfg.smc_graphrag_root),
        schema_path=cfg.evidence_schema_path,
    )
    registry.append(
        {
            "source_id": sid,
            "source_type": source_item["source_type"],
            "url": url,
            "normalized_url": url,
            "title": title,
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": "api_or_local_rag",
            "sha256": content_hash,
            "raw_path": str(parsed_path),
            "parsed_path": str(parsed_path),
            "packet_path": str(pkt_path),
            "parser_engine": "deep_research_chat",
            "chunk_count": len(chunks),
            "table_count": 0,
        }
    )
    return {"status": "OK", "source_id": sid, "saved_files": saved, "parsed_path": str(parsed_path)}


def commit_research_items(
    *,
    project_id: str,
    candidate_ids: list[str] | None = None,
    custom_urls: list[str] | None = None,
    bibtex_text: str = "",
    also_ingest_kg: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """대화 창에서 선택한 후보 자료·직접 URL·Google Scholar BibTeX를 프로젝트 분리 폴더(+선택 KG)에 누적 추가한다."""
    cfg = cfg or get_config()
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project {project_id} not found")

    packet_id = st.get("packet_id") or f"{project_id}_evidence"
    topic_ko = st.get("topic_ko", project_id)
    collected_root = cfg.project_collected_dir(project_id)
    proj_e_evidence_dir = cfg.project_e_evidence_dir(project_id)
    proj_e_evidence_dir.mkdir(parents=True, exist_ok=True)
    ws_collected_dir = cfg.project_dir(project_id) / "collected"
    ws_collected_dir.mkdir(parents=True, exist_ok=True)

    # 최근 대화 기록에서 cand_id 매핑 복원
    chat_entries = load_research_chat(project_id, limit=80, cfg=cfg)
    cand_map: dict[str, dict[str, Any]] = {}
    for entry in chat_entries:
        for c in entry.get("candidates", []):
            if c.get("cand_id"):
                cand_map[c["cand_id"]] = c

    existing_sources: list[dict[str, Any]] = list(st.get("collected_sources") or [])
    existing_sids = {s.get("source_id") for s in existing_sources if s.get("source_id")}
    newly_added: list[dict[str, Any]] = []
    errors: list[str] = []

    def _append_source(rec: dict[str, Any]) -> None:
        sid = rec.get("source_id", "")
        if not sid:
            return
        newly_added.append(rec)
        if sid not in existing_sids:
            existing_sids.add(sid)
            existing_sources.append(rec)

    # 1) 선택된 대화 후보 항목 처리
    for cid in (candidate_ids or []):
        c = cand_map.get(cid)
        if not c:
            continue
        tier_key = c.get("tier") if c.get("tier") in TIER_DIRS else "international_journals"
        tier_dir = collected_root / TIER_DIRS[tier_key]
        tier_dir.mkdir(parents=True, exist_ok=True)
        ptype = c.get("payload_type", "")
        pl = c.get("payload") or {}
        try:
            if ptype == "paper":
                res = ingest_paper_record(paper=pl, packet_id=packet_id, topic=topic_ko, download_oa_pdf=True, force=False, cfg=cfg)
                if res.get("status") == "OK" and res.get("source_id"):
                    sid = res["source_id"]
                    reg_rec = SourcesRegistry(cfg.sources_registry_path).find_duplicate(url=pl.get("url")) or {}
                    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=res.get("parsed_path"), raw_path=reg_rec.get("raw_path"))
                    _append_source(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": TIER_LABELS_KO[tier_key],
                            "title": c["title"],
                            "journal": c.get("org_or_journal", ""),
                            "year": c.get("year"),
                            "cited_by_count": c.get("cited_by_count", 0),
                            "url": c.get("url", ""),
                            "provider": f"심층조사({c.get('channel','')})",
                            "status": "OK",
                            "saved_files": saved,
                        }
                    )
                elif res.get("status") == "SKIPPED_DUPLICATE" and res.get("existing"):
                    ex = res["existing"]
                    sid = ex.get("source_id", "")
                    _ensure_duplicate_in_packet(existing_rec=ex, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=ex.get("parsed_path"), raw_path=ex.get("raw_path"))
                    _append_source(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": TIER_LABELS_KO[tier_key],
                            "title": c["title"],
                            "journal": c.get("org_or_journal", ""),
                            "year": c.get("year"),
                            "cited_by_count": c.get("cited_by_count", 0),
                            "url": c.get("url", ""),
                            "provider": f"심층조사({c.get('channel','')}, 재연결)",
                            "status": "REUSED",
                            "saved_files": saved,
                        }
                    )
            elif ptype == "web_url":
                u = pl.get("url") or c.get("url", "")
                res = fetch_and_clean_url(
                    url=u,
                    packet_id=packet_id,
                    topic=topic_ko,
                    license_note=pl.get("license_note") or "심층 조사 수집 공개 웹자료",
                    use_crawl4ai=False,
                    extract_facts=False,
                    force=False,
                    cfg=cfg,
                )
                if res.get("status") == "OK" and res.get("source_id"):
                    sid = res["source_id"]
                    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=res.get("parsed_path"), raw_path=res.get("raw_path"))
                    _append_source(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": TIER_LABELS_KO[tier_key],
                            "title": res.get("title") or c["title"],
                            "journal": c.get("org_or_journal", ""),
                            "year": None,
                            "cited_by_count": 0,
                            "url": u,
                            "provider": f"심층조사({c.get('channel','')})",
                            "status": "OK",
                            "saved_files": saved,
                        }
                    )
                elif res.get("status") == "SKIPPED_DUPLICATE" and res.get("existing"):
                    ex = res["existing"]
                    sid = ex.get("source_id", "")
                    _ensure_duplicate_in_packet(existing_rec=ex, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=ex.get("parsed_path"), raw_path=ex.get("raw_path"))
                    _append_source(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": TIER_LABELS_KO[tier_key],
                            "title": c["title"],
                            "journal": c.get("org_or_journal", ""),
                            "year": None,
                            "cited_by_count": 0,
                            "url": u,
                            "provider": f"심층조사({c.get('channel','')}, 재연결)",
                            "status": "REUSED",
                            "saved_files": saved,
                        }
                    )
                else:
                    errors.append(f"{u}: {res.get('status')} ({res.get('robots_status', '')})")
            elif ptype == "inline_markdown":
                res = _ingest_inline_markdown(
                    title=pl.get("title") or c["title"],
                    url=pl.get("url") or c.get("url", ""),
                    markdown_text=pl.get("markdown", ""),
                    source_type=pl.get("source_type", "web"),
                    license_note=pl.get("license_note", "공식 통계/로컬 RAG 자료"),
                    packet_id=packet_id,
                    topic=topic_ko,
                    tier_dir=tier_dir,
                    cfg=cfg,
                )
                _append_source(
                    {
                        "source_id": res["source_id"],
                        "tier": tier_key,
                        "tier_folder": TIER_DIRS[tier_key],
                        "tier_label": TIER_LABELS_KO[tier_key],
                        "title": c["title"],
                        "journal": c.get("org_or_journal", ""),
                        "year": c.get("year"),
                        "cited_by_count": 0,
                        "url": c.get("url", ""),
                        "provider": f"심층조사({c.get('channel','')})",
                        "status": res["status"],
                        "saved_files": res.get("saved_files", []),
                    }
                )
        except Exception as exc:
            errors.append(f"{cid} ({c.get('title','')[:40]}): {exc}")

    # 2) 사용자 직접 입력 URL 수집 (국내/해외 자동 판별)
    for raw_u in (custom_urls or []):
        u = raw_u.strip()
        if not u.startswith(("http://", "https://")):
            continue
        is_kr = ".kr" in u.lower() or "ko.wikipedia" in u.lower()
        tier_key = "domestic_agencies" if is_kr else "international_agencies"
        tier_dir = collected_root / TIER_DIRS[tier_key]
        tier_dir.mkdir(parents=True, exist_ok=True)
        try:
            res = fetch_and_clean_url(url=u, packet_id=packet_id, topic=topic_ko, use_crawl4ai=False, cfg=cfg)
            if res.get("status") == "OK":
                sid = res["source_id"]
                saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=res.get("parsed_path"), raw_path=res.get("raw_path"))
                _append_source(
                    {
                        "source_id": sid,
                        "tier": tier_key,
                        "tier_folder": TIER_DIRS[tier_key],
                        "tier_label": TIER_LABELS_KO[tier_key],
                        "title": res.get("title") or u,
                        "journal": "사용자 직접 추가 URL",
                        "year": None,
                        "cited_by_count": 0,
                        "url": u,
                        "provider": "직접 URL 수집",
                        "status": "OK",
                        "saved_files": saved,
                    }
                )
            elif res.get("status") == "SKIPPED_DUPLICATE" and res.get("existing"):
                ex = res["existing"]
                sid = ex.get("source_id", "")
                _ensure_duplicate_in_packet(existing_rec=ex, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=ex.get("parsed_path"), raw_path=ex.get("raw_path"))
                _append_source(
                    {
                        "source_id": sid,
                        "tier": tier_key,
                        "tier_folder": TIER_DIRS[tier_key],
                        "tier_label": TIER_LABELS_KO[tier_key],
                        "title": ex.get("title") or u,
                        "journal": "사용자 직접 추가 URL (재연결)",
                        "year": None,
                        "cited_by_count": 0,
                        "url": u,
                        "provider": "직접 URL 수집",
                        "status": "REUSED",
                        "saved_files": saved,
                    }
                )
            else:
                errors.append(f"{u}: {res.get('status')} ({res.get('robots_status','')})")
        except Exception as exc:
            errors.append(f"{u}: {exc}")

    # 3) Google Scholar / RISS / KCI BibTeX 직접 붙여넣기 임포트
    if bibtex_text and bibtex_text.strip():
        bib_papers = parse_bibtex_entries(bibtex_text)
        for p in bib_papers:
            tier_key = "domestic_journals" if p.get("language") == "ko" else "international_journals"
            tier_dir = collected_root / TIER_DIRS[tier_key]
            tier_dir.mkdir(parents=True, exist_ok=True)
            try:
                res = ingest_paper_record(paper=p, packet_id=packet_id, topic=topic_ko, download_oa_pdf=True, capture_webpage=True, auto_unify_rag=True, cfg=cfg)
                if res.get("status") == "OK" and res.get("source_id"):
                    sid = res["source_id"]
                    saved = _copy_source_files_to_tier(tier_dir=tier_dir, source_id=sid, parsed_path=res.get("parsed_path"))
                    _append_source(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": TIER_LABELS_KO[tier_key],
                            "title": p.get("title", ""),
                            "journal": p.get("journal", "Google Scholar BibTeX"),
                            "year": p.get("year"),
                            "cited_by_count": 0,
                            "url": p.get("url", ""),
                            "provider": "Google Scholar / BibTeX",
                            "status": "OK",
                            "saved_files": saved,
                        }
                    )
            except Exception as exc:
                errors.append(f"BibTeX({p.get('title','')[:30]}): {exc}")

    # 프로젝트 전용 근거 패킷 & 매니페스트 & state.json 동기화
    global_pkt = cfg.evidence_dir / f"{packet_id}.json"
    proj_pkt = proj_e_evidence_dir / f"{packet_id}.json"
    if global_pkt.is_file():
        shutil.copy2(global_pkt, proj_pkt)

    breakdown = {k: sum(1 for s in existing_sources if s.get("tier") == k) for k in TIER_DIRS}
    manifest_path = collected_root / "collection_manifest.json"
    prev_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "topic_en": st.get("topic_en", topic_ko),
        "preset": prev_manifest.get("preset", "custom"),
        "generated_at": utc_now_iso(),
        "collected_root": str(collected_root),
        "tier_directories": {k: str(collected_root / v) for k, v in TIER_DIRS.items()},
        "global_evidence_path": str(global_pkt),
        "project_evidence_path": str(proj_pkt),
        "packet_id": packet_id,
        "total_collected": len(existing_sources),
        "pdf_downloaded_count": prev_manifest.get("pdf_downloaded_count", 0),
        "breakdown": breakdown,
        "source_ids": [s["source_id"] for s in existing_sources if s.get("source_id")],
        "sources": existing_sources,
        "blocked_or_failed": prev_manifest.get("blocked_or_failed", []),
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_json, encoding="utf-8")
    (ws_collected_dir / "collection_manifest.json").write_text(manifest_json, encoding="utf-8")
    _write_collection_index_md(manifest, collected_root / "INDEX.md")
    _write_collection_index_md(manifest, ws_collected_dir / "INDEX.md")

    st["collected_sources"] = existing_sources
    st["collection_breakdown"] = {**breakdown, "total": len(existing_sources)}
    st["collected_dir"] = str(collected_root)
    st["collection_manifest_path"] = str(manifest_path)
    save_project_state(st, cfg)

    added_sids = [x["source_id"] for x in newly_added if x.get("source_id")]
    if added_sids:
        append_event(
            project_id,
            "deep-research",
            "stage2_web_scout",
            f"대화형 심층 조사에서 {len(added_sids)}건 자료 추가 완료 ({', '.join(added_sids[:8])}) → 프로젝트 누적 {len(existing_sources)}건",
            cfg=cfg,
        )

    kg_result = None
    if also_ingest_kg and added_sids:
        from build_platform_kg import build_knowledge_graph_from_sources

        kg_model = st.get("options", {}).get("kg_model") or cfg.ollama_fast_model
        append_event(project_id, "kg-builder", "stage3_kg_builder", f"심층 조사 신규 자료 {len(added_sids)}건 지식그래프 즉시 증분 반영 시작...", cfg=cfg)
        kg_result = build_knowledge_graph_from_sources(source_ids=added_sids, model=kg_model, cfg=cfg)
        append_event(
            project_id,
            "kg-builder",
            "stage3_kg_builder",
            f"심층 조사 KG 증분 완료: +{kg_result.get('nodes_after',0)-kg_result.get('nodes_before',0)}노드 / +{kg_result.get('edges_after',0)-kg_result.get('edges_before',0)}관계",
            cfg=cfg,
        )

    commit_entry = {
        "turn_id": f"commit_{datetime.now().strftime('%H%M%S')}",
        "role": "system",
        "timestamp": utc_now_iso(),
        "local_time": datetime.now().strftime("%H:%M:%S"),
        "message": f"선택 자료 {len(added_sids)}건이 분리 저장 폴더({collected_root})에 추가되었습니다 (프로젝트 총 {len(existing_sources)}건).",
        "added_source_ids": added_sids,
        "errors": errors,
        "kg_ingested": bool(kg_result),
        "kg_summary": {
            "nodes_added": kg_result.get("nodes_after", 0) - kg_result.get("nodes_before", 0),
            "edges_added": kg_result.get("edges_after", 0) - kg_result.get("edges_before", 0),
        } if kg_result else None,
    }
    append_research_chat(project_id, commit_entry, cfg=cfg)
    return {
        "status": "OK",
        "added_count": len(added_sids),
        "added_source_ids": added_sids,
        "total_project_sources": len(existing_sources),
        "breakdown": breakdown,
        "errors": errors,
        "kg_result": commit_entry["kg_summary"],
    }
