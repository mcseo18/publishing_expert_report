# 제11장. 컴퓨터 비전 및 딥러닝 기반 디지털 병해충·생리장해 진단 — 문맥 기반 시각화 기획서 (이미지 번호 · 설명 · 프롬프트)

- **단원 ID**: `ch11`
- **총 시각화 수**: **10종** (Google Gemini Nano Banana 전량 제작)
- **생성 시각**: `2026-11-22T09:12:12+00:00`

---

## [그림 11-1] 다양한 자연광 환경에서의 마늘 엽병 병징 영상 데이터 수집 환경

- **이미지 번호 / 파일명**: `그림 11-1` / `fig_ch11_v01.png`
- **문서 결합 절(Section)**: 11.1 마늘 병징 영상 데이터베이스 구축 및 데이터 증강(Augmentation)
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 11-1] 딥러닝 진단 모델의 일반화 성능을 높이기 위해 야외 마늘 포장에서 진행되는 정밀 병징 영상 촬영 과정을 보여줍니다. 연구원이 비반사 캘리브레이션 컬러 차트와 확산 조명 텐트를 활용하여 녹병(Puccinia allii)과 잎마름병 증상이 발생한 마늘 잎의 각도와 조도를 정밀하게 기록합니다. [SRC-100]에 기술된 바와 같이 실제 농작업 현장의 가변적인 기상 요소를 반영한 고품질 데이터베이스 구축의 기초가 됩니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
Documentary-style agricultural photography showing a research technician in a sunlit garlic field using a professional DSLR camera mounted on an adjustable ground tripod. A portable translucent diffusion tent shades a diseased garlic plant (Allium sativum) with elongated straplike leaves exhibiting rust pustules. Beside the garlic leaves rests a miniature 24-patch color calibration chart and a millimeter scale bar on the rich dark mulch soil, capturing accurate surface texture under diffuse daylight, sharp focus on botanical foliage with natural background garlic rows extending to the horizon. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 11-2] 마늘 잎마름병 병반 영상의 데이터 증강(Augmentation) 파이프라인

- **이미지 번호 / 파일명**: `그림 11-2` / `fig_ch11_v02.png`
- **문서 결합 절(Section)**: 11.1 마늘 병징 영상 데이터베이스 구축 및 데이터 증강(Augmentation)
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 11-2] 마늘 잎마름병(Stemphylium solani) 초기 병반이 형성된 단일 마늘 잎 원본 영상이 딥러닝 학습용 증강 데이터셋으로 변환되는 과정을 시각화한 과학 해부도입니다. 무작위 기하학적 회전, 배율 스케일링, 조도 밝기 변조, 가우시안 노이즈 주입 등의 다채로운 변형 과정을 통해 모델의 과적합을 방지하고 강건성을 확보합니다. [SRC-100]에서 강조한 데이터 증강 기법의 학술적 원리와 모델 일반화 기전을 명확히 설명합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A scientific botanical illustration on a pure white background demonstrating computer vision data augmentation transformations of a single diseased garlic leaf. The central garlic leaf (Allium sativum) with an oval tan leaf blight lesion with yellow halo branches into surrounding modified variants: 45-degree geometric rotation, horizontal mirror reflection, underexposed dark lighting, overexposed bright sunlight simulation, motion blur, and subtle pixel noise. Rendered in hyper-detailed photorealistic scientific art style with clean studio lighting and crisp fibrous leaf veins. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## [그림 11-3] 마늘 파총채벌레 가해 흔적 및 엽초 부위 객체 탐지(Object Detection) 시각화

- **이미지 번호 / 파일명**: `그림 11-3` / `fig_ch11_v03.png`
- **문서 결합 절(Section)**: 11.2 객체 탐지(YOLO) 및 이미지 분할을 활용한 병해충 식별
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 11-3] 마늘 줄기와 잎 엽초 틈새에서 발생하는 파총채벌레(Thrips tabaci)의 섭식 가해 부위를 초근접 매크로 촬영으로 포착한 장면입니다. 은백색 탈색 반점과 미세한 배설물 흔적이 엽맥을 따라 분포하며, 신경망 추론 모델이 특정 이상 영역을 분리하여 포착하는 객체 탐지 기술의 실제 대상을 선명하게 보여줍니다. [SRC-100]의 YOLO 등 실시간 탐지 알고리즘이 현장에서 미세 해충 피해를 신속히 판별하는 메커니즘을 뒷받침합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
Extreme macro photography of an upright garlic stem and leaf junction showing insect infestation. Tiny slender onion thrips crawl near longitudinal silver-white feeding scars and minute dark frass specks along the fibrous green cuticle of the Allium sativum sheath. Crisp shallow depth of field, natural optical refraction on translucent plant epidermal cells, sharp focus on pest morphology and chlorotic leaf tissue under soft directional morning light. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 11-4] 마늘 자주빛무늬병(흑반병) 병반의 인스턴스 픽셀 분할(Segmentation) 분석

