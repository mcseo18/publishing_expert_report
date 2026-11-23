"""학술 출판급 matplotlib 정량 그래프 공통 스타일 및 실데이터(기상 DB·문헌·수리계산) 차트 엔진 (V2, V3, V8).

핵심 원칙:
1. 실제 데이터(CSV/기상 DB/검증 문헌 표/검증 물리식 계산)가 없으면 절대 차트를 그리지 않는다.
2. 색맹 안전 팔레트(Okabe-Ito 학술 표준), 300 DPI, 맑은 고딕(Malgun Gothic), 논문(paper) 모드 흑백 인쇄 대응(선종·마커 구분).
3. 모든 차트는 축 제목(단위 포함), 간결한 그림 제목(장 제목 반복 금지), 오차막대·표본수(n), 하단 출처('자료: ...')를 필수로 표기한다.
4. 생성된 모든 차트 옆에 원천 데이터 CSV를 함께 저장해 완전한 재현성을 보장한다.
"""
from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path
from typing import Any

# Okabe-Ito 색맹 안전(Colorblind-safe) 학술 팔레트
ACADEMIC_PALETTE = {
    "blue": "#0072B2",
    "vermilion": "#D55E00",
    "bluish_green": "#009E73",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "reddish_purple": "#CC79A7",
    "navy": "#1D3557",
    "slate": "#475569",
    "grid": "#E2E8F0",
    "fill_opt": "#D1FAE5",
}

ACADEMIC_COLOR_CYCLE = [
    ACADEMIC_PALETTE["blue"],
    ACADEMIC_PALETTE["vermilion"],
    ACADEMIC_PALETTE["bluish_green"],
    ACADEMIC_PALETTE["orange"],
    ACADEMIC_PALETTE["reddish_purple"],
    ACADEMIC_PALETTE["sky_blue"],
]

ACADEMIC_LINESTYLES = ["-", "--", "-.", ":", (0, (5, 2, 1, 2))]
ACADEMIC_MARKERS = ["o", "s", "^", "D", "v", "P"]

# 논문 흑백 인쇄 대응 팔레트 (명도 차등 + 선종/마커 병용)
PAPER_GRAYSCALE_CYCLE = ["#111827", "#4B5563", "#6B7280", "#9CA3AF"]


