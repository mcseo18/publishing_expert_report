---
name: textbook-visual-director
description: 『최신 잡초방제학(weed_control)』에서 검증된 대학교재 실물 도판 제작 표준(A/B/C/D 4유형 분류 · 3계층 하이브리드 생성[fal.ai/Google Nano Banana Pro 2K + Python matplotlib 300 DPI + Pillow 오버레이 보정] · 4단계 품질 게이트[V-01~V-05 멀티모달 시각 감수 + QA 컨택트 시트 + manifest.json] · DOCX/HTML/네이버 블로그 최적 임베딩)을 전문 교재·보고서 시각화 제작 전반에 적용하는 스킬.
---

# textbook-visual-director — 전문 교재 실물 도판 4유형·3계층·4게이트 표준 제작 스킬

본 스킬은 `C:\smc_drive_desk\smc_drive\lecture\weed_control`에서 전권 705점 실물 도판(405점 본문 도판 + 300점 도감)을 출판급 품질로 완결한 검증 방법론을 범용 전문 교재·보고서 플랫폼에 표준화한 지침이다.

## 1. 도판 4유형 분류 체계 (`A / B / C / D`) 및 파일명 규약

단원별 실제 원고(`chapters/chNN.mdx`)를 정독해 각 절(`##`)의 핵심 개념·메커니즘·수치·현장 사례에 1:1 매칭되는 도판(단원당 최소 10~15점)을 아래 4유형으로 기획한다.

| 유형 | 명칭 | 표준 화면비 | 표준 해상도 | 생성 엔진 (Tier) | 텍스트·표기 규율 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| **A** | **현장 다큐멘터리 실사** | `4:3` | `2K` (`~2400×1792`, PNG) | Nano Banana Pro (T2I / `/edit`) | **완전 무문자 (`ZERO-TEXT`)**, 워터마크·상표 금지, 한국형 현장 경관, 인물 뒷모습·PPE 준수 |
| **B** | **스튜디오 접사·표본 실사** | `4:3` | `2K` (`~2400×1792`, PNG) | Nano Banana Pro (T2I / `/edit`) | 순백색 배경(`#FFFFFF`), 균일 조명, **단순 눈금자(`10 mm` / `10 cm` 또는 무문자 스케일바) 외 문자 일체 금지** |
| **C** | **교재 개념도·기작 도해·인포그래픽** | `16:9` | `2K` (`~2752×1536`, PNG) | Nano Banana Pro (T2I / `/edit`) + 선택적 Python `Pillow` 오버레이 | 표준 5색 팔레트·순백 배경, **Two-Track 타이포그래피 정책** 준수, **물음표(`?`) 절대 금지** |
| **D** | **정량 통계 그래프·수리모델 곡선** | `16:9` | `2560×1440` (`300 DPI`, PNG) | **100% 순수 Python (`matplotlib` / `RDKit`)** | **생성형 AI 단독 생성 절대 금지**, 맑은 고딕(`Malgun Gothic`), 3D 효과 금지, 하단 출처(`자료: ...`) 명시 |

- **표준 파일명**: `chNN_KK_X.png` (예: `ch01_01_C.png`, `ch01_02_A.png`, `ch01_08_D.png`, `ch01_12_B.png`) 또는 플랫폼 확장 ID `fig_chNN_vKK.png` (메타데이터 `type: "A"|"B"|"C"|"D"` 필수 기록).
- **도감/개체별 다각도 세트(선택)**: 생물종·품종·장비 등 도감형 단원에서는 개체당 6구도(`1: 유묘/초기`, `2: 성체/전체`, `3: 화기/열매/핵심부`, `4: 식별 접사`, `5: 종자·번식체+스케일바`, `6: 현장 군락`)를 적용한다.

## 2. 교과서 통일 디자인 시스템 (색채·폰트·해상도)

- **표준 5색 팔레트 (전권·유형 C/D 완전 통일)**:
  - 주조 작물·정상 녹색: `#3A7D44` (진한 헤더 `#1B4332`)
  - 강조·경고·스트레스 주황: `#E07A2E`
  - 토양·기질 갈색: `#8B5E3C`
  - 수계·기후 청색: `#3B82C4`
  - 학술 감청색(제목·축): `#1D3557`
  - 보조 중립색: 본문 `#1E293B`, 보조 `#475569`, 격자 `#E2E8F0`, 비강조 영역 `#CBD5E1`, 배경 `#FFFFFF`
