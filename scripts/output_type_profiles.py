"""참참살이 영농 AI 출판도우미 — 1차 산출물 6대 유형 프로필 및 파이프라인 맞춤 지침 엔진.

지원하는 1차 산출물 유형 (Primary Output Types):
1. textbook    : 교과서 · 전문 대학교재 (B5/신국판 · 4단계 이론→생리→현장→법규 · 연습문제 1:1 · 오해와 진실)
2. web_publish : 웹 출판 · 블로그 · 디지털 매거진 (반응형 HTML · 네이버 20태그 · 짧은 단락 · CTA)
3. lecture     : 강의 교재 · 워크북 · 세미나 핸드아웃 (주차별 강의안 · 학습목표 · 실습 체크리스트 · 토론)
4. report      : 연구 · 정책 · 기술 용역 보고서 (A4 · Executive Summary · 개조식/객관적 수치 · 정책 제언)
5. paper       : 학술 논문 · 체계적 리뷰 페이퍼 (IMRaD/Review · 국영문 초록 · 정량 근거 [SRC-NN] 집중)
6. storybook   : 이야기 책 · 농업 에세이 · 대중 교양서 (신국판 · 스토리텔링 · 현장 에피소드 · 쉬운 비유)
"""
from __future__ import annotations

from typing import Any

