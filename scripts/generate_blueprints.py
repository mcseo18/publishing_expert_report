"""master_outline.yaml(5부 16개 단원 540p)에서 아직 청사진 YAML이 없는 나머지 12개 단원의
상세 단원 청사진(content/blueprints/chNN.yaml)을 자동 생성하고,
각 단원에 해당하는 C:\\SMC_GRAPHRAG 기존 지식 + 큐레이션 근거 패킷을 일괄 동기화한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from config import PlatformConfig, get_config
from export_kg_evidence import export_kg_reuse_evidence
from sync_chapter_packets import sync_packets

# 나머지 12개 단원별 C:\SMC_GRAPHRAG 선조회 키워드 및 절별 세분화 설계
CHAPTER_SPECS: dict[str, dict[str, Any]] = {
    "ch02": {
        "kg_terms": "유기물,분해,탄질비,리그닌,셀룰로오스,식물 잔사,퇴비",
        "sections": [
            ("2.1", "토양 유기물의 기원과 식물 잔사·근권 삼출물의 생화학적 조성", "표 2-1: 주요 식물 잔사·녹비·퇴비 원료별 C/N비 및 생화학 분획 특성 비교"),
            ("2.2", "환경 요인(온도 Q10·수분·통기성·pH)에 따른 유기물 분해 속도 조절", "표 2-2: 토양 온도·수분·호기/혐기 조건별 유기물 분해 반응 요약"),
            ("2.3", "잔사 분해 초기 질량 손실 동태와 휴민화 계수·탄소 잔존율", "표 2-3: 유기성 자재 유형별 단기 분해 특성과 토양 잔존 탄소 기여도"),
        ],
    },
    "ch03": {
        "kg_terms": "부식,부식질,부식산,휴믹산,풀빅산,점토 광물,광물",
        "sections": [
            ("3.1", "전통적 부식화(Humification) 이론: 부식산(HA)·풀빅산(FA)·휴민의 화학", "표 3-1: 부식산(HA)·풀빅산(FA)·휴민(Humin)의 용해도·작용기·특성 비교"),
            ("3.2", "현대 토양 연속체 모델과 미생물 탄소 펌프(MCP)·미생물 사체(Necromass)", "표 3-2: 전통적 부식 중합 가설 vs 현대 미생물 탄소 펌프(MCP) 이론 비교"),
            ("3.3", "광물 표면 안정화 기작(점토·비정질 산화철/알루미늄 복합체)", "표 3-3: 유기-광물 결합 메커니즘별 결합 강도 및 토양 pH 의존성"),
        ],
    },
    "ch04": {
        "kg_terms": "단립,입단,토양 구조,수분,공극,경운,토양 침식",
        "sections": [
            ("4.1", "단립 계층 모델(Aggregate Hierarchy)과 POM·균사·다당류의 결합 역할", "표 4-1: 대단립(>250 μm)과 소단립(53~250 μm)의 형성 인자 및 탄소 보호 기간"),
            ("4.2", "토양 유기물과 유효수분보유능(AWC), 침투율 및 가뭄 저항성", "표 4-2: 유기물 증진에 따른 토양 물리성(보수성·침투율·용적밀도) 개선 효과"),
            ("4.3", "경운 교란에 의한 단립 파괴와 물리적 보호 탄소(Aggregate-C) 손실 관리", "표 4-3: 관행 경운 vs 무경운·최소경운의 단립 안정성 및 탄소 분포 비교"),
        ],
    },
    "ch05": {
        "kg_terms": "양이온치환용량,양이온교환용량,CEC,pH,인산,중금속,킬레이트",
        "sections": [
            ("5.1", "유기물 작용기(카르복실·페놀기)의 pH 의존 음전하와 양이온치환용량(CEC)", "표 5-1: 점토광물 대비 토양 유기물·부식질의 CEC 및 전하 특성 비교"),
            ("5.2", "유기산 킬레이트화, 인산 고정 저감 및 필수 양분 유효도 증진", "표 5-2: 토양 유기물 함량과 주요 양분(N·P·K·미량원소) 가용성 상호작용"),
            ("5.3", "토양 유기물·탄소계 흡착제의 중금속 및 잔류성 유기오염물질 거동 제어", "표 5-3: 중금속·잔류성 농약에 대한 유기물 및 탄소계 흡착제 저감 기작"),
        ],
    },
    "ch06": {
        "kg_terms": "미생물,근권,균근균,토양 생물,효소,지렁이,호흡",
        "sections": [
            ("6.1", "토양 미생물 군집(세균·균근균 AMF·PGPR)과 근권 생태계 상호작용", "표 6-1: 세균·균근균(AMF)·PGPR의 유기물 변환 및 작물 양분흡수 기여"),
            ("6.2", "토양 대형동물(지렁이 등)의 생태계 공학과 토양 먹이망", "표 6-2: 지렁이 활동이 토양 단립·유기물 혼합·생태계 서비스에 미치는 영향"),
            ("6.3", "프라이밍 효과(Priming Effect)와 미생물 생체량·토양 효소 진단", "표 6-3: 양성·음성 프라이밍 효과 발생 조건 및 관리 시사점"),
        ],
    },
    "ch08": {
        "kg_terms": "토양 유기물,분석,유기탄소,FTIR,13C-NMR,E4/E6,토양검정",
        "sections": [
            ("8.1", "습식산화법(Tyurin·Walkley-Black), 건식연소법(Dumas) 및 강열감량법(LOI)", "표 8-1: 토양 유기탄소·유기물 4대 표준 정량분석법 비교"),
            ("8.2", "Van Bemmelen 환산계수의 한계와 현장 신속 추정(토색판·SPAD 503)", "표 8-2: 실험실 정밀 분석 vs 현장 신속 추정 지표의 장단점 비교"),
            ("8.3", "분광·핵자기공명 정성 분석(UV-Vis E4/E6 비, FTIR, 13C-NMR, Vis-NIR)", "표 8-3: 주요 분광 분석법별 유기물 화학구조 판독 지표 요약"),
        ],
    },
    "ch09": {
        "kg_terms": "흙토람,토양검정,분획,유기물 함량,토양건강,활성 풀",
        "sections": [
            ("9.1", "물리적 분획 표준 프로토콜: 입자크기(53 μm) 및 밀도 분획(POM·MAOM)", "표 9-1: POM과 MAOM 물리 분획의 실험 절차 및 해석 기준"),
            ("9.2", "민감 토양유기물 지표: 활성탄소(POXC), 용존유기물(DOM) 및 생물 지표", "표 9-2: 단기 관리 민감 지표(POXC·POM) vs 장기 저장 지표(MAOM·SOC)"),
            ("9.3", "국내외 토양건강 종합평가 체계 비교: 한국 흙토람 vs 미국 Cornell CASH vs EU", "표 9-3: 한국 흙토람·미국 Cornell CASH·유럽 토양건강 평가 지표 비교"),
        ],
    },
    "ch12": {
        "kg_terms": "논토양,밭토양,시설재배,흙토람,염류,적정,시비",
        "sections": [
            ("12.1", "담수 논토양 vs 호기 밭토양의 유기물 분해·축적 동태 차이", "표 12-1: 논토양(혐기)·밭토양(호기)·시설재배지의 유기물 동태 비교"),
            ("12.2", "시설재배지 유기물·염류집적 관리 및 토양수분 연계 제어", "표 12-2: 시설재배지 과다 시용 문제 진단 및 적정 유기물 유지 대책"),
            ("12.3", "한국(흙토람) vs 일본(MAFF 도도부현) 농경지 시비·유기물 적정 기준 비교", "표 12-3: 한국 흙토람과 일본 농림수산성(MAFF) 토양·시비 관리 체계 비교"),
        ],
    },
    "ch13": {
        "kg_terms": "퇴비,가축분퇴비,부숙도,헤어리베치,녹비,무경운,보전농업",
        "sections": [
            ("13.1", "완숙 퇴비의 부숙도·비료공정규격과 토양 유기물·부식산 증진 효과", "표 13-1: 가축분퇴비·완숙퇴비의 품질 지표 및 토양 개량 효과"),
            ("13.2", "녹비작물(헤어리베치 등), 작물잔사 환원 및 깊이거름주기 탄소중립 실증", "표 13-2: 유기성 자재(퇴비·녹비·짚류)별 탄소 축적 및 작물 수량 반응"),
            ("13.3", "피복작물·무경운·윤작 기반 보전농업의 유기물 관리 전략(USDA SARE 사례)", "표 13-3: 보전농업 실천 기술별 표토·심토 유기물 변화와 현장 트레이드오프"),
        ],
    },
    "ch14": {
        "kg_terms": "바이오차,부식산,풀빅산,옥신,갈탄,탄소격리",
        "sections": [
            ("14.1", "바이오차(Biochar)의 열분해 특성, 난분해성 안정성 및 토양 개량 기작", "표 14-1: 바이오차 원료·열분해 온도별 물리화학적 특성 요약"),
            ("14.2", "농지 바이오차 시용 기준과 실증: 일본 MAFF 상한 지침 및 화산회 논토양 왕겨 바이오차", "표 14-2: 바이오차 농지 적용 시 탄소격리·온실가스(CH4/N2O) 및 시용량 주의사항"),
            ("14.3", "기능성 부식산·풀빅산 자재의 생리활성(옥신 유사 활성)과 과학적 적용 기준", "표 14-3: 부식산(HA)·풀빅산(FA) 자재의 토양·작물 효과와 검증 한계"),
        ],
    },
    "ch15": {
        "kg_terms": "심토,이탄,소택토,산림,초지,화산회토,토양 탄소",
        "sections": [
            ("15.1", "심토(Subsoil, 30~100 cm+)의 MAOM 미포화 저장 잠재력과 뿌리 탄소", "표 15-1: 표토(0~30 cm) vs 심토(30~100 cm)의 MAOM 포화도 및 탄소 격리 효율"),
            ("15.2", "이탄지·습지(소택토) 및 산림·초지 생태계의 토양 유기탄소 동태와 취약성", "표 15-2: 생태계 유형별(농경지·초지·산림·이탄지) 토양유기탄소 축적 특성"),
            ("15.3", "화산회토(Andosol)의 비정질 광물 보호 기작과 기후 온난화(Q10) 피드백", "표 15-3: 화산회토 비정질 광물(알로페인 등)의 유기물 안정화 및 온난화 민감도"),
        ],
    },
    "ch16": {
        "kg_terms": "탄소중립,탄소격리,저탄소,기후변화,토양탄소,녹색성장",
        "sections": [
            ("16.1", "국제 토양탄소 격리 이니셔티브: FAO GSOCseq, 4 per 1000, EU EEA·EJP SOIL", "표 16-1: 주요 국제·유럽 토양탄소 정책(FAO·4p1000·EU EEA·EJP SOIL) 비교"),
            ("16.2", "IPCC 인벤토리(Tier 1~3), 등가토양질량(ESM) 산정 및 일본 J-Credit 사례", "표 16-2: 토양탄소 산정 Tier 1·2·3 방법론 및 MRV 핵심 요건"),
            ("16.3", "국내 저탄소 농산물 인증과 농업 탄소크레딧 MRV의 영속성·추가성 쟁점", "표 16-3: 농업 토양탄소 크레딧 도입 시 핵심 리스크(영속성·포화·측정비용)와 대응"),
        ],
    },
}


def generate_missing_blueprints_and_sync(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    master = yaml.safe_load((cfg.blueprints_dir / "master_outline.yaml").read_text(encoding="utf-8"))
    ch_meta: dict[str, dict[str, Any]] = {}
    for part in master.get("parts", []):
        for ch in part.get("chapters", []):
            ch_meta[ch["chapter_id"]] = ch

    created_blueprints: list[str] = []
    kg_exports: dict[str, Any] = {}

    for cid, spec in CHAPTER_SPECS.items():
        cm = ch_meta.get(cid, {})
        bp_path = cfg.blueprints_dir / f"{cid}.yaml"

        # 1. C:\SMC_GRAPHRAG 기존 지식에서 해당 단원용 kg_reuse 근거 추출
        kg_res = export_kg_reuse_evidence(
            terms=[t.strip() for t in spec["kg_terms"].split(",") if t.strip()],
            packet_id=f"{cid}_evidence",
            topic=cm.get("title", cid),
            title=f"C:\\SMC_GRAPHRAG 기존 지식그래프 선조회 재활용 근거 ({cid})",
            max_relations_per_term=8,
            cfg=cfg,
        )
        kg_exports[cid] = kg_res

        # 2. 단원 청사진 YAML 생성
        bp_obj = {
            "chapter_id": cid,
            "chapter_number": cm.get("chapter_number", int(cid[2:])),
            "title": cm.get("title", cid),
            "target_pages": cm.get("target_pages", 32),
            "target_audience": master["book_metadata"]["target_audience"],
            "evidence_packet": f"data/evidence/{cid}_evidence.json",
            "learning_objectives": cm.get("learning_objectives", []),
            "sections": [
                {
                    "section_id": sec_id,
                    "title": sec_title,
                    "target_chars": 1800,
                    "key_points": [
                        f"{sec_title}의 핵심 원리와 과학적 메커니즘",
                        f"핵심 개념 연계: {', '.join(cm.get('essential_concepts', []))}",
                        "근거 패킷 내 국내외 실증 사례 및 현장 적용 시 트레이드오프",
                    ],
                    "required_table": req_tbl,
                }
                for sec_id, sec_title, req_tbl in spec["sections"]
            ],
        }
        bp_path.write_text(yaml.safe_dump(bp_obj, allow_unicode=True, sort_keys=False), encoding="utf-8")
        created_blueprints.append(str(bp_path))

    # 3. 대시보드 큐레이션(curation_state.json)의 단원 배정을 12개 단원 패킷에 모두 동기화
    synced = sync_packets(list(CHAPTER_SPECS.keys()), cfg=cfg)
    return {
        "created_blueprints_count": len(created_blueprints),
        "created_blueprints": created_blueprints,
        "synced_packets": {k: v["total_sources_in_packet"] for k, v in synced.items()},
    }


if __name__ == "__main__":
    print(json.dumps(generate_missing_blueprints_and_sync(), ensure_ascii=False, indent=2))