- **표준 API 호출 파라미터**:
  - **fal.ai 백엔드 (`FAL_KEY`)**: `fal-ai/nano-banana-pro` (신규 생성) / `fal-ai/nano-banana-pro/edit` (참조 편집), `resolution="2K"`, `output_format="png"`, `aspect_ratio="4:3"|"16:9"`, `num_images=1`, `enable_web_search=False` (부가 과금 및 외부 스타일 혼입 차단).
  - **Google Gemini 백엔드 (`GEMINI_API_KEY`)**: `nano-banana-pro-preview` → `gemini-nano-banana-2.1` → `gemini-3.1-flash-image` 폴백 체인.
  - **동시 실행·캐시 재개**: `asyncio.Semaphore(4~6)` 또는 `ThreadPoolExecutor(max_workers=4~6)`로 병렬 생성하되, 이미 정상 크기(`> 30 KB`) 파일이 존재하면 캐시 재사용하고, 검수 반려 항목만 `--only <filename>`으로 선택 재생성한다.

## 3. 3계층(3-Tier) 하이브리드 생성 파이프라인

1. **Tier 1 — Nano Banana Pro 단독 생성 (T2I)**: 일반 현장 실사(A), 거시 대비 표본(B), 단문 라벨(8~12개 이하) 개념도·비교도·연표(C).
2. **Tier 2 — 참조 편집(`/edit`) & `Pillow` 후처리 오버레이 하이브리드**:
   - 공인 표본 사진 표준화(순백 배경·스케일바 통일)나 지도·분자식 밑그림의 일러스트화에는 `fal-ai/nano-banana-pro/edit`(`image_urls`) 사용.
   - 고밀도 도해(마인드맵, 의사결정 트리, 복합 수식 카드)에서 한글 자모 깨짐이나 미니 곡선 왜곡이 1건이라도 발견되면, **`polish_chNN_overlays.py`** 패턴으로 `PIL.ImageDraw` + `C:/Windows/Fonts/malgunbd.ttf`를 사용해 해당 박스·배지·곡선 영역만 픽셀 정밀도로 덮어 보정한다.
3. **Tier 3 — 순수 Python 코드 렌더링 (`$0`, 오차 0%)**:
   - 모든 정량 데이터 그래프·히트맵·회귀곡선·생육 달력(유형 D)은 `matplotlib`(`figsize=(2560/300, 1440/300), dpi=300`)으로 생성한다.
   - 요약 정보 카드나 범례 박스는 본 축과 분리된 독립 정규화 축(`fig.add_axes([...])` + `FancyBboxPatch`)을 사용해 텍스트 겹침과 모서리 왜곡을 원천 차단한다.
   - 순수 2D 화학 구조식은 `RDKit`으로 생성한다.

## 4. 4단계 품질 보증 게이트 (Gate 1 ~ Gate 4)

### Gate 1. 프롬프트 사전 정제 (`Prompt Sanitizer`)
- **생육단계·속성 충돌 제거**: 유묘/초기 단계 컷에서 성체·개화·결실 어휘(`panicle, flower, seed head, awn, achene`)를 제거하고, 종자·표본 컷에서 전초·잎·줄기 어휘를 제거한다.
- **명시적 해부·구조 대조 제약**: 혼동하기 쉬운 대상은 프롬프트에 **존재/부재 조건을 명시적으로 대조**한다(예: `clearly showing white membranous ligule and hairy auricles` vs `completely smooth bare junction with ZERO ligule and ZERO auricles`).
- **안전·윤리·법규 통제**: 농약·기계 작업 컷은 보호구(PPE) 착용과 무상표 장비(`unbranded generic`)를 명시하고, 인물은 뒷모습(`back view, face not visible`)으로 초상권을 보호한다.

### Gate 2. Two-Track 타이포그래피 통제 (한글 자모 결손 0건)
- **Track 1 (단문 네이티브 한글 — 유형 C `nano-banana-pro` `2K`)**: 프롬프트에 출력할 한글 문자열을 **작은따옴표로 정확히 열거**하고(`Render ONLY the exact specified Korean label strings in single quotes; strictly NO pseudo-Chinese characters, NO gibberish text, NO question marks`), 의사결정 분기 노드에도 물음표(`?`) 대신 평서 명사구(예: `'방제 기준 초과 여부'`)를 사용한다.
- **Track 2 (무문자 기반 + Python `Pillow`/HTML 캡션)**:
  - 실사(A·B)와 해부·메커니즘 사실화에는 **100% 영문 + `ABSOLUTE ZERO-TEXT`**를 강제하고, 이미지 직하단 학술 **줄글 해설**(`[그림 N-K]` + 3~4문장 평서체, 표 형식 금지)로 설명한다.
  - 고밀도 도해(C)에서 네이티브 한글 오류가 반복되면 빈 텍스트 박스(`blank clean label boxes without text`)로 생성 후 `Pillow`(`malgunbd.ttf`)로 정밀 오버레이한다.

