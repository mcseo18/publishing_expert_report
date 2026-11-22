"""참참살이 영농 AI 출판도우미 — Phase 4 다각화 수익화(Monetization) & 상용 패키징 모듈.

4단계 수익 모델 구현:
1. B2C POD 출판 패키지 (부크크 Bookk · 교보문고 퍼플 · 유페이퍼 eBook 원클릭 압축 내보내기)
2. B2B/B2G 기관 맞춤 납품 패키지 (농업기술센터 · 지자체 · 스마트팜 기업용 A4/B5 보고서·교재 명세)
3. 트래픽 마케팅 (네이버 블로그 HTML 20개 해시태그 일괄 추출·검증 + 영농 아카데미 CTA 번들)
4. SaaS & API 라이선싱 패키징 (화이트라벨 테넌트 프로필 + 4채널 수익 시뮬레이터)
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from compliance import utc_now_iso
from config import PlatformConfig, get_config

POD_PLATFORMS: dict[str, dict[str, Any]] = {
    "bookk": {
        "name_ko": "부크크 (Bookk POD)",
        "recommended_trim": "shinkuk",
        "trim_label": "신국판 (152 × 225 mm)",
        "royalty_rate": 0.35,
        "checklist": [
            "본문 PDF (신국판 152×225mm, 300dpi 도판 내장)",
            "표지·머리말·전체 목차 파일 (cover_and_toc.pdf)",
            "책 소개·저자 소개·목차 메타데이터 (pod_metadata.json)",
            "ISBN 발급 신청 및 유통 채널(교보·예스24·알라딘) 연동 체크",
        ],
    },
    "kyobo_purple": {
        "name_ko": "교보문고 퍼플 (POD / eBook)",
        "recommended_trim": "b5",
        "trim_label": "B5 대학교재판 (182 × 257 mm)",
        "royalty_rate": 0.30,
        "checklist": [
            "본문 PDF (B5 182×257mm 또는 신국판 152×225mm)",
            "앞·뒤 표지 및 책등 규격 안내서",
            "도서 카테고리(농학/스마트농업) 및 검색 키워드 10종",
        ],
    },
    "upaper_ebook": {
        "name_ko": "유페이퍼 · 리디 · 밀리의서재 (전자책)",
        "recommended_trim": "b5",
        "trim_label": "전자책 PDF / ePub 원본 패키지",
        "royalty_rate": 0.55,
        "checklist": [
            "웹 최적화 72dpi 이미지 기반 경량 전자책 원본",
            "머리말·저자소개·전체 목차 마크다운/HTML",
            "서점 등록용 홍보 카피 및 20개 핵심 해시태그",
        ],
    },
}


def get_monetization_overview(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트의 4단계 수익화 준비 상태(POD / B2G / 네이버 블로그 / SaaS)를 진단한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    ch_files = sorted((ws / "chapters").glob("*.mdx")) if (ws / "chapters").is_dir() else []
    exp_dir = ws / "exports"
    front_dir = exp_dir / "front_matter"
    master_dir = exp_dir / "master_book"
    mon_dir = exp_dir / "monetization"

    naver_files = sorted(exp_dir.glob("ch*/ch*_naver_blog.html")) if exp_dir.is_dir() else []
    pdf_files = sorted(exp_dir.glob("ch*/ch*_textbook.pdf")) if exp_dir.is_dir() else []
    docx_files = sorted(exp_dir.glob("ch*/ch*_report.docx")) if exp_dir.is_dir() else []
    master_pdfs = sorted(master_dir.glob("*.pdf")) if master_dir.is_dir() else []
    has_cover = (front_dir / "cover_and_toc.pdf").is_file() or (front_dir / "cover_and_toc.html").is_file()

    # 네이버 블로그 해시태그 현황 스캔
    hashtag_count_total = 0
    for nf in naver_files:
        txt = nf.read_text(encoding="utf-8", errors="ignore")
        hashtag_count_total += len(re.findall(r"#[가-힣A-Za-z0-9_]{2,}", txt))

    existing_packages = []
    if mon_dir.is_dir():
        for f in sorted(mon_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                existing_packages.append(
                    {
                        "filename": f.name,
                        "url": f"/project-files/{project_id}/exports/monetization/{f.name}",
                        "size_kb": round(f.stat().st_size / 1024, 1),
                        "updated_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    }
                )

    pod_ready_score = sum(
        [
            30 if len(ch_files) > 0 else 0,
            25 if has_cover else 0,
            25 if (len(master_pdfs) > 0 or len(pdf_files) > 0) else 0,
            20 if len(st.get("collected_sources") or []) > 0 else 0,
        ]
    )

    return {
        "project_id": project_id,
        "topic_ko": st.get("topic_ko", ""),
        "topic_en": st.get("topic_en", ""),
        "target_pages": st.get("target_pages", 400),
        "chapter_count": len(ch_files),
        "has_cover_toc": has_cover,
        "chapter_pdfs": len(pdf_files),
        "chapter_docx": len(docx_files),
        "master_pdfs": [p.name for p in master_pdfs],
        "naver_blog_files": len(naver_files),
        "naver_hashtags_detected": hashtag_count_total,
        "pod_ready_score": pod_ready_score,
        "pod_platforms": POD_PLATFORMS,
        "packages": existing_packages,
    }


def build_pod_export_package(
    *,
    project_id: str,
    platform: str = "bookk",
    author: str = "참참살이 영농 AI 출판위원회",
    author_bio: str = "스마트 농업·작물생리·데이터 기반 정밀농업 전문 연구 및 현장 컨설팅 저자.",
    list_price_krw: int = 28000,
    isbn_placeholder: str = "발급 예정 (POD 플랫폼 신청)",
    book_intro: str = "",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """1단계 B2C POD 플랫폼(부크크/교보문고/유페이퍼) 원클릭 출판 등록 패키지를 ZIP으로 생성한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    plat = POD_PLATFORMS.get(platform, POD_PLATFORMS["bookk"])
    ws = Path(st["workspace_dir"])
    exp_dir = ws / "exports"
    mon_dir = exp_dir / "monetization"
    mon_dir.mkdir(parents=True, exist_ok=True)

    bp_path = ws / "blueprints" / "master_outline.yaml"
    toc_lines: list[str] = []
    if bp_path.is_file():
        import yaml

        bp = yaml.safe_load(bp_path.read_text(encoding="utf-8")) or {}
        for pt in bp.get("parts", []):
            toc_lines.append(f"## {pt.get('title', '')}")
            for ch in pt.get("chapters", []):
                toc_lines.append(f"- {ch.get('title', '')} (약 {ch.get('target_pages', 30)}쪽)")

    topic_ko = st.get("topic_ko", project_id)
    intro_text = book_intro.strip() or (
        f"《{topic_ko}》는 국내외 공식 농업 연구기관 자료, SCI 학술 문헌, 로컬 지식그래프(GraphRAG)를 결합해 "
        "이론·생리 메커니즘·현장 정밀관리 기술·관련 법규까지 1권에 완결한 전문 실무 교재입니다."
    )

    est_royalty_per_copy = int(round(list_price_krw * float(plat["royalty_rate"])))
    metadata = {
        "brand": "참참살이 영농 AI 출판도우미",
        "platform": platform,
        "platform_name": plat["name_ko"],
        "generated_at": utc_now_iso(),
        "book": {
            "title_ko": topic_ko,
            "title_en": st.get("topic_en", ""),
            "author": author,
            "author_bio": author_bio,
            "target_audience": st.get("target_audience", ""),
            "recommended_trim": plat["trim_label"],
            "target_pages": st.get("target_pages", 400),
            "list_price_krw": list_price_krw,
            "estimated_royalty_krw": est_royalty_per_copy,
            "isbn": isbn_placeholder,
            "keywords": st.get("keywords_ko") or [],
            "book_intro": intro_text,
        },
        "checklist": plat["checklist"],
    }

    guide_md = (
        f"# {plat['name_ko']} 원클릭 출판 등록 패키지 — 《{topic_ko}》\n\n"
        f"- **권장 판형**: {plat['trim_label']}\n"
        f"- **정가 / 예상 권당 인세**: {list_price_krw:,}원 / 약 {est_royalty_per_copy:,}원 ({int(plat['royalty_rate']*100)}%)\n"
        f"- **저자**: {author}\n"
        f"- **ISBN**: {isbn_placeholder}\n\n"
        f"## 1. 서점 등록용 책 소개\n\n{intro_text}\n\n"
        f"## 2. 저자 소개\n\n{author_bio}\n\n"
        f"## 3. 전체 목차\n\n" + ("\n".join(toc_lines) or "- 목차 파일(cover_and_toc.md) 참조") + "\n\n"
        f"## 4. 등록 체크리스트\n\n" + "\n".join(f"- [ ] {c}" for c in plat["checklist"]) + "\n"
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{project_id}_POD_{platform}_{ts}.zip"
    zip_path = mon_dir / zip_name

    included: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_pod_metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        zf.writestr("01_pod_submission_guide.md", guide_md)
        included.extend(["00_pod_metadata.json", "01_pod_submission_guide.md"])

        front_dir = exp_dir / "front_matter"
        if front_dir.is_dir():
            for fp in sorted(front_dir.iterdir()):
                if fp.is_file():
                    arc = f"front_matter/{fp.name}"
                    zf.write(fp, arc)
                    included.append(arc)

        master_dir = exp_dir / "master_book"
        if master_dir.is_dir():
            for fp in sorted(master_dir.iterdir()):
                if fp.is_file() and fp.suffix.lower() in (".pdf", ".docx", ".yml"):
                    arc = f"master_book/{fp.name}"
                    zf.write(fp, arc)
                    included.append(arc)

        # 마스터 PDF가 아직 없다면 단원별 교재 PDF 포함
        if not any(x.startswith("master_book/") and x.endswith(".pdf") for x in included) and exp_dir.is_dir():
            for fp in sorted(exp_dir.glob("ch*/ch*_textbook.pdf")):
                arc = f"chapters_pdf/{fp.name}"
                zf.write(fp, arc)
                included.append(arc)

    return {
        "status": "OK",
        "platform": platform,
        "zip_filename": zip_name,
        "download_url": f"/project-files/{project_id}/exports/monetization/{zip_name}",
        "included_count": len(included),
        "included_files": included[:30],
        "size_kb": round(zip_path.stat().st_size / 1024, 1),
        "metadata": metadata,
    }


def build_b2g_delivery_package(
    *,
    project_id: str,
    client_org: str = "지역 농업기술센터 / 지자체 농정과",
    contract_title: str = "",
    trim_format: str = "a4",
    contract_amount_krw: int = 5000000,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """2단계 B2B/B2G(농업기술센터·지자체·스마트팜 기업) 기관 맞춤 보고서·교재 납품 패키지를 생성한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    exp_dir = ws / "exports"
    mon_dir = exp_dir / "monetization"
    mon_dir.mkdir(parents=True, exist_ok=True)

    topic_ko = st.get("topic_ko", project_id)
    title_final = contract_title.strip() or f"{client_org} 맞춤형 《{topic_ko}》 기술교재 및 연구보고서"
    manifest_md = (
        f"# B2B / B2G 기관 맞춤 납품 명세서\n\n"
        f"- **발주 기관**: {client_org}\n"
        f"- **과업명**: {title_final}\n"
        f"- **납품 판형**: {'A4 기관 보고서판 (210×297mm)' if trim_format == 'a4' else 'B5 교육교재판 (182×257mm)'}\n"
        f"- **예상 용역 금액**: {contract_amount_krw:,}원\n"
        f"- **생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"## 학술 무결성 및 품질 보증\n"
        f"- 총 {len(st.get('collected_sources') or [])}건의 1차 공식기관·학술지 근거 패킷 `[SRC-NN]` 1:1 매핑 완료\n"
        f"- 로컬 지식그래프(`C:\\SMC_GRAPHRAG`) 기반 환각 차단 및 15어절 원문 무단 복제 감사 게이트 적용\n"
        f"- 인쇄용 300 DPI 도판 및 Word(.docx) 편집 원본 동시 납품\n"
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{project_id}_B2G_delivery_{ts}.zip"
    zip_path = mon_dir / zip_name

    included: list[str] = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_b2g_delivery_manifest.md", manifest_md)
        included.append("00_b2g_delivery_manifest.md")
        if exp_dir.is_dir():
            for fp in sorted(exp_dir.glob("ch*/ch*_report.docx")):
                arc = f"docx/{fp.name}"
                zf.write(fp, arc)
                included.append(arc)
            for fp in sorted(exp_dir.glob("ch*/ch*_textbook.pdf")):
                arc = f"pdf/{fp.name}"
                zf.write(fp, arc)
                included.append(arc)
            for rp in sorted((ws / "reports").glob("*.md")) if (ws / "reports").is_dir() else []:
                arc = f"reports/{rp.name}"
                zf.write(rp, arc)
                included.append(arc)

    return {
        "status": "OK",
        "client_org": client_org,
        "zip_filename": zip_name,
        "download_url": f"/project-files/{project_id}/exports/monetization/{zip_name}",
        "included_count": len(included),
        "size_kb": round(zip_path.stat().st_size / 1024, 1),
    }


def build_naver_marketing_bundle(
    *,
    project_id: str,
    academy_cta_title: str = "참참살이 영농 AI 아카데미 · 주간 정밀영농 리포트 구독 안내",
    academy_cta_url: str = "https://blog.naver.com/",
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """3단계 네이버 블로그 마케팅용 HTML(20개 해시태그 보장 + CTA 배너 삽입) 일괄 번들을 생성한다."""
    from naver_blog_formatter import generate_20_hashtags, render_hashtag_box_html
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    exp_dir = ws / "exports"
    mon_dir = exp_dir / "monetization"
    mon_dir.mkdir(parents=True, exist_ok=True)

    topic_ko = st.get("topic_ko", project_id)
    cta_banner = (
        f'<div style="margin:28px 0;padding:18px 20px;background:#063b2c;color:#ffffff;border-radius:10px;'
        f'border-left:5px solid #eab308;font-family:Malgun Gothic,sans-serif;">'
        f'<div style="font-size:12px;color:#34d399;font-weight:700;">참참살이 영농 AI 출판도우미 · 아카데미 안내</div>'
        f'<div style="font-size:16px;font-weight:700;margin:6px 0;">{academy_cta_title}</div>'
        f'<div style="font-size:13px;color:#e2e8f0;">《{topic_ko}》 전체 교재(신국판·B5·전자책) 및 현장 영농 컨설팅 문의: '
        f'<a href="{academy_cta_url}" style="color:#fef08a;font-weight:700;">바로가기 ↗</a></div></div>'
    )

    naver_files = sorted(exp_dir.glob("ch*/ch*_naver_blog.html")) if exp_dir.is_dir() else []
    chapter_tags: list[dict[str, Any]] = []

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{project_id}_naver_blog_marketing_{ts}.zip"
    zip_path = mon_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if naver_files:
            for idx, nf in enumerate(naver_files, 1):
                cid = nf.parent.name
                raw_html = nf.read_text(encoding="utf-8", errors="ignore")
                existing_tags = re.findall(r"#[가-힣A-Za-z0-9_]{2,}", raw_html)
                if len(existing_tags) < 20:
                    tags = generate_20_hashtags(cid, topic_ko, raw_html[:1500])
                    raw_html = raw_html + "\n" + render_hashtag_box_html(tags, idx)
                else:
                    tags = existing_tags[:20]
                enhanced = raw_html + "\n" + cta_banner
                zf.writestr(f"posts/{cid}_naver_marketing.html", enhanced)
                chapter_tags.append({"chapter_id": cid, "hashtag_count": len(tags), "tags": tags[:20]})
        else:
            # 6단계 HTML이 없으면 원고 기반으로 즉시 20개 해시태그 세트 생성
            for idx, p in enumerate(sorted((ws / "chapters").glob("*.mdx")) if (ws / "chapters").is_dir() else [], 1):
                cid = p.stem
                txt = p.read_text(encoding="utf-8", errors="ignore")
                tags = generate_20_hashtags(cid, topic_ko, txt[:1500])
                post_html = f"<h2>《{topic_ko}》 {cid} 핵심 요약</h2><p>{txt[:600]}</p>{render_hashtag_box_html(tags, idx)}{cta_banner}"
                zf.writestr(f"posts/{cid}_naver_marketing.html", post_html)
                chapter_tags.append({"chapter_id": cid, "hashtag_count": len(tags), "tags": tags[:20]})

        summary = {
            "project_id": project_id,
            "topic_ko": topic_ko,
            "generated_at": utc_now_iso(),
            "posts_bundled": len(chapter_tags),
            "chapters": chapter_tags,
        }
        zf.writestr("naver_hashtags_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))

    return {
        "status": "OK",
        "zip_filename": zip_name,
        "download_url": f"/project-files/{project_id}/exports/monetization/{zip_name}",
        "posts_bundled": len(chapter_tags),
        "sample_hashtags": chapter_tags[0]["tags"] if chapter_tags else [],
        "size_kb": round(zip_path.stat().st_size / 1024, 1),
    }


def generate_saas_license_package(
    *,
    project_id: str,
    tenant_name: str = "참참살이 영농 AI 출판 파트너",
    domain_vertical: str = "스마트 농업 · 생명과학",
    plan_tier: str = "Pro Author (월 49,000원)",
    monthly_quota_chapters: int = 40,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """4단계 SaaS & API 라이선싱용 화이트라벨 테넌트 설정 패키지를 생성한다."""
    from agro_framework import BRAND_IDENTITY
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    mon_dir = ws / "exports" / "monetization"
    mon_dir.mkdir(parents=True, exist_ok=True)

    profile = {
        "schema_version": "1.0",
        "generated_at": utc_now_iso(),
        "engine": BRAND_IDENTITY["app_title"],
        "tenant": {
            "tenant_name": tenant_name,
            "domain_vertical": domain_vertical,
            "plan_tier": plan_tier,
            "monthly_quota_chapters": monthly_quota_chapters,
            "enabled_modules": [
                "6stage_pipeline",
                "graphrag_hybrid_qa",
                "abcd_visual_director_300dpi",
                "single_source_shinkuk_b5_a4",
                "pod_and_naver_monetization",
            ],
            "theme": BRAND_IDENTITY["palette"],
        },
        "api_endpoints": {
            "create_project": "POST /api/projects",
            "run_pipeline": "POST /api/projects/{id}/run",
            "citation_audit": "POST /api/projects/{id}/inspector/audit",
            "multi_format_bind": "POST /api/projects/{id}/publish/multi-format",
            "pod_export": "POST /api/projects/{id}/monetization/pod-export",
            "gdd_diagnose": "POST /api/agro/gdd-diagnose",
        },
    }
    out_p = mon_dir / f"saas_tenant_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_p.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "OK",
        "filename": out_p.name,
        "download_url": f"/project-files/{project_id}/exports/monetization/{out_p.name}",
        "profile": profile,
    }


def simulate_monetization_revenue(
    *,
    pod_monthly_copies: int = 80,
    pod_unit_royalty: int = 8500,
    b2g_quarterly_contracts: int = 2,
    b2g_contract_value: int = 4500000,
    academy_subscribers: int = 60,
    academy_monthly_fee: int = 29000,
    saas_tenants: int = 15,
    saas_monthly_fee: int = 49000,
) -> dict[str, Any]:
    """4단계 수익화 채널 통합 월/연 예상 수익 시뮬레이터."""
    m_pod = max(0, pod_monthly_copies) * max(0, pod_unit_royalty)
    m_b2g = int(round((max(0, b2g_quarterly_contracts) * max(0, b2g_contract_value)) / 3.0))
    m_academy = max(0, academy_subscribers) * max(0, academy_monthly_fee)
    m_saas = max(0, saas_tenants) * max(0, saas_monthly_fee)
    m_total = m_pod + m_b2g + m_academy + m_saas
    return {
        "monthly": {
            "b2c_pod_krw": m_pod,
            "b2b_b2g_krw": m_b2g,
            "traffic_academy_krw": m_academy,
            "saas_licensing_krw": m_saas,
            "total_krw": m_total,
        },
        "annual_total_krw": m_total * 12,
        "shares_pct": {
            "b2c_pod": round((m_pod / max(1, m_total)) * 100, 1),
            "b2b_b2g": round((m_b2g / max(1, m_total)) * 100, 1),
            "traffic_academy": round((m_academy / max(1, m_total)) * 100, 1),
            "saas_licensing": round((m_saas / max(1, m_total)) * 100, 1),
        },
    }
