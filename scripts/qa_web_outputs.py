"""Phase 3 인터랙티브 웹페이지 자동 시각·반응형 QA 스크립트 (Playwright + 로컬 Chrome/Edge).

데스크톱(1280x800) 및 모바일(390x844) 뷰포트에서 모든 빌드된 인터랙티브 HTML을 열어:
1. 콘솔 오류(console error) 0건
2. 런타임 페이지 예외(pageerror) 0건
3. 가로 넘침(horizontal overflow) 0건
4. [SRC-NN] 인용 칩 클릭 시 우측 근거 패널 렌더링 정상 동작
을 검증하고 스크린샷을 reports/qa_screenshots/ 에 저장한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from config import get_config


def _find_browser_exe() -> str | None:
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(p).is_file():
            return p
    return None


def qa_chapters(chapter_ids: list[str]) -> dict[str, Any]:
    cfg = get_config()
    exe = _find_browser_exe()
    shot_dir = cfg.reports_dir / "qa_screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    all_ok = True

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe, headless=True) if exe else p.chromium.launch(headless=True)
        try:
            for cid in chapter_ids:
                html_file = cfg.workspace_exports_dir / cid / f"{cid}_interactive.html"
                if not html_file.is_file():
                    results.append({"chapter_id": cid, "ok": False, "error": "HTML missing"})
                    all_ok = False
                    continue

                ch_res: dict[str, Any] = {"chapter_id": cid, "viewports": {}, "ok": True}
                for label, vp in [("desktop_1280", {"width": 1280, "height": 800}), ("mobile_390", {"width": 390, "height": 844})]:
                    ctx = browser.new_context(viewport=vp)
                    page = ctx.new_page()
                    console_errs: list[str] = []
                    page_errs: list[str] = []
                    page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
                    page.on("pageerror", lambda e: page_errs.append(str(e)))

                    page.goto(html_file.resolve().as_uri(), wait_until="networkidle")
                    overflow = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 2")

                    # 첫 [SRC-NN] 버튼 클릭 테스트
                    cite_ok = True
                    cite_btns = page.locator("button.cite-btn")
                    if cite_btns.count() > 0:
                        cite_btns.first.click()
                        card_txt = page.locator("#citeCard").inner_text()
                        cite_ok = "SRC-" in card_txt

                    shot_path = shot_dir / f"{cid}_{label}.png"
                    page.screenshot(path=str(shot_path), full_page=False)
                    ctx.close()

                    vp_ok = (len(console_errs) == 0) and (len(page_errs) == 0) and (not overflow) and cite_ok
                    ch_res["viewports"][label] = {
                        "ok": vp_ok,
                        "console_errors": console_errs,
                        "page_errors": page_errs,
                        "horizontal_overflow": bool(overflow),
                        "cite_click_ok": cite_ok,
                        "screenshot": str(shot_path),
                    }
                    if not vp_ok:
                        ch_res["ok"] = False
                        all_ok = False
                results.append(ch_res)
        finally:
            browser.close()

    report = {"all_passed": all_ok, "results": results}
    out_file = cfg.reports_dir / "phase3_web_qa_report.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="인터랙티브 웹페이지 데스크톱·모바일 자동 QA")
    parser.add_argument("--chapters", default="ch01,ch07,ch10,ch11")
    args = parser.parse_args()
    cids = [c.strip() for c in args.chapters.split(",") if c.strip()]
    res = qa_chapters(cids)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
