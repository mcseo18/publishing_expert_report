"""교재 시각화 자산(16개 SVG 정량 차트 + 4개 나노바나나 과학 일러스트) 통합 레지스트리 및 삽입 유틸리티.

기능:
1. content/assets/nano_banana_manifest.json 및 content/assets/charts_manifest.json 로드
2. 16개 SVG 차트를 Playwright로 고해상도 PNG로 래스터화(content/assets/charts_png/ 및 E:\\SMC_Report_Platform_Data\\exports\\figures\\charts_png\\)
   → Master Book DOCX 및 보고서 DOCX에서도 20종 도해 전체를 선명하게 삽입 가능
3. PDF/HTML 출판 시 깨진 이미지(broken image) 0건을 보장하기 위해:
   - SVG는 인라인 <svg> 벡터로 직접 삽입
   - PNG(나노바나나 과학 도해)는 경량 고화질 JPEG Data URI(또는 절대 경로)로 삽입하여
     단독 파일(file://), 대시보드(/chapters/chNN), Chrome PDF 임시 경로 어디서나 100% 렌더링
"""
from __future__ import annotations

import base64
import html
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from config import PlatformConfig, get_config


# 전 20종 시각화 자료별 줄글(텍스트) 상세 해설 카탈로그 (별도 표 없이 본문 텍스트로 자연스럽게 기술)
FIGURE_NARRATIVE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "fig_ch01_som_pom_maom": {
        "fig_no": "그림 1-1",
        "title": "입자성 유기물(POM, 좌)과 점토·미사 표면 광물결합 유기물(MAOM, 우)의 미시적 결합 구조 개념도",
        "desc": (
            "좌측 도해는 토양 공극 사이에서 부분 분해된 갈색 식물 잔사와 흰색 균근균 균사가 얽혀 존재하는 입자성 유기물(POM)의 모습을 보여준다. "
            "POM은 미생물 접근성이 높아 비교적 빠르게 분해·회전하며 작물 생육에 필요한 양분을 공급하는 활성 탄소 풀 역할을 한다. "
            "반면 우측 도해는 층상 점토·미사 광물 판상 표면에 미생물 대사산물과 유기 분자 피막이 강하게 흡착·결합된 광물결합 유기물(MAOM)의 미시 구조를 나타내며, "
            "이러한 유기-광물 보호 기작 덕분에 수십 년에서 수백 년 이상 토양에 안정적으로 탄소가 저장된다 [SRC-04, SRC-05, SRC-06, SRC-10]."
        ),
    },
    "fig_ch01_pom_maom_turnover": {
        "fig_no": "그림 1-2",
        "title": "입자성 유기물(POM) 대비 광물결합 유기물(MAOM)의 평균 체류시간 및 전 지구 MAOC 저장 포화도 비교",
        "desc": (
            "전 지구 토양 유기탄소 분획을 비교한 정량 차트로, POM은 평균 체류시간이 수년~수십 년 수준으로 짧은 반면 MAOM은 수십~수백 년 이상 훨씬 긴 안정성을 보임을 나타낸다. "
            "아울러 전 지구 농경지 광물 표면의 유기탄소(MAOC) 저장 용량은 무한하지 않으며 지역·토성에 따라 광물 포화 한계가 존재하므로, "
            "단기 양분 순환(POM)과 장기 탄소 격리(MAOM)를 함께 고려한 균형 관리가 필요함을 시사한다 [SRC-05, SRC-06]."
        ),
    },
    "fig_ch02_cn_materials": {
        "fig_no": "그림 2-1",
        "title": "주요 유기성 자재별 대표 탄질비(C/N비) 범위와 질소 무기화·부동화 경계 개념도",
        "desc": (
            "두과 녹비(헤어리베치), 완숙 가축분퇴비, 볏짚, 목질계 톱밥 등 주요 유기성 자재의 대표 탄질비(C/N비) 분포를 가로 막대로 비교한 그림이다. "
            "일반적으로 C/N비 약 20~25를 임계 경계로 삼아, 이보다 낮은 자재는 분해 시 순 질소 무기화가 우세하여 작물에 질소를 공급하는 반면, "
            "볏짚·톱밥처럼 C/N비가 높은 자재는 초기 분해 과정에서 토양 무기태 질소를 미생물이 흡수하는 질소 부동화가 일어나므로 사전 부숙이나 질소 보정이 필요하다 [SRC-01, SRC-02, SRC-19]."
        ),
    },
    "fig_ch03_humus_vs_mcp": {
        "fig_no": "그림 3-1",
        "title": "전통적 부식화(HA·FA·휴민) 경로와 현대 미생물 탄소 펌프(MCP·Necromass) 안정화 경로 비교",
        "desc": (
            "식물 잔사가 부식산(HA)·풀빅산(FA)·휴민으로 중합된다고 보았던 전통적 부식화 모델(상단)과, "
            "식물 유래 이분해성 탄소가 미생물 대사를 거쳐 균체 및 미생물 사체(Necromass)로 전환된 뒤 광물 표면에 안정화되는 현대 미생물 탄소 펌프(MCP) 경로(하단)를 대비해 보여준다. "
            "장기 토양 탄소 축적은 단순 난분해성 잔사 축적보다 미생물 탄소 이용 효율(CUE)과 광물-유기물 복합체 형성에 크게 의존함을 직관적으로 이해할 수 있다 [SRC-01, SRC-09, SRC-54, SRC-58]."
        ),
    },
    "fig_ch04_aggregate_hierarchy": {
        "fig_no": "그림 4-1",
        "title": "토양 대단립(>250 μm) 및 소단립(53~250 μm) 계층 구조 내 균근균 균사·뿌리털·부식질 결합 단면도",
        "desc": (
            "건강한 토양 대단립(>250 μm)의 내부 단면을 확대한 과학 도해로, 모래·미사·점토 입자가 유기물과 뭉쳐 형성된 여러 개의 소단립(53~250 μm)이 "
            "황백색 균근균 균사, 미세한 작물 뿌리털, 그리고 암갈색 부식질 가교로 단단히 묶여 있는 계층 구조를 보여준다. "
            "단립 사이에는 공기가 통하는 대공극과 수분이 머무는 소공극이 공존하여, 토양 유기물이 배수성·통기성과 유효수분보유능(AWC)을 동시에 개선하는 원리를 설명한다 [SRC-03, SRC-42, SRC-44]."
        ),
    },
    "fig_ch04_aggregate_tiers": {
        "fig_no": "그림 4-2",
        "title": "토양 단립 계층 구조(일차입자 → 소단립 → 대단립)와 물리적 유기탄소 보호 메커니즘",
        "desc": (
            "일차 광물입자(<53 μm)에서 소단립(53~250 μm), 대단립(>250 μm)으로 이어지는 단계별 결합제(광물-부식 복합체, 다당류, 균사·뿌리)와 탄소 보호 특성을 도식화하였다. "
            "대단립은 경운 교란에 민감하게 파괴되지만 소단립 형성의 보호 공간 역할을 하며, 일단 소단립 내부에 포획된 유기탄소는 물리적 차폐를 통해 장기적으로 보호된다 [SRC-03, SRC-42, SRC-44]."
        ),
    },
    "fig_ch05_cec_comparison": {
        "fig_no": "그림 5-1",
        "title": "주요 토양 점토광물 대비 토양 유기물(부식질)의 대표 양이온치환용량(CEC) 범위 비교",
        "desc": (
            "카올리나이트, 일라이트, 스멕타이트(몬모릴로나이트) 등 대표적 점토광물과 순수 토양 유기물(부식질)의 단위 질량당 양이온치환용량(CEC, cmol(+)/kg) 범위를 비교한 차트이다. "
            "부식질은 일반 점토광물보다 수 배에서 수십 배 높은 CEC를 지니며, 특히 사질토나 저활성 점토 토양에서 유기물 함량을 1~2%만 높여도 양분 보유력과 완충능이 크게 향상됨을 보여준다 [SRC-01, SRC-25, SRC-30]."
        ),
    },
    "fig_ch06_rhizosphere_priming": {
        "fig_no": "그림 6-1",
        "title": "근권 삼출물·토양 생물군(세균·균근균·지렁이)과 양성/음성 프라이밍 효과 메커니즘",
        "desc": (
            "작물 뿌리에서 분비되는 근권 삼출물이 세균·균근균(AMF)·지렁이 먹이망을 활성화할 때 나타나는 두 가지 프라이밍 경로를 비교한 모식도이다. "
            "양분이 부족한 조건에서 미생물이 효소를 분비해 기존 토양 유기물을 추가 분해하는 양성 프라이밍과, 신선 기질을 우선 이용하며 기존 유기물 분해를 억제하는 음성 프라이밍의 분기 조건을 정리한다 [SRC-16, SRC-49, SRC-53]."
        ),
    },
    "fig_ch07_stanford_smith_n": {
        "fig_no": "그림 7-1",
        "title": "Stanford-Smith 1차 질소 무기화 모델(N_t = N₀(1 − e^(−kt))) 시뮬레이션 곡선",
        "desc": (
            "본 플랫폼의 파이썬 시뮬레이터(scripts/som_cn_simulator.py)로 계산한 Stanford-Smith 1차 질소 무기화 누적 곡선이다. "
            "잠재 무기화 질소(N₀)와 온도 조건에 따른 속도 상수(k)가 높아질수록 초기 질소 방출 기울기가 가팔라지며, "
            "작물 생육기 질소 요구 시점과 유기물 무기화 방출 시점을 동기화하기 위한 추비 설계의 정량 기준을 제시한다 [SRC-59, SRC-60]."
        ),
    },
    "fig_ch08_soc_analysis_methods": {
        "fig_no": "그림 8-1",
        "title": "토양 유기탄소(SOC) 4대 표준 분석법(건식연소·Tyurin·Walkley-Black·LOI) 및 현장 색도계 비교",
        "desc": (
            "원소분석기 건식연소법(Dumas), 국내 흙토람 표준 Tyurin 습식산화법, 국제 표준 Walkley-Black법, 강열감량법(LOI), 그리고 현장 토색판·SPAD 503 색도계의 정밀도·신속성·주의사항을 비교한 그림이다. "
            "습식산화법의 불완전 산화 보정과 LOI의 점토 결정수 오차를 고려해 연구·탄소계정 목적에 맞는 표준 분석법을 선택해야 함을 보여준다 [SRC-13, SRC-27, SRC-94]."
        ),
    },
    "fig_ch09_soil_health_frameworks": {
        "fig_no": "그림 9-1",
        "title": "한국 흙토람 · 미국 Cornell CASH · 유럽 EEA 토양건강 평가 프레임워크 비교 구조",
        "desc": (
            "한국 농촌진흥청 흙토람(화학성·작물별 처방 중심), 미국 코넬대 CASH(물리·화학·생물성 통합 점수화, POXC·단립안정성 포함), "
            "유럽 환경청(EEA)·EJP SOIL(토양 기능 및 탄소·생물다양성 정책 지표)의 핵심 평가 지표를 나란히 비교한 구조도이다. "
            "국내 토양검정 체계에 활성탄소와 물리·생물 지표를 보강하는 통합 토양건강 진단 방향을 제시한다 [SRC-01, SRC-40, SRC-41, SRC-46]."
        ),
    },
    "fig_ch10_rothc_5pool": {
        "fig_no": "그림 10-1",
        "title": "RothC 5-풀(DPM·RPM·BIO·HUM·IOM) 구획 모델 구조 및 분해속도상수(k) 흐름도",
        "desc": (
            "가장 널리 활용되는 표준 토양탄소 모델 RothC의 5개 구획 풀 구조와 연간 기본 분해속도상수(k) 및 탄소 전달 흐름을 도식화하였다. "
            "식물 잔사가 이분해성(DPM)과 난분해성(RPM)으로 유입된 뒤 점토 함량에 따라 대기 호흡(CO₂), 미생물 바이오매스(BIO), 부식화 풀(HUM)로 분배되며, "
            "불활성 풀(IOM)은 분해되지 않고 기저 탄소로 유지되는 동태 원리를 한눈에 보여준다 [SRC-45, SRC-61, SRC-62, SRC-64]."
        ),
    },
    "fig_ch11_rothc_30yr_sim": {
        "fig_no": "그림 11-1",
        "title": "영농 관리 시나리오별 30년 표토(0~30 cm) SOC 변화 시뮬레이션",
        "desc": (
            "초기 표토 유기탄소 45 t C/ha, 점토 함량 22% 조건에서 파이썬 시뮬레이터(scripts/som_cn_simulator.py)로 30년간 모의한 영농 관리 시나리오 비교 곡선이다. "
            "관행 잔사 반출 시나리오에서는 토양 유기탄소가 점차 감소하는 반면, 작물 잔사 환원·헤어리베치 녹비·완숙 퇴비 복합 시용 시나리오에서는 표토 SOC가 꾸준히 축적되어 새로운 평형에 접근하는 장기 추세를 정량적으로 확인할 수 있다 [SRC-45, SRC-61, SRC-62]."
        ),
    },
    "fig_ch12_paddy_upland_greenhouse": {
        "fig_no": "그림 12-1",
        "title": "농경지 유형별(담수 논·호기 밭·시설재배지) 토양 유기물 동태 및 한·일 관리 초점 비교",
        "desc": (
            "담수 혐기 환경의 논토양, 호기성 분해가 빠른 밭토양, 강우 세탈이 차단된 시설재배지의 유기물 분해 속도·주요 온실가스·염류 위험을 3열로 비교한 도해이다. "
            "한국 흙토람과 일본 MAFF 도도부현 시비 기준을 바탕으로 논에서는 메탄 억제와 탄소 축적의 조화, 밭에서는 잔사 환원, 시설재배지에서는 염류(EC)·수분 연계 제어가 핵심임을 정리한다 [SRC-01, SRC-18, SRC-33, SRC-62]."
        ),
    },
    "fig_ch13_conservation_practices": {
        "fig_no": "그림 13-1",
        "title": "퇴비·녹비작물·깊이거름주기·보전경운 통합 유기물 관리 프레임워크",
        "desc": (
            "완숙 퇴비 시용(화학성·부식질 보강), 두과·화본과 녹비작물(질소 고정·뿌리 탄소 공급), 농촌진흥청 깊이거름주기(심층 양분 효율 및 온실가스 저감), "
            "무경운·피복작물 기반 보전농업(단립 보호)을 하나의 순환 관리 체계로 통합한 프레임워크이다. "
            "개별 농법을 단독 적용할 때보다 상호 보완적으로 결합할 때 토양 건강과 탄소중립 효과가 극대화됨을 보여준다 [SRC-17, SRC-19, SRC-23, SRC-26]."
        ),
    },
    "fig_ch14_biochar_rhizosphere": {
        "fig_no": "그림 14-1",
        "title": "다공성 바이오차(Biochar) 미세공극 내 수분·양분 흡착 및 근권 미생물·작물 뿌리 상호작용 단면 도해",
        "desc": (
            "어두운 농경지 토양 속에 매립된 벌집 모양의 다공성 바이오차 입자 단면을 고해상도로 시각화한 과학 일러스트이다. "
            "바이오차 내부의 풍부한 미세공극이 수분과 무기 양분 이온을 붙잡아 두는 동시에 근권 세균과 균근균 균사의 안전한 서식처를 제공하며, "
            "인접한 작물 뿌리털이 안정적으로 수분·양분을 흡수하는 토양 개량·탄소 격리 복합 기작을 보여준다 [SRC-36, SRC-38, SRC-79]."
        ),
    },
    "fig_ch14_biochar_pyrolysis": {
        "fig_no": "그림 14-2",
        "title": "열분해 온도(350~700 °C) 상승에 따른 바이오차 방향족 안정성·비표면적·수율 변화 개념 곡선",
        "desc": (
            "바이오매스 열분해 온도가 350 °C에서 700 °C로 높아짐에 따라 바이오차의 방향족 탄소 안정성과 비표면적은 증가하는 반면, "
            "질량 수율과 표층 산소 작용기(초기 양분 공급 특성)는 감소하는 트레이드오프 관계를 곡선으로 나타낸다. "
            "토양 탄소 장기 격리용과 산성 토양 개량·양분 보완용 바이오차의 적정 제조 온도 선정 근거를 제공한다 [SRC-36, SRC-38, SRC-79]."
        ),
    },
    "fig_ch15_soil_profiles": {
        "fig_no": "그림 15-1",
        "title": "주요 토양 생태계(농경지 광질토·화산회토 Andosol·이탄지 Histosol·산림토양) 1 m 토양 단면 비교",
        "desc": (
            "좌측부터 일반 농경지 광질토, 검은 부식층이 깊게 발달한 화산회토(Andosol), 지하수위가 높고 미분해 식물 섬유질이 축적된 이탄지 습지토(Histosol), "
            "그리고 표층 낙엽 유기물층(O층)과 깊은 수목 뿌리가 발달한 산림토양의 1 m 수직 단면을 나란히 비교한 도해이다. "
            "생태계와 토양 생성 환경에 따라 유기탄소의 심도별 분포와 보호 기작, 교란 취약성이 극명하게 다름을 한눈에 대조할 수 있다 [SRC-06, SRC-51, SRC-80, SRC-81]."
        ),
    },
    "fig_ch15_ecosystem_soc": {
        "fig_no": "그림 15-2",
        "title": "특수 토양 생태계(이탄지·화산회토·심토·농경지)별 유기탄소 보호 기작 및 취약성 비교",
        "desc": (
            "이탄지·화산회토·심토(30~100 cm+)·일반 농경지 4개 생태계의 핵심 탄소 보호 메커니즘(혐기 침수, 비정질 알로페인 광물 결합, 심토 MAOM 미포화 저장, 영농 관리)과 "
            "기후 온난화·배수·경운 교란 시 탄소 손실 취약성을 비교 정리한 도표이다. "
            "고위험-고가치 저장고인 이탄지 보전과 심토 미포화 광물층 활용의 전략적 중요성을 강조한다 [SRC-06, SRC-51, SRC-80, SRC-81, SRC-93]."
        ),
    },
    "fig_ch16_mrv_framework": {
        "fig_no": "그림 16-1",
        "title": "농업 토양탄소 격리(4 per 1000 · J-Credit · EU · 한국 저탄소) 국제 MRV 검증 파이프라인",
        "desc": (
            "기준선(Baseline) 설정과 영농 실천 도입에서 출발해 등가토양질량(ESM) 기반 시료 채취·분석, RothC/DNDC 모델 시뮬레이션 보간, "
            "제3자 검증 및 영속성·추가성 심사를 거쳐 탄소 크레딧 발급으로 이어지는 5단계 국제 MRV(측정·보고·검증) 파이프라인을 시각화하였다. "
            "FAO 4 per 1000, 일본 J-Credit, EU 토양 정책 및 국내 저탄소 농산물 인증 제도를 연결하는 실무 절차를 보여준다 [SRC-34, SRC-47, SRC-48, SRC-84, SRC-87]."
        ),
    },
}


