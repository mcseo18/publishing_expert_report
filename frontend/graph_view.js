/* ==========================================================================
   SMC Knowledge Graph Interactive Canvas Renderer (Zero External Dependencies)
   Renders publishing_DB/<pid>/knowledge_graph/kg_graph.json with zoom/pan/filter
   ========================================================================== */
(function () {
  const GROUP_COLORS = {
    topic: "#2563eb",
    keyword: "#0d9488",
    source: "#7c3aed",
    concept: "#d97706",
    smc_kg: "#e11d48",
    default: "#475569",
  };

  const GROUP_RADIUS = {
    topic: 22,
    keyword: 13,
    source: 12,
    concept: 11,
    smc_kg: 11,
    default: 10,
  };

  class SMCKnowledgeGraph {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.onSelect = options.onSelect || (() => {});
      this.nodes = [];
      this.edges = [];
      this.nodeMap = new Map();
      this.selectedId = null;
      this.hoverId = null;
      this.searchTerm = "";
      this.hiddenGroups = new Set();

      this.scale = 1;
      this.offsetX = 0;
      this.offsetY = 0;
      this.isDragging = false;
      this.dragStart = { x: 0, y: 0 };
      this.dragMoved = false;

      this._bindEvents();
      this._resize();
      window.addEventListener("resize", () => this._resize());
    }

    _resize() {
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.width = Math.max(300, Math.floor(rect.width));
      this.height = Math.max(300, Math.floor(rect.height));
      this.canvas.width = this.width * dpr;
      this.canvas.height = this.height * dpr;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.render();
    }

    setData(graph) {
      const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
      const rawEdges = Array.isArray(graph?.edges) ? graph.edges : [];
      this.edges = rawEdges.map((e) => ({
        source: String(e.source || ""),
        target: String(e.target || ""),
        relation: String(e.relation || ""),
        weight: Number(e.weight || 1),
      }));

      // 계층적 원형 배치 + 가벼운 반발 이완 (즉시 안정화)
      const groups = { topic: [], keyword: [], source: [], concept: [], smc_kg: [] };
      this.nodes = rawNodes.map((n) => {
        const g = groups[n.group] ? n.group : "concept";
        const item = {
          id: String(n.id),
          label: String(n.label || n.id),
          group: g,
          meta: n.meta || {},
          r: GROUP_RADIUS[g] || GROUP_RADIUS.default,
          color: GROUP_COLORS[g] || GROUP_COLORS.default,
          x: 0,
          y: 0,
        };
        groups[g].push(item);
        return item;
      });

      const ringConfig = [
        { list: groups.topic, radius: 0 },
        { list: groups.keyword, radius: 115 },
        { list: groups.source, radius: 225 },
        { list: groups.concept, radius: 320 },
        { list: groups.smc_kg, radius: 410 },
      ];

      ringConfig.forEach(({ list, radius }, ringIdx) => {
        const count = list.length;
        if (!count) return;
        const phase = ringIdx * 0.45;
        list.forEach((node, idx) => {
          if (radius === 0) {
            node.x = idx * 36;
            node.y = 0;
          } else {
            const angle = phase + (idx / count) * Math.PI * 2;
            const jitter = (idx % 2 === 0 ? 1 : -1) * Math.min(22, radius * 0.08);
            node.x = Math.cos(angle) * (radius + jitter);
            node.y = Math.sin(angle) * (radius + jitter);
          }
        });
      });

      this.nodeMap = new Map(this.nodes.map((n) => [n.id, n]));
      this._relaxLayout(45);
      this.fitView();
    }

    _relaxLayout(iterations) {
      const nodes = this.nodes;
      const nCount = nodes.length;
      if (nCount < 2 || nCount > 240) return;
      for (let iter = 0; iter < iterations; iter++) {
        for (let i = 0; i < nCount; i++) {
          const a = nodes[i];
          if (a.group === "topic") continue;
          for (let j = i + 1; j < nCount; j++) {
            const b = nodes[j];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distSq = dx * dx + dy * dy + 0.01;
            const minDist = (a.r + b.r) * 2.7;
            if (distSq < minDist * minDist) {
              const dist = Math.sqrt(distSq);
              const push = (minDist - dist) * 0.14;
              const ux = dx / dist;
              const uy = dy / dist;
              a.x -= ux * push;
              a.y -= uy * push;
              if (b.group !== "topic") {
                b.x += ux * push;
                b.y += uy * push;
              }
            }
          }
        }
      }
    }

    fitView() {
      if (!this.nodes.length) {
        this.scale = 1;
        this.offsetX = this.width / 2;
        this.offsetY = this.height / 2;
        this.render();
        return;
      }
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      this.nodes.forEach((n) => {
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
      });
      const pad = 72;
      const spanX = Math.max(120, maxX - minX + pad * 2);
      const spanY = Math.max(120, maxY - minY + pad * 2);
      this.scale = Math.max(0.35, Math.min(1.45, Math.min(this.width / spanX, this.height / spanY)));
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      this.offsetX = this.width / 2 - cx * this.scale;
      this.offsetY = this.height / 2 - cy * this.scale;
      this.render();
    }

    setSearch(term) {
      this.searchTerm = String(term || "").trim().toLowerCase();
      this.render();
    }

    toggleGroup(group) {
      if (this.hiddenGroups.has(group)) this.hiddenGroups.delete(group);
      else this.hiddenGroups.add(group);
      this.render();
    }

    _screenToWorld(sx, sy) {
      return {
        x: (sx - this.offsetX) / this.scale,
        y: (sy - this.offsetY) / this.scale,
      };
    }

    _hitTest(sx, sy) {
      const w = this._screenToWorld(sx, sy);
      for (let i = this.nodes.length - 1; i >= 0; i--) {
        const n = this.nodes[i];
        if (this.hiddenGroups.has(n.group)) continue;
        const dx = w.x - n.x;
        const dy = w.y - n.y;
        const hitR = n.r + 5 / this.scale;
        if (dx * dx + dy * dy <= hitR * hitR) return n;
      }
      return null;
    }

    _bindEvents() {
      const c = this.canvas;
      c.addEventListener("wheel", (ev) => {
        ev.preventDefault();
        const rect = c.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;
        const factor = ev.deltaY < 0 ? 1.14 : 0.88;
        const nextScale = Math.max(0.25, Math.min(3.0, this.scale * factor));
        const ratio = nextScale / this.scale;
        this.offsetX = mx - (mx - this.offsetX) * ratio;
        this.offsetY = my - (my - this.offsetY) * ratio;
        this.scale = nextScale;
        this.render();
      }, { passive: false });

      c.addEventListener("mousedown", (ev) => {
        this.isDragging = true;
        this.dragMoved = false;
        this.dragStart = { x: ev.clientX - this.offsetX, y: ev.clientY - this.offsetY };
      });

      window.addEventListener("mousemove", (ev) => {
        const rect = c.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;
        if (this.isDragging) {
          this.offsetX = ev.clientX - this.dragStart.x;
          this.offsetY = ev.clientY - this.dragStart.y;
          this.dragMoved = true;
          this.render();
          return;
        }
        if (mx >= 0 && my >= 0 && mx <= rect.width && my <= rect.height) {
          const hit = this._hitTest(mx, my);
          const nextHover = hit ? hit.id : null;
          if (nextHover !== this.hoverId) {
            this.hoverId = nextHover;
            c.style.cursor = hit ? "pointer" : "grab";
            this.render();
          }
        }
      });

      window.addEventListener("mouseup", (ev) => {
        if (!this.isDragging) return;
        this.isDragging = false;
        if (!this.dragMoved) {
          const rect = c.getBoundingClientRect();
          const hit = this._hitTest(ev.clientX - rect.left, ev.clientY - rect.top);
          this.selectedId = hit ? hit.id : null;
          if (hit) {
            const connected = this.edges.filter((e) => e.source === hit.id || e.target === hit.id);
            this.onSelect(hit, connected, this.nodeMap);
          } else {
            this.onSelect(null, [], this.nodeMap);
          }
          this.render();
        }
      });
    }

    render() {
      const ctx = this.ctx;
      const isDark = document.documentElement.getAttribute("data-theme") === "dark";
      ctx.clearRect(0, 0, this.width, this.height);

      if (!this.nodes.length) {
        ctx.fillStyle = isDark ? "#94a3b8" : "#64748b";
        ctx.font = "500 14px Pretendard, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("아직 지식그래프 노드가 없습니다. 리서치를 수집하거나 [그래프 재구축]을 눌러주세요.", this.width / 2, this.height / 2);
        return;
      }

      const activeId = this.selectedId || this.hoverId;
      const neighborSet = new Set();
      if (activeId) {
        neighborSet.add(activeId);
        this.edges.forEach((e) => {
          if (e.source === activeId) neighborSet.add(e.target);
          if (e.target === activeId) neighborSet.add(e.source);
        });
      }

      ctx.save();
      ctx.translate(this.offsetX, this.offsetY);
      ctx.scale(this.scale, this.scale);

      // 1. 엣지 그리기
      this.edges.forEach((e) => {
        const a = this.nodeMap.get(e.source);
        const b = this.nodeMap.get(e.target);
        if (!a || !b) return;
        if (this.hiddenGroups.has(a.group) || this.hiddenGroups.has(b.group)) return;
        const highlighted = activeId && (e.source === activeId || e.target === activeId);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.lineWidth = highlighted ? 2.1 : 1.0;
        ctx.strokeStyle = highlighted
          ? (isDark ? "rgba(96,165,250,0.85)" : "rgba(37,99,235,0.72)")
          : (isDark ? "rgba(148,163,184,0.22)" : "rgba(100,116,139,0.24)");
        ctx.stroke();

        if (highlighted && e.relation && this.scale > 0.55) {
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          ctx.font = "600 10px Pretendard, sans-serif";
          ctx.fillStyle = isDark ? "#cbd5e1" : "#334155";
          ctx.textAlign = "center";
          ctx.fillText(e.relation.slice(0, 18), mx, my - 3);
        }
      });

      // 2. 노드 그리기
      this.nodes.forEach((n) => {
        if (this.hiddenGroups.has(n.group)) return;
        const matchSearch = !this.searchTerm || n.label.toLowerCase().includes(this.searchTerm);
        const dim = (activeId && !neighborSet.has(n.id)) || !matchSearch;
        ctx.globalAlpha = dim ? 0.22 : 1.0;

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = n.color;
        ctx.fill();

        ctx.lineWidth = n.id === this.selectedId ? 3.2 : 1.8;
        ctx.strokeStyle = n.id === this.selectedId ? "#facc15" : (isDark ? "#0f172a" : "#ffffff");
        ctx.stroke();

        // 라벨 표시 (중요 노드, 줌인 상태, 또는 선택·검색 매치 시)
        const showLabel = n.group === "topic" || n.group === "keyword" || n.id === activeId || (this.searchTerm && matchSearch) || this.scale >= 0.72;
        if (showLabel) {
          const shortLbl = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
          ctx.font = (n.group === "topic" ? "700 12.5px " : "600 10.5px ") + "Pretendard, sans-serif";
          ctx.fillStyle = isDark ? "#f1f5f9" : "#0f172a";
          ctx.textAlign = "center";
          ctx.fillText(shortLbl, n.x, n.y + n.r + 13);
        }
      });

      ctx.globalAlpha = 1.0;
      ctx.restore();
    }
  }

  window.SMCKnowledgeGraph = SMCKnowledgeGraph;
})();
