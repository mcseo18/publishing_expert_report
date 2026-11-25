/* ==========================================================================
   SMC 출판 스튜디오 v2 — 반응형 프론트엔드 애플리케이션 컨트롤러
   Backend: FastAPI (/api/* + /api/v2/*) · Storage: projects_v2 & publishing_DB
   ========================================================================== */
(function () {
  const ROUTE_META = {
    home: { title: "홈 · 새 프로젝트", subtitle: "projects_v2와 publishing_DB 기반으로 새 출판 프로젝트를 시작합니다." },
    stage1: { title: "1. 기획 · 목차 설계", subtitle: "AI 청사진 목차를 검토·수정하고 확정합니다." },
    stage2: { title: "2. 리서치 · eco-browser 스튜디오", subtitle: "eco-browser 웹 크롤링·캡처·PDF 수집 및 NotebookLM 스타일 근거 질의" },
    stage3: { title: "3. 지식그래프 · publishing_DB", subtitle: "인터랙티브 지식그래프 탐색과 캡처·PDF·참고이미지 통합 DB 관리" },
    stage4: { title: "4. 원고 집필 · 검수", subtitle: "단원별 심층 집필 파이프라인, 인용 감사 및 원고 편집" },
    stage5: { title: "5. 시각화 · 도판 스튜디오", subtitle: "프롬프트 팩, Scientific-Figure-Design Draw.io(0원), 유료 AI 재생성·직접 대체" },
    stage6: { title: "6. 최종 출판 · 변환", subtitle: "마스터 DOCX · 블로그 단일 HTML 기본 2종 출판 및 사후 포맷 변환" },
    system: { title: "시스템 · 진단/복구", subtitle: "3단계 오류 진단·자동 복구, API 키 관리 및 로컬 엔진 상태" },
  };

  const STAGE_MAP = {
    stage1: "stage1_planning",
    stage2: "stage2_source_collect",
    stage3: "stage3_kg_build",
    stage4: "stage4_manuscript_draft",
    stage5: "stage5_visuals",
    stage6: "stage6_publish",
  };

  const state = {
    route: "home",
    bootstrap: null,
    projects: [],
    activeProjectId: "",
    project: null,
    events: [],
    // View-specific caches
    publishingDb: null,
    kgData: null,
    kgInstance: null,
    ecoCrawl: null,
    selectedSources: new Set(),
    notebookChat: [],
    notebookBrief: null,
    dbActiveTab: "captures",
    chapters: [],
    selectedChapterId: "",
    chapterContent: "",
    chapterPipeline: null,
    visualsData: null,
    promptPack: null,
    visualsQa: null,
    outputsSummary: null,
    outputFormats: [],
    diagnostics: null,
    selectedOutputType: "textbook",
    pollTimer: null,
  };

  // ---------- Utilities ----------
  const $ = (id) => document.getElementById(id);

  function esc(val) {
    return String(val ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtBytes(n) {
    const b = Number(n || 0);
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / (1024 * 1024)).toFixed(2)} MB`;
  }

  function toast(msg, kind = "info") {
    const stack = $("toastStack");
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  async function api(url, opts = {}) {
    const init = {
      method: opts.method || "GET",
      headers: opts.headers ? { ...opts.headers } : {},
    };
    if (opts.body !== undefined) {
      if (opts.body instanceof FormData) {
        init.body = opts.body;
      } else {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
      }
    }
    const res = await fetch(url, init);
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok) {
      const detail = data?.detail || data?.message || `HTTP ${res.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function getStageObj(routeKey) {
    const sid = STAGE_MAP[routeKey];
    if (!state.project || !sid) return null;
    return (state.project.stages || []).find((s) => s.stage_id === sid) || null;
  }

  function statusBadgeLabel(st) {
    const map = {
      DONE: ["완료", "done"],
      RUNNING: ["실행중", "running"],
      AWAITING_APPROVAL: ["승인대기", "awaiting"],
      FAILED: ["오류", "error"],
      INTERRUPTED: ["중단됨", "warn"],
      STOPPED: ["중지됨", "warn"],
      PENDING: ["대기", ""],
    };
    return map[String(st || "PENDING").toUpperCase()] || ["대기", ""];
  }

  // ---------- Lightbox ----------
  function openLightbox({ title, meta, url, isPdf = false }) {
    $("lightboxTitle").textContent = title || "미리보기";
    $("lightboxMeta").textContent = meta || "";
    $("lightboxDownload").href = url;
    const body = $("lightboxBody");
    if (isPdf) {
      body.innerHTML = `<iframe src="${esc(url)}" style="width:100%;height:74vh;border:none;border-radius:8px;background:#fff;"></iframe>`;
    } else {
      body.innerHTML = `<img src="${esc(url)}" alt="${esc(title || "preview")}" />`;
    }
    $("lightboxModal").classList.remove("hidden");
  }

  function closeLightbox() {
    $("lightboxModal").classList.add("hidden");
    $("lightboxBody").innerHTML = "";
  }

  // ---------- Bootstrap & State Sync ----------
  async function loadBootstrap(preserveSelection = true) {
    const data = await api("/api/v2/bootstrap");
    state.bootstrap = data;
    state.projects = data.projects || [];
    updateEngineBadges(data.engines || {}, data.workspace_info || {});
    renderProjectSelect();

    if (preserveSelection && state.activeProjectId && state.projects.some((p) => p.project_id === state.activeProjectId)) {
      await loadActiveProject(state.activeProjectId, false);
    } else if (!state.activeProjectId && state.projects.length > 0) {
      const saved = localStorage.getItem("smc_v2_active_project");
      const pick = state.projects.find((p) => p.project_id === saved) || state.projects[0];
      await loadActiveProject(pick.project_id, false);
    } else if (!state.projects.length) {
      state.activeProjectId = "";
      state.project = null;
      updateSidebarPills();
      updateTopbarStepper();
    }
  }

  async function loadActiveProject(projectId, rerender = true) {
    if (!projectId) {
      state.activeProjectId = "";
      state.project = null;
      updateSidebarPills();
      updateTopbarStepper();
      if (rerender) await renderCurrentRoute();
      return;
    }
    const res = await api(`/api/projects/${encodeURIComponent(projectId)}?limit_events=60`);
    state.activeProjectId = projectId;
    state.project = res.project;
    state.events = res.events || [];
    localStorage.setItem("smc_v2_active_project", projectId);

    const sel = $("projectSelect");
    if (sel) sel.value = projectId;

    const meta = $("sidebarProjectMeta");
    if (meta && state.project) {
      const srcCnt = (state.project.collected_sources || []).length;
      meta.innerHTML = `<span>${esc(state.project.primary_output_type || "textbook")} · 자료 ${srcCnt}건 · publishing_DB 연동</span>`;
    }

    updateSidebarPills();
    updateTopbarStepper();
    updateLiveBanner();
    syncPolling();
    if (rerender) await renderCurrentRoute();
  }

  function renderProjectSelect() {
    const sel = $("projectSelect");
    if (!sel) return;
    if (!state.projects.length) {
      sel.innerHTML = `<option value="">(projects_v2 비어 있음 — 새 프로젝트 생성)</option>`;
      return;
    }
    sel.innerHTML = state.projects
      .map((p) => {
        const label = `${p.topic_ko || p.project_id} (${p.done_stages || 0}/6)`;
        const selected = p.project_id === state.activeProjectId ? "selected" : "";
        return `<option value="${esc(p.project_id)}" ${selected}>${esc(label)}</option>`;
      })
      .join("");
  }

  function updateEngineBadges(engines, wsInfo) {
    const gChip = $("chipGraphRag");
    const oChip = $("chipOllama");
    if (gChip) {
      const ok = Boolean(wsInfo.smc_graphrag_exists);
      gChip.className = `status-dot-chip ${ok ? "ok" : "warn"}`;
      gChip.textContent = ok ? "● GraphRAG 연결" : "● GraphRAG 대기";
    }
    if (oChip) {
      const ok = Boolean(engines?.ollama?.online || engines?.ollama?.available || engines?.ollama_available);
      oChip.className = `status-dot-chip ${ok ? "ok" : "warn"}`;
      oChip.textContent = ok ? "● Ollama 활성" : "● Ollama 오프라인";
    }
  }

  function updateSidebarPills() {
    ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"].forEach((rk) => {
      const pill = $(`pill-${rk}`);
      if (!pill) return;
      const sObj = getStageObj(rk);
      const [label, cls] = statusBadgeLabel(sObj?.status);
      pill.textContent = label;
      pill.className = `nav-pill ${cls}`;
    });
  }

  function updateTopbarStepper() {
    const el = $("topbarStepper");
    if (!el) return;
    el.innerHTML = ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"]
      .map((rk, i) => {
        const sObj = getStageObj(rk);
        const [lbl, cls] = statusBadgeLabel(sObj?.status);
        return `<button type="button" class="step-dot ${cls}" data-route="${rk}" title="${i + 1}단계: ${lbl}">${i + 1}</button>`;
      })
      .join("");
    el.querySelectorAll(".step-dot").forEach((btn) => {
      btn.addEventListener("click", () => navigate(btn.dataset.route));
    });
  }

  function updateLiveBanner() {
    const banner = $("liveBanner");
    if (!banner) return;
    const runningStage = (state.project?.stages || []).find((s) => s.status === "RUNNING");
    const ecoRunning = state.ecoCrawl?.status === "RUNNING";
    const cpRunning = state.chapterPipeline?.status === "RUNNING";

    if (runningStage) {
      banner.classList.remove("hidden");
      $("liveBannerTitle").textContent = `${runningStage.title || runningStage.stage_id} 실행 중`;
      $("liveBannerDetail").textContent = runningStage.current_action || "작업을 진행하고 있습니다...";
      $("liveBannerBar").style.width = `${Math.max(8, Number(runningStage.progress || 10))}%`;
      $("btnStopRunning").classList.remove("hidden");
    } else if (ecoRunning) {
      banner.classList.remove("hidden");
      $("liveBannerTitle").textContent = `eco-browser 웹 수집·캡처 실행 중 (${state.ecoCrawl.completed}/${state.ecoCrawl.total_urls})`;
      $("liveBannerDetail").textContent = state.ecoCrawl.current_action || "웹페이지를 렌더링하고 캡처하는 중...";
      const pct = state.ecoCrawl.total_urls ? Math.round((state.ecoCrawl.completed / state.ecoCrawl.total_urls) * 100) : 20;
      $("liveBannerBar").style.width = `${Math.max(12, pct)}%`;
      $("btnStopRunning").classList.add("hidden");
    } else if (cpRunning) {
      banner.classList.remove("hidden");
      $("liveBannerTitle").textContent = "단원별 심층 집필 파이프라인 실행 중";
      $("liveBannerDetail").textContent = state.chapterPipeline.current_action || "단원을 순차 집필 중입니다...";
      $("liveBannerBar").style.width = `${Math.max(10, Number(state.chapterPipeline.progress || 20))}%`;
      $("btnStopRunning").classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  }

  function syncPolling() {
    const isBusy =
      (state.project?.stages || []).some((s) => s.status === "RUNNING") ||
      state.ecoCrawl?.status === "RUNNING" ||
      state.chapterPipeline?.status === "RUNNING";

    if (isBusy && !state.pollTimer) {
      state.pollTimer = setInterval(async () => {
        if (!state.activeProjectId) return;
        try {
          await loadActiveProject(state.activeProjectId, false);
          if (state.route === "stage2") {
            state.ecoCrawl = await api(`/api/v2/projects/${encodeURIComponent(state.activeProjectId)}/eco-crawl/status`);
            updateLiveBanner();
            if (state.ecoCrawl?.status !== "RUNNING") await renderStage2();
          } else if (state.route === "stage4") {
            await renderStage4();
          } else {
            await renderCurrentRoute();
          }
        } catch (_) {}
      }, 3500);
    } else if (!isBusy && state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // ---------- Routing ----------
  function navigate(route) {
    if (!ROUTE_META[route]) route = "home";
    state.route = route;
    window.location.hash = route;
    $("appShell").classList.remove("sidebar-open");

    document.querySelectorAll(".nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.route === route);
    });
    const meta = ROUTE_META[route];
    $("topbarTitle").textContent = meta.title;
    $("topbarSubtitle").textContent = state.project && route !== "home"
      ? `${state.project.topic_ko} · ${meta.subtitle}`
      : meta.subtitle;

    renderCurrentRoute();
  }

  function requireProjectGuard(stageLabel) {
    if (state.project) return false;
    $("appView").innerHTML = `
      <div class="empty-state">
        <div style="font-size:34px;">📚</div>
        <h3>먼저 새 프로젝트를 만들어 주세요</h3>
        <p>${esc(stageLabel)} 기능은 프로젝트 폴더(<code>projects_v2/</code>)와 연동 DB(<code>publishing_DB/</code>)가 생성된 후 바로 사용할 수 있습니다.</p>
        <button type="button" class="btn btn-primary" id="btnGoHomeNew">＋ 새 프로젝트 만들기</button>
      </div>
    `;
    $("btnGoHomeNew").addEventListener("click", () => navigate("home"));
    return true;
  }

  async function renderCurrentRoute() {
    const view = $("appView");
    try {
      switch (state.route) {
        case "home": return renderHome();
        case "stage1": return await renderStage1();
        case "stage2": return await renderStage2();
        case "stage3": return await renderStage3();
        case "stage4": return await renderStage4();
        case "stage5": return await renderStage5();
        case "stage6": return await renderStage6();
        case "system": return await renderSystem();
        default: return renderHome();
      }
    } catch (err) {
      view.innerHTML = `<div class="card"><h3>화면을 불러오는 중 오류가 발생했습니다</h3><p class="muted">${esc(err.message)}</p></div>`;
    }
  }

  // ========================================================================
  // VIEW 0: 홈 · 새 프로젝트
  // ========================================================================
  function renderHome() {
    const ws = state.bootstrap?.workspace_info || {};
    const rawTypes = state.bootstrap?.output_types || {};
    const types = Array.isArray(rawTypes) ? rawTypes : Object.values(rawTypes);
    const personas = Array.isArray(state.bootstrap?.personas) ? state.bootstrap.personas : Object.values(state.bootstrap?.personas || {});

    const existingListHtml = state.projects.length
      ? `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">진행 중인 v2 프로젝트 (${state.projects.length})</h3>
            <p class="card-desc"><code>projects_v2/</code>에 생성된 프로젝트와 <code>publishing_DB/</code> 저장소가 자동으로 쌍을 이룹니다.</p>
          </div>
        </div>
        <div class="grid-3">
          ${state.projects.map((p) => `
            <div class="stat-card" style="display:flex;flex-direction:column;gap:8px;">
              <div class="row-between">
                <span class="badge badge-primary">${esc(p.primary_output_type || "textbook")}</span>
                <span class="muted-sm">${p.done_stages || 0}/6 단계</span>
              </div>
              <strong style="font-size:15px;">${esc(p.topic_ko || p.project_id)}</strong>
              <span class="muted-sm">${esc(p.project_id)}</span>
              <div class="row-wrap" style="margin-top:auto;padding-top:6px;">
                <button type="button" class="btn btn-primary btn-sm" data-open-proj="${esc(p.project_id)}">작업 열기</button>
                <button type="button" class="btn btn-secondary btn-sm" data-open-db="${esc(p.project_id)}">DB·그래프</button>
                <button type="button" class="btn btn-danger-soft btn-xs" data-del-proj="${esc(p.project_id)}">삭제</button>
              </div>
            </div>
          `).join("")}
        </div>
      </div>`
      : "";

    $("appView").innerHTML = `
      <div class="hero-card">
        <span class="hero-eyebrow">✨ Clean Start · projects_v2 &amp; publishing_DB</span>
        <h2>리서치부터 지식그래프·집필·시각화·출판까지, 한 단계씩 직관적으로</h2>
        <p>좌측 사이드바에서 1~6단계를 순서대로 이동하며 작업하세요. 새 프로젝트를 만들면 <code>projects_v2/&lt;프로젝트ID&gt;</code>와 동일한 이름의 <code>publishing_DB/&lt;프로젝트ID&gt;</code> 폴더가 자동 생성되어 웹 캡처, PDF, 참고이미지, 지식그래프를 한곳에 축적합니다.</p>
      </div>

      <div class="grid-4" style="margin-bottom:20px;">
        <div class="stat-card">
          <div class="stat-label">프로젝트 저장소</div>
          <div class="stat-value" style="font-size:18px;">projects_v2/</div>
          <div class="stat-sub">기존 projects/ 원본 보존</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">통합 리서치 DB</div>
          <div class="stat-value" style="font-size:18px;">publishing_DB/</div>
          <div class="stat-sub">캡처·PDF·이미지·KG 미러</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">로컬 지식그래프</div>
          <div class="stat-value" style="font-size:18px;">${ws.smc_graphrag_exists ? "연결됨" : "대기"}</div>
          <div class="stat-sub">C:\\SMC_GRAPHRAG 기본 ON</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">eco-browser 리서치</div>
          <div class="stat-value" style="font-size:18px;">NotebookLM급</div>
          <div class="stat-sub">크롤링·캡처·근거 Q&amp;A</div>
        </div>
      </div>

      ${existingListHtml}

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">새 출판 프로젝트 시작하기</h3>
            <p class="card-desc">주제와 출판 유형을 선택하면 1단계 목차 기획과 <code>publishing_DB</code> 초기화가 자동으로 진행됩니다.</p>
          </div>
        </div>

        <form id="newProjectForm" class="stack-md">
          <div>
            <label class="field-label">1. 출판 유형 선택</label>
            <div class="type-grid" id="outputTypeGrid">
              ${types.map((t) => `
                <button type="button" class="type-option ${t.id === state.selectedOutputType ? "selected" : ""}" data-type-id="${esc(t.id)}">
                  <strong>${esc((t.icon ? t.icon + " " : "") + (t.name_ko || t.label_ko || t.label || t.id))}</strong>
                  <span>${esc((t.subtitle_ko || t.description_ko || t.description || t.summary || "").slice(0, 80))}</span>
                </button>
              `).join("")}
            </div>
          </div>

          <div class="form-grid">
            <div class="form-field full">
              <label for="npTopicKo">한국어 주제 / 도서·논문 제목 *</label>
              <input id="npTopicKo" class="text-input" required placeholder="예: 메밀의 과학적 재배 기술과 기후적응형 생산 매뉴얼" />
            </div>
            <div class="form-field">
              <label for="npTopicEn">영문 주제 (국제 SCI/OA 검색 정확도 향상)</label>
              <input id="npTopicEn" class="text-input" placeholder="예: Scientific Cultivation Technology of Buckwheat" />
            </div>
            <div class="form-field">
              <label for="npAudience">대상 독자</label>
              <input id="npAudience" class="text-input" value="대학 전공 심화, 대학원생, 연구자 및 선도 현장 실무자" />
            </div>
            <div class="form-field">
              <label for="npKeywordsKo">핵심 키워드 (한국어, 쉼표 구분)</label>
              <input id="npKeywordsKo" class="text-input" placeholder="예: 메밀, 파종시기, 루틴, 습해방지, 수확후관리" />
            </div>
            <div class="form-field">
              <label for="npKeywordsEn">핵심 키워드 (영문, 쉼표 구분)</label>
              <input id="npKeywordsEn" class="text-input" placeholder="예: Fagopyrum esculentum, sowing date, rutin, agronomy" />
            </div>
            <div class="form-field">
              <label for="npChapters">목표 단원 수</label>
              <input id="npChapters" type="number" min="3" max="24" value="10" class="text-input" />
            </div>
            <div class="form-field">
              <label for="npPages">목표 분량 (페이지)</label>
              <input id="npPages" type="number" min="20" max="1200" value="280" class="text-input" />
            </div>
            <div class="form-field">
              <label for="npVisualMode">도판·시각화 제작 방식</label>
              <select id="npVisualMode" class="select-input">
                <option value="hybrid_with_prompt_pack">0원 학술 그래프/Draw.io + 한·영 프롬프트 팩 (권장)</option>
                <option value="prompt_pack_only">한·영 이미지 프롬프트 팩 전용 (비용 0원)</option>
                <option value="hybrid_cited">OA 그림·표 재작도 + 필요 시 선택 유료 보강</option>
              </select>
            </div>
            <div class="form-field">
              <label for="npPersona">저자 페르소나</label>
              <select id="npPersona" class="select-input">
                <option value="">출판 유형 기본 페르소나 자동 적용</option>
                ${personas.map((ps) => `<option value="${esc(ps.id || ps.persona_id)}">${esc(ps.name_ko || ps.name || ps.id)}</option>`).join("")}
              </select>
            </div>
          </div>

          <div class="row-wrap" style="padding-top:4px;">
            <label class="checkbox-row"><input type="checkbox" id="npUseGraphRag" checked /> C:\\SMC_GRAPHRAG 로컬 지식그래프 기본 연동 (ON)</label>
            <label class="checkbox-row"><input type="checkbox" id="npAutoStart" checked /> 생성 즉시 1단계 목차 기획 시작</label>
          </div>

          <div class="row-between" style="padding-top:8px;border-top:1px solid var(--border);">
            <span class="muted-sm">생성 위치: <code>projects_v2/&lt;id&gt;</code> &amp; <code>publishing_DB/&lt;id&gt;</code></span>
            <button type="submit" class="btn btn-primary" id="btnCreateProject">🚀 새 프로젝트 생성 및 시작</button>
          </div>
        </form>
      </div>
    `;

    $("outputTypeGrid").querySelectorAll(".type-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.selectedOutputType = btn.dataset.typeId;
        $("outputTypeGrid").querySelectorAll(".type-option").forEach((b) => b.classList.toggle("selected", b === btn));
        if (state.selectedOutputType === "paper") {
          $("npChapters").value = "5";
          $("npPages").value = "40";
        } else if (state.selectedOutputType === "report") {
          $("npChapters").value = "8";
          $("npPages").value = "120";
        } else {
          $("npChapters").value = "10";
          $("npPages").value = "280";
        }
      });
    });

    document.querySelectorAll("[data-open-proj]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await loadActiveProject(btn.dataset.openProj, false);
        navigate("stage1");
      });
    });
    document.querySelectorAll("[data-open-db]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await loadActiveProject(btn.dataset.openDb, false);
        navigate("stage3");
      });
    });
    document.querySelectorAll("[data-del-proj]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.delProj;
        if (!confirm(`프로젝트 '${pid}'를 목록에서 삭제(아카이브)할까요?`)) return;
        await api(`/api/projects/${encodeURIComponent(pid)}`, { method: "DELETE" });
        toast("프로젝트를 정리했습니다.", "success");
        if (state.activeProjectId === pid) state.activeProjectId = "";
        await loadBootstrap(false);
        renderHome();
      });
    });

    $("newProjectForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const topicKo = $("npTopicKo").value.trim();
      if (!topicKo) return toast("한국어 주제를 입력해 주세요.", "warn");
      const btn = $("btnCreateProject");
      btn.disabled = true;
      btn.textContent = "프로젝트 생성 중...";
      try {
        const kwKo = $("npKeywordsKo").value.split(",").map((s) => s.trim()).filter(Boolean);
        const kwEn = $("npKeywordsEn").value.split(",").map((s) => s.trim()).filter(Boolean);
        const personaId = $("npPersona").value;
        const body = {
          topic_ko: topicKo,
          topic_en: $("npTopicEn").value.trim(),
          primary_output_type: state.selectedOutputType,
          target_audience: $("npAudience").value.trim(),
          keywords_ko: kwKo,
          keywords_en: kwEn,
          chapter_count: Number($("npChapters").value || 10),
          target_pages: Number($("npPages").value || 280),
          visual_generation_mode: $("npVisualMode").value,
          generate_visual_prompt_pack: $("npVisualMode").value !== "hybrid_cited",
          use_smc_graphrag: $("npUseGraphRag").checked,
          auto_start: $("npAutoStart").checked,
        };
        if (personaId) body.persona = { persona_id: personaId };
        const res = await api("/api/projects", { method: "POST", body });
        const pid = res.project?.project_id;
        toast(`새 프로젝트 생성 완료 (projects_v2 & publishing_DB/${pid})`, "success");
        await loadBootstrap(false);
        if (pid) await loadActiveProject(pid, false);
        navigate("stage1");
      } catch (err) {
        toast(`생성 오류: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 새 프로젝트 생성 및 시작";
      }
    });
  }

  // ========================================================================
  // VIEW 1: 1. 기획 · 목차 설계
  // ========================================================================
  async function renderStage1() {
    if (requireProjectGuard("1단계 기획·목차")) return;
    const p = state.project;
    const st1 = getStageObj("stage1") || {};
    const outline = p.outline || {};
    const parts = outline.parts || [];
    const totalCh = parts.reduce((acc, pt) => acc + (pt.chapters || []).length, 0);

    $("appView").innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">목차 청사진 (1단계)</h3>
            <p class="card-desc">상태: <strong>${esc(st1.status || "PENDING")}</strong> · 총 ${parts.length}부 / ${totalCh}개 단원 · 목표 ${p.target_pages || 0}쪽</p>
          </div>
          <div class="row-wrap">
            <button type="button" class="btn btn-secondary btn-sm" id="btnRunStage1">▶ 1단계(목차 생성) 실행</button>
            <button type="button" class="btn btn-primary btn-sm" id="btnApproveStage1">✅ 목차 확정 → 2단계 리서치로</button>
          </div>
        </div>

        <div class="form-field" style="margin-bottom:16px;">
          <label for="stage1Feedback">AI에게 목차 수정 요청 (예: "스마트팜 환경제어 단원을 추가하고 8단원으로 압축해줘")</label>
          <div class="row-wrap" style="align-items:stretch;">
            <input id="stage1Feedback" class="text-input" style="flex:1;min-width:240px;" placeholder="수정 지시사항을 입력하세요..." />
            <button type="button" class="btn btn-accent" id="btnReviseStage1">✨ AI 목차 재설계</button>
          </div>
        </div>

        ${parts.length ? `
          <div class="stack-sm">
            ${parts.map((pt, pIdx) => `
              <div style="border:1px solid var(--border);border-radius:12px;padding:14px 16px;background:var(--bg-subtle);">
                <div class="row-between" style="margin-bottom:8px;">
                  <strong>Part ${pIdx + 1}. ${esc(pt.title_ko || pt.part_title || "")}</strong>
                  <span class="badge">${(pt.chapters || []).length}개 단원</span>
                </div>
                <div class="stack-sm">
                  ${(pt.chapters || []).map((ch) => `
                    <div style="background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:10px 12px;">
                      <div class="row-between">
                        <strong>${esc(ch.id || "")} · ${esc(ch.title_ko || ch.title || "")}</strong>
                        <span class="muted-sm">${ch.target_pages ? `${ch.target_pages}쪽` : ""}</span>
                      </div>
                      ${(ch.sections || []).length ? `<p class="muted-sm" style="margin-top:4px;">세부 절: ${esc((ch.sections || []).map((s) => (typeof s === "string" ? s : s.title_ko || s.title || "")).join(" · "))}</p>` : ""}
                    </div>
                  `).join("")}
                </div>
              </div>
            `).join("")}
          </div>
        ` : `
          <div class="empty-state">
            <h3>아직 목차 청사진이 생성되지 않았습니다</h3>
            <p>[1단계(목차 생성) 실행] 버튼을 누르면 주제와 <code>C:\\SMC_GRAPHRAG</code> 기존 지식을 바탕으로 구조화된 목차를 생성합니다.</p>
          </div>
        `}
      </div>
    `;

    $("btnRunStage1").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(p.project_id)}/run`, { method: "POST", body: { mode: "single", stage_id: "stage1_planning" } });
      toast("1단계 목차 기획을 시작했습니다.", "success");
      await loadActiveProject(p.project_id, true);
    });

    $("btnReviseStage1").addEventListener("click", async () => {
      const fb = $("stage1Feedback").value.trim();
      if (!fb) return toast("수정 요청 내용을 입력해 주세요.", "warn");
      const btn = $("btnReviseStage1");
      btn.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(p.project_id)}/stage1/revise`, { method: "POST", body: { feedback_prompt: fb } });
        toast("AI 목차 재설계가 반영되었습니다.", "success");
        await loadActiveProject(p.project_id, true);
      } catch (err) {
        toast(`재설계 오류: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
      }
    });

    $("btnApproveStage1").addEventListener("click", async () => {
      try {
        await api(`/api/projects/${encodeURIComponent(p.project_id)}/stage1/approve`, {
          method: "POST",
          body: { auto_continue: false },
        });
        toast("1단계 목차가 확정되었습니다. 2단계 리서치 스튜디오로 이동합니다.", "success");
        await loadActiveProject(p.project_id, false);
        navigate("stage2");
      } catch (err) {
        toast(`확정 오류: ${err.message}`, "error");
      }
    });
  }

  // ========================================================================
  // VIEW 2: 2. 리서치 · eco-browser & NotebookLM 스튜디오
  // ========================================================================
  async function renderStage2() {
    if (requireProjectGuard("2단계 리서치 · eco-browser 스튜디오")) return;
    const p = state.project;
    const pid = p.project_id;
    const [ecoStatus, dbRes] = await Promise.all([
      api(`/api/v2/projects/${encodeURIComponent(pid)}/eco-crawl/status`).catch(() => ({ status: "IDLE" })),
      api(`/api/v2/projects/${encodeURIComponent(pid)}/publishing-db`).catch(() => ({ counts: {} })),
    ]);
    state.ecoCrawl = ecoStatus;
    state.publishingDb = dbRes;
    updateLiveBanner();
    syncPolling();

    const sources = p.collected_sources || [];
    if (!state.selectedSources.size && sources.length) {
      sources.forEach((s) => s.source_id && state.selectedSources.add(s.source_id));
    }

    const dbCounts = dbRes.counts || {};
    $("appView").innerHTML = `
      <div class="grid-4" style="margin-bottom:18px;">
        <div class="stat-card"><div class="stat-label">등록 출처 ([SRC-NN])</div><div class="stat-value">${sources.length}건</div></div>
        <div class="stat-card"><div class="stat-label">웹 캡처 (captures/)</div><div class="stat-value">${dbCounts.captures || 0}장</div></div>
        <div class="stat-card"><div class="stat-label">수집 PDF (pdfs/)</div><div class="stat-value">${dbCounts.pdfs || 0}편</div></div>
        <div class="stat-card"><div class="stat-label">참고 이미지 (reference_images/)</div><div class="stat-value">${dbCounts.reference_images || 0}장</div></div>
      </div>

      <div class="notebook-layout">
        <!-- 좌측: eco-browser 크롤러 + 출처 패널 -->
        <div class="stack-md">
          <div class="card">
            <div class="card-header">
              <div>
                <h3 class="card-title">🌐 eco-browser 웹 크롤링 · 캡처</h3>
                <p class="card-desc">검색어 또는 URL로 웹페이지를 렌더링하고 풀페이지 캡처·참고이미지·PDF를 <code>publishing_DB/${esc(pid)}</code>에 자동 저장합니다.</p>
              </div>
            </div>
            <div class="stack-sm">
              <div class="form-field">
                <label for="ecoQuery">검색어 (자동 URL 탐색 + 크롤링)</label>
                <input id="ecoQuery" class="text-input" placeholder="예: 메밀 재배 기술 농촌진흥청" value="${esc(p.topic_ko || "")}" />
              </div>
              <div class="form-field">
                <label for="ecoUrls">직접 크롤링할 URL (선택, 줄바꿈으로 여러 개)</label>
                <textarea id="ecoUrls" class="textarea-input" style="min-height:66px;" placeholder="https://www.nongsaro.go.kr/..."></textarea>
              </div>
              <div class="row-wrap">
                <label class="checkbox-row"><input type="checkbox" id="ecoCap" checked /> 전체화면 캡처</label>
                <label class="checkbox-row"><input type="checkbox" id="ecoImg" checked /> 참고이미지 추출</label>
                <label class="checkbox-row"><input type="checkbox" id="ecoPdf" checked /> PDF 자동저장</label>
              </div>
              <div class="row-between" style="padding-top:4px;">
                <div class="row-wrap">
                  <label class="muted-sm">최대 페이지</label>
                  <select id="ecoMaxPages" class="select-input" style="width:74px;padding:5px 8px;">
                    <option value="2">2</option>
                    <option value="4" selected>4</option>
                    <option value="6">6</option>
                    <option value="8">8</option>
                  </select>
                </div>
                <button type="button" class="btn btn-primary" id="btnStartEcoCrawl">🚀 eco-browser 수집 시작</button>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div>
                <h3 class="card-title">📚 소스 라이브러리 (${sources.length}건)</h3>
                <p class="card-desc">체크한 소스를 근거로 우측 NotebookLM 스튜디오가 답변합니다.</p>
              </div>
              <div class="row-wrap">
                <button type="button" class="btn btn-secondary btn-xs" id="btnRunStage2Auto">4계층 자동수집</button>
                <label class="btn btn-secondary btn-xs" style="cursor:pointer;">
                  📎 PDF 앵커 추가
                  <input type="file" id="anchorPdfInput" accept=".pdf,.txt,.md" hidden />
                </label>
              </div>
            </div>

            ${sources.length ? `
              <div class="row-between" style="margin-bottom:8px;">
                <span class="muted-sm">선택됨: ${state.selectedSources.size}/${sources.length}</span>
                <div class="row-wrap">
                  <button type="button" class="btn btn-secondary btn-xs" id="btnSelectAllSrc">전체 선택</button>
                  <button type="button" class="btn btn-secondary btn-xs" id="btnClearAllSrc">선택 해제</button>
                </div>
              </div>
              <div class="source-list" id="sourceList">
                ${sources.map((s) => {
                  const sid = s.source_id || "";
                  const checked = state.selectedSources.has(sid) ? "checked" : "";
                  return `
                    <label class="source-item">
                      <input type="checkbox" data-src-check="${esc(sid)}" ${checked} />
                      <div class="source-item-body">
                        <div class="source-item-title">${esc(s.title || sid)}</div>
                        <div class="source-item-meta">
                          <span class="badge badge-primary">${esc(sid)}</span>
                          ${s.channel ? `<span>${esc(s.channel)}</span>` : ""}
                          ${s.capture_path ? `<span class="badge badge-accent">📸 캡처됨</span>` : ""}
                          ${s.is_anchor ? `<span class="badge badge-warning">★ 앵커</span>` : ""}
                        </div>
                      </div>
                    </label>
                  `;
                }).join("")}
              </div>
            ` : `
              <p class="muted-sm">아직 수집된 자료가 없습니다. 위에서 <strong>eco-browser 수집</strong>을 실행하거나 <strong>4계층 자동수집</strong> / <strong>PDF 앵커 추가</strong>를 눌러주세요.</p>
            `}
          </div>
        </div>

        <!-- 우측: NotebookLM 스타일 근거 Q&A + 원클릭 브리핑 스튜디오 -->
        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">🧠 NotebookLM 리서치 스튜디오</h3>
              <p class="card-desc">선택된 출처 + <code>C:\\SMC_GRAPHRAG</code> 트리플만을 근거로 <code>[SRC-NN]</code> 인용 답변과 브리핑을 생성합니다.</p>
            </div>
            <div class="row-wrap">
              <button type="button" class="btn btn-secondary btn-sm" data-brief-mode="briefing">📄 브리핑 문서</button>
              <button type="button" class="btn btn-secondary btn-sm" data-brief-mode="study_guide">📘 학습 가이드</button>
              <button type="button" class="btn btn-secondary btn-sm" data-brief-mode="faq">❓ FAQ·오해 정리</button>
            </div>
          </div>

          <div class="chat-feed" id="notebookChatFeed">
            ${state.notebookChat.length ? state.notebookChat.map((m) => `
              <div class="chat-bubble ${m.role}">
                <div>${esc(m.text)}</div>
                ${(m.citations || []).length ? `
                  <div class="chat-citations">
                    ${m.citations.map((c) => `<span class="badge badge-primary" title="${esc(c.title || "")}">[${esc(c.source_id)}] ${esc((c.title || "").slice(0, 26))}</span>`).join("")}
                  </div>
                ` : ""}
              </div>
            `).join("") : `
              <div style="text-align:center;padding:42px 16px;color:var(--text-muted);">
                <div style="font-size:28px;margin-bottom:8px;">💬</div>
                <p style="margin:0 0 6px;font-weight:600;color:var(--text);">수집된 자료에 대해 무엇이든 질문해 보세요</p>
                <p style="margin:0;font-size:12.5px;">예: "핵심 재배 적온과 파종 시기의 근거 수치를 [SRC-NN]과 함께 비교표로 요약해 줘"</p>
              </div>
            `}
          </div>

          <form id="notebookAskForm" class="row-wrap" style="margin-top:12px;align-items:stretch;">
            <input id="notebookQuestion" class="text-input" style="flex:1;min-width:220px;" placeholder="선택된 자료와 지식그래프를 바탕으로 질문하세요..." />
            <button type="submit" class="btn btn-primary" id="btnNotebookAsk">질문하기</button>
          </form>
        </div>
      </div>
    `;

    $("btnStartEcoCrawl").addEventListener("click", async () => {
      const query = $("ecoQuery").value.trim();
      const urls = $("ecoUrls").value.split(/\r?\n/).map((u) => u.trim()).filter(Boolean);
      if (!query && !urls.length) return toast("검색어 또는 URL을 입력해 주세요.", "warn");
      try {
        const res = await api(`/api/v2/projects/${encodeURIComponent(pid)}/eco-crawl`, {
          method: "POST",
          body: {
            query,
            urls,
            max_pages: Number($("ecoMaxPages").value || 4),
            capture_screenshot: $("ecoCap").checked,
            extract_images: $("ecoImg").checked,
            download_pdfs: $("ecoPdf").checked,
            sync_smc_kg: true,
          },
        });
        state.ecoCrawl = res;
        toast("eco-browser 크롤링·캡처를 시작했습니다.", "success");
        updateLiveBanner();
        syncPolling();
      } catch (err) {
        toast(`크롤링 시작 실패: ${err.message}`, "error");
      }
    });

    $("btnRunStage2Auto").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(pid)}/run`, { method: "POST", body: { mode: "single", stage_id: "stage2_source_collect" } });
      toast("2단계 4계층 자동 자료 수집을 시작했습니다.", "success");
      await loadActiveProject(pid, true);
    });

    $("anchorPdfInput").addEventListener("change", async (ev) => {
      const file = ev.target.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", file.name);
      try {
        await api(`/api/projects/${encodeURIComponent(pid)}/anchors/upload`, { method: "POST", body: fd });
        await api(`/api/v2/projects/${encodeURIComponent(pid)}/publishing-db/sync`, { method: "POST" });
        toast(`앵커 파일 '${file.name}' 등록 및 publishing_DB 동기화 완료`, "success");
        await loadActiveProject(pid, true);
      } catch (err) {
        toast(`업로드 실패: ${err.message}`, "error");
      }
    });

    document.querySelectorAll("[data-src-check]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const sid = cb.dataset.srcCheck;
        if (cb.checked) state.selectedSources.add(sid);
        else state.selectedSources.delete(sid);
      });
    });
    if ($("btnSelectAllSrc")) {
      $("btnSelectAllSrc").addEventListener("click", () => {
        sources.forEach((s) => s.source_id && state.selectedSources.add(s.source_id));
        renderStage2();
      });
    }
    if ($("btnClearAllSrc")) {
      $("btnClearAllSrc").addEventListener("click", () => {
        state.selectedSources.clear();
        renderStage2();
      });
    }

    $("notebookAskForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const q = $("notebookQuestion").value.trim();
      if (!q) return;
      state.notebookChat.push({ role: "user", text: q });
      $("notebookQuestion").value = "";
      renderStage2();
      try {
        const res = await api(`/api/v2/projects/${encodeURIComponent(pid)}/notebook/ask`, {
          method: "POST",
          body: {
            question: q,
            selected_source_ids: Array.from(state.selectedSources),
            include_smc_graphrag: true,
          },
        });
        state.notebookChat.push({
          role: "assistant",
          text: res.answer || "응답이 비어 있습니다.",
          citations: res.citations || [],
        });
        renderStage2();
        const feed = $("notebookChatFeed");
        if (feed) feed.scrollTop = feed.scrollHeight;
      } catch (err) {
        state.notebookChat.push({ role: "assistant", text: `질의 오류: ${err.message}` });
        renderStage2();
      }
    });

    document.querySelectorAll("[data-brief-mode]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const mode = btn.dataset.briefMode;
        const label = btn.textContent.trim();
        btn.disabled = true;
        state.notebookChat.push({ role: "user", text: `[스튜디오 생성] ${label}` });
        renderStage2();
        try {
          const res = await api(`/api/v2/projects/${encodeURIComponent(pid)}/notebook/brief`, {
            method: "POST",
            body: { mode, selected_source_ids: Array.from(state.selectedSources) },
          });
          state.notebookChat.push({
            role: "assistant",
            text: res.content || "생성 결과 없음",
            citations: res.citations || [],
          });
          toast(`${label} 생성 완료`, "success");
          renderStage2();
        } catch (err) {
          toast(`브리핑 생성 실패: ${err.message}`, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  // ========================================================================
  // VIEW 3: 3. 지식그래프 · publishing_DB 갤러리
  // ========================================================================
  async function renderStage3() {
    if (requireProjectGuard("3단계 지식그래프 · publishing_DB")) return;
    const pid = state.project.project_id;
    const [kgRes, dbRes] = await Promise.all([
      api(`/api/v2/projects/${encodeURIComponent(pid)}/knowledge-graph`).catch(() => ({ nodes: [], edges: [], stats: {} })),
      api(`/api/v2/projects/${encodeURIComponent(pid)}/publishing-db`).catch(() => ({ counts: {}, items: {} })),
    ]);
    state.kgData = kgRes;
    state.publishingDb = dbRes;

    const stats = kgRes.stats || {};
    const counts = dbRes.counts || {};
    const tabs = [
      { id: "captures", label: `📸 웹 캡처 (${counts.captures || 0})` },
      { id: "pdfs", label: `📑 PDF 문서 (${counts.pdfs || 0})` },
      { id: "reference_images", label: `🖼️ 참고 이미지 (${counts.reference_images || 0})` },
      { id: "web_pages", label: `📝 크롤링 마크다운 (${counts.web_pages || 0})` },
    ];
    const items = (dbRes.items || {})[state.dbActiveTab] || [];

    $("appView").innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">🕸️ 프로젝트 지식그래프 (${stats.nodes || 0} 노드 · ${stats.edges || 0} 관계)</h3>
            <p class="card-desc">저장 경로: <code>publishing_DB/${esc(pid)}/knowledge_graph/kg_graph.json</code> · <code>C:\\SMC_GRAPHRAG</code> 연계 트리플 ${stats.smc_kg_triples || 0}건</p>
          </div>
          <div class="row-wrap">
            <button type="button" class="btn btn-secondary btn-sm" id="btnRebuildKg">🔄 그래프 재구축</button>
            <button type="button" class="btn btn-primary btn-sm" id="btnRunStage3">▶ 3단계(SMC GraphRAG 증분) 실행</button>
          </div>
        </div>

        <div class="kg-layout">
          <div class="kg-canvas-wrap">
            <canvas id="kgCanvas"></canvas>
            <div class="kg-toolbar">
              <input id="kgSearch" class="text-input" style="max-width:220px;padding:6px 10px;font-size:12.5px;" placeholder="노드 검색..." />
              <button type="button" class="btn btn-secondary btn-xs" id="btnKgFit">⌖ 전체 맞추기</button>
            </div>
            <div class="kg-legend">
              <span class="legend-dot"><i style="background:#2563eb;"></i>주제</span>
              <span class="legend-dot"><i style="background:#0d9488;"></i>키워드</span>
              <span class="legend-dot"><i style="background:#7c3aed;"></i>출처[SRC]</span>
              <span class="legend-dot"><i style="background:#d97706;"></i>개념</span>
              <span class="legend-dot"><i style="background:#e11d48;"></i>SMC_GRAPHRAG</span>
            </div>
          </div>

          <div class="kg-inspector" id="kgInspector">
            <h4 style="margin:0;font-size:14.5px;">노드 인스펙터</h4>
            <p class="muted-sm">좌측 지식그래프에서 노드를 클릭하면 연결된 출처, 관계, <code>C:\\SMC_GRAPHRAG</code> 속성이 표시됩니다.</p>
            <div class="stat-card" style="padding:12px;">
              <div class="stat-label">구성 요약</div>
              <div class="muted-sm" style="margin-top:6px;">
                노드 ${stats.nodes || 0}개 · 엣지 ${stats.edges || 0}개<br/>
                출처 노드 ${stats.sources || 0}개 · SMC_KG 트리플 ${stats.smc_kg_triples || 0}건
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">🗄️ publishing_DB/${esc(pid)} 통합 자산 갤러리</h3>
            <p class="card-desc"><code>projects_v2/${esc(pid)}</code>와 동일한 폴더명으로 웹 캡처·PDF·참고이미지·문서를 보관합니다.</p>
          </div>
          <button type="button" class="btn btn-secondary btn-sm" id="btnSyncPubDb">↻ 프로젝트 자료 DB 동기화</button>
        </div>

        <div class="tabs">
          ${tabs.map((t) => `<button type="button" class="tab-btn ${t.id === state.dbActiveTab ? "active" : ""}" data-db-tab="${t.id}">${esc(t.label)}</button>`).join("")}
        </div>

        ${items.length ? `
          <div class="asset-grid">
            ${items.map((it) => {
              const isImg = /\.(png|jpg|jpeg|webp|svg)$/i.test(it.name || "");
              const isPdf = /\.pdf$/i.test(it.name || "");
              return `
                <div class="asset-card">
                  <div class="asset-thumb" data-preview-url="${esc(it.url)}" data-preview-title="${esc(it.name)}" data-preview-pdf="${isPdf ? "1" : "0"}">
                    ${isImg ? `<img src="${esc(it.url)}" alt="${esc(it.name)}" loading="lazy" />` : `<div style="font-size:36px;">${isPdf ? "📑" : "📝"}</div>`}
                  </div>
                  <div class="asset-body">
                    <div class="asset-title">${esc(it.name)}</div>
                    <div class="muted-sm">${fmtBytes(it.size_bytes)} · ${esc((it.modified_at || "").slice(0, 16).replace("T", " "))}</div>
                    <div class="asset-actions">
                      <button type="button" class="btn btn-secondary btn-xs" data-preview-url="${esc(it.url)}" data-preview-title="${esc(it.name)}" data-preview-pdf="${isPdf ? "1" : "0"}">미리보기</button>
                      <a href="${esc(it.url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-xs">원본 ↗</a>
                    </div>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        ` : `
          <div class="empty-state" style="padding:32px;">
            <p style="margin-bottom:10px;">이 탭에 저장된 항목이 아직 없습니다.</p>
            <button type="button" class="btn btn-primary btn-sm" id="btnGoStage2FromDb">2단계 eco-browser에서 웹 캡처·수집하기 →</button>
          </div>
        `}
      </div>
    `;

    // 지식그래프 캔버스 마운트
    const canvas = $("kgCanvas");
    if (canvas && window.SMCKnowledgeGraph) {
      const kg = new window.SMCKnowledgeGraph(canvas, {
        onSelect: (node, connected, nodeMap) => {
          const insp = $("kgInspector");
          if (!insp) return;
          if (!node) {
            insp.innerHTML = `<h4 style="margin:0;font-size:14.5px;">노드 인스펙터</h4><p class="muted-sm">노드를 클릭해 상세 관계를 확인하세요.</p>`;
            return;
          }
          insp.innerHTML = `
            <div class="row-between">
              <span class="badge badge-primary">${esc(node.group)}</span>
              <span class="muted-sm">연결 ${connected.length}건</span>
            </div>
            <h4 style="margin:0;font-size:15px;">${esc(node.label)}</h4>
            ${node.meta?.url ? `<a href="${esc(node.meta.url)}" target="_blank" rel="noopener" class="muted-sm" style="word-break:break-all;">${esc(node.meta.url)} ↗</a>` : ""}
            <div style="border-top:1px solid var(--border);padding-top:10px;">
              <div class="field-label">연결된 관계</div>
              <div class="stack-sm">
                ${connected.slice(0, 14).map((e) => {
                  const otherId = e.source === node.id ? e.target : e.source;
                  const other = nodeMap.get(otherId);
                  return `<div style="font-size:12.5px;padding:6px 8px;border-radius:7px;background:var(--bg-subtle);"><strong>${esc(e.relation || "연결")}</strong> → ${esc(other?.label || otherId)}</div>`;
                }).join("")}
              </div>
            </div>
          `;
        },
      });
      kg.setData(kgRes);
      state.kgInstance = kg;
      $("kgSearch").addEventListener("input", (e) => kg.setSearch(e.target.value));
      $("btnKgFit").addEventListener("click", () => kg.fitView());
    }

    $("btnRebuildKg").addEventListener("click", async () => {
      const btn = $("btnRebuildKg");
      btn.disabled = true;
      try {
        await api(`/api/v2/projects/${encodeURIComponent(pid)}/knowledge-graph/rebuild`, { method: "POST" });
        toast("지식그래프를 최신 자료 기준으로 재구축했습니다.", "success");
        await renderStage3();
      } catch (err) {
        toast(`재구축 실패: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
      }
    });

    $("btnRunStage3").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(pid)}/run`, { method: "POST", body: { mode: "single", stage_id: "stage3_kg_build" } });
      toast("3단계 SMC GraphRAG 증분 구축을 시작했습니다.", "success");
      await loadActiveProject(pid, true);
    });

    $("btnSyncPubDb").addEventListener("click", async () => {
      await api(`/api/v2/projects/${encodeURIComponent(pid)}/publishing-db/sync`, { method: "POST" });
      toast("publishing_DB 동기화를 완료했습니다.", "success");
      await renderStage3();
    });

    document.querySelectorAll("[data-db-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.dbActiveTab = btn.dataset.dbTab;
        renderStage3();
      });
    });

    document.querySelectorAll("[data-preview-url]").forEach((el) => {
      el.addEventListener("click", () => {
        openLightbox({
          title: el.dataset.previewTitle,
          url: el.dataset.previewUrl,
          isPdf: el.dataset.previewPdf === "1",
        });
      });
    });

    if ($("btnGoStage2FromDb")) {
      $("btnGoStage2FromDb").addEventListener("click", () => navigate("stage2"));
    }
  }

  // ========================================================================
  // VIEW 4: 4. 원고 집필 · 검수
  // ========================================================================
  async function renderStage4() {
    if (requireProjectGuard("4단계 원고 집필 · 검수")) return;
    const pid = state.project.project_id;
    const [chRes, cpRes] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(pid)}/chapters`).catch(() => ({ chapters: [] })),
      api(`/api/projects/${encodeURIComponent(pid)}/chapter-pipeline`).catch(() => null),
    ]);
    state.chapters = chRes.chapters || [];
    state.chapterPipeline = cpRes;
    updateLiveBanner();
    syncPolling();

    if (!state.selectedChapterId && state.chapters.length) {
      state.selectedChapterId = state.chapters[0].chapter_id;
    }
    let activeChapter = state.chapters.find((c) => c.chapter_id === state.selectedChapterId) || null;
    if (activeChapter && !state.chapterContent) {
      try {
        const detail = await api(`/api/projects/${encodeURIComponent(pid)}/chapters/${encodeURIComponent(activeChapter.chapter_id)}`);
        state.chapterContent = detail.content || "";
      } catch (_) {
        state.chapterContent = "";
      }
    }

    const reviewedCount = state.chapters.filter((c) => c.expert_reviewed).length;
    $("appView").innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">✍️ 단원별 심층 집필 파이프라인</h3>
            <p class="card-desc">총 ${state.chapters.length}개 단원 · 전문가 검토 완료 ${reviewedCount}/${state.chapters.length} · <code>C:\\SMC_GRAPHRAG</code> 근거 자동 연계</p>
          </div>
          <div class="row-wrap">
            <select id="cpDepth" class="select-input" style="width:140px;padding:6px 10px;">
              <option value="standard">표준 심도</option>
              <option value="deep" selected>심층 (권장)</option>
              <option value="exhaustive">최고 심도</option>
            </select>
            <button type="button" class="btn btn-primary btn-sm" id="btnStartCp">▶ 단원 순차 집필 시작</button>
            <button type="button" class="btn btn-secondary btn-sm" id="btnRunStage4">4단계 일괄 집필</button>
            <button type="button" class="btn btn-accent btn-sm" id="btnReviewAllCh">✓ 전체 검토 완료</button>
          </div>
        </div>
      </div>

      <div class="editor-layout" style="margin-top:18px;">
        <div class="card" style="padding:14px;">
          <div class="field-label" style="margin-bottom:8px;">단원 목록 (${state.chapters.length})</div>
          <div class="chapter-list">
            ${state.chapters.length ? state.chapters.map((ch) => `
              <button type="button" class="chapter-btn ${ch.chapter_id === state.selectedChapterId ? "active" : ""}" data-ch-id="${esc(ch.chapter_id)}">
                <div class="row-between">
                  <strong style="font-size:13px;">${esc(ch.chapter_id)}</strong>
                  <span class="badge ${ch.expert_reviewed ? "badge-success" : ch.exists ? "badge-primary" : ""}">${ch.expert_reviewed ? "검토완료" : ch.exists ? `${ch.char_count || 0}자` : "미집필"}</span>
                </div>
                <span class="muted-sm" style="text-align:left;">${esc(ch.title_ko || ch.title || "")}</span>
              </button>
            `).join("") : `<p class="muted-sm">1단계 목차를 먼저 생성해 주세요.</p>`}
          </div>
        </div>

        <div class="card">
          ${activeChapter ? `
            <div class="card-header">
              <div>
                <h3 class="card-title">${esc(activeChapter.chapter_id)} · ${esc(activeChapter.title_ko || "")}</h3>
                <p class="card-desc">분량 ${activeChapter.char_count || 0}자 · 인용 ${activeChapter.citation_count || 0}건 · 검토 ${activeChapter.expert_reviewed ? "완료" : "대기"}</p>
              </div>
              <div class="row-wrap">
                <button type="button" class="btn btn-secondary btn-sm" id="btnToggleChReview">${activeChapter.expert_reviewed ? "검토 해제" : "✓ 검토 완료"}</button>
                <button type="button" class="btn btn-primary btn-sm" id="btnSaveChapter">💾 원고 저장</button>
              </div>
            </div>
            <textarea id="chapterEditorBox" class="code-editor" placeholder="집필된 MDX 원고가 여기에 표시됩니다...">${esc(state.chapterContent)}</textarea>
          ` : `
            <div class="empty-state" style="padding:40px;">
              <h3>편집할 단원을 선택해 주세요</h3>
              <p>좌측 목록에서 단원을 선택하거나 상단 [단원 순차 집필 시작]을 눌러 원고를 생성할 수 있습니다.</p>
            </div>
          `}
        </div>
      </div>
    `;

    $("btnStartCp").addEventListener("click", async () => {
      try {
        await api(`/api/projects/${encodeURIComponent(pid)}/chapter-pipeline/start`, {
          method: "POST",
          body: { research_depth: $("cpDepth").value, force_rerun: false },
        });
        toast("단원별 순차 심층 집필 파이프라인을 시작했습니다.", "success");
        await renderStage4();
      } catch (err) {
        toast(`실행 실패: ${err.message}`, "error");
      }
    });

    $("btnRunStage4").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(pid)}/run`, { method: "POST", body: { mode: "single", stage_id: "stage4_manuscript_draft" } });
      toast("4단계 일괄 집필을 시작했습니다.", "success");
      await loadActiveProject(pid, true);
    });

    $("btnReviewAllCh").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(pid)}/chapters/review-all`, { method: "POST", body: { reviewed: true, note: "v2 스튜디오 일괄 검토" } });
      toast("모든 집필 단원을 검토 완료 처리했습니다.", "success");
      await renderStage4();
    });

    document.querySelectorAll("[data-ch-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.selectedChapterId = btn.dataset.chId;
        state.chapterContent = "";
        try {
          const detail = await api(`/api/projects/${encodeURIComponent(pid)}/chapters/${encodeURIComponent(state.selectedChapterId)}`);
          state.chapterContent = detail.content || "";
        } catch (_) {}
        renderStage4();
      });
    });

    if ($("btnSaveChapter") && activeChapter) {
      $("btnSaveChapter").addEventListener("click", async () => {
        const content = $("chapterEditorBox").value;
        await api(`/api/projects/${encodeURIComponent(pid)}/chapters/${encodeURIComponent(activeChapter.chapter_id)}`, {
          method: "PUT",
          body: { content },
        });
        state.chapterContent = content;
        toast(`${activeChapter.chapter_id} 원고를 저장했습니다.`, "success");
      });
    }

    if ($("btnToggleChReview") && activeChapter) {
      $("btnToggleChReview").addEventListener("click", async () => {
        await api(`/api/projects/${encodeURIComponent(pid)}/chapters/${encodeURIComponent(activeChapter.chapter_id)}/review`, {
          method: "POST",
          body: { reviewed: !activeChapter.expert_reviewed, note: "스튜디오 검토" },
        });
        toast("단원 검토 상태를 변경했습니다.", "success");
        await renderStage4();
      });
    }
  }

  // ========================================================================
  // VIEW 5: 5. 시각화 · 도판 스튜디오 (Draw.io + Prompt Pack + Paid AI + Upload)
  // ========================================================================
  async function renderStage5() {
    if (requireProjectGuard("5단계 시각화 · 도판 스튜디오")) return;
    const pid = state.project.project_id;
    const [visRes, ppRes, qaRes] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(pid)}/visuals`).catch(() => ({ visuals: [] })),
      api(`/api/projects/${encodeURIComponent(pid)}/visuals/prompt-pack`).catch(() => null),
      api(`/api/projects/${encodeURIComponent(pid)}/visuals/qa`).catch(() => null),
    ]);
    state.visualsData = visRes;
    state.promptPack = ppRes;
    state.visualsQa = qaRes;
    const visuals = visRes.visuals || [];

    $("appView").innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">🎨 도판 제작 · 업그레이드 툴바 (총 ${visuals.length}개 도판)</h3>
            <p class="card-desc">무료 0원 학술 도식(<code>Scientific-Figure-Design Draw.io + Lucide</code>), 한·영 프롬프트 팩, 선택 유료 AI 재생성, 내 파일 직접 대체를 한곳에서 제어합니다.</p>
          </div>
          <div class="row-wrap">
            <button type="button" class="btn btn-secondary btn-sm" id="btnRunStage5">▶ 5단계 기본 도판 생성</button>
            <button type="button" class="btn btn-accent btn-sm" id="btnBuildPromptPack">📝 한·영 프롬프트 팩</button>
            <button type="button" class="btn btn-primary btn-sm" id="btnUpgradeDrawio">📐 Draw.io 학술 도식 업그레이드 (0원)</button>
          </div>
        </div>

        <div class="row-wrap" style="padding:12px 14px;background:var(--bg-subtle);border-radius:10px;border:1px solid var(--border);">
          <strong style="font-size:13px;">💎 선택 유료 AI 재생성 설정:</strong>
          <select id="paidEngineSel" class="select-input" style="width:220px;padding:6px 10px;">
            <option value="gemini_flash">Gemini 2.5 Flash Image (~$0.039)</option>
            <option value="gemini_pro">Gemini 3 Pro Image (~$0.134)</option>
            <option value="fal_nano_banana">fal.ai Nano Banana (~$0.04)</option>
            <option value="fal_flux_pro">fal.ai FLUX Pro Ultra (~$0.06)</option>
          </select>
          <input id="paidBudgetCap" type="number" step="0.5" min="0.5" max="100" value="3.0" class="text-input" style="width:92px;padding:6px 10px;" title="예산 상한 USD" />
          <span class="muted-sm">USD 상한</span>
          <button type="button" class="btn btn-secondary btn-sm" id="btnBatchPaidReplace">✨ 개념도 일괄 유료 재생성</button>
          ${ppRes?.docx_url ? `<a href="${esc(ppRes.docx_url)}" target="_blank" class="btn btn-secondary btn-sm">📥 프롬프트 팩 DOCX ↗</a>` : ""}
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">도판 갤러리 (${visuals.length}건)</h3>
            <p class="card-desc">QA 요약: 통과 ${qaRes?.passed ?? "-"} · 주의 ${qaRes?.warnings ?? "-"} · 차단 ${qaRes?.failed ?? "-"}</p>
          </div>
        </div>

        ${visuals.length ? `
          <div class="asset-grid">
            ${visuals.map((v) => {
              const imgUrl = v.url || `/project-files/${encodeURIComponent(pid)}/assets/${encodeURIComponent(v.filename || "")}`;
              return `
                <div class="asset-card">
                  <div class="asset-thumb" data-vis-preview="${esc(imgUrl)}" data-vis-title="${esc(v.title_ko || v.figure_id || v.filename)}">
                    <img src="${esc(imgUrl)}?t=${Date.now()}" alt="${esc(v.title_ko || v.filename)}" loading="lazy" />
                  </div>
                  <div class="asset-body">
                    <div class="row-between">
                      <span class="badge badge-primary">${esc(v.figure_id || v.chapter_id || "FIG")}</span>
                      <span class="muted-sm">${esc(v.kind || v.engine || "")}</span>
                    </div>
                    <div class="asset-title">${esc(v.title_ko || v.filename)}</div>
                    <div class="asset-actions">
                      <button type="button" class="btn btn-primary btn-xs" data-regen-fig="${esc(v.figure_id || v.filename)}">💎 AI 재생성</button>
                      <label class="btn btn-secondary btn-xs" style="cursor:pointer;">
                        📤 내 파일 대체
                        <input type="file" accept=".png,.jpg,.jpeg,.webp,.svg" hidden data-upload-fig="${esc(v.figure_id || v.filename)}" />
                      </label>
                      ${v.drawio_url ? `<a href="${esc(v.drawio_url)}" target="_blank" class="btn btn-secondary btn-xs">.drawio</a>` : ""}
                    </div>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        ` : `
          <div class="empty-state">
            <h3>아직 생성된 도판이 없습니다</h3>
            <p>[5단계 기본 도판 생성] 또는 [한·영 프롬프트 팩] 버튼을 눌러 시작하세요.</p>
          </div>
        `}
      </div>
    `;

    $("btnRunStage5").addEventListener("click", async () => {
      await api(`/api/projects/${encodeURIComponent(pid)}/run`, { method: "POST", body: { mode: "single", stage_id: "stage5_visuals" } });
      toast("5단계 도판 생성을 시작했습니다.", "success");
      await loadActiveProject(pid, true);
    });

    $("btnBuildPromptPack").addEventListener("click", async () => {
      const btn = $("btnBuildPromptPack");
      btn.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(pid)}/visuals/prompt-pack`, { method: "POST", body: {} });
        toast("고품질 한·영 프롬프트 팩(MD/DOCX) 생성 완료!", "success");
        await renderStage5();
      } catch (err) {
        toast(`프롬프트 팩 오류: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
      }
    });

    $("btnUpgradeDrawio").addEventListener("click", async () => {
      const btn = $("btnUpgradeDrawio");
      btn.disabled = true;
      try {
        const res = await api(`/api/projects/${encodeURIComponent(pid)}/visuals/upgrade-scientific-drawio`, {
          method: "POST",
          body: { overwrite_existing: true, also_republish: false },
        });
        toast(`Scientific-Figure-Design Draw.io 업그레이드 완료 (${res.upgraded_count || 0}건)`, "success");
        await renderStage5();
      } catch (err) {
        toast(`Draw.io 업그레이드 오류: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
      }
    });

    $("btnBatchPaidReplace").addEventListener("click", async () => {
      const engine = $("paidEngineSel").value;
      const cap = Number($("paidBudgetCap").value || 3.0);
      if (!confirm(`선택한 유료 엔진(${engine}, 상한 $${cap})으로 개념도 일괄 재생성을 실행할까요?`)) return;
      try {
        await api(`/api/projects/${encodeURIComponent(pid)}/visuals/batch-paid-replace`, {
          method: "POST",
          body: { engine, max_budget_usd: cap, only_schematic_or_placeholder: true },
        });
        toast("일괄 유료 AI 재생성을 시작했습니다.", "success");
      } catch (err) {
        toast(`실행 실패: ${err.message}`, "error");
      }
    });

    document.querySelectorAll("[data-vis-preview]").forEach((el) => {
      el.addEventListener("click", () => openLightbox({ title: el.dataset.visTitle, url: el.dataset.visPreview }));
    });

    document.querySelectorAll("[data-regen-fig]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const fid = btn.dataset.regenFig;
        const engine = $("paidEngineSel").value;
        if (!confirm(`'${fid}' 도판을 유료 AI(${engine})로 재생성할까요?`)) return;
        btn.disabled = true;
        try {
          await api(`/api/projects/${encodeURIComponent(pid)}/visuals/regenerate`, {
            method: "POST",
            body: { figure_id: fid, engine },
          });
          toast(`'${fid}' 재생성 완료!`, "success");
          await renderStage5();
        } catch (err) {
          toast(`재생성 실패: ${err.message}`, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });

    document.querySelectorAll("[data-upload-fig]").forEach((input) => {
      input.addEventListener("change", async (ev) => {
        const file = ev.target.files?.[0];
        if (!file) return;
        const fid = input.dataset.uploadFig;
        const fd = new FormData();
        fd.append("figure_id", fid);
        fd.append("file", file);
        try {
          await api(`/api/projects/${encodeURIComponent(pid)}/visuals/replace-upload`, { method: "POST", body: fd });
          toast(`'${fid}' 도판을 업로드한 파일로 교체했습니다.`, "success");
          await renderStage5();
        } catch (err) {
          toast(`교체 실패: ${err.message}`, "error");
        }
      });
    });
  }

  // ========================================================================
  // VIEW 6: 6. 최종 출판 · 변환
  // ========================================================================
  async function renderStage6() {
    if (requireProjectGuard("6단계 최종 출판 · 변환")) return;
    const pid = state.project.project_id;
    const [sumRes, fmtRes, readyRes] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(pid)}/outputs-summary`).catch(() => ({})),
      api("/api/output-converter/formats").catch(() => ({ formats: [] })),
      api(`/api/projects/${encodeURIComponent(pid)}/publish-readiness`).catch(() => ({})),
    ]);
    state.outputsSummary = sumRes;
    const rawFmts = fmtRes.formats || {};
    state.outputFormats = Array.isArray(rawFmts) ? rawFmts : Object.values(rawFmts);
    const primary = sumRes.primary_outputs || [];
    const converted = sumRes.converted_outputs || [];
    const blockers = readyRes.blockers || [];

    $("appView").innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">📦 기본 출판 산출물 2종 (마스터 DOCX · 블로그 단일 HTML)</h3>
            <p class="card-desc">중복 파일을 방지하기 위해 기본 출판은 2종만 깔끔하게 생성합니다.</p>
          </div>
          <div class="row-wrap">
            <button type="button" class="btn btn-primary" id="btnPublishDefault">🚀 기본 2종 출판 실행</button>
            <a href="/api/projects/${encodeURIComponent(pid)}/exports.zip" class="btn btn-secondary">🗜️ 전체 ZIP 다운로드</a>
          </div>
        </div>

        ${blockers.length ? `
          <div style="padding:12px 14px;border-radius:10px;background:var(--warning-soft);border:1px solid rgba(217,119,6,0.3);margin-bottom:14px;">
            <strong style="color:var(--warning);">출판 전 확인 사항 (${blockers.length}건)</strong>
            <ul style="margin:6px 0 0 18px;font-size:13px;">
              ${blockers.map((b) => `<li>${esc(typeof b === "string" ? b : b.message || JSON.stringify(b))}</li>`).join("")}
            </ul>
          </div>
        ` : ""}

        ${primary.length ? `
          <div class="grid-2">
            ${primary.map((o) => `
              <div class="stat-card" style="display:flex;flex-direction:column;gap:8px;">
                <span class="badge badge-success">${esc(o.kind || o.format || "기본 산출물")}</span>
                <strong>${esc(o.label || o.filename)}</strong>
                <span class="muted-sm">${fmtBytes(o.size_bytes)}</span>
                <div><a href="${esc(o.url)}" target="_blank" class="btn btn-primary btn-sm">다운로드 / 열기 ↗</a></div>
              </div>
            `).join("")}
          </div>
        ` : `<p class="muted-sm">아직 생성된 출판 파일이 없습니다. 상단 [기본 2종 출판 실행]을 눌러주세요.</p>`}
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <h3 class="card-title">🔄 사후 포맷 변환 (PDF · 학회지 2단 · 단원 분할)</h3>
            <p class="card-desc">필요한 인쇄·투고용 포맷만 선택해 추가로 변환합니다.</p>
          </div>
        </div>
        <div class="grid-3">
          ${state.outputFormats.map((f) => `
            <div class="stat-card" style="display:flex;flex-direction:column;gap:8px;">
              <strong>${esc((f.icon ? f.icon + " " : "") + (f.name_ko || f.label_ko || f.label || f.id))}</strong>
              <span class="muted-sm">${esc(f.description_ko || f.description || "")}</span>
              <button type="button" class="btn btn-secondary btn-sm" data-convert-fmt="${esc(f.id)}">변환 생성</button>
            </div>
          `).join("")}
        </div>
        ${converted.length ? `
          <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border);">
            <div class="field-label">생성된 변환 파일 (${converted.length})</div>
            <div class="row-wrap">
              ${converted.map((c) => `<a href="${esc(c.url)}" target="_blank" class="btn btn-secondary btn-xs">📄 ${esc(c.filename || c.label)} ↗</a>`).join("")}
            </div>
          </div>
        ` : ""}
      </div>
    `;

    $("btnPublishDefault").addEventListener("click", async () => {
      const btn = $("btnPublishDefault");
      btn.disabled = true;
      try {
        await api(`/api/projects/${encodeURIComponent(pid)}/publish-default`, { method: "POST", body: {} });
        toast("기본 2종(DOCX + HTML) 출판을 완료했습니다!", "success");
        await renderStage6();
      } catch (err) {
        toast(`출판 오류: ${err.message}`, "error");
      } finally {
        btn.disabled = false;
      }
    });

    document.querySelectorAll("[data-convert-fmt]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const fmt = btn.dataset.convertFmt;
        btn.disabled = true;
        try {
          await api(`/api/projects/${encodeURIComponent(pid)}/convert-output`, { method: "POST", body: { target_format: fmt } });
          toast(`${fmt} 포맷 변환 완료!`, "success");
          await renderStage6();
        } catch (err) {
          toast(`변환 실패: ${err.message}`, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  // ========================================================================
  // VIEW 7: 시스템 · 진단/복구 & API 키
  // ========================================================================
  async function renderSystem() {
    const ws = state.bootstrap?.workspace_info || {};
    const keys = state.bootstrap?.api_keys || {};
    let diag = null;
    if (state.activeProjectId) {
      diag = await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/diagnostics`).catch(() => null);
    }
    const issues = diag?.issues || [];

    $("appView").innerHTML = `
      <div class="grid-2">
        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">🛠️ 프로젝트 3단계 오류 진단 · 원클릭 복구</h3>
              <p class="card-desc">${state.project ? `대상: ${esc(state.project.topic_ko)}` : "프로젝트를 선택하면 상세 진단을 수행합니다."}</p>
            </div>
            ${state.project ? `<button type="button" class="btn btn-secondary btn-sm" id="btnReDiag">↻ 재진단</button>` : ""}
          </div>
          ${state.project ? (issues.length ? `
            <div class="stack-sm">
              ${issues.map((is) => `
                <div style="border:1px solid var(--border);border-radius:10px;padding:12px;">
                  <div class="row-between">
                    <span class="badge ${is.severity === "critical" || is.severity === "error" ? "badge-danger" : "badge-warning"}">${esc(is.severity || "warn")}</span>
                    ${is.action_id ? `<button type="button" class="btn btn-primary btn-xs" data-recover-act="${esc(is.action_id)}">원클릭 복구</button>` : ""}
                  </div>
                  <strong style="display:block;margin-top:6px;font-size:13.5px;">${esc(is.title || is.code || "진단 항목")}</strong>
                  <p class="muted-sm" style="margin-top:3px;">${esc(is.detail || is.message || "")}</p>
                </div>
              `).join("")}
            </div>
          ` : `<p class="muted-sm">✅ 현재 프로젝트에서 감지된 차단 오류가 없습니다.</p>`) : `<p class="muted-sm">좌측 상단에서 프로젝트를 선택하면 진단을 표시합니다.</p>`}
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <h3 class="card-title">🔑 API 키 설정 (.env 안전 저장)</h3>
              <p class="card-desc">변경할 키만 입력하고 저장하세요. 기존 키는 마스킹되어 보호됩니다.</p>
            </div>
          </div>
          <form id="apiKeysForm" class="stack-sm">
            ${["GEMINI_API_KEY", "FAL_KEY", "KMA_HUB_KEY", "DATA_GO_KR_API_KEY", "KOSIS_API_KEY"].map((k) => {
              const info = keys[k] || {};
              const configured = Boolean(info.configured || info === true);
              return `
                <div class="form-field">
                  <label>${esc(k)} <span class="badge ${configured ? "badge-success" : ""}">${configured ? "설정됨" : "미설정"}</span></label>
                  <input name="${esc(k)}" type="password" class="text-input" placeholder="${configured ? "변경 시에만 새 키 입력" : "API 키 입력..."}" autocomplete="off" />
                </div>
              `;
            }).join("")}
            <div style="padding-top:6px;">
              <button type="submit" class="btn btn-primary btn-sm">💾 API 키 저장</button>
            </div>
          </form>
        </div>
      </div>

      <div class="card" style="margin-top:18px;">
        <div class="card-header">
          <div>
            <h3 class="card-title">📂 저장소 경로 및 엔진 현황</h3>
            <p class="card-desc">기존 <code>projects/</code> 폴더는 보존되며 모든 신규 작업은 <code>projects_v2/</code>와 <code>publishing_DB/</code>에 저장됩니다.</p>
          </div>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>구성 요소</th><th>경로 / 상태</th></tr></thead>
            <tbody>
              <tr><td><strong>신규 프로젝트 폴더</strong></td><td><code>${esc(ws.projects_dir || "projects_v2")}</code></td></tr>
              <tr><td><strong>통합 리서치 DB 폴더</strong></td><td><code>${esc(ws.publishing_db_dir || "publishing_DB")}</code></td></tr>
              <tr><td><strong>보존된 기존 폴더</strong></td><td><code>${esc(ws.legacy_projects_dir || "projects")}</code> (원본 무훼손)</td></tr>
              <tr><td><strong>로컬 지식그래프</strong></td><td><code>${esc(ws.smc_graphrag_root || "C:\\SMC_GRAPHRAG")}</code> (${ws.smc_graphrag_exists ? "연결됨" : "미감지"})</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    if ($("btnReDiag")) {
      $("btnReDiag").addEventListener("click", () => renderSystem());
    }
    document.querySelectorAll("[data-recover-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const actId = btn.dataset.recoverAct;
        btn.disabled = true;
        try {
          await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/recovery/execute`, {
            method: "POST",
            body: { action_id: actId, params: {} },
          });
          toast(`복구 액션(${actId}) 실행 완료`, "success");
          await loadActiveProject(state.activeProjectId, true);
        } catch (err) {
          toast(`복구 실패: ${err.message}`, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });

    $("apiKeysForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {};
      new FormData(ev.target).forEach((v, k) => {
        if (String(v).trim()) payload[k] = String(v).trim();
      });
      if (!Object.keys(payload).length) return toast("입력된 새 API 키가 없습니다.", "warn");
      await api("/api/explorer/keys", { method: "POST", body: payload });
      toast("API 키를 안전하게 저장했습니다.", "success");
      await loadBootstrap(true);
      renderSystem();
    });
  }

  // ---------- Global Wiring ----------
  function bindShellEvents() {
    document.querySelectorAll("[data-route]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        navigate(el.dataset.route);
      });
    });

    $("btnOpenSidebar").addEventListener("click", () => $("appShell").classList.add("sidebar-open"));
    $("btnCloseSidebar").addEventListener("click", () => $("appShell").classList.remove("sidebar-open"));
    $("sidebarBackdrop").addEventListener("click", () => $("appShell").classList.remove("sidebar-open"));

    $("btnQuickNew").addEventListener("click", () => navigate("home"));
    $("projectSelect").addEventListener("change", async (ev) => {
      const pid = ev.target.value;
      state.selectedSources.clear();
      state.notebookChat = [];
      state.selectedChapterId = "";
      state.chapterContent = "";
      await loadActiveProject(pid, true);
    });

    $("btnRefreshAll").addEventListener("click", async () => {
      await loadBootstrap(true);
      await renderCurrentRoute();
      toast("최신 상태로 새로고침했습니다.");
    });

    $("btnStopRunning").addEventListener("click", async () => {
      if (!state.activeProjectId) return;
      await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/stop`, { method: "POST" }).catch(() => {});
      await api(`/api/projects/${encodeURIComponent(state.activeProjectId)}/chapter-pipeline/stop`, { method: "POST" }).catch(() => {});
      toast("실행 중인 작업에 중지 신호를 보냈습니다.", "warn");
      await loadActiveProject(state.activeProjectId, true);
    });

    const savedTheme = localStorage.getItem("smc_v2_theme") || "light";
    document.documentElement.setAttribute("data-theme", savedTheme);
    $("btnToggleTheme").textContent = savedTheme === "dark" ? "☀️ 라이트 모드" : "🌙 다크 모드";
    $("btnToggleTheme").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", cur);
      localStorage.setItem("smc_v2_theme", cur);
      $("btnToggleTheme").textContent = cur === "dark" ? "☀️ 라이트 모드" : "🌙 다크 모드";
      if (state.kgInstance) state.kgInstance.render();
    });

    $("btnCloseLightbox").addEventListener("click", closeLightbox);
    $("lightboxModal").addEventListener("click", (ev) => {
      if (ev.target === $("lightboxModal")) closeLightbox();
    });
    window.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeLightbox();
    });
    window.addEventListener("hashchange", () => {
      const next = (window.location.hash || "#home").replace(/^#/, "");
      if (ROUTE_META[next] && next !== state.route) navigate(next);
    });
  }

  async function init() {
    bindShellEvents();
    try {
      await loadBootstrap(false);
    } catch (err) {
      toast(`초기화 오류: ${err.message}`, "error");
    }
    const hashRoute = (window.location.hash || "#home").replace(/^#/, "");
    navigate(ROUTE_META[hashRoute] ? hashRoute : "home");
  }

  init();
})();
