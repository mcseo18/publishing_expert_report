"""교재 단원당 10개 이상 시각화 자료 자동 설계·생성 스튜디오 (Stage 5 visual-artist).

지원 생성 엔진:
1. fal.ai API (`FAL_KEY` + 사용자 체크박스 ON 시):
   - 모델 선택: `fal-ai/nano-banana`, `fal-ai/flux/schnell`, `fal-ai/flux-pro/v1.1`
   - 실사진(photorealistic) 및 고해상도 과학 인포그래픽 PNG/JPG 생성
2. Google Gemini 나노바나나(Nano Banana) API (`GEMINI_API_KEY` 설정 시):
   - `gemini-2.5-flash-image` 기반 과학 단면도·현장 실사진 생성
3. 고해상도 한글 벡터 SVG 차트·다이어그램 엔진 (무인증·항시 가동):
   - 비교 막대 차트, 프로세스 흐름도, 생육/단계 타임라인, 매트릭스 도해 등 출판급 SVG 생성
4. 모든 시각화 자료는 별도 표 없이 [그림 N-K] 제목 + 자연스러운 줄글 텍스트 해설(`visuals_text_guide.md`)로 저장한다.
5. 이미지 1건 완료마다 체크포인트 콜백을 호출해 중간 중단 시 미생성 항목부터 정확히 이어서 생성한다.
"""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any, Callable

import requests

from compliance import utc_now_iso
from config import PlatformConfig, get_config
from data_connectors import resolve_api_key

FONT = "'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif"

ZERO_TEXT_RULE = (
    "STRICT REQUIREMENT: Pure visual photography or text-free scientific illustration ONLY. "
    "Absolutely ZERO text, ZERO words, ZERO letters, ZERO numbers, ZERO Korean Hangul, ZERO English labels, "
    "ZERO titles, ZERO captions, ZERO logos, ZERO tablet/monitor screens, ZERO signboards, ZERO watermarks anywhere in the image."
)

# 작물/분야 국문 -> 순수 영문 시각 주체 매핑 (긴 복합 작물명 우선; 1글자 작물명 '밀/벼/쌀/콩'은 비작물 복합어 제외 후 경계 매칭)
NON_CROP_COMPOUND_MASK = (
    "정밀", "밀도", "밀식", "치밀", "긴밀", "과밀", "밀착", "밀폐", "기밀", "비밀", "밀접", "밀집", "밀어", "밀리",
    "재배", "무경운", "실무", "전파", "파종", "파괴", "주파", "선별", "선배", "배수", "배양", "배유", "분배",
)

CROP_SUBJECT_MAP: list[tuple[tuple[str, ...], str, str]] = [
    (("옥수수", "단옥수수", "찰옥수수", "사료용 옥수수", "corn", "maize", "zea mays"),
     "tall green maize corn (Zea mays) plants with broad arching leaves, golden tassels, and developing ears with silky husks in neat agricultural rows",
     "mature maize corn (Zea mays) plant showing brace prop roots, nodal stalk, broad parallel-veined C4 leaves, apical tassel, and longitudinal cross-section of a golden kernel cob ear"),
    (("고구마", "sweet potato", "ipomoea batatas"),
     "sweet potato (Ipomoea batatas) plants with lush heart-shaped green vines and rich reddish-purple orange storage roots",
     "sweet potato (Ipomoea batatas) plant showing leafy vines, fibrous feeder roots, and cross-section of a fleshy orange-red storage tuberous root"),
    (("감자", "씨감자", "potato", "solanum tuberosum"),
     "potato (Solanum tuberosum) plants with green compound foliage and clean golden-brown tubers in dark soil",
     "potato (Solanum tuberosum) plant showing stems, stolons, fibrous roots, and developing underground tubers"),
    (("보리", "맥류", "barley", "hordeum vulgare"),
     "barley (Hordeum vulgare) crop field with dense green stems and long-awned ripening spikes",
     "barley (Hordeum vulgare) plant showing fibrous root system, tillers, culm, and long-awned grain spike"),
    (("대두", "콩", "soybean", "glycine max"),
     "soybean (Glycine max) plants with lush trifoliate green leaves and clustered hairy pods along sturdy stems",
     "soybean (Glycine max) plant showing nitrogen-fixing root nodules, trifoliate leaves, stem nodes, and cross-section of developing seed pods"),
    (("고추", "pepper", "capsicum"),
     "red chili pepper (Capsicum annuum) plants cultivated on mulched agricultural ridges laden with glossy green and crimson fruits",
     "pepper (Capsicum annuum) plant showing taproot zone, branching stems, white blossoms, and longitudinal cross-section of a fruit"),
    (("배추", "napa cabbage", "brassica rapa"),
     "napa cabbage (Brassica rapa) heading crops neatly arranged in raised mulched Korean farm beds",
     "napa cabbage (Brassica rapa) cross-section showing dense overlapping inner heading leaves, core meristem, and root system"),
    (("마늘", "garlic", "allium sativum"),
     "garlic (Allium sativum) plants with upright blue-green flat leaves growing in mulched ridges and harvested white bulbs",
     "garlic (Allium sativum) plant showing fibrous roots, subterranean segmented clove bulb cross-section, and pseudostem"),
    (("양파", "onion", "allium cepa"),
     "onion (Allium cepa) plants with tubular green leaves and round golden-skinned bulbs emerging from loamy soil",
     "onion (Allium cepa) plant showing concentric fleshy bulb scales in cross-section, basal plate, and fibrous roots"),
    (("딸기", "strawberry", "fragaria"),
     "strawberry (Fragaria x ananassa) plants in elevated smart greenhouse beds with white blossoms and glossy red berries",
     "strawberry (Fragaria x ananassa) plant showing crown, runners, trifoliate leaves, root zone, and fruit cross-section"),
    (("토마토", "tomato", "solanum lycopersicum"),
     "greenhouse tomato (Solanum lycopersicum) vines trained on trellises with ripening red fruit clusters",
     "tomato (Solanum lycopersicum) plant showing root system, compound leaves, flowering truss, and fruit cross-section"),
    (("사과", "과수원", "apple", "malus domestica"),
     "Korean apple orchard (Malus domestica) rows with leafy canopies and ripening red apples above grass-covered orchard floor",
     "apple (Malus domestica) fruiting spur showing leaves, flower bud, and cross-section of an apple fruit"),
    (("잡초", "weed", "herbicide"),
     "Korean agricultural crop field showing competitive annual and perennial weeds emerging between crop rows",
     "botanical comparison of grass, sedge, and broadleaf agricultural weeds showing stem cross-sections and root propagules"),
    (("겨울밀", "우리밀", "밀", "wheat", "triticum"),
     "winter wheat (Triticum aestivum) stalks with green flag leaves and ripening golden spikes",
     "mature winter wheat (Triticum aestivum) plant showing fibrous root system, crown, tillers, hollow culm, leaf sheath, and ripening grain spike"),
    (("벼", "수도작", "쌀", "rice", "oryza sativa"),
     "paddy rice (Oryza sativa) plants with lush green leaves and drooping golden panicles in a flooded field",
     "rice (Oryza sativa) plant showing flooded paddy root zone, tillers, culms, leaf ligule-auricle junction, and grain panicle structure"),
    (("토양", "유기물", "soil"),
     "fertile dark crumbly agricultural topsoil profile with healthy crop roots and earthworm channels",
     "layered agricultural soil profile showing organic matter aggregates, clay minerals, mycorrhizal hyphae, and root hairs"),
    (("수확 후", "저장", "postharvest"),
     "freshly harvested agricultural produce inside a clean modern temperature-controlled postharvest facility",
     "cutaway illustration of a controlled-atmosphere postharvest cold storage and curing room"),
]


