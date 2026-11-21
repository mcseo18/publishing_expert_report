"""유기물 질소 동역학·모델 & 토양 탄소 분해 모델(이론·실전) 전문 학술 자료 수집기.

대상 주제:
1. 유기물 질소 동역학 & 모델 (cn_model):
   - Stanford & Smith (1972) 질소 무기화 잠재량 지수 모델
   - Schimel & Bennett (2004) 질소 무기화 패러다임 전환(해중합 병목)
   - Manzoni et al. (2008) 낙엽·유기물 질소 무기화의 전 지구 화학양론(C/N & CUE)
   - Li et al. DNDC 탄소-질소 연계 모델(탈질·N2O·용탈)
   - 국내 학회지(한국토양비료학회지) 녹비·퇴비 질소 무기화 및 모델 연구
2. 토양 탄소 분해 모델 이론 & 실전 (carbon_model):
   - Jenkinson (1990) / Coleman & Jenkinson RothC 다중 풀 이론
   - Parton et al. (1987) CENTURY 3-풀 탄소·질소 연계 모델
   - Manzoni & Porporato (2009) 250종 토양 탄소·질소 분해 모델 수학적 통합 리뷰
   - Wieder et al. (2013/2015) MIMICS 차세대 미생물 명시형(Michaelis-Menten) 탄소 분해 모델
   - Sierra et al. (2012) SoilR 오픈소스 토양유기물 분해 모델링 패키지(이론+실전 코드)
   - 국내 학회지(한국토양비료학회지) 국내 논·밭 RothC/DNDC 탄소 분해·축적 모델 적용 연구
"""
from __future__ import annotations

import json
import sys
from typing import Any

import requests

from compliance import USER_AGENT, utc_now_iso
from config import PlatformConfig, get_config
from fetch_scholar import (
    _reconstruct_openalex_abstract,
    ingest_paper_record,
    search_crossref_korean_society,
)


def _set_curation(
    source_id: str,
    category: str,
    tier: str,
    chapters: list[str],
    tags: list[str],
    notes: str,
    rating: int = 5,
    cfg: PlatformConfig | None = None,
) -> None:
    cfg = cfg or get_config()
    p = cfg.index_dir / "curation_state.json"
    state: dict[str, Any] = {}
    if p.is_file():
        try:
            state = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state[source_id] = {
        "status": "approved",
        "category": category,
        "tier": tier,
        "chapters": chapters,
        "tags": tags,
        "notes": notes,
        "rating": rating,
        "updated_at": utc_now_iso(),
    }
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _search_top_openalex(query: str, extra_filter: str = "", limit: int = 1) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": query,
        "sort": "cited_by_count:desc",
        "per-page": limit,
    }
    if extra_filter:
        params["filter"] = extra_filter
    r = requests.get(
        "https://api.openalex.org/works",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    out: list[dict[str, Any]] = []
    for w in r.json().get("results", []):
        primary = w.get("primary_location") or {}
        src = primary.get("source") or {}
        best_oa = w.get("best_oa_location") or {}
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:6]
        ]
        authors = [a for a in authors if a]
        doi = w.get("doi") or ""
        landing = best_oa.get("landing_page_url") or primary.get("landing_page_url") or doi or w.get("id", "")
        pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
        abstract = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
        out.append(
            {
                "id": w.get("id", ""),
                "title": w.get("display_name") or w.get("title") or "",
                "authors": authors,
                "year": w.get("publication_year"),
                "journal": src.get("display_name") or "International Journal",
                "doi": doi,
                "url": landing,
                "pdf_url": pdf_url,
                "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
                "cited_by_count": int(w.get("cited_by_count") or 0),
                "language": w.get("language") or "en",
                "abstract": abstract,
                "provider": "OpenAlex",
            }
        )
    return out


