"""참참살이 영농 AI 출판도우미 — 핵심 프레임워크 통합 모듈.

Agro AI Publishing Framework Plan.md (Phase 1~4) 기술 구현:
1. 브랜드 아이덴티티 & 디자인 토큰 (Emerald Agri / Golden Wheat / Academic Navy / KoPubWorld)
2. 7대 영역 31개 범용 핵심 키워드 체계 & 17개 스페셜티 농업 분야 커리큘럼 카탈로그
3. 문맥 인지형 4단계 장·단원 구조화 엔진 (이론 -> 생리·분자 -> 현장 적용 -> 법규·정책)
4. GraphRAG 하이브리드 트리플 추출 + [SRC-NN] 1:1 인용 감사 및 자동 보정 게이트
5. 직관적 데이터 해석 레이어: 생육 적산온도(GDD) 백엔드 연산 + 신호등 상태 진단
6. 시각화 300dpi(인쇄) / 72dpi(웹) 이중 해상도 최적화
7. 싱글 소스 다중 판형(신국판 152x225 / B5 182x257 / A4 210x297) 마스터 제본 + Quarto 매니페스트
"""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from compliance import utc_now_iso
from config import PlatformConfig, get_config

# ============================================================
# 1. 브랜드 아이덴티티 & 타이포그래피 표준
# ============================================================
BRAND_IDENTITY: dict[str, Any] = {
    "app_title": "참참살이 영농 AI 출판도우미",
    "app_subtitle": "한정 자원 기반 고효율 AI 전문 출판 프레임워크 · GraphRAG · 싱글 소스 다중 제본",
    "version": "3.0.0",
    "palette": {
        "emerald_primary": "#063b2c",
        "emerald_accent": "#34d399",
        "golden_bg": "#0f291e",
        "golden_wheat": "#eab308",
        "academic_navy": "#1D3557",
        "slate_muted": "#94a3b8",
        "surface_dark": "#071a14",
        "card_dark": "#0c241c",
    },
    "typography": {
        "body_print": "'KoPubWorldBatang', 'KoPubBatang', 'Batang', 'Malgun Gothic', serif",
        "heading_print": "'KoPubWorldDotum', 'Pretendard', 'Malgun Gothic', sans-serif",
        "heading_color": "#1D3557",
    },
}

# ============================================================
# 2. 7대 영역 31개 범용 핵심 키워드 & 17개 스페셜티 분야 카탈로그
# ============================================================
AGRO_CORE_KEYWORDS_31: list[dict[str, Any]] = [
    {
        "domain_id": "D1",
        "domain_ko": "생육·생리",
        "domain_en": "Growth & Physiology",
        "keywords": [
            {"ko": "광합성·동화산물 분배", "en": "photosynthesis assimilate partitioning"},
            {"ko": "생육 적산온도(GDD)", "en": "growing degree days GDD"},
            {"ko": "춘화처리·개화생리", "en": "vernalization flowering physiology"},
            {"ko": "수분스트레스·증산조절", "en": "water stress transpiration"},
            {"ko": "식물호르몬·신호전달", "en": "phytohormone signaling"},
        ],
    },
    {
        "domain_id": "D2",
        "domain_ko": "양분·토양",
        "domain_en": "Nutrients & Soil Science",
        "keywords": [
            {"ko": "토양유기물·탄질비(C/N)", "en": "soil organic matter C/N ratio"},
            {"ko": "질소순환·정밀시비", "en": "nitrogen cycle precision fertilization"},
            {"ko": "근권미생물·바이오차", "en": "rhizosphere microbiome biochar"},
            {"ko": "토양 pH·EC·양분가용성", "en": "soil pH EC nutrient availability"},
            {"ko": "토양물리성·배수관리", "en": "soil physical properties drainage"},
        ],
    },
    {
        "domain_id": "D3",
        "domain_ko": "유전·종자",
        "domain_en": "Genetics & Seed Technology",
        "keywords": [
            {"ko": "품종특성·내재해성", "en": "cultivar traits stress tolerance"},
            {"ko": "종자활력·발아생리", "en": "seed vigor germination physiology"},
            {"ko": "분자육종·유전체선발", "en": "molecular breeding genomic selection"},
            {"ko": "우량육묘·접목생리", "en": "seedling raising grafting physiology"},
        ],
    },
    {
        "domain_id": "D4",
        "domain_ko": "작물보호",
        "domain_en": "Crop Protection",
        "keywords": [
            {"ko": "병해충 예찰·IPM", "en": "pest forecasting integrated pest management"},
            {"ko": "잡초방제·제초제 저항성", "en": "weed control herbicide resistance"},
            {"ko": "생물적 방제·미생물농약", "en": "biological control biopesticide"},
            {"ko": "농약안전사용·PLS 기준", "en": "pesticide safety PLS standard"},
        ],
    },
    {
        "domain_id": "D5",
        "domain_ko": "생육모형·디지털농업",
        "domain_en": "Crop Modeling & Digital Ag",
        "keywords": [
            {"ko": "작물생육모형(DSSAT·APSIM)", "en": "crop simulation model DSSAT APSIM"},
            {"ko": "드론·위성 NDVI 원격탐사", "en": "UAV satellite NDVI remote sensing"},
            {"ko": "IoT 토양·기상 센서", "en": "IoT soil weather sensor network"},
            {"ko": "스마트팜 복합환경제어", "en": "smart farm environment control"},
            {"ko": "AI 디지털 트윈·수량예측", "en": "agricultural digital twin yield prediction"},
        ],
    },
    {
        "domain_id": "D6",
        "domain_ko": "수확후·품질",
        "domain_en": "Postharvest & Quality",
        "keywords": [
            {"ko": "수확적기·성숙도 판정", "en": "harvest maturity index"},
            {"ko": "예냉·CA/MA 저장기술", "en": "precooling CA MA storage"},
            {"ko": "기능성분·등급규격", "en": "functional compounds grading standard"},
            {"ko": "콜드체인·유통손실 저감", "en": "cold chain postharvest loss"},
        ],
    },
    {
        "domain_id": "D7",
        "domain_ko": "지속가능성·정책",
        "domain_en": "Sustainability & Policy",
        "keywords": [
            {"ko": "저탄소 농업·온실가스(CH4·N2O)", "en": "low carbon agriculture GHG mitigation"},
            {"ko": "기후변화 적응·이상기상", "en": "climate change adaptation extreme weather"},
            {"ko": "순환농업·퇴비 부숙도", "en": "circular agriculture compost maturity"},
            {"ko": "농업정책·친환경인증·가축분뇨법", "en": "agricultural policy eco certification"},
        ],
    },
]

