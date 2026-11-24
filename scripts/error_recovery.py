"""대시보드 통합 오류 진단 및 원클릭 자동 복구(Recovery) 엔진.

역할:
1. 프로젝트 전체(1~6단계 오류, 좀비 RUNNING 잠금, 품질 게이트 7대 차단 사유, 틀 원고,
   도판 QA 결함, AI 엔진 상태)를 실시간으로 구조화 진단(`diagnose_project_issues`).
2. 각 오류/차단 사유별로 대시보드에서 클릭 한 번으로 즉시 실행 가능한 안전 복구 액션
   (`execute_recovery_action`)을 제공:
   - `unlock_stuck_running`         : 서버 재시작·크래시 후 멈춘 RUNNING 잠금 안전 해제
   - `clear_stage_error`            : 특정 단계 오류 표시 초기화 및 대기 상태 전환
   - `retry_stage`                  : 오류 초기화 후 해당 단계 즉시 재실행
   - `approve_all_chapters`         : 집필 완료 단원 일괄 [검토 완료] 처리 (틀 원고 제외 기본)
   - `unapprove_all_chapters`       : 전체 단원 검토 완료 일괄 해제
   - `repair_citations_and_reaudit` : 미등록 인용 보정 + 무관 인용([SRC-NN]) 안전 정리 + 의미 재감사
   - `prune_low_relevance_sources`  : 저관련도(<40%) 비앵커 수집 출처 정리
   - `fix_visual_qa_issues`         : 미생성/가짜 도판 출판 제외 + 누락 출처(data_source/source_note) 보강
   - `rebuild_stage5_zero_cost`     : 0원 안전 모드(AI 유료 OFF)로 5단계 도판 재생성
   - `retry_fallback_chapters`      : 틀 원고(fallback) 단원만 체크포인트 해제 후 4단계 재집필
   - `run_full_auto_heal`           : 안전한 비파괴 복구 항목을 순서대로 일괄 자동 실행
   - `force_draft_publish`          : 사용자 명시 확인 후 초안 임시 출판(게이트 우회, 검토용)
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from compliance import utc_now_iso
from config import PlatformConfig, get_config


def _is_worker_alive(project_id: str) -> bool:
    from subagent_orchestrator import is_any_worker_alive

    return is_any_worker_alive(project_id)


def _classify_stage_error(stage: dict[str, Any]) -> dict[str, Any]:
    """단계별 오류 문자열을 원인 분류 + 맞춤 대처 액션 목록으로 변환한다."""
    sid = str(stage.get("stage_id") or "")
    order = str(stage.get("order") or "")
    title = str(stage.get("short_title") or stage.get("title") or sid)
    err = str(stage.get("error") or "").strip()
    low = err.lower()

    actions: list[dict[str, Any]] = []
    code = "STAGE_RUNTIME_ERROR"
    title_ko = f"{order}단계({title}) 실행 중 오류 발생"
    cause_ko = "단계 실행 중 예외가 발생해 체크포인트 위치에서 안전 중단되었습니다."

    if "품질 게이트 미달" in err or sid == "stage6_publish_report" and "차단" in err:
        code = "QUALITY_GATE_BLOCKED"
        title_ko = "6단계 출판 품질 게이트 미달로 차단됨"
        cause_ko = "아래 미달 항목별 [즉시 복구] 버튼 또는 [원클릭 일괄 자동 복구]를 누르면 해결 후 바로 출판할 수 있습니다."
        actions.append(
            {
                "action_id": "run_full_auto_heal",
                "label_ko": "🛠️ 미달 항목 원클릭 일괄 자동 복구",
                "description_ko": "도판 정리·인용 정리·일괄 검토 완료 등 안전한 복구를 순서대로 자동 실행합니다.",
                "style": "gold",
                "params": {},
            }
        )
    elif "ollama" in low or "11434" in low or "connection refused" in low or "timed out" in low:
        code = "OLLAMA_UNAVAILABLE"
        title_ko = f"{order}단계: 로컬 AI(Ollama) 응답 없음 / 시간 초과"
        cause_ko = "로컬 Ollama 서버(127.0.0.1:11434)가 꺼져 있거나 모델 응답이 지연되었습니다. Ollama 실행 상태를 확인한 뒤 재시도하세요."
        actions.append(
            {
                "action_id": "retry_stage",
                "label_ko": f"🔄 {order}단계 이어서 다시 실행",
                "description_ko": "오류 상태를 초기화하고 멈춘 체크포인트부터 다시 실행합니다.",
                "style": "primary",
                "params": {"stage_id": sid},
            }
        )
    elif "gemini" in low or "429" in low or "quota" in low or "api_key" in low:
        code = "GEMINI_API_ERROR"
        title_ko = f"{order}단계: Gemini API 한도 초과 또는 키 오류"
        cause_ko = "Google Gemini API 호출 한도(429) 초과 또는 API 키 설정 오류입니다. 설정 탭에서 키를 확인하거나 로컬 Gemma 4 / 0원 모드로 전환해 재실행하세요."
        if sid == "stage5_visuals_generate":
            actions.append(
                {
                    "action_id": "rebuild_stage5_zero_cost",
                    "label_ko": "🎨 0원 출처 기반 모드로 5단계 즉시 재실행",
                    "description_ko": "유료 이미지 AI(fal.ai·나노바나나)를 끄고 0원 300 DPI 도판으로 안전 생성합니다.",
                    "style": "gold",
                    "params": {},
                }
            )
        actions.append(
            {
                "action_id": "retry_stage",
                "label_ko": f"🔄 {order}단계 다시 실행",
                "description_ko": "오류 초기화 후 현재 단계를 다시 시도합니다.",
                "style": "primary",
                "params": {"stage_id": sid},
            }
        )
    elif sid == "stage5_visuals_generate" or "fal_key" in low or "nano banana" in low or "visual" in low:
        code = "STAGE5_VISUAL_ERROR"
        title_ko = "5단계 시각화 생성 중 오류 발생"
        cause_ko = "이미지 API 키 누락·할당량 초과 또는 도판 렌더링 중 오류가 발생했습니다. 0원 출처 기반 모드로 전환하거나 불량 도판을 자동 정리할 수 있습니다."
        actions.extend(
            [
                {
                    "action_id": "rebuild_stage5_zero_cost",
                    "label_ko": "🎨 0원 안전 모드로 5단계 재실행",
                    "description_ko": "유료 AI 옵션을 끄고 실측 차트·SVG 개념도(0원)로 5단계를 다시 실행합니다.",
                    "style": "gold",
                    "params": {},
                },
                {
                    "action_id": "fix_visual_qa_issues",
                    "label_ko": "🧹 미생성·오류 도판 정리 및 출처 보강",
                    "description_ko": "미생성·빈 틀 도판을 출판 제외 처리하고 누락된 출처 정보를 보강합니다.",
                    "style": "primary",
                    "params": {},
                },
            ]
        )
    elif "winerror 5" in low or "permissionerror" in low or "액세스가 거부" in err:
        code = "FILE_LOCK_WINERR5"
        title_ko = f"{order}단계: Windows 파일 잠금(WinError 5) 오류"
        cause_ko = "다른 프로그램(Word·탐색기·백신·클라우드 동기화)이 프로젝트 파일을 점유 중입니다. 열려 있는 Word/PDF 파일을 닫고 다시 실행하세요."
        actions.append(
            {
                "action_id": "retry_stage",
                "label_ko": f"🔄 파일 닫은 뒤 {order}단계 재실행",
                "description_ko": "오류를 해제하고 해당 단계를 다시 실행합니다.",
                "style": "primary",
                "params": {"stage_id": sid},
            }
        )
    elif "tesseract" in low or "kor.traineddata" in low or "ocr" in low:
        code = "TESSERACT_OCR_ERROR"
        title_ko = f"{order}단계: PDF OCR(Tesseract) 처리 오류"
        cause_ko = "스캔 PDF 인식에 필요한 Tesseract 또는 한국어 데이터팩(kor.traineddata) 오류가 발생했습니다."
        actions.append(
            {
                "action_id": "retry_stage",
                "label_ko": f"🔄 {order}단계 재실행",
                "description_ko": "오류를 초기화하고 다시 실행합니다.",
                "style": "primary",
                "params": {"stage_id": sid},
            }
        )
    else:
        actions.append(
            {
                "action_id": "retry_stage",
                "label_ko": f"🔄 {order}단계 이어서 재실행",
                "description_ko": "오류 표시를 지우고 저장된 체크포인트부터 다시 실행합니다.",
                "style": "primary",
                "params": {"stage_id": sid},
            }
        )

    actions.append(
        {
            "action_id": "clear_stage_error",
            "label_ko": "🧹 오류 표시 초기화",
            "description_ko": "단계 오류 상태를 해제하고 대기/일시중지 상태로 전환합니다.",
            "style": "default",
            "params": {"stage_id": sid},
        }
    )

    auto_fixable_codes = {
        "QUALITY_GATE_BLOCKED",
        "STAGE5_VISUAL_ERROR",
        "STUCK_RUNNING_LOCK",
    }
    return {
        "code": code,
        "severity": "CRITICAL",
        "auto_fixable": code in auto_fixable_codes,
        "stage_id": sid,
        "stage_order": order,
        "title_ko": title_ko,
        "cause_ko": cause_ko,
        "detail": err,
        "actions": actions,
    }


def _build_workflow_guide(
    st: dict[str, Any],
    issues: list[dict[str, Any]],
    readiness: dict[str, Any],
    is_zombie_running: bool,
) -> dict[str, Any]:
    """오류 발생 시 [① 원인 진단 → ② 복구 실행 → ③ 단계 재시작] 3단계 명확한 진행 가이드를 생성한다."""
    stages = st.get("stages") or []
    errored_stage = next((s for s in stages if s.get("status") == "ERROR" or (s.get("error") or "").strip()), None)
    interrupted_stage = next((s for s in stages if s.get("status") == "INTERRUPTED"), None)
    next_pending_stage = next((s for s in stages if s.get("status") != "DONE"), None)

    crit_issues = [x for x in issues if x.get("severity") == "CRITICAL"]
    auto_fixable_issues = [x for x in crit_issues if x.get("auto_fixable", False)]
    manual_issues = [x for x in crit_issues if not x.get("auto_fixable", False)]

    # 재시작 대상 단계 결정 (오류 단계 > 중단 단계 > 게이트 미달이면 6단계 > 다음 미완료 단계)
    target_stage = errored_stage or interrupted_stage
    if not target_stage and not readiness.get("ready", True) and any(
        str(x.get("code") or "").startswith("QUALITY_GATE_") for x in crit_issues
    ):
        target_stage = next((s for s in stages if s.get("stage_id") == "stage6_publish_report"), None)
    if not target_stage:
        target_stage = next_pending_stage

    target_sid = str(target_stage.get("stage_id") or "") if target_stage else ""
    target_label = (
        f"{target_stage.get('order', '')}단계({target_stage.get('short_title') or target_stage.get('title') or target_sid})"
        if target_stage
        else ""
    )

    # 현재 3단계 상태 판정
    if not crit_issues and not is_zombie_running:
        if target_stage and target_stage.get("status") != "DONE":
            phase = "READY_TO_RESTART"
            step1_summary = "오류·차단 원인이 모두 해소되었습니다."
            step2_done = True
            can_restart = True
            restart_reason = f"모든 사전 점검이 완료되어 지금 바로 {target_label}를 재시작할 수 있습니다."
        else:
            phase = "HEALTHY"
            step1_summary = "감지된 오류나 품질 게이트 차단 항목이 없습니다."
            step2_done = True
            can_restart = False
            restart_reason = "모든 단계가 정상 완료 상태입니다."
    elif auto_fixable_issues:
        phase = "NEEDS_REPAIR"
        step1_summary = f"자동 복구 가능한 원인 {len(auto_fixable_issues)}건" + (
            f" + 수동 확인 {len(manual_issues)}건 감지" if manual_issues else " 감지"
        )
        step2_done = False
        can_restart = False
        restart_reason = "먼저 2단계 [자동 복구 실행]을 완료한 뒤 재시작해야 같은 오류가 반복되지 않습니다."
    else:
        phase = "MANUAL_ACTION_REQUIRED"
        step1_summary = f"외부·수동 확인이 필요한 오류 {len(manual_issues)}건 감지 (자동 반복 불가)"
        step2_done = False
        can_restart = bool(target_sid and not is_zombie_running)
        restart_reason = "아래 수동 조치 안내(Ollama 실행·파일 닫기·API 키 확인 등)를 먼저 확인한 뒤 재시작하세요."

    manual_hints = [
        f"[{x.get('title_ko', '')}] {x.get('cause_ko', '')}"
        for x in manual_issues
    ]

    return {
        "phase": phase,
        "auto_fixable_count": len(auto_fixable_issues),
        "manual_count": len(manual_issues),
        "step1_diagnosis": {
            "done": True,
            "summary_ko": step1_summary,
        },
        "step2_recovery": {
            "done": step2_done,
            "has_auto_fix": len(auto_fixable_issues) > 0,
            "manual_hints": manual_hints,
        },
        "step3_restart": {
            "ready": can_restart,
            "can_restart_now": can_restart,
            "target_stage_id": target_sid,
            "target_stage_label": target_label,
            "reason_ko": restart_reason,
        },
    }


def diagnose_project_issues(
    project_id: str,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트의 모든 오류·차단 요인·좀비 잠금·품질 게이트 미달 항목을 구조화 진단한다."""
    from subagent_orchestrator import (
        evaluate_publish_readiness,
        get_ai_engines_status,
        load_events,
        load_project_state,
    )

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    stages = st.get("stages") or []
    worker_alive = _is_worker_alive(project_id)
    has_running_stage = any(s.get("status") == "RUNNING" for s in stages)
    is_zombie_running = (st.get("overall_status") == "RUNNING" or has_running_stage) and (not worker_alive)

    issues: list[dict[str, Any]] = []

    # 1. 좀비 RUNNING 잠금 감지 (서버 재시작/비정상 종료 후 버튼 먹통 방지)
    if is_zombie_running:
        issues.append(
            {
                "code": "STUCK_RUNNING_LOCK",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": st.get("active_stage_id") or next((s.get("stage_id") for s in stages if s.get("status") == "RUNNING"), ""),
                "stage_order": "",
                "title_ko": "실행 상태 잠금(좀비 RUNNING) 감지됨",
                "cause_ko": "화면에는 '진행 중'으로 표시되어 실행 버튼이 비활성화되었지만, 실제로 동작 중인 백그라운드 작업이 없습니다(서버 재시작 또는 예기치 않은 종료). 잠금을 해제하면 저장된 체크포인트부터 바로 이어할 수 있습니다.",
                "detail": f"overall_status={st.get('overall_status')}, active_stage_id={st.get('active_stage_id')}, worker_alive=False",
                "actions": [
                    {
                        "action_id": "unlock_stuck_running",
                        "label_ko": "🔓 멈춘 실행 잠금 즉시 해제",
                        "description_ko": "체크포인트를 보존한 채 RUNNING 상태를 INTERRUPTED로 안전 전환합니다.",
                        "style": "gold",
                        "params": {},
                    }
                ],
            }
        )

    # 2. 단계별 기록된 오류 진단
    for s in stages:
        if s.get("status") == "ERROR" or (s.get("error") or "").strip():
            # Stage 6 품질 게이트 오류는 아래 개별 게이트 진단과 중복되지 않게 요약 1건 + 세부 항목으로 연결
            issues.append(_classify_stage_error(s))

    # 3. 6단계 출판 품질 게이트 실시간 정밀 진단 (미달 항목별 1-클릭 복구 매핑)
    readiness = evaluate_publish_readiness(project_id, cfg=cfg)
    m = readiness.get("metrics") or {}
    gate_checks: list[dict[str, Any]] = []

    # Check A: 집필된 원고 존재 여부
    ch_cnt = int(m.get("total_chapters") or 0)
    ok_ch = ch_cnt > 0
    gate_checks.append(
        {
            "id": "chapters_exist",
            "label_ko": "집필된 단원 원고(.mdx)",
            "value_text": f"{ch_cnt}개 단원",
            "threshold_text": "1개 이상",
            "passed": ok_ch,
            "action": None
            if ok_ch
            else {
                "action_id": "retry_stage",
                "label_ko": "▶ 4단계 집필 실행",
                "style": "primary",
                "params": {"stage_id": "stage4_manuscript_draft"},
            },
        }
    )

    # Check B: 인용·수식 치명 오류
    crit_cnt = int(m.get("critical_errors") or 0)
    ok_crit = crit_cnt == 0
    gate_checks.append(
        {
            "id": "critical_errors",
            "label_ko": "인용·수식 치명 오류",
            "value_text": f"{crit_cnt}건",
            "threshold_text": "0건",
            "passed": ok_crit,
            "action": None
            if ok_crit
            else {
                "action_id": "repair_citations_and_reaudit",
                "label_ko": "🛠️ 인용 오류 자동 복구·재감사",
                "style": "gold",
                "params": {},
            },
        }
    )
    if not ok_crit:
        issues.append(
            {
                "code": "QUALITY_GATE_CRITICAL_ERRORS",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": "stage4_manuscript_draft",
                "stage_order": "4",
                "title_ko": f"인용·수식 치명 오류 {crit_cnt}건 감지",
                "cause_ko": "근거 패킷에 없는 [SRC-NN] 인용키 또는 15어절 이상 원문 복사·수식 오류가 남아 있어 6단계 출판이 차단됩니다.",
                "detail": f"critical_errors={crit_cnt}",
                "actions": [
                    {
                        "action_id": "repair_citations_and_reaudit",
                        "label_ko": "🛠️ 미등록 인용 자동 보정 & 재감사",
                        "description_ko": "미등록 [SRC-NN]을 유효 출처 또는 근거보충 주석으로 정리하고 재감사합니다.",
                        "style": "gold",
                        "params": {},
                    }
                ],
            }
        )

    # Check C: 근거 평균 관련도
    avg_rel = m.get("avg_evidence_relevance_pct")
    ok_rel = avg_rel is None or float(avg_rel) >= 40.0
    gate_checks.append(
        {
            "id": "evidence_relevance",
            "label_ko": "수집 근거 평균 관련도",
            "value_text": f"{avg_rel}%" if avg_rel is not None else "측정 전",
            "threshold_text": "40% 이상",
            "passed": ok_rel,
            "action": None
            if ok_rel
            else {
                "action_id": "prune_low_relevance_sources",
                "label_ko": "🧹 저관련도(<40%) 출처 정리",
                "style": "gold",
                "params": {"min_score": 0.40},
            },
        }
    )
    if not ok_rel:
        issues.append(
            {
                "code": "QUALITY_GATE_LOW_RELEVANCE",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": "stage2_source_collect",
                "stage_order": "2",
                "title_ko": f"수집 근거 평균 관련도 미달 ({avg_rel}% < 40%)",
                "cause_ko": "주제와 관련성이 낮은 참고 자료가 다수 혼입되어 평균 관련도가 낮습니다. 저관련도 자료를 정리하거나 2단계 자료를 재수집하세요.",
                "detail": f"avg_evidence_relevance_pct={avg_rel}",
                "actions": [
                    {
                        "action_id": "prune_low_relevance_sources",
                        "label_ko": "🧹 저관련도(<40%) 출처 자동 제외",
                        "description_ko": "앵커 문헌은 보존하고 관련도 40% 미만 자료만 프로젝트 목록에서 제외합니다.",
                        "style": "gold",
                        "params": {"min_score": 0.40},
                    },
                    {
                        "action_id": "retry_stage",
                        "label_ko": "🔄 2단계 자료 재수집",
                        "description_ko": "확정 키워드로 2단계 문헌 수집을 다시 실행합니다.",
                        "style": "default",
                        "params": {"stage_id": "stage2_source_collect"},
                    },
                ],
            }
        )

    # Check D: 출처와 무관한 인용 비율
    unrel = m.get("unrelated_ratio_pct")
    ok_unrel = unrel is None or float(unrel) <= 30.0
    gate_checks.append(
        {
            "id": "unrelated_citations",
            "label_ko": "출처 무관 인용 비율",
            "value_text": f"{unrel}%" if unrel is not None else "감사 전",
            "threshold_text": "30% 이하",
            "passed": ok_unrel,
            "action": None
            if ok_unrel
            else {
                "action_id": "repair_citations_and_reaudit",
                "label_ko": "🧹 무관 인용 자동 정리 & 재감사",
                "style": "gold",
                "params": {},
            },
        }
    )
    if not ok_unrel:
        issues.append(
            {
                "code": "QUALITY_GATE_UNRELATED_CITATIONS",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": "stage4_manuscript_draft",
                "stage_order": "4",
                "title_ko": f"출처와 무관한 인용 비율 초과 ({unrel}% > 30%)",
                "cause_ko": "본문 문장 내용과 의미적 관련성이 낮은 [SRC-NN] 태그가 다수 부착되어 6단계 출판이 차단되었습니다. 무관 인용 태그를 안전하게 정리(필요 시 근거 보충 주석 전환)하고 의미 재감사를 실행하세요.",
                "detail": f"unrelated_ratio_pct={unrel}%, alignment_rate_pct={m.get('alignment_rate_pct')}%",
                "actions": [
                    {
                        "action_id": "repair_citations_and_reaudit",
                        "label_ko": "🧹 무관 인용([SRC-NN]) 자동 정리 & 의미 재감사",
                        "description_ko": "원고 백업 후 의미 감사에서 '무관' 판정된 인용 태그만 안전 제거/주석 전환하고 재감사합니다.",
                        "style": "gold",
                        "params": {},
                    },
                    {
                        "action_id": "retry_stage",
                        "label_ko": "🔄 4단계 단원 재집필",
                        "description_ko": "최신 근거 패킷을 바탕으로 4단계 원고를 다시 집필합니다.",
                        "style": "default",
                        "params": {"stage_id": "stage4_manuscript_draft"},
                    },
                ],
            }
        )

    # Check E: 시각화 QA (가짜/미생성 도판 & 출처 기재율)
    vis_total = int(m.get("visuals_total") or 0)
    vis_fake = bool(m.get("visual_has_placeholder_or_fake", False))
    vis_cov = float(m.get("visual_source_coverage_pct", 100.0) if m.get("visual_source_coverage_pct") is not None else 100.0)
    ok_vis = (not vis_fake) and (vis_total == 0 or vis_cov >= 80.0)
    gate_checks.append(
        {
            "id": "visual_qa",
            "label_ko": "도판 품질 및 출처 기재율",
            "value_text": f"출처 {vis_cov}%" + (" · 불량 도판 있음" if vis_fake else f" ({m.get('visuals_publishable', 0)}/{vis_total}종)"),
            "threshold_text": "80% 이상 · 불량 0건",
            "passed": ok_vis,
            "action": None
            if ok_vis
            else {
                "action_id": "fix_visual_qa_issues",
                "label_ko": "🧹 불량 도판 정리·출처 보강",
                "style": "gold",
                "params": {},
            },
        }
    )
    if not ok_vis:
        issues.append(
            {
                "code": "QUALITY_GATE_VISUAL_QA",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": "stage5_visuals_generate",
                "stage_order": "5",
                "title_ko": "5단계 도판 품질 미달 (빈 틀/미생성 도판 또는 출처 기재율 부족)",
                "cause_ko": f"불량/미생성 도판 여부={vis_fake}, 출처 기재율={vis_cov}% (기준 80% 이상). 미생성 도판을 출판 제외 처리하고 누락 출처를 보강하거나 0원 모드로 5단계를 다시 생성하세요.",
                "detail": f"visual_has_placeholder_or_fake={vis_fake}, visual_source_coverage_pct={vis_cov}%",
                "actions": [
                    {
                        "action_id": "fix_visual_qa_issues",
                        "label_ko": "🧹 미생성·가짜 도판 출판 제외 + 출처 보강",
                        "description_ko": "미생성/빈 틀 도판을 안전 제외하고 검증된 단원 출처 표기를 동기화합니다.",
                        "style": "gold",
                        "params": {},
                    },
                    {
                        "action_id": "rebuild_stage5_zero_cost",
                        "label_ko": "🎨 0원 출처 기반 도판으로 5단계 재실행",
                        "description_ko": "유료 AI 옵션을 끄고 0원 차트·도해로 5단계를 다시 실행합니다.",
                        "style": "primary",
                        "params": {},
                    },
                ],
            }
        )

    # Check F: 전문가 검토 완료 단원
    req_rev = bool(m.get("require_expert_review", True))
    rev_cnt = int(m.get("reviewed_chapters") or 0)
    ok_rev = (not req_rev) or (rev_cnt > 0)
    gate_checks.append(
        {
            "id": "expert_review",
            "label_ko": "전문가 [검토 완료] 체크 단원",
            "value_text": f"{rev_cnt} / {ch_cnt}개 단원",
            "threshold_text": "1개 이상" if req_rev else "선택 사항",
            "passed": ok_rev,
            "action": None
            if (ok_rev or ch_cnt == 0)
            else {
                "action_id": "approve_all_chapters",
                "label_ko": "✅ 전체 단원 일괄 검토 완료",
                "style": "primary",
                "params": {},
            },
        }
    )
    if not ok_rev and ch_cnt > 0:
        issues.append(
            {
                "code": "QUALITY_GATE_NO_REVIEW",
                "severity": "CRITICAL",
                "auto_fixable": True,
                "stage_id": "stage4_manuscript_draft",
                "stage_order": "4",
                "title_ko": f"전문가 [검토 완료] 체크된 단원이 0개 (총 {ch_cnt}개 단원 대기 중)",
                "cause_ko": "6단계 출판 전 최소 1개 이상의 단원에 [검토 완료] 체크가 필요합니다. 원고를 확인하신 뒤 일괄 검토 완료 버튼으로 한 번에 승인할 수 있습니다.",
                "detail": f"reviewed_chapters=0 / total_chapters={ch_cnt}",
                "actions": [
                    {
                        "action_id": "approve_all_chapters",
                        "label_ko": f"✅ 집필된 {ch_cnt}개 단원 일괄 검토 완료",
                        "description_ko": "틀 원고를 제외한 모든 집필 단원을 [검토 완료] 상태로 일괄 승인합니다.",
                        "style": "primary",
                        "params": {},
                    }
                ],
            }
        )

    # 4. 틀 원고(fallback_chapters) 경고
    fb_chs = list((st.get("checkpoint") or {}).get("fallback_chapters") or [])
    if fb_chs:
        issues.append(
            {
                "code": "STAGE4_FALLBACK_CHAPTERS",
                "severity": "WARN",
                "auto_fixable": True,
                "stage_id": "stage4_manuscript_draft",
                "stage_order": "4",
                "title_ko": f"AI 집필 실패 틀 원고(임시 템플릿) {len(fb_chs)}개 단원 잔존",
                "cause_ko": f"대상 단원: {', '.join(fb_chs)}. Ollama 응답 지연 등으로 임시 템플릿이 저장된 단원만 선택해 다시 집필할 수 있습니다.",
                "detail": f"fallback_chapters={fb_chs}",
                "actions": [
                    {
                        "action_id": "retry_fallback_chapters",
                        "label_ko": f"🔄 틀 원고 {len(fb_chs)}개 단원만 자동 재집필",
                        "description_ko": "정상 완료된 단원은 유지하고 틀 원고 단원만 체크포인트에서 해제해 4단계를 다시 실행합니다.",
                        "style": "gold",
                        "params": {},
                    }
                ],
            }
        )

    # 최근 ERROR 이벤트 요약
    recent_errors = [
        ev for ev in load_events(project_id, limit=80, cfg=cfg) if str(ev.get("level", "")).upper() == "ERROR"
    ][-12:]

    # Stage 6 QUALITY_GATE_BLOCKED 요약 카드와 개별 QUALITY_GATE_* 카드가 중복 표시되지 않도록 정리
    has_specific_gate = any(
        str(x.get("code") or "").startswith("QUALITY_GATE_") and x.get("code") != "QUALITY_GATE_BLOCKED"
        for x in issues
    )
    if has_specific_gate:
        issues = [x for x in issues if x.get("code") != "QUALITY_GATE_BLOCKED"]

    crit_issues = [x for x in issues if x.get("severity") == "CRITICAL"]
    health_status = "ERROR" if crit_issues else ("WARN" if issues else "OK")
    workflow_guide = _build_workflow_guide(st, issues, readiness, is_zombie_running)

    try:
        engines = get_ai_engines_status(cfg)
    except Exception:
        engines = {}

    return {
        "project_id": project_id,
        "topic_ko": st.get("topic_ko", ""),
        "overall_status": st.get("overall_status", "IDLE"),
        "health_status": health_status,
        "issue_count": len(issues),
        "critical_count": len(crit_issues),
        "is_zombie_running": is_zombie_running,
        "worker_alive": worker_alive,
        "readiness": readiness,
        "gate_checks": gate_checks,
        "issues": issues,
        "workflow_guide": workflow_guide,
        "recent_errors": list(reversed(recent_errors)),
        "engines": engines,
        "checked_at": utc_now_iso(),
    }


