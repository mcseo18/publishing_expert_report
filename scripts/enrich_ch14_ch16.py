"""ch14(바이오차·부식산), ch15(심토·이탄지·화산회토), ch16(기후변화·MRV·탄소크레딧)
근거 패킷 심화 보강 스크립트:
1. 기존 수집 자료 중 ch14~ch16 관련 핵심 출처의 단원 매핑 재정비
2. 국제 SCI 핵심 논문 9편 + 국내 한국토양비료학회지 바이오차/탄소격리 논문 2편 추가 수집
3. ch14~ch16 근거 패킷 동기화 및 C:\\SMC_GRAPHRAG 증분 지식그래프 반영
"""
from __future__ import annotations

import json
import sys
from typing import Any

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from fetch_cn_models import _search_top_openalex, _set_curation
from fetch_scholar import ingest_paper_record, search_crossref_korean_society
from sync_chapter_packets import sync_packets


ENRICH_QUERIES: list[dict[str, Any]] = [
    # --- ch14: 바이오차 & 부식산 바이오스티뮬런트 ---
    {
        "query": "Sustainable biochar to mitigate global climate change Woolf Amonette",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch14_evidence",
        "chapters": ["ch14", "ch16"],
        "tags": ["바이오차", "CDR", "기후변화완화", "NatureComm", "Woolf"],
        "note": "바이오차 기반 전 지구 탄소격리(CDR) 잠재력과 지속가능성 정량 평가 핵심 논문(Nature Communications).",
    },
    {
        "query": "Humic and fulvic acids as biostimulants in horticulture Canellas",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch14_evidence",
        "chapters": ["ch14", "ch03"],
        "tags": ["부식산", "풀빅산", "바이오스티뮬런트", "옥신유사활성", "Canellas"],
        "note": "부식산·풀빅산의 원예·농작물 바이오스티뮬런트 생리활성(뿌리발달·H+-ATPase·옥신유사) 핵심 리뷰.",
    },
    {
        "query": "Biochar effects on soil biota A review Lehmann Rillig Thies",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch14_evidence",
        "chapters": ["ch14", "ch06"],
        "tags": ["바이오차", "토양미생물", "Lehmann", "열분해안정성"],
        "note": "바이오차 시용이 토양 미생물 군집·효소·균근균·물리화학성에 미치는 종합 리뷰(Soil Biology & Biochemistry).",
    },
    # --- ch15: 심토(Subsoil) · 이탄지(Peatland) · 화산회토(Andosol) ---
    {
        "query": "Deep soil organic matter a key but poorly understood component of terrestrial C cycle Rumpel",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch15_evidence",
        "chapters": ["ch15", "ch01"],
        "tags": ["심토유기물", "Subsoil", "Rumpel", "뿌리탄소", "광물결합"],
        "note": "심토(Subsoil) 토양유기물의 기원·안정화·장기 체류시간 및 전 지구 탄소수지 기여 핵심 리뷰.",
    },
    {
        "query": "The underappreciated potential of peatlands in global climate change mitigation Leifeld",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch15_evidence",
        "chapters": ["ch15", "ch16"],
        "tags": ["이탄지", "습지탄소", "Peatland", "Leifeld", "NatureComm"],
        "note": "전 지구 이탄지·습지 토양유기탄소 축적량 및 배수 시 탄소 손실·복원 완화 잠재력 핵심 논문.",
    },
    {
        "query": "Nature properties and function of aluminum humus complexes in volcanic soils Takahashi Dahlgren",
        "category": "japan_source",
        "tier": "일본·화산회토 SCI",
        "packet": "ch15_evidence",
        "chapters": ["ch15", "ch03"],
        "tags": ["화산회토", "Andosol", "알로페인", "Al-부식복합체", "제주·일본"],
        "note": "화산회토(Andosol)의 알루미늄-부식 복합체 및 알로페인에 의한 초고농도 유기탄소 안정화 메커니즘.",
    },
    # --- ch16: 토양탄소 격리 · 4 per 1000 · MRV · 탄소크레딧 ---
    {
        "query": "The role of soil carbon in natural climate solutions Bossio",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch16_evidence",
        "chapters": ["ch16", "ch01"],
        "tags": ["자연기반기후해법", "NCS", "토양탄소격리", "Bossio", "NatureSustain"],
        "note": "자연기반 기후해법(NCS)에서 토양유기탄소 보호·복원의 정량적 기여도(약 25%) 분석 논문.",
    },
    {
        "query": "Soil carbon 4 per mille Minasny Malone McBratney",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch16_evidence",
        "chapters": ["ch16"],
        "tags": ["4per1000", "Minasny", "Geoderma", "글로벌잠재력", "탄소격리정책"],
        "note": "전 세계 20개국 실측 데이터로 4 per 1000 토양탄소 격리 목표의 실현 가능성과 지역 한계를 분석한 핵심 논문.",
    },
    {
        "query": "How to measure report and verify soil carbon change to realize the potential of soil carbon sequestration Pete Smith",
        "category": "international_journal",
        "tier": "국제 SCI 저널",
        "packet": "ch16_evidence",
        "chapters": ["ch16", "ch11"],
        "tags": ["MRV", "PeteSmith", "탄소크레딧", "IPCC", "검증프로토콜"],
        "note": "농업 토양탄소 MRV(측정·보고·검증) 프레임워크(실측·모델링·원격탐사 결합 및 영속성 기준) 결정판 논문.",
    },
]

