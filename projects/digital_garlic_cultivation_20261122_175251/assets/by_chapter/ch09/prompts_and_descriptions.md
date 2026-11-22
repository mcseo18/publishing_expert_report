# 제9장. 농작업 무인 자동화와 RTK-GPS 자율주행 농기계 기술 — 문맥 기반 시각화 기획서 (이미지 번호 · 설명 · 프롬프트)

- **단원 ID**: `ch09`
- **총 시각화 수**: **10종** (Google Gemini Nano Banana 전량 제작)
- **생성 시각**: `2026-11-22T09:10:12+00:00`

---

## [그림 9-1] 정밀 노지 마늘 재배 포장에서의 자율주행 트랙터 작업 전경

- **이미지 번호 / 파일명**: `그림 9-1` / `fig_ch09_v01.png`
- **문서 결합 절(Section)**: 단원 개요
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 9-1] 본 사진은 검은색 비닐 멀칭이 시공된 규칙적인 마늘 이랑 사이를 고정밀 자율주행 트랙터가 주행하며 정밀 방제 작업을 수행하는 전경을 보여준다. 캐빈 상단에 장착된 RTK-GNSS 수신기 안테나와 작업기 센서가 결합되어 센티미터 수준의 오차 범위 내에서 마늘 생육 라인을 정확히 추종한다. 이처럼 정밀 농업 기반의 자율주행 농기계 기술은 마늘 경운, 파종, 방제 등 전 생육 주기 작업의 효율성을 비약적으로 향상시킨다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
An ultra-sharp documentary field photograph of a modern autonomous tractor driving precisely along elevated raised beds of young green garlic (Allium sativum) plants covered with black plastic mulch. Golden morning sunlight illuminates the long straight parallel crop rows extending towards the horizon. The tractor features a dual RTK-GNSS antenna dome on its cab roof, rugged all-terrain narrow tires aligned accurately in the furrows without disturbing garlic foliage, clear rural agricultural research landscape in crisp focus. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 9-2] 기준국-이동국 간 반송파 위상 보정 및 RTK 측위 메커니즘

- **이미지 번호 / 파일명**: `그림 9-2` / `fig_ch09_v02.png`
- **문서 결합 절(Section)**: 9.1 센티미터급 RTK-GNSS 측위 원리와 현장 통신 인프라 구축
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 9-2] 궤도 상의 복수 GNSS 위성으로부터 발신된 반송파 신호가 지상 고정 기준국과 농기계 이동국에 동시 도달하는 기하학적 측위 원리를 시각화한 모식도이다. 알려진 절대 좌표에 위치한 기준국이 위상 측정치를 기반으로 대기 지연 및 위성 오차 성분을 실시간 계산하여 무선 통신망을 통해 트랙터 이동국으로 보정 데이터를 전송한다 [SRC-104]. 이동국은 이 차분 데이터를 통해 잔여 오차를 상쇄함으로써 수 센티미터급의 초고정밀 위치 좌표를 산출한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A clean scientific visual illustration on a pure white background demonstrating RTK-GNSS positioning principles for agriculture. Three navigation satellites in the upper field emit distinct translucent cyan and amber carrier-wave propagation cones toward a terrestrial base station tripod antenna and a tractor rover antenna. Visible mathematical wave vectors indicate phase differential correction links and atmospheric ionosphere delay layers, rendered in an elegant, richly shaded academic textbook style with crisp geometry. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## [그림 9-3] 농업용 트랙터 캐빈 루프에 장착된 초정밀 RTK 수신기와 5G 텔레매틱스 모듈