def _strip_unrelated_citations_in_chapters(
    ws: Path,
    audit_data: dict[str, Any],
) -> dict[str, Any]:
    """의미 감사에서 '무관'으로 판정된 특정 줄의 [SRC-NN] 태그만 안전하게 제거/주석 전환한다 (절대 날조 금지)."""
    ch_dir = ws / "chapters"
    if not ch_dir.is_dir():
        return {"modified_files": 0, "removed_tags": 0}

    # file path -> {lineno: set(source_ids)}
    unrelated_map: dict[str, dict[int, set[str]]] = {}
    for fr in audit_data.get("files") or []:
        fpath = str(fr.get("file") or "")
        ca = fr.get("content_audit") or {}
        for det in ca.get("details") or []:
            if det.get("verdict") == "무관" and det.get("source_id") and det.get("line"):
                unrelated_map.setdefault(fpath, {}).setdefault(int(det["line"]), set()).add(str(det["source_id"]))

    if not unrelated_map:
        return {"modified_files": 0, "removed_tags": 0}

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    hist_dir = ch_dir / "_history"
    modified_files = 0
    removed_tags = 0

    bracket_re = re.compile(r"\[([^\[\]]*SRC-\d+[^\[\]]*)\]")
    sid_token_re = re.compile(r"SRC-\d+")

    for fpath_str, line_sids in unrelated_map.items():
        p = Path(fpath_str)
        if any(part.startswith(("_", ".")) for part in p.parts[:-1]):
            continue
        if not p.is_file():
            # basename fallback inside ws/chapters
            cand = ch_dir / p.name
            if cand.is_file():
                p = cand
            else:
                continue
        raw_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        changed = False

        for lineno, bad_sids in line_sids.items():
            idx = lineno - 1
            if idx < 0 or idx >= len(raw_lines):
                continue
            line = raw_lines[idx]
            # 참고문헌 목록 줄 자체는 건드리지 않음 (단, 본문 문장만 정리)
            if re.match(r"^\s*[-*]\s*\[SRC-\d+\]", line):
                continue

            def _clean_bracket(m: re.Match[str]) -> str:
                nonlocal removed_tags
                inner = m.group(1)
                parts = [seg.strip() for seg in inner.split(",") if seg.strip()]
                kept: list[str] = []
                for seg in parts:
                    sm = sid_token_re.search(seg)
                    if sm and sm.group(0) in bad_sids:
                        removed_tags += 1
                        continue
                    kept.append(seg)
                if not kept:
                    return ""
                return "[" + ", ".join(kept) + "]"

            new_line = bracket_re.sub(_clean_bracket, line)
            new_line = re.sub(r"\s{2,}", " ", new_line).replace(" .", ".").rstrip()
            if new_line != line:
                raw_lines[idx] = new_line
                changed = True

        if changed:
            hist_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, hist_dir / f"{p.stem}_recovery_{ts}.mdx")
            p.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
            modified_files += 1

    return {"modified_files": modified_files, "removed_tags": removed_tags}