def load_chapter_visuals(cfg: PlatformConfig | None = None) -> dict[str, list[dict[str, Any]]]:
    """단원 ID(ch01~ch16)별 시각화 자산 목록을 반환한다 (나노바나나 도해 우선 → SVG 차트)."""
    cfg = cfg or get_config()
    assets_dir = cfg.assets_dir
    by_ch: dict[str, list[dict[str, Any]]] = {}

    nb_manifest = assets_dir / "nano_banana_manifest.json"
    if nb_manifest.is_file():
        data = json.loads(nb_manifest.read_text(encoding="utf-8"))
        for item in data.get("figures", []):
            fp = Path(item.get("file_path", ""))
            if not fp.is_file():
                fp = assets_dir / "figures" / item.get("filename", "")
            if fp.is_file():
                cid = item["chapter_id"]
                fid = item.get("figure_id", fp.stem)
                narr = FIGURE_NARRATIVE_DESCRIPTIONS.get(fid, {})
                by_ch.setdefault(cid, []).append(
                    {
                        "kind": "nano_banana",
                        "figure_id": fid,
                        "chapter_id": cid,
                        "filename": fp.name,
                        "file_path": str(fp),
                        "docx_image_path": str(fp),
                        "fig_no": narr.get("fig_no", ""),
                        "title_ko": narr.get("title", item.get("caption_ko", "")),
                        "description_ko": narr.get("desc", ""),
                        "caption_ko": item.get("caption_ko", ""),
                    }
                )

    ch_manifest = assets_dir / "charts_manifest.json"
    if ch_manifest.is_file():
        data = json.loads(ch_manifest.read_text(encoding="utf-8"))
        png_dir = assets_dir / "charts_png"
        for item in data.get("charts", []):
            fp = Path(item.get("file_path", ""))
            if not fp.is_file():
                fp = assets_dir / "charts" / item.get("filename", "")
            if fp.is_file():
                cid = item["chapter_id"]
                fid = fp.stem
                png_fp = png_dir / f"{fp.stem}.png"
                narr = FIGURE_NARRATIVE_DESCRIPTIONS.get(fid, {})
                by_ch.setdefault(cid, []).append(
                    {
                        "kind": "svg_chart",
                        "figure_id": fid,
                        "chapter_id": cid,
                        "filename": fp.name,
                        "file_path": str(fp),
                        "docx_image_path": str(png_fp) if png_fp.is_file() else "",
                        "fig_no": narr.get("fig_no", ""),
                        "title_ko": narr.get("title", item.get("caption_ko", "")),
                        "description_ko": narr.get("desc", ""),
                        "caption_ko": item.get("caption_ko", ""),
                    }
                )

    return by_ch