PRIMARY_OUTPUT_TYPES: dict[str, dict[str, Any]] = {
    "textbook": {
        "id": "textbook",
        "icon": "📘",
        "name_ko": "교과서",
        "subtitle_ko": "대학 전공 심화 · 전문 실무 표준 교재",
        "description_ko": "체계적 부·장·절 구성, 개념→생리메커니즘→현장적용→법규 4단계 흐름, 핵심 용어집, 1:1 문제-풀이, 오해와 진실, 풍부한 도판(A/B/C/D)을 갖춘 출판급 교재입니다.",
        "recommended_trim": "b5",
        "trim_formats": ["b5", "shinkuk", "a4"],
        "defaults": {
            "target_pages": 450,
            "chapter_count": 14,
            "visuals_per_chapter": 5,
            "target_audience": "대학 전공 심화, 대학원생, 연구자 및 선도 현장 실무자",
            "tone": "학술적이고 체계적인 대학교재 표준 문체(~이다/~한다)",
            "unit_label": "장(Chapter)",
            "include_exercises": True,
            "include_myths": True,
            "include_glossary": True,
            "include_executive_summary": False,
            "include_naver_hashtags": True,
            "visual_priority": {"A": 2, "B": 2, "C": 2, "D": 2},
            "citation_density": "high",
        },
        "custom_fields": [
            {"key": "structure_mode", "label": "단원 전개 구조", "type": "select", "options": ["4단계 표준(이론→생리→현장→법규)", "원리→사례→실습 3단계", "품종·생육단계별 전개"], "default": "4단계 표준(이론→생리→현장→법규)"},
            {"key": "include_exercises", "label": "이해도 점검 연습문제 + 1:1 정답·풀이 포함", "type": "checkbox", "default": True},
            {"key": "include_myths", "label": "오해와 진실 (현장 오해 교정 ≥3선) 포함", "type": "checkbox", "default": True},
            {"key": "include_glossary", "label": "단원별 핵심 용어집 (국·영문 표) 포함", "type": "checkbox", "default": True},
            {"key": "math_level", "label": "수식·정량 기준표 수준", "type": "select", "options": ["전공 심화 (생육모형·통계 포함)", "실무 표준 (핵심 기준표 위주)", "기초 입문 (쉬운 수치 해설)"], "default": "전공 심화 (생육모형·통계 포함)"},
        ],
    },
    "web_publish": {
        "id": "web_publish",
        "icon": "🌐",
        "name_ko": "웹 출판",
        "subtitle_ko": "네이버 블로그 · 디지털 매거진 · 웹 연재 시리즈",
        "description_ko": "모바일·웹 화면에서 술술 읽히는 짧은 단락, 시선 집중 도입 훅(Hook), 핵심 요약 박스, 72 DPI 경량 시각화, 소단원별 20개 자동 해시태그와 CTA 배너를 최적화합니다.",
        "recommended_trim": "web_html",
        "trim_formats": ["b5"],
        "defaults": {
            "target_pages": 140,
            "chapter_count": 10,
            "visuals_per_chapter": 4,
            "target_audience": "농업인, 귀농·귀촌인, 스마트팜 관심 대중 및 블로그 구독자",
            "tone": "친근하고 명쾌하며 가독성 높은 해요체/웹 매거진체",
            "unit_label": "회차(아티클)",
            "include_exercises": False,
            "include_myths": True,
            "include_glossary": False,
            "include_executive_summary": True,
            "include_naver_hashtags": True,
            "visual_priority": {"A": 2, "B": 0, "C": 1, "D": 1},
            "citation_density": "medium",
        },
        "custom_fields": [
            {"key": "web_channel", "label": "주 발행 플랫폼", "type": "select", "options": ["네이버 블로그 + 웹 아티클", "브런치·뉴스레터 연재", "자체 홈페이지/전자 매거진"], "default": "네이버 블로그 + 웹 아티클"},
            {"key": "mobile_short_para", "label": "모바일 최적화 짧은 단락(2~3문장) + 핵심 요약 박스", "type": "checkbox", "default": True},
            {"key": "include_naver_hashtags", "label": "소단원별 네이버 SEO 해시태그 20개 자동 생성", "type": "checkbox", "default": True},
            {"key": "include_myths", "label": "독자 관심 유발 '흔한 오해 vs 진실 Q&A' 포함", "type": "checkbox", "default": True},
            {"key": "include_cta_banner", "label": "아카데미·컨설팅·전자책 연결 CTA 배너 삽입", "type": "checkbox", "default": True},
        ],
    },
    "lecture": {
        "id": "lecture",
        "icon": "🎓",
        "name_ko": "강의 교재",
        "subtitle_ko": "대학·농업기술센터 강의노트 · 실습 워크북",
        "description_ko": "주차(강)별 학습 목표, 핵심 슬라이드 요약, 현장 실습 체크리스트, 토론·그룹 활동 과제, 형성평가 퀴즈와 시간 배분 가이드를 갖춘 실전 강의용 교재입니다.",
        "recommended_trim": "a4",
        "trim_formats": ["a4", "b5"],
        "defaults": {
            "target_pages": 220,
            "chapter_count": 12,
            "visuals_per_chapter": 5,
            "target_audience": "대학 수강생, 농업기술센터 교육생, 영농 아카데미 수강자",
            "tone": "강연자가 설명하듯 명료하고 핵심을 짚어주는 강의체",
            "unit_label": "강(주차)",
            "include_exercises": True,
            "include_myths": True,
            "include_glossary": True,
            "include_executive_summary": True,
            "include_naver_hashtags": False,
            "visual_priority": {"A": 1, "B": 1, "C": 2, "D": 1},
            "citation_density": "medium",
        },
        "custom_fields": [
            {"key": "session_duration", "label": "1강(회차) 기준 강의 시간", "type": "select", "options": ["50분 (대학 1교시)", "90분~2시간 (기술센터 특강)", "3시간 (반일 실습 워크숍)"], "default": "90분~2시간 (기술센터 특강)"},
            {"key": "include_learning_goals", "label": "매 강 시작 [학습 목표 · 핵심 요약 박스] 포함", "type": "checkbox", "default": True},
            {"key": "include_workshop_checklist", "label": "현장 실습 체크리스트 및 워크시트 포함", "type": "checkbox", "default": True},
            {"key": "include_discussion", "label": "수강생 토론·사례 분석 과제 포함", "type": "checkbox", "default": True},
            {"key": "include_exercises", "label": "형성평가 퀴즈 및 해설 포함", "type": "checkbox", "default": True},
        ],
    },
    "report": {
        "id": "report",
        "icon": "📊",
        "name_ko": "보고서",
        "subtitle_ko": "정부 R&D · 지자체 정책 · 기술 용역 최종보고서",
        "description_ko": "Executive Summary(핵심 요약), 현황 및 문제점 진단, 국내외 정량 데이터 비교표·차트, 정책·예산·실행 로드맵과 철저한 출처 증빙을 갖춘 기관 제출용 A4 보고서입니다.",
        "recommended_trim": "a4",
        "trim_formats": ["a4", "b5"],
        "defaults": {
            "target_pages": 120,
            "chapter_count": 8,
            "visuals_per_chapter": 4,
            "target_audience": "농림축산식품부, 지자체, 농업기술센터, 연구기관 및 기업 의사결정자",
            "tone": "객관적이고 간결한 연구·정책 보고서 문체(개조식+서술식 조화)",
            "unit_label": "장(과업 절)",
            "include_exercises": False,
            "include_myths": False,
            "include_glossary": False,
            "include_executive_summary": True,
            "include_naver_hashtags": False,
            "visual_priority": {"A": 1, "B": 0, "C": 1, "D": 2},
            "citation_density": "very_high",
        },
        "custom_fields": [
            {"key": "report_style", "label": "보고서 작성 양식", "type": "select", "options": ["개조식 + 핵심 서술 혼용 (공공기관 표준)", "학술·기술 연구보고서 서술형", "비즈니스·컨설팅 전략제안서형"], "default": "개조식 + 핵심 서술 혼용 (공공기관 표준)"},
            {"key": "include_executive_summary", "label": "Executive Summary (의사결정자용 1~2p 핵심 요약) 포함", "type": "checkbox", "default": True},
            {"key": "include_policy_roadmap", "label": "추진 전략 · 단계별 로드맵 · 기대효과 KPI 표 포함", "type": "checkbox", "default": True},
            {"key": "include_swot_benchmark", "label": "국내외 벤치마킹 및 SWOT/GAP 분석 포함", "type": "checkbox", "default": True},
            {"key": "client_org_name", "label": "제출·발주 기관명 (선택)", "type": "text", "default": "농업기술센터 / 유관 연구기관"},
        ],
    },
    "paper": {
        "id": "paper",
        "icon": "📄",
        "name_ko": "논문",
        "subtitle_ko": "KCI · SCI(E) 학술 논문 · 체계적 문헌고찰(Review)",
        "description_ko": "학회 즉시 투고 표준 5대 구성(① 전체 초록 1개 → ② 재료 및 방법[세부 절] → ③ 결과 및 고찰[학회 투고급 6단계 심층 분석 세부 절·분량 집중] → ④ 핵심 내용 요약 1개 → ⑤ 마지막 1회 통합 참고문헌)을 엄격히 준수합니다.",
        "recommended_trim": "a4",
        "trim_formats": ["a4"],
        "defaults": {
            "target_pages": 30,
            "chapter_count": 5,
            "visuals_per_chapter": 2,
            "target_audience": "국내외 학회지 심사위원, 대학교수, 농학·생명과학 연구자",
            "tone": "엄밀하고 객관적인 KCI/SCI(E) 학술 논문 문체(~하였다/~로 나타났다)",
            "unit_label": "대항목(5대 고정)",
            "include_exercises": False,
            "include_myths": False,
            "include_glossary": False,
            "include_executive_summary": False,
            "include_naver_hashtags": False,
            "visual_priority": {"A": 0, "B": 1, "C": 0, "D": 1},
            "citation_density": "very_high",
            "methods_subsection_count": 4,
            "results_subsection_count": 5,
            "journal_tier": "SCI(E) / KCI 등재지 즉시 투고 수준",
            "single_abstract_only": True,
            "single_core_summary_only": True,
            "single_references_at_end": True,
        },
        "custom_fields": [
            {"key": "paper_type", "label": "논문 유형", "type": "select", "options": ["체계적 문헌고찰 / 리뷰 논문 (Review Paper)", "원저 논문 (Original Article)", "기술 단신 / 정책 제언 논문 (Technical Note)"], "default": "체계적 문헌고찰 / 리뷰 논문 (Review Paper)"},
            {"key": "journal_tier", "label": "목표 학술지 심사 수준", "type": "select", "options": ["SCI(E) / KCI 등재지 즉시 투고 수준", "SCI(E) Q1·Q2 국제학술지 심층 수준", "국내 전문학회지 (KCI 등재지) 표준"], "default": "SCI(E) / KCI 등재지 즉시 투고 수준"},
            {"key": "methods_subsection_count", "label": "재료 및 방법 세부 절(2.x) 개수", "type": "select", "options": ["3", "4", "5"], "default": "4"},
            {"key": "results_subsection_count", "label": "결과 및 고찰 심층 분석 세부 절(3.x) 개수", "type": "select", "options": ["4", "5", "6", "7"], "default": "5"},
            {"key": "citation_style", "label": "참고문헌 서식 기준 (문서 말미 단 1회 통합)", "type": "select", "options": ["APA 7th / 한국농학계 표준", "Nature / Springer 번호 인용형", "IEEE / 공학계 표준"], "default": "APA 7th / 한국농학계 표준"},
            {"key": "include_bilingual_abstract", "label": "전체 초록에 국문 + 영문 Abstract 및 Keywords (5~6개) 병기", "type": "checkbox", "default": True},
            {"key": "include_limitations", "label": "결과 및 고찰 최종 절에 연구의 한계(Limitations) 및 향후 연구 과제 포함", "type": "checkbox", "default": True},
        ],
    },
    "storybook": {
        "id": "storybook",
        "icon": "📖",
        "name_ko": "이야기 책",
        "subtitle_ko": "농업 에세이 · 현장 르포 · 스토리텔링 대중 교양서",
        "description_ko": "전문 농업 지식을 딱딱한 수식 대신 계절의 흐름, 농부·작물의 생생한 현장 에피소드, 따뜻한 비유와 감성 일러스트로 풀어내 일반 독자와 귀농인이 단숨에 읽는 신국판 단행본입니다.",
        "recommended_trim": "shinkuk",
        "trim_formats": ["shinkuk", "b5"],
        "defaults": {
            "target_pages": 240,
            "chapter_count": 12,
            "visuals_per_chapter": 3,
            "target_audience": "일반 교양 독자, 귀농·귀촌 준비자, 도시농부, 농업 현장 애호가",
            "tone": "따뜻하고 생생하며 몰입감 있는 스토리텔링·에세이 문체",
            "unit_label": "이야기(에피소드)",
            "include_exercises": False,
            "include_myths": True,
            "include_glossary": False,
            "include_executive_summary": False,
            "include_naver_hashtags": True,
            "visual_priority": {"A": 2, "B": 0, "C": 1, "D": 0},
            "citation_density": "gentle",
        },
        "custom_fields": [
            {"key": "narrative_style", "label": "서사 전개 방식", "type": "select", "options": ["사계절 농사 연대기 에세이", "현장 농부·작물 스토리 르포", "초보 귀농인의 성장 대화형 스토리", "어린이·청소년도 읽는 쉬운 교양 동화체"], "default": "사계절 농사 연대기 에세이"},
            {"key": "pov", "label": "서술 시점", "type": "select", "options": ["1인칭 따뜻한 관찰자(저자 에세이)", "3인칭 현장 다큐멘터리", "선배 농부와 후배의 대화체"], "default": "1인칭 따뜻한 관찰자(저자 에세이)"},
            {"key": "avoid_heavy_formulas", "label": "복잡한 수식·학술 표 배제하고 일상 비유로 풀어쓰기", "type": "checkbox", "default": True},
            {"key": "include_ending_reflection", "label": "매 장 끝 [밭두렁 메모 · 독자에게 건네는 질문] 포함", "type": "checkbox", "default": True},
        ],
    },
}


