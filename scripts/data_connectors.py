"""외부 API 및 로컬 기상 DB 통합 데이터 탐색·다운로드·RAG 적재 커넥터 모듈.

지원 데이터 소스:
1. 로컬 통합 기상 DB (D:\\0002_XLS_backup\\weather_daily_kr.db — 690만 행, 876지점 ASOS/AWS/농업기상)
2. 기상청 API허브 종관기상(ASOS kma_sfcdd3.php) 및 방재기상(AWS sfc_aws_day.php)
3. OpenWeatherMap API (현재 기상, 5일/3시간 예보, 대기질)
4. 공공데이터포털 OpenAPI (apis.data.go.kr — JSON/XML 자동 파싱 및 프리셋/임의 엔드포인트)
5. 통계청 KOSIS OpenAPI (통계표 검색 statisticsSearch.do + 실제 시계열 데이터 다운로드)

보안 원칙:
- API 키는 워크스페이스(.git) 외부의 E:\\SMC_Report_Platform_Data\\index\\local_api_keys.json 또는 OS 환경변수에서만 관리한다.
- UI/API 응답에는 절대 평문 키를 반환하지 않고 마스킹된 상태(configured, masked)만 노출한다.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

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
from fetch_project_sources import TIER_DIRS, _write_collection_index_md

LOCAL_WEATHER_DB_PATH = Path(r"D:\0002_XLS_backup\weather_daily_kr.db")
LOCAL_WEATHER_STATIONS_CSV = Path(r"D:\0002_XLS_backup\weather_stations_summary.csv")

API_KEY_FIELDS: dict[str, dict[str, str]] = {
    "OPENAI_API_KEY": {
        "label": "OpenAI API 키 (1단계 목차·요약·키워드 설계 및 수정)",
        "env": "OPENAI_API_KEY",
        "portal": "https://platform.openai.com/api-keys",
    },
    "FAL_KEY": {
        "label": "fal.ai API 키 (5단계 실사진·인포그래픽 시각화 생성)",
        "env": "FAL_KEY",
        "portal": "https://fal.ai/dashboard/keys",
    },
    "GEMINI_API_KEY": {
        "label": "Google Gemini API 키 (나노바나나 이미지 생성)",
        "env": "GEMINI_API_KEY",
        "portal": "https://aistudio.google.com/apikey",
    },
    "KMA_HUB_KEY": {
        "label": "기상청 API허브 인증키 (ASOS/AWS 종관기상)",
        "env": "KMA_HUB_KEY",
        "portal": "https://apihub.kma.go.kr/",
    },
    "OPENWEATHER_API_KEY": {
        "label": "OpenWeatherMap API 키",
        "env": "OPENWEATHER_API_KEY",
        "portal": "https://openweathermap.org/api",
    },
    "DATA_GO_KR_API_KEY": {
        "label": "공공데이터포털 인증키 (data.go.kr)",
        "env": "DATA_GO_KR_API_KEY",
        "portal": "https://www.data.go.kr/",
    },
    "KOSIS_API_KEY": {
        "label": "통계청 KOSIS OpenAPI 인증키",
        "env": "KOSIS_API_KEY",
        "portal": "https://kosis.kr/openapi/",
    },
}

# 공공데이터포털 주요 농업·기상 프리셋 (사용자 serviceKey 자동 주입)
PUBLIC_PORTAL_PRESETS: list[dict[str, Any]] = [
    {
        "preset_id": "kma_asos_daily_datagokr",
        "name": "기상청 지상(종관, ASOS) 일자료 조회 (공공데이터포털)",
        "endpoint": "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList",
        "key_param": "serviceKey",
        "default_params": {
            "pageNo": "1",
            "numOfRows": "31",
            "dataType": "JSON",
            "dataCd": "ASOS",
            "dateCd": "DAY",
            "startDt": "20250901",
            "endDt": "20250930",
            "stnIds": "119",
        },
        "note": "지점번호 예: 108(서울), 119(수원), 136(안동), 146(전주), 184(제주), 189(서귀포)",
    },
    {
        "preset_id": "kma_mid_weather_datagokr",
        "name": "기상청 중기기온예보 조회 (공공데이터포털)",
        "endpoint": "http://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa",
        "key_param": "serviceKey",
        "default_params": {
            "pageNo": "1",
            "numOfRows": "10",
            "dataType": "JSON",
            "regId": "11B10101",
            "tmFc": "202611210600",
        },
        "note": "regId 예: 11B10101(서울), 11B20601(수원), 11F10201(전주), 11G00201(제주)",
    },
    {
        "preset_id": "rda_soil_heuktoram",
        "name": "농촌진흥청 흙토람 토양화학적특성 조회 (공공데이터포털)",
        "endpoint": "http://apis.data.go.kr/1390802/SoilEnviron/SoilExam/getSoilExam",
        "key_param": "serviceKey",
        "default_params": {
            "PNU_Code": "4111112900100010000",
        },
        "note": "필지 고유번호(PNU 19자리) 기준 토양 pH·유기물·유효인산·치환성양이온 조회 (활용신청 필요)",
    },
    {
        "preset_id": "rda_agri_weather_datagokr",
        "name": "농촌진흥청 농업기상 일별 관측자료 (공공데이터포털)",
        "endpoint": "http://apis.data.go.kr/1390802/AgriWeather/WeatherObsrInfo/V2/GnrlWeather/getWeatherTermDayList",
        "key_param": "serviceKey",
        "default_params": {
            "Page_No": "1",
            "Page_Size": "30",
            "begin_Date": "2025-09-01",
            "end_Date": "2025-09-30",
            "obsr_Spot_Code": "477802A001",
        },
        "note": "농진청 농업기상 관측지점별 일별 기온·습도·일사·토양온도·토양수분 조회 (활용신청 필요)",
    },
    {
        "preset_id": "custom_public_api",
        "name": "사용자 직접 지정 공공데이터포털 OpenAPI URL",
        "endpoint": "",
        "key_param": "serviceKey",
        "default_params": {"pageNo": "1", "numOfRows": "30", "type": "json"},
        "note": "공공데이터포털 상세 페이지의 요청 URL과 파라미터를 그대로 입력해 데이터를 내려받습니다.",
    },
]

OWM_PRESET_CITIES: list[dict[str, Any]] = [
    {"label": "수원 (대한민국 · 농진청/경기)", "q": "Suwon,KR", "lat": 37.2636, "lon": 127.0286},
    {"label": "전주 (대한민국 · 농진청 본원)", "q": "Jeonju,KR", "lat": 35.8242, "lon": 127.1480},
    {"label": "안동 (대한민국 · 사과 주산지)", "q": "Andong,KR", "lat": 36.5684, "lon": 128.7294},
    {"label": "나주 (대한민국 · 배 주산지)", "q": "Naju,KR", "lat": 35.0161, "lon": 126.7108},
    {"label": "서귀포 (대한민국 · 감귤/원예)", "q": "Seogwipo,KR", "lat": 33.2541, "lon": 126.5601},
    {"label": "상주 (대한민국 · 곶감/과수)", "q": "Sangju,KR", "lat": 36.4109, "lon": 128.1591},
    {"label": "Davis, CA (미국 · UC Davis)", "q": "Davis,US", "lat": 38.5449, "lon": -121.7405},
    {"label": "Tsukuba (일본 · NARO 농연기구)", "q": "Tsukuba,JP", "lat": 36.0835, "lon": 140.0764},
    {"label": "Wageningen (네덜란드 · WUR)", "q": "Wageningen,NL", "lat": 51.9692, "lon": 5.6654},
]


# ============================================================
# 1. 보안 로컬 API 키 저장소 (워크스페이스 외부 E:\ 저장, 마스킹 반환)
# ============================================================
def _keys_file(cfg: PlatformConfig) -> Path:
    cfg.index_dir.mkdir(parents=True, exist_ok=True)
    return cfg.index_dir / "local_api_keys.json"


def _load_saved_keys_raw(cfg: PlatformConfig) -> dict[str, str]:
    p = _keys_file(cfg)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: str(v).strip() for k, v in data.items() if isinstance(v, str) and v.strip()}
    except Exception:
        return {}


def resolve_api_key(key_name: str, override_key: str | None = None, cfg: PlatformConfig | None = None) -> str:
    if override_key and override_key.strip():
        return override_key.strip()
    cfg = cfg or get_config()
    saved = _load_saved_keys_raw(cfg)
    if saved.get(key_name):
        return saved[key_name]
    env_name = API_KEY_FIELDS.get(key_name, {}).get("env", key_name)
    return os.environ.get(env_name, "").strip()


def _mask_secret(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 6:
        return "*" * len(val)
    return f"{val[:2]}{'*' * min(10, len(val) - 6)}{val[-4:]}"


def get_api_keys_status(cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    saved = _load_saved_keys_raw(cfg)
    out: dict[str, Any] = {}
    for k, meta in API_KEY_FIELDS.items():
        val = saved.get(k) or os.environ.get(meta["env"], "").strip()
        src = "saved_local" if saved.get(k) else ("env" if val else "none")
        out[k] = {
            "label": meta["label"],
            "portal": meta["portal"],
            "configured": bool(val),
            "source": src,
            "masked": _mask_secret(val),
        }
    return {"keys": out, "storage_path": str(_keys_file(cfg))}


def save_api_keys(updates: dict[str, str], cfg: PlatformConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_config()
    cur = _load_saved_keys_raw(cfg)
    for k, v in updates.items():
        if k not in API_KEY_FIELDS:
            continue
        val = (v or "").strip()
        if val == "__CLEAR__":
            cur.pop(k, None)
        elif val:
            cur[k] = val
    p = _keys_file(cfg)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_api_keys_status(cfg)


# ============================================================
# 2. D:\0002_XLS_backup 로컬 통합 종관기상 DB (690만 행, 876지점)
# ============================================================
def get_weather_db_overview(db_path: Path = LOCAL_WEATHER_DB_PATH) -> dict[str, Any]:
    if not db_path.is_file():
        return {"available": False, "db_path": str(db_path), "error": "로컬 기상 DB 파일을 찾을 수 없습니다."}
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        net_rows = cur.execute(
            """
            SELECT network, COUNT(*) AS stn_cnt, MIN(min_date), MAX(max_date), SUM(n_days)
            FROM stations
            GROUP BY network
            ORDER BY stn_cnt DESC
            """
        ).fetchall()
        provinces = [
            r[0]
            for r in cur.execute("SELECT DISTINCT province FROM stations WHERE province IS NOT NULL AND province != '' ORDER BY province").fetchall()
        ]
        asos_stations = [
            {
                "network": r[0],
                "station_code": r[1],
                "station_name": r[2],
                "province": r[3] or "",
                "lat": r[4],
                "lon": r[5],
                "altitude_m": r[6],
                "min_date": r[7],
                "max_date": r[8],
                "n_days": r[9],
            }
            for r in cur.execute(
                """
                SELECT network, station_code, station_name, province, lat, lon, altitude_m, min_date, max_date, n_days
                FROM stations
                WHERE network = 'ASOS'
                ORDER BY station_name
                """
            ).fetchall()
        ]
        total_rows = sum(int(r[4] or 0) for r in net_rows)
        return {
            "available": True,
            "db_path": str(db_path),
            "size_mb": round(db_path.stat().st_size / (1024 * 1024), 1),
            "total_records": total_rows,
            "networks": [
                {"network": r[0], "stations": r[1], "min_date": r[2], "max_date": r[3], "records": r[4]}
                for r in net_rows
            ],
            "provinces": provinces,
            "asos_stations": asos_stations,
        }
    finally:
        conn.close()


def query_local_weather_db(
    *,
    network: str = "ASOS",
    station_query: str = "",
    province: str = "",
    start_date: str = "2024-01-01",
    end_date: str = "2026-10-31",
    agg_mode: str = "monthly",  # daily | monthly | yearly
    limit: int = 300,
    db_path: Path = LOCAL_WEATHER_DB_PATH,
) -> dict[str, Any]:
    """D:\\0002_XLS_backup\\weather_daily_kr.db 에서 지점·기간·관측망별 실측 기상 시계열/통계를 추출한다."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Weather DB not found: {db_path}")

    where = ["d.date BETWEEN ? AND ?"]
    params: list[Any] = [start_date, end_date]
    if network and network.upper() != "ALL":
        where.append("d.network = ?")
        params.append(network.upper())
    if province and province.strip():
        where.append("d.province LIKE ?")
        params.append(f"%{province.strip()}%")
    if station_query and station_query.strip():
        sq = station_query.strip()
        where.append("(d.station_name LIKE ? OR d.station_code = ?)")
        params.extend([f"%{sq}%", sq])

    where_sql = " AND ".join(where)
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        summary_row = cur.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT d.station_code),
                   ROUND(AVG(d.tavg_c), 2), ROUND(MIN(d.tmin_c), 2), ROUND(MAX(d.tmax_c), 2),
                   ROUND(SUM(COALESCE(d.prcp_mm, 0)), 1), ROUND(AVG(d.rh_avg_pct), 1),
                   ROUND(AVG(d.solar_rad_mj), 2), ROUND(AVG(d.wind_avg_ms), 2),
                   ROUND(AVG(d.soil_temp_10cm_c), 2), ROUND(AVG(d.soil_moisture_pct), 2)
            FROM daily_weather d
            WHERE {where_sql}
            """,
            params,
        ).fetchone()

        if agg_mode == "yearly":
            q = f"""
                SELECT d.year AS period, d.network, d.station_code, d.station_name, d.province,
                       COUNT(*) AS days,
                       ROUND(AVG(d.tavg_c), 2) AS tavg_c,
                       ROUND(AVG(d.tmin_c), 2) AS tmin_c,
                       ROUND(AVG(d.tmax_c), 2) AS tmax_c,
                       ROUND(SUM(COALESCE(d.prcp_mm, 0)), 1) AS prcp_sum_mm,
                       ROUND(AVG(d.rh_avg_pct), 1) AS rh_avg_pct,
                       ROUND(AVG(d.solar_rad_mj), 2) AS solar_rad_mj,
                       ROUND(AVG(d.wind_avg_ms), 2) AS wind_avg_ms,
                       ROUND(AVG(d.soil_temp_10cm_c), 2) AS soil_temp_10cm_c
                FROM daily_weather d
                WHERE {where_sql}
                GROUP BY d.year, d.network, d.station_code, d.station_name, d.province
                ORDER BY d.year DESC, d.station_name
                LIMIT ?
            """
        elif agg_mode == "monthly":
            q = f"""
                SELECT printf('%04d-%02d', d.year, d.month) AS period, d.network, d.station_code, d.station_name, d.province,
                       COUNT(*) AS days,
                       ROUND(AVG(d.tavg_c), 2) AS tavg_c,
                       ROUND(AVG(d.tmin_c), 2) AS tmin_c,
                       ROUND(AVG(d.tmax_c), 2) AS tmax_c,
                       ROUND(SUM(COALESCE(d.prcp_mm, 0)), 1) AS prcp_sum_mm,
                       ROUND(AVG(d.rh_avg_pct), 1) AS rh_avg_pct,
                       ROUND(AVG(d.solar_rad_mj), 2) AS solar_rad_mj,
                       ROUND(AVG(d.wind_avg_ms), 2) AS wind_avg_ms,
                       ROUND(AVG(d.soil_temp_10cm_c), 2) AS soil_temp_10cm_c
                FROM daily_weather d
                WHERE {where_sql}
                GROUP BY d.year, d.month, d.network, d.station_code, d.station_name, d.province
                ORDER BY period DESC, d.station_name
                LIMIT ?
            """
        else:
            q = f"""
                SELECT d.date AS period, d.network, d.station_code, d.station_name, d.province,
                       d.tavg_c, d.tmin_c, d.tmax_c, d.prcp_mm, d.rh_avg_pct,
                       d.solar_rad_mj, d.sunshine_hr, d.wind_avg_ms, d.soil_temp_10cm_c, d.soil_moisture_pct
                FROM daily_weather d
                WHERE {where_sql}
                ORDER BY d.date DESC, d.station_name
                LIMIT ?
            """
        rows_raw = cur.execute(q, params + [min(max(limit, 10), 2000)]).fetchall()
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in rows_raw]
    finally:
        conn.close()

    summary = {
        "total_daily_rows": int(summary_row[0] or 0),
        "station_count": int(summary_row[1] or 0),
        "mean_tavg_c": summary_row[2],
        "min_tmin_c": summary_row[3],
        "max_tmax_c": summary_row[4],
        "total_prcp_mm": summary_row[5],
        "mean_rh_pct": summary_row[6],
        "mean_solar_rad_mj": summary_row[7],
        "mean_wind_ms": summary_row[8],
        "mean_soil_temp_10cm_c": summary_row[9],
        "mean_soil_moisture_pct": summary_row[10],
    }
    title = f"[국내 종관기상 DB] {network} · {station_query or province or '전국'} ({start_date}~{end_date}, {agg_mode})"
    md = _rows_to_markdown(
        title=title,
        meta_lines=[
            f"- **원천 DB**: `D:\\0002_XLS_backup\\weather_daily_kr.db` (기상청 ASOS/AWS·농업기상 통합 690만 건)",
            f"- **조회 조건**: 관측망 `{network}` | 지점 `{station_query or '전체'}` | 시도 `{province or '전체'}` | 기간 `{start_date} ~ {end_date}` | 집계 `{agg_mode}`",
            f"- **기간 요약**: 총 일별 관측 {summary['total_daily_rows']:,}건 ({summary['station_count']}개 지점) | 평균기온 {summary['mean_tavg_c']}℃ (최저 {summary['min_tmin_c']}℃ / 최고 {summary['max_tmax_c']}℃) | 누적강수 {summary['total_prcp_mm']}mm | 평균습도 {summary['mean_rh_pct']}% | 평균일사 {summary['mean_solar_rad_mj']} MJ/m²",
        ],
        columns=cols,
        rows=rows,
        max_md_rows=60,
    )
    return {
        "source_kind": "local_weather_db",
        "title": title,
        "url": f"local-db://D:/0002_XLS_backup/weather_daily_kr.db?network={network}&station={station_query}&start={start_date}&end={end_date}",
        "license_note": "로컬 통합 기상 DB (기상청 ASOS/AWS·농업기상 공공 실측자료) - 연구·교재 분석 목적",
        "summary": summary,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "markdown": md,
    }


# ============================================================
# 3. 기상청 API허브 실시간 ASOS 종관기상 일자료 (kma_sfcdd3.php)
# ============================================================
def _kma_num(tok: str, missing_floor: float) -> float | None:
    try:
        v = float(tok)
        return None if v <= missing_floor else v
    except Exception:
        return None


def fetch_kma_apihub_asos(
    *,
    start_date: str,
    end_date: str,
    stn: str = "119",
    api_key: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """기상청 API허브 종관기상 일자료(kma_sfcdd3.php, 56컬럼 공백구분)를 실시간 조회·파싱한다."""
    key = resolve_api_key("KMA_HUB_KEY", api_key, cfg)
    if not key:
        raise ValueError("기상청 API허브 인증키(KMA_HUB_KEY)가 설정되지 않았습니다. 상단 API 키 설정에서 입력해 주세요.")

    tm1 = re.sub(r"[^0-9]", "", start_date)[:8]
    tm2 = re.sub(r"[^0-9]", "", end_date)[:8]
    stn_clean = re.sub(r"[^0-9]", "", str(stn or "0")) or "0"

    base_url = "https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php"
    resp = requests.get(
        base_url,
        params={"tm1": tm1, "tm2": tm2, "stn": stn_clean, "help": "0", "authKey": key},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    resp.raise_for_status()
    text = resp.text

    # 지점명 매핑 (weather_stations_summary.csv 활용)
    stn_names: dict[str, str] = {}
    if LOCAL_WEATHER_STATIONS_CSV.is_file():
        try:
            with LOCAL_WEATHER_STATIONS_CSV.open("r", encoding="utf-8-sig", errors="ignore") as f:
                for r in csv.DictReader(f):
                    if r.get("network") == "ASOS" and r.get("station_code"):
                        stn_names[str(r["station_code"]).strip()] = r.get("station_name", "")
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 42 or not re.fullmatch(r"\d{8}", parts[0]):
            continue
        tm_str = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}"
        stn_id = parts[1]
        rows.append(
            {
                "date": tm_str,
                "station_code": stn_id,
                "station_name": stn_names.get(stn_id, f"STN-{stn_id}"),
                "tavg_c": _kma_num(parts[10], -90.0),
                "tmax_c": _kma_num(parts[11], -90.0),
                "tmin_c": _kma_num(parts[13], -90.0),
                "grass_tmin_c": _kma_num(parts[17], -90.0),
                "rh_avg_pct": _kma_num(parts[18], -9.0),
                "wind_avg_ms": _kma_num(parts[2], -9.0),
                "wind_max_ms": _kma_num(parts[5], -9.0),
                "sunshine_hr": _kma_num(parts[32], -9.0),
                "solar_rad_mj": _kma_num(parts[35], -9.0),
                "prcp_mm": _kma_num(parts[38], -9.0),
                "prcp_dur_hr": _kma_num(parts[40], -9.0),
                "prcp_1h_max_mm": _kma_num(parts[41], -9.0),
                "cloud_cover": _kma_num(parts[31], -9.0),
                "evap_small_mm": _kma_num(parts[22], -9.0),
                "evap_large_mm": _kma_num(parts[23], -9.0),
                "snow_new_cm": _kma_num(parts[47], -9.0) if len(parts) > 47 else None,
            }
        )

    cols = list(rows[0].keys()) if rows else ["date", "station_code", "station_name", "tavg_c", "tmin_c", "tmax_c", "prcp_mm", "rh_avg_pct", "solar_rad_mj"]
    tavg_vals = [r["tavg_c"] for r in rows if r["tavg_c"] is not None]
    prcp_vals = [r["prcp_mm"] for r in rows if r["prcp_mm"] is not None]
    summary = {
        "rows_parsed": len(rows),
        "mean_tavg_c": round(sum(tavg_vals) / len(tavg_vals), 2) if tavg_vals else None,
        "total_prcp_mm": round(sum(prcp_vals), 1) if prcp_vals else 0.0,
        "station": stn_names.get(stn_clean, stn_clean),
    }
    title = f"[기상청 API허브 ASOS] 지점 {summary['station']} ({tm1}~{tm2})"
    md = _rows_to_markdown(
        title=title,
        meta_lines=[
            f"- **API 엔드포인트**: `https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php` (인증키 비공개 처리)",
            f"- **조회 조건**: 지점 `{stn_clean} ({summary['station']})` | 기간 `{tm1} ~ {tm2}` | 수집 건수 {len(rows)}건",
            f"- **요약 통계**: 평균기온 `{summary['mean_tavg_c']}℃` | 누적강수 `{summary['total_prcp_mm']}mm`",
            f"- **수집 시각**: `{utc_now_iso()}`",
        ],
        columns=cols,
        rows=rows,
        max_md_rows=60,
    )
    return {
        "source_kind": "kma_apihub_asos",
        "title": title,
        "url": f"https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php?tm1={tm1}&tm2={tm2}&stn={stn_clean}",
        "license_note": "기상청 API허브 공식 종관기상관측(ASOS) 일자료 - 공공누리 제1유형/학술 인용",
        "summary": summary,
        "columns": cols,
        "rows": rows[:500],
        "row_count": len(rows),
        "markdown": md,
    }


# ============================================================
# 4. OpenWeatherMap API (현재 기상 + 5일 예보 + 대기질)
# ============================================================
def fetch_openweathermap(
    *,
    city: str = "Suwon,KR",
    lat: float | None = None,
    lon: float | None = None,
    include_forecast: bool = True,
    include_air: bool = True,
    api_key: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """OpenWeatherMap API로 현재 기상, 5일/3시간 예보, 대기질 데이터를 조회한다."""
    key = resolve_api_key("OPENWEATHER_API_KEY", api_key, cfg)
    if not key:
        raise ValueError("OpenWeatherMap API 키(OPENWEATHER_API_KEY)가 설정되지 않았습니다. 상단 API 키 설정에서 입력해 주세요.")

    params: dict[str, Any] = {"appid": key, "units": "metric", "lang": "kr"}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    else:
        params["q"] = city.strip() or "Suwon,KR"

    cur_r = requests.get("https://api.openweathermap.org/data/2.5/weather", params=params, timeout=15)
    cur_r.raise_for_status()
    cur_j = cur_r.json()
    coord = cur_j.get("coord") or {}
    c_lat, c_lon = coord.get("lat"), coord.get("lon")
    loc_name = f"{cur_j.get('name', city)} ({(cur_j.get('sys') or {}).get('country', '')})"

    main_d = cur_j.get("main") or {}
    wind_d = cur_j.get("wind") or {}
    weather_desc = ", ".join(w.get("description", "") for w in (cur_j.get("weather") or []))
    current_row = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kind": "current",
        "location": loc_name,
        "temp_c": main_d.get("temp"),
        "temp_min_c": main_d.get("temp_min"),
        "temp_max_c": main_d.get("temp_max"),
        "humidity_pct": main_d.get("humidity"),
        "pressure_hpa": main_d.get("pressure"),
        "wind_ms": wind_d.get("speed"),
        "clouds_pct": (cur_j.get("clouds") or {}).get("all"),
        "rain_3h_mm": (cur_j.get("rain") or {}).get("1h") or (cur_j.get("rain") or {}).get("3h") or 0.0,
        "weather": weather_desc,
    }
    rows: list[dict[str, Any]] = [current_row]

    if include_forecast and c_lat is not None and c_lon is not None:
        fc_r = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": c_lat, "lon": c_lon, "appid": key, "units": "metric", "lang": "kr"},
            timeout=15,
        )
        if fc_r.status_code == 200:
            for it in fc_r.json().get("list", [])[:24]:
                m = it.get("main") or {}
                w = it.get("wind") or {}
                rows.append(
                    {
                        "datetime": it.get("dt_txt", ""),
                        "kind": "forecast_3h",
                        "location": loc_name,
                        "temp_c": m.get("temp"),
                        "temp_min_c": m.get("temp_min"),
                        "temp_max_c": m.get("temp_max"),
                        "humidity_pct": m.get("humidity"),
                        "pressure_hpa": m.get("pressure"),
                        "wind_ms": w.get("speed"),
                        "clouds_pct": (it.get("clouds") or {}).get("all"),
                        "rain_3h_mm": (it.get("rain") or {}).get("3h") or 0.0,
                        "weather": ", ".join(x.get("description", "") for x in (it.get("weather") or [])),
                    }
                )

    air_summary: dict[str, Any] = {}
    if include_air and c_lat is not None and c_lon is not None:
        air_r = requests.get(
            "https://api.openweathermap.org/data/2.5/air_pollution",
            params={"lat": c_lat, "lon": c_lon, "appid": key},
            timeout=15,
        )
        if air_r.status_code == 200:
            al = air_r.json().get("list") or []
            if al:
                air_summary = {"aqi": (al[0].get("main") or {}).get("aqi"), **(al[0].get("components") or {})}

    cols = list(current_row.keys())
    title = f"[OpenWeatherMap API] {loc_name} 실시간 기상 및 단기 예보 ({datetime.now().strftime('%Y-%m-%d')})"
    meta_lines = [
        f"- **위치 / 좌표**: `{loc_name}` (lat `{c_lat}`, lon `{c_lon}`)",
        f"- **현재 기상**: 기온 `{current_row['temp_c']}℃`, 습도 `{current_row['humidity_pct']}%`, 풍속 `{current_row['wind_ms']} m/s`, 기압 `{current_row['pressure_hpa']} hPa`, 날씨 `{weather_desc}`",
        f"- **수집 시각**: `{utc_now_iso()}` (예보 {max(0, len(rows)-1)}개 구간 포함)",
    ]
    if air_summary:
        meta_lines.append(
            f"- **대기질 (Air Pollution)**: AQI `{air_summary.get('aqi')}`, PM2.5 `{air_summary.get('pm2_5')} μg/m³`, PM10 `{air_summary.get('pm10')} μg/m³`, O₃ `{air_summary.get('o3')} μg/m³`"
        )
    md = _rows_to_markdown(title=title, meta_lines=meta_lines, columns=cols, rows=rows, max_md_rows=40)
    return {
        "source_kind": "openweathermap",
        "title": title,
        "url": f"https://openweathermap.org/?lat={c_lat}&lon={c_lon}",
        "license_note": "OpenWeatherMap API (CC BY-SA 4.0) - 기상 현황·예보 분석 및 인용",
        "summary": {"location": loc_name, "lat": c_lat, "lon": c_lon, "current": current_row, "air": air_summary},
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "markdown": md,
    }


# ============================================================
# 5. 공공데이터포털 OpenAPI 범용 접속기 (JSON / XML 자동 파싱)
# ============================================================
def _extract_rows_from_any_json(obj: Any) -> list[dict[str, Any]]:
    """공공데이터포털 중첩 JSON 응답에서 가장 큰 객체 리스트(item 배열)를 자동 추출한다."""
    best: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        nonlocal best
        if isinstance(node, list):
            dict_items = [x for x in node if isinstance(x, dict)]
            if dict_items and len(dict_items) > len(best):
                best = dict_items
            for x in node[:20]:
                _walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)

    _walk(obj)
    if not best and isinstance(obj, dict):
        return [{k: str(v)[:180] for k, v in obj.items()}]
    return best


def _extract_rows_from_xml(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items = root.findall(".//item") or root.findall(".//row")
    rows: list[dict[str, Any]] = []
    for it in items:
        row = {child.tag.split("}")[-1]: (child.text or "").strip() for child in it}
        if row:
            rows.append(row)
    if not rows:
        flat = {el.tag.split("}")[-1]: (el.text or "").strip() for el in root.iter() if (el.text or "").strip()}
        if flat:
            rows.append(flat)
    return rows


def fetch_public_data_portal(
    *,
    endpoint: str,
    params: dict[str, Any] | None = None,
    key_param: str = "serviceKey",
    dataset_label: str = "",
    api_key: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """공공데이터포털 OpenAPI(apis.data.go.kr 등)에 접속해 JSON/XML 데이터를 다운로드·표화한다."""
    ep = (endpoint or "").strip()
    if not ep.startswith(("http://", "https://")):
        raise ValueError("유효한 공공데이터포털 API 요청 URL(http:// 또는 https://)을 입력해 주세요.")
    key = resolve_api_key("DATA_GO_KR_API_KEY", api_key, cfg)
    if not key and key_param not in ep:
        raise ValueError("공공데이터포털 인증키(DATA_GO_KR_API_KEY)가 설정되지 않았습니다. 상단 API 키 설정에서 입력해 주세요.")

    q_params = {k: str(v) for k, v in (params or {}).items() if str(v).strip() != ""}
    # 공공데이터포털은 이미 URL-인코딩된 키(% 포함)를 그대로 쿼리에 붙여야 하는 경우가 많음
    encoded_qs = urllib.parse.urlencode(q_params)
    sep = "&" if "?" in ep else "?"
    if key and key_param not in ep and key_param not in q_params:
        key_part = f"{key_param}={key}" if "%" in key else f"{key_param}={urllib.parse.quote(key, safe='')}"
        full_url = f"{ep}{sep}{key_part}" + (f"&{encoded_qs}" if encoded_qs else "")
    else:
        full_url = f"{ep}{sep}{encoded_qs}" if encoded_qs else ep

    resp = requests.get(full_url, headers={"User-Agent": USER_AGENT}, timeout=25)
    resp.raise_for_status()
    ctype = (resp.headers.get("content-type") or "").lower()
    raw_text = resp.text.strip()

    rows: list[dict[str, Any]] = []
    parsed_format = "text"
    if "json" in ctype or raw_text.startswith(("{", "[")):
        parsed_format = "json"
        rows = _extract_rows_from_any_json(resp.json())
    elif "xml" in ctype or raw_text.startswith("<"):
        parsed_format = "xml"
        rows = _extract_rows_from_xml(raw_text)
    else:
        rows = [{"raw_excerpt": raw_text[:1000]}]

    cols: list[str] = []
    for r in rows[:30]:
        for k in r.keys():
            if k not in cols:
                cols.append(k)

    clean_url_display = re.sub(r"(serviceKey|authKey|apiKey)=[^&]+", r"\1=***", full_url, flags=re.I)
    title = dataset_label.strip() or f"[공공데이터포털 API] {urllib.parse.urlparse(ep).path.strip('/').split('/')[-1] or 'OpenAPI'}"
    md = _rows_to_markdown(
        title=title,
        meta_lines=[
            f"- **요청 엔드포인트**: `{clean_url_display}`",
            f"- **응답 형식 / 건수**: `{parsed_format.upper()}` / 총 `{len(rows)}`행",
            f"- **수집 시각**: `{utc_now_iso()}`",
        ],
        columns=cols,
        rows=rows,
        max_md_rows=60,
    )
    return {
        "source_kind": "public_data_portal",
        "title": title,
        "url": ep,
        "license_note": "공공데이터포털(data.go.kr) OpenAPI 공공저작물 - 교재 근거·통계 활용",
        "summary": {"format": parsed_format, "row_count": len(rows), "columns": cols[:12]},
        "columns": cols,
        "rows": rows[:400],
        "row_count": len(rows),
        "markdown": md,
    }


# ============================================================
# 6. 통계청 KOSIS OpenAPI (통계표 검색 + 실데이터 다운로드)
# ============================================================
def search_kosis_tables(
    *,
    keyword: str,
    count: int = 15,
    api_key: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """통계청 KOSIS OpenAPI(statisticsSearch.do)로 통계표 목록을 검색한다."""
    key = resolve_api_key("KOSIS_API_KEY", api_key, cfg)
    if not key:
        raise ValueError("통계청 KOSIS 인증키(KOSIS_API_KEY)가 설정되지 않았습니다. 상단 API 키 설정에서 입력해 주세요.")

    resp = requests.get(
        "https://kosis.kr/openapi/statisticsSearch.do",
        params={
            "method": "getList",
            "apiKey": key,
            "searchNm": keyword.strip(),
            "format": "json",
            "jsonVD": "Y",
            "startCount": 1,
            "resultCount": min(max(count, 1), 30),
        },
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("err"):
        raise RuntimeError(f"KOSIS API 오류({data.get('err')}): {data.get('errMsg')}")
    items = data if isinstance(data, list) else []
    tables = [
        {
            "org_id": it.get("ORG_ID", ""),
            "org_name": it.get("ORG_NM", ""),
            "tbl_id": it.get("TBL_ID", ""),
            "tbl_name": it.get("TBL_NM") or it.get("STAT_NM") or "",
            "start_prd": it.get("STRT_PRD_DE", ""),
            "end_prd": it.get("END_PRD_DE", ""),
            "link_url": it.get("LINK_URL") or "https://kosis.kr/",
        }
        for it in items
    ]
    return {"keyword": keyword, "count": len(tables), "tables": tables}


def download_kosis_data(
    *,
    org_id: str = "",
    tbl_id: str = "",
    tbl_name: str = "",
    itm_id: str = "ALL",
    obj_l1: str = "ALL",
    prd_se: str = "Y",
    start_prd: str = "2019",
    end_prd: str = "2025",
    full_openapi_url: str = "",
    api_key: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """통계청 KOSIS 통계표 실제 수치 데이터를 다운로드해 표·CSV·마크다운으로 변환한다."""
    key = resolve_api_key("KOSIS_API_KEY", api_key, cfg)
    if not key and "apiKey=" not in full_openapi_url:
        raise ValueError("통계청 KOSIS 인증키(KOSIS_API_KEY)가 설정되지 않았습니다. 상단 API 키 설정에서 입력해 주세요.")

    if full_openapi_url and full_openapi_url.strip().startswith(("http://", "https://")):
        url = full_openapi_url.strip()
        if "apiKey=" not in url and key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}apiKey={urllib.parse.quote(key, safe='')}"
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        src_url_clean = re.sub(r"apiKey=[^&]+", "apiKey=***", url, flags=re.I)
    else:
        if not org_id.strip() or not tbl_id.strip():
            raise ValueError("org_id와 tbl_id를 입력하거나 KOSIS OpenAPI 전체 URL을 붙여넣어 주세요.")
        params = {
            "method": "getList",
            "apiKey": key,
            "itmId": itm_id.strip() or "ALL",
            "objL1": obj_l1.strip() or "ALL",
            "format": "json",
            "jsonVD": "Y",
            "prdSe": prd_se.strip() or "Y",
            "startPrdDe": start_prd.strip() or "2019",
            "endPrdDe": end_prd.strip() or "2025",
            "orgId": org_id.strip(),
            "tblId": tbl_id.strip(),
        }
        resp = requests.get("https://kosis.kr/openapi/Param/statisticsParameterData.do", params=params, headers={"User-Agent": USER_AGENT}, timeout=25)
        src_url_clean = f"https://kosis.kr/openapi/Param/statisticsParameterData.do?orgId={org_id}&tblId={tbl_id}&prdSe={prd_se}&startPrdDe={start_prd}&endPrdDe={end_prd}"

    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("err"):
        raise RuntimeError(f"KOSIS 데이터 조회 오류({data.get('err')}): {data.get('errMsg')} (일부 다차원 통계표는 KOSIS OpenAPI URL 생성기 주소를 붙여넣으면 정확히 조회됩니다.)")

    raw_rows = data if isinstance(data, list) else _extract_rows_from_any_json(data)
    rows: list[dict[str, Any]] = []
    for r in raw_rows[:500]:
        rows.append(
            {
                "PRD_DE": r.get("PRD_DE", ""),
                "TBL_NM": r.get("TBL_NM", tbl_name),
                "C1_NM": r.get("C1_NM", ""),
                "C2_NM": r.get("C2_NM", ""),
                "ITM_NM": r.get("ITM_NM", ""),
                "DT": r.get("DT", ""),
                "UNIT_NM": r.get("UNIT_NM", ""),
            }
            if "DT" in r
            else r
        )

    cols = list(rows[0].keys()) if rows else ["PRD_DE", "C1_NM", "ITM_NM", "DT", "UNIT_NM"]
    label = tbl_name or (rows[0].get("TBL_NM") if rows and isinstance(rows[0], dict) else "") or f"{org_id}_{tbl_id}"
    title = f"[통계청 KOSIS] {label} ({start_prd}~{end_prd})"
    md = _rows_to_markdown(
        title=title,
        meta_lines=[
            f"- **기관 / 통계표 ID**: `orgId={org_id}` / `tblId={tbl_id}`",
            f"- **요청 URL**: `{src_url_clean}`",
            f"- **수집 건수**: `{len(raw_rows)}`행 (미리보기 최대 500행)",
            f"- **수집 시각**: `{utc_now_iso()}`",
        ],
        columns=cols,
        rows=rows,
        max_md_rows=60,
    )
    return {
        "source_kind": "kosis_statistics",
        "title": title,
        "url": src_url_clean,
        "license_note": "통계청 국가통계포털(KOSIS) 공식 통계자료 - 공공누리 제1유형/학술 인용",
        "summary": {"org_id": org_id, "tbl_id": tbl_id, "tbl_name": label, "row_count": len(raw_rows)},
        "columns": cols,
        "rows": rows,
        "row_count": len(raw_rows),
        "markdown": md,
    }


# ============================================================
# 7. 공통 마크다운·CSV 변환 및 프로젝트 분리 폴더 + RAG 즉시 저장
# ============================================================
def _rows_to_markdown(
    *,
    title: str,
    meta_lines: list[str],
    columns: list[str],
    rows: list[dict[str, Any]],
    max_md_rows: int = 50,
) -> str:
    lines = [f"# {title}", "", *meta_lines, ""]
    if columns and rows:
        use_cols = columns[:12]
        lines.append("## 수집 데이터 요약표")
        lines.append("")
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in use_cols) + " |")
        lines.append("| " + " | ".join(":---" for _ in use_cols) + " |")
        for r in rows[:max_md_rows]:
            vals = [str(r.get(c, "") if r.get(c) is not None else "").replace("|", "/").replace("\n", " ")[:70] for c in use_cols]
            lines.append("| " + " | ".join(vals) + " |")
        if len(rows) > max_md_rows:
            lines.append(f"\n_외 {len(rows) - max_md_rows}행은 동봉된 CSV/JSON 원본 파일에 전체 저장되었습니다._")
    else:
        lines.append("_조회된 행 데이터가 없습니다._")
    return "\n".join(lines) + "\n"


def rows_to_csv_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    if not columns and rows:
        columns = list(rows[0].keys())
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def save_explorer_dataset_to_project(
    *,
    project_id: str,
    title: str,
    source_kind: str,
    url: str,
    license_note: str,
    markdown_text: str,
    columns: list[str] | None = None,
    rows: list[dict[str, Any]] | None = None,
    user_prompt_note: str = "",
    also_ingest_rag: bool = True,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """탐색·다운로드한 기상/공공포털/통계청 데이터를 프로젝트 분리 폴더(CSV+JSON+MD)에 저장하고 RAG에 적재한다."""
    cfg = cfg or get_config()
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project {project_id} not found")

    packet_id = st.get("packet_id") or f"{project_id}_evidence"
    topic_ko = st.get("topic_ko", project_id)
    collected_root = cfg.project_collected_dir(project_id)
    proj_e_ev = cfg.project_e_evidence_dir(project_id)
    proj_e_ev.mkdir(parents=True, exist_ok=True)
    ws_col = cfg.project_dir(project_id) / "collected"
    ws_col.mkdir(parents=True, exist_ok=True)

    # 국내 기상·공공포털·KOSIS는 01_domestic_agencies, OpenWeatherMap/글로벌 통계는 03_international_agencies
    tier_key = "international_agencies" if source_kind in ("openweathermap", "worldbank_api") else "domestic_agencies"
    tier_dir = collected_root / TIER_DIRS[tier_key]
    tier_dir.mkdir(parents=True, exist_ok=True)
    # 데이터 원본(CSV/JSON) 전용 하위 폴더에도 별도 보관
    api_downloads_dir = collected_root / "05_api_weather_stats_downloads"
    api_downloads_dir.mkdir(parents=True, exist_ok=True)

    full_md = markdown_text
    if user_prompt_note and user_prompt_note.strip():
        full_md += f"\n\n## 사용자 추가 요청 프롬프트 및 활용 메모\n\n{user_prompt_note.strip()}\n"

    cleaned_md, pii_count = mask_pii(full_md)
    content_hash = sha256_text(cleaned_md)
    registry = SourcesRegistry(cfg.sources_registry_path)
    sid = registry.next_source_id()
    slug = slugify(f"{source_kind}_{title}", 48)

    parsed_path = cfg.parsed_dir / f"{sid}_{slug}.md"
    parsed_path.write_text(cleaned_md, encoding="utf-8")

    # 분리 폴더(01 또는 03) + 05_api_weather_stats_downloads 동시 저장
    saved_files: list[str] = []
    dst_md = tier_dir / parsed_path.name
    shutil.copy2(parsed_path, dst_md)
    saved_files.append(str(dst_md))
    shutil.copy2(parsed_path, api_downloads_dir / parsed_path.name)

    csv_path_str = ""
    json_path_str = ""
    if rows:
        use_cols = columns or list(rows[0].keys())
        csv_text = rows_to_csv_text(use_cols, rows)
        csv_p = api_downloads_dir / f"{sid}_{slug}.csv"
        csv_p.write_text("\ufeff" + csv_text, encoding="utf-8")
        csv_path_str = str(csv_p)
        saved_files.append(csv_path_str)

        json_p = api_downloads_dir / f"{sid}_{slug}.json"
        json_p.write_text(json.dumps({"title": title, "source_kind": source_kind, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        json_path_str = str(json_p)
        saved_files.append(json_path_str)

    chunks = chunk_korean_text(cleaned_md, default_section=title[:60])
    now = utc_now_iso()
    source_item = {
        "source_id": sid,
        "source_type": "web",
        "url": url,
        "title": title,
        "accessed_at": now,
        "robots_allowed": True,
        "robots_status": f"official_api ({source_kind})",
        "license_note": license_note,
        "page_or_section": source_kind,
        "raw_path": csv_path_str or json_path_str or str(parsed_path),
        "parsed_path": str(parsed_path),
        "pii_masked": True,
        "pii_redaction_count": pii_count,
        "prompt_injection_warnings": [],
        "sha256": content_hash,
        "extracted_facts": [],
        "tables": [],
        "chunks": chunks,
    }
    global_pkt = cfg.evidence_dir / f"{packet_id}.json"
    upsert_evidence_packet(
        packet_path=global_pkt,
        source_item=source_item,
        packet_id=packet_id,
        topic=topic_ko,
        storage_root=str(cfg.collected_data_root),
        kg_store_root=str(cfg.smc_graphrag_root),
        schema_path=cfg.evidence_schema_path,
    )
    shutil.copy2(global_pkt, proj_e_ev / f"{packet_id}.json")

    registry.append(
        {
            "source_id": sid,
            "source_type": "web",
            "scholar_category": source_kind,
            "provider": source_kind,
            "url": url,
            "normalized_url": url,
            "title": title,
            "accessed_at": now,
            "robots_allowed": True,
            "robots_status": source_item["robots_status"],
            "sha256": content_hash,
            "raw_path": source_item["raw_path"],
            "parsed_path": str(parsed_path),
            "packet_path": str(global_pkt),
            "parser_engine": f"explorer_{source_kind}",
            "chunk_count": len(chunks),
            "table_count": 1 if rows else 0,
        }
    )

    # 프로젝트 state.json & collection_manifest.json 동기화
    existing_sources = list(st.get("collected_sources") or [])
    existing_sources.append(
        {
            "source_id": sid,
            "tier": tier_key,
            "tier_folder": TIER_DIRS[tier_key],
            "tier_label": source_kind,
            "title": title,
            "journal": source_kind,
            "year": datetime.now().year,
            "cited_by_count": 0,
            "url": url,
            "provider": f"데이터탐색({source_kind})",
            "status": "OK",
            "saved_files": saved_files,
        }
    )
    breakdown = {k: sum(1 for s in existing_sources if s.get("tier") == k) for k in TIER_DIRS}
    st["collected_sources"] = existing_sources
    st["collection_breakdown"] = {**breakdown, "total": len(existing_sources)}
    save_project_state(st, cfg)

    manifest_path = collected_root / "collection_manifest.json"
    prev_m = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "topic_en": st.get("topic_en", topic_ko),
        "preset": prev_m.get("preset", "custom"),
        "generated_at": now,
        "collected_root": str(collected_root),
        "tier_directories": {k: str(collected_root / v) for k, v in TIER_DIRS.items()},
        "api_downloads_dir": str(api_downloads_dir),
        "global_evidence_path": str(global_pkt),
        "project_evidence_path": str(proj_e_ev / f"{packet_id}.json"),
        "packet_id": packet_id,
        "total_collected": len(existing_sources),
        "pdf_downloaded_count": prev_m.get("pdf_downloaded_count", 0),
        "breakdown": breakdown,
        "source_ids": [s["source_id"] for s in existing_sources if s.get("source_id")],
        "sources": existing_sources,
        "blocked_or_failed": prev_m.get("blocked_or_failed", []),
    }
    m_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    manifest_path.write_text(m_json, encoding="utf-8")
    (ws_col / "collection_manifest.json").write_text(m_json, encoding="utf-8")
    _write_collection_index_md(manifest, collected_root / "INDEX.md")
    _write_collection_index_md(manifest, ws_col / "INDEX.md")

    append_event(
        project_id,
        "data-explorer",
        "stage2_web_scout",
        f"데이터 탐색 저장 완료 [{sid}] {title} (CSV/MD 분리 폴더 저장: {api_downloads_dir.name})",
        cfg=cfg,
    )

    kg_delta = None
    if also_ingest_rag:
        from build_platform_kg import build_knowledge_graph_from_sources

        kg_model = st.get("options", {}).get("kg_model") or cfg.ollama_fast_model
        append_event(project_id, "kg-builder", "stage3_kg_builder", f"[{sid}] 데이터 탐색 결과 RAG(C:\\SMC_GRAPHRAG) 증분 적재 시작...", cfg=cfg)
        kg_res = build_knowledge_graph_from_sources(source_ids=[sid], model=kg_model, cfg=cfg)
        kg_delta = {
            "nodes_added": kg_res.get("nodes_after", 0) - kg_res.get("nodes_before", 0),
            "edges_added": kg_res.get("edges_after", 0) - kg_res.get("edges_before", 0),
            "nodes_after": kg_res.get("nodes_after", 0),
            "edges_after": kg_res.get("edges_after", 0),
            "lightrag_server_online": kg_res.get("lightrag_server_online", False),
        }
        append_event(
            project_id,
            "kg-builder",
            "stage3_kg_builder",
            f"[{sid}] RAG 증분 완료: +{kg_delta['nodes_added']}노드 / +{kg_delta['edges_added']}관계",
            cfg=cfg,
        )

    return {
        "status": "OK",
        "source_id": sid,
        "title": title,
        "saved_files": saved_files,
        "csv_path": csv_path_str,
        "json_path": json_path_str,
        "md_path": str(dst_md),
        "total_project_sources": len(existing_sources),
        "rag_ingested": bool(kg_delta),
        "rag_delta": kg_delta,
    }


def synthesize_explorer_prompt(
    *,
    project_id: str,
    prompt_text: str,
    checked_sources: list[str],
    attached_datasets: list[dict[str, Any]],
    use_claude: bool = False,
    gemma_model: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """데이터 탐색 페이지의 '추가 요청 사항 프롬프트'를 바탕으로 선택된 실측/API 데이터를 교재용 분석 리포트로 정리한다."""
    cfg = cfg or get_config()
    from subagent_orchestrator import _run_claude_code_stream, load_project_state

    st = load_project_state(project_id, cfg) or {}
    topic_ko = st.get("topic_ko", project_id)

    data_digest_parts: list[str] = []
    for ds in attached_datasets[:6]:
        data_digest_parts.append(f"### {ds.get('title', '데이터셋')}\n{(ds.get('markdown') or '')[:2200]}")
    digest = "\n\n".join(data_digest_parts) or "(첨부된 조회 결과 없음 — 일반 주제 맥락으로 분석)"

    full_prompt = (
        f"교재 프로젝트 주제: 《{topic_ko}》\n"
        f"체크된 탐색 데이터 소스: {', '.join(checked_sources)}\n"
        f"사용자 추가 요청 프롬프트:\n{prompt_text}\n\n"
        f"[실측·API 조회 데이터 발췌]\n{digest}\n\n"
        "위 실측 데이터와 요청 사항을 바탕으로 교재 집필 및 RAG 적재에 바로 활용할 수 있는 "
        "한국어 구조화 분석 리포트(핵심 수치 요약, 비교 해석, 교재 반영 포인트, 추가 권장 조사 항목)를 마크다운으로 작성해 주세요."
    )

    engine_used = "fallback"
    synthesis = ""
    if use_claude:
        ok, cl_out = _run_claude_code_stream(
            project_id=project_id,
            agent_name="data-explorer",
            stage_id="stage2_web_scout",
            prompt=full_prompt,
            cfg=cfg,
            timeout_sec=150,
        )
        if ok and cl_out:
            synthesis = cl_out
            engine_used = "claude_code"

    if not synthesis:
        try:
            from local_gemma import LocalGemmaClient

            mdl = gemma_model or st.get("options", {}).get("gemma_model") or cfg.ollama_fast_model
            synthesis = LocalGemmaClient(cfg).draft_text(
                system_prompt="당신은 농학·기상·통계 데이터 분석 및 전문 교재 집필 보조 AI입니다. 제공된 실측 수치만 정확히 인용해 한국어 마크다운 리포트를 작성하세요.",
                user_prompt=full_prompt,
                model=mdl,
                think=False,
                num_predict=2048,
                timeout=180,
            )
            engine_used = mdl
        except Exception as exc:
            synthesis = f"# 데이터 탐색 프롬프트 정리 ({topic_ko})\n\n- 요청: {prompt_text}\n- 체크 소스: {', '.join(checked_sources)}\n- 참고: LLM 요약 중 예외({exc}) 발생으로 원본 데이터 발췌를 보존합니다.\n\n{digest[:3000]}"

    return {
        "status": "OK",
        "engine_used": engine_used,
        "title": f"[프롬프트 분석 리포트] {prompt_text[:55]}",
        "markdown": synthesis,
    }
