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

# 단원당 기본 10종 시각화 아키타입 (실사진/과학도해 4종 + 정량/구조 한글 SVG 6종)
CHAPTER_VISUAL_TEMPLATES: list[dict[str, str]] = [
    {
        "slot": "v01",
        "kind": "photo_ai",
        "style": "photorealistic",
        "role_ko": "현장 실사진: 핵심 작물·재배 환경 전경",
        "prompt_tmpl": "Ultra-realistic documentary agricultural photograph of {field_scene}, crisp natural daylight, field research station quality, accurate botanical morphology, shallow depth of field. {zero_text}",
    },
    {
        "slot": "v02",
        "kind": "infographic_ai",
        "style": "scientific_illustration",
        "role_ko": "과학 단면도·생리 구조 도해",
        "prompt_tmpl": "Publication-grade Nature journal scientific botanical illustration: {diagram_scene}, anatomically and physically accurate, crisp editorial shading, clean pure white background. {zero_text}",
    },
    {
        "slot": "v03",
        "kind": "photo_ai",
        "style": "photorealistic_macro",
        "role_ko": "근접 실사진: 생리·품질·구조 정밀 관찰",
        "prompt_tmpl": "High-resolution macro scientific photography closely capturing {macro_scene}, true-to-life botanical color, crisp natural texture, laboratory diagnostic clarity. {zero_text}",
    },
    {
        "slot": "v04",
        "kind": "infographic_ai",
        "style": "system_illustration",
        "role_ko": "디지털·스마트 현장 시스템 도해",
        "prompt_tmpl": "Clean modern editorial isometric illustration on pure white background showing precision agriculture sensors, weather station, and field crop canopy related to {field_scene}, realistic architectural clarity. {zero_text}",
    },
    {
        "slot": "v05",
        "kind": "svg_flow",
        "style": "flowchart",
        "role_ko": "핵심 메커니즘 및 의사결정 흐름도",
        "prompt_tmpl": "",
    },
    {
        "slot": "v06",
        "kind": "svg_bar",
        "style": "comparison_bar",
        "role_ko": "핵심 관리 요인별 상대 기여도 비교 차트",
        "prompt_tmpl": "",
    },
    {
        "slot": "v07",
        "kind": "svg_timeline",
        "style": "stage_timeline",
        "role_ko": "단계별 생육·작업 프로세스 로드맵",
        "prompt_tmpl": "",
    },
    {
        "slot": "v08",
        "kind": "svg_matrix",
        "style": "diagnostic_matrix",
        "role_ko": "현장 이상 진단 및 대응 전략 매트릭스",
        "prompt_tmpl": "",
    },
    {
        "slot": "v09",
        "kind": "svg_curve",
        "style": "response_curve",
        "role_ko": "환경 변수 변화에 따른 정량 반응 곡선",
        "prompt_tmpl": "",
    },
    {
        "slot": "v10",
        "kind": "svg_summary",
        "style": "concept_map",
        "role_ko": "단원 핵심 개념 통합 관계도",
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
    model: str = "nano-banana-pro-preview",
    api_key: str,
) -> tuple[bool, str]:
    """Google Gemini 나노바나나(Nano Banana Pro 우선 폴백 체인) API로 실사진/과학 일러스트를 생성한다."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    chain = [model] + [m for m in ("nano-banana-pro-preview", "gemini-nano-banana-2.1", "gemini-3.1-flash-image", "gemini-2.5-flash-image") if m != model]
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


def _svg_canvas(title: str, subtitle: str, body: str, accent: str = "#0f172a") -> str:
    t_clean = _wrap_svg_lines(title, max_chars=48, max_lines=1)[0]
    s_clean = _wrap_svg_lines(subtitle, max_chars=74, max_lines=1)[0]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 420" width="800" height="420" '
        f'style="background:#ffffff;font-family:{FONT};">\n'
        f'  <rect x="0" y="0" width="800" height="420" rx="12" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>\n'
        f'  <rect x="0" y="0" width="800" height="58" rx="12" fill="{accent}"/>\n'
        f'  <rect x="0" y="42" width="800" height="16" fill="{accent}"/>\n'
        f'  <text x="22" y="27" font-size="14.5" font-weight="700" fill="#f8fafc">{html.escape(t_clean)}</text>\n'
        f'  <text x="22" y="47" font-size="11" fill="#cbd5e1">{html.escape(s_clean)}</text>\n'
        f'  {body}\n'
        f'</svg>'
    )


def _render_vector_svg(spec: dict[str, Any], sections: list[str]) -> str:
    """단원 내용에 맞춘 출판급 한글 벡터 SVG 도해·차트를 생성한다 (단어 경계 줄바꿈으로 글자 잘림·오탈자 0%)."""
    style = spec.get("style", "flowchart")
    title = spec["title_ko"]
    sub = spec["subtitle_ko"]
    sec_labels = [_clean_svg_label(s) for s in (sections[:4] or ["1. 기초 원리", "2. 환경 제어", "3. 정밀 분석", "4. 현장 적용"])]
    while len(sec_labels) < 4:
        sec_labels.append(f"단계 {len(sec_labels)+1}")

    if style == "comparison_bar":
        vals = [92, 84, 76, 68]
        colors = ["#0284c7", "#16a34a", "#d97706", "#7c3aed"]
        parts = []
        for i, (lbl, v, col) in enumerate(zip(sec_labels, vals, colors)):
            y = 92 + i * 74
            w = int((v / 100.0) * 410)
            lines = _wrap_svg_lines(lbl, max_chars=16, max_lines=2)
            parts.append(_svg_multiline_text(24, y + 20, lines, font_size=11.5, line_height=15, fill="#1e293b", weight="700", anchor="start"))
            parts.append(f'<rect x="270" y="{y+6}" width="420" height="28" rx="6" fill="#f1f5f9"/>')
            parts.append(f'<rect x="270" y="{y+6}" width="{w}" height="28" rx="6" fill="{col}"/>')
            parts.append(f'<text x="{278+w}" y="{y+25}" font-size="12" font-weight="700" fill="#0f172a">{v}%</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#0f2942")

    if style == "response_curve":
        pts = [(110, 310), (220, 250), (350, 155), (480, 125), (610, 175), (720, 265)]
        poly = " ".join(f"{x},{y}" for x, y in pts)
        parts = [
            '<rect x="85" y="84" width="665" height="260" fill="#f8fafc" stroke="#cbd5e1"/>',
            '<line x1="85" y1="214" x2="750" y2="214" stroke="#e2e8f0" stroke-dasharray="4,4"/>',
            '<rect x="300" y="84" width="220" height="260" fill="rgba(22,163,74,0.10)"/>',
            '<text x="410" y="106" text-anchor="middle" font-size="11.5" font-weight="700" fill="#15803d">최적 관리 구간 (Optimal Zone)</text>',
            f'<polyline fill="none" stroke="#0284c7" stroke-width="3.2" points="{poly}"/>',
        ]
        for x, y in pts:
            parts.append(f'<circle cx="{x}" cy="{y}" r="5.5" fill="#0284c7" stroke="#ffffff" stroke-width="2"/>')
        parts.append('<text x="418" y="378" text-anchor="middle" font-size="12" font-weight="700" fill="#334155">환경 · 투입 인자 수준 (부족 → 최적 → 과잉)</text>')
        parts.append('<text x="26" y="215" text-anchor="middle" font-size="12" font-weight="700" fill="#334155" transform="rotate(-90 26 215)">생육 · 품질 지수</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#064e3b")

    if style == "diagnostic_matrix":
        cells = [
            (40, 88, "#dcfce7", "#166534", "정상 · 최적 상태", sec_labels[0]),
            (415, 88, "#dbeafe", "#1e40af", "예방적 디지털 모니터링", sec_labels[1]),
            (40, 245, "#fef9c3", "#854d0e", "주의 · 임계치 접근", sec_labels[2]),
            (415, 245, "#fee2e2", "#991b1b", "즉각 교정 · 방제 조치", sec_labels[3]),
        ]
        parts = []
        for x, y, bg, fg, head, desc in cells:
            parts.append(f'<rect x="{x}" y="{y}" width="345" height="135" rx="10" fill="{bg}" stroke="{fg}" stroke-width="1.5"/>')
            parts.append(f'<text x="{x+18}" y="{y+34}" font-size="14" font-weight="700" fill="{fg}">{html.escape(head)}</text>')
            d_lines = _wrap_svg_lines(desc, max_chars=24, max_lines=2)
            parts.append(_svg_multiline_text(x + 18, y + 70, d_lines, font_size=11.8, line_height=16, fill="#1e293b", weight="600", anchor="start"))
            parts.append(f'<text x="{x+18}" y="{y+114}" font-size="11" fill="#475569">정량 계측 → 임계 판정 → 현장 처방</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#312e81")

    if style == "stage_timeline":
        parts = ['<line x1="70" y1="228" x2="730" y2="228" stroke="#0284c7" stroke-width="4"/>']
        colors = ["#0284c7", "#0d9488", "#16a34a", "#7c3aed"]
        for i, (lbl, col) in enumerate(zip(sec_labels, colors)):
            cx = 115 + i * 190
            parts.append(f'<circle cx="{cx}" cy="228" r="22" fill="{col}" stroke="#ffffff" stroke-width="3"/>')
            parts.append(f'<text x="{cx}" y="233" text-anchor="middle" font-size="13" font-weight="700" fill="#ffffff">S{i+1}</text>')
            parts.append(f'<rect x="{cx-84}" y="96" width="168" height="86" rx="8" fill="#f8fafc" stroke="{col}" stroke-width="1.5"/>')
            t_lines = _wrap_svg_lines(lbl, max_chars=12, max_lines=3)
            parts.append(_svg_multiline_text(cx, 139, t_lines, font_size=11.5, line_height=16, fill="#0f172a", weight="700", anchor="middle"))
            parts.append(f'<text x="{cx}" y="286" text-anchor="middle" font-size="11" fill="#475569">핵심 지표 계측 · 검증</text>')
        return _svg_canvas(title, sub, "\n  ".join(parts), "#1e293b")

    # flowchart / concept_map / ai_blueprint_card
    parts = [
        '<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
        '<path d="M 0 1 L 10 5 L 0 9 z" fill="#334155"/></marker></defs>'
    ]
    bgs = ["#e0f2fe", "#dcfce7", "#fef3c7", "#f3e8ff"]
    for i, (lbl, bg) in enumerate(zip(sec_labels, bgs)):
        x = 34 + i * 188
        parts.append(f'<rect x="{x}" y="128" width="164" height="158" rx="10" fill="{bg}" stroke="#334155" stroke-width="1.4"/>')
        parts.append(f'<text x="{x+82}" y="162" text-anchor="middle" font-size="11" font-weight="700" fill="#475569">STEP {i+1}</text>')
        b_lines = _wrap_svg_lines(lbl, max_chars=11, max_lines=3)
        parts.append(_svg_multiline_text(x + 82, 224, b_lines, font_size=12, line_height=18, fill="#0f172a", weight="700", anchor="middle"))
        if i < 3:
            parts.append(f'<line x1="{x+164}" y1="208" x2="{x+188}" y2="208" stroke="#334155" stroke-width="2" marker-end="url(#ar)"/>')
    if spec.get("prompt"):
        parts.append(
            f'<text x="400" y="348" text-anchor="middle" font-size="11" fill="#64748b">'
            f'실사진/도해 생성 프롬프트 준비됨 (fal.ai 또는 나노바나나 API 키 활성화 시 실사 PNG 자동 대체)</text>'
        )
    return _svg_canvas(title, sub, "\n  ".join(parts), "#0f172a")


def build_chapter_visual_specs(
    *,
    topic_ko: str,
    topic_en: str,
    chapter: dict[str, Any],
    per_chapter_count: int = 10,
) -> list[dict[str, Any]]:
    """단원 1개당 최소 10개 이상의 시각화 명세(실사진/과학도해 + 정량 SVG + 줄글 해설)를 구성한다."""
    cid = chapter.get("chapter_id", "ch01")
    ch_num = int(chapter.get("chapter_number") or 1)
    ch_title = chapter.get("title", f"제{ch_num}장")
    secs = chapter.get("sections") or [f"{ch_num}.1 개요", f"{ch_num}.2 원리", f"{ch_num}.3 응용", f"{ch_num}.4 현장관리"]
    field_scene, diagram_scene, macro_scene = _resolve_english_visual_scenes(topic_ko, topic_en, chapter)
    count = max(10, int(per_chapter_count))

    specs: list[dict[str, Any]] = []
    for idx in range(count):
        tmpl = CHAPTER_VISUAL_TEMPLATES[idx % len(CHAPTER_VISUAL_TEMPLATES)]
        v_num = idx + 1
        fig_id = f"fig_{cid}_v{v_num:02d}"
        sec_ref = secs[idx % len(secs)]
        is_ai = tmpl["kind"] in ("photo_ai", "infographic_ai")
        title_ko = f"그림 {ch_num}-{v_num}. {ch_title} — {tmpl['role_ko']} ({sec_ref})"
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
        narrative_ko = (
            f"[그림 {ch_num}-{v_num}] {title_ko}은(는) 《{topic_ko}》 {ch_title}의 핵심 학습 요소인 '{sec_ref}'을 "
            f"{'사실적인 현장 실사진 및 고해상도 과학 도해' if is_ai else '정량적 벡터 차트 및 구조 다이어그램'}으로 시각화한 자료이다. "
            f"독자는 이 도해를 통해 주요 환경·생리·관리 변수 간의 인과관계를 직관적으로 파악하고 현장 의사결정 기준과 직접 연결할 수 있다."
        )
        specs.append(
            {
                "figure_id": fig_id,
                "chapter_id": cid,
                "chapter_number": ch_num,
                "index": v_num,
                "kind": tmpl["kind"],
                "style": tmpl["style"],
                "is_ai_image": is_ai,
                "title_ko": title_ko,
                "subtitle_ko": f"{topic_ko} · {sec_ref}",
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
            page = browser.new_page(viewport={"width": 960, "height": 540}, device_scale_factor=2)
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
    per_chapter_count: int = 10,
    use_fal_ai: bool = False,
    fal_model: str = "fal-ai/nano-banana",
    use_nano_banana: bool = True,
    completed_ids: set[str] | None = None,
    on_item_done: Callable[[dict[str, Any], int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 단원별 10개 이상 시각화 자료를 체크포인트 기반으로 생성하고 별도 폴더(로컬+E:\\)에 체계 저장한다."""
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
    done_set = set(completed_ids or set())

    all_specs: list[dict[str, Any]] = []
    for ch in chapters:
        all_specs.extend(
            build_chapter_visual_specs(
                topic_ko=topic_ko,
                topic_en=topic_en,
                chapter=ch,
                per_chapter_count=per_chapter_count,
            )
        )

    total = len(all_specs)
    records: list[dict[str, Any]] = []
    ai_generated_cnt = 0
    svg_generated_cnt = 0
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
            }
            records.append(rec)
            if actual_p.suffix == ".png":
                ai_generated_cnt += 1
            else:
                svg_generated_cnt += 1
            continue

        engine_used = "vector_svg"
        saved_path = svg_path
        note = ""

        if spec["is_ai_image"]:
            generated_ai = False
            # 1순위: fal.ai API (사용자 체크 ON + FAL_KEY 보유 시)
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
                    note = f"fal.ai 폴백({str(exc)[:80]})"

            # 2순위: Google Gemini 나노바나나 (GEMINI_API_KEY 보유 시)
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
                    note = f"나노바나나 폴백({str(exc)[:80]})"

            # 3순위: API 키 미설정 시 출판급 벡터 도해 SVG + 실사 프롬프트 매니페스트 보존
            if not generated_ai:
                svg_text = _render_vector_svg(spec, spec.get("sections") or [])
                svg_path.write_text(svg_text, encoding="utf-8")
                engine_used = "svg_blueprint_ready"
                saved_path = svg_path
                svg_generated_cnt += 1
                if not note:
                    note = "FAL_KEY 또는 GEMINI_API_KEY 입력 시 실사 PNG 자동 생성"
        else:
            svg_text = _render_vector_svg(spec, spec.get("sections") or [])
            svg_path.write_text(svg_text, encoding="utf-8")
            engine_used = "vector_svg"
            saved_path = svg_path
            svg_generated_cnt += 1

        sub = "figures" if saved_path.suffix == ".png" else "charts"
        rec = {
            **spec,
            "filename": saved_path.name,
            "path": str(saved_path),
            "rel_url": f"/project-files/{project_id}/assets/{sub}/{saved_path.name}",
            "engine": engine_used,
            "note": note,
            "status": "OK",
        }
        records.append(rec)
        done_set.add(fid)
        if on_item_done:
            on_item_done(rec, idx, total)

    # SVG → 고해상도 PNG 일괄 래스터화 (DOCX·네이버 블로그 <img> 완벽 삽입용)
    svg_batch: list[tuple[Path, Path]] = []
    for r in records:
        p = Path(r["path"])
        if p.suffix.lower() == ".svg":
            svg_batch.append((p, png_dir / f"{p.stem}.png"))
    raster_map = _rasterize_svgs_batch(svg_batch)

    # 단원별 분리 폴더(로컬 assets/by_chapter/<chNN>/ + E:\SMC_Report_Platform_Data\projects\<pid>\visuals\by_chapter\<chNN>\) 저장
    by_ch_summary: dict[str, int] = {}
    for r in records:
        cid = r.get("chapter_id", "ch01")
        by_ch_summary[cid] = by_ch_summary.get(cid, 0) + 1
        src_p = Path(r["path"])
        loc_ch = by_ch_dir / cid
        e_ch = e_by_ch_dir / cid
        loc_ch.mkdir(parents=True, exist_ok=True)
        e_ch.mkdir(parents=True, exist_ok=True)

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

        r["chapter_dir_local"] = str(loc_ch)
        r["chapter_dir_e"] = str(e_ch)

    # 매니페스트 및 줄글 텍스트 해설 가이드(표 금지 규칙 준수!) 저장 + E:\ 별도 저장소 미러링
    manifest_payload = {
        "project_id": project_id,
        "generated_at": utc_now_iso(),
        "per_chapter_target": max(10, int(per_chapter_count)),
        "use_fal_ai": use_fal_ai,
        "fal_model": fal_model,
        "use_nano_banana": use_nano_banana,
        "total_generated": len(records),
        "ai_images_count": ai_generated_cnt,
        "svg_charts_count": svg_generated_cnt,
        "png_rasterized_count": sum(1 for r in records if r.get("docx_image_path")),
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_summary,
        "stopped_early": stopped_early,
        "visuals": records,
    }
    manifest_path = proj_ws / "assets" / "visuals_plan.json"
    manifest_text = json.dumps(manifest_payload, ensure_ascii=False, indent=2)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    (e_vis_root / "visuals_plan.json").write_text(manifest_text, encoding="utf-8")

    guide_lines = [
        f"# 《{topic_ko}》 시각화 자료 줄글 해설 가이드",
        "",
        f"본 문서는 각 단원당 {max(10, int(per_chapter_count))}개 이상 제작된 실사진·인포그래픽 및 정량 차트의 상세 내용을 표 형식이 아닌 자연스러운 줄글로 설명합니다.",
        f"- 로컬 단원별 저장소: `{by_ch_dir}`",
        f"- E 드라이브 별도 저장소: `{e_vis_root}`",
        "",
    ]
    for r in records:
        guide_lines.append(f"## {r['title_ko']}")
        guide_lines.append("")
        guide_lines.append(r["narrative_ko"])
        guide_lines.append("")
    guide_text = "\n".join(guide_lines)
    guide_path = proj_ws / "assets" / "visuals_text_guide.md"
    guide_path.write_text(guide_text, encoding="utf-8")
    (e_vis_root / "visuals_text_guide.md").write_text(guide_text, encoding="utf-8")

    # E:\visuals\INDEX.md 별도 인덱스 작성
    idx_lines = [
        f"# 《{topic_ko}》 시각화 자료 별도 저장소 인덱스",
        "",
        f"- **총 시각화 자료**: {len(records)}종 (AI/실사 {ai_generated_cnt}종 · SVG {svg_generated_cnt}종 · DOCX/블로그용 PNG {manifest_payload['png_rasterized_count']}종)",
        f"- **단원별 저장 폴더**: `{e_by_ch_dir}`",
        "",
    ]
    for cid, cnt in sorted(by_ch_summary.items()):
        idx_lines.append(f"- `{cid}`: {cnt}종 (`by_chapter/{cid}/`)")
    (e_vis_root / "INDEX.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

    return {
        "status": "INTERRUPTED" if stopped_early else "DONE",
        "total_planned": total,
        "total_generated": len(records),
        "ai_images_count": ai_generated_cnt,
        "svg_charts_count": svg_generated_cnt,
        "png_rasterized_count": manifest_payload["png_rasterized_count"],
        "local_visuals_dir": str(by_ch_dir),
        "e_visuals_dir": str(e_vis_root),
        "by_chapter_counts": by_ch_summary,
        "completed_visual_ids": sorted(done_set),
        "manifest_path": str(manifest_path),
        "guide_path": str(guide_path),
        "visuals": records,
    }
