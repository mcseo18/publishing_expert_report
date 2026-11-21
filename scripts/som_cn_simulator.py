"""제7장·제11장 실습용 토양 질소 무기화(Stanford-Smith) 및 탄소 분해(RothC 5-풀) 시뮬레이터.

실행 예:
    .venv\\Scripts\\python.exe scripts\\som_cn_simulator.py
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass


def stanford_smith_mineralization(n0_kg_ha: float, k_per_week: float, weeks: list[int]) -> list[dict[str, float]]:
    """Stanford & Smith (1972) 1차 지수 질소 무기화 모델: N_t = N_0 * (1 - exp(-k * t))."""
    return [
        {
            "week": w,
            "cumulative_n_kg_ha": round(n0_kg_ha * (1.0 - math.exp(-k_per_week * w)), 2),
        }
        for w in weeks
    ]


def falloon_iom(soc_t_c_ha: float) -> float:
    """Falloon et al. 경험식: IOM = 0.049 * SOC^1.139 (t C/ha)."""
    return 0.049 * (soc_t_c_ha ** 1.139)


def rothc_clay_co2_ratio(clay_pct: float) -> float:
    """RothC-26.3 점토 함량 기반 CO2 / (BIO + HUM) 분배비 x."""
    return 1.67 * (1.85 + 1.60 * math.exp(-0.0786 * clay_pct))


def rothc_temp_modifier(temp_c: float) -> float:
    """RothC-26.3 온도 보정 인자 a(T)."""
    if temp_c <= -5.0:
        return 0.0
    return 47.91 / (1.0 + math.exp(106.06 / (temp_c + 18.27)))


@dataclass
class RothCParams:
    clay_pct: float = 22.0
    dpm_rpm_ratio: float = 1.44  # 농경지 기본값(DPM/RPM = 1.44)
    k_dpm: float = 10.0  # yr^-1
    k_rpm: float = 0.30  # yr^-1
    k_bio: float = 0.66  # yr^-1
    k_hum: float = 0.02  # yr^-1


def simulate_rothc_simple(
    initial_soc_t_c_ha: float,
    annual_c_input_t_c_ha: float,
    years: int = 30,
    monthly_temps: list[float] | None = None,
    moisture_factor: float = 0.85,
    cover_factor: float = 0.75,
    params: RothCParams | None = None,
) -> dict[str, float]:
    """월별 스텝 기반 교육용 RothC 5-풀 탄소 동역학 시뮬레이터."""
    p = params or RothCParams()
    temps = monthly_temps or [-1.5, 1.0, 6.5, 13.0, 18.5, 22.8, 25.5, 26.0, 21.2, 14.8, 7.8, 1.0]

    iom = falloon_iom(initial_soc_t_c_ha)
    active_soc = max(initial_soc_t_c_ha - iom, 0.0)
    # 초기 근사 풀 비율 (실전에서는 Spin-up 권장)
    dpm = active_soc * 0.01
    rpm = active_soc * 0.14
    bio = active_soc * 0.03
    hum = active_soc * 0.82

    x = rothc_clay_co2_ratio(p.clay_pct)
    frac_bio = 0.46 / (1.0 + x)
    frac_hum = 0.54 / (1.0 + x)
    dpm_share = p.dpm_rpm_ratio / (1.0 + p.dpm_rpm_ratio)
    rpm_share = 1.0 - dpm_share

    monthly_in = annual_c_input_t_c_ha / 12.0
    dt = 1.0 / 12.0

    for _ in range(years):
        for t_c in temps:
            rate_mod = rothc_temp_modifier(t_c) * moisture_factor * cover_factor
            dpm += monthly_in * dpm_share
            rpm += monthly_in * rpm_share

            dec_dpm = dpm * (1.0 - math.exp(-p.k_dpm * rate_mod * dt))
            dec_rpm = rpm * (1.0 - math.exp(-p.k_rpm * rate_mod * dt))
            dec_bio = bio * (1.0 - math.exp(-p.k_bio * rate_mod * dt))
            dec_hum = hum * (1.0 - math.exp(-p.k_hum * rate_mod * dt))

            total_dec = dec_dpm + dec_rpm + dec_bio + dec_hum
            dpm -= dec_dpm
            rpm -= dec_rpm
            bio = bio - dec_bio + total_dec * frac_bio
            hum = hum - dec_hum + total_dec * frac_hum

    final_soc = dpm + rpm + bio + hum + iom
    return {
        "initial_soc_t_c_ha": round(initial_soc_t_c_ha, 2),
        "annual_c_input_t_c_ha": round(annual_c_input_t_c_ha, 2),
        "years": years,
        "final_soc_t_c_ha": round(final_soc, 2),
        "delta_soc_t_c_ha": round(final_soc - initial_soc_t_c_ha, 2),
        "annual_rate_t_c_ha_yr": round((final_soc - initial_soc_t_c_ha) / years, 3),
        "pools": {
            "DPM": round(dpm, 3),
            "RPM": round(rpm, 3),
            "BIO": round(bio, 3),
            "HUM": round(hum, 3),
            "IOM": round(iom, 3),
        },
    }


if __name__ == "__main__":
    demo = {
        "stanford_smith_demo": stanford_smith_mineralization(120.0, 0.054, [2, 4, 8, 12, 24]),
        "rothc_30yr_scenarios": {
            "chemical_only_low_input_1.5tC": simulate_rothc_simple(45.0, 1.5, years=30),
            "compost_plus_residue_3.5tC": simulate_rothc_simple(45.0, 3.5, years=30),
            "green_manure_plus_compost_5.0tC": simulate_rothc_simple(45.0, 5.0, years=30),
        },
    }
    print(json.dumps(demo, ensure_ascii=False, indent=2))