### Gate 3. 멀티모달 시각 감수 (`read_file` Visual QA Loop & Contact Sheet)
- 단원 이미지 생성 직후 **`qa_grid_chNN.jpg`**(4×4 또는 3×2 고해상도 컨택트 시트)와 **`manifest.json`**(`Pillow` 검증 해상도·바이트·유형·상태)을 자동 생성한다.
- 에이전트가 **`read_file`** 도구로 컨택트 시트 및 개별 PNG를 직접 육안 판독하여 **5대 검수 게이트(`V-01`~`V-05`)**를 심사하고 `chNN_image_qa_report.md`에 기록한다:
  - **V-01 도메인·해부 정확성**: 생육단계 혼입·기관 위조·구조 오류 0건.
  - **V-02 타이포그래피 무결성**: 한글 자모 깨짐·오탈자·위조 한자·물음표(`?`) 0건.
  - **V-03 정량 수치 일치성**: 본문·참고문헌 수치 및 비율과 100% 일치.
  - **V-04 현장 현실성·안전·윤리**: 한국 현장 적합성, PPE 착용, 초상권 보호, 상표 미노출.
  - **V-05 색채·해상도·조판 일관성**: 5색 팔레트 준수, `2K`(`>=2000×1400`) / `300 DPI`, 테두리 잘림·겹침·워터마크 0건.
- 1개라도 반려되면 즉시 `--only <filename>` 재생성 또는 `Pillow` 오버레이 보정 후 `read_file` 재검수 → `manifest.json` 동기화까지 완료한다.

### Gate 4. 저장소 분리 보관 및 멀티포맷 출판 연동
- **이중 저장소 분리 보관**: 단원별 폴더(`projects/<pid>/assets/by_chapter/<chNN>/` 및 `E:\SMC_Report_Platform_Data\projects\<pid>\visuals\by_chapter\<chNN>\`)에 이미지 PNG, `prompts_and_descriptions.md`/`.json`, 개별 `<fig_id>_prompt.txt`, `manifest.json`, `qa_grid_<chNN>.jpg`를 함께 저장한다.
- **Word(`.docx`) 삽입 규격**: `16:9` 도판(유형 C·D)은 본문 폭 **`155 mm`** 중앙 정렬, `4:3` 도판(유형 A·B)은 본문 폭 **`135 mm`** 중앙 정렬, 직하단에 `[그림 N-K]` 제목과 줄글 해설을 배치한다(도판 설명용 표 사용 금지).
- **오프라인 단일 HTML(`.html`) 규격**: `RGBA` 차트는 `.convert("RGB")` 변환 + 최대 폭 `1920 px` 리사이즈 후 `WebP(quality=92)` Base64 Data URI로 내장하여 외부 네트워크 의존 0건을 유지한다.
- **네이버 블로그(`SmartEditor ONE`) 규격**: 외부 CSS·base64를 제거하고 인라인 스타일만 사용하며, 업로드를 위한 번호순 JPG(최대 폭 `1600 px`, `quality=90`)를 별도 폴더로 분리 저장하고 본문에 `[사진 NN]` 안내 상자 + 캡션 + 유니코드 수식(`CO₂`, `m⁻²`, `<sub>`/`<sup>` 미사용)을 배치한다(이미지 45장 초과 시 글 자동 분할).

## 5. 상세 프롬프트 템플릿 및 실행 참조
- 유형별 영문 스타일 서픽스, `figure_prompts.json` 스키마, `matplotlib` 차트 템플릿, `Pillow` 오버레이 보정 패턴, 시각 감수 체크리스트 전문은 [references/prompt_templates_and_qa.md](references/prompt_templates_and_qa.md)를 참조한다.
- 플랫폼 자동 실행 엔진: `scripts/context_visual_director.py` (문맥 기반 기획 + 단원별 설명/프롬프트·`manifest.json`·`qa_grid` 자동 생성 + Nano Banana Pro / fal.ai / Python 하이브리드 생성).