def _encode_image_as_jpeg_data_uri(img_path: Path, max_width: int = 1100, quality: int = 86) -> str:
    """PNG/JPG 과학 일러스트를 선명하고 가벼운 JPEG base64 Data URI로 인코딩한다."""
    img = Image.open(img_path).convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _clean_inline_svg(svg_text: str) -> str:
    """인라인 HTML 삽입을 위해 XML 선언을 제거하고 반응형 width/height 스타일을 보정한다."""
    s = re.sub(r"<\?xml[^>]*\?>", "", svg_text).strip()
    if 'style="' not in s[:250]:
        s = s.replace("<svg ", '<svg style="width:100%;height:auto;display:block;max-width:100%;" ', 1)
    return s


def render_visual_figure_html(
    vis: dict[str, Any],
    *,
    theme: str = "print",
) -> str:
    """단일 시각화 항목을 이미지 + 번호·제목·줄글 해설 텍스트 형태로 렌더링한다 (별도 표 미사용)."""
    fig_no = vis.get("fig_no", "")
    title_ko = vis.get("title_ko") or vis.get("caption_ko", "")
    desc_ko = vis.get("description_ko", "")
    header_line = f"[{fig_no}] {title_ko}" if fig_no else title_ko
    alt_text = html.escape(re.sub(r"\s*\[SRC-[^\]]+\]", "", header_line).strip())

    fp = Path(vis["file_path"])
    if vis["kind"] == "svg_chart":
        body_inner = f'<div class="fig-svg-wrap">{_clean_inline_svg(fp.read_text(encoding="utf-8"))}</div>'
    else:
        data_uri = _encode_image_as_jpeg_data_uri(fp, max_width=1150 if theme == "print" else 1000, quality=88)
        body_inner = f'<img class="fig-img" src="{data_uri}" alt="{alt_text}" />'

    desc_html = f'<p class="fig-desc">{html.escape(desc_ko)}</p>' if desc_ko else ""
    return (
        f'<figure class="book-figure book-figure-{theme}" data-fig-id="{html.escape(vis["figure_id"])}">'
        f"{body_inner}"
        f'<figcaption class="fig-text-block">'
        f'<p class="fig-title"><strong>{html.escape(header_line)}</strong></p>'
        f"{desc_html}"
        f"</figcaption>"
        f"</figure>"
    )


