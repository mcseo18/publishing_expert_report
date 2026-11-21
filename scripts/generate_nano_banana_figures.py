"""나노바나나(Nano Banana: Gemini Image Generation API) 기반 교재 사진·과학 일러스트 생성 모듈.

사용 모델 (Google Gemini API — google-genai SDK):
- 기본: gemini-2.5-flash-image (Nano Banana)
- 고화질/프로 옵션: gemini-3.1-flash-image-preview / imagen-3.0-generate-002

환경변수:
- GEMINI_API_KEY (또는 GOOGLE_API_KEY)가 .env 에 설정되어 있으면 API로 직접 이미지 생성
- API 키 미설정 시 프롬프트 매니페스트(content/assets/nano_banana_prompts.json)를 생성하고
  Antigravity image-generator 서브에이전트와 연동 가능한 표준 규격을 유지한다.

사용 예:
    .venv\\Scripts\\python.exe scripts\\generate_nano_banana_figures.py --list
    .venv\\Scripts\\python.exe scripts\\generate_nano_banana_figures.py --chapter ch01
    .venv\\Scripts\\python.exe scripts\\generate_nano_banana_figures.py --all --model gemini-2.5-flash-image
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from config import PlatformConfig, get_config

# 교재 핵심 장별 나노바나나(Nano Banana) 과학·사진 도해 프롬프트 카탈로그
NANO_BANANA_FIGURE_SPECS: list[dict[str, Any]] = [
    {
        "figure_id": "fig_ch01_som_pom_maom",
        "chapter_id": "ch01",
        "filename": "fig_ch01_som_pom_maom.png",
        "caption_ko": "그림 1-1. 입자성 유기물(POM, 좌)과 점토·미사 표면 광물결합 유기물(MAOM, 우)의 미시적 결합 구조 개념도 [SRC-04, SRC-05, SRC-06, SRC-10]",
        "prompt": (
            "Publication-grade scientific textbook cross-section illustration on a clean white background showing "
            "Particulate Organic Matter (POM: amber plant fragments and fungal hyphae in soil pores, left) vs "
            "Mineral-Associated Organic Matter (MAOM: molecular organic films tightly bound to blue-grey clay mineral platelets, right). "
            "Nature journal scientific style, NO text or letters."
        ),
    },
    {
        "figure_id": "fig_ch04_aggregate_hierarchy",
        "chapter_id": "ch04",
        "filename": "fig_ch04_aggregate_hierarchy.png",
        "caption_ko": "그림 4-1. 토양 대단립(>250 μm) 및 소단립(53~250 μm) 계층 구조 내 균근균 균사·뿌리털·부식질 결합 단면도 [SRC-03, SRC-42, SRC-44]",
        "prompt": (
            "Detailed scientific cross-section of a healthy soil macroaggregate (>250 um) on white background, "
            "showing microaggregates bound by golden-white arbuscular mycorrhizal fungal hyphae, root hairs, and humus bridges "
            "with clear water/air pores. Editorial biology illustration style, NO text or labels."
        ),
    },
    {
        "figure_id": "fig_ch14_biochar_rhizosphere",
        "chapter_id": "ch14",
        "filename": "fig_ch14_biochar_rhizosphere.png",
        "caption_ko": "그림 14-1. 다공성 바이오차(Biochar) 미세공극 내 수분·양분 흡착 및 근권 미생물·작물 뿌리 상호작용 단면 도해 [SRC-36, SRC-38, SRC-79]",
        "prompt": (
            "High-resolution scientific cutaway illustration on white background showing porous honeycomb black biochar particle "
            "in dark brown soil, colonized by rhizosphere bacteria and mycorrhizal hyphae with water and mineral ions next to a crop root hair. "
            "Modern photorealistic scientific illustration, NO text or labels."
        ),
    },
    {
        "figure_id": "fig_ch15_soil_profiles",
        "chapter_id": "ch15",
        "filename": "fig_ch15_soil_profiles.png",
        "caption_ko": "그림 15-1. 주요 토양 생태계(농경지 광질토·화산회토 Andosol·이탄지 Histosol·산림토양) 1 m 토양 단면 비교 [SRC-06, SRC-51, SRC-80, SRC-81]",
        "prompt": (
            "Clean scientific textbook vertical 1-meter soil monolith comparison side by side on white background: "
            "(1) agricultural mineral loam topsoil/subsoil, (2) deep black volcanic Andosol, (3) wet fibrous peatland Histosol, "
            "(4) forest soil with organic O-horizon and deep roots. Museum soil monolith illustration style, NO text."
        ),
    },
]


def generate_with_nano_banana_api(
    spec: dict[str, Any],
    out_path: Path,
    model: str = "gemini-2.5-flash-image",
) -> dict[str, Any]:
    """google-genai SDK를 통해 나노바나나(Gemini Image) 모델로 이미지를 직접 생성한다."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {
            "figure_id": spec["figure_id"],
            "status": "SKIPPED_NO_API_KEY",
            "note": ".env 에 GEMINI_API_KEY 를 설정하거나 Antigravity image-generator 서브에이전트로 생성하세요.",
            "out_path": str(out_path),
            "exists": out_path.is_file(),
        }

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=spec["prompt"],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            raw = inline.data if isinstance(inline.data, bytes) else base64.b64decode(inline.data)
            out_path.write_bytes(raw)
            return {
                "figure_id": spec["figure_id"],
                "status": "GENERATED_VIA_NANO_BANANA",
                "model": model,
                "out_path": str(out_path),
                "bytes": len(raw),
            }
    return {"figure_id": spec["figure_id"], "status": "NO_IMAGE_RETURNED", "model": model}


def write_manifest(cfg: PlatformConfig | None = None) -> Path:
    cfg = cfg or get_config()
    fig_dir = cfg.assets_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for spec in NANO_BANANA_FIGURE_SPECS:
        fp = fig_dir / spec["filename"]
        manifest.append(
            {
                **spec,
                "file_path": str(fp),
                "exists": fp.is_file(),
                "size_bytes": fp.stat().st_size if fp.is_file() else 0,
            }
        )
    mpath = cfg.assets_dir / "nano_banana_manifest.json"
    mpath.write_text(json.dumps({"figures": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    return mpath


def main() -> int:
    parser = argparse.ArgumentParser(description="나노바나나(Nano Banana) 교재 과학 일러스트 생성기")
    parser.add_argument("--list", action="store_true", help="등록된 도해 목록 및 생성 여부 확인")
    parser.add_argument("--chapter", default="", help="특정 단원만 생성 (예: ch01)")
    parser.add_argument("--all", action="store_true", help="모든 나노바나나 도해 생성")
    parser.add_argument("--model", default="gemini-2.5-flash-image", help="나노바나나 모델명 (기본 gemini-2.5-flash-image)")
    parser.add_argument("--force", action="store_true", help="기존 이미지 덮어쓰기")
    args = parser.parse_args()

    cfg = get_config()
    fig_dir = cfg.assets_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    if args.list or (not args.chapter and not args.all):
        mpath = write_manifest(cfg)
        print(mpath.read_text(encoding="utf-8"))
        return 0

    targets = [
        s for s in NANO_BANANA_FIGURE_SPECS if args.all or s["chapter_id"] == args.chapter
    ]
    results = []
    for spec in targets:
        fp = fig_dir / spec["filename"]
        if fp.is_file() and not args.force:
            results.append({"figure_id": spec["figure_id"], "status": "ALREADY_EXISTS", "out_path": str(fp)})
            continue
        results.append(generate_with_nano_banana_api(spec, fp, model=args.model))

    write_manifest(cfg)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
