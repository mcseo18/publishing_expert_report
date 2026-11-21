"""16개 전 단원용 정량 데이터 차트 및 개념 도해(고해상도 벡터 SVG) 자동 생성기.

특징:
- 외부 폰트 깨짐 없이 한글(`Malgun Gothic`)을 완벽 지원하는 출판급 벡터 SVG 생성
- 실제 som_cn_simulator.py 계산 결과(Stanford-Smith 질소 무기화, RothC 5-풀 30년 시뮬레이션)와
  검증된 근거 패킷 수치(POM 23년 vs MAOM 129년, MAOC 899 Pg C / 42% 포화 등)를 직접 시각화
- 출력 위치: content/assets/charts/fig_chNN_*.svg (+ E:\\SMC_Report_Platform_Data\\exports\\figures\\ 미러)
- 매니페스트: content/assets/charts_manifest.json
"""
from __future__ import annotations

import html
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

from config import PlatformConfig, get_config
from som_cn_simulator import simulate_rothc_simple, stanford_smith_mineralization

FONT = "'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"


def _svg_wrap(title: str, subtitle: str, body: str, width: int = 760, height: int = 380) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="background:#ffffff;font-family:{FONT};">
  <rect x="0" y="0" width="{width}" height="{height}" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
  <rect x="0" y="0" width="{width}" height="52" rx="10" fill="#0f172a"/>
  <rect x="0" y="38" width="{width}" height="14" fill="#0f172a"/>
  <text x="20" y="24" font-size="14" font-weight="700" fill="#f8fafc">{html.escape(title)}</text>
  <text x="20" y="43" font-size="10.5" fill="#94a3b8">{html.escape(subtitle)}</text>
  {body}