- **이미지 번호 / 파일명**: `그림 9-3` / `fig_ch09_v03.png`
- **문서 결합 절(Section)**: 9.1 센티미터급 RTK-GNSS 측위 원리와 현장 통신 인프라 구축
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 9-3] 자율주행 농기계의 상단 루프에 견고하게 체결된 고정밀 RTK-GNSS 이중 주파수 패치 안테나와 셀룰러 텔레매틱스 통신 유닛의 매크로 클로즈업이다. 열악한 노지 환경의 진동, 분진, 강우를 견디도록 IP67 등급의 방수·방진 하우징으로 밀폐되어 있으며, 후면에는 차분 보정 신호를 수신하기 위한 저지연 무선 링크 케이블이 연결되어 있다 [SRC-100]. 수집된 위상 데이터는 트랙터 내부 ECU(전자 제어 장치)로 즉각 전송되어 센티미터급 조향 기준점을 형성한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A detailed commercial macro photograph of an agricultural RTK-GNSS smart antenna module and cellular communication dome securely mounted on the painted metal roof bracket of a tractor. High-resolution texture of the white weatherproof composite radome casing, brass RF connectors, heavy-duty insulated cabling, and status indicator LEDs glowing softly under natural diffuse overcast daylight, with blurred green garlic field ridges visible in the soft background. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 9-4] 마늘 재배 단지 외곽에 설치된 농업용 RTK 고정 기준국 인프라

- **이미지 번호 / 파일명**: `그림 9-4` / `fig_ch09_v04.png`
- **문서 결합 절(Section)**: 9.1 센티미터급 RTK-GNSS 측위 원리와 현장 통신 인프라 구축
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 9-4] 광활한 마늘 생산 단지의 가시선을 확보하기 위해 필드 경계에 가설된 독립형 무선 RTK 기준국(Base Station) 스테이션의 전경이다. 삼각대 상단의 초정밀 헬리컬 안테나와 함께 무정전 전원 공급을 위한 태양광 패널 및 전파 송신용 UHF/LTE 안테나 타워가 통합 구성되어 있다 [SRC-100]. 이 인프라는 지형지물에 의한 멀티패스 및 전파 음영 구역을 최소화하여 단지 내 모든 자율 농기계에 끊김 없는 보정 데이터를 송출한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A photorealistic documentary shot of a solar-powered agricultural RTK base station erected on an elevated field boundary beside vast commercial garlic beds. The station features a calibrated high-precision choke-ring GNSS antenna mounted on a heavy survey tripod, a small solar photovoltaic panel, an industrial battery enclosure, and an omnidirectional radio whip antenna. Vast rows of thriving green garlic plants stretch across the fertile countryside under a blue sky. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 9-5] 순응 제어(Pure Pursuit) 및 횡방향 경로 추종 기하학 모델

- **이미지 번호 / 파일명**: `그림 9-5` / `fig_ch09_v05.png`
- **문서 결합 절(Section)**: 9.2 자율주행 트랙터의 조향 제어 및 경로 계획(Path Planning) 알고리즘
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 9-5] 자율주행 트랙터의 목표 경로 추종을 위한 순응 제어(Pure Pursuit) 알고리즘의 기하학적 벡터 구성을 도식화한 학술 일러스트레이션이다. 마늘 두둑 사이의 목표 궤적선(Target Path)과 차량의 현재 위치(Pcurrent) 사이의 수직 이격인 횡방향 오차(Cross-Track Error) 및 전방 주시 거리(Lookahead Distance)를 기반으로 전륜 조향각(δ)이 산출되는 원리를 보여준다. 이러한 정밀 조향 제어는 좁은 이랑 사이에서 마늘 인경의 기계적 손상을 완벽히 방지한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A refined scientific vector-geometry illustration on a pristine white background depicting vehicle kinematic Pure Pursuit steering algorithms over an agricultural grid. A stylized top-down tractor chassis shows front-wheel steering deflection, a curved pursuit arc terminating at a forward lookahead reference coordinate, and orthogonal cross-track deviation vectors relative to a straight green crop centerline. Clear geometric lines, circular trajectory curves, and angle arcs rendered in high-end technical textbook style. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---

## [그림 9-6] 트랙터 전륜 전동-유압 조향 액추에이터와 휠 각도 센서의 미세 구동

