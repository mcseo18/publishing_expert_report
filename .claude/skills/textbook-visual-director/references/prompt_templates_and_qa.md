# 『weed_control』 검증 도판 프롬프트 표준 템플릿 · 코드 패턴 · 시각 QA 규격

본 문서는 `textbook-visual-director` 스킬의 실행 레퍼런스이다.

---

## 1. `figure_prompts.json` 마스터 스키마

단원별 도판 명세는 아래 표준 JSON 스키마를 따른다(`prompts_and_descriptions.json` 및 마스터 `figure_prompts.json` 공용).

```json
{
  "id": "그림 1-01",
  "figure_id": "fig_ch01_v01",
  "chapter": 1,
  "chapter_id": "ch01",
  "chapter_title": "단원 제목",
  "unit": "1.1",
  "target_section": "1.1 절 제목",
  "type": "C",
  "title": "도판 제목 (한국어)",
  "description": "본문 문맥 및 [SRC-NN]과 직결되는 3~4문장 학술 줄글 해설 (표 형식 금지).",
  "prompt": "Concrete English visual prompt + STYLE_A/B/C suffix",
  "filename": "ch01_01_C.png",
  "aspect_ratio": "16:9",
  "method": "nano_banana_pro"
}
```

- `type`: `"A"` (현장 실사, `4:3`), `"B"` (스튜디오 표본, `4:3`), `"C"` (도해·인포그래픽, `16:9`), `"D"` (정량 차트, `16:9`, `method: "python"`).

---

## 2. 유형별 표준 스타일 서픽스 (Prompt Suffix Standard)

### 유형 A — 현장 다큐멘터리 실사 (`4:3`, Zero-Text)
```text
Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, crisp natural depth-of-field, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

### 유형 B — 스튜디오 접사·표본 실사 (`4:3`, Scale Bar Only)
```text
Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral metric scale bar at bottom without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

### 유형 C — 교재 개념도·기작 도해 (`16:9`)
- **Track 1 (Nano Banana Pro `2K` 단문 한글 라벨 모드 — 라벨 ≤ 10~12개)**:
```text
Clean educational university textbook vector illustration, flat vector style with subtle shading on pure white background (#FFFFFF), crisp Korean labels in bold clear sans-serif font (Noto Sans KR / Malgun Gothic), consistent textbook palette: primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557. Render ONLY the exact specified Korean label strings in single quotes; strictly NO pseudo-Chinese characters, NO gibberish text, NO question marks, NO watermark, aspect ratio 16:9.
```
- **Track 2 (완전 무문자 사실화 / `Pillow` 후처리 베이스 모드)**:
```text
Publication-grade editorial scientific illustration on pure white background (#FFFFFF), richly shaded painterly scientific art (Nature / Scientific American style), strictly NO cartoon or childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO captions, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## 3. 유형 D — 순수 Python (`matplotlib`) 300 DPI 출판 차트 표준 규칙

1. **캔버스 규격**: `fig = plt.figure(figsize=(2560 / 300, 1440 / 300), dpi=300, facecolor="white")` → 정확히 `2560 × 1440 px` (`16:9`).
2. **한글·부호 설정**:
   ```python
   plt.rcParams["font.family"] = "Malgun Gothic"
   plt.rcParams["axes.unicode_minus"] = False
   ```
3. **표준 색채 상수**:
   ```python
   C_GREEN = "#3A7D44"
   C_ORANGE = "#E07A2E"
   C_BROWN = "#8B5E3C"
   C_BLUE = "#3B82C4"
   C_NAVY = "#1D3557"
   C_GRAY_SLICE = "#CBD5E1"
   C_TEXT = "#1E293B"
   C_MUTED = "#475569"
   C_GRID = "#E2E8F0"
   ```
4. **레이아웃 규범**:
   - 상단 좌측 정렬 제목(`fontsize=15.5, fontweight="bold", color=C_NAVY`) + 부제(`fontsize=9.5, color=C_MUTED`).
   - 상·우측 축선 제거(`spines["top"].set_visible(False)`, `spines["right"].set_visible(False)`), 점선 보조선(`linestyle="--", color=C_GRID, zorder=0`).
   - 우측·하단 요약 지표 카드나 범례 카드는 메인 축과 분리된 독립 정규화 축(`ax_card = fig.add_axes([x, y, w, h]); ax_card.axis("off")`)에 `FancyBboxPatch`로 그려 모서리 왜곡과 텍스트 겹침을 방지한다.
   - 하단 좌측(`0.05, 0.045`)에 검증된 출처(`자료: ...`)를 반드시 기입한다.

---

## 4. `Pillow` 픽셀 정밀 한글 오버레이 보정 패턴 (`polish_overlays`)

유형 C 고밀도 도해에서 특정 박스 텍스트 1~2곳에 자모 오류가 발견되었거나 미니 그래프 곡선이 부정확할 때, 전체 이미지를 버리지 않고 해당 영역만 정밀 보정한다.

```python
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"

