"""농사로(nongsaro.go.kr) 합법 크롤링 + 오픈 교과서(USDA SARE / FAO / LibreTexts) 수집 + 국내외 표준 토양학 교재·농진청 도서관 참고자료 통합 등록기.

법적 컴플라이언스:
- robots.txt 사전 확인 필수 (lib.rda.go.kr/search/ 는 Disallow 경로이므로 자동 크롤링 금지 -> 서지·URL 카탈로그로 등록하고 수동 열람/ego-browser 안내)
- nongsaro.go.kr 는 robots.txt Allow 경로(rdaInterLst/rdaInterDtl, curationDtl 등)만 정중하게 크롤링
- 모든 원문 HTML, PDF, 정제 마크다운, 근거 패킷은 E:\\SMC_Report_Platform_Data 에 저장
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

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
from parse_pdf import parse_document


# 국내외 표준 토양학·토양유기물학 교재·교과서 및 농진청 핵심 간행물 서지 카탈로그
STANDARD_TEXTBOOKS: list[dict[str, Any]] = [
    {
        "title": "[농촌진흥청 표준교재] 농업기술길잡이 — 농경지 토양 관리기술 (제6장 토양유기물·제7장 토양미생물)",
        "authors": "농촌진흥청 국립농업과학원 토양비료과",
        "year": 2023,
        "publisher": "농촌진흥청 (농사로 / 농업과학도서관)",
        "url": "https://www.nongsaro.go.kr/portal/portalMain.ps?menuId=PS00001",
        "category": "rda_nongsaro",
        "tier": "농진청·농사로 교재",
        "chapters": ["ch01", "ch04", "ch05", "ch06", "ch10", "ch11"],
        "tags": ["농촌진흥청", "농사로", "농업기술길잡이", "토양유기물", "교재"],
        "summary": (
            "농촌진흥청 공식 농경지 토양 관리 표준 길잡이. 제6장 '토양유기물'은 (1) 토양유기물의 정의, "
            "(2) 토양 물리·화학성 개선 및 작물 생육 효과, (3) 유기자원 종류별 특성과 활용, (4) 유기물 분해 요인, "
            "(5) 토양유기물 유지·증진 방안, (6) 국내 농경지의 유기물 함량 현황, (7) 유기물 시용 전 사전 파악사항, "
            "(8) 토양유기물과 기후변화의 8개 절로 구성되어 국내 현장 실무와 500p 교재 제1·10·11장의 핵심 기준을 제공한다."
        ),
        "note": "농사로(nongsaro.go.kr) 영농기술 > 농업기술길잡이 및 농촌진흥청 농업과학도서관(lib.rda.go.kr)에서 e-book/PDF 원문 무료 열람 가능 (lib.rda.go.kr/search/는 robots.txt Disallow 준수).",
    },
    {
        "title": "[국립농업과학원 표준지침서] 토양 및 식물체 분석법 (Tyurin법 토양유기물 정량분석 표준)",
        "authors": "농촌진흥청 국립농업과학원",
        "year": 2010,
        "publisher": "농촌진흥청 농업과학도서관 (lib.rda.go.kr)",
        "url": "https://lib.rda.go.kr/",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch07", "ch08", "ch10"],
        "tags": ["농촌진흥청", "농업과학도서관", "토양분석법", "Tyurin법", "표준지침"],
        "summary": (
            "대한민국 도 농업기술원 및 시·군 농업기술센터 토양검정실의 공식 분석 표준서. "
            "토양 물리성(입도·용적밀도·수분), 화학성(pH, EC, Tyurin 습식산화법에 의한 토양유기물 정량, 유효인산, 치환성 양이온, CEC), "
            "식물체 성분 및 토양 미생물 조사 프로토콜을 규정하며, 교재 제7장(분석법) 및 제10장(국내 토양검정 기준)의 국내 1차 기준서이다."
        ),
        "note": "농촌진흥청 농업과학도서관(lib.rda.go.kr) 소장 공식 지침서 (robots.txt 정책 준수하여 서지 카탈로그로 등록, 원문 PDF는 도서관/ego-browser에서 직접 다운로드 후 E:\\SMC_Report_Platform_Data\\raw\\docs\\ 에 투입 가능).",
    },
    {
        "title": "[KOCW 대학공개강의 교재] 농경지토양관리기술 — 토양유기물과 물질의 순환",
        "authors": "농촌진흥청 (KOCW 공개강좌)",
        "year": 2020,
        "publisher": "한국교육학술정보원 KOCW (kocw.net)",
        "url": "http://www.kocw.net/",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch01", "ch02", "ch05", "ch10"],
        "tags": ["KOCW", "농촌진흥청", "대학강의", "토양유기물", "물질순환"],
        "summary": (
            "KOCW에 공개된 농촌진흥청의 대학 수준 토양관리 강좌. 토양 생성·분류, 물리·화학적 성질, "
            "토양유기물과 탄소·질소·황 물질 순환, 식물 양분 관리 및 비료 사용법을 차시별 강의 교안으로 제공한다."
        ),
        "note": "KOCW(kocw.net)에서 '농경지토양관리기술' 검색으로 강의안·영상 무료 열람 가능.",
    },
    {
        "title": "[국내 대학 교과서] 토양학 (제6장 토양 생물과 유기물)",
        "authors": "한국방송통신대학교 농학과 (김계훈 외)",
        "year": 2021,
        "publisher": "한국방송통신대학교 출판문화원",
        "url": "https://press.knou.ac.kr/",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch01", "ch02", "ch03", "ch06"],
        "tags": ["대학교재", "토양학", "교과서", "부식형성", "토양생물"],
        "summary": (
            "국내 농학 전공 표준 대학교재. 토양 물리·화학·생물성 기초와 제6장 '토양 생물과 유기물'에서 "
            "유기물 분해 과정, 부식 형성, C/N비, 토양 탄소 저장 및 기후변화 대응 관리 원리를 한국 농경지 맥락으로 해설한다."
        ),
        "note": "저작권 보호 출판 교과서 — 무단 복제 금지, 목차 체계 및 국내 표준 용어 정합성 참고용 서지 등록.",
    },
    {
        "title": "[국제 표준 대학교과서] The Nature and Properties of Soils (15th Edition) — Ch.12 Soil Organic Matter",
        "authors": "Ray R. Weil, Nyle C. Brady",
        "year": 2017,
        "publisher": "Pearson Education",
        "url": "https://www.pearson.com/",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch01", "ch02", "ch03", "ch04", "ch05", "ch06", "ch13"],
        "tags": ["Brady&Weil", "국제표준교과서", "토양학바이블", "SOM", "전단원참고"],
        "summary": (
            "전 세계 농과대학·토양학과에서 가장 널리 채택되는 토양학 표준 교과서(제15판). "
            "제12장 'Soil Organic Matter'를 중심으로 지구 탄소순환, 잔사 분해 속도론, 부식 물질과 콜로이드 전하(CEC), "
            "토양단립 안정화, 퇴비·녹비·경운에 따른 토양탄소 관리까지 500p 교재 전 단원의 이론적 뼈대를 제공한다."
        ),
        "note": "국제 표준 교과서 서지 참고자료 (저작권 준수: 원문 복제 없이 핵심 개념 구조·용어 참고).",
    },
    {
        "title": "[국제 전문 원서] Humus Chemistry: Genesis, Composition, Reactions (2nd Edition)",
        "authors": "Frank J. Stevenson",
        "year": 1994,
        "publisher": "John Wiley & Sons",
        "url": "https://www.wiley.com/",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch03", "ch05", "ch07"],
        "tags": ["Stevenson", "부식화학", "부식산", "풀빅산", "분광분석"],
        "summary": (
            "토양 부식화학(Humus Chemistry) 분야의 고전적 표준 전문서. 부식산(HA)·풀빅산(FA)·휴민(Humin)의 "
            "추출·정제, 카르복실·페놀 작용기 화학, 금속 이온 킬레이트 착물, UV-Vis(E4/E6 비)·FTIR·13C-NMR 분광 특성, "
            "점토-부식 복합체 반응 메커니즘을 심층적으로 다룬다."
        ),
        "note": "제3장(부식화 이론)·제5장(화학성·킬레이트)·제7장(분광 분석) 고전 원리 비교용 핵심 전문서.",
    },
    {
        "title": "[국제 대학원 교과서] Soil Microbiology, Ecology, and Biochemistry (4th Edition)",
        "authors": "Eldor A. Paul (Editor)",
        "year": 2015,
        "publisher": "Academic Press (Elsevier)",
        "url": "https://www.sciencedirect.com/book/9780124159556/soil-microbiology-ecology-and-biochemistry",
        "category": "textbook",
        "tier": "표준 교재·교과서",
        "chapters": ["ch02", "ch03", "ch06", "ch09"],
        "tags": ["Paul", "토양미생물학", "생지화학", "미생물탄소펌프", "모델링"],
        "summary": (
            "토양 미생물학·생태학·생지화학 대학원 표준 교과서. 근권 생태계, 균근균(AMF)과 글로말린, "
            "토양 효소 동역학, 미생물 탄소이용효율(CUE)과 프라이밍 효과, 동위원소(13C/14C) 추적 및 탄소 순환 모델링을 집대성한다."
        ),
        "note": "제2장(분해 동태)·제3장(미생물 탄소 펌프)·제6장(미생물·프라이밍)·제9장(모델링) 핵심 참고 교과서.",
    },
]


def _update_curation_meta(
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
    cur_path = cfg.index_dir / "curation_state.json"
    state: dict[str, Any] = {}
    if cur_path.is_file():
        try:
            state = json.loads(cur_path.read_text(encoding="utf-8"))
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
    cur_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def search_nongsaro_rda_inter(keywords: list[str], limit_per_kw: int = 4) -> list[dict[str, str]]:
    """농사로(nongsaro.go.kr) robots.txt 허용 경로(rdaInterLst.ps?menuId=PS00063)에서 토양·유기물·탄소 기사를 검색한다."""
    hdr = {"User-Agent": USER_AGENT}
    found: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for kw in keywords:
        try:
            r = requests.post(
                "https://www.nongsaro.go.kr/portal/ps/psv/psvr/psvrc/rdaInterLst.ps?menuId=PS00063",
                data={"menuId": "PS00063", "srchType": "01", "srchVal": kw, "pageIndex": "1"},
                headers=hdr,
                timeout=15,
            )
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            count = 0
            for a in soup.find_all("a", href=True):
                txt = a.get_text(" ", strip=True)
                oc = a.get("onclick", "")
                if "fncDtl" not in oc and "rdaInterDtl" not in a["href"]:
                    continue
                m = re.search(r"(\d{5,})", oc + a["href"])
                if not m:
                    continue
                cid = m.group(1)
                if cid in seen_ids or cid == "204722":  # 발간목록 제외
                    continue
                if any(k in txt for k in ("토양", "유기", "퇴비", "탄소", "거름", "비료", "흙", "미생물", "농업")):
                    seen_ids.add(cid)
                    found.append(
                        {
                            "cntntsNo": cid,
                            "title": txt,
                            "keyword": kw,
                            "url": f"https://www.nongsaro.go.kr/portal/ps/psv/psvr/psvrc/rdaInterDtl.ps?menuId=PS00063&cntntsNo={cid}",
                        }
                    )
                    count += 1
                    if count >= limit_per_kw:
                        break
        except Exception:
            continue
    return found


def register_textbook_catalog(cfg: PlatformConfig | None = None) -> list[dict[str, Any]]:
    """국내외 표준 토양학 교재·교과서 및 농진청 핵심 간행물 서지·목차를 근거 패킷에 등록한다."""
    cfg = cfg or get_config()
    registry = SourcesRegistry(cfg.sources_registry_path)
    results: list[dict[str, Any]] = []

    for tb in STANDARD_TEXTBOOKS:
        md_text = "\n".join(
            [
                f"# {tb['title']}",
                "",
                f"- **저자/발행기관**: {tb['authors']}",
                f"- **발행연도**: {tb['year']}",
                f"- **출판사/플랫폼**: {tb['publisher']}",
                f"- **참조 URL**: {tb['url']}",
                f"- **배정 단원**: {', '.join(tb['chapters'])}",
                "",
                "## 교재·교과서 핵심 구성 및 참고 의의",
                tb["summary"],
                "",
                "## 수집·열람 컴플라이언스 메모",
                tb["note"],
            ]
        )
        cleaned_md, pii_cnt = mask_pii(md_text)
        content_hash = sha256_text(cleaned_md)
        dup = registry.find_duplicate(content_sha256=content_hash)
        if dup:
            results.append({"status": "SKIPPED_DUPLICATE", "title": tb["title"], "source_id": dup.get("source_id")})
            continue

        source_id = registry.next_source_id()
        slug = slugify(tb["title"], 44)
        parsed_path = cfg.parsed_dir / f"{source_id}_{slug}.md"
        parsed_path.write_text(cleaned_md, encoding="utf-8")

        chunks = chunk_korean_text(cleaned_md, default_section=f"{tb['publisher']} ({tb['year']})")
        primary_ch = tb["chapters"][0] if tb["chapters"] else "ch01"
        packet_id = f"{primary_ch}_evidence"
        packet_path = cfg.evidence_dir / f"{packet_id}.json"
        now = utc_now_iso()

        source_item = {
            "source_id": source_id,
            "source_type": "md",
            "url": tb["url"],
            "title": tb["title"],
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": "textbook_catalog_metadata",
            "license_note": f"교재·교과서 서지·목차 참고자료 ({tb['publisher']}) - 저작권 준수·변환적 참고",
            "page_or_section": f"표준 교재 참고 ({tb['year']})",
            "raw_path": str(parsed_path),
            "parsed_path": str(parsed_path),
            "pii_masked": True,
            "pii_redaction_count": pii_cnt,
            "prompt_injection_warnings": [],
            "sha256": content_hash,
            "extracted_facts": [
                {
                    "claim": f"{tb['authors']} ({tb['year']}), {tb['title']} — {tb['summary'][:200]}",
                    "page_or_section": str(tb["year"]),
                    "evidence_quote_short": tb["summary"][:180],
                }
            ],
            "tables": [],
            "chunks": chunks,
        }

        upsert_evidence_packet(
            packet_path=packet_path,
            source_item=source_item,
            packet_id=packet_id,
            topic=f"토양 유기물학 표준 교재 참고자료 ({primary_ch})",
            storage_root=str(cfg.collected_data_root),
            kg_store_root=str(cfg.smc_graphrag_root),
            schema_path=cfg.evidence_schema_path,
        )

        registry.append(
            {
                "source_id": source_id,
                "source_type": "md",
                "scholar_category": tb["category"],
                "provider": tb["publisher"],
                "authors": tb["authors"],
                "year": tb["year"],
                "journal": tb["publisher"],
                "doi": "",
                "cited_by_count": 0,
                "is_oa": tb["category"] == "rda_nongsaro",
                "url": tb["url"],
                "normalized_url": f"textbook://{source_id}/{slug}",
                "title": tb["title"],
                "accessed_at": now,
                "robots_allowed": True,
                "robots_status": "textbook_catalog_metadata",
                "sha256": content_hash,
                "raw_path": str(parsed_path),
                "parsed_path": str(parsed_path),
                "packet_path": str(packet_path),
                "parser_engine": "textbook_catalog",
                "chunk_count": len(chunks),
                "table_count": 0,
            }
        )

        _update_curation_meta(
            source_id=source_id,
            category=tb["category"],
            tier=tb["tier"],
            chapters=tb["chapters"],
            tags=tb["tags"],
            notes=tb["note"],
            rating=5,
            cfg=cfg,
        )
        results.append({"status": "OK", "source_id": source_id, "title": tb["title"], "packet": packet_id})
    return results


def run_full_crawl_and_textbook_ingest(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    summary: dict[str, Any] = {
        "nongsaro_crawled": [],
        "open_textbook_pdfs": [],
        "open_textbook_chapters": [],
        "standard_textbooks_catalog": [],
    }

    # 1. 농사로(nongsaro.go.kr) 공개 큐레이션 & RDA 인테러뱅 검색·크롤링
    nongsaro_targets: list[dict[str, Any]] = [
        {
            "url": "https://www.nongsaro.go.kr/portal/ps/psv/psvr/psvre/curationDtl.ps?menuId=PS03352&srchCurationNo=2146",
            "packet": "ch11_evidence",
            "chapters": ["ch11", "ch13"],
            "tags": ["농사로", "농촌진흥청", "깊이거름주기", "탄소중립"],
            "note": "농사로 공식 큐레이션: 깊이거름주기 장치 탄소중립 실증 확인",
        },
        {
            "url": "https://www.nongsaro.go.kr/portal/ps/psv/psvr/psvre/curationDtl.ps?menuId=PS03352&srchCurationNo=2360",
            "packet": "ch04_evidence",
            "chapters": ["ch04", "ch10"],
            "tags": ["농사로", "농촌진흥청", "토양수분", "시설재배"],
            "note": "농사로 공식 큐레이션: 시설재배 토양 수분 관리 기준",
        },
    ]

    inter_hits = search_nongsaro_rda_inter(["토양", "유기물", "탄소", "퇴비"], limit_per_kw=3)
    for h in inter_hits[:4]:
        nongsaro_targets.append(
            {
                "url": h["url"],
                "packet": "ch10_evidence",
                "chapters": ["ch01", "ch10", "ch13"],
                "tags": ["농사로", "RDA인테러뱅", "농촌진흥청", h["keyword"]],
                "note": f"농사로 RDA 인테러뱅 자동 검색·크롤링 (키워드: {h['keyword']})",
            }
        )

    for item in nongsaro_targets:
        try:
            res = fetch_and_clean_url(
                url=item["url"],
                packet_id=item["packet"],
                topic="농사로 토양·유기물·탄소중립 공개 자료",
                license_note="농촌진흥청 농사로(nongsaro.go.kr) 공공누리/공개 영농기술 자료 - 변환적 분석 및 인용",
                use_crawl4ai=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                _update_curation_meta(
                    source_id=res["source_id"],
                    category="rda_nongsaro",
                    tier="농진청·농사로",
                    chapters=item["chapters"],
                    tags=item["tags"],
                    notes=item["note"],
                    rating=5,
                    cfg=cfg,
                )
            summary["nongsaro_crawled"].append(res)
        except Exception as exc:
            summary["nongsaro_crawled"].append({"status": "ERROR", "url": item["url"], "error": str(exc)})

    # 2. 오픈액세스 전체 교과서 PDF 2종 파싱 (USDA SARE 4판 14.4MB + FAO Soils Bulletin 80 2.46MB)
    pdf_books = [
        {
            "file": cfg.raw_docs_dir / "SARE_Building_Soils_for_Better_Crops_4thEd.pdf",
            "packet": "ch01_evidence",
            "chapters": ["ch01", "ch02", "ch04", "ch05", "ch10", "ch11"],
            "tags": ["USDA-SARE", "오픈교과서", "PDF원문", "Magdoff&vanEs", "토양유기물"],
            "license": "USDA SARE 공식 무료 오픈액세스 교재(4th Ed., Fred Magdoff & Harold van Es) - 교육·연구 인용",
            "note": "미국 USDA SARE 공식 오픈액세스 4판 전체 교과서 PDF(14.4MB). 토양유기물 원리·관리·퇴비·피복작물·토양검정 전 영역 수록.",
        },
        {
            "file": cfg.raw_docs_dir / "FAO_Soils_Bulletin_80_Soil_Organic_Matter.pdf",
            "packet": "ch01_evidence",
            "chapters": ["ch01", "ch02", "ch04", "ch11", "ch13"],
            "tags": ["FAO", "오픈교과서", "PDF원문", "SoilsBulletin80", "가뭄저항성"],
            "license": "FAO 공식 공개 기술교재(Soils Bulletin 80, Bot & Benites) - 변환적 분석 및 인용",
            "note": "UN FAO 공식 토양유기물 종합 기술교재 전체 PDF(2.46MB). 분해·물리화학기능·가뭄저항성·보전농업 사례 수록.",
        },
    ]
    for pb in pdf_books:
        if pb["file"].is_file():
            try:
                res = parse_document(
                    file_path=pb["file"],
                    packet_id=pb["packet"],
                    topic="국제 오픈액세스 토양유기물 표준 교과서 PDF",
                    license_note=pb["license"],
                    use_docling=False,
                    cfg=cfg,
                )
                if res.get("status") == "OK":
                    _update_curation_meta(
                        source_id=res["source_id"],
                        category="textbook",
                        tier="표준 교재·교과서",
                        chapters=pb["chapters"],
                        tags=pb["tags"],
                        notes=pb["note"],
                        rating=5,
                        cfg=cfg,
                    )
                summary["open_textbook_pdfs"].append(res)
            except Exception as exc:
                summary["open_textbook_pdfs"].append({"status": "ERROR", "file": str(pb["file"]), "error": str(exc)})

    # 3. 오픈 대학 교과서 핵심 단원 웹 크롤링 (USDA SARE Ch.2/Ch.3/Ch.9 + LibreTexts Soils Lab Manual Ch.4/Ch.5)
    open_chapters = [
        {
            "url": "https://www.sare.org/publications/building-soils-for-better-crops/what-is-organic-matter-and-why-is-it-so-important/",
            "packet": "ch01_evidence",
            "chapters": ["ch01"],
            "tags": ["USDA-SARE", "교과서", "Ch2", "토양유기물정의"],
            "note": "Building Soils for Better Crops (4e) Ch.2: 토양 유기물의 정의와 중요성(활성·완효·안정 풀)",
        },
        {
            "url": "https://www.sare.org/publications/building-soils-for-better-crops/amount-of-organic-matter-in-soils/",
            "packet": "ch02_evidence",
            "chapters": ["ch02", "ch04"],
            "tags": ["USDA-SARE", "교과서", "Ch3", "유기물함량요인"],
            "note": "Building Soils for Better Crops (4e) Ch.3: 토성·기후·경운에 따른 토양 유기물 함량 결정 요인",
        },
        {
            "url": "https://www.sare.org/publications/building-soils-for-better-crops/ch-9-managing-for-high-quality-soils-and-focusing-on-organic-matter-management/",
            "packet": "ch11_evidence",
            "chapters": ["ch10", "ch11"],
            "tags": ["USDA-SARE", "교과서", "Ch9", "유기물관리전략"],
            "note": "Building Soils for Better Crops (4e) Ch.9: 현장 토양 유기물 관리 핵심 전략",
        },
        {
            "url": "https://geo.libretexts.org/Bookshelves/Soil_Science/Soils_Laboratory_Manual_(Moorberg_and_Crouse)/04%3A_Soil_Biology",
            "packet": "ch06_evidence",
            "chapters": ["ch06", "ch08"],
            "tags": ["LibreTexts", "오픈교과서", "토양생물실험", "대학실습"],
            "note": "Geosciences LibreTexts 오픈 대학 실험교재(Moorberg & Crouse) Ch.4 토양 생물학 실습",
        },
        {
            "url": "https://geo.libretexts.org/Bookshelves/Soil_Science/Soils_Laboratory_Manual_(Moorberg_and_Crouse)/05%3A_Soil_Chemistry",
            "packet": "ch05_evidence",
            "chapters": ["ch05", "ch07"],
            "tags": ["LibreTexts", "오픈교과서", "토양화학실험", "CEC", "대학실습"],
            "note": "Geosciences LibreTexts 오픈 대학 실험교재(Moorberg & Crouse) Ch.5 토양 화학·CEC 실습",
        },
    ]
    for oc in open_chapters:
        try:
            res = fetch_and_clean_url(
                url=oc["url"],
                packet_id=oc["packet"],
                topic="오픈 대학 토양학 교과서 단원 원문",
                license_note="오픈액세스 대학 교과서(USDA SARE / LibreTexts CC-BY) - 변환적 분석 및 인용",
                use_crawl4ai=False,
                cfg=cfg,
            )
            if res.get("status") == "OK":
                _update_curation_meta(
                    source_id=res["source_id"],
                    category="textbook",
                    tier="표준 교재·교과서",
                    chapters=oc["chapters"],
                    tags=oc["tags"],
                    notes=oc["note"],
                    rating=5,
                    cfg=cfg,
                )
            summary["open_textbook_chapters"].append(res)
        except Exception as exc:
            summary["open_textbook_chapters"].append({"status": "ERROR", "url": oc["url"], "error": str(exc)})

    # 4. 국내외 표준 토양학 교재·농진청 농업과학도서관 핵심 참고서지 카탈로그 등록
    summary["standard_textbooks_catalog"] = register_textbook_catalog(cfg)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="농사로 크롤링 + 오픈 교과서 + 국내외 표준 교재 참고자료 일괄 수집기")
    parser.add_argument("--search-nongsaro", default="", help="농사로 RDA 인테러뱅 키워드 검색만 실행 (쉼표 구분)")
    args = parser.parse_args()

    if args.search_nongsaro:
        kws = [k.strip() for k in args.search_nongsaro.split(",") if k.strip()]
        print(json.dumps(search_nongsaro_rda_inter(kws), ensure_ascii=False, indent=2))
        return 0

    res = run_full_crawl_and_textbook_ingest()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