TARGET_MODEL_QUERIES: list[dict[str, Any]] = [
    # --- 유기물 질소 동역학 및 모델 (ch07, ch11) ---
    {
        "query": "Nitrogen mineralization potentials of soils Stanford Smith",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch07_evidence",
        "chapters": ["ch07", "ch11"],
        "tags": ["질소동역학", "질소무기화모델", "Stanford-Smith", "1차속도식"],
        "note": "토양 유기질소 무기화 1차 지수 모델 Nt = N0(1 - exp(-kt))의 고전 원조 논문.",
    },
    {
        "query": "Nitrogen mineralization challenges of a changing paradigm Schimel Bennett",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch07_evidence",
        "chapters": ["ch07", "ch06"],
        "tags": ["질소동역학", "해중합병목", "Schimel&Bennett", "유기질소흡수"],
        "note": "현대 토양 질소 순환 패러다임 전환: 무기화가 아닌 고분자 유기질소 해중합(Depolymerization)이 율속 단계임을 규명.",
    },
    {
        "query": "The global stoichiometry of litter nitrogen mineralization Manzoni",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch07_evidence",
        "chapters": ["ch07", "ch02", "ch10"],
        "tags": ["질소동역학", "탄질비화학양론", "CUE", "Manzoni", "무기화부동화"],
        "note": "유기물 탄질비(C/N)와 미생물 탄소이용효율(CUE)에 따른 질소 순무기화·부동화 임계점의 전 지구 화학양론 모델.",
    },
    {
        "query": "Modeling trace gas emissions from agricultural ecosystems DNDC Changsheng Li",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch07_evidence",
        "chapters": ["ch07", "ch10", "ch11"],
        "tags": ["DNDC모델", "질산화", "탈질", "N2O", "C-N연계모델"],
        "note": "DNDC(DeNitrification-DeComposition) 탄소-질소 연계 생지화학 모델 핵심 논문(질산화·탈질·메탄·아산화질소 모의).",
    },
    # --- 탄소 분해 모델 이론과 실전 (ch10, ch11) ---
    {
        "query": "Analysis of factors controlling soil organic matter levels in Great Plains grasslands Parton",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch10_evidence",
        "chapters": ["ch10", "ch11"],
        "tags": ["CENTURY모델", "탄소분해모델", "Parton", "3풀모델", "C-N연계"],
        "note": "CENTURY 토양유기물 모델(활성·완효·수동 3-풀 + 질소 연계) 원조 논문.",
    },
    {
        "query": "The turnover of organic carbon and nitrogen in soil Jenkinson",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch10_evidence",
        "chapters": ["ch10", "ch11"],
        "tags": ["RothC모델", "Jenkinson", "탄소분해이론", "5풀구조"],
        "note": "RothC 모델 이론적 토대: DPM·RPM·BIO·HUM·IOM 5-풀 토양탄소·질소 회전율 모델 원조 논문.",
    },
    {
        "query": "Soil carbon and nitrogen mineralization Theory and models across scales Manzoni Porporato",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch10_evidence",
        "chapters": ["ch07", "ch10"],
        "tags": ["탄소질소모델리뷰", "수학적이론", "Manzoni&Porporato", "분해동역학"],
        "note": "약 250종 토양 탄소·질소 무기화·분해 수학 모델을 스케일·비선형성별로 체계화한 결정판 이론 리뷰.",
    },
    {
        "query": "Global soil carbon projections are improved by modelling microbial processes Wieder",
        "category": "cn_model",
        "tier": "질소·탄소 모델 핵심논문",
        "packet": "ch10_evidence",
        "chapters": ["ch10", "ch11", "ch03"],
        "tags": ["MIMICS모델", "미생물명시형모델", "Michaelis-Menten", "비선형탄소모델"],
        "note": "차세대 미생물 명시형(Microbial-explicit) 비선형 토양탄소 분해 모델(MIMICS 계열) 이론·지구 규모 적용 논문.",
    },
    {
        "query": "Models of soil organic matter decomposition the SoilR package Sierra",
        "extra_filter": "is_oa:true",
        "category": "cn_model",
        "tier": "질소·탄소 모델 실전(OA)",
        "packet": "ch11_evidence",
        "chapters": ["ch10", "ch11"],
        "tags": ["SoilR", "모델링실전", "구획행렬이론", "오픈소스실습", "Sierra"],
        "note": "토양유기물 분해 모델의 선형·비선형 구획 미분방정식 행렬 이론과 오픈소스 SoilR 실전 구현 가이드(오픈액세스).",
    },
    {
        "query": "Explicitly representing soil microbial processes in Earth system models MIMICS Wieder",
        "extra_filter": "is_oa:true",
        "category": "cn_model",
        "tier": "질소·탄소 모델 실전(OA)",
        "packet": "ch11_evidence",
        "chapters": ["ch10", "ch11"],
        "tags": ["MIMICS", "실전매개변수", "효소동역학", "오픈액세스"],
        "note": "MIMICS 모델의 구체적 미분방정식·매개변수·교정 절차를 수록한 오픈액세스 실전 구현 논문.",
    },
]