def inject_figures_into_chapter_html(
    ch_id: str,
    rendered_html: str,
    visuals_map: dict[str, list[dict[str, Any]]],
    *,
    theme: str = "print",
) -> str:
    """렌더링된 단원 HTML의 적절한 절 위치(1번째·2번째 H2 직후 문단 뒤)에 도해·차트를 자동 삽입한다."""
    items = visuals_map.get(ch_id, [])
    if not items:
        return rendered_html

    fig_htmls = [render_visual_figure_html(v, theme=theme) for v in items]

    # H2 위치 탐색 (<h2 ...>...</h2>)
    h2_matches = list(re.finditer(r"<h2\b[^>]*>.*?</h2>", rendered_html, flags=re.S))
    if not h2_matches:
        return rendered_html + "\n" + "\n".join(fig_htmls)

    # 삽입 위치 계산 (뒤쪽 인덱스부터 삽입해야 문자열 오프셋이 밀리지 않음)
    insertions: list[tuple[int, str]] = []
    for idx, fhtml in enumerate(fig_htmls):
        # 첫 번째 그림은 첫 번째 본문 H2 직후 첫 문단 뒤, 두 번째 그림은 두 번째 H2 직후 첫 문단 뒤
        target_h2_idx = min(idx, len(h2_matches) - 1)
        after_h2 = h2_matches[target_h2_idx].end()
        next_p = re.search(r"</p>", rendered_html[after_h2:])
        pos = after_h2 + next_p.end() if next_p else after_h2
        insertions.append((pos, f"\n{fhtml}\n"))

    out = rendered_html
    for pos, chunk in sorted(insertions, key=lambda x: x[0], reverse=True):
        out = out[:pos] + chunk + out[pos:]
    return out