- **이미지 번호 / 파일명**: `그림 9-6` / `fig_ch09_v06.png`
- **문서 결합 절(Section)**: 9.2 자율주행 트랙터의 조향 제어 및 경로 계획(Path Planning) 알고리즘
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 9-6] 자율주행 트랙터의 전륜 조향 축에 장착된 전동-유압 비례 제어 밸브 및 휠 각도 센서(Wheel Angle Sensor)의 실제 작동부 매크로 사진이다. 실시간 조향 알고리즘이 연산한 목표 조향각에 맞추어 유압 실린더가 수 밀리미터 단위로 미세 신장하며 차륜 각도를 즉각 교정한다. 흙먼지와 수분이 가득한 마늘 고랑 주행 환경에서도 지속적인 정밀 추종 성능을 유지할 수 있도록 설계된 기계 장치부이다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A razor-sharp mechanical macro photograph of an electro-hydraulic steering valve assembly and rotary wheel angle potentiometer mounted on the heavy front steering knuckle of a farm tractor. Metallic cylinder rod reflecting light, hydraulic high-pressure hoses with brass crimps, grease fitting detail, positioned right above the damp soil of a furrow between green garlic beds, natural daylight highlighting metal textures and durable industrial sensors. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 9-7] 3D 비전 기반 마늘종(추대) 자동 절단·피킹 로봇 엔드이펙터

- **이미지 번호 / 파일명**: `그림 9-7` / `fig_ch09_v07.png`
- **문서 결합 절(Section)**: 9.3 추대 제거(마늘종 꺾기) 및 중경 제초 자동화 로봇 기술
- **시각화 유형**: `photorealistic_macro`