def run_cn_model_collection(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    results: dict[str, Any] = {
        "international_cn_models": [],
        "korean_society_cn_models": [],
        "ingested_source_ids": [],
    }

    # 1. 국제 핵심 질소·탄소 모델 논문 10편
    for spec in TARGET_MODEL_QUERIES:
        try:
            hits = _search_top_openalex(spec["query"], extra_filter=spec.get("extra_filter", ""), limit=1)
            if not hits:
                results["international_cn_models"].append({"status": "NOT_FOUND", "query": spec["query"]})
                continue
            paper = hits[0]
            paper["category"] = spec["category"]
            res = ingest_paper_record(
                paper=paper,
                packet_id=spec["packet"],
                topic="유기물 질소 동역학 및 토양 탄소 분해 모델 이론·실전",
                download_oa_pdf=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                sid = res["source_id"]
                _set_curation(sid, spec["category"], spec["tier"], spec["chapters"], spec["tags"], spec["note"], 5, cfg)
                results["ingested_source_ids"].append(sid)
            results["international_cn_models"].append(res)
        except Exception as exc:
            results["international_cn_models"].append({"status": "ERROR", "query": spec["query"], "error": str(exc)})

    # 2. 국내 학회지(한국토양비료학회지) 질소 무기화 및 탄소 분해 모델(RothC/DNDC) 적용 논문
    kr_queries = [
        ("nitrogen mineralization organic matter compost", "ch07_evidence", ["ch07", "ch11", "ch13"], ["한국토양비료학회", "질소무기화", "유기물", "국내실증"]),
        ("RothC DNDC soil organic carbon model paddy", "ch11_evidence", ["ch10", "ch11", "ch12"], ["한국토양비료학회", "RothC", "DNDC", "탄소모델실전"]),
    ]
    for q, pkt, chs, tags in kr_queries:
        try:
            papers = search_crossref_korean_society(q, limit=2)
            for p in papers:
                p["category"] = "cn_model"
                res = ingest_paper_record(
                    paper=p,
                    packet_id=pkt,
                    topic="국내 한국토양비료학회지 질소 무기화·탄소 모델 실전 적용",
                    cfg=cfg,
                )
                if res.get("status") == "OK":
                    sid = res["source_id"]
                    _set_curation(
                        sid,
                        "cn_model",
                        "국내 학회(질소·탄소모델)",
                        chs,
                        tags,
                        f"한국토양비료학회지 국내 농경지 질소 무기화 / 탄소 모델 적용 논문 ({p.get('year')}).",
                        5,
                        cfg,
                    )
                    results["ingested_source_ids"].append(sid)
                results["korean_society_cn_models"].append(res)
        except Exception as exc:
            results["korean_society_cn_models"].append({"status": "ERROR", "query": q, "error": str(exc)})

    return results


if __name__ == "__main__":
    print(json.dumps(run_cn_model_collection(), ensure_ascii=False, indent=2))