</svg>"""


def _hbar_chart(
    title: str,
    subtitle: str,
    items: list[tuple[str, float, str, str]],
    unit: str = "",
    max_val: float | None = None,
) -> str:
    mv = max_val or max(v for _, v, _, _ in items) * 1.15
    y0 = 78
    row_h = min(46, int(265 / max(len(items), 1)))
    parts: list[str] = []
    for idx, (label, val, color, note) in enumerate(items):
        y = y0 + idx * row_h
        bar_w = max(8, int((val / mv) * 380))
        parts.append(f'<text x="22" y="{y + 18}" font-size="11.5" font-weight="600" fill="#1e293b">{html.escape(label)}</text>')
        parts.append(f'<rect x="215" y="{y + 4}" width="380" height="22" rx="4" fill="#f1f5f9"/>')
        parts.append(f'<rect x="215" y="{y + 4}" width="{bar_w}" height="22" rx="4" fill="{color}"/>')
        parts.append(f'<text x="{222 + bar_w}" y="{y + 19}" font-size="11" font-weight="700" fill="#0f172a">{val:g}{html.escape(unit)}</text>')
        if note:
            parts.append(f'<text x="22" y="{y + 33}" font-size="9.5" fill="#64748b">{html.escape(note)}</text>')
    return _svg_wrap(title, subtitle, "\n  ".join(parts))


def _flow_diagram(title: str, subtitle: str, nodes: list[tuple[int, int, int, int, str, str, str]], arrows: list[tuple[int, int, int, int, str]]) -> str:
    parts = [
        '<defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M 0 1 L 10 5 L 0 9 z" fill="#334155"/></marker></defs>'
    ]
    for x1, y1, x2, y2, lbl in arrows:
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#334155" stroke-width="1.8" marker-end="url(#arr)"/>')
        if lbl:
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2 - 5
            parts.append(f'<text x="{mx}" y="{my}" text-anchor="middle" font-size="9.5" font-weight="600" fill="#1d4ed8">{html.escape(lbl)}</text>')
    for x, y, w, h, head, sub, bg in nodes:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{bg}" stroke="#1e293b" stroke-width="1.2"/>')
        parts.append(f'<text x="{x + w//2}" y="{y + 22}" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0f172a">{html.escape(head)}</text>')
        if sub:
            for si, sl in enumerate(sub.split("\n")):
                parts.append(f'<text x="{x + w//2}" y="{y + 38 + si*13}" text-anchor="middle" font-size="9.5" fill="#334155">{html.escape(sl)}</text>')
    return _svg_wrap(title, subtitle, "\n  ".join(parts))


def _line_chart(
    title: str,
    subtitle: str,
    xs: list[float],
    series: list[tuple[str, list[float], str]],
    x_label: str,
    y_label: str,
) -> str:
    left, top, plot_w, plot_h = 72, 74, 620, 225
    all_y = [v for _, ys, _ in series for v in ys]
    ymin, ymax = min(0.0, min(all_y)), max(all_y) * 1.12
    xmin, xmax = min(xs), max(xs)
    x_span = max(xmax - xmin, 1e-6)
    y_span = max(ymax - ymin, 1e-6)

    def px(x: float) -> float:
        return left + (x - xmin) / x_span * plot_w

    def py(y: float) -> float:
        return top + plot_h - (y - ymin) / y_span * plot_h

    parts = [
        f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>'
    ]
    # Grid lines
    for i in range(5):
        yv = ymin + y_span * i / 4
        yy = py(yv)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{left + plot_w}" y2="{yy:.1f}" stroke="#e2e8f0" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="9.5" fill="#475569">{yv:.1f}</text>')
    for x in xs:
        xx = px(x)
        parts.append(f'<text x="{xx:.1f}" y="{top + plot_h + 16}" text-anchor="middle" font-size="9.5" fill="#475569">{x:g}</text>')

    parts.append(f'<text x="{left + plot_w/2:.1f}" y="{top + plot_h + 34}" text-anchor="middle" font-size="10.5" font-weight="600" fill="#1e293b">{html.escape(x_label)}</text>')
    parts.append(f'<text x="18" y="{top + plot_h/2:.1f}" text-anchor="middle" font-size="10.5" font-weight="600" fill="#1e293b" transform="rotate(-90 18 {top + plot_h/2:.1f})">{html.escape(y_label)}</text>')

    # Plot series & legend
    for s_idx, (name, ys, color) in enumerate(series):
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in zip(xs, ys))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.6" points="{pts}"/>')
        for x, y in zip(xs, ys):
            parts.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5" fill="{color}"/>')
        lx = left + s_idx * 205
        ly = 354
        parts.append(f'<rect x="{lx}" y="{ly - 8}" width="14" height="4" fill="{color}"/>')
        parts.append(f'<text x="{lx + 20}" y="{ly - 3}" font-size="10" font-weight="600" fill="#1e293b">{html.escape(name)}</text>')

    return _svg_wrap(title, subtitle, "\n  ".join(parts))


def generate_all_charts(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    chart_dir = cfg.assets_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # 실제 시뮬레이터 계산값 추출 (ch07, ch11)
    weeks = [0, 2, 4, 8, 12, 16, 20, 24]
    ss_low = [r["cumulative_n_kg_ha"] for r in stanford_smith_mineralization(90.0, 0.045, weeks)]
    ss_mid = [r["cumulative_n_kg_ha"] for r in stanford_smith_mineralization(120.0, 0.054, weeks)]
    ss_high = [r["cumulative_n_kg_ha"] for r in stanford_smith_mineralization(160.0, 0.068, weeks)]

    yrs_axis = [0, 5, 10, 15, 20, 25, 30]
    rothc_15 = [45.0] + [simulate_rothc_simple(45.0, 1.5, years=y)["final_soc_t_c_ha"] for y in yrs_axis[1:]]
    rothc_35 = [45.0] + [simulate_rothc_simple(45.0, 3.5, years=y)["final_soc_t_c_ha"] for y in yrs_axis[1:]]
    rothc_50 = [45.0] + [simulate_rothc_simple(45.0, 5.0, years=y)["final_soc_t_c_ha"] for y in yrs_axis[1:]]

    charts_spec: list[dict[str, str]] = [
        {
            "chapter_id": "ch01",
            "filename": "fig_ch01_pom_maom_turnover.svg",
            "caption_ko": "그림 1-2. 입자성 유기물(POM) vs 광물결합 유기물(MAOM) 평균 체류시간 및 전 지구 MAOC 저장 포화도 비교 [SRC-05, SRC-06]",
            "svg": _hbar_chart(
                "POM vs MAOM 평균 체류시간(년) 및 전 지구 MAOC 포화 지표",
                "출처: Nature Communications 2024 [SRC-05] & Georgiou et al. 2022 [SRC-06]",
                [
                    ("POM 평균 체류시간", 23, "#f59e0b", "빠른 순환 · 단기 양분 공급 및 토양 단립 형성"),
                    ("MAOM 평균 체류시간", 129, "#2563eb", "광물 표면 화학 결합 · 장기 탄소 격리 핵심"),
                    ("전 지구 MAOC 포화율", 42, "#10b981", "현재 899 Pg C 저장 (비동결 광질토 1m 기준 미포화 58%)"),
                    ("미포화 토양 축적배수 (×10)", 30, "#8b5cf6", "포화도 1/10 토양은 1/2 토양 대비 약 3배 빠른 탄소 축적"),
                ],
                unit=" (년 / %)",
                max_val=150,
            ),
        },
        {
            "chapter_id": "ch02",
            "filename": "fig_ch02_cn_materials.svg",
            "caption_ko": "그림 2-1. 주요 유기성 자재별 대표 탄질비(C/N비) 범위와 질소 무기화·부동화 경계 개념도 [SRC-01, SRC-02, SRC-19]",
            "svg": _hbar_chart(
                "유기성 자재 유형별 대표 탄질비(C/N) 비교와 부동화 경계(~25~30)",
                "낮은 C/N비(<20): 신속한 질소 무기화 | 높은 C/N비(>30): 초기 질소 부동화 주의 [SRC-01, SRC-19]",
                [
                    ("헤어리베치(두과 녹비)", 12, "#16a34a", "질소 함량 높음 · 신속 분해 및 질소 공급"),
                    ("완숙 가축분퇴비", 18, "#2563eb", "부숙 완료 · 안정적 유기물 및 양분 공급"),
                    ("적정 퇴비화 목표 C/N", 28, "#0ea5e9", "미생물 활성·암모니아 부동화 균형 구간 [SRC-01]"),
                    ("볏짚·맥짚(화본과 잔사)", 65, "#f59e0b", "셀룰로오스·리그닌 높음 · 초기 질소 보정 필요"),
                    ("톱밥·목질 수분조절재", 120, "#dc2626", "고리그닌 난분해성 · 단독 생시용 시 질소 기아 유발"),
                ],
                unit=" :1",
                max_val=140,
            ),
        },
        {
            "chapter_id": "ch03",
            "filename": "fig_ch03_humus_vs_mcp.svg",
            "caption_ko": "그림 3-1. 전통적 부식화(HA·FA·휴민) 경로와 현대 미생물 탄소 펌프(MCP·Necromass) 안정화 경로 비교 [SRC-01, SRC-09, SRC-54, SRC-58]",
            "svg": _flow_diagram(
                "식물 잔사 → 미생물 탄소 펌프(MCP) 및 광물 결합 안정화 경로",
                "MEMS 프레임워크 [SRC-54] · 미생물 사체(Necromass) 기여 [SRC-58] · 광물 보호 [SRC-50]",
                [
                    (24, 95, 130, 62, "식물 잔사·근권삼출", "이분해성·난분해성\n유기 기질 유입", "#fef3c7"),
                    (205, 80, 150, 65, "미생물 동화 (CUE)", "세균·진균 효소 해중합\n세포 생체량 합성", "#dbeafe"),
                    (205, 195, 150, 62, "입자성 유기물(POM)", "물리적 파쇄·단립 포획\n(체류시간 ~23년)", "#fde68a"),
                    (415, 80, 145, 65, "미생물 사체(Necromass)", "세포벽 잔재·대사산물\n장기 탄소 전구체", "#e9d5ff"),
                    (600, 80, 138, 65, "광물결합(MAOM)", "점토·Fe/Al 산화물 결합\n(체류시간 ~129년)", "#bbf7d0"),
                    (415, 195, 323, 62, "전통 화학분획(참고): 부식산(HA)·풀빅산(FA)·휴민", "알칼리 추출 기반 지표 (HA/FA, E4/E6, FTIR, 13C-NMR) [SRC-01]", "#f1f5f9"),
                ],
                [
                    (154, 118, 203, 112, "흡수·동화"),
                    (154, 142, 203, 218, "물리 파쇄"),
                    (355, 112, 413, 112, "사멸·전환"),
                    (560, 112, 598, 112, "광물 흡착"),
                ],
            ),
        },
        {
            "chapter_id": "ch04",
            "filename": "fig_ch04_aggregate_tiers.svg",
            "caption_ko": "그림 4-2. 토양 단립 계층 구조(일차입자 → 소단립 → 대단립)와 물리적 유기탄소 보호 메커니즘 [SRC-03, SRC-42, SRC-44]",
            "svg": _flow_diagram(
                "토양 단립 계층 모델 (Aggregate Hierarchy) 및 탄소 보호 기간",
                "출처: 미국토양학회지 SSSAJ [SRC-42, SRC-44] & FAO Soils Bulletin 80 [SRC-03]",
                [
                    (25, 110, 155, 80, "점토·미사 일차입자", "(< 53 μm)\nMAOM 화학 결합\n수십~수백 년 보호", "#dbeafe"),
                    (230, 110, 175, 80, "소단립 (Microaggregate)", "(53 ~ 250 μm)\n다당류·다가양이온 가교\n수십 년 물리적 보호", "#bbf7d0"),
                    (455, 110, 185, 80, "대단립 (Macroaggregate)", "(> 250 μm)\n균근균 균사·잔뿌리 결속\n경운에 민감 · 수년 보호", "#fef3c7"),
                    (230, 240, 410, 62, "강한 경운(Tillage) → 대단립 파괴 → 보호된 POM 노출 · CO2 손실 가속", "무경운·피복작물·퇴비 시용으로 단립 계층 회복 [SRC-19, SRC-23]", "#fee2e2"),
                ],
                [
                    (180, 150, 228, 150, "결속"),
                    (405, 150, 453, 150, "균사·뿌리"),
                    (545, 190, 545, 238, "경운 교란"),
                ],
            ),
        },
        {
            "chapter_id": "ch05",
            "filename": "fig_ch05_cec_comparison.svg",
            "caption_ko": "그림 5-1. 주요 토양 점토광물 대비 토양 유기물(부식질)의 대표 양이온치환용량(CEC) 범위 비교 [SRC-01, SRC-25, SRC-30]",
            "svg": _hbar_chart(
                "점토광물 vs 토양 유기물(부식질)의 대표 양이온치환용량(CEC, cmolc/kg)",
                "유기물 카르복실·페놀기 해리로 높은 pH 의존 음전하 제공 [SRC-01, SRC-25, SRC-30]",
                [
                    ("카올리나이트 (1:1 점토)", 10, "#94a3b8", "낮은 영구전하 · 양분 보유력 취약"),
                    ("일라이트 (2:1 비팽창)", 30, "#64748b", "중간 수준 CEC"),
                    ("스멕타이트 (2:1 팽창)", 100, "#3b82f6", "광물 중 높은 CEC 보유"),
                    ("토양 부식질 / 유기물", 250, "#15803d", "점토 대비 2.5~25배 높은 양분 보유·완충능 [SRC-01, SRC-30]"),
                ],
                unit=" cmolc/kg",
                max_val=300,
            ),
        },
        {
            "chapter_id": "ch06",
            "filename": "fig_ch06_rhizosphere_priming.svg",
            "caption_ko": "그림 6-1. 근권 삼출물·토양 생물군(세균·균근균·지렁이)과 양성/음성 프라이밍 효과 메커니즘 [SRC-16, SRC-49, SRC-53]",
            "svg": _flow_diagram(
                "근권(Rhizosphere) 미생물 먹이망과 프라이밍 효과(Priming Effect)",
                "출처: 한국토양비료학회지 AMF/PGPR [SRC-16] · EJSS 지렁이 리뷰 [SRC-49] · Frontiers [SRC-53]",
                [
                    (25, 115, 140, 70, "작물 뿌리·근권삼출", "당류·유기산 분비\n에너지 기질 공급", "#dcfce7"),
                    (215, 78, 165, 65, "양성 프라이밍 (+)", "양분 결핍 시 미생물 활성\n기존 SOM 분해 촉진", "#fee2e2"),
                    (215, 180, 165, 65, "음성 프라이밍 (-)", "충분한 가용 양분 조건\n기존 SOM 분해 억제·보존", "#dbeafe"),
                    (435, 78, 290, 65, "균근균(AMF)·PGPR 공생 네트워크", "인산·미량원소 흡수 증진 및 스트레스 완화 [SRC-16]", "#f3e8ff"),
                    (435, 180, 290, 65, "지렁이·토양대형동물 생태계 공학", "잔사 혼입·분변토 단립 형성·공극률 개선 [SRC-49]", "#fef3c7"),
                ],
                [
                    (165, 138, 213, 112, "N 제한"),
                    (165, 162, 213, 212, "N 충분"),
                    (380, 110, 433, 110, "상호작용"),
                    (380, 210, 433, 210, "물리 혼합"),
                ],
            ),
        },
        {
            "chapter_id": "ch07",
            "filename": "fig_ch07_stanford_smith_n.svg",
            "caption_ko": "그림 7-1. Stanford-Smith 1차 질소 무기화 모델(Nt = N0(1 - e^-kt)) 시뮬레이션 곡선 (som_cn_simulator.py 실측 계산) [SRC-59, SRC-60]",
            "svg": _line_chart(
                "Stanford-Smith 1차 질소 무기화 누적 곡선 (N0 및 속도상수 k 비교)",
                "실제 Python 시뮬레이터(scripts/som_cn_simulator.py) 산출 · 온도 상승 시 k 증가 [SRC-59, SRC-60]",
                weeks,
                [
                    ("저투입 (N0=90, k=0.045)", ss_low, "#64748b"),
                    ("표준 (N0=120, k=0.054)", ss_mid, "#2563eb"),
                    ("녹비+퇴비 (N0=160, k=0.068)", ss_high, "#16a34a"),
                ],
                "배양·경과 기간 (주, Weeks)",
                "누적 무기화 질소 (kg N/ha)",
            ),
        },
        {
            "chapter_id": "ch08",
            "filename": "fig_ch08_soc_analysis_methods.svg",
            "caption_ko": "그림 8-1. 토양 유기탄소(SOC) 4대 표준 분석법(건식연소·Tyurin·Walkley-Black·LOI) 및 현장 색도계 비교 [SRC-13, SRC-27]",
            "svg": _hbar_chart(
                "토양 유기탄소(SOC) 주요 분석법의 상대 정밀도·회수율 지표 (개념 비교)",
                "국립농업과학원 토양분석법(Tyurin) [SRC-27] · SPAD 503 현장추정 [SRC-13]",
                [
                    ("원소분석기 건식연소(Dumas)", 99, "#1d4ed8", "국제 기준법 · 무기탄소(탄산염) 전처리 필요"),
                    ("Tyurin 습식산화법(국내 표준)", 92, "#0284c7", "국내 토양검정실 표준 [SRC-27] · 크롬 폐액 관리"),
                    ("Walkley-Black 습식산화법", 77, "#f59e0b", "미가열 시 평균 회수율 ~77% · 보정계수 필수"),
                    ("강열감량법 (LOI, 360~550°C)", 84, "#10b981", "무시약 간편 · 고점토 토양 구조수 손실 오차 주의"),
                    ("토색판·SPAD 503 현장 추정", 72, "#8b5cf6", "신속 현장 스크리닝 [SRC-13] · 지역별 검량식 필요"),
                ],
                unit="%",
                max_val=115,
            ),
        },
        {
            "chapter_id": "ch09",
            "filename": "fig_ch09_soil_health_frameworks.svg",
            "caption_ko": "그림 9-1. 한국 흙토람 · 미국 Cornell CASH · 유럽 EEA 토양건강 평가 프레임워크 비교 구조 [SRC-01, SRC-40, SRC-41, SRC-46]",
            "svg": _flow_diagram(
                "국내외 토양건강 종합평가 체계(흙토람 · Cornell CASH · EU EEA)",
                "물리·화학·생물 통합 지표와 유기물 분획(POM·MAOM·POXC) 연계",
                [
                    (24, 85, 218, 175, "한국 흙토람 (농촌진흥청)", "필지별 토양검정·비료처방\n· pH, EC, OM(Tyurin)\n· 유효인산·치환성양이온\n· 논/밭/과수/시설 적정기준\n[SRC-01, SRC-27]", "#dbeafe"),
                    (270, 85, 220, 175, "미국 Cornell CASH", "물리·생물·화학 균형 채점\n· 총유기물(SOM) + 활성탄소(POXC)\n· 습식 단립안정성·유효수분\n· 토양호흡·ACE 단백질\n[SRC-40, SRC-41]", "#dcfce7"),
                    (518, 85, 218, 175, "유럽 EU EEA · EJP SOIL", "광역 LUCAS 모니터링·정책\n· 표토 SOC 농도·추세 감시\n· SOC/점토 비율 건강지표\n· EU Soil Strategy 2030\n[SRC-46, SRC-48]", "#f3e8ff"),
                ],
                [],
            ),
        },
        {
            "chapter_id": "ch10",
            "filename": "fig_ch10_rothc_5pool.svg",
            "caption_ko": "그림 10-1. RothC 5-풀(DPM·RPM·BIO·HUM·IOM) 구획 모델 구조 및 분해속도상수(k) 흐름도 [SRC-45, SRC-61, SRC-62, SRC-64]",
            "svg": _flow_diagram(
                "RothC-26.3 5-풀 토양 유기탄소 구획 모델 구조 (dC/dt = I + A·C)",
                "출처: Rothamsted Research [SRC-45] · 국내 RothC 적용 [SRC-62, SRC-64]",
                [
                    (20, 100, 115, 62, "식물 잔사·퇴비", "월별 탄소 유입\n(DPM/RPM 분할)", "#fef3c7"),
                    (175, 76, 130, 56, "DPM (이분해성)", "k = 10.0 yr⁻¹\n수개월 내 분해", "#fde68a"),
                    (175, 160, 130, 56, "RPM (난분해성)", "k = 0.30 yr⁻¹\n수년 내 분해", "#fed7aa"),
                    (370, 76, 145, 56, "BIO (미생물체)", "k = 0.66 yr⁻¹\n46%/(1+x) 분배", "#dbeafe"),
                    (370, 160, 145, 56, "HUM (부식화풀)", "k = 0.02 yr⁻¹\n54%/(1+x) 분배", "#bbf7d0"),
                    (575, 76, 155, 56, "대기 CO2 방출", "점토함량 함수 x\n호흡 손실", "#fee2e2"),
                    (575, 160, 155, 56, "IOM (비활성풀)", "k = 0 (고정)\nFalloon 식 산정", "#e2e8f0"),
                    (175, 252, 555, 48, "차세대 확장 (MIMICS / MEMS): Michaelis-Menten 미생물 효소 역학 + 광물 포화 반영 [SRC-54, SRC-58]", "", "#f3e8ff"),
                ],
                [
                    (135, 120, 173, 104, ""),
                    (135, 142, 173, 185, ""),
                    (305, 104, 368, 104, "분해"),
                    (305, 188, 368, 188, "분해"),
                    (515, 104, 573, 104, "CO2"),
                    (515, 178, 573, 118, "CO2"),
                ],
            ),
        },
        {
            "chapter_id": "ch11",
            "filename": "fig_ch11_rothc_30yr_sim.svg",
            "caption_ko": "그림 11-1. 영농 관리 시나리오별 30년 표토(0~30 cm) SOC 변화 시뮬레이션 (초기 45 t C/ha, 점토 22%, som_cn_simulator.py 실측) [SRC-45, SRC-61, SRC-62]",
            "svg": _line_chart(
                "RothC 5-풀 30년 표토 유기탄소(SOC) 시나리오 모의 결과",
                "초기 SOC 45.0 t C/ha · Falloon IOM 3.74 t C/ha · scripts/som_cn_simulator.py 실측 실행",
                yrs_axis,
                [
                    ("저투입 1.5 tC/yr (최종 29.0)", rothc_15, "#dc2626"),
                    ("퇴비+잔사 3.5 tC/yr (최종 37.4)", rothc_35, "#2563eb"),
                    ("녹비+퇴비 5.0 tC/yr (최종 43.7)", rothc_50, "#16a34a"),
                ],
                "시뮬레이션 경과 연수 (Years)",
                "표토 유기탄소 스톡 (t C/ha)",
            ),
        },
        {
            "chapter_id": "ch12",
            "filename": "fig_ch12_paddy_upland_greenhouse.svg",
            "caption_ko": "그림 12-1. 농경지 유형별(담수 논·호기 밭·시설재배지) 토양 유기물 동태 및 한·일 관리 초점 비교 [SRC-01, SRC-18, SRC-33, SRC-62]",
            "svg": _flow_diagram(
                "국내외 농경지 유형별(논 · 밭 · 시설재배지) 유기물 동태와 핵심 관리 과제",
                "출처: 한국 흙토람·농사로 [SRC-01, SRC-18] · 일본 MAFF 시비기준 [SRC-33]",
                [
                    (24, 92, 218, 165, "담수 논토양 (Paddy)", "혐기 조건 → 분해 지연\n· 유기탄소 축적 유리\n· 주의: 생짚 과다 시 메탄(CH4)\n  배출 증가 상충 관리\n[SRC-01, SRC-38, SRC-62]", "#dbeafe"),
                    (270, 92, 220, 165, "노지 밭토양 (Upland)", "호기·경운 → 산화 분해 빠름\n· 유기물 소모 빨라 보충 필수\n· 퇴비·녹비(헤어리베치)·\n  피복작물로 단립·보수력 회복\n[SRC-01, SRC-19, SRC-33]", "#fef3c7"),
                    (518, 92, 218, 165, "시설재배지 (Greenhouse)", "고온·무강우 → 염류(EC) 집적\n· 가축분퇴비 과다 시용 주의\n· 토양검정 기반 적정 시용 &\n  수분감지기 연계 물관리\n[SRC-01, SRC-18, SRC-87]", "#fee2e2"),
                ],
                [],
            ),
        },
        {
            "chapter_id": "ch13",
            "filename": "fig_ch13_conservation_practices.svg",
            "caption_ko": "그림 13-1. 퇴비·녹비작물·깊이거름주기·보전경운 통합 유기물 관리 프레임워크 [SRC-17, SRC-19, SRC-23, SRC-26]",
            "svg": _flow_diagram(
                "농경지 유기물 증진 4대 현장 실천 기술과 시너지 경로",
                "출처: 농사로 깊이거름주기 실증 [SRC-17] · USDA SARE 4판 [SRC-19, SRC-23] · 농업기술길잡이 [SRC-26]",
                [
                    (24, 85, 165, 70, "1. 완숙 퇴비 시용", "부숙도·C/N 25~30 준수\n부식산·CEC 증진", "#dcfce7"),
                    (205, 85, 165, 70, "2. 녹비·피복작물", "헤어리베치·호밀 환원\n근권 탄소·질소 공급", "#dbeafe"),
                    (386, 85, 165, 70, "3. 깊이거름주기", "농사로 탄소중립 실증\n양분 손실·가스 저감", "#fef3c7"),
                    (567, 85, 168, 70, "4. 무경운·최소경운", "대단립 파괴 억제\n표층 POM·침식 방어", "#f3e8ff"),
                    (110, 215, 540, 62, "통합 목표: 단기 양분순환(POM) + 장기 탄소격리(MAOM) + 가뭄저항성·수확량 안정화", "단독 기술보다 2~3종 복합 적용 시 토양건강·탄소축적 시너지 극대화 [SRC-19, SRC-23]", "#e0f2fe"),
                ],
                [
                    (106, 155, 220, 213, ""),
                    (287, 155, 320, 213, ""),
                    (468, 155, 440, 213, ""),
                    (651, 155, 540, 213, ""),
                ],
            ),
        },
        {
            "chapter_id": "ch14",
            "filename": "fig_ch14_biochar_pyrolysis.svg",
            "caption_ko": "그림 14-2. 열분해 온도(350~700°C) 상승에 따른 바이오차 방향족 안정성·비표면적·수율 변화 개념 곡선 [SRC-36, SRC-38, SRC-79]",
            "svg": _line_chart(
                "열분해 온도별 바이오차 안정성 · 비표면적 · 수율 트레이드오프 (정규화 지수)",
                "출처: Biochar Physicochemical Properties Review [SRC-79] · MAFF 바이오차 지침 [SRC-36]",
                [350, 400, 450, 500, 550, 600, 700],
                [
                    ("방향족 탄소 안정성 (지수)", [42, 55, 68, 78, 86, 92, 97], "#1d4ed8"),
                    ("비표면적·공극률 (지수)", [20, 32, 48, 65, 78, 88, 95], "#16a34a"),
                    ("고체 바이오차 수율 (지수)", [52, 45, 39, 34, 30, 27, 22], "#dc2626"),
                ],
                "열분해 온도 (°C)",
                "상대 지수 (0 ~ 100)",
            ),
        },
        {
            "chapter_id": "ch15",
            "filename": "fig_ch15_ecosystem_soc.svg",
            "caption_ko": "그림 15-2. 특수 토양 생태계(이탄지·화산회토·심토·농경지)별 유기탄소 보호 기작 및 취약성 비교 [SRC-06, SRC-51, SRC-80, SRC-81]",
            "svg": _flow_diagram(
                "특수 토양 생태계별 토양 유기탄소 안정화 기작과 기후 취약성",
                "출처: Nature Climate-Smart Soils [SRC-80] · Wetland Loss [SRC-81] · EJSS 심토 광물보호 [SRC-51]",
                [
                    (20, 90, 170, 165, "심토 (Subsoil)", "30~100 cm+\n· 높은 MAOM 미포화 결핍\n· 심근성 뿌리 탄소 핵심\n· 저장 잠재력 우수\n[SRC-06, SRC-51]", "#dbeafe"),
                    (204, 90, 170, 165, "화산회토 (Andosol)", "제주·일본 화산재 기원\n· 비정질 알로페인·Al/Fe\n  유기복합체 초강력 보호\n· 극고농도 유기탄소 축적\n[SRC-38, SRC-51, SRC-82]", "#f3e8ff"),
                    (388, 90, 170, 165, "이탄지·습지 (Peat)", "혐기·과습 환경\n· 전 지구 면적 소수이나\n  막대한 탄소 집중 저장\n· 배수 시 급격한 CO2 방출\n[SRC-81]", "#fee2e2"),
                    (572, 90, 168, 165, "산림·초지 (Forest)", "다년생 식생·무경운\n· 풍부한 표층 낙엽(O층)\n  및 심층 뿌리 네트워크\n· 온난화(Q10) 피드백 주의\n[SRC-07, SRC-43, SRC-80]", "#dcfce7"),
                ],
                [],
            ),
        },
        {
            "chapter_id": "ch16",
            "filename": "fig_ch16_mrv_framework.svg",
            "caption_ko": "그림 16-1. 농업 토양탄소 격리(4 per 1000 · J-Credit · EU · 한국 저탄소) 국제 MRV 검증 파이프라인 [SRC-34, SRC-47, SRC-48, SRC-84, SRC-87]",
            "svg": _flow_diagram(
                "농업 토양유기탄소 격리 및 탄소크레딧 MRV (측정·보고·검증) 파이프라인",
                "출처: Geoderma 4 per mille [SRC-84] · 4p1000 [SRC-47] · EJP SOIL [SRC-48] · MAFF J-Credit [SRC-34]",
                [
                    (24, 102, 150, 72, "1. 영농실천(Baseline)", "퇴비·녹비·바이오차·무경운\n추가성(Additionality) 입증", "#fef3c7"),
                    (206, 102, 155, 72, "2. 측정 (Measure)", "표토/심토 실측(ESM 보정)\n+ Vis-NIR·원격탐사 결합", "#dbeafe"),
                    (393, 102, 155, 72, "3. 모델링·보고(Report)", "RothC·DNDC IPCC Tier 3\n불확실성·누출 정량 보고", "#dcfce7"),
                    (580, 102, 156, 72, "4. 제3자 검증(Verify)", "영속성(Permanence) 감사\n크레딧·저탄소 인증 발행", "#f3e8ff"),
                    (110, 224, 540, 56, "글로벌 정책 연계: UN FAO GSOCseq · 프랑스 4 per 1000 · EU CRCF · 일본 J-Credit · 한국 저탄소 농산물", "", "#f1f5f9"),
                ],
                [
                    (174, 138, 204, 138, ""),
                    (361, 138, 391, 138, ""),
                    (548, 138, 578, 138, ""),
                ],
            ),
        },
    ]

    manifest_items = []
    e_fig_dir = cfg.exports_dir / "figures"
    e_fig_dir.mkdir(parents=True, exist_ok=True)

    for item in charts_spec:
        fp = chart_dir / item["filename"]
        fp.write_text(item["svg"], encoding="utf-8")
        shutil.copy2(fp, e_fig_dir / item["filename"])
        manifest_items.append(
            {
                "chapter_id": item["chapter_id"],
                "filename": item["filename"],
                "file_path": str(fp),
                "caption_ko": item["caption_ko"],
                "type": "svg_chart",
            }
        )

    mpath = cfg.assets_dir / "charts_manifest.json"
    mpath.write_text(json.dumps({"charts": manifest_items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"generated_charts": len(manifest_items), "manifest_path": str(mpath), "e_drive_mirror": str(e_fig_dir)}


if __name__ == "__main__":
    print(json.dumps(generate_all_charts(), ensure_ascii=False, indent=2))