def _match_crop_key(key: str, text_blob: str) -> bool:
    """1글자 국문 작물명('밀'·'벼'·'쌀'·'콩')이 '정밀재배'·'밀도' 같은 비작물 복합어에 오매칭되지 않도록 정밀 검사한다."""
    k = key.lower().strip()
    if not k:
        return False
    # 영문 키워드는 단어 경계 매칭
    if re.fullmatch(r"[a-z0-9 \-]+", k):
        return bool(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", text_blob))
    # 2글자 이상 국문 키워드는 직접 매칭
    if len(k) >= 2:
        return k in text_blob
    # 1글자 국문 작물명('밀', '벼', '쌀', '콩'): 비작물 복합어를 먼저 마스킹한 뒤 독립 어절/작물 복합어만 허용
    masked = text_blob
    for comp in NON_CROP_COMPOUND_MASK:
        masked = masked.replace(comp, " ")
    # 앞이 공백/문장시작/구두점이고 뒤가 공백/구두점/조사/재배/품종/이삭/생산/수확 등인 경우에만 매칭
    return bool(re.search(rf"(?:^|[\s·,:/\(\)\[\]《》\-]){re.escape(k)}(?:$|[\s·,:/\(\)\[\]《》\-의은는이가을를과와도에서로]|재배|품종|농사|생산|수확|이삭|알곡|가루|전분|밭|논|작물)", masked))

# 단원 세부 주제(한국어 키워드) -> {crop_field} / {crop_bot} 슬롯을 조합하는 범용 영문 장면 템플릿
CHAPTER_THEME_SCENES: list[tuple[tuple[str, ...], str, str]] = [
    (("기초", "분류", "생물학", "생리", "품종군", "생육 주기"), "{crop_field} thriving in a sunlit agricultural research station field plot at golden hour", "botanical anatomical cross-section of {crop_bot} on pure white background"),
    (("품종", "유전", "종자", "육종", "씨고구마", "묘"), "diverse cultivars and propagation specimens of {crop_field} neatly arranged on an agronomy research inspection bench in natural daylight", "clean scientific botanical comparison of diverse cultivars and internal tissue cross-sections of {crop_bot} on pure white background"),
    (("토양", "파종", "정식", "이랑", "멀칭"), "precision planting and raised soil beds prepared for {crop_field} in dark fertile loam soil at an experimental farm", "clean soil profile cross-section showing dark fertile soil beds, root zone moisture, and early rooting of {crop_bot} on pure white background"),
    (("월동", "초기", "동해", "활착"), "young vigorous seedlings of {crop_field} established across neat mulched agricultural ridges in crisp morning sunlight", "clean botanical illustration of early root establishment and protective soil microclimate for {crop_bot} on pure white background"),
    (("분얼", "분화", "덩이뿌리", "괴근", "비대", "중기"), "vigorous mid-season canopy and developing yield organs of {crop_field} across uniform experimental field plots", "clean botanical developmental sequence showing vegetative growth and storage/reproductive organ formation in {crop_bot} on pure white background"),
    (("양분", "분배", "생육모형", "질소", "시비", "비료"), "precision fertilization research plots of {crop_field} showing lush healthy foliage and vigorous crop growth under clear daylight", "clean Nature-style botanical cross-section of {crop_bot} showing glowing blue and amber nutrient transport pathways moving from soil roots through stems and leaves into storage organs on pure white background"),
    (("병해충", "잡초", "바이러스", "녹병", "방제"), "close-up agronomic field inspection of healthy leaves alongside plant pathology diagnostic observation in {crop_field}", "clean scientific botanical illustration contrasting healthy leaf and root tissue of {crop_bot} with pathogen defense mechanisms on pure white background"),
    (("스트레스", "가뭄", "고온", "수분", "관개"), "modern precision drip and sprinkler irrigation watering a sunlit field of {crop_field} with fine water droplets", "clean plant-soil-atmosphere scientific illustration showing root water uptake and drip moisture distribution around {crop_bot} on pure white background"),
    (("수확", "큐어링", "건조", "저장"), "modern agricultural harvesting and clean curing-storage handling of freshly harvested {crop_field} under bright daylight", "clean cutaway engineering illustration of a controlled temperature and humidity curing and storage facility holding harvested {crop_field} on pure white background"),
    (("품질", "단백질", "전분", "당도", "비파괴", "평가"), "clean agricultural food quality laboratory workbench with samples of {crop_field} in glass inspection dishes beside an optical near-infrared analyzer", "clean microscopic cross-section illustration of internal cellular starch granules and nutrient storage tissues of {crop_bot} on pure white background"),
    (("글로벌", "세계", "유통", "시장", "경제", "공급망"), "aerial panoramic view of expansive sunlit farmland growing {crop_field} beside modern agricultural distribution facilities", "clean isometric editorial illustration showing harvest transport from sunlit farmland of {crop_field} to modern cold storage and distribution center on pure white background"),
    (("가공", "제분", "제빵", "면류", "기능성", "산업"), "clean artisanal and modern food processing showcase featuring freshly harvested {crop_field} and refined culinary ingredients on a wooden studio table", "clean scientific cross-section illustration of cellular starch and dietary fiber matrix derived from {crop_bot} on pure white background"),
    (("디지털", "트윈", "인공지능", "원격", "드론", "스마트", "센서", "자동화"), "agricultural multispectral quadcopter drone flying above lush rows of {crop_field} during precision crop monitoring at sunrise", "clean isometric scientific illustration showing satellite orbit, agricultural drone, soil sensors, and sunlit field rows of {crop_field} connected by subtle light rays on pure white background"),
    (("저탄소", "탄소", "지속 가능", "친환경", "기후"), "regenerative conservation farmland growing healthy {crop_field} with organic mulch and dark carbon-rich soil", "clean ecosystem cross-section showing atmospheric carbon captured by green foliage of {crop_bot} and stored deep in dark organic-rich soil on pure white background"),
    (("미래", "유전자", "미생물", "로봇", "융합"), "modern glass smart agricultural research greenhouse cultivating experimental {crop_field} under precision LED lighting", "clean microscopic rhizosphere illustration showing beneficial golden soil bacteria and white mycorrhizal fungal hyphae around roots of {crop_bot} on pure white background"),
]

# 단원당 기본 주장 기반 시각화 아키타입 (V1·V2: 가짜 수치 막대/곡선 틀 완전 제거, 3~6장 권장)
CHAPTER_VISUAL_TEMPLATES: list[dict[str, str]] = [
    {
        "slot": "v01",
        "kind": "photo_ai",
        "style": "photorealistic",
        "role_ko": "장 도입 · 현장 관찰 실사",
        "prompt_tmpl": "Ultra-realistic documentary agricultural photograph of {field_scene}, crisp natural daylight, field research station quality, accurate botanical morphology, shallow depth of field. {zero_text}",
    },
    {
        "slot": "v02",
        "kind": "svg_flow",
        "style": "content_diagram",
        "role_ko": "원고 내용 기반 구조·피드백 도해",
        "prompt_tmpl": "",
    },
    {
        "slot": "v03",
        "kind": "photo_ai",
        "style": "photorealistic_macro",
        "role_ko": "근접 형태·조직 관찰 실사",
        "prompt_tmpl": "High-resolution macro scientific photography closely capturing {macro_scene}, true-to-life botanical color, crisp natural texture, laboratory diagnostic clarity. {zero_text}",
    },
    {
        "slot": "v04",
        "kind": "svg_layers",
        "style": "layered_comparison",
        "role_ko": "원고 내용 기반 계층·비교 도해",
        "prompt_tmpl": "",
    },
]


def _resolve_english_visual_scenes(topic_ko: str, topic_en: str, chapter: dict[str, Any]) -> tuple[str, str, str]:
    """한글 주제·단원 제목을 해당 작물/분야에 맞는 순수 영문 시각 장면으로 변환한다 (정밀재배→밀 오매칭 완전 차단)."""
    topic_blob = f"{topic_ko} {topic_en}".lower()
    crop_field = ""
    crop_bot = ""
    for keys, cf, cb in CROP_SUBJECT_MAP:
        if any(_match_crop_key(k, topic_blob) for k in keys):
            crop_field, crop_bot = cf, cb
            break
    if not crop_field:
        base_en = re.sub(r"[^A-Za-z0-9 ,\-]", "", topic_en or "").strip() or "precision agricultural crops"
        crop_field = f"{base_en} crops in a sunlit experimental agricultural field"
        crop_bot = f"{base_en} plant showing roots, stems, leaves, and yield organs"

    ch_blob = " ".join([
        str(chapter.get("title", "")),
        str(chapter.get("summary_ko", "")),
        " ".join(chapter.get("sections") or []),
    ])
    for keys, field_tmpl, diag_tmpl in CHAPTER_THEME_SCENES:
        if any(k in ch_blob for k in keys):
            field_s = field_tmpl.format(crop_field=crop_field, crop_bot=crop_bot)
            diag_s = diag_tmpl.format(crop_field=crop_field, crop_bot=crop_bot)
            macro_s = f"close-up botanical detail of {crop_field}"
            return field_s, diag_s, macro_s

    field_s = f"{crop_field} in a sunlit experimental agricultural research field"
    diag_s = f"clean botanical cross-section illustration of {crop_bot} on pure white background"
    macro_s = f"macro close-up of healthy botanical tissues and soil structure of {crop_field}"
    return field_s, diag_s, macro_s


def _clean_svg_label(text: str) -> str:
    """SVG 박스 내부 라벨에서 과도한 영문 괄호 부연설명을 정리해 한글 가독성을 높인다."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    # 긴 영문 괄호 (예: (Critical N Dilution Curve)) 제거, 짧은 약어 (예: (NNI), (N·P·K·S))는 유지
    s = re.sub(r"\s*\([A-Za-z][A-Za-z0-9\s\-/,·]{7,}\)", "", s)
    return s.strip()


def _wrap_svg_lines(text: str, max_chars: int = 13, max_lines: int = 3) -> list[str]:
    """단어·공백 경계를 엄격히 지켜 줄바꿈한다 (단어나 영문 약어 중간 잘림 방지)."""
    s = _clean_svg_label(text)
    if not s:
        return [""]
    words = s.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur = cur + " " + w
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # 혹시 단일 어절 자체가 max_chars보다 훨씬 길면 구분자(·, /) 기준으로 깔끔히 줄임
    out: list[str] = []
    for ln in lines[:max_lines]:
        if len(ln) > max_chars + 3:
            cut = ln[: max_chars + 1]
            for sep in (" ", "·", "/", ","):
                if sep in cut and cut.rfind(sep) >= max_chars // 2:
                    cut = cut[: cut.rfind(sep)]
                    break
            ln = cut.rstrip(" (·,/") + "…"
        # 닫히지 않은 괄호 제거
        if ln.count("(") > ln.count(")"):
            ln = re.sub(r"\([^)]*$", "", ln).strip()
        out.append(ln)
    return out or [s[:max_chars]]


def _svg_multiline_text(
    x: float,
    y_center: float,
    lines: list[str],
    *,
    font_size: float = 12,
    line_height: float = 17,
    fill: str = "#0f172a",
    weight: str = "700",
    anchor: str = "middle",
) -> str:
    n = len(lines)
    y0 = y_center - ((n - 1) * line_height) / 2.0
    tspans = []
    for i, ln in enumerate(lines):
        tspans.append(f'<tspan x="{x}" y="{y0 + i * line_height:.1f}">{html.escape(ln)}</tspan>')
    return f'<text text-anchor="{anchor}" font-size="{font_size}" font-weight="{weight}" fill="{fill}">{"".join(tspans)}</text>'


def _generate_with_fal_ai(
    *,
    prompt: str,
    out_path: Path,
    fal_model: str = "fal-ai/nano-banana",
    api_key: str,
) -> tuple[bool, str]:
    """fal.ai REST API(`https://fal.run/<model>`)로 사실적 실사진/인포그래픽 이미지를 생성한다."""
    model_slug = (fal_model or "fal-ai/nano-banana").strip().lstrip("/")
    url = f"https://fal.run/{model_slug}"
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "prompt": prompt,
        "num_images": 1,
    }
    if "flux" in model_slug:
        payload["image_size"] = "landscape_16_9"
    else:
        payload["aspect_ratio"] = "16:9"

    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    images = data.get("images") or ([] if not data.get("image") else [data["image"]])
    if not images:
        return False, "fal.ai 응답에 이미지 URL이 없습니다."
    img_url = images[0].get("url") if isinstance(images[0], dict) else str(images[0])
    if not img_url:
        return False, "fal.ai 이미지 URL 비어 있음"
    img_r = requests.get(img_url, timeout=45)
    img_r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_r.content)
    return True, f"fal.ai ({model_slug})"


def _generate_with_nano_banana(
    *,
    prompt: str,
    out_path: Path,
    model: str = "gemini-2.5-flash-image",
    api_key: str,
) -> tuple[bool, str]:
    """Google Gemini 저비용 이미지 모델(gemini-2.5-flash-image 기본, Pro는 명시 요청 시만)로 실사진/일러스트를 생성한다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    # 비용 누수 차단: flash 기본 호출 시 고가 Pro(nano-banana-pro-preview)로 자동 에스컬레이션 금지
    if "pro" in (model or "").lower():
        chain = [model, "gemini-2.5-flash-image"]
    else:
        chain = [model] + [m for m in ("gemini-2.5-flash-image", "gemini-3.1-flash-image") if m != model]
    last_err = ""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for mdl in chain:
        try:
            response = client.models.generate_content(
                model=mdl,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in response.candidates[0].content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    raw = inline.data if isinstance(inline.data, bytes) else base64.b64decode(inline.data)
                    out_path.write_bytes(raw)
                    return True, f"Nano Banana ({mdl})"
        except Exception as exc:
            last_err = f"{mdl}: {str(exc)[:90]}"
    return False, last_err or "Gemini 응답에 이미지 바이너리가 없습니다."


def _svg_canvas(title: str, subtitle: str, body: str, accent: str = "#1D3557", source_note: str = "") -> str:
    t_clean = _wrap_svg_lines(title, max_chars=48, max_lines=1)[0]
    s_clean = _wrap_svg_lines(subtitle, max_chars=74, max_lines=1)[0]
    footer = ""
    if source_note:
        sn = _wrap_svg_lines(f"자료: {source_note}", max_chars=86, max_lines=1)[0]
        footer = f'  <text x="30" y="660" font-size="13.5" font-weight="500" fill="#334155">{html.escape(sn)}</text>\n'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 680" width="1200" height="680" '
        f'style="background:#ffffff;font-family:{FONT};">\n'
        f'  <defs>\n'
        f'    <filter id="cardShadow" x="-6%" y="-6%" width="112%" height="116%">\n'
        f'      <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#0f172a" flood-opacity="0.10"/>\n'
        f'    </filter>\n'
        f'    <marker id="ar" viewBox="0 0 18 16" refX="14" refY="8" markerWidth="18" markerHeight="16" orient="auto" markerUnits="userSpaceOnUse">\n'
        f'      <path d="M 1 1.5 L 16.5 8 L 1 14.5 L 4.8 8 Z" fill="#0F172A"/>\n'
        f'    </marker>\n'
        f'    <marker id="ar-green" viewBox="0 0 18 16" refX="14" refY="8" markerWidth="18" markerHeight="16" orient="auto" markerUnits="userSpaceOnUse">\n'
        f'      <path d="M 1 1.5 L 16.5 8 L 1 14.5 L 4.8 8 Z" fill="#047857"/>\n'
        f'    </marker>\n'
        f'  </defs>\n'
        f'  <rect x="1" y="1" width="1198" height="678" rx="14" fill="#ffffff" stroke="#94a3b8" stroke-width="2.2"/>\n'
        f'  <rect x="1" y="1" width="1198" height="92" rx="14" fill="{accent}"/>\n'
        f'  <rect x="1" y="70" width="1198" height="23" fill="{accent}"/>\n'
        f'  <text x="30" y="40" font-size="22" font-weight="700" fill="#ffffff">{html.escape(t_clean)}</text>\n'
        f'  <text x="30" y="70" font-size="15" font-weight="500" fill="#e2e8f0">{html.escape(s_clean)}</text>\n'
        f'  {body}\n'
        f'{footer}'
        f'</svg>'
    )


def _extract_content_nodes_from_spec(spec: dict[str, Any], sections: list[str]) -> list[dict[str, str]]:
    """원고에서 추출한 구조화 노드(nodes)가 있으면 그대로 사용하고, 없으면 절/주장 내용에서 핵심 단계를 구성한다 (V4)."""
    raw_nodes = spec.get("diagram_nodes") or spec.get("nodes") or []
    nodes: list[dict[str, str]] = []
    for i, n in enumerate(raw_nodes[:5], 1):
        if isinstance(n, dict):
            nodes.append(
                {
                    "tag": str(n.get("tag") or f"STEP {i}"),
                    "label": str(n.get("label") or f"단계 {i}"),
                    "detail": str(n.get("detail") or ""),
                    "metric": str(n.get("metric") or ""),
                }
            )
    if nodes:
        return nodes
    # 폴백: 절 제목을 반복 문구 없이 간결한 개념 노드로 정리
    base_secs = [_clean_svg_label(s) for s in (sections[:4] or []) if str(s).strip()]
    for i, s in enumerate(base_secs, 1):
        clean_s = re.sub(r"^\d+(?:\.\d+)*\s*", "", s).strip()
        nodes.append({"tag": f"요소 {i}", "label": clean_s, "detail": spec.get("claim_ko", "")[:34] if i == 1 else "", "metric": ""})
    return nodes


def render_content_diagram_svg(spec: dict[str, Any], sections: list[str] | None = None) -> str:
    """원고 내용 기반 구조도·피드백 흐름도·계층 비교도 SVG를 고가독성·고시인성 규격(1200×680)으로 생성한다 (V2/V4)."""
    style = str(spec.get("style") or "content_diagram")
    if style in ("comparison_bar", "response_curve"):
        raise ValueError(
            f"고정값 차트 틀({style})은 V2 원칙에 따라 삭제되었습니다. "
            "실제 데이터 표/CSV로 academic_plot_style.render_data_chart_png()를 사용하십시오."
        )

    title = str(spec.get("title_ko") or "내용 기반 구조 도해")
    sub = str(spec.get("subtitle_ko") or spec.get("claim_ko") or "")
    source_note = str(spec.get("data_source") or "")
    nodes = _extract_content_nodes_from_spec(spec, sections or [])
    edges = spec.get("diagram_edges") or []
    feedback_label = str(spec.get("feedback_label") or "")

    # Scientific-Figure-Design (qhy991) 시맨틱 팔레트 + Lucide 단일 패밀리 벡터 아이콘 연동
    palette = [
        ("#E0F2FE", "#00629B"),
        ("#DCFCE7", "#047857"),
        ("#FEF3C7", "#C2410C"),
        ("#F3E8FF", "#7C3AED"),
        ("#F1F5F9", "#334155"),
    ]
    _icon_matcher = None
    _icon_loader = None
    try:
        from scientific_figure_engine import load_recolored_lucide_inner_svg, match_lucide_icon_for_text

        _icon_matcher = match_lucide_icon_for_text
        _icon_loader = load_recolored_lucide_inner_svg
    except Exception:
        pass

    def _render_header_icon(x_px: float, y_px: float, probe: str, idx_n: int, size_px: float = 24.0) -> str:
        if not (_icon_matcher and _icon_loader):
            return ""
        ico_id = _icon_matcher(probe, idx=idx_n)
        inner = _icon_loader(ico_id, stroke_color="#FFFFFF", stroke_width=2.1)
        if not inner:
            return ""
        scale = size_px / 24.0
        return (
            f'<g transform="translate({x_px:.1f},{y_px:.1f}) scale({scale:.3f})" '
            f'aria-label="{html.escape(ico_id)}">{inner}</g>'
        )

    if style == "layered_comparison" and len(nodes) >= 2:
        n_cols = min(3, len(nodes))
        col_gap = 26
        col_w = int((1140 - (n_cols - 1) * col_gap) / n_cols)
        parts: list[str] = []
        for idx, nd in enumerate(nodes[:n_cols]):
            bg, bd = palette[idx % len(palette)]
            x = 30 + idx * (col_w + col_gap)
            parts.append(
                f'<rect x="{x}" y="116" width="{col_w}" height="504" rx="14" fill="{bg}" stroke="{bd}" '
                f'stroke-width="2.8" filter="url(#cardShadow)"/>'
            )
            parts.append(f'<rect x="{x}" y="116" width="{col_w}" height="52" rx="14" fill="{bd}"/>')
            parts.append(f'<rect x="{x}" y="150" width="{col_w}" height="18" fill="{bd}"/>')
            ico_svg = _render_header_icon(x + 18, 129, f"{nd['tag']} {nd['label']} {nd.get('detail','')}", idx, size_px=25.0)
            if ico_svg:
                parts.append(ico_svg)
            tag_clean = _wrap_svg_lines(nd["tag"], max_chars=max(10, int((col_w - 64) / 18.5)), max_lines=1)[0]
            parts.append(
                f'<text x="{x + (col_w + 22) / 2:.1f}" y="149" text-anchor="middle" font-size="18.5" font-weight="700" '
                f'fill="#ffffff">{html.escape(tag_clean)}</text>'
            )
            l_lines = _wrap_svg_lines(nd["label"], max_chars=max(10, int((col_w - 38) / 19.5)), max_lines=3)
            parts.append(_svg_multiline_text(x + col_w / 2, 224, l_lines, font_size=19.5, line_height=27, fill="#0f172a", weight="700"))
            parts.append(f'<line x1="{x + 22}" y1="274" x2="{x + col_w - 22}" y2="274" stroke="{bd}" stroke-opacity="0.32" stroke-width="1.6"/>')
            if nd.get("detail"):
                d_lines = _wrap_svg_lines(nd["detail"], max_chars=max(14, int((col_w - 48) / 16.2)), max_lines=6)
                parts.append(
                    _svg_multiline_text(
                        x + 24,
                        394,
                        d_lines,
                        font_size=16.5,
                        line_height=26,
                        fill="#1e293b",
                        weight="500",
                        anchor="start",
                    )
                )
            if nd.get("metric"):
                parts.append(
                    f'<rect x="{x + 18}" y="534" width="{col_w - 36}" height="68" rx="10" fill="#ffffff" '
                    f'stroke="{bd}" stroke-width="2.0"/>'
                )
                m_lines = _wrap_svg_lines(nd["metric"], max_chars=max(14, int((col_w - 50) / 14.5)), max_lines=2)
                parts.append(_svg_multiline_text(x + col_w / 2, 568, m_lines, font_size=16.0, line_height=22, fill=bd, weight="700"))
        return _svg_canvas(title, sub, "\n  ".join(parts), "#1D3557", source_note=source_note)

    # 기본: 내용 기반 프로세스·피드백 루프 흐름도 (V4 — 굵은 화살표·대형 글꼴·고대비 카드)
    n_cnt = max(1, min(4, len(nodes)))
    gap = 68 if n_cnt <= 3 else 62
    box_w = int((1144 - (n_cnt - 1) * gap) / n_cnt)
    box_y = 122 if feedback_label else 128
    box_h = 372 if feedback_label else 468

    parts = []
    arrow_parts: list[str] = []
    for i, nd in enumerate(nodes[:n_cnt]):
        bg, bd = palette[i % len(palette)]
        x = 28 + i * (box_w + gap)
        parts.append(
            f'<rect x="{x}" y="{box_y}" width="{box_w}" height="{box_h}" rx="14" fill="{bg}" stroke="{bd}" '
            f'stroke-width="2.8" filter="url(#cardShadow)"/>'
        )
        parts.append(f'<rect x="{x}" y="{box_y}" width="{box_w}" height="48" rx="14" fill="{bd}"/>')
        parts.append(f'<rect x="{x}" y="{box_y + 32}" width="{box_w}" height="16" fill="{bd}"/>')
        ico_svg = _render_header_icon(x + 14, box_y + 12, f"{nd['tag']} {nd['label']} {nd.get('detail','')}", i, size_px=23.0)
        if ico_svg:
            parts.append(ico_svg)
        tag_clean = _wrap_svg_lines(nd["tag"], max_chars=max(8, int((box_w - 54) / 15.5)), max_lines=1)[0]
        parts.append(
            f'<text x="{x + (box_w + (24 if ico_svg else 0)) / 2:.1f}" y="{box_y + 31}" text-anchor="middle" font-size="16.5" font-weight="700" '
            f'fill="#ffffff">{html.escape(tag_clean)}</text>'
        )
        lbl_y = box_y + (108 if feedback_label else 126)
        l_lines = _wrap_svg_lines(nd["label"], max_chars=max(8, int((box_w - 24) / 18.2)), max_lines=3)
        parts.append(_svg_multiline_text(x + box_w / 2, lbl_y, l_lines, font_size=18.5, line_height=26, fill="#0f172a", weight="700"))
        parts.append(
            f'<line x1="{x + 18}" y1="{lbl_y + 48}" x2="{x + box_w - 18}" y2="{lbl_y + 48}" '
            f'stroke="{bd}" stroke-opacity="0.28" stroke-width="1.5"/>'
        )
        if nd.get("detail"):
            det_y = box_y + (224 if feedback_label else 268)
            d_lines = _wrap_svg_lines(nd["detail"], max_chars=max(10, int((box_w - 26) / 14.8)), max_lines=4 if feedback_label else 6)
            parts.append(_svg_multiline_text(x + box_w / 2, det_y, d_lines, font_size=15.0, line_height=22.5, fill="#1e293b", weight="500"))
        if nd.get("metric"):
            my = box_y + box_h - 60
            parts.append(
                f'<rect x="{x + 12}" y="{my}" width="{box_w - 24}" height="46" rx="9" fill="#ffffff" '
                f'stroke="{bd}" stroke-width="1.9"/>'
            )
            # ASCII 수식/영문 비율이 높을수록 가로 폭을 더 효율적으로 허용
            m_txt = str(nd["metric"])
            ascii_ratio = sum(1 for ch in m_txt if ord(ch) < 128) / max(1, len(m_txt))
            char_px = 10.2 if ascii_ratio >= 0.65 else 13.8
            m_lines = _wrap_svg_lines(m_txt, max_chars=max(12, int((box_w - 34) / char_px)), max_lines=2)
            parts.append(_svg_multiline_text(x + box_w / 2, my + 23, m_lines, font_size=14.5, line_height=19, fill=bd, weight="700"))
        if i < n_cnt - 1:
            ay = box_y + box_h // 2
            ax1 = x + box_w + 4
            ax2 = x + box_w + gap - 6
            # 모든 카드 위에 최상단 Z-순서로 선명한 대형 화살표와 배지를 배치
            arrow_parts.append(f'<line x1="{ax1}" y1="{ay}" x2="{ax2 - 4}" y2="{ay}" stroke="#FFFFFF" stroke-width="10" stroke-linecap="round"/>')
            arrow_parts.append(
                f'<line x1="{ax1}" y1="{ay}" x2="{ax2}" y2="{ay}" stroke="#0F172A" stroke-width="5.0" '
                f'stroke-linecap="round" marker-end="url(#ar)"/>'
            )
            if i < len(edges) and edges[i]:
                elbl = _wrap_svg_lines(str(edges[i]), max_chars=7, max_lines=1)[0]
                cx = x + box_w + gap / 2.0
                bw = max(64, len(elbl) * 14 + 22)
                arrow_parts.append(
                    f'<rect x="{cx - bw / 2:.1f}" y="{ay - 44}" width="{bw}" height="28" rx="14" '
                    f'fill="#FFFFFF" stroke="#0F172A" stroke-width="1.8" filter="url(#cardShadow)"/>'
                )
                arrow_parts.append(
                    f'<text x="{cx:.1f}" y="{ay - 25}" text-anchor="middle" font-size="13.0" font-weight="700" '
                    f'fill="#0F172A">{html.escape(elbl)}</text>'
                )

    parts.extend(arrow_parts)

    if feedback_label and n_cnt >= 2:
        x_start = 28 + (n_cnt - 1) * (box_w + gap) + box_w // 2
        x_end = 28 + box_w // 2
        y_bot = box_y + box_h
        y_loop = y_bot + 82
        r = 18
        # 둥근 모서리 + 굵은 점선 + 전용 에메랄드 화살촉(#ar-green) 피드백 경로
        parts.append(
            f'<path d="M {x_start} {y_bot + 2} L {x_start} {y_loop - r} '
            f'Q {x_start} {y_loop} {x_start - r} {y_loop} '
            f'L {x_end + r} {y_loop} '
            f'Q {x_end} {y_loop} {x_end} {y_loop - r} '
            f'L {x_end} {y_bot + 7}" '
            f'fill="none" stroke="#047857" stroke-width="4.2" stroke-dasharray="11,7" '
            f'stroke-linecap="round" marker-end="url(#ar-green)"/>'
        )
        fb_clean = _wrap_svg_lines(feedback_label, max_chars=58, max_lines=1)[0]
        pill_w = min(920, max(460, len(fb_clean) * 15 + 72))
        pill_x = 600 - pill_w // 2
        parts.append(
            f'<rect x="{pill_x}" y="{y_loop - 22}" width="{pill_w}" height="44" rx="22" '
            f'fill="#ECFDF5" stroke="#047857" stroke-width="2.4" filter="url(#cardShadow)"/>'
        )
        parts.append(
            f'<text x="600" y="{y_loop + 6}" text-anchor="middle" font-size="15.5" font-weight="700" '
            f'fill="#064E3B">{html.escape(fb_clean)}</text>'
        )

    return _svg_canvas(title, sub, "\n  ".join(parts), "#1D3557", source_note=source_note)


def _render_vector_svg(spec: dict[str, Any], sections: list[str]) -> str:
    """하위 호환 래퍼: 내용 기반 구조도만 렌더링하고 가짜 수치 차트 생성을 차단한다 (V2/V4)."""
    return render_content_diagram_svg(spec, sections)


def overlay_korean_labels_pillow(
    base_image_path: Path,
    labels: list[dict[str, Any]],
    out_path: Path,
) -> Path:
    """V5 (textbook-visual-director Tier 2): 무문자 AI 바탕 이미지 위에 Pillow + 맑은 고딕 Bold로 한글 라벨·지시선을 정밀 합성한다."""
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(base_image_path) as im:
        img = im.convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", max(24, int(w * 0.020)))
    except Exception:
        font = ImageFont.load_default()

    for lb in labels:
        text = str(lb.get("text") or "").strip()
        if not text:
            continue
        # 상대 좌표 (0.0~1.0) 기준 배치
        lx = int(float(lb.get("x", 0.5)) * w)
        ly = int(float(lb.get("y", 0.5)) * h)
        tx = lb.get("target_x")
        ty = lb.get("target_y")
        accent = lb.get("color", (15, 23, 42, 255))
        if tx is not None and ty is not None:
            px, py = int(float(tx) * w), int(float(ty) * h)
            draw.line([(lx, ly), (px, py)], fill=(255, 255, 255, 240), width=8)
            draw.line([(lx, ly), (px, py)], fill=accent, width=4)
            r = max(7, int(w * 0.0055))
            draw.ellipse([px - r, py - r, px + r, py + r], fill=accent, outline=(255, 255, 255, 255), width=3)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad_x, pad_y = 16, 10
        bx0 = max(6, min(w - tw - pad_x * 2 - 6, lx - (tw // 2) - pad_x))
        by0 = max(6, min(h - th - pad_y * 2 - 6, ly - (th // 2) - pad_y))
        bx1, by1 = bx0 + tw + pad_x * 2, by0 + th + pad_y * 2
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=10, fill=(255, 255, 255, 245), outline=accent, width=3)
        draw.text((bx0 + pad_x, by0 + pad_y - 1), text, fill=(15, 23, 42, 255), font=font)

    merged = Image.alpha_composite(img, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(str(out_path), format="PNG")
    return out_path


def format_three_sentence_narrative(
    *,
    fig_no: str,
    claim_ko: str,
    how_to_read_ko: str,
    data_source: str,
) -> str:
    """V9 / P12: 그림마다 '① 무엇을 보여 주는가 → ② 어떻게 읽는가 → ③ 출처' 3문장 구조로 해설을 작성한다."""
    s1 = (claim_ko or "").strip().rstrip(".")
    s2 = (how_to_read_ko or "").strip().rstrip(".")
    s3 = (data_source or "본문 인용 근거 및 표준 문헌").strip().rstrip(".")
    return f"[{fig_no}] {s1}. {s2}. (자료: {s3})."


def build_chapter_visual_specs(
    *,
    topic_ko: str,
    topic_en: str,
    chapter: dict[str, Any],
    per_chapter_count: int = 4,
    manuscript_path: Path | None = None,
    allow_ai_images: bool = True,
) -> list[dict[str, Any]]:
    """V1/V8/V9: 원고의 실제 절·주장을 기반으로 간결한 제목과 3문장 해설을 갖춘 시각화 명세(권장 3~6장)를 구성한다.
    allow_ai_images=False(0원 기본 모드)일 때는 유료 AI 빈 틀(UNGENERATED)을 만들지 않고 0원 내용 구조도 템플릿만 배정한다."""
    cid = chapter.get("chapter_id", "ch01")
    ch_num = int(chapter.get("chapter_number") or 1)
    ch_title = chapter.get("title", f"제{ch_num}장")
    secs = chapter.get("sections") or [f"{ch_num}.1 개요", f"{ch_num}.2 원리", f"{ch_num}.3 응용"]
    field_scene, diagram_scene, macro_scene = _resolve_english_visual_scenes(topic_ko, topic_en, chapter)
    count = max(0, min(12, int(per_chapter_count)))
    if count == 0:
        return []

    # 0원 모드(allow_ai_images=False)에서는 비-AI 내용 구조도 템플릿만 사용 (빈 틀 UNGENERATED 스텁 생성 원천 차단)
    active_templates = (
        CHAPTER_VISUAL_TEMPLATES
        if allow_ai_images
        else [t for t in CHAPTER_VISUAL_TEMPLATES if t.get("kind") not in ("photo_ai", "infographic_ai")]
    ) or CHAPTER_VISUAL_TEMPLATES

    # 원고가 존재하면 실제 절 본문에서 인용키와 핵심 요지를 발췌 (근거 부족 경고 배너·주석 제외)
    sec_claims: dict[str, tuple[str, str]] = {}
    if manuscript_path and manuscript_path.is_file():
        raw_md = manuscript_path.read_text(encoding="utf-8", errors="ignore")
        body_md = re.split(r"(?m)^##\s*참고문헌", raw_md, maxsplit=1)[0]
        for m in re.finditer(r"(?m)^##\s+([^\n]+)\n([\s\S]*?)(?=^##\s+|\Z)", body_md):
            h_txt = m.group(1).strip()
            s_body = m.group(2).strip()
            cites = sorted(set(re.findall(r"\[SRC-\d+\]", s_body)))
            first_para = next(
                (
                    p.strip()
                    for p in s_body.split("\n\n")
                    if p.strip()
                    and not p.strip().startswith(("#", "|", "<", "*", ">"))
                    and "근거 부족" not in p
                    and "NEED_EVIDENCE" not in p
                ),
                "",
            )
            first_sent = re.split(r"(?<=[.다])\s+", re.sub(r"\s+", " ", first_para))[0][:140] if first_para else ""
            sec_claims[h_txt] = (first_sent, ", ".join(cites[:4]) if cites else "본문 분석")

    specs: list[dict[str, Any]] = []
    for idx in range(count):
        tmpl = active_templates[idx % len(active_templates)]
        v_num = idx + 1
        fig_id = f"fig_{cid}_v{v_num:02d}"
        fig_no = f"그림 {ch_num}-{v_num}"
        sec_ref = secs[idx % len(secs)]
        short_sec = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_ref).strip()
        if len(short_sec) > 34:
            short_sec = short_sec[:33].rstrip(" ,·(") + "…"
        is_ai = tmpl["kind"] in ("photo_ai", "infographic_ai")
        # V8: 간결한 그림 제목 (장 제목 반복 금지!)
        title_ko = f"{fig_no}. {short_sec}"
        prompt = (
            tmpl["prompt_tmpl"].format(
                field_scene=field_scene,
                diagram_scene=diagram_scene,
                macro_scene=macro_scene,
                zero_text=ZERO_TEXT_RULE,
            )
            if is_ai
            else ""
        )
        matched_claim, matched_src = sec_claims.get(sec_ref, ("", ""))
        claim_ko = matched_claim or f"{short_sec}의 핵심 구성 요소와 작동 원리를 보여준다"
        how_to_read = (
            "현장 실사 장면의 생육 형태와 환경 배치를 중심으로 관찰한다"
            if is_ai
            else "좌측 입력·계측 요소에서 우측 판단·적용 단계로 이어지는 화살표와 핵심 기준값을 따라 읽는다"
        )
        data_src = matched_src or f"《{topic_ko}》 {sec_ref} 본문 및 근거 패킷"
        narrative_ko = format_three_sentence_narrative(
            fig_no=fig_no,
            claim_ko=claim_ko,
            how_to_read_ko=how_to_read,
            data_source=data_src,
        )
        specs.append(
            {
                "figure_id": fig_id,
                "figure_no": fig_no,
                "chapter_id": cid,
                "chapter_number": ch_num,
                "index": v_num,
                "kind": tmpl["kind"],
                "style": tmpl["style"],
                "is_ai_image": is_ai,
                "target_section": sec_ref,
                "title_ko": title_ko,
                "subtitle_ko": short_sec,
                "claim_ko": claim_ko,
                "how_to_read_ko": how_to_read,
                "data_source": data_src,
                "prompt": prompt,
                "narrative_ko": narrative_ko,
                "sections": secs,
            }
        )
    return specs


def _rasterize_svgs_batch(
    svg_targets: list[tuple[Path, Path]],
    *,
    force: bool = False,
) -> dict[str, str]:
    """생성된 SVG 차트들을 Playwright 단일 브라우저 세션으로 고해상도 PNG로 일괄 래스터화한다 (DOCX/네이버 블로그 삽입용)."""
    if not svg_targets:
        return {}
    out_map: dict[str, str] = {}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 740}, device_scale_factor=2)
            for svg_p, png_p in svg_targets:
                if not svg_p.is_file():
                    continue
                if (
                    not force
                    and png_p.is_file()
                    and png_p.stat().st_size > 1500
                    and png_p.stat().st_mtime >= svg_p.stat().st_mtime
                ):
                    out_map[str(svg_p)] = str(png_p)
                    continue
                png_p.parent.mkdir(parents=True, exist_ok=True)
                svg_markup = svg_p.read_text(encoding="utf-8", errors="ignore")
                page.set_content(
                    f'<!DOCTYPE html><html><body style="margin:0;background:#ffffff;display:inline-block;">{svg_markup}</body></html>'
                )
                page.locator("svg").first.screenshot(path=str(png_p))
                if png_p.is_file():
                    out_map[str(svg_p)] = str(png_p)
            browser.close()
    except Exception:
        pass
    return out_map


def generate_project_visuals(
    *,
    project_id: str,
    topic_ko: str,
    topic_en: str,
    chapters: list[dict[str, Any]],
    per_chapter_count: int = 4,
    use_fal_ai: bool = False,
    fal_model: str = "fal-ai/nano-banana",
    use_nano_banana: bool = True,
    completed_ids: set[str] | None = None,
    on_item_done: Callable[[dict[str, Any], int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """V1/V6/V7: 주장·내용 기반 시각화 자료를 체크포인트 기반으로 생성한다. AI 생성 실패 시 빈 틀 SVG를 저장하지 않고 '미생성(UNGENERATED)'으로 표기해 출판에서 제외한다."""
    import shutil

    cfg = cfg or get_config()
    proj_ws = cfg.project_dir(project_id)
    fig_dir = proj_ws / "assets" / "figures"
    chart_dir = proj_ws / "assets" / "charts"
    png_dir = proj_ws / "assets" / "charts_png"
    by_ch_dir = proj_ws / "assets" / "by_chapter"
    e_vis_root = cfg.e_projects_dir / project_id / "visuals"
    e_by_ch_dir = e_vis_root / "by_chapter"
    for d in (fig_dir, chart_dir, png_dir, by_ch_dir, e_vis_root, e_by_ch_dir):
        d.mkdir(parents=True, exist_ok=True)

    fal_key = resolve_api_key("FAL_KEY", None, cfg) if use_fal_ai else ""
    gemini_key = resolve_api_key("GEMINI_API_KEY", None, cfg) if use_nano_banana else ""
    allow_ai = bool((use_fal_ai and fal_key) or (use_nano_banana and gemini_key))
    done_set = set(completed_ids or set())

    all_specs: list[dict[str, Any]] = []
    for ch in chapters:
        cid = ch.get("chapter_id", "ch01")
        mdx_p = proj_ws / "chapters" / f"{cid}.mdx"
        all_specs.extend(
            build_chapter_visual_specs(
                topic_ko=topic_ko,
                topic_en=topic_en,
                chapter=ch,
                per_chapter_count=per_chapter_count,
                manuscript_path=mdx_p if mdx_p.is_file() else None,
                allow_ai_images=allow_ai,
            )
        )

    total = len(all_specs)
    records: list[dict[str, Any]] = []
    ai_generated_cnt = 0
    svg_generated_cnt = 0
    ungenerated_cnt = 0
    stopped_early = False

    for idx, spec in enumerate(all_specs, 1):
        if should_stop and should_stop():
            stopped_early = True
            break

        fid = spec["figure_id"]
        png_path = fig_dir / f"{fid}.png"
        svg_path = chart_dir / f"{fid}.svg"

        # 체크포인트 복구: 이미 생성 완료된 파일이 존재하면 재사용
        if fid in done_set and (png_path.is_file() or svg_path.is_file()):
            actual_p = png_path if png_path.is_file() else svg_path
            sub = "figures" if actual_p.suffix == ".png" else "charts"
            rec = {
                **spec,
                "filename": actual_p.name,
                "path": str(actual_p),
                "rel_url": f"/project-files/{project_id}/assets/{sub}/{actual_p.name}",
                "engine": "resumed_checkpoint",
                "status": "OK",
                "exclude_from_publish": False,
            }
            records.append(rec)
            if actual_p.suffix == ".png":
                ai_generated_cnt += 1
            else:
                svg_generated_cnt += 1
            continue

        engine_used = "vector_svg"
        saved_path: Path | None = svg_path
        note = ""
        item_status = "OK"
        exclude_pub = False

        if spec["is_ai_image"]:
            generated_ai = False
            if use_fal_ai and fal_key:
                try:
                    ok, msg = _generate_with_fal_ai(prompt=spec["prompt"], out_path=png_path, fal_model=fal_model, api_key=fal_key)
                    if ok:
                        generated_ai = True
                        engine_used = msg
                        saved_path = png_path
                        ai_generated_cnt += 1
                    else:
                        note = msg
                except Exception as exc:
                    note = f"fal.ai 실패({str(exc)[:80]})"

            if not generated_ai and use_nano_banana and gemini_key:
                try:
                    ok, msg = _generate_with_nano_banana(prompt=spec["prompt"], out_path=png_path, api_key=gemini_key)
                    if ok:
                        generated_ai = True
                        engine_used = msg
                        saved_path = png_path
                        ai_generated_cnt += 1
                    else:
                        note = msg
                except Exception as exc:
                    note = f"나노바나나 실패({str(exc)[:80]})"

            # V6 핵심 수정: API 키 미설정 또는 생성 실패 시 빈 틀 SVG를 저장하지 않고 '미생성(UNGENERATED)'으로 기록해 출판에서 제외!
            if not generated_ai:
                engine_used = "unrendered_no_api_or_failed"
                saved_path = None
                item_status = "UNGENERATED"
                exclude_pub = True
                ungenerated_cnt += 1
                if not note:
                    note = "미생성 — FAL_KEY 또는 GEMINI_API_KEY 활성화 후 개별 생성 필요 (출판물에서 자동 제외됨)"
        else:
            svg_text = _render_vector_svg(spec, spec.get("sections") or [])
            svg_path.write_text(svg_text, encoding="utf-8")
            engine_used = "content_vector_svg"
            saved_path = svg_path
            svg_generated_cnt += 1

        if saved_path is not None and saved_path.is_file():
            sub = "figures" if saved_path.suffix == ".png" else "charts"
            rel_u = f"/project-files/{project_id}/assets/{sub}/{saved_path.name}"
            fname = saved_path.name
            p_str = str(saved_path)
            done_set.add(fid)
        else:
            rel_u = ""
            fname = ""
            p_str = ""

        rec = {
            **spec,
            "filename": fname,
            "path": p_str,
            "rel_url": rel_u,
            "engine": engine_used,
            "note": note,
            "status": item_status,
            "exclude_from_publish": exclude_pub,
        }
        records.append(rec)
        if on_item_done:
            on_item_done(rec, idx, total)

    # SVG → 고해상도 PNG 일괄 래스터화 (DOCX·네이버 블로그 <img> 삽입용)
    svg_batch: list[tuple[Path, Path]] = []
    for r in records:
        if r.get("status") != "OK" or not r.get("path"):
            continue
        p = Path(r["path"])
        if p.suffix.lower() == ".svg":
            svg_batch.append((p, png_dir / f"{p.stem}.png"))
    raster_map = _rasterize_svgs_batch(svg_batch)

    # 단원별 분리 폴더 저장 (미생성 항목은 파일 복사 건너뜀)
    by_ch_summary: dict[str, int] = {}
    for r in records:
        cid = r.get("chapter_id", "ch01")
        loc_ch = by_ch_dir / cid
        e_ch = e_by_ch_dir / cid
        loc_ch.mkdir(parents=True, exist_ok=True)
        e_ch.mkdir(parents=True, exist_ok=True)
        r["chapter_dir_local"] = str(loc_ch)
        r["chapter_dir_e"] = str(e_ch)

        if r.get("status") != "OK" or not r.get("path"):
            r["docx_image_path"] = ""
            r["png_url"] = ""
            continue

        by_ch_summary[cid] = by_ch_summary.get(cid, 0) + 1
        src_p = Path(r["path"])
        if src_p.is_file():
            shutil.copy2(src_p, loc_ch / src_p.name)
            shutil.copy2(src_p, e_ch / src_p.name)

        if src_p.suffix.lower() == ".png":
            r["docx_image_path"] = str(src_p)
            r["png_url"] = r["rel_url"]
        else:
            png_str = raster_map.get(str(src_p), "")
            if png_str and Path(png_str).is_file():
                png_p = Path(png_str)
                shutil.copy2(png_p, loc_ch / png_p.name)
                shutil.copy2(png_p, e_ch / png_p.name)
                r["docx_image_path"] = str(png_p)
                r["png_url"] = f"/project-files/{project_id}/assets/charts_png/{png_p.name}"
            else:
                r["docx_image_path"] = ""
                r["png_url"] = ""

    # 단원별 QA 컨택트 시트 자동 생성 (V7)
    contact_sheets: dict[str, str] = {}
    for cid in sorted({r.get("chapter_id", "ch01") for r in records}):
        ch_recs = [r for r in records if r.get("chapter_id") == cid and r.get("status") == "OK"]
        if not ch_recs:
            continue
        grid_local = by_ch_dir / cid / f"qa_grid_{cid}.jpg"
        grid_e = e_by_ch_dir / cid / f"qa_grid_{cid}.jpg"
        try:
            build_visual_contact_sheet(cid, f"{topic_ko} ({cid})", ch_recs, grid_local)
            if grid_local.is_file():
                shutil.copy2(grid_local, grid_e)
                contact_sheets[cid] = f"/project-files/{project_id}/assets/by_chapter/{cid}/qa_grid_{cid}.jpg"
        except Exception:
            pass

    generated_ok = [r for r in records if r.get("status") == "OK"]
    manifest_payload = {
        "project_id": project_id,
        "generated_at": utc_now_iso(),
        "per_chapter_target": int(per_chapter_count),
        "use_fal_ai": use_fal_ai,
        "fal_model": fal_model,
        "use_nano_banana": use_nano_banana,
        "total_planned": total,
        "total_generated": len(generated_ok),
        "ungenerated_count": ungenerated_cnt,
        "ai_images_count": ai_generated_cnt,
        "svg_charts_count": svg_generated_cnt,
        "png_rasterized_count": sum(1 for r in generated_ok if r.get("docx_image_path")),
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_summary,
        "contact_sheets": contact_sheets,
        "stopped_early": stopped_early,
        "visuals": records,
    }
    manifest_path = proj_ws / "assets" / "visuals_plan.json"
    manifest_text = json.dumps(manifest_payload, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    (e_vis_root / "visuals_plan.json").write_text(manifest_text, encoding="utf-8")

    guide_lines = [
        f"# 《{topic_ko}》 시각화 자료 3문장 해설 가이드 (무엇을 보여 주나 · 어떻게 읽나 · 출처)",
        "",
        f"- **완료된 출판 가능 도판**: {len(generated_ok)}종 (미생성/출판 제외: {ungenerated_cnt}종)",
        f"- 로컬 단원별 저장소: `{by_ch_dir}`",
        f"- E 드라이브 별도 저장소: `{e_vis_root}`",
        "",
    ]
    for r in generated_ok:
        guide_lines.append(f"## {r['title_ko']}")
        guide_lines.append("")
        guide_lines.append(r["narrative_ko"])
        guide_lines.append("")
    guide_text = "\n".join(guide_lines)
    guide_path = proj_ws / "assets" / "visuals_text_guide.md"
    guide_path.write_text(guide_text, encoding="utf-8")
    (e_vis_root / "visuals_text_guide.md").write_text(guide_text, encoding="utf-8")

    idx_lines = [
        f"# 《{topic_ko}》 시각화 자료 별도 저장소 인덱스",
        "",
        f"- **출판 가능 시각화**: {len(generated_ok)}종 (AI/실사 {ai_generated_cnt}종 · 내용 도해/차트 {svg_generated_cnt}종 · 미생성 {ungenerated_cnt}종)",
        f"- **단원별 저장 폴더**: `{e_by_ch_dir}`",
        "",
    ]
    for cid, cnt in sorted(by_ch_summary.items()):
        idx_lines.append(f"- `{cid}`: {cnt}종 (`by_chapter/{cid}/`)")
    (e_vis_root / "INDEX.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

    return {
        "status": "INTERRUPTED" if stopped_early else "DONE",
        "total_planned": total,
        "total_generated": len(generated_ok),
        "ungenerated_count": ungenerated_cnt,
        "ai_images_count": ai_generated_cnt,
        "svg_charts_count": svg_generated_cnt,
        "png_rasterized_count": manifest_payload["png_rasterized_count"],
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_summary,
        "contact_sheets": contact_sheets,
        "completed_visual_ids": sorted(done_set),
        "manifest_path": str(manifest_path),
        "guide_path": str(guide_path),
        "visuals": records,
    }


def build_visual_contact_sheet(
    chapter_id: str,
    chapter_title: str,
    records: list[dict[str, Any]],
    out_jpg: Path,
) -> Path:
    """V7: 단원별 완성 도판을 한눈에 시각 검수하는 고해상도 QA 컨택트 시트(qa_grid_chNN.jpg)를 생성한다."""
    from PIL import Image, ImageDraw, ImageFont

    cols = 3 if len(records) <= 6 else 4
    rows = max(1, (len(records) + cols - 1) // cols)
    cell_w, cell_h = 680, 440
    margin, header_h = 18, 62
    canvas_w = margin + cols * (cell_w + margin)
    canvas_h = header_h + margin + rows * (cell_h + margin)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (248, 250, 252))
    draw = ImageDraw.Draw(canvas)
    try:
        f_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 24)
        f_lbl = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 15)
    except Exception:
        f_title = f_lbl = ImageFont.load_default()

    draw.rectangle([0, 0, canvas_w, header_h], fill=(29, 53, 87))
    draw.text((22, 16), f"[{chapter_id}] {chapter_title} — 시각 QA 컨택트 시트 ({len(records)}종)", fill=(255, 255, 255), font=f_title)

    for idx, rec in enumerate(records):
        r, c = idx // cols, idx % cols
        x = margin + c * (cell_w + margin)
        y = header_h + margin + r * (cell_h + margin)
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(255, 255, 255), outline=(203, 213, 225), width=2)
        img_cand = Path(rec.get("docx_image_path") or rec.get("path") or "")
        if img_cand.is_file() and img_cand.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                with Image.open(img_cand) as im:
                    im_rgb = im.convert("RGB")
                    im_rgb.thumbnail((cell_w - 12, cell_h - 46), Image.Resampling.LANCZOS)
                    px = x + (cell_w - im_rgb.width) // 2
                    py = y + (cell_h - 40 - im_rgb.height) // 2
                    canvas.paste(im_rgb, (px, py))
            except Exception:
                draw.text((x + 14, y + 40), f"이미지 로드 오류: {img_cand.name}", fill=(220, 38, 38), font=f_lbl)
        else:
            draw.text((x + 18, y + 60), f"미생성 / PNG 없음 ({rec.get('status', '')})", fill=(180, 83, 9), font=f_lbl)
        lbl_y = y + cell_h - 38
        draw.rectangle([x + 1, lbl_y, x + cell_w - 1, y + cell_h - 1], fill=(241, 245, 249))
        caption = f"{rec.get('title_ko', rec.get('figure_id', ''))[:44]} | {rec.get('engine', '')[:18]}"
        draw.text((x + 10, lbl_y + 8), caption, fill=(15, 23, 42), font=f_lbl)

    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out_jpg), format="JPEG", quality=90)
    return out_jpg


def audit_visual_assets(
    project_id: str,
    chapter_id: str | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """V7: 렌더링된 시각화 자산의 출처 유무·틀 그림·가짜 수치·제목 잘림·해상도를 자동 감사한다."""
    from figure_registry import _is_placeholder_or_fake_visual

    cfg = cfg or get_config()
    ws = cfg.project_dir(project_id)
    plan_p = ws / "assets" / "visuals_plan.json"
    if not plan_p.is_file():
        return {
            "project_id": project_id,
            "total": 0,
            "publishable": 0,
            "issues_count": 0,
            "source_coverage_pct": 100.0,
            "has_placeholder_or_fake": False,
            "items": [],
        }

    plan = json.loads(plan_p.read_text(encoding="utf-8"))
    raw_items = plan.get("visuals") or plan.get("items") or []
    if chapter_id:
        raw_items = [x for x in raw_items if x.get("chapter_id") == chapter_id]

    audited: list[dict[str, Any]] = []
    publishable = 0
    excluded_count = 0
    active_total = 0
    with_source = 0
    has_fake = False
    issues_total = 0

    for it in raw_items:
        issues: list[str] = []
        is_excluded = bool(it.get("exclude_from_publish"))
        fp = Path(it.get("path") or "") if it.get("path") else Path("")
        is_bad = _is_placeholder_or_fake_visual(it, fp)
        title = str(it.get("title_ko") or "")
        src_str = str(it.get("data_source") or it.get("source_note") or "").strip()
        if not src_str:
            narr_txt = str(it.get("narrative_ko") or "")
            m_src = re.search(r"\((?:자료|출처)\s*:\s*([^)]+)\)", narr_txt)
            if m_src:
                src_str = m_src.group(1).strip()
            else:
                cites_in_narr = re.findall(r"\[SRC-\d+\]", narr_txt)
                if cites_in_narr:
                    src_str = ", ".join(dict.fromkeys(cites_in_narr)) + " 기반 재구성"

        if is_excluded:
            excluded_count += 1
            audited.append(
                {
                    "figure_id": it.get("figure_id", ""),
                    "chapter_id": it.get("chapter_id", ""),
                    "title_ko": title,
                    "status": it.get("status", "EXCLUDED"),
                    "engine": it.get("engine", ""),
                    "has_source": bool(src_str),
                    "publishable": False,
                    "excluded": True,
                    "issues": [],
                }
            )
            continue

        active_total += 1
        is_prompt_ready = str(it.get("status", "")).upper() == "PROMPT_READY"
        if is_prompt_ready:
            if not src_str:
                issues.append("자료 출처(data_source) 미기재")
            else:
                with_source += 1
                publishable += 1
            issues_total += len(issues)
            audited.append(
                {
                    "figure_id": it.get("figure_id", ""),
                    "chapter_id": it.get("chapter_id", ""),
                    "title_ko": title,
                    "status": "PROMPT_READY",
                    "engine": it.get("engine", "Bilingual Prompt Pack (0원)"),
                    "has_source": bool(src_str),
                    "publishable": bool(src_str),
                    "excluded": False,
                    "issues": issues,
                }
            )
            continue
        if is_bad:
            issues.append("빈 틀 또는 가짜 수치 차트(출판 제외 대상)")
            has_fake = True
        if str(it.get("status", "")).upper() == "UNGENERATED" or not fp.is_file():
            issues.append("이미지 파일 미생성")
        if "— 현장" in title or len(title) > 68:
            issues.append("그림 제목 과장/잘림 위험(장 제목 반복 제거 필요)")
        if not src_str:
            issues.append("자료 출처(data_source) 미기재")
        else:
            with_source += 1
        if not is_bad and fp.is_file():
            publishable += 1
        issues_total += len(issues)
        audited.append(
            {
                "figure_id": it.get("figure_id", ""),
                "chapter_id": it.get("chapter_id", ""),
                "title_ko": title,
                "status": it.get("status", ""),
                "engine": it.get("engine", ""),
                "has_source": bool(src_str),
                "publishable": (not is_bad and fp.is_file()),
                "excluded": False,
                "issues": issues,
            }
        )

    tot = len(raw_items)
    denom = active_total if active_total > 0 else tot
    return {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "total": tot,
        "active_total": active_total,
        "excluded_count": excluded_count,
        "publishable": publishable,
        "issues_count": issues_total,
        "source_coverage_pct": round((with_source / max(1, denom)) * 100.0, 1) if denom else 100.0,
        "has_placeholder_or_fake": has_fake,
        "contact_sheets": plan.get("contact_sheets") or {},
        "items": audited,
    }