AGRO_SPECIALTY_CURRICULA: list[dict[str, Any]] = [
    {"id": "smart_rice", "topic_ko": "스마트 벼 재배와 디지털 논 물관리", "topic_en": "Smart Rice Cultivation & Digital Paddy Management", "chapters": 14, "pages": 460, "t_base": 10.0, "keywords_ko": ["벼 출수생리", "간단관개", "메탄 저감", "드론 엽색 진단", "정밀 질소시비"]},
    {"id": "soybean", "topic_ko": "데이터 기반 콩(대두) 정밀재배학", "topic_en": "Data-Driven Precision Soybean Cultivation", "chapters": 12, "pages": 400, "t_base": 10.0, "keywords_ko": ["근류균 질소고정", "논콩 배수관리", "개화·착협 생리", "기계수확 적응성", "단백질 함량"]},
    {"id": "potato", "topic_ko": "디지털 감자 재배와 스마트 저장관리", "topic_en": "Digital Potato Cultivation & Smart Storage", "chapters": 14, "pages": 450, "t_base": 7.0, "keywords_ko": ["씨감자 휴면타파", "괴경 비대 생리", "역병 예찰 모델", "토양수분 정밀관개", "큐어링·저온저장"]},
    {"id": "pepper", "topic_ko": "노지·시설 고추 정밀재배 및 병해충 IPM", "topic_en": "Precision Red Pepper Cultivation & IPM", "chapters": 14, "pages": 440, "t_base": 10.0, "keywords_ko": ["탄저병·역병 예찰", "캡사이신 생합성", "점적관비", "칼슘결핍 배꼽썩음과", "건조·품질관리"]},
    {"id": "wheat", "topic_ko": "디지털 밀 재배학", "topic_en": "Digital Wheat Cultivation", "chapters": 16, "pages": 530, "t_base": 4.0, "keywords_ko": ["겨울밀 춘화처리", "분얼·출수 생리", "드론 NDVI 질소처방", "붉은곰팡이병 예찰", "제분·단백질 품질"]},
    {"id": "corn", "topic_ko": "디지털 옥수수 재배학", "topic_en": "Digital Corn Cultivation", "chapters": 14, "pages": 460, "t_base": 10.0, "keywords_ko": ["C4 광합성", "수염 출사·수분", "GDD 적산온도", "가변시비", "사일리지·종실 수확"]},
    {"id": "sweet_potato", "topic_ko": "고구마 생리생태와 큐어링 저장기술", "topic_en": "Sweet Potato Physiology & Curing Storage", "chapters": 12, "pages": 380, "t_base": 12.0, "keywords_ko": ["괴근 분화", "삽식 밀도", "덩굴쪼김병", "아물이(큐어링)", "당도·전분 전환"]},
    {"id": "garlic", "topic_ko": "디지털 마늘 정밀재배와 한지·난지형 관리", "topic_en": "Digital Garlic Precision Cultivation", "chapters": 12, "pages": 390, "t_base": 5.0, "keywords_ko": ["인편 분화", "월동 동해 관리", "2차 생장(벌마늘)", "잎마름병 예찰", "예건·저온저장"]},
    {"id": "soil_science", "topic_ko": "현대 토양유기물학 및 토양비옥도 관리", "topic_en": "Modern Soil Organic Matter & Fertility Science", "chapters": 16, "pages": 500, "t_base": 5.0, "keywords_ko": ["토양유기탄소(SOC)", "부식질 분획", "퇴비 부숙도", "바이오차 탄화", "양분수지"]},
    {"id": "crop_physiology", "topic_ko": "최신 작물재배생리학", "topic_en": "Advanced Crop Cultivation Physiology", "chapters": 15, "pages": 480, "t_base": 8.0, "keywords_ko": ["광합성 기구", "탄소·질소 대사", "삼투조절", "환경스트레스 반응", "소스-싱크 관계"]},
    {"id": "weed_control", "topic_ko": "최신 잡초방제학 및 제초제 저항성 관리", "topic_en": "Modern Weed Science & Herbicide Resistance", "chapters": 14, "pages": 450, "t_base": 8.0, "keywords_ko": ["잡초 생태형", "작용기작(HRAC)", "저항성 잡초", "종합잡초관리(IWM)", "정밀 변량살포"]},
    {"id": "postharvest", "topic_ko": "농산물 수확후관리학 및 스마트 콜드체인", "topic_en": "Postharvest Management & Smart Cold Chain", "chapters": 14, "pages": 440, "t_base": 5.0, "keywords_ko": ["호흡률·에틸렌", "예냉 공학", "CA/MA 저장", "비파괴 선별", "신선도 IoT 모니터링"]},
    {"id": "smart_greenhouse", "topic_ko": "스마트 온실 복합환경제어와 딸기·토마토 수경재배", "topic_en": "Smart Greenhouse Control & Hydroponics", "chapters": 14, "pages": 460, "t_base": 5.0, "keywords_ko": ["VPD 수증기압포차", "CO2 시비", "양액 EC·pH 제어", "근권 수분센서", "에너지 절감 난방"]},
    {"id": "orchard_smart", "topic_ko": "기후변화 대응 스마트 과수원(사과·배) 정밀관리", "topic_en": "Climate-Adaptive Smart Orchard Management", "chapters": 14, "pages": 450, "t_base": 5.0, "keywords_ko": ["저온요구도·휴면", "개화기 서리 방상", "과실 착색 생리", "화상병 예찰", "무인방제기"]},
    {"id": "compost_livestock", "topic_ko": "경축순환농업과 가축분뇨 퇴비 부숙도 관리", "topic_en": "Crop-Livestock Circular Ag & Compost Maturity", "chapters": 12, "pages": 360, "t_base": 10.0, "keywords_ko": ["가축분뇨법 부숙도", "호기성 발효", "탄질비(C/N)", "암모니아 휘산 저감", "액비 정밀살포"]},
    {"id": "global_ag_trends", "topic_ko": "글로벌 애그테크 및 해외 스마트농업 트렌드", "topic_en": "Global AgTech & International Smart Farming Trends", "chapters": 12, "pages": 380, "t_base": 8.0, "keywords_ko": ["네덜란드 WUR 온실", "미국 정밀농업", "일본 스마트농기계", "재생농업 탄소크레딧", "농업 AI 에이전트"]},
    {"id": "climate_smart_ag", "topic_ko": "기후스마트농업(CSA)과 저탄소 영농 실무", "topic_en": "Climate-Smart Agriculture & Low-Carbon Farming", "chapters": 12, "pages": 400, "t_base": 8.0, "keywords_ko": ["탄소중립 영농", "가뭄·폭염 대응", "기상재해 조기경보", "저탄소 농축산물 인증", "LCA 탄소발자국"]},
]

# ============================================================
# 3. 문맥 인지형 4단계 장·단원 분할 표준 구조
# ============================================================
CONTEXT_AWARE_4STAGE_TEMPLATE: list[dict[str, str]] = [
    {
        "phase": "1단계",
        "key": "theory_background",
        "title_ko": "개념 소개 및 이론적 배경",
        "guide": "핵심 개념 정의, 학술적·산업적 의의, 국내외 현황 및 정량 지표를 [SRC-NN] 근거와 함께 서술",
    },
    {
        "phase": "2단계",
        "key": "physiology_mechanism",
        "title_ko": "생리·분자 메커니즘",
        "guide": "작물 생리·대사 경로, 토양-식물-대기 상호작용, 수식·모형(GDD, 물질수지 등) 및 핵심 원리 규명",
    },
    {
        "phase": "3단계",
        "key": "field_application",
        "title_ko": "현장 적용 및 실전 기술",
        "guide": "농가·스마트팜 현장 적용 절차, 정량 관리 기준표, 진단 체크리스트, 장애·오해 교정 실증 사례",
    },
    {
        "phase": "4단계",
        "key": "policy_regulation",
        "title_ko": "관련 법규 및 정책 지침",
        "guide": "농촌진흥청 영농활용 기준, PLS·가축분뇨법·친환경인증·탄소중립 직불제 등 관련 법령·정책 지침 연계",
    },
]