# 기존 수집 자료의 ch14~ch16 교차 배정 보정
REMAP_CHAPTERS: dict[str, list[str]] = {
    "SRC-06": ["ch01", "ch15"],                # Georgiou 2022 MAOM (심토 미포화 포함)
    "SRC-07": ["ch01", "ch02", "ch15"],        # Davidson & Janssens 2006 Q10 온난화 피드백
    "SRC-34": ["ch12", "ch13", "ch14", "ch16"],# 일본 MAFF 지구온난화대책·J-Credit
    "SRC-36": ["ch14", "ch16"],                # 일본 MAFF 바이오차 시용량 상한
    "SRC-38": ["ch10", "ch14", "ch15"],        # 일본 화산회 논토양 왕겨 바이오차 SSPN
    "SRC-39": ["ch05", "ch14"],                # 일본 탄소계 흡착제 SSPN
    "SRC-46": ["ch01", "ch16"],                # EU EEA 토양전략
    "SRC-47": ["ch16"],                        # 4 per 1000 공식 이니셔티브
    "SRC-48": ["ch09", "ch11", "ch16"],        # EU EJP SOIL
    "SRC-51": ["ch03", "ch15"],                # EJSS 산성 심토 비정질 광물 유기물 보호
}


def run_enrichment(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    # 1. 기존 출처의 ch14~ch16 단원 교차 배정 보정
    cur_path = cfg.index_dir / "curation_state.json"
    curation = json.loads(cur_path.read_text(encoding="utf-8")) if cur_path.is_file() else {}
    for sid, chs in REMAP_CHAPTERS.items():
        entry = curation.get(sid, {"status": "approved"})
        merged = sorted(set((entry.get("chapters") or []) + chs))
        entry["chapters"] = merged
        entry["updated_at"] = utc_now_iso()
        curation[sid] = entry
    cur_path.write_text(json.dumps(curation, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. 국제 핵심 논문 9편 추가 수집
    added: list[dict[str, Any]] = []
    for spec in ENRICH_QUERIES:
        try:
            hits = _search_top_openalex(spec["query"], limit=1)
            if not hits:
                added.append({"status": "NOT_FOUND", "query": spec["query"]})
                continue
            p = hits[0]
            p["category"] = spec["category"]
            r = ingest_paper_record(p, packet_id=spec["packet"], topic=f"{spec['packet']} 근거 보강", cfg=cfg)
            if r.get("status") == "OK":
                _set_curation(r["source_id"], spec["category"], spec["tier"], spec["chapters"], spec["tags"], spec["note"], 5, cfg)
            added.append(r)
        except Exception as exc:
            added.append({"status": "ERROR", "query": spec["query"], "error": str(exc)})

    # 3. 국내 한국토양비료학회지 바이오차·탄소격리 논문 2편 추가 수집
    for q, pkt, chs, tags in [
        ("biochar soil organic carbon", "ch14_evidence", ["ch14", "ch16"], ["한국토양비료학회", "바이오차", "국내실증"]),
        ("soil carbon sequestration paddy greenhouse gas", "ch16_evidence", ["ch15", "ch16"], ["한국토양비료학회", "토양탄소격리", "온실가스"]),
    ]:
        try:
            papers = search_crossref_korean_society(q, limit=1)
            for p in papers:
                p["category"] = "korean_society"
                r = ingest_paper_record(p, packet_id=pkt, topic="국내 학회지 ch14/ch16 보강", cfg=cfg)
                if r.get("status") == "OK":
                    _set_curation(r["source_id"], "korean_society", "국내 학회지", chs, tags, "한국토양비료학회지 바이오차·탄소격리 국내 실증", 5, cfg)
                added.append(r)
        except Exception as exc:
            added.append({"status": "ERROR", "query": q, "error": str(exc)})

    # 4. ch14~ch16 패킷 동기화
    synced = sync_packets(["ch14", "ch15", "ch16"], cfg=cfg)
    return {
        "added_count": sum(1 for a in added if a.get("status") == "OK"),
        "added": added,
        "synced_packets": {k: v["total_sources_in_packet"] for k, v in synced.items()},
    }


if __name__ == "__main__":
    print(json.dumps(run_enrichment(), ensure_ascii=False, indent=2))