### 문맥 기반 상세 설명 (줄글)
[그림 9-7] 마늘 생육 후기 마늘종(꽃대)을 자동으로 식별하여 절단하는 스마트 농업 로봇의 정밀 엔드이펙터(End-Effector) 클로즈업 사진이다. 다관절 로봇 팔 선단에 탑재된 스테레오 깊이 카메라와 고성능 조명이 마늘 엽초 사이로 솟아오른 둥근 꽃봉오리와 줄기를 인식하고 초소형 전동 전정 가위가 정확한 위치를 집어내 절단한다 [SRC-103]. 이 자동화 기술은 마늘 인경으로의 양분 집중을 유도하는 필수 농작업의 노동력을 획기적으로 절감한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
An ultra-sharp macro photograph of a robotic picking gripper operating on a standing mature garlic plant. A specialized miniature carbon-fiber robotic claw with dual sharp tungsten cutter blades holds and snips the coiled green floral scape (garlic scape) just above the strap-like leaves. An integrated compact stereo depth camera and circular LED ring light illuminate the dew droplets on the garlic sheath in crisp botanical detail. Professional studio macro specimen photography on pure seamless white background (#FFFFFF), soft even studio lighting, true-to-life color and razor-sharp macro focus, clean neutral millimeter scale bar without extraneous text, strictly NO watermark, aspect ratio 4:3.
```

---

## [그림 9-8] 이랑 위를 자율 주행하며 중경 제초를 수행하는 필드 로봇 플랫폼

- **이미지 번호 / 파일명**: `그림 9-8` / `fig_ch09_v08.png`
- **문서 결합 절(Section)**: 9.3 추대 제거(마늘종 꺾기) 및 중경 제초 자동화 로봇 기술
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 9-8] 마늘 두둑 양측을 걸치고 주행하는 고상형 자율주행 소형 필드 로봇이 마늘 주간 사이의 잡초를 기계적으로 제거하는 현장 사진이다. 지상고가 높은 차체 하부에 초소형 회전 칼날과 레이저 센서가 부착되어 있어 마늘 원줄기에는 손상을 주지 않고 잡초 유묘만을 정밀 타격한다. RTK-GNSS 기반의 오차 없는 주행과 결합되어 제초제 살포량을 최소화하고 지속 가능한 친환경 마늘 생산을 뒷받침한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A crisp documentary field photograph of a lightweight high-clearance autonomous agricultural weeding robot straddling a raised bed of vibrant green garlic plants. The four-wheeled robot chassis is equipped with downward-facing multispectral weed-detection optics and miniature rotating inter-row rotary tines carefully clearing small weeds between plastic mulch openings. Bright morning sun, moist field soil, and pristine rows of healthy garlic. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 9-9] 메시 네트워크 통신 기반 대규모 마늘 단지 자율 군집 로봇 작업

- **이미지 번호 / 파일명**: `그림 9-9` / `fig_ch09_v09.png`
- **문서 결합 절(Section)**: 9.4 자율 군집 농작업 제어 시스템과 노지 필드 안전 메커니즘
- **시각화 유형**: `photorealistic_field`

### 문맥 기반 상세 설명 (줄글)
[그림 9-9] 넓은 면적의 마늘 재배 단지에서 분산형 메시 네트워크(Mesh Network)로 상호 연결된 3대의 자율주행 소형 작업 로봇이 협력 작업을 수행하는 장면이다. 중앙 서버의 전체 작업 할당 아래 각 로봇은 상호 위치와 작업 상태를 실시간 송수신하며 일정 간격을 유지하고 중복 작업을 방지한다. 이와 같은 군집 시스템은 개별 장비의 고장 시에도 전체 작업 중단 없이 유연하게 농작업을 지속할 수 있는 장점을 제공한다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
A wide-angle agricultural field photograph showing a synchronized swarm of three compact autonomous electric farm rovers operating harmoniously across an extensive commercial garlic plantation. The rovers maintain equidistant spacing across parallel raised beds, with omnidirectional antennas and slim sensor masts visible. Uniform parallel rows of emerald-green garlic foliage stretch under a partly cloudy sky during late afternoon golden hour. Photorealistic documentary field photograph, natural daylight, authentic Korean agricultural and environmental setting, accurate biological and technical morphology, high detail, strictly NO text, NO letters, NO numbers, NO logos, NO watermark, aspect ratio 4:3.
```

---

## [그림 9-10] 다중 센서 융합 기반 필드 안전 보호막 및 비상 정지·폴백 메커니즘

- **이미지 번호 / 파일명**: `그림 9-10` / `fig_ch09_v10.png`
- **문서 결합 절(Section)**: 9.4 자율 군집 농작업 제어 시스템과 노지 필드 안전 메커니즘
- **시각화 유형**: `scientific_anatomy`

### 문맥 기반 상세 설명 (줄글)
[그림 9-10] 노지 농작업 로봇에 구축된 3단계 안전 보호 구역(Safety Envelope)과 다중 센서 융합 구조를 시각화한 학술 단면도이다. 차체 상부의 3D 라이다(LiDAR) 반구형 스캔 영역, 전방 밀리미터파 레이더 빔, 초음파 근접 센서 구역이 단계별로 중첩되어 비정형 장애물 출현 시 즉시 비상 정지를 수행한다. 동시에 RTK 보정 신호 단절 시 IMU 기반의 추측 항법으로 전환되어 장비를 안전 속도로 감속시키는 폴백(Failover) 모드의 메커니즘을 상세히 보여준다.

### 나노바나나 생성 프롬프트 (Pure English · Zero-Text)
```text
An academic 3D scientific technical illustration on a pure white background showing the safety perception envelope of an autonomous agricultural robot in a garlic field. Translucent concentric sensor lobes emanate outward: a dome-shaped 3D LiDAR point cloud in cyan, forward millimeter-wave radar cones in deep amber, and close-proximity ultrasonic detection zones in soft violet. Clear dimensional safety perimeter boundaries surround the machine with subtle internal IMU and failover architecture schematics. Clean educational university textbook editorial scientific illustration on pure white background (#FFFFFF), consistent textbook palette (primary green #3A7D44, accent orange #E07A2E, soil brown #8B5E3C, water blue #3B82C4, academic navy #1D3557), richly shaded publication-grade clarity, strictly NO childish clipart. ABSOLUTE ZERO-TEXT REQUIREMENT: strictly NO text, NO words, NO letters, NO numbers, NO Korean Hangul, NO English labels, NO question marks, NO watermarks anywhere in the image, aspect ratio 16:9.
```

---