def apply_academic_matplotlib_style(*, paper_mode: bool = False) -> Any:
    """matplotlib 전역 학술 스타일(300 DPI, 맑은 고딕, 색맹 안전 팔레트, 깔끔한 축)을 적용하고 plt를 반환한다."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # Windows 한글 폰트 우선 탐색
    font_candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"]
    avail = {f.name for f in font_manager.fontManager.ttflist}
    chosen_font = next((f for f in font_candidates if f in avail), "DejaVu Sans")

    plt.rcParams.update(
        {
            "font.family": chosen_font,
            "axes.unicode_minus": False,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "axes.edgecolor": "#334155",
            "axes.linewidth": 0.9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": ACADEMIC_PALETTE["grid"],
            "grid.linestyle": "--",
            "grid.linewidth": 0.6,
            "grid.alpha": 0.85,
            "axes.titlesize": 11.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 10.0,
            "axes.labelweight": "bold",
            "xtick.labelsize": 9.0,
            "ytick.labelsize": 9.0,
            "legend.fontsize": 8.8,
            "legend.frameon": True,
            "legend.facecolor": "#FFFFFF",
            "legend.edgecolor": "#CBD5E1",
            "figure.facecolor": "#FFFFFF",
            "axes.facecolor": "#FFFFFF",
        }
    )
    if paper_mode:
        plt.rcParams["axes.prop_cycle"] = plt.cycler(color=PAPER_GRAYSCALE_CYCLE)
    else:
        plt.rcParams["axes.prop_cycle"] = plt.cycler(color=ACADEMIC_COLOR_CYCLE)
    return plt


def _save_csv(csv_path: Path, headers: list[str], rows: list[list[Any]]) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return csv_path


def render_data_chart_png(
    *,
    out_png: Path,
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
    source_note: str,
    series: list[dict[str, Any]],
    x_values: list[Any],
    y2_label: str = "",
    y2_series: list[dict[str, Any]] | None = None,
    highlight_band: dict[str, Any] | None = None,
    x_log: bool = False,
    paper_mode: bool = False,
    csv_out_path: Path | None = None,
) -> dict[str, Any]:
    """검증된 실데이터로만 300 DPI 학술 matplotlib 차트를 생성한다 (데이터·단위·출처 누락 시 거부)."""
    if not x_values or not series:
        raise ValueError("실제 수치 데이터(x_values, series)가 없어 차트를 생성할 수 없습니다.")
    if not source_note or not source_note.strip():
        raise ValueError("학술 차트는 반드시 자료 출처(source_note)를 명시해야 합니다.")
    if not x_label.strip() or not y_label.strip():
        raise ValueError("학술 차트는 반드시 단위가 포함된 x축·y축 제목을 명시해야 합니다.")

    plt = apply_academic_matplotlib_style(paper_mode=paper_mode)
    fig, ax = plt.subplots(figsize=(8.53, 4.8), dpi=300)

    colors = PAPER_GRAYSCALE_CYCLE if paper_mode else ACADEMIC_COLOR_CYCLE
    n_x = len(x_values)
    is_cat = any(isinstance(v, str) for v in x_values)
    x_pos = list(range(n_x)) if is_cat else [float(v) for v in x_values]

    if highlight_band:
        hb = highlight_band
        if hb.get("axis", "x") == "x":
            ax.axvspan(hb["min"], hb["max"], color=hb.get("color", "#D1FAE5"), alpha=float(hb.get("alpha", 0.45)), zorder=1)
            if hb.get("label"):
                y_top = hb.get("label_y_frac", 0.94)
                x_mid = math.sqrt(hb["min"] * hb["max"]) if (x_log and hb["min"] > 0 and hb["max"] > 0) else (hb["min"] + hb["max"]) / 2.0
                ax.text(
                    x_mid,
                    y_top,
                    hb["label"],
                    transform=ax.get_xaxis_transform(),
                    ha="center",
                    va="top",
                    fontsize=8.3,
                    fontweight="bold",
                    color="#065F46",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#ECFDF5", edgecolor="#10B981", lw=0.8),
                )
        else:
            ax.axhspan(hb["min"], hb["max"], color=hb.get("color", "#D1FAE5"), alpha=float(hb.get("alpha", 0.45)), zorder=1)

    for idx, s in enumerate(series):
        y_vals = [float(v) for v in s["y"]]
        y_err = [float(e) for e in s["yerr"]] if s.get("yerr") else None
        col = s.get("color") or colors[idx % len(colors)]
        ls = s.get("linestyle") or ACADEMIC_LINESTYLES[idx % len(ACADEMIC_LINESTYLES)]
        mk = s.get("marker") or ACADEMIC_MARKERS[idx % len(ACADEMIC_MARKERS)]
        lbl = s.get("label") or f"계열 {idx + 1}"
        s_kind = s.get("kind") or chart_type

        if s_kind == "bar":
            n_bars = sum(1 for ss in series if (ss.get("kind") or chart_type) == "bar")
            bar_idx = sum(1 for ss in series[:idx] if (ss.get("kind") or chart_type) == "bar")
            width = 0.72 / max(1, n_bars)
            offsets = [xp - 0.36 + width * (bar_idx + 0.5) for xp in x_pos]
            ax.bar(
                offsets,
                y_vals,
                width=width * 0.9,
                color=col,
                edgecolor="#1E293B" if paper_mode else "none",
                alpha=0.85,
                yerr=y_err,
                capsize=3 if y_err else 0,
                error_kw={"elinewidth": 0.9, "ecolor": "#334155"},
                label=lbl,
                zorder=3,
            )
        else:
            if y_err:
                ax.errorbar(
                    x_pos,
                    y_vals,
                    yerr=y_err,
                    color=col,
                    linestyle=ls,
                    marker=mk,
                    markersize=5.2,
                    linewidth=2.0,
                    capsize=3,
                    elinewidth=0.9,
                    label=lbl,
                    zorder=4,
                )
            else:
                ax.plot(
                    x_pos,
                    y_vals,
                    color=col,
                    linestyle=ls,
                    marker=mk if len(x_pos) <= 24 else None,
                    markersize=5.0,
                    linewidth=2.1,
                    label=lbl,
                    zorder=4,
                )

    if is_cat:
        ax.set_xticks(x_pos)
        ax.set_xticklabels([str(v) for v in x_values])
    if x_log:
        ax.set_xscale("log")

    ax.set_xlabel(x_label, labelpad=6)
    ax.set_ylabel(y_label, labelpad=6)
    ax.set_title(title, pad=12, loc="left", color="#0F172A")

    handles, labels = ax.get_legend_handles_labels()
    if y2_series:
        ax2 = ax.twinx()
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_color("#475569")
        ax2.grid(False)
        for j, s2 in enumerate(y2_series):
            col2 = s2.get("color") or colors[(len(series) + j) % len(colors)]
            ls2 = s2.get("linestyle") or ACADEMIC_LINESTYLES[(len(series) + j) % len(ACADEMIC_LINESTYLES)]
            mk2 = s2.get("marker") or ACADEMIC_MARKERS[(len(series) + j) % len(ACADEMIC_MARKERS)]
            ax2.plot(
                x_pos,
                [float(v) for v in s2["y"]],
                color=col2,
                linestyle=ls2,
                marker=mk2,
                markersize=5.2,
                linewidth=2.1,
                label=s2.get("label") or f"보조계열 {j + 1}",
                zorder=5,
            )
        ax2.set_ylabel(y2_label, labelpad=6, color="#334155")
        h2, l2 = ax2.get_legend_handles_labels()
        handles += h2
        labels += l2

    if handles:
        leg_loc = "lower left" if chart_type == "line" and y2_series else "upper left"
        ax.legend(handles, labels, loc=leg_loc, frameon=True, framealpha=0.94)

    fig.text(
        0.015,
        0.012,
        f"자료: {source_note.strip()}",
        fontsize=7.3,
        color="#475569",
        ha="left",
        va="bottom",
    )
    plt.tight_layout(rect=[0.0, 0.045, 1.0, 0.98])

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out_png), dpi=300, facecolor="#FFFFFF")
    plt.close(fig)

    # 원천 데이터 CSV 동반 저장
    if csv_out_path is not None:
        headers = [x_label]
        for s in series:
            headers.append(s.get("label", "value"))
            if s.get("yerr"):
                headers.append(f"{s.get('label', 'value')}_SD")
        for s2 in (y2_series or []):
            headers.append(s2.get("label", "value2"))
        csv_rows: list[list[Any]] = []
        for i in range(n_x):
            row: list[Any] = [x_values[i]]
            for s in series:
                row.append(s["y"][i])
                if s.get("yerr"):
                    row.append(s["yerr"][i])
            for s2 in (y2_series or []):
                row.append(s2["y"][i])
            csv_rows.append(row)
        _save_csv(csv_out_path, headers, csv_rows)

    return {
        "png_path": str(out_png),
        "csv_path": str(csv_out_path) if csv_out_path else "",
        "title": title,
        "source_note": source_note,
    }


# ============================================================
# V3: 로컬 기상 DB(D:\0002_XLS_backup\weather_daily_kr.db) 기반 FAO-56 ET0 / ETc 실측 계산기
# ============================================================
def compute_fao56_et0_daily(
    *,
    t_mean_c: float,
    t_min_c: float | None = None,
    t_max_c: float | None = None,
    rh_mean_pct: float = 70.0,
    wind_ms: float = 2.0,
    solar_rad_mj: float | None = None,
    lat_deg: float = 34.82,
    alt_m: float = 38.0,
    doy: int = 150,
    wind_height_m: float = 10.0,
) -> float:
    """FAO-56 Penman-Monteith 일 기준 증발산량 ET0 (mm/day)를 정확히 계산한다 (Allen et al., 1998)."""
    t_min = t_min_c if t_min_c is not None else (t_mean_c - 4.0)
    t_max = t_max_c if t_max_c is not None else (t_mean_c + 4.0)
    t_avg = (t_max + t_min) / 2.0

    # 대기압 P (kPa) & 건습계 상수 gamma (kPa/°C)
    p_kpa = 101.3 * ((293.0 - 0.0065 * alt_m) / 293.0) ** 5.26
    gamma = 0.000665 * p_kpa

    # 포화수증기압 e_s (kPa) & 곡선 기울기 Delta (kPa/°C)
    e_tmax = 0.6108 * math.exp((17.27 * t_max) / (t_max + 237.3))
    e_tmin = 0.6108 * math.exp((17.27 * t_min) / (t_min + 237.3))
    e_s = (e_tmax + e_tmin) / 2.0
    e_a = e_s * max(0.05, min(1.0, rh_mean_pct / 100.0))
    delta = (4098.0 * (0.6108 * math.exp((17.27 * t_avg) / (t_avg + 237.3)))) / ((t_avg + 237.3) ** 2)

    # 2 m 높이 풍속 환산 (FAO-56 Eq. 47)
    u2 = max(0.5, wind_ms * (4.87 / math.log(67.8 * max(2.0, wind_height_m) - 5.42)))

    # 외기복사 R_a (MJ/m²/day, FAO-56 Eq. 21-25)
    phi = math.radians(lat_deg)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
    sol_dec = 0.409 * math.sin((2.0 * math.pi * doy / 365.0) - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(sol_dec))))
    ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(sol_dec) + math.cos(phi) * math.cos(sol_dec) * math.sin(ws)
    )
    rso = (0.75 + 2e-5 * alt_m) * ra

    # 일사량 결측 시 Hargreaves 복사 추정 (k_Rs = 0.16 내륙/0.19 해안; 서남해안 0.17)
    if solar_rad_mj is not None and solar_rad_mj > 0.5:
        rs = solar_rad_mj
    else:
        rs = min(rso, 0.17 * math.sqrt(max(1.0, t_max - t_min)) * ra)

    rns = (1.0 - 0.23) * rs
    sigma = 4.903e-9
    rs_ratio = max(0.3, min(1.0, rs / max(0.1, rso)))
    rnl = (
        sigma
        * (((t_max + 273.16) ** 4 + (t_min + 273.16) ** 4) / 2.0)
        * (0.34 - 0.14 * math.sqrt(max(0.01, e_a)))
        * (1.35 * rs_ratio - 0.35)
    )
    rn = max(0.0, rns - rnl)

    # FAO-56 Eq. 6 (일 단위 G ≈ 0)
    num = 0.408 * delta * rn + gamma * (900.0 / (t_avg + 273.0)) * u2 * max(0.0, e_s - e_a)
    den = delta + gamma * (1.0 + 0.34 * u2)
    return max(0.0, num / den)


def query_monthly_et0_from_weather_db(
    *,
    station_name: str = "목포",
    start_year: int = 2015,
    end_year: int = 2024,
    kc_by_month: dict[int, float] | None = None,
) -> dict[str, Any]:
    """로컬 기상 DB(D:\\0002_XLS_backup\\weather_daily_kr.db)에서 실측 일 기상을 조회해 월별 FAO-56 ET0와 ETc(평균±SD)를 계산한다."""
    from data_connectors import LOCAL_WEATHER_DB_PATH

    if not LOCAL_WEATHER_DB_PATH.is_file():
        raise FileNotFoundError(f"로컬 기상 DB를 찾을 수 없습니다: {LOCAL_WEATHER_DB_PATH}")

    conn = sqlite3.connect(str(LOCAL_WEATHER_DB_PATH))
    try:
        cur = conn.cursor()
        stn_row = cur.execute(
            """
            SELECT station_code, station_name, province, lat, lon, altitude_m, min_date, max_date
            FROM stations
            WHERE network = 'ASOS' AND station_name LIKE ?
            ORDER BY n_days DESC LIMIT 1
            """,
            (f"%{station_name}%",),
        ).fetchone()
        if not stn_row:
            raise ValueError(f"ASOS 기상 지점을 찾을 수 없습니다: {station_name}")
        stn_code, stn_nm, prov, lat, lon, alt, min_d, max_d = stn_row
        lat = float(lat or 34.82)
        alt = float(alt or 38.0)

        rows = cur.execute(
            """
            SELECT year, month, date, tavg_c, tmin_c, tmax_c, rh_avg_pct, wind_avg_ms, solar_rad_mj, prcp_mm
            FROM daily_weather
            WHERE network = 'ASOS' AND station_code = ? AND year BETWEEN ? AND ?
            ORDER BY date
            """,
            (stn_code, start_year, end_year),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"{stn_nm}({stn_code}) 지점의 {start_year}~{end_year}년 기상 데이터가 없습니다.")

    # 월·연도별 합계/일평균 집계
    ym_et0_days: dict[tuple[int, int], list[float]] = {}
    ym_prcp: dict[tuple[int, int], float] = {}
    ym_tavg: dict[tuple[int, int], list[float]] = {}
    month_mid_doy = {1: 15, 2: 46, 3: 74, 4: 105, 5: 135, 6: 166, 7: 196, 8: 227, 9: 258, 10: 288, 11: 319, 12: 349}

    for yr, mo, dt_s, tavg, tmin, tmax, rh, wind, srad, prcp in rows:
        if tavg is None:
            continue
        et0_d = compute_fao56_et0_daily(
            t_mean_c=float(tavg),
            t_min_c=float(tmin) if tmin is not None else None,
            t_max_c=float(tmax) if tmax is not None else None,
            rh_mean_pct=float(rh) if rh is not None else 70.0,
            wind_ms=float(wind) if wind is not None else 2.5,
            solar_rad_mj=float(srad) if srad is not None else None,
            lat_deg=lat,
            alt_m=alt,
            doy=month_mid_doy.get(int(mo), 150),
        )
        ym_et0_days.setdefault((int(yr), int(mo)), []).append(et0_d)
        ym_prcp[(int(yr), int(mo))] = ym_prcp.get((int(yr), int(mo)), 0.0) + float(prcp or 0.0)
        ym_tavg.setdefault((int(yr), int(mo)), []).append(float(tavg))

    # 기본 양파(중만생종 전남 가을정식 11월~익년 6월 수확) FAO-56 Table 12 작물계수
    # 11월 정식·활착(0.70), 12~2월 월동(0.70), 3월 생육재생(0.85), 4~5월 구 비대기(1.05), 6월 도복·성숙기(0.75)
    kc_map = kc_by_month or {11: 0.70, 12: 0.70, 1: 0.70, 2: 0.70, 3: 0.85, 4: 1.05, 5: 1.05, 6: 0.75}
    years_found = sorted({yr for yr, _ in ym_et0_days})
    monthly_stats: list[dict[str, Any]] = []
    for mo in range(1, 13):
        yr_means = []
        yr_sums = []
        yr_prcps = []
        yr_temps = []
        for yr in years_found:
            vals = ym_et0_days.get((yr, mo))
            if vals and len(vals) >= 20:
                m_avg = sum(vals) / len(vals)
                yr_means.append(m_avg)
                yr_sums.append(sum(vals))
                yr_prcps.append(ym_prcp.get((yr, mo), 0.0))
                t_vals = ym_tavg.get((yr, mo)) or []
                if t_vals:
                    yr_temps.append(sum(t_vals) / len(t_vals))
        n_yr = len(yr_means)
        et0_mean = sum(yr_means) / n_yr if n_yr else 0.0
        et0_sd = math.sqrt(sum((x - et0_mean) ** 2 for x in yr_means) / max(1, n_yr - 1)) if n_yr > 1 else 0.0
        et0_sum_mean = sum(yr_sums) / n_yr if n_yr else 0.0
        kc = kc_map.get(mo)
        etc_mean = round(et0_mean * kc, 2) if kc is not None else None
        etc_sum = round(et0_sum_mean * kc, 1) if kc is not None else None
        monthly_stats.append(
            {
                "month": mo,
                "n_years": n_yr,
                "tavg_c": round(sum(yr_temps) / len(yr_temps), 1) if yr_temps else None,
                "prcp_mm": round(sum(yr_prcps) / len(yr_prcps), 1) if yr_prcps else 0.0,
                "et0_mm_day_mean": round(et0_mean, 2),
                "et0_mm_day_sd": round(et0_sd, 2),
                "et0_mm_month": round(et0_sum_mean, 1),
                "kc": kc,
                "etc_mm_day": etc_mean,
                "etc_mm_month": etc_sum,
            }
        )

    return {
        "station_code": stn_code,
        "station_name": stn_nm,
        "province": prov,
        "lat": lat,
        "lon": lon,
        "altitude_m": alt,
        "start_year": min(years_found),
        "end_year": max(years_found),
        "n_years": len(years_found),
        "monthly": monthly_stats,
    }


def generate_swrc_chart(
    out_png: Path,
    *,
    csv_out_path: Path | None = None,
    paper_mode: bool = False,
) -> dict[str, Any]:
    """문헌 표준 van Genuchten 매개변수(Carsel & Parrish, 1988)로 토성별(사양토·양토·식양토) 토양수분 특성곡선을 그린다."""
    # Carsel & Parrish (1988), Water Resources Research 24(5):755-769 Table 2 표준 매개변수
    # alpha (cm^-1), n, theta_r, theta_s (cm^3/cm^3)
    soils = [
        ("사양토 (Sandy Loam)", 0.065, 0.41, 0.075, 1.89),
        ("양토 (Loam)", 0.078, 0.43, 0.036, 1.56),
        ("식양토 (Clay Loam)", 0.095, 0.41, 0.019, 1.31),
    ]
    # 수분 장력 |h| (kPa): 1 kPa ≈ 10.197 cm H2O
    kpa_grid = [1, 2, 5, 10, 15, 20, 25, 33, 50, 75, 100, 200, 500, 1000, 1500]
    series = []
    for name, tr, ts, alpha, n in soils:
        m = 1.0 - 1.0 / n
        y_vals = []
        for kpa in kpa_grid:
            h_cm = kpa * 10.197
            theta = tr + (ts - tr) / ((1.0 + (alpha * h_cm) ** n) ** m)
            y_vals.append(round(theta * 100.0, 2))  # 체적수분함량 %
        series.append({"label": name, "y": y_vals, "kind": "line"})

    return render_data_chart_png(
        out_png=out_png,
        chart_type="line",
        title="그림 5-2. 토성별 토양수분 특성곡선(SWRC)과 양파 적정 관수개시 장력 구간",
        x_label="토양수분 장력 |Ψm| (kPa, 로그 눈금)",
        y_label="체적수분함량 θv (%)",
        source_note="van Genuchten (1980) 모형 및 Carsel & Parrish (1988, Water Resour. Res. 24:755–769) 토성별 표준 매개변수; 양파 관수개시 장력(-15~-25 kPa) FAO-56/RDA 기준",
        series=series,
        x_values=kpa_grid,
        highlight_band={"axis": "x", "min": 15, "max": 25, "label": "양파 구 비대기\n관수개시 구간\n(15–25 kPa)", "label_y_frac": 0.93},
        x_log=True,
        paper_mode=paper_mode,
        csv_out_path=csv_out_path,
    )


def generate_onion_et0_etc_chart(
    out_png: Path,
    *,
    station_name: str = "목포",
    start_year: int = 2015,
    end_year: int = 2024,
    csv_out_path: Path | None = None,
    paper_mode: bool = False,
) -> dict[str, Any]:
    """로컬 기상 DB 실측 자료로 양파 주산지(목포·무안권) 생육기(11월~익년 6월) 월별 ET0 및 ETc 그래프를 그린다."""
    res = query_monthly_et0_from_weather_db(station_name=station_name, start_year=start_year, end_year=end_year)
    by_m = {m["month"]: m for m in res["monthly"]}
    # 양파 재배력 순서: 11월 정식 → 12~2월 월동 → 3월 재생 → 4~5월 구 비대 → 6월 수확
    crop_months = [11, 12, 1, 2, 3, 4, 5, 6]
    stage_tags = ["11월\n(정식)", "12월\n(활착)", "1월\n(월동)", "2월\n(월동)", "3월\n(재생)", "4월\n(구비대)", "5월\n(구비대)", "6월\n(수확)"]

    et0_y = [by_m[m]["et0_mm_day_mean"] for m in crop_months]
    et0_sd = [by_m[m]["et0_mm_day_sd"] for m in crop_months]
    etc_y = [by_m[m]["etc_mm_day"] for m in crop_months]
    kc_y = [by_m[m]["kc"] for m in crop_months]

    out = render_data_chart_png(
        out_png=out_png,
        chart_type="bar",
        title=f"그림 5-3. 양파 주산지({res['station_name']}권) 월별 ET0 및 양파 작물 증발산량 ETc ({res['start_year']}~{res['end_year']}, n={res['n_years']}년)",
        x_label="양파 생육 월 및 주요 단계",
        y_label="증발산량 (mm/day)",
        y2_label="작물계수 Kc (무차원)",
        source_note=f"기상청 ASOS {res['station_name']}(지점 {res['station_code']}, {res['start_year']}–{res['end_year']}, n={res['n_years']}년, weather_daily_kr.db) 기반 FAO-56 ET0 산출; 양파 Kc(0.70/1.05/0.75, Allen et al. 1998)",
        series=[
            {"label": "기준 증발산량 ET0 (평균 ± SD)", "y": et0_y, "yerr": et0_sd, "kind": "bar"},
            {"label": "양파 작물 증발산량 ETc (= Kc × ET0)", "y": etc_y, "kind": "line", "marker": "o"},
        ],
        y2_series=[
            {"label": "양파 작물계수 Kc (우축)", "y": kc_y, "linestyle": "--", "marker": "^"},
        ],
        x_values=stage_tags,
        paper_mode=paper_mode,
        csv_out_path=csv_out_path,
    )
    out["weather_summary"] = res
    return out


def generate_drip_hydraulics_chart(
    out_png: Path,
    *,
    csv_out_path: Path | None = None,
    paper_mode: bool = False,
) -> dict[str, Any]:
    """Hazen-Williams 마찰손실과 점적기 유량-압력식(q = k H^x) 기반 지선 길이별 압력 감소 및 배출량 편차 그래프."""
    # 표준 양파 이랑 점적테이프: 내경 D = 16 mm (0.016 m), 점적 간격 0.20 m, 공칭 유량 1.6 L/h @ 10 m (1.0 bar), C = 145
    d_m = 0.016
    c_hw = 145.0
    spacing_m = 0.20
    q_nom_lph = 1.6
    h_inlet_m = 10.0  # 1.0 bar ≈ 10.2 m, 기준 10.0 m

    lengths = list(range(0, 101, 10))  # 0 ~ 100 m
    # 전길이 100 m 지선(500개 점적기, 총 유입유량 800 L/h = 2.222e-4 m^3/s)에서 거리 x 지점까지의 누적 손실 계산
    total_len = 100.0
    n_emitters_total = int(total_len / spacing_m)
    q_total_m3s = (n_emitters_total * q_nom_lph) / 3_600_000.0
    # 구간별 유량 감소 Q(s) = Q_total * (1 - s/L) 적분 (수치적 1 m 스텝)
    pressures_m: dict[int, float] = {0: h_inlet_m}
    h_cur = h_inlet_m
    for s_m in range(1, 101):
        q_seg = q_total_m3s * max(0.0, 1.0 - (s_m - 0.5) / total_len)
        dh = 10.67 * 1.0 * (q_seg ** 1.852) / ((c_hw ** 1.852) * (d_m ** 4.87))
        h_cur = max(0.5, h_cur - dh)
        pressures_m[s_m] = h_cur

    p_series = [round(pressures_m[x], 2) for x in lengths]
    # 비압력보상형(Non-PC, 난류형 x = 0.50) vs 압력보상형(PC, x = 0.05) 유량
    q_nonpc = [round(q_nom_lph * ((pressures_m[x] / h_inlet_m) ** 0.50), 3) for x in lengths]
    q_pc = [round(q_nom_lph * ((pressures_m[x] / h_inlet_m) ** 0.05), 3) for x in lengths]

    return render_data_chart_png(
        out_png=out_png,
        chart_type="line",
        title="그림 5-4. 점적관 길이(0–100 m)에 따른 압력 감소와 점적기 배출량 편차 (내경 16 mm, 간격 20 cm)",
        x_label="점적 지선 거리 (m)",
        y_label="점적기 배출 유량 q (L/h)",
        y2_label="관 내 작동 압력수두 H (m H2O)",
        source_note="Hazen-Williams 마찰손실식(C=145, D=16 mm, 입구압 10 m H2O) 및 점적기 유량-압력식(q = k H^x; Non-PC x=0.50, PC x=0.05, ASAE EP405.1) 수치 계산",
        series=[
            {"label": "비압력보상형(Non-PC, x=0.50) 배출량", "y": q_nonpc, "kind": "line", "marker": "s"},
            {"label": "압력보상형(PC, x=0.05) 배출량", "y": q_pc, "kind": "line", "marker": "o"},
        ],
        y2_series=[
            {"label": "관 내 압력수두 H (우축)", "y": p_series, "linestyle": ":", "marker": "^"},
        ],
        x_values=lengths,
        paper_mode=paper_mode,
        csv_out_path=csv_out_path,
    )