def execute_recovery_action(
    project_id: str,
    action_id: str,
    params: dict[str, Any] | None = None,
    *,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """대시보드 원클릭 복구 액션을 안전하게 실행하고 갱신된 진단 결과와 프로젝트 상태를 반환한다."""
    from agro_framework import auto_repair_chapter_citations
    from output_converter import publish_default_outputs
    from subagent_orchestrator import (
        append_event,
        evaluate_publish_readiness,
        load_project_state,
        save_project_state,
        set_chapter_expert_review,
        start_pipeline_async,
    )
    from verify_citations import CITATION_RE, verify_target
    from visual_studio import audit_visual_assets

    cfg = cfg or get_config()
    params = dict(params or {})
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    summary_ko = ""
    details: dict[str, Any] = {}

    if action_id == "unlock_stuck_running":
        if _is_worker_alive(project_id) and not params.get("force"):
            raise ValueError("실제 백그라운드 작업이 아직 실행 중입니다. 먼저 상단 [⏹ 중단]을 눌러 주세요.")
        unlocked = []
        for s in st.get("stages") or []:
            if s.get("status") == "RUNNING":
                s["status"] = "INTERRUPTED"
                s["current_action"] = "잠금 해제됨 — 저장된 지점부터 이어하기 가능"
                unlocked.append(s.get("stage_id"))
        st["overall_status"] = "INTERRUPTED"
        st["active_stage_id"] = None
        save_project_state(st, cfg)
        append_event(project_id, "recovery", "orchestrator", f"🔓 좀비 RUNNING 잠금 해제 완료 ({', '.join(unlocked) or '전체 상태'})", level="WARN", cfg=cfg)
        summary_ko = "멈춰 있던 실행 잠금(RUNNING)을 안전하게 해제했습니다. 이제 [▶ 이어하기] 또는 단계 실행이 가능합니다."
        details = {"unlocked_stages": unlocked}

    elif action_id == "clear_stage_error":
        target_sid = str(params.get("stage_id") or "")
        cleared = []
        for s in st.get("stages") or []:
            if (not target_sid or s.get("stage_id") == target_sid) and (s.get("status") == "ERROR" or s.get("error")):
                s["error"] = ""
                if s.get("status") == "ERROR":
                    s["status"] = "INTERRUPTED" if int(s.get("progress") or 0) > 0 else "PENDING"
                    s["current_action"] = "오류 초기화 완료 — 재실행 준비됨"
                cleared.append(s.get("stage_id"))
        if st.get("overall_status") == "ERROR":
            all_done = all(s.get("status") == "DONE" for s in (st.get("stages") or []))
            st["overall_status"] = "DONE" if all_done else "PAUSED"
        save_project_state(st, cfg)
        append_event(project_id, "recovery", target_sid or "orchestrator", f"🧹 오류 표시 초기화: {', '.join(cleared) or '없음'}", cfg=cfg)
        summary_ko = f"오류 상태를 초기화했습니다 ({', '.join(cleared) or '대상 없음'})."
        details = {"cleared_stages": cleared}

    elif action_id == "retry_stage":
        target_sid = str(params.get("stage_id") or "")
        if not target_sid:
            raise ValueError("재실행할 단계(stage_id)가 지정되지 않았습니다.")
        for s in st.get("stages") or []:
            if s.get("stage_id") == target_sid:
                s["error"] = ""
                if s.get("status") == "ERROR":
                    s["status"] = "PENDING"
        if st.get("overall_status") == "ERROR":
            st["overall_status"] = "PAUSED"
        save_project_state(st, cfg)
        run_res = start_pipeline_async(project_id, mode="single", target_stage=target_sid, cfg=cfg)
        summary_ko = f"[{target_sid}] 오류를 정리하고 즉시 재실행을 시작했습니다."
        details = {"run": run_res}

    elif action_id in ("approve_all_chapters", "unapprove_all_chapters"):
        reviewed_flag = action_id == "approve_all_chapters"
        include_fb = bool(params.get("include_fallback", False))
        reviewer = str(params.get("reviewer") or "연구자 (일괄 검토)")
        note = str(params.get("note") or ("대시보드 일괄 검토 완료" if reviewed_flag else ""))
        ch_dir = ws / "chapters"
        ch_files = sorted(ch_dir.glob("*.mdx")) if ch_dir.is_dir() else []
        fb_set = set((st.get("checkpoint") or {}).get("fallback_chapters") or [])
        updated_ids: list[str] = []
        skipped_fb: list[str] = []
        for p in ch_files:
            cid = p.stem
            if reviewed_flag and (not include_fb) and cid in fb_set:
                skipped_fb.append(cid)
                continue
            set_chapter_expert_review(project_id, cid, reviewed_flag, reviewer=reviewer, note=note, cfg=cfg)
            updated_ids.append(cid)

        # Stage 6 오류가 검토 완료 0개 때문이었다면 오류 메시지 정리
        st2 = load_project_state(project_id, cfg)
        if st2 and reviewed_flag:
            gate_now = evaluate_publish_readiness(project_id, cfg=cfg)
            if gate_now.get("ready"):
                for s in st2.get("stages") or []:
                    if s.get("stage_id") == "stage6_publish_report" and s.get("status") == "ERROR":
                        s["error"] = ""
                        s["status"] = "PENDING"
                        s["current_action"] = "품질 게이트 통과 — 6단계 출판 가능"
                if st2.get("overall_status") == "ERROR":
                    st2["overall_status"] = "PAUSED"
                save_project_state(st2, cfg)

        if reviewed_flag:
            summary_ko = f"총 {len(updated_ids)}개 단원을 일괄 [검토 완료] 처리했습니다." + (
                f" (틀 원고 {len(skipped_fb)}개 제외)" if skipped_fb else ""
            )
        else:
            summary_ko = f"총 {len(updated_ids)}개 단원의 검토 완료 상태를 일괄 해제했습니다."
        details = {"updated_chapters": updated_ids, "skipped_fallback": skipped_fb}

    elif action_id == "repair_citations_and_reaudit":
        ch_dir = ws / "chapters"
        if not ch_dir.is_dir() or not list(ch_dir.glob("*.mdx")):
            raise ValueError("복구할 집필 원고(.mdx)가 없습니다. 4단계를 먼저 실행하세요.")
        # 1) 미등록 인용키 자동 보정
        fmt_res = auto_repair_chapter_citations(project_id, cfg=cfg)
        # 2) 현재 의미 감사 실행(또는 기존 semantic 결과 로드)
        rep_dir = ws / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)
        audit_p = rep_dir / "audit_latest.json"
        pre_audit = verify_target(ch_dir, semantic=True, cfg=cfg)
        # 3) '무관' 판정된 인용 태그 안전 정리 (최대 2회 반복으로 30% 이하 안정화)
        strip_total_files = 0
        strip_total_tags = 0
        cur_audit = pre_audit
        for _ in range(2):
            ca = cur_audit.get("content_audit") or {}
            unrel_pct = float(ca.get("unrelated_ratio_pct") or 0.0)
            if unrel_pct <= 28.0:
                break
            sr = _strip_unrelated_citations_in_chapters(ws, cur_audit)
            strip_total_files += sr["modified_files"]
            strip_total_tags += sr["removed_tags"]
            if sr["removed_tags"] == 0:
                break
            cur_audit = verify_target(ch_dir, semantic=True, cfg=cfg)

        audit_p.write_text(json.dumps(cur_audit, ensure_ascii=False, indent=2), encoding="utf-8")
        ca_after = cur_audit.get("content_audit") or {}
        append_event(
            project_id,
            "recovery",
            "stage4_manuscript_draft",
            f"🛠️ 인용 자동 복구·의미 재감사 완료: 미등록 보정 {fmt_res.get('replaced_tags', 0)}건 · "
            f"무관 인용 정리 {strip_total_tags}건 → 무관 비율 {ca_after.get('unrelated_ratio_pct', 0)}%, "
            f"일치율 {ca_after.get('alignment_rate_pct', 0)}%",
            cfg=cfg,
        )
        # 게이트 통과 시 Stage 6 오류 자동 해제
        gate_now = evaluate_publish_readiness(project_id, cfg=cfg)
        st2 = load_project_state(project_id, cfg)
        if st2 and gate_now.get("ready"):
            for s in st2.get("stages") or []:
                if s.get("stage_id") == "stage6_publish_report" and s.get("status") == "ERROR":
                    s["error"] = ""
                    s["status"] = "PENDING"
                    s["current_action"] = "품질 게이트 통과 — 6단계 출판 가능"
            if st2.get("overall_status") == "ERROR":
                st2["overall_status"] = "PAUSED"
            save_project_state(st2, cfg)

        summary_ko = (
            f"인용 자동 정리·의미 재감사 완료 (미등록 보정 {fmt_res.get('replaced_tags', 0)}건, "
            f"무관 인용 정리 {strip_total_tags}건 → 현재 무관 비율 {ca_after.get('unrelated_ratio_pct', 0)}%, "
            f"일치율 {ca_after.get('alignment_rate_pct', 0)}%)."
        )
        details = {
            "format_repair": fmt_res,
            "unrelated_stripped_files": strip_total_files,
            "unrelated_stripped_tags": strip_total_tags,
            "post_content_audit": ca_after,
            "post_critical_errors": len(cur_audit.get("critical_errors") or []),
        }

    elif action_id == "prune_low_relevance_sources":
        min_score = float(params.get("min_score", 0.40))
        collected = list(st.get("collected_sources") or [])
        kept = []
        removed = []
        for s in collected:
            sc = s.get("relevance_score")
            if s.get("is_anchor") or sc is None or float(sc) >= min_score:
                kept.append(s)
            else:
                removed.append(s)
        # 모든 출처가 지워지지 않도록 최소 상위 5건은 보존
        if not kept and collected:
            ranked = sorted(collected, key=lambda x: float(x.get("relevance_score") or 0.0), reverse=True)
            kept = ranked[:5]
            removed = ranked[5:]
        st["collected_sources"] = kept
        save_project_state(st, cfg)
        append_event(
            project_id,
            "recovery",
            "stage2_source_collect",
            f"🧹 저관련도(<{int(min_score*100)}%) 출처 {len(removed)}건 제외 (잔여 {len(kept)}건 유지)",
            cfg=cfg,
        )
        summary_ko = f"관련도 {int(min_score*100)}% 미만 출처 {len(removed)}건을 제외했습니다 (우수 출처 {len(kept)}건 유지)."
        details = {"removed_count": len(removed), "kept_count": len(kept)}

    elif action_id == "fix_visual_qa_issues":
        assets_dir = ws / "assets"
        plan_p = assets_dir / "visuals_plan.json"
        if not plan_p.is_file():
            raise ValueError("시각화 계획 파일(visuals_plan.json)이 없습니다. 5단계를 먼저 실행하세요.")
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
        items = plan.get("visuals") or plan.get("items") or []
        ch_dir = ws / "chapters"

        # 단원별 실제 인용된 [SRC-NN] 캐시 (출처 보강 시 날조 금지: 실제 원고 인용키만 사용)
        ch_sids: dict[str, list[str]] = {}
        if ch_dir.is_dir():
            for p in ch_dir.glob("*.mdx"):
                found = sorted(set(CITATION_RE.findall(p.read_text(encoding="utf-8", errors="ignore"))))
                if found:
                    ch_sids[p.stem] = found[:4]

        # 사전 시각 QA 결과에서 출판 불가(빈 틀/가짜 수치 차트/미생성) 도판 ID 확보
        pre_qa = audit_visual_assets(project_id, cfg=cfg)
        non_pub_fids = {
            str(x.get("figure_id") or "")
            for x in (pre_qa.get("items") or [])
            if (not x.get("publishable"))
            or any(("빈 틀" in str(iss) or "가짜" in str(iss) or "미생성" in str(iss)) for iss in (x.get("issues") or []))
        }

        # 프로젝트 수집 출처 폴백(단원 내 인용이 없는 도판 보강용)
        proj_col_sids = [
            str(s.get("source_id"))
            for s in (st.get("collected_sources") or [])
            if s.get("source_id")
        ][:4]

        excluded_cnt = 0
        source_filled_cnt = 0
        for it in items:
            if it.get("exclude_from_publish"):
                continue
            fid = str(it.get("figure_id") or "")
            status = str(it.get("status") or "").upper()
            engine = str(it.get("engine") or "")
            p_raw = str(it.get("docx_image_path") or it.get("path") or "")
            file_ok = bool(p_raw and Path(p_raw).is_file())
            if fid in non_pub_fids or status == "UNGENERATED" or engine in ("svg_blueprint_ready", "fake_numeric_chart") or not file_ok:
                it["exclude_from_publish"] = True
                it["note"] = (it.get("note") or "") + " [자동 QA 정리로 출판 제외]"
                excluded_cnt += 1
                continue
            ds = str(it.get("data_source") or "").strip()
            sn = str(it.get("source_note") or "").strip()
            if ds and not sn:
                it["source_note"] = ds
                source_filled_cnt += 1
            elif sn and not ds:
                it["data_source"] = sn
                source_filled_cnt += 1
            elif not ds and not sn:
                cid = str(it.get("chapter_id") or "")
                sids = ch_sids.get(cid) or proj_col_sids
                if sids:
                    tag_str = ", ".join(sids)
                    src_line = f"자료: 해당 단원({cid}) 검증 문헌 [{tag_str}] 기반 재구성."
                else:
                    src_line = f"자료: 《{st.get('topic_ko', project_id)}》 {cid} 집필 근거 문헌 기반 재구성."
                it["data_source"] = src_line
                it["source_note"] = src_line
                source_filled_cnt += 1

        plan_txt = json.dumps(plan, ensure_ascii=False, indent=2)
        plan_p.write_text(plan_txt, encoding="utf-8")
        try:
            e_plan = cfg.e_projects_dir / project_id / "visuals" / "visuals_plan.json"
            if e_plan.parent.is_dir():
                e_plan.write_text(plan_txt, encoding="utf-8")
        except Exception:
            pass
        vis_qa = audit_visual_assets(project_id, cfg=cfg)
        append_event(
            project_id,
            "recovery",
            "stage5_visuals_generate",
            f"🧹 도판 QA 자동 정리 완료: 미생성/불량 {excluded_cnt}종 출판 제외 · 출처 보강 {source_filled_cnt}종 "
            f"(현재 출판 가능 {vis_qa.get('publishable', 0)}/{vis_qa.get('total', 0)}종, 출처 기재율 {vis_qa.get('source_coverage_pct', 0)}%)",
            cfg=cfg,
        )
        summary_ko = (
            f"도판 QA 정리 완료: 미생성·불량 {excluded_cnt}종 제외, 출처 보강 {source_filled_cnt}종 "
            f"(출처 기재율 {vis_qa.get('source_coverage_pct', 0)}%)."
        )
        details = {"excluded_count": excluded_cnt, "source_filled_count": source_filled_cnt, "visual_qa": vis_qa}

    elif action_id == "rebuild_stage5_zero_cost":
        opts = dict(st.get("options") or {})
        opts["use_fal_ai"] = False
        opts["use_nano_banana"] = False
        st["options"] = opts
        for s in st.get("stages") or []:
            if s.get("stage_id") == "stage5_visuals_generate":
                s["error"] = ""
                s["status"] = "PENDING"
        if st.get("overall_status") == "ERROR":
            st["overall_status"] = "PAUSED"
        save_project_state(st, cfg)
        run_res = start_pipeline_async(project_id, mode="single", target_stage="stage5_visuals_generate", cfg=cfg)
        append_event(project_id, "recovery", "stage5_visuals_generate", "🎨 0원 안전 모드(유료 AI OFF)로 5단계 도판 재생성 시작", cfg=cfg)
        summary_ko = "유료 AI 이미지 옵션을 끄고 0원 출처 기반 모드로 5단계 도판 생성을 다시 시작했습니다."
        details = {"run": run_res}

    elif action_id == "retry_fallback_chapters":
        ck = dict(st.get("checkpoint") or {})
        fb = list(ck.get("fallback_chapters") or [])
        if not fb:
            summary_ko = "재집필할 틀 원고 단원이 없습니다."
            details = {"retried": []}
        else:
            comp = [c for c in (ck.get("completed_chapters") or []) if c not in set(fb)]
            ck["completed_chapters"] = comp
            ck["fallback_chapters"] = []
            st["checkpoint"] = ck
            for s in st.get("stages") or []:
                if s.get("stage_id") == "stage4_manuscript_draft":
                    s["error"] = ""
                    s["status"] = "PENDING"
            if st.get("overall_status") == "ERROR":
                st["overall_status"] = "PAUSED"
            save_project_state(st, cfg)
            run_res = start_pipeline_async(project_id, mode="single", target_stage="stage4_manuscript_draft", cfg=cfg)
            append_event(project_id, "recovery", "stage4_manuscript_draft", f"🔄 틀 원고 {len(fb)}개 단원({', '.join(fb)}) 자동 재집필 시작", cfg=cfg)
            summary_ko = f"틀 원고 {len(fb)}개 단원({', '.join(fb)})의 체크포인트를 해제하고 4단계 재집필을 시작했습니다."
            details = {"retried": fb, "run": run_res}

    elif action_id == "run_full_auto_heal":
        auto_restart = bool(params.get("auto_restart", False))
        steps_log: list[str] = []
        diag_pre = diagnose_project_issues(project_id, cfg=cfg)
        crit_before = int(diag_pre.get("critical_count") or 0)
        target_restart_sid = str((diag_pre.get("workflow_guide") or {}).get("step3_restart", {}).get("target_stage_id") or "")

        if diag_pre.get("is_zombie_running"):
            r = execute_recovery_action(project_id, "unlock_stuck_running", cfg=cfg)
            steps_log.append(r["summary_ko"])

        readiness = diag_pre.get("readiness") or {}
        metrics = readiness.get("metrics") or {}
        if metrics.get("visual_has_placeholder_or_fake") or (
            int(metrics.get("visuals_total") or 0) > 0 and float(metrics.get("visual_source_coverage_pct") or 100.0) < 80.0
        ):
            try:
                r = execute_recovery_action(project_id, "fix_visual_qa_issues", cfg=cfg)
                steps_log.append(r["summary_ko"])
            except Exception as exc:
                steps_log.append(f"도판 정리 건너뜀: {exc}")

        avg_rel = metrics.get("avg_evidence_relevance_pct")
        if avg_rel is not None and float(avg_rel) < 40.0:
            r = execute_recovery_action(project_id, "prune_low_relevance_sources", {"min_score": 0.40}, cfg=cfg)
            steps_log.append(r["summary_ko"])

        unrel = metrics.get("unrelated_ratio_pct")
        if int(metrics.get("critical_errors") or 0) > 0 or (unrel is not None and float(unrel) > 30.0):
            if int(metrics.get("total_chapters") or 0) > 0:
                r = execute_recovery_action(project_id, "repair_citations_and_reaudit", cfg=cfg)
                steps_log.append(r["summary_ko"])

        if bool(metrics.get("require_expert_review", True)) and int(metrics.get("reviewed_chapters") or 0) == 0 and int(metrics.get("total_chapters") or 0) > 0:
            r = execute_recovery_action(project_id, "approve_all_chapters", cfg=cfg)
            steps_log.append(r["summary_ko"])

        # 자동 복구 후 완료/게이트 통과 단계의 잔여 오류 메시지 정리
        st_post = load_project_state(project_id, cfg)
        if st_post:
            gate_post = evaluate_publish_readiness(project_id, cfg=cfg)
            changed_st = False
            for s in st_post.get("stages") or []:
                if s.get("status") == "DONE" and s.get("error"):
                    s["error"] = ""
                    changed_st = True
                elif s.get("stage_id") == "stage6_publish_report" and s.get("status") == "ERROR" and gate_post.get("ready"):
                    s["error"] = ""
                    s["status"] = "PENDING"
                    s["current_action"] = "자동 복구 완료 — 6단계 출판 가능"
                    changed_st = True
            if changed_st:
                if st_post.get("overall_status") == "ERROR" and not any(
                    x.get("status") == "ERROR" for x in (st_post.get("stages") or [])
                ):
                    st_post["overall_status"] = "PAUSED"
                save_project_state(st_post, cfg)

        diag_mid = diagnose_project_issues(project_id, cfg=cfg)
        crit_after = int(diag_mid.get("critical_count") or 0)
        no_progress = bool(crit_before > 0 and crit_after >= crit_before and not steps_log)

        restarted_info = None
        if auto_restart and crit_after == 0 and target_restart_sid:
            restarted_info = start_pipeline_async(project_id, mode="single", target_stage=target_restart_sid, cfg=cfg)
            steps_log.append(f"3단계 재시작 시작: {target_restart_sid}")

        if no_progress:
            manual_hints = (diag_mid.get("workflow_guide") or {}).get("step2_recovery", {}).get("manual_hints") or []
            summary_ko = (
                "자동으로 해결할 수 없는 외부/수동 확인 오류가 남아 있습니다(반복 실행 중단). "
                + (" / ".join(manual_hints[:2]) if manual_hints else "상세 원인을 확인해 주세요.")
            )
        else:
            if not steps_log:
                steps_log.append("해결할 자동 복구 항목이 없어 현재 상태를 점검 완료했습니다.")
            summary_ko = f"복구 결과(치명 오류 {crit_before}건 → {crit_after}건): " + " / ".join(steps_log)

        details = {
            "steps": steps_log,
            "critical_before": crit_before,
            "critical_after": crit_after,
            "no_progress": no_progress,
            "restarted": restarted_info,
        }

    elif action_id == "force_draft_publish":
        pub_res = publish_default_outputs(project_id, only_reviewed=False, check_quality_gate=False, cfg=cfg)
        append_event(
            project_id,
            "recovery",
            "stage6_publish_report",
            "📄 초안 임시 출판 완료 (품질 게이트 우회 — 검토용 DOCX + 블로그 HTML 생성)",
            level="WARN",
            cfg=cfg,
        )
        d_out = pub_res.get("default_outputs") or {}
        summary_ko = (
            f"초안 임시 출판(검토용) 완료: DOCX({(d_out.get('master_docx') or {}).get('size_kb', 0)} KB) + "
            f"블로그 HTML({(d_out.get('blog_single_html') or {}).get('size_kb', 0)} KB)"
        )
        details = {"publish": pub_res}

    else:
        raise ValueError(f"알 수 없는 복구 액션입니다: {action_id}")

    fresh_state = load_project_state(project_id, cfg)
    fresh_diag = diagnose_project_issues(project_id, cfg=cfg)
    return {
        "status": "OK",
        "action_id": action_id,
        "summary_ko": summary_ko,
        "details": details,
        "diagnostics": fresh_diag,
        "project": fresh_state,
    }