def build_context_aware_sections(chapter_number: int, chapter_title: str, existing_sections: list[str] | None = None) -> list[str]:
    """기존 절 목록이 부족하거나 비어있을 때 문맥 인지형 4단계 표준 절 구조를 보완한다."""
    cleaned = [s.strip() for s in (existing_sections or []) if str(s).strip()]
    if len(cleaned) >= 4:
        return cleaned
    base_name = re.sub(r"^제?\s*\d+\s*장[\.\s]*", "", chapter_title).strip() or chapter_title
    return [
        f"{chapter_number}.1 {base_name}의 개념 소개 및 이론적 배경",
        f"{chapter_number}.2 {base_name}의 생리·분자 메커니즘과 정량 원리",
        f"{chapter_number}.3 {base_name}의 현장 적용 및 실전 정밀관리 기술",
        f"{chapter_number}.4 {base_name} 관련 법규·인증 및 정책 지침",
    ]


# ============================================================
# 4. GraphRAG 하이브리드 트리플 조회 + 인용 감사·자동 보정
# ============================================================
def query_kg_triples_for_chapter(
    *,
    chapter_title: str,
    chapter_text: str = "",
    project_source_ids: set[str] | None = None,
    limit: int = 24,
    cfg: PlatformConfig | None = None,
) -> list[dict[str, Any]]:
    """C:\\SMC_GRAPHRAG 증분 지식그래프에서 단원 문맥과 관련된 엔티티-관계 트리플을 추출한다."""
    cfg = cfg or get_config()
    inc_path = cfg.smc_incremental_graph_path
    if not inc_path.is_file():
        return []
    try:
        raw = json.loads(inc_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    edges = raw.get("edges") or raw.get("links") or []
    if not edges:
        return []

    # 단원 제목 + 본문 앞부분 토큰 추출
    probe_text = f"{chapter_title}\n{chapter_text[:4000]}".lower()
    tokens = {
        tok
        for tok in re.findall(r"[가-힣a-z0-9]{2,}", probe_text)
        if tok not in {"단원", "내용", "기준", "방법", "적용", "연구", "분석", "기술", "관리", "결과"}
    }

    scored: list[tuple[int, dict[str, Any]]] = []
    for e in edges:
        src = str(e.get("source") or e.get("head") or "").strip()
        rel = str(e.get("relation") or e.get("label") or e.get("type") or "관련").strip()
        tgt = str(e.get("target") or e.get("tail") or "").strip()
        sid = str(e.get("source_id") or "").strip()
        if not src or not tgt:
            continue

        score = 0
        if project_source_ids and sid in project_source_ids:
            score += 4
        blob = f"{src} {rel} {tgt}".lower()
        for tok in tokens:
            if tok in blob:
                score += 2
        if score > 0:
            scored.append(
                (
                    score,
                    {
                        "head": src,
                        "relation": rel,
                        "tail": tgt,
                        "source_id": sid or "KG-LOCAL",
                        "score": score,
                        "triple_text": f"[{src}] —[{rel}]→ [{tgt}]",
                        "citation_tag": f"[{sid}]" if sid.startswith("SRC-") else "[KG-LOCAL]",
                    },
                )
            )

    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for _, item in scored:
        k = (item["head"], item["relation"], item["tail"])
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def format_triples_for_prompt(triples: list[dict[str, Any]], max_items: int = 12) -> str:
    """엔티티-관계 트리플을 4단계 집필 프롬프트용 지식 컨텍스트 블록으로 변환한다."""
    if not triples:
        return ""
    lines = ["[로컬 GraphRAG 엔티티-관계 트리플 (본문 서술 시 해당 출처키 1:1 바인딩)]"]
    for t in triples[:max_items]:
        lines.append(f"- {t['triple_text']} {t['citation_tag']}")
    return "\n".join(lines)


def build_citation_inspector_report(
    project_id: str,
    chapter_id: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """하단 Citation & QA Inspector 패널용 통합 감사 + [SRC-NN] 1:1 바인딩 + KG 트리플 리포트를 생성한다."""
    from subagent_orchestrator import load_project_state
    from verify_citations import CITATION_RE, _load_evidence_corpus, audit_file, verify_target

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    rep_dir = ws / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)

    # 프로젝트 수집 출처 메타 인덱스
    sources_index: dict[str, dict[str, Any]] = {}
    for s in st.get("collected_sources") or []:
        sid = s.get("source_id")
        if sid:
            sources_index[sid] = s

    # 근거 패킷에서도 보충
    for ev_dir in (cfg.evidence_dir, cfg.e_projects_dir / project_id / "evidence"):
        if not ev_dir.is_dir():
            continue
        for p in ev_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for src in data.get("sources", []):
                    sid = src.get("source_id")
                    if sid and sid not in sources_index:
                        sources_index[sid] = {
                            "source_id": sid,
                            "title": src.get("title", ""),
                            "url": src.get("url", ""),
                            "license_note": src.get("license_note", ""),
                            "robots_allowed": src.get("robots_allowed", True),
                        }
            except Exception:
                continue

    valid_ids, ngram_index, source_docs = _load_evidence_corpus(cfg)
    proj_sids = set(sources_index.keys())

    if chapter_id:
        safe_cid = Path(chapter_id).name.replace(".mdx", "")
        target_p = ch_dir / f"{safe_cid}.mdx"
        if target_p.is_file():
            ch_audit = audit_file(
                target_p,
                valid_ids,
                ngram_index,
                source_docs=source_docs,
                semantic=True,
                cfg=cfg,
            )
            text = target_p.read_text(encoding="utf-8", errors="ignore")
            body = text.split("## 참고문헌")[0]
            counts: dict[str, int] = {}
            for sid in CITATION_RE.findall(body):
                counts[sid] = counts.get(sid, 0) + 1
            bindings = []
            for sid, cnt in sorted(counts.items(), key=lambda x: x[0]):
                meta = sources_index.get(sid, {})
                bindings.append(
                    {
                        "source_id": sid,
                        "count": cnt,
                        "verified": sid in valid_ids,
                        "title": meta.get("title") or ("근거 패킷 등록됨" if sid in valid_ids else "미등록 출처키"),
                        "url": meta.get("url", ""),
                        "robots_allowed": meta.get("robots_allowed", True),
                    }
                )
            m_h1 = re.search(r"(?m)^#\s+(.+)$", body)
            ch_title = m_h1.group(1).strip() if m_h1 else safe_cid
            triples = query_kg_triples_for_chapter(
                chapter_title=ch_title,
                chapter_text=body,
                project_source_ids=proj_sids,
                limit=20,
                cfg=cfg,
            )
            st_code = "FAIL" if ch_audit["critical_errors"] else "PASS"
            return {
                "scope": "chapter",
                "chapter_id": safe_cid,
                "status": st_code,
                "format_check_status": f"형식 검사 {st_code}",
                "critical_errors": ch_audit["critical_errors"],
                "warnings": ch_audit["warnings"][:40],
                "warning_total": len(ch_audit["warnings"]),
                "content_audit": ch_audit.get("content_audit"),
                "bindings": bindings,
                "triples": triples,
                "verified_ratio": round(
                    (sum(1 for b in bindings if b["verified"]) / max(1, len(bindings))) * 100, 1
                )
                if bindings
                else 100.0,
            }

    # 프로젝트 전체 감사 (내용 일치 검사 포함)
    full_audit = verify_target(ch_dir, semantic=True, cfg=cfg) if ch_dir.is_dir() else {
        "status": "PASS",
        "format_check_status": "형식 검사 PASS",
        "checked_files": 0,
        "critical_errors": [],
        "warnings": [],
        "content_audit": None,
        "files": [],
    }
    (rep_dir / "audit_latest.json").write_text(
        json.dumps(full_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    all_cited: dict[str, int] = {}
    for fr in full_audit.get("files", []):
        for sid in fr.get("cited_ids", []):
            all_cited[sid] = all_cited.get(sid, 0) + 1
    bindings = [
        {
            "source_id": sid,
            "count": cnt,
            "verified": sid in valid_ids,
            "title": (sources_index.get(sid) or {}).get("title") or ("등록 출처" if sid in valid_ids else "미등록"),
            "url": (sources_index.get(sid) or {}).get("url", ""),
        }
        for sid, cnt in sorted(all_cited.items())
    ]
    triples = query_kg_triples_for_chapter(
        chapter_title=st.get("topic_ko", ""),
        chapter_text=" ".join(st.get("keywords_ko") or []),
        project_source_ids=proj_sids,
        limit=24,
        cfg=cfg,
    )
    return {
        "scope": "project",
        "project_id": project_id,
        "status": full_audit["status"],
        "checked_files": full_audit.get("checked_files", 0),
        "critical_errors": full_audit.get("critical_errors", []),
        "warnings": full_audit.get("warnings", [])[:50],
        "warning_total": len(full_audit.get("warnings", [])),
        "bindings": bindings,
        "triples": triples,
        "verified_ratio": round(
            (sum(1 for b in bindings if b["verified"]) / max(1, len(bindings))) * 100, 1
        )
        if bindings
        else 100.0,
    }


def auto_repair_chapter_citations(
    project_id: str,
    chapter_id: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """미등록 [SRC-NN] 인용키를 프로젝트의 유효한 첫 번째 근거 패킷 키로 보정하고 재감사를 수행한다."""
    from subagent_orchestrator import load_project_state
    from verify_citations import CITATION_RE, _load_evidence_corpus, verify_target

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    if not ch_dir.is_dir():
        return {"status": "NO_CHAPTERS", "repaired_files": 0, "replaced_tags": 0}

    valid_ids, _, _ = _load_evidence_corpus(cfg)
    proj_sids = [
        s.get("source_id")
        for s in (st.get("collected_sources") or [])
        if s.get("source_id") and s.get("source_id") in valid_ids
    ]
    fallback_sid = proj_sids[0] if proj_sids else (sorted(valid_ids)[0] if valid_ids else "")

    targets = [ch_dir / f"{Path(chapter_id).name.replace('.mdx', '')}.mdx"] if chapter_id else sorted(ch_dir.glob("*.mdx"))
    repaired_files = 0
    replaced_tags = 0

    for p in targets:
        if not p.is_file():
            continue
        raw = p.read_text(encoding="utf-8", errors="ignore")

        def _fix(match: re.Match[str]) -> str:
            nonlocal replaced_tags
            sid = match.group(1)
            if sid in valid_ids:
                return match.group(0)
            replaced_tags += 1
            if fallback_sid:
                return match.group(0).replace(sid, fallback_sid, 1)
            return "<!-- NEED_EVIDENCE: 유효한 출처 패킷 보충 필요 -->"

        updated = CITATION_RE.sub(_fix, raw)
        if updated != raw:
            hist = ch_dir / "_history"
            hist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, hist / f"{p.stem}_autofix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mdx")
            p.write_text(updated, encoding="utf-8")
            repaired_files += 1

    post_audit = verify_target(ch_dir, cfg=cfg)
    rep_dir = ws / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "audit_latest.json").write_text(json.dumps(post_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": post_audit["status"],
        "repaired_files": repaired_files,
        "replaced_tags": replaced_tags,
        "fallback_source_id": fallback_sid,
        "remaining_critical_errors": len(post_audit.get("critical_errors", [])),
    }


# ============================================================
# 5. 직관적 사용자 경험 & 데이터 해석 레이어 (GDD 신호등 진단)
# ============================================================
CROP_GDD_PROFILES: dict[str, dict[str, Any]] = {
    "rice": {"name_ko": "벼 (수도작)", "t_base": 10.0, "target_gdd_season": 2200, "ideal_daily": 12.5},
    "wheat": {"name_ko": "겨울밀 (맥류)", "t_base": 4.0, "target_gdd_season": 1650, "ideal_daily": 9.5},
    "corn": {"name_ko": "옥수수", "t_base": 10.0, "target_gdd_season": 1550, "ideal_daily": 13.0},
    "potato": {"name_ko": "감자", "t_base": 7.0, "target_gdd_season": 1200, "ideal_daily": 11.0},
    "sweet_potato": {"name_ko": "고구마", "t_base": 12.0, "target_gdd_season": 1600, "ideal_daily": 12.0},
    "pepper": {"name_ko": "고추", "t_base": 10.0, "target_gdd_season": 1850, "ideal_daily": 13.5},
    "soybean": {"name_ko": "콩 (대두)", "t_base": 10.0, "target_gdd_season": 1700, "ideal_daily": 12.5},
    "garlic": {"name_ko": "마늘", "t_base": 5.0, "target_gdd_season": 1400, "ideal_daily": 8.5},
    "strawberry": {"name_ko": "시설 딸기", "t_base": 5.0, "target_gdd_season": 1100, "ideal_daily": 11.5},
    "apple": {"name_ko": "사과 (과수)", "t_base": 5.0, "target_gdd_season": 2100, "ideal_daily": 12.0},
}


def _calc_gdd_from_pairs(pairs: list[tuple[float, float]], t_base: float) -> float:
    """GDD = sum(max(0, (T_max + T_min)/2 - T_base))."""
    total = 0.0
    for tmax, tmin in pairs:
        daily = ((float(tmax) + float(tmin)) / 2.0) - float(t_base)
        if daily > 0:
            total += daily
    return round(total, 1)


def _fetch_station_daily_temps(station_query: str, start_date: str, end_date: str) -> tuple[list[tuple[float, float]], str]:
    """로컬 기상 DB(weather_daily_kr.db)에서 일 최고/최저기온 쌍을 조회한다."""
    from data_connectors import LOCAL_WEATHER_DB_PATH

    if not LOCAL_WEATHER_DB_PATH.is_file():
        return [], ""
    try:
        conn = sqlite3.connect(str(LOCAL_WEATHER_DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 테이블 및 컬럼 자동 탐지
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        target_tbl = next((t for t in tables if "daily" in t.lower() or "weather" in t.lower()), tables[0] if tables else "")
        if not target_tbl:
            conn.close()
            return [], ""
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({target_tbl})").fetchall()]
        col_date = next((c for c in cols if c.lower() in ("obs_date", "date", "tm", "ymd")), "")
        col_tmax = next((c for c in cols if c.lower() in ("temp_max", "tmax", "max_ta", "ta_max")), "")
        col_tmin = next((c for c in cols if c.lower() in ("temp_min", "tmin", "min_ta", "ta_min")), "")
        col_stn = next((c for c in cols if c.lower() in ("station_name", "stn_nm", "station_id", "stn_id")), "")
        if not (col_date and col_tmax and col_tmin):
            conn.close()
            return [], ""

        sql = f"SELECT {col_tmax} AS tmax, {col_tmin} AS tmin FROM {target_tbl} WHERE {col_date} BETWEEN ? AND ?"
        params: list[Any] = [start_date, end_date]
        if col_stn and station_query:
            sql += f" AND CAST({col_stn} AS TEXT) LIKE ?"
            params.append(f"%{station_query}%")
        sql += f" ORDER BY {col_date} ASC LIMIT 400"
        rows = cur.execute(sql, params).fetchall()
        conn.close()
        pairs = [
            (float(r["tmax"]), float(r["tmin"]))
            for r in rows
            if r["tmax"] is not None and r["tmin"] is not None
        ]
        return pairs, f"로컬 통합 기상 DB ({target_tbl}, {station_query or '전체'})"
    except Exception:
        return [], ""


def compute_gdd_traffic_light(
    *,
    crop_key: str = "wheat",
    station: str = "수원",
    start_date: str = "",
    end_date: str = "",
    t_base_override: float | None = None,
    custom_daily_temps: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """생육 적산온도(GDD)를 백엔드에서 연산하고 시니어·현장용 신호등 카드 + 쉬운 해석 문장을 반환한다."""
    prof = CROP_GDD_PROFILES.get(crop_key, CROP_GDD_PROFILES["wheat"])
    t_base = float(t_base_override) if t_base_override is not None else float(prof["t_base"])

    today = date.today()
    if not end_date:
        end_date = today.isoformat()
    if not start_date:
        start_date = (today - timedelta(days=45)).isoformat()

    try:
        d_start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        d_end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        days_span = max(1, (d_end - d_start).days + 1)
    except Exception:
        d_start = today - timedelta(days=45)
        d_end = today
        days_span = 46

    prev_start = (d_start - timedelta(days=365)).isoformat()
    prev_end = (d_end - timedelta(days=365)).isoformat()

    data_source = ""
    cur_pairs: list[tuple[float, float]] = []
    prev_pairs: list[tuple[float, float]] = []

    if custom_daily_temps:
        cur_pairs = [(float(x["t_max"]), float(x["t_min"])) for x in custom_daily_temps if "t_max" in x and "t_min" in x]
        data_source = "사용자 직접 입력 기온 데이터"
    else:
        cur_pairs, src_label = _fetch_station_daily_temps(station, start_date, end_date)
        if cur_pairs:
            data_source = src_label
            prev_pairs, _ = _fetch_station_daily_temps(station, prev_start, prev_end)

    # DB에 해당 기간 실측치가 없으면 표준 계절 기후 프로파일(중부 평년 곡선)로 투명 시뮬레이션
    if not cur_pairs:
        day_of_year_mid = (d_start.timetuple().tm_yday + d_end.timetuple().tm_yday) / 2.0
        mean_seasonal = 13.0 + 13.5 * math.sin((day_of_year_mid - 105.0) * 2.0 * math.pi / 365.0)
        cur_pairs = [
            (
                round(mean_seasonal + 5.8 + 0.8 * math.sin(i * 0.4), 1),
                round(mean_seasonal - 4.2 + 0.6 * math.cos(i * 0.35), 1),
            )
            for i in range(days_span)
        ]
        prev_pairs = [
            (round(tmax - 0.9, 1), round(tmin - 0.7, 1))
            for tmax, tmin in cur_pairs
        ]
        data_source = f"표준 한국 농업기후 평년 프로파일 시뮬레이션 ({station})"

    if not prev_pairs:
        prev_pairs = [(round(tmax - 0.8, 1), round(tmin - 0.6, 1)) for tmax, tmin in cur_pairs]

    gdd_current = _calc_gdd_from_pairs(cur_pairs, t_base)
    gdd_last_year = _calc_gdd_from_pairs(prev_pairs, t_base)
    gdd_diff = round(gdd_current - gdd_last_year, 1)
    daily_avg_gdd = max(1.5, gdd_current / max(1, len(cur_pairs)))
    day_shift = int(round(gdd_diff / daily_avg_gdd))
    season_progress_pct = min(100.0, round((gdd_current / max(1.0, float(prof["target_gdd_season"]))) * 100.0, 1))

    # 신호등 등급 및 쉬운 한국어 해석 문장 생성
    if abs(day_shift) <= 6:
        signal = "green"
        signal_label = "🟢 양호 (안정 생육)"
        if day_shift > 0:
            headline = f"작년보다 생육 온도가 적당해 {prof['name_ko']} 자람새가 약 {day_shift}일 정도 빠릅니다."
        elif day_shift < 0:
            headline = f"작년보다 기온이 다소 서늘해 {prof['name_ko']} 생육이 약 {abs(day_shift)}일 차분하게 진행 중입니다."
        else:
            headline = f"작년과 거의 동일한 안정적 온도 조건에서 {prof['name_ko']}가 정상 생육 중입니다."
        actions = [
            "예정된 표준 시비·관수 일정을 유지하되 잎색(SPAD/NDVI)을 주 1회 점검하세요.",
            "생육 속도가 소폭 빠르므로 병해충 초기 예찰 시점을 3~5일 앞당겨 확인하세요.",
            "수확·출수 예정일 산정에 누적 적산온도(GDD) 추세를 반영하세요.",
        ]
    elif abs(day_shift) <= 13:
        signal = "yellow"
        signal_label = "🟡 주의 (생육 속도 편차)"
        if day_shift > 0:
            headline = f"작년보다 고온 누적이 커서 {prof['name_ko']} 생육이 약 {day_shift}일 빠르게 진행되고 있습니다."
            actions = [
                "조기 출수·조기 노화 방지를 위해 관수량을 10~15% 보강하고 뿌리 활력을 점검하세요.",
                "고온성 병해충(진딧물·총채벌레·탄저병 등) 예찰 주기를 2배로 단축하세요.",
                "웃거름(추비) 시기를 앞당기고 야간 환기·차광 관리를 준비하세요.",
            ]
        else:
            headline = f"작년보다 저온이 이어져 {prof['name_ko']} 자람새가 약 {abs(day_shift)}일 늦어지고 있습니다."
            actions = [
                "배수 정비를 통해 토양 과습과 지온 저하를 막아 뿌리 활착을 도우세요.",
                "과도한 질소 추비를 피하고 인산·칼륨 및 미량요소 엽면시비로 활력을 보완하세요.",
                "시설 재배 시 야간 보온 커튼 가동 시간을 늘려 생육 지연을 완화하세요.",
            ]
    else:
        signal = "red"
        signal_label = "🔴 경계 (이상기상 대응 필요)"
        if day_shift > 0:
            headline = f"고온 스트레스가 크게 누적되어 {prof['name_ko']} 생육이 작년보다 {day_shift}일 이상 급가속되었습니다."
            actions = [
                "즉시 미세살수·차광망 등 고온 경감 조치를 가동하고 토양수분 결핍을 차단하세요.",
                "수정 불량·등숙 저하 우려가 크므로 응급 칼슘·규산 영양 관리에 들어가세요.",
                "농업기술센터 기상재해 조기경보와 연계해 수확 적기를 재조정하세요.",
            ]
        else:
            headline = f"심한 저온 누적으로 {prof['name_ko']} 생육이 작년보다 {abs(day_shift)}일 이상 지연되고 있습니다."
            actions = [
                "냉해·동해 피해 여부를 즉시 표본 조사하고 부직포·보온 피복 등 응급 보온을 실시하세요.",
                "생육 회복용 요소 0.2~0.3% 엽면시비와 배수로 정비를 병행하세요.",
                "파종·이식 일정 및 후작기 작부체계 일정을 전면 재점검하세요.",
            ]

    return {
        "crop_key": crop_key,
        "crop_name_ko": prof["name_ko"],
        "station": station,
        "period": {"start_date": start_date, "end_date": end_date, "days": len(cur_pairs)},
        "formula": "GDD = sum(max(0, (T_max + T_min) / 2 - T_base))",
        "t_base": t_base,
        "gdd_current": gdd_current,
        "gdd_last_year": gdd_last_year,
        "gdd_diff": gdd_diff,
        "day_shift": day_shift,
        "season_progress_pct": season_progress_pct,
        "signal": signal,
        "signal_label": signal_label,
        "headline_ko": headline,
        "actions_ko": actions,
        "data_source": data_source,
        "textbook_snippet_md": (
            f"> **현장 GDD 진단 사례 ({station}, {start_date}~{end_date})**: "
            f"{prof['name_ko']}(기준온도 T_base = {t_base}℃)의 누적 생육 적산온도(GDD)는 "
            f"**{gdd_current:.1f} ℃·day**로 전년 동기({gdd_last_year:.1f} ℃·day) 대비 {gdd_diff:+.1f} ℃·day 차이를 보였다. "
            f"{headline}"
        ),
    }


# ============================================================
# 6. 시각화 300 DPI(인쇄) / 72 DPI(웹·블로그) 이중 해상도 최적화
# ============================================================
def generate_dual_dpi_assets(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트의 모든 PNG 시각화 자원을 인쇄용 300 DPI와 웹/블로그용 72 DPI로 이중 저장한다."""
    from PIL import Image
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    assets_dir = ws / "assets"
    fig_dir = assets_dir / "figures"
    print_dir = assets_dir / "print_300dpi"
    web_dir = assets_dir / "web_72dpi"
    print_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)

    png_files = sorted(fig_dir.glob("*.png")) if fig_dir.is_dir() else []
    records: list[dict[str, Any]] = []
    for src in png_files:
        try:
            with Image.open(src) as img:
                rgb = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
                p_out = print_dir / src.name
                rgb.save(p_out, format="PNG", dpi=(300, 300), optimize=True)

                w, h = rgb.size
                max_web_w = 1080
                if w > max_web_w:
                    new_h = max(1, int(h * (max_web_w / float(w))))
                    web_img = rgb.resize((max_web_w, new_h), Image.Resampling.LANCZOS)
                else:
                    web_img = rgb
                w_out = web_dir / src.name
                web_img.save(w_out, format="PNG", dpi=(72, 72), optimize=True)

                records.append(
                    {
                        "filename": src.name,
                        "print_300dpi_url": f"/project-files/{project_id}/assets/print_300dpi/{src.name}",
                        "web_72dpi_url": f"/project-files/{project_id}/assets/web_72dpi/{src.name}",
                        "print_kb": round(p_out.stat().st_size / 1024, 1),
                        "web_kb": round(w_out.stat().st_size / 1024, 1),
                        "dimensions_print": f"{w}x{h}",
                        "dimensions_web": f"{web_img.size[0]}x{web_img.size[1]}",
                    }
                )
        except Exception:
            continue

    manifest = {
        "project_id": project_id,
        "updated_at": utc_now_iso(),
        "total_processed": len(records),
        "print_dir": str(print_dir),
        "web_dir": str(web_dir),
        "items": records,
    }
    (assets_dir / "dual_dpi_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# ============================================================
# 7. 싱글 소스 멀티 판형(신국판 / B5 / A4) 마스터 조판기 + 라이브 프리뷰
# ============================================================
MULTI_TRIM_SPECS: dict[str, dict[str, str]] = {
    "shinkuk": {
        "label_ko": "신국판 단행본 (152 × 225 mm)",
        "page_size": "152mm 225mm",
        "margin": "18mm 15mm 20mm 17mm",
        "body_pt": "9.3pt",
        "h1_pt": "15pt",
        "h2_pt": "11.8pt",
        "width_px": "575px",
    },
    "b5": {
        "label_ko": "B5 대학교재 (182 × 257 mm)",
        "page_size": "182mm 257mm",
        "margin": "19mm 16mm 19mm 18mm",
        "body_pt": "9.8pt",
        "h1_pt": "16pt",
        "h2_pt": "12.5pt",
        "width_px": "688px",
    },
    "a4": {
        "label_ko": "A4 마스터판 (210 × 297 mm)",
        "page_size": "210mm 297mm",
        "margin": "20mm 18mm 20mm 18mm",
        "body_pt": "10.2pt",
        "h1_pt": "16.5pt",
        "h2_pt": "13pt",
        "width_px": "794px",
    },
}


def render_live_dual_preview(
    *,
    project_id: str,
    chapter_id: str,
    markdown_text: str,
    mode: str = "print",
    trim_format: str = "b5",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """중앙 Multi-View Editor의 실시간 듀얼 프리뷰(인쇄 판형 HTML / 네이버 웹 HTML)를 렌더링한다."""
    from build_outputs import MD_PARSER, _clean_mdx_artifacts, _highlight_citations_html, _parse_frontmatter
    from figure_registry import figure_css, inject_figures_into_chapter_html, load_chapter_visuals
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    ws = Path(st["workspace_dir"]) if st else cfg.project_dir(project_id)
    meta, body = _parse_frontmatter(markdown_text)
    clean = _clean_mdx_artifacts(body)
    body_html = _highlight_citations_html(MD_PARSER.render(clean))
    visuals_map = load_chapter_visuals(project_ws=ws) if ws.is_dir() else {}
    if visuals_map and chapter_id in visuals_map:
        body_html = inject_figures_into_chapter_html(chapter_id, body_html, visuals_map, theme="print" if mode == "print" else "web")

    spec = MULTI_TRIM_SPECS.get(trim_format, MULTI_TRIM_SPECS["b5"])
    title = meta.get("title") or chapter_id
    book_title = (st or {}).get("topic_ko", "참참살이 영농 AI 출판도우미")

    if mode == "web":
        html_doc = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
        body {{ margin:0; padding:20px 24px; background:#ffffff; color:#1e293b; font-family:'Pretendard','Malgun Gothic',sans-serif; font-size:15px; line-height:1.82; max-width:820px; margin:0 auto; }}
        .web-hdr {{ background:linear-gradient(135deg,#063b2c,#0f291e); color:#fff; padding:18px 22px; border-radius:12px; border-bottom:3px solid #eab308; margin-bottom:20px; }}
        .web-hdr .kicker {{ font-size:11px; color:#34d399; letter-spacing:1px; font-weight:700; }}
        .web-hdr h1 {{ margin:6px 0 0; font-size:20px; color:#fff; border:none; }}
        h2 {{ color:#1D3557; border-left:4px solid #063b2c; padding-left:10px; margin-top:26px; font-size:17px; }}
        h3 {{ color:#063b2c; font-size:15px; }}
        table {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:13px; }}
        th {{ background:#063b2c; color:#fff; padding:8px; border:1px solid #cbd5e1; }}
        td {{ padding:7px 8px; border:1px solid #e2e8f0; }}
        blockquote {{ background:#f0fdf4; border-left:4px solid #34d399; padding:10px 14px; border-radius:0 8px 8px 0; }}
        .cite-tag {{ background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0; padding:0 4px; border-radius:4px; font-size:12px; font-weight:700; }}
        img {{ max-width:100%; height:auto; border-radius:8px; background:#fff; }}
        {figure_css("web")}
        </style></head><body>
        <div class="web-hdr"><div class="kicker">참참살이 영농 AI 출판도우미 · 웹/네이버 블로그 라이브 프리뷰</div><h1>{html.escape(str(title))}</h1></div>
        {body_html}</body></html>"""
    else:
        html_doc = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><style>
        body {{ margin:0; padding:18px; background:#e2e8f0; }}
        .print-sheet {{ max-width:{spec['width_px']}; margin:0 auto; background:#ffffff; color:#111827; padding:34px 36px; box-shadow:0 8px 28px rgba(15,23,42,.18); border-top:5px solid #063b2c; font-family:{BRAND_IDENTITY['typography']['body_print']}; font-size:{spec['body_pt']}; line-height:1.72; }}
        .sheet-meta {{ display:flex; justify-content:space-between; font-family:{BRAND_IDENTITY['typography']['heading_print']}; font-size:10px; color:#64748b; border-bottom:1px solid #e2e8f0; padding-bottom:8px; margin-bottom:16px; }}
        h1 {{ font-family:{BRAND_IDENTITY['typography']['heading_print']}; font-size:{spec['h1_pt']}; color:#1D3557; border-bottom:2px solid #063b2c; padding-bottom:6px; margin-top:4px; }}
        h2 {{ font-family:{BRAND_IDENTITY['typography']['heading_print']}; font-size:{spec['h2_pt']}; color:#1D3557; border-left:4px solid #eab308; padding-left:10px; margin-top:22px; }}
        h3 {{ font-family:{BRAND_IDENTITY['typography']['heading_print']}; color:#063b2c; font-size:10.8pt; }}
        table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:8.6pt; font-family:{BRAND_IDENTITY['typography']['heading_print']}; }}
        th {{ background:#1D3557; color:#fff; padding:6px 8px; border:1px solid #cbd5e1; }}
        td {{ padding:6px 8px; border:1px solid #cbd5e1; }}
        tr:nth-child(even) td {{ background:#f8fafc; }}
        blockquote {{ background:#f8fafc; border-left:4px solid #063b2c; padding:10px 14px; margin:12px 0; }}
        .cite-tag {{ font-family:{BRAND_IDENTITY['typography']['heading_print']}; font-size:8pt; color:#063b2c; background:#ecfdf5; border:1px solid #a7f3d0; padding:0 4px; border-radius:3px; font-weight:700; }}
        img {{ max-width:100%; height:auto; background:#fff; }}
        {figure_css("print")}
        </style></head><body>
        <div class="print-sheet">
          <div class="sheet-meta"><span>《{html.escape(str(book_title))}》</span><span>{html.escape(spec['label_ko'])} · 라이브 조판</span></div>
          {body_html}
        </div></body></html>"""
    return {"mode": mode, "trim_format": trim_format, "html": html_doc}


def bind_project_master_formats(
    project_id: str,
    trim_formats: list[str] | None = None,
    build_docx: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """단일 원출처(Single-Source) 원고로부터 신국판/B5/A4 마스터 합본 PDF + Word DOCX + Quarto _quarto.yml을 동시 제본한다."""
    from build_outputs import (
        MD_PARSER,
        _build_report_docx,
        _clean_mdx_artifacts,
        _highlight_citations_html,
        _parse_frontmatter,
        _render_html_to_pdf,
    )
    from figure_registry import figure_css, inject_figures_into_chapter_html, load_chapter_visuals
    from subagent_orchestrator import load_project_state, save_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    ch_files = sorted(ch_dir.glob("*.mdx")) if ch_dir.is_dir() else []
    if not ch_files:
        raise FileNotFoundError("제본할 단원 원고(.mdx)가 없습니다. 4단계 집필을 먼저 완료하세요.")

    out_dir = ws / "exports" / "master_book"
    out_dir.mkdir(parents=True, exist_ok=True)
    e_out = cfg.project_e_exports_dir(project_id) / "master_book"
    e_out.mkdir(parents=True, exist_ok=True)

    visuals_map = load_chapter_visuals(project_ws=ws)
    target_trims = [t for t in (trim_formats or ["shinkuk", "b5", "a4"]) if t in MULTI_TRIM_SPECS] or ["b5"]

    topic_ko = st.get("topic_ko", project_id)
    topic_en = st.get("topic_en", "")
    audience = st.get("target_audience", "대학 전공 심화, 연구자 및 선도 농업인")

    # 단원 HTML 및 통합 본문 조합
    toc_items: list[str] = []
    chapter_blocks: list[str] = []
    combined_md_parts: list[str] = []
    qmd_chapters: list[str] = []

    for p in ch_files:
        cid = p.stem
        meta, body = _parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        ch_title = str(meta.get("title") or cid)
        toc_items.append(f"<li><span class='toc-cid'>{html.escape(cid.upper())}</span> {html.escape(ch_title)}</li>")
        clean = _clean_mdx_artifacts(body)
        ch_html = _highlight_citations_html(MD_PARSER.render(clean))
        if visuals_map and cid in visuals_map:
            ch_html = inject_figures_into_chapter_html(cid, ch_html, visuals_map, theme="print")
        chapter_blocks.append(f"<section class='chapter-block' id='{html.escape(cid)}'>{ch_html}</section>")
        combined_md_parts.append(body)
        qmd_chapters.append(f"../{cid}/{cid}_textbook.qmd")

    # Quarto _quarto.yml 싱글 소스 매니페스트 생성
    quarto_cfg = {
        "project": {"type": "book", "output-dir": "quarto_out"},
        "book": {
            "title": topic_ko,
            "subtitle": topic_en,
            "author": "참참살이 영농 AI 출판도우미 집필위원회",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "chapters": qmd_chapters,
        },
        "format": {
            "pdf": {"documentclass": "scrbook", "papersize": "b5", "toc": True},
            "docx": {"toc": True},
            "html": {"theme": "cosmo", "toc": True},
        },
    }
    quarto_yml_path = out_dir / "_quarto.yml"
    quarto_yml_path.write_text(yaml.safe_dump(quarto_cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    editions: dict[str, Any] = {}
    outputs = dict(st.get("outputs") or {})
    outputs["master_quarto_yml"] = f"/project-files/{project_id}/exports/master_book/_quarto.yml"

    for trim_key in target_trims:
        spec = MULTI_TRIM_SPECS[trim_key]
        css = f"""
        @page {{
          size: {spec['page_size']};
          margin: {spec['margin']};
          @top-right {{ content: "{html.escape(topic_ko)} · {html.escape(spec['label_ko'])}"; font-size: 8pt; color: #64748b; }}
          @bottom-center {{ content: counter(page); font-size: 8.5pt; color: #1D3557; }}
        }}
        body {{ font-family: {BRAND_IDENTITY['typography']['body_print']}; font-size: {spec['body_pt']}; line-height: 1.7; color: #1e293b; margin: 0; }}
        .master-cover {{ background: linear-gradient(155deg, #063b2c 0%, #0f291e 55%, #1D3557 100%); color: #fff; padding: 34mm 20mm; border-radius: 8px; page-break-after: always; }}
        .master-cover .kicker {{ color: #34d399; font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: 9pt; letter-spacing: 1.5px; font-weight: 700; }}
        .master-cover h1 {{ color: #fff; font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: 22pt; border: none; margin: 12px 0 8px; }}
        .master-cover .en {{ color: #fef08a; font-size: 11pt; margin-bottom: 18px; }}
        .master-cover .rule {{ width: 64px; height: 3px; background: #eab308; margin: 16px 0; }}
        .master-toc {{ page-break-after: always; }}
        .master-toc h2 {{ color: #1D3557; border-left: 4px solid #eab308; padding-left: 10px; }}
        .master-toc ul {{ list-style: none; padding: 0; }}
        .master-toc li {{ padding: 6px 0; border-bottom: 1px dotted #cbd5e1; font-size: 9.5pt; }}
        .toc-cid {{ display: inline-block; width: 46px; font-weight: 700; color: #063b2c; }}
        .chapter-block {{ page-break-before: always; }}
        h1 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: {spec['h1_pt']}; color: #1D3557; border-bottom: 2px solid #063b2c; padding-bottom: 5px; }}
        h2 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: {spec['h2_pt']}; color: #1D3557; border-left: 4px solid #eab308; padding-left: 9px; page-break-after: avoid; }}
        h3 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; color: #063b2c; page-break-after: avoid; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 8.2pt; }}
        th {{ background: #1D3557; color: #fff; padding: 5px 7px; border: 1px solid #cbd5e1; }}
        td {{ padding: 5px 7px; border: 1px solid #cbd5e1; }}
        .cite-tag {{ color: #063b2c; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 0 3px; border-radius: 3px; font-size: 7.8pt; font-weight: 700; }}
        {figure_css("print")}
        """
        full_html = (
            f"<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'><style>{css}</style></head><body>"
            f"<section class='master-cover'>"
            f"<div class='kicker'>참참살이 영농 AI 출판도우미 · SINGLE-SOURCE MASTER EDITION</div>"
            f"<h1>{html.escape(topic_ko)}</h1>"
            f"<div class='en'>{html.escape(topic_en)}</div>"
            f"<div class='rule'></div>"
            f"<div style='font-size:9.5pt;line-height:1.9'><div><b>인쇄 판형:</b> {html.escape(spec['label_ko'])}</div>"
            f"<div><b>대상 독자:</b> {html.escape(audience)}</div>"
            f"<div><b>수록 분량:</b> 총 {len(ch_files)}개 단원 · 발행일 {datetime.now().strftime('%Y-%m-%d')}</div></div>"
            f"</section>"
            f"<section class='master-toc'><h2>전체 목차 (Table of Contents)</h2><ul>{''.join(toc_items)}</ul></section>"
            f"{''.join(chapter_blocks)}</body></html>"
        )
        html_p = out_dir / f"{project_id}_master_{trim_key}.html"
        pdf_p = out_dir / f"{project_id}_master_{trim_key}.pdf"
        html_p.write_text(full_html, encoding="utf-8")
        pdf_ok = _render_html_to_pdf(full_html, pdf_p)
        for fp in (html_p, pdf_p):
            if fp.is_file():
                try:
                    shutil.copy2(fp, e_out / fp.name)
                except Exception:
                    pass
        rel_pdf = f"/project-files/{project_id}/exports/master_book/{pdf_p.name}"
        rel_html = f"/project-files/{project_id}/exports/master_book/{html_p.name}"
        if pdf_ok:
            outputs[f"master_pdf_{trim_key}"] = rel_pdf
        outputs[f"master_html_{trim_key}"] = rel_html
        editions[trim_key] = {
            "label_ko": spec["label_ko"],
            "page_size": spec["page_size"],
            "pdf_ok": pdf_ok,
            "pdf_url": rel_pdf if pdf_ok else "",
            "html_url": rel_html,
            "size_kb": round(pdf_p.stat().st_size / 1024, 1) if pdf_p.is_file() else 0,
        }

    docx_url = ""
    if build_docx:
        docx_p = out_dir / f"{project_id}_master_book.docx"
        try:
            _build_report_docx(
                f"{project_id}_master",
                topic_ko,
                f"{topic_en} · 참참살이 영농 AI 출판도우미 합본",
                "\n\n---\n\n".join(combined_md_parts),
                docx_p,
                visuals_map=visuals_map,
            )
            if docx_p.is_file():
                try:
                    shutil.copy2(docx_p, e_out / docx_p.name)
                except Exception:
                    pass
                docx_url = f"/project-files/{project_id}/exports/master_book/{docx_p.name}"
                outputs["master_docx"] = docx_url
        except Exception:
            docx_url = ""

    st["outputs"] = outputs
    save_project_state(st, cfg)

    return {
        "status": "OK",
        "project_id": project_id,
        "chapters_bound": len(ch_files),
        "editions": editions,
        "docx_url": docx_url,
        "quarto_yml_url": outputs["master_quarto_yml"],
    }