def figure_css(theme: str = "print") -> str:
    if theme == "web":
        return """
        .book-figure {
          margin: 20px 0;
          padding: 14px 16px;
          background: #ffffff;
          color: #0f172a;
          border: 1px solid rgba(148,163,184,0.35);
          border-radius: 12px;
          box-shadow: 0 6px 20px rgba(0,0,0,0.22);
        }
        .book-figure .fig-head { margin-bottom: 8px; display: flex; justify-content: flex-end; }
        .book-figure .fig-badge {
          font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
        }
        .book-figure .fig-badge-ai { background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; }
        .book-figure .fig-badge-svg { background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; }
        .book-figure .fig-img { width: 100%; height: auto; display: block; border-radius: 8px; }
        .book-figure .fig-svg-wrap { width: 100%; overflow: hidden; border-radius: 8px; }
        .book-figure .fig-svg-wrap svg { width: 100% !important; height: auto !important; display: block; max-width: 100%; }
        .book-figure figcaption {
          margin-top: 10px; font-size: 12.5px; line-height: 1.55; color: #334155;
          border-top: 1px solid #e2e8f0; padding-top: 8px; font-weight: 600;
        }
        """
    return """
    .book-figure {
      margin: 12px 0 16px;
      padding: 8px 10px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      page-break-inside: avoid;
      break-inside: avoid;
    }
    .book-figure .fig-head { margin-bottom: 4px; text-align: right; }
    .book-figure .fig-badge {
      font-size: 7.2pt; font-weight: 700; padding: 1px 6px; border-radius: 999px; display: inline-block;
    }
    .book-figure .fig-badge-ai { background: #f3e8ff; color: #6b21a8; border: 1px solid #d8b4fe; }
    .book-figure .fig-badge-svg { background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
    .book-figure .fig-img { width: 100%; height: auto; display: block; border-radius: 4px; max-height: 115mm; object-fit: contain; }
    .book-figure .fig-svg-wrap { width: 100%; }
    .book-figure .fig-svg-wrap svg { width: 100% !important; height: auto !important; display: block; }
    .book-figure figcaption {
      margin-top: 6px; font-size: 8.3pt; line-height: 1.55; color: #334155;
      border-top: 1px solid #e2e8f0; padding-top: 6px; text-align: justify;
    }
    .book-figure .fig-title { margin: 0 0 3px; font-size: 8.6pt; color: #0f172a; }
    .book-figure .fig-desc { margin: 0; font-size: 8.2pt; color: #334155; font-weight: 400; }
    """


