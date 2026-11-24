"""프로젝트별 국내외 공식기관·웹사이트·학회지·국제 SCI 논문 분리 수집기 (Stage 2 web-scout 엔진).

핵심 설계:
1. 주제별로 국내 기관, 국내 학회지, 해외 공식기관/국제기구, 국제 SCI 저널의 4계층 자료를
   충분히 수집해 프로젝트 전용 분리 폴더에 먼저 저장한다:
   E:\\SMC_Report_Platform_Data\\projects\\<project_slug>\\collected\\
     ├── 01_domestic_agencies\\        (국내 공식기관·웹사이트)
     ├── 02_domestic_journals\\        (국내 학회지·국내 기관 논문)
     ├── 03_international_agencies\\   (국제기구·해외 공식기관·대학 확장)
     ├── 04_international_journals\\   (국제 핵심 SCI 저널·오픈액세스 논문/PDF)
     ├── collection_manifest.json      (4계층 분류 통계·robots 상태·저작권 메모)
     └── INDEX.md                      (전체 수집 목록 요약표)
2. 모든 수집 자료는 E:\\SMC_Report_Platform_Data\\evidence\\<packet_id>.json 및
   프로젝트 전용 E:\\SMC_Report_Platform_Data\\projects\\<project_slug>\\evidence\\<packet_id>.json
   양쪽에 등록해 이후 Stage 3 (kg-builder)가 이 분리 폴더의 source_id만 정확히 지식그래프로 넘긴다.
3. 모든 웹 URL 수집 전 robots.txt 확인, PII 자동 마스킹, 페이월·캡차 우회 금지 규약을 준수한다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from compliance import (
    SourcesRegistry,
    upsert_evidence_packet,
    utc_now_iso,
)
from config import PlatformConfig, get_config
from fetch_clean import fetch_and_clean_url
from fetch_scholar import (
    ingest_paper_record,
    search_crossref_korean_society,
    search_openalex_papers,
)

TIER_DIRS: dict[str, str] = {
    "domestic_agencies": "01_domestic_agencies",
    "domestic_journals": "02_domestic_journals",
    "international_agencies": "03_international_agencies",
    "international_journals": "04_international_journals",
}

TIER_LABELS_KO: dict[str, str] = {
    "domestic_agencies": "국내 기관·웹사이트",
    "domestic_journals": "국내 학회지·연구기관",
    "international_agencies": "해외 기관·국제기구·대학",
    "international_journals": "국제 SCI 저널·오픈액세스",
}

# 분야별 국내외 공식기관(robots.txt 허용 검증 완료) 및 학회지 프리셋
DOMAIN_PRESETS: dict[str, dict[str, Any]] = {
    "postharvest": {
        "topic_patterns": [
            r"수확\s*후", r"수확후", r"postharvest", r"저온\s*유통", r"콜드\s*체인", r"cold\s*chain", r"예냉", r"선도\s*유지",
        ],
        "match_terms": [
            "수확후", "수확 후", "예냉", "저온유통", "콜드체인",
            "선도유지", "에틸렌", "postharvest", "cold chain", "precooling", "1-mcp",
            "chilling injury", "controlled atmosphere",
        ],
        "required_terms": ["postharvest", "storage", "cold chain", "ethylene", "1-mcp", "수확후", "저장", "선도", "예냉"],
        "domestic_agencies": [
            {
                "name": "농촌진흥청 (RDA) 공식 포털",
                "url": "https://www.rda.go.kr/",
                "license_note": "대한민국 농촌진흥청 공개 웹자료 - 공공누리/변환적 분석 및 정식 인용",
            },
            {
                "name": "농촌진흥청 영농기술·보도자료",
                "url": "https://www.rda.go.kr/board/board.do?boardId=farmprmninfo&prgId=day_farmprmninfoEntry",
                "license_note": "대한민국 농촌진흥청 영농기술 보도자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "한국식품연구원 (KFRI) 저장·유통·품질연구",
                "url": "https://www.kfri.re.kr/",
                "license_note": "한국식품연구원 공개 웹자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "국립식량과학원 (NICS) 수확·품질관리",
                "url": "https://www.nics.go.kr/index.do",
                "license_note": "국립식량과학원 공개 웹자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "농림축산식품부 (MAFRA) 농산물 유통·품질 정책",
                "url": "https://www.mafra.go.kr/home/index.do",
                "license_note": "농림축산식품부 공개 정책 웹자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "식품의약품안전처 (MFDS) 농산물 안전·품질 기준",
                "url": "https://www.mfds.go.kr/index.do",
                "license_note": "식품의약품안전처 공개 기준 웹자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "한국농촌경제연구원 (KREI) 농산물 유통·수급 연구",
                "url": "https://www.krei.re.kr/krei/index.do",
                "license_note": "한국농촌경제연구원 공개 연구 포털 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "저온 유통 (Cold Chain) 기술 개요 — 한국어 위키백과",
                "url": "https://ko.wikipedia.org/wiki/%EC%BD%9C%EB%93%9C_%EC%B2%B4%EC%9D%B8",
                "license_note": "CC BY-SA 4.0 오픈 기술 백과 - 개념 대조 및 정식 인용",
            },
            {
                "name": "에틸렌 (Ethylene) 식물 생장·성숙 호르몬 — 한국어 위키백과",
                "url": "https://ko.wikipedia.org/wiki/%EC%97%90%ED%8B%B8%EB%A0%8C",
                "license_note": "CC BY-SA 4.0 오픈 기술 백과 - 개념 대조 및 정식 인용",
            },
        ],
        "domestic_journals": [
            {"journal": "Horticultural Science and Technology", "query": "postharvest storage quality ethylene fruit"},
            {"journal": "Korean Journal of Food Preservation", "query": "postharvest storage quality cold freshness"},
            {"journal": "Korean Journal of Food Science and Technology", "query": "postharvest storage quality fruit vegetable"},
            {"journal": "Food Science and Biotechnology", "query": "postharvest quality storage shelf life"},
        ],
        "domestic_openalex_queries": [
            "postharvest storage cold chain fruit vegetable quality",
            "1-MCP ethylene controlled atmosphere storage apple peach strawberry",
            "non-destructive near-infrared hyperspectral fruit quality brix firmness",
        ],
        "international_agencies": [
            {
                "name": "UN FAO Technical Platform on Measurement and Reduction of Food Loss and Waste",
                "url": "https://www.fao.org/platform-food-loss-waste/en/",
                "license_note": "UN FAO 공개 국제기구 자료 (CC BY-NC-SA 3.0 IGO) - 변환적 분석 및 정식 인용",
            },
            {
                "name": "UN FAO Food Loss and Waste (FLW) Database",
                "url": "https://www.fao.org/food-loss-and-food-waste/flw-data/en/",
                "license_note": "UN FAO 공개 데이터베이스 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "FAO/WHO Codex Alimentarius International Food & Fresh Produce Standards",
                "url": "https://www.fao.org/fao-who-codexalimentarius/en/",
                "license_note": "FAO/WHO Codex Alimentarius 국제 표준 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "University of Florida IFAS Extension — Ask IFAS: Postharvest and Handling",
                "url": "https://edis.ifas.ufl.edu/topics/postharvest",
                "license_note": "UF/IFAS Extension 미국 주립대 공개 기술 가이드 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "USDA Agricultural Research Service (ARS)",
                "url": "https://www.ars.usda.gov/",
                "license_note": "USDA ARS 미 연방 공공영역(Public Domain) 자료 - 정식 인용",
            },
            {
                "name": "USDA ARS National Programs (Food Quality & Postharvest)",
                "url": "https://www.ars.usda.gov/research/programs/",
                "license_note": "USDA ARS 미 연방 공공영역(Public Domain) 자료 - 정식 인용",
            },
            {
                "name": "Japan NARO Food Research Institute (NFRI, 일본 농연기구 식품연구부문)",
                "url": "https://www.naro.go.jp/english/laboratory/nfri/index.html",
                "license_note": "일본 농연기구(NARO) 공개 기관 자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "Japan MAFF (일본 농림수산성)",
                "url": "https://www.maff.go.jp/e/index.html",
                "license_note": "일본 농림수산성(MAFF) 공개 기관 자료 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "Postharvest Technology & Physiology Overview (Open Reference)",
                "url": "https://en.wikipedia.org/wiki/Postharvest",
                "license_note": "CC BY-SA 4.0 오픈 레퍼런스 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "Controlled Atmosphere (CA) Storage Technology (Open Reference)",
                "url": "https://en.wikipedia.org/wiki/Controlled_atmosphere",
                "license_note": "CC BY-SA 4.0 오픈 레퍼런스 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "Modified Atmosphere Packaging (MAP) Technology (Open Reference)",
                "url": "https://en.wikipedia.org/wiki/Modified_atmosphere",
                "license_note": "CC BY-SA 4.0 오픈 레퍼런스 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "1-Methylcyclopropene (1-MCP) Ethylene Action Inhibitor (Open Reference)",
                "url": "https://en.wikipedia.org/wiki/1-Methylcyclopropene",
                "license_note": "CC BY-SA 4.0 오픈 레퍼런스 - 변환적 분석 및 정식 인용",
            },
            {
                "name": "Cold Chain Logistics & Precooling Management (Open Reference)",
                "url": "https://en.wikipedia.org/wiki/Cold_chain",
                "license_note": "CC BY-SA 4.0 오픈 레퍼런스 - 변환적 분석 및 정식 인용",
            },
        ],
        "international_openalex_queries": [
            "postharvest management harvest maturity fruit vegetable quality",
            "precooling cold chain controlled atmosphere modified atmosphere storage",
            "ethylene 1-MCP ripening senescence chilling injury postharvest",
            "non-destructive near-infrared spectroscopy hyperspectral fruit quality firmness brix",
            "postharvest pathology decay fresh-cut shelf life food loss",
        ],
    },
    "wheat": {
        # 주제(topic)에 독립 작물 '밀'/'wheat'가 있을 때만 선택 ('메밀'/'buckwheat'/'정밀'/'밀도' 오매칭 차단)
        "topic_patterns": [
            r"(?<![가-힣])밀(?![가-힣])",
            r"(?<![가-힣])밀(?:의|을|은|이|과|와|에|재배|품종|수확)",
            r"(?<![a-z])wheat(?![a-z])",
            r"소맥",
            r"맥류",
        ],
        "match_terms": [
            "밀 재배", "밀 양분", "소맥", "맥류", "겨울밀", "우리밀",
            "wheat", "triticum", "winter wheat", "spring wheat",
        ],
        "exclude_topic_patterns": [r"메밀", r"buckwheat", r"fagopyrum"],
        # 논문 제목·초록에 아래 단어가 하나도 없으면 주제와 무관한 자료로 보고 수집하지 않는다
        "required_terms": ["wheat", "triticum", "밀", "소맥", "맥류", "cereal"],
        "domestic_agencies": [
            {"name": "국립식량과학원 (NICS)", "url": "https://www.nics.go.kr/index.do", "license_note": "국립식량과학원 공개 웹자료 - 변환적 분석 및 정식 인용"},
            {"name": "농사로 농업기술 포털", "url": "https://www.nongsaro.go.kr/portal/portalMain.ps?menuId=PS00001", "license_note": "농촌진흥청 농사로 공개 웹자료 - 변환적 분석 및 정식 인용"},
            {"name": "농촌진흥청 (RDA)", "url": "https://www.rda.go.kr/", "license_note": "농촌진흥청 공개 웹자료 - 변환적 분석 및 정식 인용"},
            {"name": "농림축산식품부 (MAFRA)", "url": "https://www.mafra.go.kr/home/index.do", "license_note": "농림축산식품부 공개 웹자료"},
            {"name": "한국농촌경제연구원 (KREI)", "url": "https://www.krei.re.kr/krei/index.do", "license_note": "한국농촌경제연구원 공개 웹자료"},
            {"name": "밀 - 위키백과", "url": "https://ko.wikipedia.org/wiki/%EB%B0%80", "license_note": "위키백과 CC BY-SA - 개요 참고용"},
        ],
        "domestic_journals": [
            {"journal": "Korean Journal of Crop Science", "query": "wheat cultivation yield"},
            {"journal": "Korean Journal of Breeding Science", "query": "wheat cultivar breeding"},
            {"journal": "Korean Journal of Agricultural and Forest Meteorology", "query": "wheat growth climate yield"},
            {"journal": "Korean Journal of Soil Science and Fertilizer", "query": "wheat nitrogen fertilization"},
            {"journal": "Food Science and Biotechnology", "query": "wheat flour quality"},
        ],
        "domestic_openalex_queries": [
            "wheat cultivation yield Korea",
            "wheat cultivar quality breeding Korea",
            "wheat flour processing quality Korea",
            "wheat remote sensing growth monitoring Korea",
        ],
        "international_agencies": [
            {"name": "CIMMYT", "url": "https://www.cimmyt.org/", "license_note": "CIMMYT 공개 자료"},
            {"name": "AHDB Wheat Growth Guide", "url": "https://ahdb.org.uk/wheatgrowthguide", "license_note": "AHDB 공개 자료 - 변환적 분석 및 정식 인용"},
            {"name": "USDA ERS Wheat", "url": "https://www.ers.usda.gov/topics/crops/wheat", "license_note": "USDA Public Domain"},
            {"name": "FAO Cereal Supply and Demand Brief", "url": "https://www.fao.org/worldfoodsituation/csdb/en/", "license_note": "UN FAO 공개 자료"},
            {"name": "Wheat - Wikipedia", "url": "https://en.wikipedia.org/wiki/Wheat", "license_note": "Wikipedia CC BY-SA - 개요 참고용"},
        ],
        "international_openalex_queries": [
            "wheat physiology phenology development",
            "wheat cultivar seed quality germination",
            "wheat sowing date seeding rate tillage",
            "winter wheat nitrogen topdressing management",
            "wheat fusarium head blight rust disease management",
            "wheat harvest grain moisture preharvest sprouting",
            "wheat grain storage postharvest quality",
            "global wheat production trade market",
            "wheat crop growth model APSIM DSSAT",
            "precision agriculture wheat remote sensing yield prediction",
            "wheat flour processing baking quality gluten",
        ],
    },
    "soil": {
        "match_terms": ["토양", "유기물", "부식", "비료", "바이오차", "soil", "organic matter", "biochar"],
        "domestic_agencies": [
            {"name": "농촌진흥청 (RDA)", "url": "https://www.rda.go.kr/", "license_note": "농촌진흥청 공개 웹자료"},
            {"name": "국립식량과학원 (NICS)", "url": "https://www.nics.go.kr/index.do", "license_note": "국립식량과학원 공개 웹자료"},
        ],
        "domestic_journals": [
            {"journal": "Korean Journal of Soil Science and Fertilizer", "query": "soil organic matter carbon nitrogen"},
            {"journal": "Korean Journal of Environmental Agriculture", "query": "soil organic carbon biochar"},
        ],
        "domestic_openalex_queries": ["soil organic matter carbon nitrogen Korea"],
        "international_agencies": [
            {"name": "USDA ARS", "url": "https://www.ars.usda.gov/", "license_note": "USDA ARS Public Domain"},
            {"name": "Japan NARO", "url": "https://www.naro.go.jp/english/laboratory/nfri/index.html", "license_note": "Japan NARO 공개 자료"},
        ],
        "international_openalex_queries": ["soil organic matter POM MAOM carbon sequestration"],
    },
    "onion": {
        "topic_patterns": [r"양파", r"onion", r"allium\s*cepa"],
        "match_terms": ["양파", "onion", "allium cepa", "구 비대", "점적관개", "스마트 관개", "bulbing"],
        "required_terms": [
            "onion", "allium", "양파", "evapotranspiration", "penman-monteith", "fao-56",
            "drip irrigation", "soil moisture", "tensiometer", "tdr", "fdr", "cwsi",
            "irrigation uniformity", "관개", "증발산", "토양수분",
        ],
        "domestic_agencies": [],
        "domestic_journals": [
            {"journal": "Horticultural Science and Technology", "query": "onion Allium cepa cultivation irrigation yield"},
            {"journal": "Korean Journal of Agricultural and Forest Meteorology", "query": "onion evapotranspiration irrigation temperature"},
            {"journal": "Korean Journal of Soil Science and Fertilizer", "query": "onion soil moisture drip irrigation fertilization"},
            {"journal": "Journal of Bio-Environment Control", "query": "onion smart farm sensor irrigation"},
        ],
        "domestic_openalex_queries": [
            "onion Allium cepa cultivation irrigation Korea",
            "onion bulb yield soil moisture fertilization Korea",
            "smart farm drip irrigation soil moisture sensor Korea",
        ],
        "international_agencies": [],
        "international_openalex_queries": [
            "onion Allium cepa drip irrigation evapotranspiration crop coefficient Kc",
            "FAO-56 Penman-Monteith reference evapotranspiration crop water requirement",
            "onion irrigation scheduling soil water tension tensiometer TDR FDR bulb yield",
            "drip irrigation emission uniformity Christiansen hydraulic design",
            "crop water stress index CWSI canopy temperature infrared irrigation scheduling",
            "onion smart farming precision agriculture sensor automated irrigation",
        ],
    },
    "crop_model": {
        "topic_patterns": [r"생육\s*모형", r"생육\s*모델", r"crop\s*growth\s*model", r"dssat", r"apsim", r"oryza"],
        "match_terms": ["생육모형", "생육모델", "작물모형", "crop growth model", "dssat", "apsim", "wofost", "aquacrop"],
        "required_terms": ["crop model", "growth model", "dssat", "apsim", "wofost", "aquacrop", "simulation", "생육모형", "작물모형", "생육"],
        "domestic_agencies": [],
        "domestic_journals": [
            {"journal": "Korean Journal of Agricultural and Forest Meteorology", "query": "crop growth model simulation yield climate"},
            {"journal": "Korean Journal of Crop Science", "query": "crop model phenology biomass yield"},
        ],
        "domestic_openalex_queries": ["crop growth model DSSAT APSIM ORYZA Korea"],
        "international_agencies": [],
        "international_openalex_queries": [
            "crop growth model DSSAT APSIM WOFOST calibration validation review",
            "crop simulation model climate change yield prediction uncertainty",
            "process-based crop model data assimilation remote sensing",
        ],
    },
    "3d_vision": {
        "topic_patterns": [r"3차원", r"3d\s*image", r"3d\s*reconstruction", r"포인트\s*클라우드", r"point\s*cloud", r"nerf", r"gaussian\s*splatting"],
        "match_terms": ["3차원", "3d image", "3d reconstruction", "point cloud", "photogrammetry", "lidar", "phenotyping", "표현형"],
        "required_terms": ["3d", "point cloud", "reconstruction", "lidar", "photogrammetry", "phenotyping", "nerf", "depth", "rgb-d", "3차원", "표현형"],
        "domestic_agencies": [],
        "domestic_journals": [
            {"journal": "Journal of Biosystems Engineering", "query": "3D crop phenotyping point cloud reconstruction"},
            {"journal": "Korean Journal of Agricultural Science", "query": "3D imaging plant phenotyping deep learning"},
        ],
        "domestic_openalex_queries": ["3D crop phenotyping point cloud RGB-D LiDAR Korea"],
        "international_agencies": [],
        "international_openalex_queries": [
            "3D plant phenotyping point cloud reconstruction deep learning review",
            "crop 3D reconstruction multi-view stereo NeRF Gaussian splatting agriculture",
            "RGB-D LiDAR 3D crop morphology biomass volume estimation accuracy",
        ],
    },
    "general": {
        "match_terms": [],
        "domestic_agencies": [
            {"name": "농촌진흥청 (RDA)", "url": "https://www.rda.go.kr/", "license_note": "농촌진흥청 공개 웹자료"},
            {"name": "한국식품연구원 (KFRI)", "url": "https://www.kfri.re.kr/", "license_note": "한국식품연구원 공개 웹자료"},
            {"name": "농림축산식품부 (MAFRA)", "url": "https://www.mafra.go.kr/home/index.do", "license_note": "농림축산식품부 공개 웹자료"},
            {"name": "한국농촌경제연구원 (KREI)", "url": "https://www.krei.re.kr/krei/index.do", "license_note": "한국농촌경제연구원 공개 웹자료"},
        ],
        "domestic_journals": [
            {"journal": "Horticultural Science and Technology", "query": ""},
            {"journal": "Korean Journal of Food Preservation", "query": ""},
            {"journal": "Korean Journal of Soil Science and Fertilizer", "query": ""},
        ],
        "domestic_openalex_queries": [],
        "international_agencies": [
            {"name": "UN FAO", "url": "https://www.fao.org/platform-food-loss-waste/en/", "license_note": "UN FAO 공개 자료"},
            {"name": "USDA ARS", "url": "https://www.ars.usda.gov/", "license_note": "USDA ARS Public Domain"},
            {"name": "Japan NARO NFRI", "url": "https://www.naro.go.jp/english/laboratory/nfri/index.html", "license_note": "Japan NARO 공개 자료"},
        ],
        "international_openalex_queries": [],
    },
}


def _term_in_text(term: str, text_low: str) -> bool:
    """영문 용어는 단어 경계(buckwheat!=wheat)를 지키고, 국문 용어는 직접 매칭한다."""
    t = (term or "").strip().lower()
    if not t:
        return False
    if re.fullmatch(r"[a-z0-9\-\s/]+", t):
        return bool(re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", text_low))
    return t in text_low


def detect_domain_preset(
    topic_ko: str,
    topic_en: str = "",
    keywords_ko: list[str] | None = None,
    keywords_en: list[str] | None = None,
) -> str:
    """주제와 키워드를 분석해 가장 적합한 국내외 기관·학회지 수집 프리셋을 선택한다."""
    blob = " ".join([topic_ko, topic_en, *(keywords_ko or []), *(keywords_en or [])]).lower()
    topic_blob = f" {topic_ko} {topic_en} ".lower()
    best_name = "general"
    best_score = 0
    for name, spec in DOMAIN_PRESETS.items():
        if name == "general":
            continue
        if any(re.search(pat, topic_blob) for pat in spec.get("exclude_topic_patterns", [])):
            continue
        score = sum(1 for term in spec.get("match_terms", []) if _term_in_text(term, blob))
        # 주제명 자체에 프리셋 핵심어가 있으면 크게 가산 (예: '디지털 밀 재배'의 목차에 '수확'이 있어도 밀 프리셋 선택)
        score += 10 * sum(1 for pat in spec.get("topic_patterns", []) if re.search(pat, topic_blob))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _copy_source_files_to_tier(
    *,
    tier_dir: Path,
    source_id: str,
    parsed_path: str | None,
    raw_path: str | None = None,
) -> list[str]:
    """수집된 정제 마크다운(및 표 JSON/원본 PDF·메타)을 프로젝트 분리 폴더로 복사한다."""
    tier_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if parsed_path and Path(parsed_path).is_file():
        p = Path(parsed_path)
        dst = tier_dir / p.name
        shutil.copy2(p, dst)
        copied.append(str(dst))
        tbl_p = p.with_name(f"{p.stem}_tables.json")
        if tbl_p.is_file():
            dst_t = tier_dir / tbl_p.name
            shutil.copy2(tbl_p, dst_t)
            copied.append(str(dst_t))
    if raw_path and Path(raw_path).is_file():
        rp = Path(raw_path)
        if rp.suffix.lower() in (".pdf", ".json"):
            dst_r = tier_dir / (rp.name if rp.name.startswith(source_id) else f"{source_id}_{rp.name}")
            shutil.copy2(rp, dst_r)
            copied.append(str(dst_r))
    return copied


# 기관 홈페이지 첫 화면(탐색 전용, 근거 목록 제외) 판별 규칙 (C1)
PORTAL_HOMEPAGE_PATHS = {"", "/", "/index.do", "/index.html", "/index.htm", "/home/index.do", "/krei/index.do", "/e/index.html", "/en/", "/english/laboratory/nfri/index.html"}


def is_portal_homepage_url(url: str) -> bool:
    """기관 홈페이지 첫 화면(루트·인덱스 URL) 여부를 판별한다 (탐색용으로만 쓰고 인용 근거에서 제외, C1)."""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return False
    parsed = urllib.parse.urlparse(u)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if path in PORTAL_HOMEPAGE_PATHS and not parsed.query:
        return True
    if any(h in host for h in ("rda.go.kr", "kfri.re.kr", "nics.go.kr", "mafra.go.kr", "mfds.go.kr", "krei.re.kr", "ars.usda.gov", "maff.go.jp", "naro.go.jp")):
        if path in PORTAL_HOMEPAGE_PATHS or path.endswith(("/index.do", "/index.html", "/home/", "/research/programs/")):
            return True
    if "wikipedia.org/wiki/" in u.lower():
        return True
    return False


def _cosine_sim_vec(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return (dot / (na * nb)) if (na > 0 and nb > 0) else 0.0


class TopicRelevanceScorer:
    """로컬 Ollama bge-m3 임베딩(+어휘 폴백) 기반 주제 관련도 평가기 (C1: 기수집 연계 포함 전수 필터)."""

    def __init__(self, topic_query: str, cfg: PlatformConfig | None = None, min_threshold: float = 0.42):
        self.topic_query = (topic_query or "").strip()
        self.cfg = cfg or get_config()
        self.min_threshold = float(min_threshold)
        self._query_vec: list[float] | None = None
        self._embed_available: bool | None = None
        self._query_tokens = {t.lower() for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", self.topic_query)}

    def _ensure_query_vec(self) -> bool:
        if self._embed_available is not None:
            return self._embed_available
        try:
            from local_gemma import LocalGemmaClient

            vecs = LocalGemmaClient(self.cfg).embed([self.topic_query[:1000]], timeout=25)
            if vecs and vecs[0]:
                self._query_vec = vecs[0]
                self._embed_available = True
                return True
        except Exception:
            pass
        self._embed_available = False
        return False

    def score(self, title: str, text_snippet: str = "") -> tuple[float, str]:
        cand = f"{title or ''}\n{(text_snippet or '')[:1000]}".strip()
        if not cand:
            return 0.0, "empty"
        if self._ensure_query_vec() and self._query_vec:
            try:
                from local_gemma import LocalGemmaClient

                vecs = LocalGemmaClient(self.cfg).embed([cand], timeout=25)
                if vecs and vecs[0]:
                    sim = _cosine_sim_vec(self._query_vec, vecs[0])
                    return round(sim, 4), "bge-m3"
            except Exception:
                pass
        cand_tokens = {t.lower() for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", cand)}
        if not self._query_tokens or not cand_tokens:
            return 0.0, "lexical"
        overlap = len(self._query_tokens & cand_tokens) / max(1, min(len(self._query_tokens), 8))
        return round(min(1.0, overlap), 4), "lexical"

    def is_relevant(self, title: str, text_snippet: str = "") -> tuple[bool, float, str]:
        sc, method = self.score(title, text_snippet)
        thr = self.min_threshold if method == "bge-m3" else 0.18
        return sc >= thr, sc, method


def _ensure_duplicate_in_packet(
    *,
    existing_rec: dict[str, Any],
    packet_id: str,
    topic: str,
    cfg: PlatformConfig,
) -> dict[str, Any]:
    """전역 sources.jsonl에 이미 존재하는 자료도 현재 프로젝트의 근거 패킷에 안전하게 연결한다."""
    sid = existing_rec.get("source_id", "")
    parsed_path = existing_rec.get("parsed_path", "")
    pkt_path = cfg.evidence_dir / f"{packet_id}.json"
    if not sid:
        return {}

    from compliance import chunk_korean_text

    text = Path(parsed_path).read_text(encoding="utf-8", errors="ignore") if parsed_path and Path(parsed_path).is_file() else ""
    chunks = chunk_korean_text(text, default_section=existing_rec.get("journal") or "본문") if text else []
    source_item = {
        "source_id": sid,
        "source_type": existing_rec.get("source_type", "web"),
        "url": existing_rec.get("url", ""),
        "title": existing_rec.get("title", sid),
        "accessed_at": existing_rec.get("accessed_at") or utc_now_iso(),
        "robots_allowed": bool(existing_rec.get("robots_allowed", True)),
        "robots_status": existing_rec.get("robots_status", "reused_from_registry"),
        "license_note": existing_rec.get("license_note") or "기수집 1차 자료 재연결 - 변환적 분석 및 정식 인용",
        "page_or_section": existing_rec.get("journal") or "본문",
        "raw_path": existing_rec.get("raw_path", ""),
        "parsed_path": parsed_path,
        "pii_masked": True,
        "pii_redaction_count": int(existing_rec.get("pii_redaction_count") or 0),
        "prompt_injection_warnings": existing_rec.get("prompt_injection_warnings") or [],
        "sha256": existing_rec.get("sha256", ""),
        "extracted_facts": [],
        "tables": [],
        "chunks": chunks,
    }
    upsert_evidence_packet(
        packet_path=pkt_path,
        source_item=source_item,
        packet_id=packet_id,
        topic=topic,
        storage_root=str(cfg.collected_data_root),
        kg_store_root=str(cfg.smc_graphrag_root),
        schema_path=cfg.evidence_schema_path,
    )
    return source_item


def _write_collection_index_md(manifest: dict[str, Any], out_path: Path) -> None:
    """분리 저장된 4계층 자료 전체 목록을 사람이 읽기 쉬운 INDEX.md로 작성한다."""
    bd = manifest["breakdown"]
    lines = [
        f"# {manifest['topic_ko']} — 국내외 학술·기관 수집 자료 분리 저장소 인덱스",
        "",
        f"- **프로젝트 ID**: `{manifest['project_id']}`",
        f"- **적용 분야 프리셋**: `{manifest['preset']}`",
        f"- **생성 시각**: `{manifest['generated_at']}`",
        f"- **분리 저장 폴더 (`E:\\`)**: `{manifest['collected_root']}`",
        f"- **프로젝트 전용 근거 패킷**: `{manifest['project_evidence_path']}`",
        f"- **총 확보 자료 수**: **{manifest['total_collected']}건** "
        f"(국내기관 {bd['domestic_agencies']}건 · 국내학회 {bd['domestic_journals']}건 · "
        f"해외기관 {bd['international_agencies']}건 · 국제SCI {bd['international_journals']}건)",
        "",
    ]
    for tier_key, folder_name in TIER_DIRS.items():
        tier_items = [s for s in manifest["sources"] if s.get("tier") == tier_key]
        lines.append(f"## {folder_name} — {TIER_LABELS_KO[tier_key]} ({len(tier_items)}건)")
        lines.append("")
        if not tier_items:
            lines.append("_해당 분류 수집 자료 없음_")
            lines.append("")
            continue
        lines.append("| 출처 ID | 제공처 / 기관 | 연도 | 피인용 | 제목 | 저장 파일명 |")
        lines.append("| :--- | :--- | :---: | :---: | :--- | :--- |")
        for s in tier_items:
            title_safe = str(s.get("title", "")).replace("|", "/")[:90]
            fname = Path(s["saved_files"][0]).name if s.get("saved_files") else "-"
            lines.append(
                f"| `{s.get('source_id', '')}` | {str(s.get('provider', '')).replace('|', '/')} "
                f"| {s.get('year') or '-'} | {s.get('cited_by_count', 0)} "
                f"| [{title_safe}]({s.get('url', '')}) | `{fname}` |"
            )
        lines.append("")

    if manifest.get("blocked_or_failed"):
        lines.append("## robots.txt 제한 또는 접속 불가로 건너뛴 항목 (준법 기록)")
        lines.append("")
        for b in manifest["blocked_or_failed"]:
            lines.append(f"- `{b.get('tier', '')}` | {b.get('url', '')} — **{b.get('status', '')}**: {b.get('reason', '')}")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def collect_project_sources(
    *,
    project_id: str,
    topic_ko: str,
    topic_en: str = "",
    keywords_ko: list[str] | None = None,
    keywords_en: list[str] | None = None,
    packet_id: str | None = None,
    papers_per_query: int = 5,
    domestic_agency_urls: list[str] | None = None,
    international_agency_urls: list[str] | None = None,
    download_oa_pdf: bool = True,
    max_pdf_downloads: int = 4,
    progress_cb: Callable[[int, str, str, str], None] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """4계층(국내기관·국내학회·해외기관·국제SCI) 자료를 프로젝트 전용 폴더에 분리 수집·저장한다."""
    cfg = cfg or get_config()
    packet_id = packet_id or f"{project_id}_evidence"
    kw_ko = [k.strip() for k in (keywords_ko or []) if k.strip()] or [topic_ko]
    kw_en = [k.strip() for k in (keywords_en or []) if k.strip()] or ([topic_en] if topic_en else [topic_ko])

    preset_name = detect_domain_preset(topic_ko, topic_en, kw_ko, kw_en)
    preset = DOMAIN_PRESETS[preset_name]

    collected_root = cfg.project_collected_dir(project_id)
    tier_paths: dict[str, Path] = {}
    for tkey, tdir_name in TIER_DIRS.items():
        p = collected_root / tdir_name
        p.mkdir(parents=True, exist_ok=True)
        tier_paths[tkey] = p

    proj_e_evidence_dir = cfg.project_e_evidence_dir(project_id)
    proj_e_evidence_dir.mkdir(parents=True, exist_ok=True)
    ws_collected_dir = cfg.project_dir(project_id) / "collected"
    ws_collected_dir.mkdir(parents=True, exist_ok=True)

    def _emit(pct: int, action: str, msg: str, level: str = "INFO") -> None:
        if progress_cb:
            progress_cb(pct, action, msg, level)

    collected_sources: list[dict[str, Any]] = []
    seen_sids: set[str] = set()
    blocked_or_failed: list[dict[str, Any]] = []
    pdf_downloaded_count = 0

    # C1: 주제별 자료 격리 — bge-m3 유사도 평가기 초기화 (기수집 연계 포함 전수 필터)
    topic_query_str = " ".join([topic_ko, topic_en, *kw_ko[:6], *kw_en[:6]]).strip()
    relevance_scorer = TopicRelevanceScorer(topic_query_str, cfg=cfg, min_threshold=0.42)

    def _register_collected(rec: dict[str, Any]) -> None:
        sid = rec.get("source_id", "")
        if sid and sid not in seen_sids:
            seen_sids.add(sid)
            collected_sources.append(rec)

    def _collect_web_tier(tier_key: str, entries: list[dict[str, str]], start_pct: int, end_pct: int) -> None:
        t_dir = tier_paths[tier_key]
        t_label = TIER_LABELS_KO[tier_key]
        total_n = max(1, len(entries))
        for idx, entry in enumerate(entries, 1):
            url = (entry.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            name = entry.get("name") or url
            # C1: 기관 홈페이지 첫 화면·위키백과 개괄은 탐색용으로만 기록하고 근거 패킷에서 제외
            if is_portal_homepage_url(url) and not entry.get("force_citable"):
                blocked_or_failed.append(
                    {
                        "tier": tier_key,
                        "url": url,
                        "status": "PORTAL_DISCOVERY_ONLY",
                        "reason": "기관 홈페이지 첫 화면/위키 개괄은 탐색용으로만 사용하고 인용 근거 목록에서 제외 (C1)",
                    }
                )
                _emit(start_pct, f"{t_label} 탐색 전용 제외", f"[C1] 기관 첫 화면/개괄 URL 근거 제외: {name} ({url})", "INFO")
                continue
            lic = entry.get("license_note") or f"{t_label} 공개 웹자료 - 변환적 분석 및 정식 인용"
            pct = start_pct + int((idx / total_n) * max(1, end_pct - start_pct))
            try:
                res = fetch_and_clean_url(
                    url=url,
                    packet_id=packet_id,
                    topic=topic_ko,
                    license_note=lic,
                    use_crawl4ai=False,
                    extract_facts=False,
                    force=False,
                    cfg=cfg,
                )
                status = res.get("status", "")
                if status == "OK":
                    sid = res["source_id"]
                    parsed_txt = ""
                    if res.get("parsed_path") and Path(res["parsed_path"]).is_file():
                        parsed_txt = Path(res["parsed_path"]).read_text(encoding="utf-8", errors="ignore")[:1200]
                    is_rel, rel_score, rel_method = relevance_scorer.is_relevant(res.get("title") or name, parsed_txt)
                    if not is_rel:
                        blocked_or_failed.append(
                            {
                                "tier": tier_key,
                                "url": url,
                                "status": "OFF_TOPIC_LOW_RELEVANCE",
                                "reason": f"주제 관련도 미달 ({rel_method}={rel_score:.3f})",
                            }
                        )
                        _emit(pct, f"{t_label} 관련도 제외", f"[C1] 주제 관련도 미달({rel_score:.2f}) 제외: {name}", "WARN")
                        continue
                    saved = _copy_source_files_to_tier(
                        tier_dir=t_dir,
                        source_id=sid,
                        parsed_path=res.get("parsed_path"),
                        raw_path=res.get("raw_path"),
                    )
                    _register_collected(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": t_label,
                            "title": res.get("title") or name,
                            "journal": name,
                            "year": None,
                            "cited_by_count": 0,
                            "url": url,
                            "provider": t_label,
                            "robots_status": res.get("robots_status", "allowed"),
                            "license_note": lic,
                            "relevance_score": rel_score,
                            "relevance_method": rel_method,
                            "status": "OK",
                            "saved_files": saved,
                        }
                    )
                    _emit(pct, f"{t_label} 수집 중 ({idx}/{total_n})", f"[{TIER_DIRS[tier_key]}] 수집 완료 [{sid}] {name} (관련도 {rel_score:.2f})")
                elif status == "SKIPPED_DUPLICATE" and res.get("existing"):
                    ex = res["existing"]
                    sid = ex.get("source_id", "")
                    ex_txt = ""
                    if ex.get("parsed_path") and Path(ex["parsed_path"]).is_file():
                        ex_txt = Path(ex["parsed_path"]).read_text(encoding="utf-8", errors="ignore")[:1200]
                    # C1 핵심 수정: 기수집 연계 자료도 현재 주제와의 관련도(bge-m3)를 반드시 검증!
                    is_rel, rel_score, rel_method = relevance_scorer.is_relevant(ex.get("title") or name, ex_txt)
                    if not is_rel:
                        blocked_or_failed.append(
                            {
                                "tier": tier_key,
                                "url": url,
                                "status": "OFF_TOPIC_REUSE_BLOCKED",
                                "reason": f"기수집 연계 자료 주제 무관 차단 ({rel_method}={rel_score:.3f}, [{sid}])",
                            }
                        )
                        _emit(pct, f"{t_label} 기수집 격리", f"[C1] 주제 무관 기수집 자료 차단 [{sid}] {ex.get('title', name)[:50]} ({rel_score:.2f})", "WARN")
                        continue
                    _ensure_duplicate_in_packet(existing_rec=ex, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                    saved = _copy_source_files_to_tier(
                        tier_dir=t_dir,
                        source_id=sid,
                        parsed_path=ex.get("parsed_path"),
                        raw_path=ex.get("raw_path"),
                    )
                    _register_collected(
                        {
                            "source_id": sid,
                            "tier": tier_key,
                            "tier_folder": TIER_DIRS[tier_key],
                            "tier_label": t_label,
                            "title": ex.get("title") or name,
                            "journal": name,
                            "year": ex.get("year"),
                            "cited_by_count": 0,
                            "url": url,
                            "provider": f"{t_label} (기수집 연계)",
                            "robots_status": ex.get("robots_status", "allowed"),
                            "license_note": lic,
                            "relevance_score": rel_score,
                            "relevance_method": rel_method,
                            "status": "REUSED",
                            "saved_files": saved,
                        }
                    )
                    _emit(pct, f"{t_label} 연계 중 ({idx}/{total_n})", f"[{TIER_DIRS[tier_key]}] 기수집 자료 관련도 검증 통과({rel_score:.2f}) [{sid}] {name}")
                else:
                    blocked_or_failed.append(
                        {
                            "tier": tier_key,
                            "url": url,
                            "status": status or "SKIPPED",
                            "reason": str(res.get("robots_status") or res.get("reason") or "접근 제한"),
                        }
                    )
                    _emit(pct, f"{t_label} 준법 점검", f"[{TIER_DIRS[tier_key]}] robots.txt/접근 제한으로 건너뜀: {url}", "WARN")
            except Exception as exc:
                blocked_or_failed.append({"tier": tier_key, "url": url, "status": "ERROR", "reason": str(exc)[:180]})
                _emit(pct, f"{t_label} 수집 경고", f"[{TIER_DIRS[tier_key]}] 수집 오류({name}): {str(exc)[:110]}", "WARN")

    def _ingest_papers_into_tier(tier_key: str, papers: list[dict[str, Any]], provider_label: str, pct: int) -> None:
        nonlocal pdf_downloaded_count
        t_dir = tier_paths[tier_key]
        t_label = TIER_LABELS_KO[tier_key]
        req_terms = [x.lower() for x in preset.get("required_terms", [])]
        for p in papers:
            p_title = str(p.get("title") or "").strip()
            p_abs = str(p.get("abstract") or "").strip()
            if req_terms:
                hay = f"{p_title} {p_abs}".lower()
                if not any(term in hay for term in req_terms):
                    blocked_or_failed.append({"tier": tier_key, "url": p.get("url", ""), "status": "OFF_TOPIC", "reason": "주제 핵심어 없음"})
                    _emit(pct, f"{t_label} 주제 적합도 검사", f"주제와 무관하여 제외: {p_title[:70]}", "WARN")
                    continue
            # C1: 제목·초록 의미 관련도(bge-m3) 검사
            is_rel, rel_score, rel_method = relevance_scorer.is_relevant(p_title, p_abs)
            if not is_rel:
                blocked_or_failed.append(
                    {
                        "tier": tier_key,
                        "url": p.get("url", ""),
                        "status": "OFF_TOPIC_LOW_RELEVANCE",
                        "reason": f"제목·초록 관련도 미달 ({rel_method}={rel_score:.3f})",
                    }
                )
                _emit(pct, f"{t_label} 관련도 필터", f"[C1] 관련도 미달({rel_score:.2f}) 제외: {p_title[:65]}", "WARN")
                continue
            want_pdf = bool(download_oa_pdf and p.get("pdf_url") and pdf_downloaded_count < max_pdf_downloads)
            try:
                res = ingest_paper_record(
                    paper=p,
                    packet_id=packet_id,
                    topic=topic_ko,
                    download_oa_pdf=want_pdf,
                    force=False,
                    cfg=cfg,
                )
            except Exception as exc:
                blocked_or_failed.append({"tier": tier_key, "url": p.get("url", ""), "status": "ERROR", "reason": str(exc)[:160]})
                continue

            status = res.get("status", "")
            if status == "OK" and res.get("source_id"):
                sid = res["source_id"]
                if res.get("pdf_downloaded"):
                    pdf_downloaded_count += 1
                reg_rec = SourcesRegistry(cfg.sources_registry_path).find_duplicate(url=p.get("url")) or {}
                saved = _copy_source_files_to_tier(
                    tier_dir=t_dir,
                    source_id=sid,
                    parsed_path=res.get("parsed_path"),
                    raw_path=reg_rec.get("raw_path"),
                )
                _register_collected(
                    {
                        "source_id": sid,
                        "tier": tier_key,
                        "tier_folder": TIER_DIRS[tier_key],
                        "tier_label": t_label,
                        "title": p_title,
                        "journal": p.get("journal", ""),
                        "year": p.get("year"),
                        "cited_by_count": p.get("cited_by_count", 0),
                        "url": p.get("url", ""),
                        "provider": provider_label,
                        "pdf_downloaded": bool(res.get("pdf_downloaded")),
                        "relevance_score": rel_score,
                        "relevance_method": rel_method,
                        "status": "OK",
                        "saved_files": saved,
                    }
                )
                pdf_tag = " [OA PDF]" if res.get("pdf_downloaded") else ""
                _emit(pct, f"{t_label} 적재 중", f"[{TIER_DIRS[tier_key]}] 수집 [{sid}] {p_title[:65]} ({p.get('year') or '-'}, 관련도 {rel_score:.2f}){pdf_tag}")
            elif status == "SKIPPED_DUPLICATE" and res.get("existing"):
                ex = res["existing"]
                sid = ex.get("source_id", "")
                ex_title = p_title or ex.get("title", "")
                ex_txt = p_abs
                if not ex_txt and ex.get("parsed_path") and Path(ex["parsed_path"]).is_file():
                    ex_txt = Path(ex["parsed_path"]).read_text(encoding="utf-8", errors="ignore")[:1000]
                is_rel_ex, rel_score_ex, rel_method_ex = relevance_scorer.is_relevant(ex_title, ex_txt)
                if not is_rel_ex:
                    blocked_or_failed.append(
                        {
                            "tier": tier_key,
                            "url": p.get("url") or ex.get("url", ""),
                            "status": "OFF_TOPIC_REUSE_BLOCKED",
                            "reason": f"기수집 논문 주제 무관 차단 ({rel_method_ex}={rel_score_ex:.3f}, [{sid}])",
                        }
                    )
                    _emit(pct, f"{t_label} 기수집 격리", f"[C1] 주제 무관 기수집 논문 차단 [{sid}] {ex_title[:60]} ({rel_score_ex:.2f})", "WARN")
                    continue
                _ensure_duplicate_in_packet(existing_rec=ex, packet_id=packet_id, topic=topic_ko, cfg=cfg)
                saved = _copy_source_files_to_tier(
                    tier_dir=t_dir,
                    source_id=sid,
                    parsed_path=ex.get("parsed_path"),
                    raw_path=ex.get("raw_path"),
                )
                _register_collected(
                    {
                        "source_id": sid,
                        "tier": tier_key,
                        "tier_folder": TIER_DIRS[tier_key],
                        "tier_label": t_label,
                        "title": ex_title,
                        "journal": p.get("journal") or ex.get("journal", ""),
                        "year": p.get("year") or ex.get("year"),
                        "cited_by_count": p.get("cited_by_count") or ex.get("cited_by_count", 0),
                        "url": p.get("url") or ex.get("url", ""),
                        "provider": f"{provider_label} (기수집 연계)",
                        "pdf_downloaded": False,
                        "relevance_score": rel_score_ex,
                        "relevance_method": rel_method_ex,
                        "status": "REUSED",
                        "saved_files": saved,
                    }
                )

    # ===== TIER 1: 국내 공식기관 및 웹사이트 (01_domestic_agencies) =====
    _emit(8, "1/4 국내 공식기관·웹사이트 수집 시작...", f"분리 저장 폴더 초기화: {collected_root} (적용 프리셋: {preset_name})")
    dom_entries = list(preset.get("domestic_agencies", []))
    for u in (domestic_agency_urls or []):
        u = u.strip()
        if u and not any(e["url"] == u for e in dom_entries):
            dom_entries.append({"name": f"사용자 지정 국내 기관 ({u[:45]})", "url": u, "license_note": "사용자 지정 국내 기관 공개 웹자료"})
    _collect_web_tier("domestic_agencies", dom_entries, 10, 28)

    # ===== TIER 2: 국내 학회지 및 국내 연구기관 논문 (02_domestic_journals) =====
    _emit(30, "2/4 국내 학회지(Crossref) 및 한국 기관 연구(OpenAlex KR) 수집 중...", "국내 핵심 학회지 및 국내 대학·연구소 학술 논문 탐색 시작")
    en_base_query = " ".join(kw_en[:4]) or topic_en or topic_ko
    kr_journal_specs = list(preset.get("domestic_journals", []))
    per_kr_j = max(2, min(4, papers_per_query))
    for spec in kr_journal_specs:
        jname = spec["journal"]
        q = spec.get("query") or en_base_query
        try:
            papers_kr = search_crossref_korean_society(query=q, limit=per_kr_j, journal_name=jname)
            _ingest_papers_into_tier("domestic_journals", papers_kr, f"Crossref ({jname})", 38)
        except Exception as exc:
            _emit(38, "국내 학회지 검색 경고", f"Crossref({jname}) 경고: {exc}", "WARN")

    kr_oa_queries = list(preset.get("domestic_openalex_queries", [])) or [en_base_query]
    for q in kr_oa_queries:
        try:
            papers_kr_oa = search_openalex_papers(query=q, limit=max(3, papers_per_query), scope="korea_all", sort="cited_by_count:desc")
            _ingest_papers_into_tier("domestic_journals", papers_kr_oa, "OpenAlex (국내 연구기관 KR)", 48)
        except Exception as exc:
            _emit(48, "OpenAlex KR 검색 경고", f"OpenAlex KR({q[:40]}) 경고: {exc}", "WARN")

    # ===== TIER 3: 해외 공식기관·국제기구·대학 웹사이트 (03_international_agencies) =====
    _emit(52, "3/4 국제기구·해외 공식기관·대학 웹사이트 수집 중...", "FAO · USDA ARS · UF/IFAS · 일본 NARO/MAFF 등 해외 기관 자료 수집 시작")
    intl_entries = list(preset.get("international_agencies", []))
    for u in (international_agency_urls or []):
        u = u.strip()
        if u and not any(e["url"] == u for e in intl_entries):
            intl_entries.append({"name": f"사용자 지정 해외 기관 ({u[:45]})", "url": u, "license_note": "사용자 지정 해외 기관 공개 웹자료"})
    _collect_web_tier("international_agencies", intl_entries, 54, 74)

    # ===== TIER 4: 국제 핵심 SCI 저널·오픈액세스 논문 (04_international_journals) =====
    _emit(76, "4/4 국제 SCI 저널 및 오픈액세스 학술 논문 수집 중...", "OpenAlex 다중 세부 쿼리로 국제 SCI 핵심 논문 및 오픈액세스 자료 확보 시작")
    intl_queries = list(preset.get("international_openalex_queries", [])) or [en_base_query]
    if en_base_query not in intl_queries and len(intl_queries) < 5:
        intl_queries.append(en_base_query)
    per_intl_q = max(3, min(6, papers_per_query))
    for q_idx, q in enumerate(intl_queries, 1):
        pct = 78 + int((q_idx / max(1, len(intl_queries))) * 16)
        try:
            papers_intl = search_openalex_papers(query=q, limit=per_intl_q, scope="all", sort="cited_by_count:desc")
            _ingest_papers_into_tier("international_journals", papers_intl, "OpenAlex (국제 SCI)", pct)
        except Exception as exc:
            _emit(pct, "국제 SCI 검색 경고", f"OpenAlex({q[:40]}) 경고: {exc}", "WARN")

    # 프로젝트 전용 근거 패킷 미러 동기화 (E:\SMC_Report_Platform_Data\projects\<slug>\evidence\)
    global_pkt_path = cfg.evidence_dir / f"{packet_id}.json"
    proj_pkt_path = proj_e_evidence_dir / f"{packet_id}.json"
    if global_pkt_path.is_file():
        shutil.copy2(global_pkt_path, proj_pkt_path)

    breakdown = {
        tkey: sum(1 for s in collected_sources if s.get("tier") == tkey)
        for tkey in TIER_DIRS
    }
    manifest = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "topic_en": topic_en or topic_ko,
        "preset": preset_name,
        "generated_at": utc_now_iso(),
        "collected_root": str(collected_root),
        "tier_directories": {k: str(v) for k, v in tier_paths.items()},
        "global_evidence_path": str(global_pkt_path),
        "project_evidence_path": str(proj_pkt_path),
        "packet_id": packet_id,
        "total_collected": len(collected_sources),
        "pdf_downloaded_count": pdf_downloaded_count,
        "breakdown": breakdown,
        "source_ids": [s["source_id"] for s in collected_sources if s.get("source_id")],
        "sources": collected_sources,
        "blocked_or_failed": blocked_or_failed,
    }

    e_manifest_path = collected_root / "collection_manifest.json"
    e_index_path = collected_root / "INDEX.md"
    ws_manifest_path = ws_collected_dir / "collection_manifest.json"
    ws_index_path = ws_collected_dir / "INDEX.md"

    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    e_manifest_path.write_text(manifest_json, encoding="utf-8")
    ws_manifest_path.write_text(manifest_json, encoding="utf-8")
    _write_collection_index_md(manifest, e_index_path)
    _write_collection_index_md(manifest, ws_index_path)

    _emit(
        100,
        f"4계층 분리 수집 완료 (총 {len(collected_sources)}건 → 지식그래프 인계 준비 완료)",
        f"분리 저장 완료: 국내기관 {breakdown['domestic_agencies']}건 · 국내학회 {breakdown['domestic_journals']}건 · "
        f"해외기관 {breakdown['international_agencies']}건 · 국제SCI {breakdown['international_journals']}건 "
        f"(폴더: {collected_root})",
    )
    return {
        "manifest": manifest,
        "manifest_path": str(e_manifest_path),
        "workspace_manifest_path": str(ws_manifest_path),
        "index_md_path": str(e_index_path),
        "workspace_index_md_path": str(ws_index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="국내외 기관·웹사이트·학회지·SCI 4계층 프로젝트 분리 수집기")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--topic-en", default="")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--keywords-en", default="")
    parser.add_argument("--papers-per-query", type=int, default=4)
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()

    res = collect_project_sources(
        project_id=args.project_id,
        topic_ko=args.topic,
        topic_en=args.topic_en,
        keywords_ko=[x.strip() for x in args.keywords.split(",") if x.strip()],
        keywords_en=[x.strip() for x in args.keywords_en.split(",") if x.strip()],
        papers_per_query=args.papers_per_query,
        download_oa_pdf=not args.no_pdf,
    )
    m = res["manifest"]
    print(
        json.dumps(
            {
                "project_id": m["project_id"],
                "preset": m["preset"],
                "collected_root": m["collected_root"],
                "total_collected": m["total_collected"],
                "breakdown": m["breakdown"],
                "pdf_downloaded_count": m["pdf_downloaded_count"],
                "manifest_path": res["manifest_path"],
                "index_md_path": res["index_md_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