def get_output_type_spec(type_id: str | None) -> dict[str, Any]:
    key = (type_id or "textbook").strip().lower()
    return PRIMARY_OUTPUT_TYPES.get(key, PRIMARY_OUTPUT_TYPES["textbook"])


def resolve_output_profile(type_id: str | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """1차 산출물 유형 기본값과 사용자 맞춤 설정을 병합해 완성된 output_profile을 반환한다."""
    spec = get_output_type_spec(type_id)
    profile = {
        "primary_output_type": spec["id"],
        "output_type_name_ko": spec["name_ko"],
        "output_type_icon": spec["icon"],
        "recommended_trim": spec["recommended_trim"],
        **spec["defaults"],
    }
    for cf in spec.get("custom_fields", []):
        profile.setdefault(cf["key"], cf["default"])
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                profile[k] = v
    return profile


def build_outline_instruction_for_type(state: dict[str, Any]) -> tuple[str, str]:
    """1단계 목차 설계 시 1차 산출물 유형별 전용 시스템 역할 및 구조 지침을 반환한다."""
    otype = state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook"
    spec = get_output_type_spec(otype)
    prof = resolve_output_profile(otype, state.get("output_profile"))

    tone = prof.get("tone", spec["defaults"]["tone"])
    unit_label = prof.get("unit_label", "장")

    if otype == "web_publish":
        role = "당신은 높은 조회수와 독자 체류 시간을 만드는 농업·스마트팜 전문 웹 출판·디지털 매거진 수석 에디터입니다."
        guide = (
            f"1차 산출물 유형: [🌐 웹 출판 ({prof.get('web_channel', '네이버 블로그 + 웹 아티클')})]\n"
            f"- 각 단원은 클릭하고 싶은 흥미로운 제목의 연재 {unit_label}으로 구성하고, 모바일에서 읽기 좋은 3~4개 소주제(sections)로 나누세요.\n"
            f"- 문체: {tone}\n"
            "- 각 회차 요약에 독자가 얻을 실용적 이득과 핵심 검색 키워드를 명확히 담으세요."
        )
    elif otype == "lecture":
        role = "당신은 대학 농학 전공 및 농업기술센터 실전 교육과정을 설계하는 수석 강의 교재 저자입니다."
        guide = (
            f"1차 산출물 유형: [🎓 강의 교재 ({prof.get('session_duration', '90분~2시간')})]\n"
            f"- 각 단원은 '제N강(주차)' 형태의 강의 모듈로 구성하고, 각 절(sections)은 '학습목표·도입 → 핵심 원리 강의 → 현장 사례/실습 → 정리 및 퀴즈' 흐름을 따르세요.\n"
            f"- 문체: {tone}"
        )
    elif otype == "report":
        role = "당신은 정부 R&D 과제, 지자체 농정 정책, 기술 용역 최종보고서를 총괄하는 수석 책임연구원입니다."
        guide = (
            f"1차 산출물 유형: [📊 보고서 ({prof.get('report_style', '공공기관 표준')}) · 제출처: {prof.get('client_org_name', '유관기관')}]\n"
            "- 전체 목차는 '제1장. 연구 개요 및 Executive Summary → 제2장. 국내외 현황 및 동향 → 제3~N-2장. 핵심 기술·데이터 정량 분석 및 현장 진단 → 제N-1장. 개선 전략·정책 제언 → 제N장. 실행 로드맵 및 기대효과' 체계로 설계하세요.\n"
            f"- 문체: {tone}"
        )
    elif otype == "paper":
        m_cnt = max(3, min(5, int(prof.get("methods_subsection_count") or 4)))
        r_cnt = max(4, min(7, int(prof.get("results_subsection_count") or 5)))
        role = "당신은 SCI(E) 및 KCI 등재 농학·생명과학 학술지에 다수 게재한 수석 연구자이자 학술지 편집위원입니다."
        guide = (
            f"1차 산출물 유형: [📄 학술 논문·리뷰 ({prof.get('paper_type', 'Review Paper')}) · 목표 수준: {prof.get('journal_tier', 'SCI(E) / KCI 등재지 즉시 투고 수준')}]\n"
            "【절대 준수 5대 고정 구성 규칙 (.agents/rules/academic-paper-review-standard.md)】\n"
            "- 반드시 정확히 5개의 대항목(ch01~ch05)으로만 구성하십시오:\n"
            "  1) ch01: '1. 초록 (Abstract)' — 전체 논문/리뷰에서 단 1개의 통합 초록만 작성 (다른 절에 초록 중복 금지)\n"
            f"  2) ch02: '2. 재료 및 방법 (Materials and Methods)' — 반드시 2.1 ~ 2.{m_cnt} 세부 절({m_cnt}개)로 체계적 구분\n"
            f"  3) ch03: '3. 결과 및 고찰 (Results and Discussion)' — 반드시 3.1 ~ 3.{r_cnt} 심층 분석 세부 절({r_cnt}개)로 구분하고, 전체 분량의 약 70%를 집중 할당하며 마지막 절(3.{r_cnt})은 '종합 고찰, 연구의 한계 및 향후 연구 과제'로 배치\n"
            "  4) ch04: '4. 핵심 내용 요약 (Core Summary & Highlights)' — 전체 논문/리뷰에서 단 1개의 핵심 요약만 작성\n"
            "  5) ch05: '5. 참고문헌 (References)' — 문서 마지막에 단 1회만 통합 수록 (중간 절별 참고문헌 금지)\n"
            f"- 문체: {tone}"
        )
    elif otype == "storybook":
        role = "당신은 어려운 농업·자연과학 지식을 따뜻한 현장 서사와 아름다운 문장으로 풀어내는 베스트셀러 교양서·에세이 작가입니다."
        guide = (
            f"1차 산출물 유형: [📖 이야기 책 ({prof.get('narrative_style', '사계절 에세이')} · 시점: {prof.get('pov', '1인칭')})]\n"
            "- 각 장은 독자의 마음을 끄는 감성적이고 서사적인 에피소드 제목으로 짓고, 딱딱한 학술 번호 대신 이야기 흐름(장면 열기 → 흙과 작물의 비밀 → 현장의 깨달음 → 여운)으로 절을 구성하세요.\n"
            f"- 문체: {tone}"
        )
    else:
        role = "당신은 대학 전공 심화·연구자·현장 실무자용 표준 전문 교과서를 기획하는 수석 교육과정 설계자입니다."
        guide = (
            f"1차 산출물 유형: [📘 교과서 ({prof.get('structure_mode', '4단계 표준')}) · 수식수준: {prof.get('math_level', '전공 심화')}]\n"
            "- 4~5개 부(Part)로 체계적으로 그룹화하고 각 단원은 '개념·이론 → 생리·분자 메커니즘 → 현장 적용·실전 기술 → 법규·정책' 흐름으로 완결성 있게 설계하세요.\n"
            f"- 문체: {tone}"
        )
    return role, guide


def infer_paper_section_role(chapter: dict[str, Any], idx: int = 1, total: int = 5) -> str:
    """논문·리뷰(paper) 모드에서 각 대항목(ch01~ch05)의 표준 역할 키를 결정한다."""
    explicit = str(chapter.get("chapter_role") or "").strip().lower()
    if explicit in {"abstract", "methods", "results_discussion", "core_summary", "references"}:
        return explicit
    title = str(chapter.get("title") or "").lower()
    if "초록" in title or "abstract" in title:
        return "abstract"
    if "재료" in title or "방법" in title or "method" in title:
        return "methods"
    if "결과" in title or "고찰" in title or "result" in title or "discussion" in title:
        return "results_discussion"
    if "핵심" in title or "요약" in title or "highlight" in title or "summary" in title or "결론" in title:
        return "core_summary"
    if "참고문헌" in title or "reference" in title:
        return "references"
    role_by_idx = {
        1: "abstract",
        2: "methods",
        3: "results_discussion",
        4: "core_summary",
        5: "references",
    }
    return role_by_idx.get(idx, "results_discussion")


def _clean_sub_title(raw_sec: str, prefix: str) -> str:
    import re as _re

    s = _re.sub(r"^\s*\d+(?:\.\d+)*\s*[\.\)\-:]?\s*", "", str(raw_sec or "").strip()).strip()
    return f"{prefix} {s}" if s else prefix


def enforce_paper_outline_structure(outline: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """논문·리뷰(paper) 목차를 표준 5대 구성(초록 1개 · 재료및방법[세부절] · 결과및고찰[심층세부절·분량집중] · 핵심내용요약 1개 · 참고문헌 1회)으로 정규화한다."""
    prof = resolve_output_profile("paper", state.get("output_profile"))
    topic_ko = str(state.get("topic_ko") or outline.get("book_metadata", {}).get("title_ko") or "전문 학술 주제").strip()
    topic_en = str(state.get("topic_en") or outline.get("book_metadata", {}).get("title_en") or topic_ko).strip()
    kws_ko = [str(k).strip() for k in (state.get("keywords_ko") or []) if str(k).strip()] or [topic_ko]
    kws_en = [str(k).strip() for k in (state.get("keywords_en") or []) if str(k).strip()] or [topic_en]
    assigned_sources = [s.get("source_id") for s in (state.get("collected_sources") or []) if s.get("source_id")]
    packet_name = f"{state.get('packet_id', 'evidence')}.json"

    m_cnt = max(3, min(5, int(prof.get("methods_subsection_count") or 4)))
    r_cnt = max(4, min(7, int(prof.get("results_subsection_count") or 5)))
    bilingual = bool(prof.get("include_bilingual_abstract", True))
    include_lim = bool(prof.get("include_limitations", True))
    paper_type = str(prof.get("paper_type") or "체계적 문헌고찰 / 리뷰 논문 (Review Paper)")
    is_review = ("리뷰" in paper_type) or ("Review" in paper_type) or ("고찰" in paper_type)

    # 기존 LLM 생성 결과에서 재료 및 방법 / 결과 및 고찰 후보 세부 절 추출 (중복·초록·요약·참고문헌 제외)
    cand_methods: list[str] = []
    cand_results: list[str] = []
    for pt in (outline.get("parts") or []):
        for ch in (pt.get("chapters") or []):
            t_low = str(ch.get("title") or "").lower()
            secs = [str(x).strip() for x in (ch.get("sections") or []) if str(x).strip()]
            if any(k in t_low for k in ("재료", "방법", "method", "프로토콜", "자료")):
                cand_methods.extend(secs)
            elif any(k in t_low for k in ("초록", "abstract", "핵심", "요약", "참고문헌", "reference")):
                continue
            else:
                cand_results.extend(secs)

    default_methods_pool = (
        [
            "연구 범위, 핵심 연구 질문(PICO/RQ) 및 문헌 탐색 전략",
            "문헌·데이터베이스 선정·제외 기준 및 PRISMA 스크리닝 절차",
            "정량 데이터 추출, 표준화 지표 정의 및 메타분석·통계 처리 방법",
            "근거 품질 평가(Risk of Bias), 이질성 진단 및 재현성 검증 체계",
            "국내외 기후·토양·작부체계 비교 프레임워크 및 민감도 분석 설계",
        ]
        if is_review
        else [
            "공시 재료, 시험 포지(또는 실험 환경) 및 기상·토양 기초 특성",
            "실험 설계, 처리구 배치 및 재배·처리 관리 프로토콜",
            "생육·생리·품질 및 환경 지표의 정량 측정 및 시료 분석 방법",
            "통계 분석, 생육·회귀 모형 검증 및 품질 관리(QA/QC) 절차",
            "민감도 분석, 오차 통제 및 데이터 재현성 검증 기준",
        ]
    )

    methods_secs: list[str] = []
    seen_m: set[str] = set()
    for raw_s in cand_methods + default_methods_pool:
        if len(methods_secs) >= m_cnt:
            break
        cleaned = _clean_sub_title(raw_s, f"2.{len(methods_secs) + 1}")
        body_key = cleaned.split(" ", 1)[-1].lower()
        if body_key and body_key not in seen_m:
            seen_m.add(body_key)
            methods_secs.append(cleaned)

    default_results_pool = [
        f"{topic_ko} 핵심 정량 지표의 분포 특성과 주요 변동 요인 분석",
        f"{kws_ko[0]} 관련 생리·분자·물리화학적 기작 해석 및 인과 경로 규명",
        f"국내외 선행연구 정량 비교 종합 및 연구 간 불일치(Discrepancy) 원인 분석",
        f"{kws_ko[min(1, len(kws_ko) - 1)]} 기반 경계조건·민감도·트레이드오프 및 교란변수 평가",
        "정밀농업·현장 적용성, 경제성·환경부하 통합 평가 및 정책·기술적 함의",
        "품종·기후대·재배환경 상호작용(G×E×M) 심층 고찰 및 최적화 조건 도출",
    ]
    final_results_sec = (
        "종합 고찰, 방법론적 한계(Limitations) 및 향후 연구 과제"
        if include_lim
        else "종합 고찰 및 학술적·실무적 의의"
    )

    results_secs: list[str] = []
    seen_r: set[str] = set()
    target_core_r = max(3, r_cnt - 1)
    for raw_s in cand_results + default_results_pool:
        if len(results_secs) >= target_core_r:
            break
        cleaned = _clean_sub_title(raw_s, f"3.{len(results_secs) + 1}")
        body_key = cleaned.split(" ", 1)[-1].lower()
        if body_key and body_key not in seen_r and "한계" not in body_key and "참고문헌" not in body_key:
            seen_r.add(body_key)
            results_secs.append(cleaned)
    results_secs.append(f"3.{len(results_secs) + 1} {final_results_sec}")

    total_target = max(15, int(state.get("target_pages") or prof.get("target_pages") or 30))
    p_abs = max(1, round(total_target * 0.04))
    p_sum = max(1, round(total_target * 0.05))
    p_ref = max(2, round(total_target * 0.08))
    p_met = max(3, round(total_target * 0.16))
    p_res = max(10, total_target - (p_abs + p_met + p_sum + p_ref))
    final_total = p_abs + p_met + p_res + p_sum + p_ref

    abstract_secs = (
        ["1.1 국문 초록 및 핵심어 (Keywords)", "1.2 영문 Abstract & Keywords"]
        if bilingual
        else ["1.1 전체 초록 및 핵심어 (Keywords)"]
    )

    chapters_5 = [
        {
            "chapter_id": "ch01",
            "chapter_number": 1,
            "chapter_role": "abstract",
            "title": "1. 초록 (Abstract)",
            "target_pages": p_abs,
            "summary_ko": f"《{topic_ko}》 전체 연구/리뷰의 배경, 방법, 핵심 정량 결과, 학술적 의의를 집약한 단일 통합 초록(국·영문) 및 핵심어.",
            "sections": abstract_secs,
            "keywords_ko": kws_ko[:5],
            "keywords_en": kws_en[:5],
            "evidence_packet": packet_name,
            "assigned_sources": assigned_sources,
        },
        {
            "chapter_id": "ch02",
            "chapter_number": 2,
            "chapter_role": "methods",
            "title": "2. 재료 및 방법 (Materials and Methods)",
            "target_pages": p_met,
            "summary_ko": f"{topic_ko}의 연구 설계, 문헌/데이터 선정·제외 기준, 정량 추출·통계·품질 평가 절차를 {len(methods_secs)}개 세부 절로 재현 가능하게 기술한다.",
            "sections": methods_secs,
            "keywords_ko": kws_ko[:4],
            "keywords_en": kws_en[:4],
            "evidence_packet": packet_name,
            "assigned_sources": assigned_sources,
        },
        {
            "chapter_id": "ch03",
            "chapter_number": 3,
            "chapter_role": "results_discussion",
            "title": "3. 결과 및 고찰 (Results and Discussion)",
            "target_pages": p_res,
            "summary_ko": (
                f"{topic_ko}에 대해 {prof.get('journal_tier', 'SCI(E)/KCI')} 즉시 투고 수준의 6단계 심층 논리"
                f"(정량 발견→기작 해석→선행연구 비교·불일치 규명→경계조건·트레이드오프→학술·현장 함의→한계·향후과제)로 {len(results_secs)}개 세부 절을 심도 있게 전개한다."
            ),
            "sections": results_secs,
            "keywords_ko": kws_ko,
            "keywords_en": kws_en,
            "evidence_packet": packet_name,
            "assigned_sources": assigned_sources,
        },
        {
            "chapter_id": "ch04",
            "chapter_number": 4,
            "chapter_role": "core_summary",
            "title": "4. 핵심 내용 요약 (Core Summary & Highlights)",
            "target_pages": p_sum,
            "summary_ko": f"《{topic_ko}》 전체 분석의 핵심 정량 발견(Highlights 4~6개)과 학술·실무 종합 결론을 단 1회 압축 정리한다.",
            "sections": ["4.1 핵심 연구 발견 (Highlights)", "4.2 종합 결론 (Concluding Remarks)"],
            "keywords_ko": kws_ko[:4],
            "keywords_en": kws_en[:4],
            "evidence_packet": packet_name,
            "assigned_sources": assigned_sources,
        },
        {
            "chapter_id": "ch05",
            "chapter_number": 5,
            "chapter_role": "references",
            "title": "5. 참고문헌 (References)",
            "target_pages": p_ref,
            "summary_ko": f"본문(1~4항목)에서 실제 인용된 모든 [SRC-NN] 1차 근거 출처를 중복 없이 {prof.get('citation_style', 'APA 7th')} 서식으로 마지막에 단 1회 통합 수록한다.",
            "sections": [f"5.1 통합 참고문헌 목록 ({prof.get('citation_style', 'APA 7th')})"],
            "keywords_ko": ["참고문헌", "1차 출처"],
            "keywords_en": ["References", "Primary Sources"],
            "evidence_packet": packet_name,
            "assigned_sources": assigned_sources,
        },
    ]

    meta = dict(outline.get("book_metadata") or {})
    meta.update(
        {
            "title_ko": topic_ko,
            "title_en": topic_en,
            "target_audience": state.get("target_audience") or prof.get("target_audience", ""),
            "book_summary_ko": meta.get("book_summary_ko")
            or f"《{topic_ko}》 {prof.get('paper_type', '학술 논문·리뷰')} — 초록 1개 · 재료 및 방법({len(methods_secs)}절) · 결과 및 고찰({len(results_secs)}절 심층 분석) · 핵심 내용 요약 1개 · 통합 참고문헌 1회 구성",
            "target_pages": final_total,
            "target_total_pages": final_total,
            "chapter_count": 5,
            "primary_output_type": "paper",
            "paper_structure_enforced": True,
            "results_discussion_share_pct": round((p_res / max(1, final_total)) * 100, 1),
        }
    )

    dom_kws = outline.get("domain_keywords") or [
        {"domain": "재료 및 방법", "keywords_ko": kws_ko[:4], "keywords_en": kws_en[:4]},
        {"domain": "결과 및 고찰", "keywords_ko": kws_ko, "keywords_en": kws_en},
    ]

    return {
        "book_metadata": meta,
        "domain_keywords": dom_kws,
        "parts": [
            {
                "part_number": 1,
                "title": f"학술 논문 · 리뷰 표준 5대 구성 ({prof.get('journal_tier', 'SCI(E)/KCI 투고 표준')})",
                "pages": final_total,
                "chapters": chapters_5,
            }
        ],
    }


def format_paper_consolidated_references(
    sources: list[dict[str, Any]],
    cited_ids: list[str] | None = None,
    *,
    citation_style: str = "APA 7th / 한국농학계 표준",
    title: str = "5. 참고문헌 (References)",
) -> str:
    """논문·리뷰 본문(ch01~ch04)에서 인용된 [SRC-NN] 출처를 중복 없이 마지막에 단 1회 통합 참고문헌으로 포매팅한다."""
    by_id: dict[str, dict[str, Any]] = {}
    ordered_all: list[str] = []
    for s in sources:
        sid = str(s.get("source_id") or "").strip()
        if sid and sid not in by_id:
            by_id[sid] = s
            ordered_all.append(sid)

    selected_ids: list[str] = []
    seen: set[str] = set()
    for cid in (cited_ids or []):
        cid = str(cid).strip()
        if cid in by_id and cid not in seen:
            seen.add(cid)
            selected_ids.append(cid)
    if not selected_ids:
        selected_ids = ordered_all

    is_nature = "Nature" in citation_style or "Springer" in citation_style
    is_ieee = "IEEE" in citation_style

    lines = [
        f"# {title}",
        "",
        f"> 본 참고문헌 목록은 본 논문·리뷰의 전체 본문(1. 초록 ~ 4. 핵심 내용 요약)에서 인용된 1차 근거 출처 **{len(selected_ids)}건**을 **{citation_style}** 기준으로 중복 없이 단 1회 통합 수록한 것입니다.",
        "",
        f"## 5.1 통합 참고문헌 목록 ({citation_style})",
        "",
    ]

    for num, sid in enumerate(selected_ids, 1):
        s = by_id[sid]
        stitle = str(s.get("title") or sid).strip().replace("\n", " ")
        authors = str(s.get("authors") or s.get("organization") or s.get("source_org") or "").strip()
        year = str(s.get("year") or s.get("published_year") or (str(s.get("retrieved_at") or "")[:4]) or "n.d.").strip()
        venue = str(s.get("journal") or s.get("venue") or s.get("source_type") or "Primary Evidence").strip()
        doi = str(s.get("doi") or "").strip()
        url = str(s.get("url") or "").strip()
        link_part = f"https://doi.org/{doi}" if doi and not doi.startswith("http") else (doi or url)
        author_part = authors if authors else venue

        if is_ieee:
            entry = f"[{num}] {author_part}, \"{stitle},\" *{venue}*, {year}."
        elif is_nature:
            entry = f"{num}. {author_part}. {stitle}. *{venue}* ({year})."
        else:
            # APA 7th / 한국농학계 표준
            entry = f"{num}. {author_part} ({year}). {stitle}. *{venue}*."

        if link_part:
            entry += f" {link_part}"
        entry += f" `[{sid}]`"
        lines.append(entry)

    lines.append("")
    return "\n".join(lines)


def build_draft_instruction_for_type(
    state: dict[str, Any],
    valid_ids: list[str],
    chapter_role: str | None = None,
) -> str:
    """4단계 원고 집필 시 1차 산출물 유형과 사용자 설정 특성에 맞춘 정밀 시스템 프롬프트를 생성한다."""
    otype = state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook"
    prof = resolve_output_profile(otype, state.get("output_profile"))
    cite_hint = ", ".join(valid_ids[:15]) if valid_ids else "근거"
    tone = prof.get("tone", "전문 서술체")

    base_rules = [
        f"당신은 참참살이 영농 AI 출판도우미의 [{prof['output_type_icon']} {prof['output_type_name_ko']}] 전문 수석 저자입니다.",
        f"1. 문체 및 어조: {tone}",
        f"2. 근거 무결성: 모든 사실·수치 문장 끝에 제공된 출처 키({cite_hint})만 정확히 부착하십시오 (없는 출처키 창작 금지).",
        "3. 표기 규약: 원소기호·화학식·첨자는 LaTeX($...$) 대신 일반 유니코드/HTML(예: CO₂, NH₄⁺, θ<sub>opt</sub>)로 작성하십시오.",
    ]

    if otype == "web_publish":
        base_rules.append("4. 웹 출판 구조: 첫 문단은 독자의 호기심을 끄는 공감 훅(Hook)과 '> **3줄 핵심 요약**' 박스로 시작하고, 모바일 가독성을 위해 한 문단을 2~4문장으로 간결하게 끊어 작성하십시오.")
        if prof.get("include_myths", True):
            base_rules.append("5. 말미에 '## 흔한 오해와 진실 Q&A' (3개 이상)와 현장 바로 실천 팁을 넣으십시오. 딱딱한 시험 연습문제는 넣지 마십시오.")
    elif otype == "lecture":
        base_rules.append(f"4. 강의 교재 구조({prof.get('session_duration', '90분')}): 최상단에 '## 이번 강의 학습 목표 및 시간 배분' 박스를 배치하고, 핵심 개념을 강의 슬라이드처럼 명확한 소제목·불릿·표로 전개하십시오.")
        if prof.get("include_workshop_checklist", True):
            base_rules.append("5. '## 현장 실습 체크리스트 및 토론 과제' 절을 반드시 포함하십시오.")
        if prof.get("include_exercises", True):
            base_rules.append("6. '## 이해도 점검 퀴즈 및 해설' (문제 3문항과 각 문제 직하단 1:1 정답·풀이)을 포함하십시오.")
    elif otype == "report":
        base_rules.append(f"4. 연구·정책 보고서 구조({prof.get('report_style', '공공기관 표준')}): 최상단에 '> **Executive Summary (핵심 요약)**'를 배치하고, 정량 비교표·현황 진단·원인 분석·정책/기술 제언·단계별 실행 로드맵 순으로 객관적으로 서술하십시오.")
        base_rules.append("5. 보고서 품격 유지를 위해 시험용 연습문제나 오해와 진실 퀴즈는 포함하지 말고, 대신 '## 핵심 제언 및 실행 로드맵 표'를 작성하십시오.")
    elif otype == "paper":
        j_tier = prof.get("journal_tier", "SCI(E) / KCI 등재지 즉시 투고 수준")
        p_type = prof.get("paper_type", "체계적 문헌고찰 / 리뷰 논문 (Review Paper)")
        bilingual = bool(prof.get("include_bilingual_abstract", True))
        role_key = (chapter_role or "results_discussion").strip().lower()

        base_rules.append(
            f"4. 학술 논문·리뷰 공통 규칙 ({p_type} · {j_tier}): "
            "연습문제·퀴즈·오해와 진실·단원별 용어집을 절대 포함하지 마십시오. "
            "또한 이 섹션 말미에 별도의 '## 참고문헌' 목록을 절대 추가하지 마십시오 (참고문헌은 5. 참고문헌에서 전체 통합하여 단 1회만 수록합니다)."
        )
        if role_key == "abstract":
            base_rules.append(
                "5. [1. 초록 전용 규칙 — 전체 논문에서 단 1개]: 연구 배경 및 목적(Background/Objective) → 재료·분석 방법(Methods) → 핵심 정량 결과(Key Quantitative Findings) → 학술적·현장 결론(Conclusion) 순으로 응축된 단일 전체 초록만 작성하십시오."
            )
            if bilingual:
                base_rules.append(
                    "6. '## 1.1 국문 초록 및 핵심어' (약 400~600자 + 핵심어 5~6개)와 '## 1.2 영문 Abstract & Keywords' (약 220~320 words + Keywords 5~6개)를 엄밀한 학술 어휘로 작성하고, 본문 전개나 참고문헌 표는 절대 넣지 마십시오."
                )
        elif role_key == "methods":
            base_rules.append(
                "5. [2. 재료 및 방법 전용 규칙 — 세부 절(2.1~2.M) 필수]: 제공된 필수 세부 절(## 2.1, ## 2.2, ...)을 빠짐없이 구분하여 다른 연구자가 그대로 재현할 수 있을 수준의 구체성(DB·검색식·포함/제외 기준·실험/관측 조건·정량 지표 수식/단위·통계 모델·편향 통제 및 QA/QC 절차)으로 작성하십시오."
            )
            base_rules.append(
                "6. 중복 금지: 이 섹션에는 초록(Abstract), 핵심 내용 요약, 참고문헌 목록을 절대 쓰지 말고 오직 재료 및 방법 본문에만 집중하십시오."
            )
        elif role_key == "results_discussion":
            base_rules.append(
                f"5. [3. 결과 및 고찰 전용 규칙 — {j_tier} 문헌 비교표 선행 + 6단계 심층 분석 논리 (C8)]: "
                "제공된 모든 세부 절(## 3.1, ## 3.2, ...)을 빠짐없이 작성하되, 단순 문헌 요약이나 교과서식 개론을 금지하고 "
                "리뷰 논문은 반드시 먼저 [연구(저자·연도) | 대상 작물 | 방법/모델 | 데이터셋/표본 | 정량 정확도(R²·RMSE·IoU·mAP·수량 등) | 출처] "
                "마크다운 비교표를 구성한 뒤, 그 표의 실측 수치를 근거로 다음 6단계 학술 논리 구조를 깊이 있게 관철하십시오:\n"
                "   (1) 정량적 실증 발견(Empirical Quantitative Findings): 핵심 지표의 수치·범위·변화율·통계적 유의성(p, R², CV 등)을 [SRC-NN]과 함께 제시하고, 다중 근거 비교 마크다운 표(Table)를 최소 1개 이상 포함.\n"
                "   (2) 생리·분자·물리화학적 기작 해석(Mechanistic Interpretation): 관찰된 수치 패턴이 왜(Why) 그리고 어떤 생리·토양·에너지·알고리즘 경로(How)로 발생했는지 인과 메커니즘을 규명.\n"
                "   (3) 선행연구 비교 종합 및 불일치 원인 규명(Cross-Study Synthesis & Discrepancy Resolution): 국내(한국)와 국외(미국·유럽·일본 등) 선행연구의 일치점과 상충점을 명시적으로 비교하고, 기후·품종·토성·관개·측정 스케일 차이에 따른 불일치 원인을 비판적으로 해석.\n"
                "   (4) 경계조건·민감도·트레이드오프 및 교란변수(Boundary Conditions, Trade-offs & Confounders): 임계 역치, 비선형 응답, 수량-품질-환경부하 간 트레이드오프와 교란요인의 영향을 분석.\n"
                "   (5) 학술적 기여 및 현장·정책 함의(Theoretical Contribution & Practical/Policy Implications): 기존 이론/기준의 확장 지점과 한국 농업 현장·정밀농업 적용 함의를 도출.\n"
                "   (6) 방법론적 한계 및 향후 연구 과제(Limitations & Future Research Agenda): 마지막 세부 절(3.K)에서 데이터 이질성·출판 편향·스케일업 한계와 구체적인 후속 연구 설계를 제시."
            )
            base_rules.append(
                "6. 분량 및 중복 금지: 전체 논문의 핵심 본문이므로 가능한 가장 풍부하고 밀도 있게 서술하되, 초록(Abstract)·핵심 내용 요약·참고문헌 목록 및 동일 제목(# / ##) 중복은 절대 작성하지 마십시오."
            )
        elif role_key == "core_summary":
            base_rules.append(
                "5. [4. 핵심 내용 요약 전용 규칙 — 전체 논문에서 단 1개 · 수치 필수 (C8)]: "
                "'## 4.1 핵심 연구 발견 (Highlights)'에 4~6개의 핵심 불릿을 제시하되, 각 항목에는 반드시 3장 비교표에서 검증된 구체적 정량 수치(단위·정확도·범위·향상률 등)와 [SRC-NN] 출처를 포함하십시오 "
                "(수치 0개인 '정량적 요약' 문장 작성 금지; 근거에 수치가 없으면 정량 비교표 보완 필요 주석 표시). "
                "이어 '## 4.2 종합 결론 (Concluding Remarks)'에 연구 전체의 최종 학술·현장 결론을 2~3개 압축 단락으로 완결하십시오."
            )
            base_rules.append(
                "6. 중복 금지: 장 제목('# 4. 핵심 내용 요약') 바로 아래에 동일한 '## 4. 핵심 내용 요약'을 절대 반복하지 말고, 초록 문장 복붙이나 참고문헌 목록 삽입을 금지합니다."
            )
        else:
            base_rules.append(
                "5. [5. 참고문헌 전용 규칙]: 전체 본문에서 실제 인용된 [SRC-NN] 출처만 중복 없이 학술지 서식으로 단 1회 통합 수록하십시오."
            )
    elif otype == "storybook":
        base_rules.append(f"4. 이야기 책 구조({prof.get('narrative_style', '사계절 에세이')} · 시점: {prof.get('pov', '1인칭')}): 생생한 계절·바람·흙·작물의 장면 묘사로 이야기를 열고, 전문 농업 지식은 일상적 비유와 현장 에피소드 속에 자연스럽게 녹여 쓰십시오.")
        if prof.get("avoid_heavy_formulas", True):
            base_rules.append("5. 복잡한 수식·딱딱한 학술 표·시험 연습문제는 배제하고, 유려한 산문 중심으로 전개하십시오.")
        if prof.get("include_ending_reflection", True):
            base_rules.append("6. 장 말미에 '## 밭두렁 메모 · 독자에게 건네는 작은 질문'을 덧붙여 여운을 남기십시오.")
    else:
        # textbook (기본)
        base_rules.append(f"4. 교과서 전개({prof.get('structure_mode', '4단계 표준')}): 본문은 개념 소개·이론적 배경 → 생리·분자 메커니즘 → 현장 적용·실전 기술 → 관련 법규·정책 지침 흐름을 반영하고 GraphRAG 엔티티-관계 트리플을 출처키와 1:1 바인딩하십시오.")
        extras: list[str] = []
        if prof.get("include_glossary", True):
            extras.append("## 핵심 용어집 (표)")
        if prof.get("include_exercises", True):
            extras.append("## 이해도 점검 연습문제 및 해설 (문제 3문항과 각 문제 직하단 1:1 정답·상세 풀이)")
        if prof.get("include_myths", True):
            extras.append("## 오해와 진실: 현장·이론 핵심 오해 교정 (오해 3개 이상)")
        if extras:
            base_rules.append("5. 단원 말미 필수 구성: " + ", ".join(extras) + "을 모두 작성하십시오.")

    return "\n".join(base_rules)