def rasterize_svgs_to_png(cfg: PlatformConfig | None = None) -> list[str]:
    """16개 SVG 차트를 Playwright 헤드리스 크롬으로 고해상도 PNG로 변환하여 DOCX 삽입에 사용한다."""
    from playwright.sync_api import sync_playwright

    cfg = cfg or get_config()
    charts_dir = cfg.assets_dir / "charts"
    out_dir = cfg.assets_dir / "charts_png"
    out_dir.mkdir(parents=True, exist_ok=True)
    e_out = cfg.exports_dir / "figures" / "charts_png"
    e_out.mkdir(parents=True, exist_ok=True)

    svgs = sorted(charts_dir.glob("*.svg"))
    created: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 960, "height": 540}, device_scale_factor=2)
        for svg_p in svgs:
            svg_markup = svg_p.read_text(encoding="utf-8")
            page.set_content(
                f'<!DOCTYPE html><html><body style="margin:0;background:#ffffff;display:inline-block;">{svg_markup}</body></html>'
            )
            loc = page.locator("svg").first
            png_p = out_dir / f"{svg_p.stem}.png"
            loc.screenshot(path=str(png_p))
            shutil.copy2(png_p, e_out / png_p.name)
            created.append(str(png_p))
        browser.close()
    return created


if __name__ == "__main__":
    outs = rasterize_svgs_to_png()
    print(json.dumps({"rasterized_pngs": len(outs), "sample": outs[:4]}, ensure_ascii=False, indent=2))