def patch_centered_text_box(im: Image.Image, box: tuple[int, int, int, int], lines: list[str], sizes: list[int], colors: list[tuple[int, int, int]], bg_color=(255, 255, 255), line_gap: int = 10):
    draw = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    draw.rectangle([x0, y0, x1, y1], fill=bg_color)
    fonts = [ImageFont.truetype(FONT_BOLD, sz) for sz in sizes]
    bboxes = [draw.textbbox((0, 0), t, font=f) for t, f in zip(lines, fonts)]
    heights = [bb[3] - bb[1] for bb in bboxes]
    cur_y = y0 + (y1 - y0 - (sum(heights) + line_gap * (len(lines) - 1))) / 2
    cx = (x0 + x1) / 2
    for txt, fnt, col, bb, h in zip(lines, fonts, colors, bboxes, heights):
        w = bb[2] - bb[0]
        draw.text((cx - w / 2 - bb[0], cur_y - bb[1]), txt, font=fnt, fill=col)
        cur_y += h + line_gap
```

보정 후 반드시 `manifest.json`의 `width`, `height`, `bytes`를 재동기화하고 `read_file`로 최종 육안 확인한다.

---

## 5. `manifest.json` 및 `qa_grid_chNN.jpg` 컨택트 시트 규격

1. **`manifest.json`**: 단원 폴더(`by_chapter/<chNN>/manifest.json`)에 모든 도판의 `id`, `filename`, `type`, `method`, `aspect_ratio`, `width`, `height`, `bytes`, `status`를 `Pillow`로 실측해 기록한다.
2. **QA 컨택트 시트 (`qa_grid_<chNN>.jpg`)**:
   - 단원 전체 도판(10~15장)을 `4×3` 또는 `4×4` 고해상도 격자(`JPEG quality=90`)로 합성하고, 각 셀 하단에 `그림 N-KK | 파일명 | 유형` 라벨 바를 부착하며 마지막 셀에 무결성 요약 박스를 배치한다.
   - 에이전트가 `read_file`로 컨택트 시트 1장을 먼저 스캔해 이상 징후(오탈자·왜곡·색채 이탈·잘림)를 신속히 포착한 뒤, 의심 도판만 원본 PNG를 `read_file`로 확대 정밀 판독한다.

---

## 6. 5대 시각 감수 게이트 (`V-01 ~ V-05`) 반려·재처리 기준

| 코드 | 항목 | 즉시 반려(Reject) 및 재처리 기준 |
| :---: | :--- | :--- |
| **V-01** | 도메인·해부·생육단계 정확성 | 유묘에 꽃/이삭 혼입, 식별 기관(잎혀·잎귀·줄기 단면·뿌리 구조 등) 오류, 물리/화학적 기작 왜곡 |
| **V-02** | 타이포그래피 무결성 | 한글 자모 깨짐·오탈자·위조 한자·외계 글자·물음표(`?`) **단 1건이라도 존재** |
| **V-03** | 본문·서지 수치 일치성 | 그래프 막대 비율·합계·축 단위·회귀 점근선이 본문 및 `[SRC-NN]` 근거와 불일치 |
| **V-04** | 현장 현실성·안전·윤리 | 한국 영농·현장 환경과 이질적인 배경, 작업자 PPE 미착용, 인물 정면 얼굴 노출, 상표·로고 노출 |
| **V-05** | 색채·해상도·조판 일관성 | 표준 5색 팔레트 이탈, 배경 오염, 텍스트·테두리 잘림/겹침, `2K` 미만 저해상도, 워터마크 흔적 |