- **이미지 번호 / 파일명**: `그림 11-4` / `fig_ch11_v04.png`
- **문서 결합 절(Section)**: 11.2 객체 탐지(YOLO) 및 이미지 분할을 활용한 병해충 식별
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 11-4] 마늘 잎 표면에 형성된 자주빛무늬병(Alternaria porri) 병반의 형태와 괴사 면적을 픽셀 단위로 정밀하게 분리하는 시맨틱 및 인스턴스 분할 원리를 도해합니다. 단순 바운딩 박스를 넘어 불규칙한 타원형 병반 가장자리의 동심원상 윤곽과 괴사 중심부를 정확한 경계선으로 추출함으로써 질병 심각도를 정량화합니다. [SRC-100]에서 논의된 컴퓨터 비전 기반 병해 진단 정량화 알고리즘의 핵심 과정을 묘사합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
Scientific cross-section and surface morphology illustration on a clean white background depicting a garlic leaf affected by purple blotch. The central elliptical lesion displays concentric dark purple rings fading into yellow chlorotic margins. Surrounding the lesion, translucent colored contour boundaries delineate the exact damaged necrotic zone versus the healthy green photosynthetic tissue, illustrating precise pixel-level image segmentation in an elegant editorial scientific textbook style. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## [그림 11-5] 수확 후 마늘 인편 기부의 뿌리응애(Aceria tulipae) 현미경적 피해 양상

- **이미지 번호 / 파일명**: `그림 11-5` / `fig_ch11_v05.png`
- **문서 결합 절(Section)**: 11.2 객체 탐지(YOLO) 및 이미지 분할을 활용한 병해충 식별
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 11-5] 마늘 인편 바닥의 줄기 기부와 인편 틈새에 서식하는 미세 뿌리응애 군집 및 그로 인한 조직 변색을 포착한 초고해상도 매크로 사진입니다. 현미경 렌즈를 통해 확대된 마늘 인피 표면의 거친 질감과 미세 해충의 군집 상태를 사실적으로 보여줍니다. [SRC-100]에서 다중 모달리티 데이터 융합과 초소형 객체 탐지 신경망이 미세 해충 진단에 필수적임을 보여주는 시각 자료입니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
High-magnification laboratory macro photograph of the basal plate of a harvested garlic bulb (Allium sativum). Translucent, microscopic bulb mites cluster inside tiny crevices between peeling fibrous outer protective scales and the ivory-white clove tissue. Delicate cellular papillae, fibrous root scars, and micro-lesions showing golden-brown oxidation, illuminated by coaxial laboratory ring lights revealing pristine microscopic surface details. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 11-6] 마늘 2차 생장(벌마늘)의 인편 내부 엽신 돌출 구조 단면

- **이미지 번호 / 파일명**: `그림 11-6` / `fig_ch11_v06.png`
- **문서 결합 절(Section)**: 11.3 2차 생장(벌마늘), 열개, 스펀지마늘 등 생리장해의 시각적 진단 알고리즘
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 11-6] 영양 과다 또는 기상 이상으로 인해 발생하는 마늘 2차 생장(벌마늘) 증상을 인편 종단면 절단을 통해 관찰한 매크로 사진입니다. 정상적인 휴면 인편 내부에서 새로운 영양 잎이 비정상적으로 자라나 외피를 뚫고 솟아나오는 구조적 결함을 상세히 드러냅니다. [SRC-100], [SRC-108]에 제시된 생리장해의 형태 계수(Shape Factor)와 내부 구조 패턴 인식 알고리즘의 대상 특징을 제시합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
Photorealistic botanical macro photograph of a dissected abnormal garlic bulb exhibiting secondary growth (witch's broom or split bulb). The outer papery skin has split open as internal individual cloves sprout miniature bright green shoot leaflets pushing upward through the clove apex. A longitudinal cross-section reveals elongated inner vegetative meristems instead of tight dormant cloves, displayed on a dark slate laboratory bench under crisp studio side lighting. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 11-7] 정상 마늘 조직과 스펀지마늘(Spongy Garlic) 유조직 붕괴 비교 단면

- **이미지 번호 / 파일명**: `그림 11-7` / `fig_ch11_v07.png`
- **문서 결합 절(Section)**: 11.3 2차 생장(벌마늘), 열개, 스펀지마늘 등 생리장해의 시각적 진단 알고리즘
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 11-7] 정상적인 단단한 마늘 인편 유세포 조직과 유조직 붕괴가 일어난 스펀지마늘의 내부 세포 구조를 정밀하게 대조한 과학 해부도입니다. 정상 세포의 팽윤하고 균일한 다각형 세포벽 구조와 달리, 스펀지마늘은 세포 간극 확장, 세포벽 융해 및 다공성 공간 형성이 두드러집니다. [SRC-100], [SRC-110]에서 언급된 미묘한 질감(Texture) 변화 및 내부 대사 이상을 딥러닝 모델이 감지하는 학술적 배경을 나타냅니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A scientific comparative anatomical illustration on a clean white background showing the internal tissue of garlic cloves. On the left, a healthy dense garlic clove cross-section with compact, turgid polygonal parenchyma cells rich in cytoplasmic starch granules. On the right, a spongy garlic (physiological breakdown) cross-section showing collapsed cell walls, large irregular air voids, desiccated fibrous strands, and porous spongy matrix. Richly shaded cellular detail in watercolor scientific textbook art style. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## [그림 11-8] 수분 불균형으로 인한 성숙 마늘 구의 열개(Bulb Cracking) 증상

- **이미지 번호 / 파일명**: `그림 11-8` / `fig_ch11_v08.png`
- **문서 결합 절(Section)**: 11.3 2차 생장(벌마늘), 열개, 스펀지마늘 등 생리장해의 시각적 진단 알고리즘
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 11-8] 생육 후기 급격한 수분 공급이나 토양 스트레스로 인해 외피가 파열되고 개별 인편이 외부로 노출된 마늘 열개 현상을 관찰한 사진입니다. 외피의 불규칙한 균열 패턴과 노출된 인편 표면의 산화 과정을 선명하게 포착하여 비정형적 생리장해의 특성을 보여줍니다. [SRC-100], [SRC-111]에서 설명한 면적 대비 균열 폭과 형태 변수를 알고리즘이 분석하는 기준을 제공합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
Photorealistic macro view of a mature harvested garlic bulb suffering from severe bulb cracking and dehiscence due to moisture fluctuation. The dry purple-striped white outer tunic has ruptured along the vertical meridians, widely exposing plump ivory cloves that are bulging outward with jagged fibrous tearing at the wrapper seams. Rested on dark loamy soil with razor-sharp macro focus and natural outdoor overcast lighting. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 11-9] 마늘 재배 포장에서 엣지 디바이스 기반 모바일 진단 앱을 구동하는 현장 실증

- **이미지 번호 / 파일명**: `그림 11-9` / `fig_ch11_v09.png`
- **문서 결합 절(Section)**: 11.4 엣지 디바이스 기반 모바일 현장 진단 애플리케이션 아키텍처
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 11-9] 통신망이 불안정한 농촌 포장에서 농업인이 스마트폰 단말기의 온디바이스(On-device) AI를 구동하여 마늘 잎의 상태를 실시간 촬영·진단하는 장면입니다. 스마트폰 화면에는 촬영된 마늘 잎과 추론 엔진이 즉시 생성한 진단 신뢰도 정보가 표시되며, 외부 클라우드 접속 없이 신속한 의사결정을 내릴 수 있습니다. [SRC-100]의 경량 딥러닝 모델(MobileNet, TinyYOLO)과 엣지 컴퓨팅 아키텍처의 현장 적용성을 입증합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
National Geographic style documentary photograph of an agricultural agronomist in a wide garlic field holding an industrial ruggedized smartphone above a healthy and partially spotted garlic canopy. The smartphone screen visibly renders a camera viewfinder targeting garlic leaves with real-time green focusing brackets. Morning sunlight illuminates the broad flat garlic foliage and raised cultivation beds covered in black plastic mulch, with soft natural bokeh in the background. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 11-10] 마늘 현장 진단용 엣지 컴퓨팅 신경망 경량화(양자화·가지치기) 파이프라인

- **이미지 번호 / 파일명**: `그림 11-10` / `fig_ch11_v10.png`
- **문서 결합 절(Section)**: 11.4 엣지 디바이스 기반 모바일 현장 진단 애플리케이션 아키텍처
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 11-10] 서버급 대규모 합성곱 신경망이 모바일 엣지 디바이스에 적합하도록 가지치기(Pruning)와 8비트 정수 양자화(INT8 Quantization)를 거치는 최적화 파이프라인 도해입니다. 복잡하고 무거운 신경망 가중치 텐서가 희소화(Sparsification) 및 압축되어 저전력 엣지 추론 가속기에서 저지연으로 구동되는 과정을 시각화합니다. [SRC-100] 및 연습문제 2번에서 다룬 모델 압축 기술과 클라우드 대비 엣지 추론의 장단점을 명확히 설명합니다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A sophisticated scientific system architecture illustration on a pure white background demonstrating neural network model compression for edge computing. On the left side, a dense multi-layered convolutional neural network processing garlic plant leaf images with thick interconnected floating-point weight matrices. Flowing toward the right, visual nodes dissolve through pruning filters and consolidate into a compact, ultra-streamlined quantized model represented by neat low-precision data nodes flowing into a microchip edge processor. Rendered in clean scientific editorial aesthetic with precise geometric styling. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---
