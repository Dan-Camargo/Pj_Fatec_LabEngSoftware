"use strict";

/* ======================================================================
   AlgoViz — front-end (vanilla JS, sem frameworks)

   Organização: um "módulo" por aba do site.
   - Sort    : aba Ordenação (um algoritmo por vez)
   - Race    : aba Corrida   (dois algoritmos no mesmo vetor)
   - Search  : aba Busca Binária
   - Grid    : aba Grafos/Caminhos (BFS, DFS, A*)
   - History : aba Histórico (lê o PostgreSQL)
   - Auth    : login/cadastro no cabeçalho

   O back-end não manda "frames prontos": ele devolve a lista de OPERAÇÕES
   executadas pelo algoritmo (comparar i,j / trocar i,j / escrever v em i...).
   O motor aqui embaixo reproduz essas operações na tela — por isso dá para
   pausar, avançar passo a passo e controlar a velocidade.
   ====================================================================== */

/* ============================== utilidades ============================== */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4200);
}

async function api(url, opts = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let body = {};
  try { body = await resp.json(); } catch (_) {}
  if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
  return body;
}

const fmtInt = n => Number(n ?? 0).toLocaleString("pt-BR");

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

// Cor determinística por usuário: o mesmo nome sempre recebe a mesma cor,
// com variedade entre pessoas (usada nos autores de posts e comentários).
const authorPalette = [
  "#0d6b38", "#b3472e", "#6b4fd8", "#c2457a", "#0f6d9e",
  "#7a5d00", "#2f8f5b", "#a03a9e", "#d0561a", "#3b5fd8",
  "#8a5a2b", "#7a1f6e",
];
function authorColor(name) {
  let h = 7;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return authorPalette[h % authorPalette.length];
}

// Vetor aleatório de valores 5..100 usado nas abas Ordenação e Corrida
function randomArray(n) {
  return Array.from({ length: n }, () => 5 + Math.floor(Math.random() * 96));
}

/* ================================ abas ================================== */
$$("#tabs button").forEach(btn =>
  btn.addEventListener("click", () => {
    $$("#tabs button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".tab").forEach(t => t.classList.remove("active"));
    $("#tab-" + btn.dataset.tab).classList.add("active");

    // Abas que buscam dados sob demanda carregam na primeira abertura
    if (btn.dataset.tab === "history") History.load();
    if (btn.dataset.tab === "community") Feed.load();
  })
);

/* ============================== metadados =============================== */
let META = { sorting: [], search: [], path: [] };

function algoCard(list, id) {
  const a = list.find(x => x.id === id);
  if (!a) return "";
  return `<b>${a.name}</b><br>${a.desc}
    <br><small>Melhor <b class="cx">${a.best}</b> · Médio <b class="cx">${a.avg || a.best}</b> · Pior <b class="cx">${a.worst}</b> · Espaço <b class="cx">${a.space}</b></small>`;
}

/* ========================================================================
   MOTOR DE ANIMAÇÃO DE ORDENAÇÃO
   Um "estado" guarda o vetor atual + os elementos DOM das barras.
   applySortOp() aplica UMA operação recebida do back-end. É compartilhado
   entre as abas Ordenação e Corrida de propósito: mesma regra visual nos
   dois lugares.
   ======================================================================== */
const OP_CLASS = { c: "cmp", s: "swp", w: "wrt" }; // tipo de op -> classe CSS

function newState(barsEl) {
  return { values: [], ops: [], idx: 0, barsEl, transient: [], pivot: null };
}

function applySortOp(st, op) {
  const bars = st.barsEl.children;

  // As cores de comparação/troca/escrita duram só até a próxima operação;
  // "done" (verde) e pivô (roxo) são permanentes até o reinício.
  st.transient.forEach(el => el.classList.remove("cmp", "swp", "wrt"));
  st.transient = [];

  if (op.t === "c") {                    // comparar posições a e b
    bars[op.a].classList.add("cmp");
    bars[op.b].classList.add("cmp");
    st.transient.push(bars[op.a], bars[op.b]);
  } else if (op.t === "s") {             // trocar os valores de a e b
    [st.values[op.a], st.values[op.b]] = [st.values[op.b], st.values[op.a]];
    const max = Math.max(...st.values, 1);
    bars[op.a].style.height = (st.values[op.a] / max * 100) + "%";
    bars[op.b].style.height = (st.values[op.b] / max * 100) + "%";
    bars[op.a].title = st.values[op.a];
    bars[op.b].title = st.values[op.b];
    bars[op.a].classList.add("swp");
    bars[op.b].classList.add("swp");
    st.transient.push(bars[op.a], bars[op.b]);
  } else if (op.t === "w") {             // escrever valor v na posição a
    st.values[op.a] = op.v;
    const max = Math.max(...st.values, 1);
    bars[op.a].style.height = (op.v / max * 100) + "%";
    bars[op.a].title = op.v;
    bars[op.a].classList.add("wrt");
    st.transient.push(bars[op.a]);
  } else if (op.t === "p") {             // novo pivô (quick sort)
    if (st.pivot) st.pivot.classList.remove("piv");
    st.pivot = bars[op.a];
    st.pivot.classList.add("piv");
  } else if (op.t === "d") {             // posição a está definitivamente ordenada
    bars[op.a].classList.remove("cmp", "swp", "wrt");
    bars[op.a].classList.add("done");
  }
}

// Redesenha todas as barras a partir de st.values (usado ao embaralhar/reiniciar)
function repaintBars(st) {
  const max = Math.max(...st.values, 1);
  $$(".bar", st.barsEl).forEach((el, i) => {
    el.className = "bar";
    el.style.height = (st.values[i] / max * 100) + "%";
    el.title = st.values[i];
  });
  st.pivot = null;
  st.transient = [];
}

// Cria as <div>s de barra para o vetor informado dentro do container
function buildBars(container, values) {
  container.innerHTML = "";
  const max = Math.max(...values, 1);
  values.forEach(v => {
    const d = document.createElement("div");
    d.className = "bar";
    d.style.height = (v / max * 100) + "%";
    d.title = v;
    container.appendChild(d);
  });
}

/* ============================== ORDENAÇÃO =============================== */
const Sort = {
  st: newState($("#bars")),
  playing: false, timer: null, savedId: null,
  _generating: false,

  algo() { return $("#sort-algo").value; },
  speedOps() { const s = +$("#speed").value; return Math.max(1, Math.round((s / 15) ** 2)); },

  randomize(n) {
    this.st.values = randomArray(n);   // initial guarda o vetor original p/ reiniciar
    this.st.initial = [...this.st.values];
    buildBars(this.st.barsEl, this.st.values);
  },

  updateStats(c) {
    $("#st-cmp").textContent = fmtInt(c.comparisons);
    $("#st-swp").textContent = fmtInt(c.swaps);
    $("#st-ms").textContent = c.elapsed_ms + " ms";
    $("#st-ops").textContent = fmtInt(this.st.ops.length);
  },

  async generate() {
    try {
      const res = await api("/api/sort", {
        method: "POST",
        body: JSON.stringify({ algorithm: this.algo(), values: this.st.initial }),
      });
      this.st.ops = res.ops;
      this.lastStats = res.stats;
      this.savedId = null;
      this.updateStats(res.stats);
      this.reset();
      return true;
    } catch (e) { toast(e.message, true); return false; }
  },

  reset() {
    this.pause();
    this.st.values = [...this.st.initial];
    this.st.idx = 0;
    repaintBars(this.st);
  },

  pause() {
    this.playing = false;
    clearTimeout(this.timer);
    $("#btn-play").classList.remove("hidden");
    $("#btn-pause").classList.add("hidden");
  },

  async play() {
    if (!this.st.ops.length && !(await this.generate())) return;
    if (this.st.idx >= this.st.ops.length) this.reset();
    this.playing = true;
    $("#btn-play").classList.add("hidden");
    $("#btn-pause").classList.remove("hidden");
    this.tick();
  },

  tick() {
    if (!this.playing) return;
    const k = this.speedOps();           // quantas operações por "quadro"
    for (let i = 0; i < k && this.st.idx < this.st.ops.length; i++) {
      applySortOp(this.st, this.st.ops[this.st.idx++]);
    }
    if (this.st.idx >= this.st.ops.length) { this.finish(); return; }
    this.timer = setTimeout(() => this.tick(), 25);
  },

  async stepOne() {
    if (this.playing) this.pause();
    if (!this.st.ops.length) {
      if (this._generating) return;
      this._generating = true;
      const ok = await this.generate();
      this._generating = false;
      if (!ok) return;
    }
    if (this.st.idx >= this.st.ops.length) this.reset();
    applySortOp(this.st, this.st.ops[this.st.idx++]);
    if (this.st.idx >= this.st.ops.length) this.finish();
  },

  async finish() {
    this.pause();
    $$(".bar", this.st.barsEl).forEach(el => el.classList.add("done"));
    // Registra a execução no banco (uma única vez por execução)
    if (this.savedId === null && this.lastStats) {
      const s = this.lastStats;
      this.savedId = await History.postRun({
        algorithm: this.algo(), category: "sorting",
        input_size: this.st.initial.length,
        comparisons: s.comparisons, swaps: s.swaps, elapsed_ms: s.elapsed_ms,
      });
      if (this.savedId) toast(`Ordenação concluída ✓ Execução #${this.savedId} salva no PostgreSQL.`);
    }
  },

  fillInfo() { $("#algo-info").innerHTML = algoCard(META.sorting, this.algo()); },
};

$("#size").addEventListener("input", e => $("#size-out").textContent = e.target.value);
$("#speed").addEventListener("input", e => $("#speed-out").textContent = e.target.value);
$("#size").addEventListener("change", () => {
  Sort.pause(); Sort.randomize(+$("#size").value); Sort.st.ops = [];
});
$("#sort-algo").addEventListener("change", () => { Sort.fillInfo(); Sort.st.ops = []; });
$("#btn-shuffle").addEventListener("click", () => {
  Sort.pause(); Sort.randomize(+$("#size").value); Sort.st.ops = [];
});
$("#btn-play").addEventListener("click", () => Sort.play());
$("#btn-pause").addEventListener("click", () => Sort.pause());
$("#btn-step").addEventListener("click", () => Sort.stepOne());
$("#btn-reset").addEventListener("click", () => Sort.reset());
$("#btn-apply-custom").addEventListener("click", () => {
  const vals = $("#custom-array").value.split(/[,\s]+/).filter(Boolean).map(Number);
  if (!vals.length || vals.some(Number.isNaN)) { toast("Vetor inválido.", true); return; }
  if (vals.length > 200) { toast("Máximo de 200 elementos.", true); return; }
  Sort.pause();
  Sort.st.values = [...vals]; Sort.st.initial = [...vals]; Sort.st.ops = [];
  buildBars(Sort.st.barsEl, vals);
  $("#size").value = vals.length; $("#size-out").textContent = vals.length;
});

/* conjuntos salvos */
$("#btn-ds-save").addEventListener("click", async () => {
  const name = $("#ds-name").value.trim();
  if (!name) { toast("Dê um nome ao conjunto.", true); return; }
  try {
    await api("/api/datasets", {
      method: "POST",
      body: JSON.stringify({ name, values: Sort.st.initial, kind: "sort" }),
    });
    $("#ds-name").value = "";
    toast(`Conjunto "${name}" salvo no banco.`);
    Datasets.refresh();
  } catch (e) { toast(e.message, true); }
});

const Datasets = {
  async refresh() {
    try {
      const items = await api("/api/datasets");
      const ul = $("#ds-list");
      ul.innerHTML = "";
      items.forEach(ds => {
        const li = document.createElement("li");
        li.innerHTML =
          `<span>${ds.name}<br><span class="meta">${ds.values.length} itens · ${ds.owner}</span></span>
           <span>
             <button class="ghost small" data-load="${ds.id}">Carregar</button>
             <button class="ghost small" data-del="${ds.id}">✕</button>
           </span>`;
        ul.appendChild(li);
      });
    } catch (e) { toast(e.message, true); }
  },
};

$("#ds-list").addEventListener("click", async e => {
  const loadId = e.target.dataset.load;
  const delId = e.target.dataset.del;
  if (loadId) {
    try {
      const items = await api("/api/datasets");
      const ds = items.find(x => x.id === +loadId);
      if (!ds) return;
      Sort.pause();
      Sort.st.values = ds.values; Sort.st.initial = [...ds.values]; Sort.st.ops = [];
      buildBars(Sort.st.barsEl, ds.values);
      $("#size").value = ds.values.length; $("#size-out").textContent = ds.values.length;
      toast(`"${ds.name}" carregado.`);
    } catch (err) { toast(err.message, true); }
  } else if (delId) {
    try { await api("/api/datasets/" + delId, { method: "DELETE" }); Datasets.refresh(); }
    catch (err) { toast(err.message, true); }
  }
});

/* =============================== CORRIDA ================================
   Dois "lanes" (raias) rodam o MESMO vetor com o MESMO relógio. Como cada
   algoritmo tem uma lista própria de operações, quem tiver menos operações
   totais chega primeiro — vitória determinística, sem sorte.
   ====================================================================== */
const Race = {
  lanes: [], timer: null, playing: false, savedRuns: false,

  speedOps() { const s = +$("#race-speed").value; return Math.max(1, Math.round((s / 15) ** 2)); },
  verdictBox() { return $("#race-verdict"); },

  makeLane(laneEl, algo) {
    const lane = {
      el: laneEl, algo,
      st: newState($(".bars-mini", laneEl)),
      stats: null, doneAt: null,
    };
    return lane;
  },

  newVector() {
    this.stop();
    const n = +$("#race-size").value;
    const values = randomArray(n);
    this.lanes = [
      this.makeLane($("#lane-a"), $("#race-algo-a").value),
      this.makeLane($("#lane-b"), $("#race-algo-b").value),
    ];
    this.lanes.forEach(lane => {
      lane.st.values = [...values];
      lane.st.initial = [...values];
      buildBars(lane.st.barsEl, values);
      $(".lane-title", lane.el).firstChild.textContent =
        META.sorting.find(a => a.id === lane.algo).name + " ";
      this.updateLane(lane);
    });
    $(".badge-win", $("#lane-a"))?.remove();
    $(".badge-win", $("#lane-b"))?.remove();
    this.verdictBox().classList.add("hidden");
  },

  async run() {
    const base = this.lanes[0]?.st.initial;
    if (!base) { this.newVector(); return this.run(); }
    // Pede ao servidor a trilha de operações dos dois algoritmos.
    // Promise.all dispara as duas requisições em paralelo.
    try {
      const results = await Promise.all(this.lanes.map(lane =>
        api("/api/sort", {
          method: "POST",
          body: JSON.stringify({ algorithm: lane.algo, values: base }),
        })
      ));
      results.forEach((res, i) => {
        this.lanes[i].st.ops = res.ops;
        this.lanes[i].stats = res.stats;
        this.lanes[i].st.idx = 0;
        this.lanes[i].st.values = [...base];
        this.lanes[i].doneAt = null;
        repaintBars(this.lanes[i].st);
      });
    } catch (e) { toast(e.message, true); return; }

    this.savedRuns = false;
    this.playing = true;
    $("#btn-race-run").classList.add("hidden");
    $("#btn-race-pause").classList.remove("hidden");
    this.tick();
  },

  tick() {
    if (!this.playing) return;
    const k = this.speedOps();
    for (const lane of this.lanes) {
      for (let i = 0; i < k && lane.doneAt === null; i++) {
        if (lane.st.idx >= lane.st.ops.length) { lane.doneAt = Date.now(); break; }
        applySortOp(lane.st, lane.st.ops[lane.st.idx++]);
      }
      this.updateLane(lane);
      if (lane.doneAt !== null && !lane.el.dataset.finished) {
        lane.el.dataset.finished = "1";   // marca barras em verde uma vez só
        $$(".bar", lane.st.barsEl).forEach(el => el.classList.add("done"));
      }
    }
    if (this.lanes.every(l => l.doneAt !== null)) { this.finish(); return; }
    this.timer = setTimeout(() => this.tick(), 25);
  },

  updateLane(lane) {
    $(".lc", lane.el).textContent = fmtInt(lane.stats ? lane.stats.comparisons : 0);
    $(".ls", lane.el).textContent = fmtInt(lane.stats ? lane.stats.swaps : 0);
    const total = lane.st.ops.length || 1;
    $(".lp", lane.el).textContent = Math.min(100, Math.round(lane.st.idx / total * 100)) + "%";
  },

  finish() {
    this.stop();
    const [a, b] = this.lanes;
    const opsA = a.st.ops.length, opsB = b.st.ops.length;

    // Vencedor = menos operações totais (mesma velocidade para ambos)
    let msg;
    if (opsA === opsB) {
      msg = `🤝 Empate técnico! Ambos usaram ${fmtInt(opsA)} operações.`;
    } else {
      const win = opsA < opsB ? a : b;
      const lose = opsA < opsB ? b : a;
      $(".lane-title", win.el).insertAdjacentHTML(
        "beforeend", '<span class="badge-win">VENCEDOR 🏆</span>');
      const diff = (1 - win.st.ops.length / lose.st.ops.length) * 100;
      msg = `🏆 <b>${META.sorting.find(x => x.id === win.algo).name}</b> venceu: ` +
            `${fmtInt(win.st.ops.length)} contra ${fmtInt(lose.st.ops.length)} operações ` +
            `(${diff.toFixed(0)}% menos trabalho neste vetor).`;
    }
    this.verdictBox().innerHTML = msg;
    this.verdictBox().classList.remove("hidden");

    // Cada lado da corrida é uma execução real -> vai para o histórico
    if (!this.savedRuns) {
      this.savedRuns = true;
      for (const lane of this.lanes) {
        History.postRun({
          algorithm: lane.algo, category: "sorting",
          input_size: lane.st.initial.length,
          comparisons: lane.stats.comparisons, swaps: lane.stats.swaps,
          elapsed_ms: lane.stats.elapsed_ms,
        });
      }
    }
  },

  stop() {
    this.playing = false;
    clearTimeout(this.timer);
    delete $("#lane-a").dataset.finished;
    delete $("#lane-b").dataset.finished;
    $("#btn-race-run").classList.remove("hidden");
    $("#btn-race-pause").classList.add("hidden");
  },
};

$("#race-size").addEventListener("input", e => $("#rsize-out").textContent = e.target.value);
$("#race-speed").addEventListener("input", e => $("#rspeed-out").textContent = e.target.value);
$("#btn-race-new").addEventListener("click", () => Race.newVector());
$("#btn-race-run").addEventListener("click", () => Race.run());
$("#btn-race-pause").addEventListener("click", () => { Race.stop(); });

/* ============================ BUSCA BINÁRIA ============================= */
const Search = {
  values: [], ops: [], idx: 0, timer: null,

  // Gera números estritamente crescentes => já vem ordenado para a busca
  randomize(n) {
    let v = 2 + Math.floor(Math.random() * 5);
    this.values = Array.from({ length: n }, () => (v += 2 + Math.floor(Math.random() * 6)));
  },

  build() {
    const box = $("#cells");
    box.innerHTML = "";
    this.values.forEach(v => {
      const c = document.createElement("div");
      c.className = "cell";
      c.textContent = v;
      box.appendChild(c);
    });
    $("#ss-res").textContent = "–"; $("#ss-cmp").textContent = "–"; $("#ss-ms").textContent = "–";
  },

  pickTarget() {
    $("#target").value = this.values[Math.floor(Math.random() * this.values.length)];
  },

  async play() {
    const target = parseInt($("#target").value, 10);
    if (Number.isNaN(target)) { toast("Escolha um alvo.", true); return; }
    let res;
    try {
      res = await api("/api/search", {
        method: "POST",
        body: JSON.stringify({ values: this.values, target }),
      });
    } catch (e) { toast(e.message, true); return; }
    clearTimeout(this.timer);
    this.ops = res.ops; this.idx = 0;
    $("#ss-cmp").textContent = fmtInt(res.stats.comparisons);
    $("#ss-ms").textContent = res.stats.elapsed_ms + " ms";
    this.animate(res.found_index, target, res.stats);
  },

  animate(foundIdx, target, st) {
    const cells = $$("#cells .cell");
    let inRange = [];
    const step = () => {
      if (inRange.length) { inRange.forEach(c => c.classList.remove("in-range", "mid")); inRange = []; }
      if (this.idx >= this.ops.length) {
        $("#ss-res").textContent = foundIdx >= 0 ? `encontrado em [${foundIdx}]` : "não encontrado";
        History.postRun({
          algorithm: "binary", category: "search",
          input_size: this.values.length,
          comparisons: st.comparisons, swaps: 0, elapsed_ms: st.elapsed_ms,
        }).then(id => id && toast(`Busca concluída ✓ Execução #${id} salva.`));
        return;
      }
      const op = this.ops[this.idx++];
      if (op.t === "r") {          // novo intervalo ativo lo..hi
        for (let i = op.a; i <= op.b; i++) { cells[i].classList.add("in-range"); inRange.push(cells[i]); }
      } else if (op.t === "m") {   // ponteiro do meio
        cells[op.a].classList.add("mid"); inRange.push(cells[op.a]);
      } else if (op.t === "f") {   // encontrado
        inRange.forEach(c => c.classList.remove("mid"));
        inRange = [];
        cells[op.a].classList.add("found");
      }
      this.timer = setTimeout(step, 380);
    };
    step();
  },
};

$("#search-size").addEventListener("input", e => $("#ssize-out").textContent = e.target.value);
$("#search-size").addEventListener("change", () => {
  clearTimeout(Search.timer); Search.randomize(+$("#search-size").value); Search.build(); Search.pickTarget();
});
$("#btn-search-gen").addEventListener("click", () => {
  clearTimeout(Search.timer); Search.randomize(+$("#search-size").value); Search.build(); Search.pickTarget();
});
$("#btn-search-target").addEventListener("click", () => Search.pickTarget());
$("#btn-search-play").addEventListener("click", () => Search.play());

/* =========================== GRAFOS · CAMINHOS ========================== */
const Grid = {
  rows: 16, cols: 34,
  walls: new Set(),          // chaves "linha,coluna" das paredes desenhadas
  start: [8, 4], end: [8, 29],
  dragging: null, animating: false,

  key(r, c) { return r + "," + c; },

  build(rows, cols) {
    this.rows = rows; this.cols = cols;
    this.walls.clear();
    this.start = [Math.floor(rows / 2), Math.max(1, Math.floor(cols * 0.12))];
    this.end = [Math.floor(rows / 2), Math.min(cols - 2, Math.floor(cols * 0.85))];
    const g = $("#grid");
    const cell = window.innerWidth <= 600 ? 22 : 28;   // células menores no mobile
    g.style.setProperty("--cell", cell + "px");
    g.style.gridTemplateColumns = `repeat(${cols}, ${cell}px)`;
    g.innerHTML = "";
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++) {
        const n = document.createElement("div");
        n.className = "node";
        n.dataset.r = r; n.dataset.c = c;
        g.appendChild(n);
      }
    this.paintMarkers();
  },

  el(r, c) { return $(`.node[data-r="${r}"][data-c="${c}"]`, $("#grid")); },

  paintMarkers() {
    $$(".node.start,.node.end", $("#grid")).forEach(n => n.classList.remove("start", "end"));
    this.el(...this.start)?.classList.add("start");
    this.el(...this.end)?.classList.add("end");
  },

  onDown(e) {
    const n = e.target.closest(".node");
    if (!n || this.animating) return;
    e.preventDefault();
    const r = +n.dataset.r, c = +n.dataset.c;
    if (n.classList.contains("start")) this.dragging = { type: "start" };
    else if (n.classList.contains("end")) this.dragging = { type: "end" };
    else {
      const erase = n.classList.contains("wall");  // 1º clique apaga se já é parede
      this.dragging = { type: "wall", erase };
      this.setWall(r, c, !erase);
    }
  },

  onOver(e) {
    const n = e.target.closest(".node");
    if (!n || !this.dragging || this.animating) return;
    const r = +n.dataset.r, c = +n.dataset.c;
    if (this.dragging.type === "wall") {
      this.setWall(r, c, !this.dragging.erase);
    } else if (this.dragging.type === "start") {
      if (this.walls.has(this.key(r, c)) || (r === this.end[0] && c === this.end[1])) return;
      this.start = [r, c]; this.paintMarkers();
    } else if (this.dragging.type === "end") {
      if (this.walls.has(this.key(r, c)) || (r === this.start[0] && c === this.start[1])) return;
      this.end = [r, c]; this.paintMarkers();
    }
  },

  // Toque (mobile): espelha o comportamento do mouse para desenhar
  // paredes e arrastar os marcadores início/destino.
  onTouchStart(e) {
    const t = e.changedTouches[0];
    const n = document.elementFromPoint(t.clientX, t.clientY);
    if (!n) return;
    this.onDown({ target: n, preventDefault: () => e.preventDefault() });
  },

  onTouchMove(e) {
    if (!this.dragging) return;
    e.preventDefault();
    const t = e.changedTouches[0];
    const n = document.elementFromPoint(t.clientX, t.clientY);
    if (!n) return;
    this.onOver({ target: n });
  },

  setWall(r, c, on) {
    if ((r === this.start[0] && c === this.start[1]) ||
        (r === this.end[0] && c === this.end[1])) return;
    if (on) this.walls.add(this.key(r, c)); else this.walls.delete(this.key(r, c));
    this.el(r, c)?.classList.toggle("wall", on);
    this.el(r, c)?.classList.remove("visited", "path");
  },

  clearWalls() {
    this.walls.clear();
    $$(".node.wall", $("#grid")).forEach(n => n.classList.remove("wall"));
  },

  cleanSolve() {
    $$(".node.visited,.node.path", $("#grid")).forEach(n => n.classList.remove("visited", "path"));
  },

  maze() {
    this.clearWalls();
    for (let r = 0; r < this.rows; r++)
      for (let c = 0; c < this.cols; c++) {
        if (Math.random() < 0.28 &&
            !(r === this.start[0] && c === this.start[1]) &&
            !(r === this.end[0] && c === this.end[1]))
          this.walls.add(this.key(r, c));
      }
    $$(".node", $("#grid")).forEach(n =>
      n.classList.toggle("wall", this.walls.has(this.key(+n.dataset.r, +n.dataset.c)))
    );
  },

  async solve() {
    if (this.animating) return;
    let res;
    try {
      res = await api("/api/path", {
        method: "POST",
        body: JSON.stringify({
          rows: this.rows, cols: this.cols,
          walls: [...this.walls].map(k => k.split(",").map(Number)),
          start: this.start, end: this.end,
          algorithm: $("#path-algo").value,
        }),
      });
    } catch (e) { toast(e.message, true); return; }

    this.cleanSolve();
    this.animating = true;
    $("#ps-vis").textContent = fmtInt(res.visited.length);
    $("#ps-len").textContent = res.path.length ? fmtInt(res.path.length) : "—";
    $("#ps-ms").textContent = res.stats.elapsed_ms + " ms";

    // Animação em duas fases: primeiro todas as células visitadas, depois o caminho
    const batch = Math.max(2, Math.round(res.visited.length / 90));
    let vi = 0, pi = 0;
    const tickVis = () => {
      for (let i = 0; i < batch && vi < res.visited.length; i++, vi++) {
        const [r, c] = res.visited[vi];
        if (!(r === this.start[0] && c === this.start[1]) && !(r === this.end[0] && c === this.end[1]))
          this.el(r, c)?.classList.add("visited");
      }
      if (vi < res.visited.length) setTimeout(tickVis, 14);
      else setTimeout(tickPath, 120);
    };
    const tickPath = () => {
      if (pi >= res.path.length) {
        this.animating = false;
        if (!res.path.length) {
          toast("Destino inalcançável ✗", true);
        } else {
          History.postRun({
            algorithm: $("#path-algo").value, category: "path",
            input_size: this.rows * this.cols,
            comparisons: res.visited.length, swaps: res.path.length,
            elapsed_ms: res.stats.elapsed_ms,
          }).then(id => id && toast(`Caminho encontrado ✓ Execução #${id} salva.`));
        }
        return;
      }
      const [r, c] = res.path[pi++];
      if (!(r === this.start[0] && c === this.start[1]) && !(r === this.end[0] && c === this.end[1]))
        this.el(r, c)?.classList.add("path");
      setTimeout(tickPath, 26);
    };
    if (!res.visited.length) { this.animating = false; toast("Nada para explorar.", true); return; }
    tickVis();
  },

  fillInfo() { $("#path-info").innerHTML = algoCard(META.path, $("#path-algo").value); },
};

const gridBox = $("#grid");
gridBox.addEventListener("mousedown", e => Grid.onDown(e));
gridBox.addEventListener("mouseover", e => { if (e.buttons & 1) Grid.onOver(e); });
document.addEventListener("mouseup", () => Grid.dragging = null);
gridBox.addEventListener("touchstart", e => Grid.onTouchStart(e), { passive: false });
gridBox.addEventListener("touchmove", e => Grid.onTouchMove(e), { passive: false });
document.addEventListener("touchend", () => Grid.dragging = null);
document.addEventListener("touchcancel", () => Grid.dragging = null);

$("#path-algo").addEventListener("change", () => Grid.fillInfo());
$("#btn-grid-rebuild").addEventListener("click", () => {
  const rows = Math.min(26, Math.max(6, +$("#grid-rows").value || 16));
  const cols = Math.min(46, Math.max(8, +$("#grid-cols").value || 34));
  $("#grid-rows").value = rows; $("#grid-cols").value = cols;
  Grid.cleanSolve(); Grid.build(rows, cols);
});
$("#btn-maze").addEventListener("click", () => { Grid.cleanSolve(); Grid.maze(); });
$("#btn-clear-walls").addEventListener("click", () => { Grid.cleanSolve(); Grid.clearWalls(); });
$("#btn-solve").addEventListener("click", () => Grid.solve());

/* =============================== HISTÓRICO ============================== */
const History = {
  async postRun(payload) {
    try {
      const res = await api("/api/runs", { method: "POST", body: JSON.stringify(payload) });
      return res.id;
    } catch (e) { toast(e.message, true); return null; }
  },

  async load() {
    try {
      const mine = $("#hist-scope").value === "mine" && Auth.user;
      const url = "/api/runs?limit=30" + (mine ? "&mine=1" : "");
      const [stats, runs] = await Promise.all([api("/api/stats"), api(url)]);
      $("#h-total").textContent = fmtInt(stats.total_runs);
      $("#h-items").textContent = fmtInt(stats.total_items);
      $("#h-algos").textContent = stats.by_algorithm.length;

      // Tabela 1: média por algoritmo (visão global, sempre)
      let html = "<tr><th>Algoritmo</th><th>Categoria</th><th>Execuções</th><th>n médio</th>" +
        "<th>Comparações</th><th>Trocas</th><th>Tempo médio</th></tr>";
      stats.by_algorithm.forEach(a => {
        html += `<tr><td><b>${a.algorithm}</b></td><td>${a.category}</td>` +
          `<td>${fmtInt(a.runs)}</td><td>${fmtInt(a.n_avg)}</td><td>${fmtInt(a.cmp_avg)}</td>` +
          `<td>${fmtInt(a.swp_avg)}</td><td>${a.ms_avg} ms</td></tr>`;
      });
      if (!stats.by_algorithm.length)
        html += '<tr><td colspan="7">Nenhuma execução ainda — rode um algoritmo! 🎬</td></tr>';
      $("#tbl-stats").innerHTML = html;

      // Tabela 2: últimas execuções (global ou só do usuário logado)
      html = "<tr><th>#</th><th>Algoritmo</th><th>Categoria</th><th>Usuário</th><th>n</th>" +
        "<th>Comparações</th><th>Trocas</th><th>Tempo</th><th>Quando</th></tr>";
      runs.forEach(r => {
        html += `<tr><td>${r.id}</td><td><b>${r.algorithm}</b></td><td>${r.category}</td>` +
          `<td>${r.user}</td><td>${fmtInt(r.input_size)}</td><td>${fmtInt(r.comparisons)}</td>` +
          `<td>${fmtInt(r.swaps)}</td><td>${r.elapsed_ms} ms</td>` +
          `<td>${new Date(r.created_at).toLocaleString("pt-BR")}</td></tr>`;
      });
      if (!runs.length)
        html += '<tr><td colspan="9">Sem registros.</td></tr>';
      $("#tbl-runs").innerHTML = html;
    } catch (e) { toast(e.message, true); }
  },
};
$("#btn-refresh-hist").addEventListener("click", () => History.load());
$("#hist-scope").addEventListener("change", () => History.load());

/* ============================== COMUNIDADE =============================
   Feed/blog: admins escrevem posts; usuários logados curtem e comentam.
   Três camadas aqui: lista (feed), detalhe do post e o painel de admins
   (modal) para criar/promover/rebaixar administradores.
   ====================================================================== */
const Feed = {
  view: "list",            // "list" ou "post"
  postId: null, post: null,
  editId: null,

  get admin() { return Auth.user && Auth.user.role === "Admin"; },

  async load() {
    if (!Auth.user) {                       // feed é exclusivo de logados
      this.view = "list";
      $("#feed-title").textContent = "Comunidade";
      $("#feed-back").classList.add("hidden");
      $("#feed-admin-actions").classList.add("hidden");
      $("#feed-content").innerHTML =
        '<p class="hint">🔒 Entre com sua conta para acessar a comunidade.</p>';
      return;
    }
    if (this.view === "post" && this.postId) return this.openPost(this.postId);
    return this.loadList();
  },

  async loadList() {
    try {
      const { posts } = await api("/api/posts");
      this.view = "list";
      this.postId = null;
      $("#feed-title").textContent = "Comunidade";
      $("#feed-back").classList.add("hidden");
      $("#feed-admin-actions").classList.toggle("hidden", !this.admin);
      const box = $("#feed-content");
      box.innerHTML = "";
      if (!posts.length) {
        box.innerHTML = `<p class="hint">Nenhum post ainda. ` +
          (this.admin ? "Clique em <b>Nova postagem</b> para publicar! ✍" 
            : "Os administradores em breve publicarão por aqui.") + `</p>`;
        return;
      }
      const nl2br = s => escapeHtml(s).replace(/\n/g, "<br>");
      posts.forEach(p => {
        const a = document.createElement("article");
        a.className = "feed-post";
        a.dataset.open = p.id;
        a.innerHTML = `
          <h3 class="feed-post-title">${escapeHtml(p.title)}</h3>
          <p class="feed-post-excerpt">${nl2br(p.excerpt)}</p>
          <div class="feed-post-meta">
            <span class="feed-author" style="color:${authorColor(p.author.username)}">👤 ${escapeHtml(p.author.username)}</span>
            <span>🕒 ${new Date(p.created_at).toLocaleString("pt-BR")}</span>
            <button class="ghost small" data-like="${p.id}" title="Curtir">
              ${p.liked_by_me ? "❤" : "🤍"} <b>${fmtInt(p.like_count)}</b>
            </button>
            <span title="Comentários">💬 ${fmtInt(p.comment_count)}</span>
          </div>`;
        box.appendChild(a);
      });
    } catch (e) { toast(e.message, true); }
  },

  async openPost(id) {
    try {
      const post = await api("/api/posts/" + id);
      this.post = post; this.postId = id; this.view = "post";
      $("#feed-title").textContent = "Post";
      $("#feed-back").classList.remove("hidden");
      $("#feed-admin-actions").classList.toggle("hidden", !this.admin);
      $("#feed-content").innerHTML = this.postHTML(post);
    } catch (e) { toast(e.message, true); }
  },

  postHTML(p) {
    const nl2br = s => escapeHtml(s).replace(/\n/g, "<br>");
    const mine = c => c.author.id === (Auth.user && Auth.user.id);
    return `
      <article class="feed-post detail" data-id="${p.id}">
        <h2 class="feed-post-title">${escapeHtml(p.title)}</h2>
        <div class="feed-post-meta">
          <span class="feed-author" style="color:${authorColor(p.author.username)}">👤 ${escapeHtml(p.author.username)}</span>
          <span>🕒 ${new Date(p.created_at).toLocaleString("pt-BR")}</span>
        </div>
        <div class="feed-post-body">${nl2br(p.body)}</div>
        ${this.admin ? `
          <div class="btn-row">
            <button class="ghost small" data-edit-post="${p.id}">✏ Editar</button>
            <button class="ghost small danger" data-del-post="${p.id}">🗑 Excluir</button>
          </div>` : ""}
        <div class="feed-actions">
          <button class="ghost small" data-like="${p.id}">
            ${p.liked_by_me ? "❤ Curtido" : "🤍 Curtir"} · <b>${fmtInt(p.like_count)}</b>
          </button>
          <span class="hint">${fmtInt(p.comment_count)} comentário(s)</span>
        </div>
        <h3 class="feed-h3">Comentários</h3>
        <div class="feed-comments">
          ${p.comments.length ? p.comments.map(c => `
            <div class="feed-comment">
              <b style="color:${authorColor(c.author.username)}">${escapeHtml(c.author.username)}</b>
              <span class="hint">${new Date(c.created_at).toLocaleString("pt-BR")}</span>
              ${(mine(c) || this.admin) ? `
                <button class="ghost small" data-del-c="${c.id}" title="Excluir">✕</button>` : ""}
              <p>${nl2br(c.body)}</p>
            </div>`).join("") : `<p class="hint">Seja o primeiro a comentar! 💬</p>`}
        </div>
        <form id="comment-form">
          <label class="feed-label">Comentar
            <textarea id="comment-body" rows="3" maxlength="1000"
              placeholder="escreva um comentário..."></textarea>
          </label>
          <button type="submit" class="primary small">Comentar ▶</button>
        </form>
      </article>`;
  },

  async like(id) {
    try {
      const r = await api(`/api/posts/${id}/like`, { method: "POST" });
      if (this.view === "post") {
        this.post.like_count = r.like_count;
        this.post.liked_by_me = r.liked;
        const btn = $("#feed-content").querySelector(`[data-like="${id}"]`);
        if (btn) btn.innerHTML = `${r.liked ? "❤ Curtido" : "🤍 Curtir"} · <b>${fmtInt(r.like_count)}</b>`;
      } else {
        await this.loadList();
      }
    } catch (e) { toast(e.message, true); }
  },

  async comment(pid) {
    const body = $("#comment-body").value.trim();
    if (!body) { toast("Escreva um comentário.", true); return; }
    try {
      await api(`/api/posts/${pid}/comments`, {
        method: "POST", body: JSON.stringify({ body }),
      });
      toast("Comentário publicado! 💬");
      await this.openPost(pid);
    } catch (e) { toast(e.message, true); }
  },

  async delComment(pid, cid) {
    if (!confirm("Excluir esse comentário?")) return;
    try {
      await api(`/api/posts/${pid}/comments/${cid}`, { method: "DELETE" });
      toast("Comentário excluído.");
      await this.openPost(pid);
    } catch (e) { toast(e.message, true); }
  },

  openPostEditor(id = null) {
    this.editId = id || null;
    const p = id && this.post && this.post.id === id ? this.post : null;
    $("#post-title").value = p ? p.title : "";
    $("#post-body").value = p ? p.body : "";
    $(".win-title", $("#post-modal")).textContent =
      p ? ":: Editar postagem ::" : ":: Nova postagem ::";
    $("#post-modal").classList.remove("hidden");
    $("#post-title").focus();
  },

  closePostEditor() {
    $("#post-modal").classList.add("hidden");
    this.editId = null;
    $("#post-title").value = "";
    $("#post-body").value = "";
  },

  async savePost() {
    const title = $("#post-title").value.trim();
    const body = $("#post-body").value.trim();
    if (!title) { toast("Dê um título ao post.", true); return; }
    if (!body) { toast("Escreva o conteúdo do post.", true); return; }
    try {
      let id = this.editId;
      if (id) {
        await api(`/api/posts/${id}`, { method: "PUT", body: JSON.stringify({ title, body }) });
        toast("Post atualizado! ✍");
      } else {
        const r = await api("/api/posts", { method: "POST", body: JSON.stringify({ title, body }) });
        id = r.id;
        toast("Post publicado! 🎉");
      }
      this.closePostEditor();
      await this.openPost(id);
    } catch (e) { toast(e.message, true); }
  },

  async delPost(id) {
    if (!confirm("Excluir este post e todos os comentários dele?")) return;
    try {
      await api(`/api/posts/${id}`, { method: "DELETE" });
      toast("Post excluído.");
      this.view = "list";
      await this.loadList();
    } catch (e) { toast(e.message, true); }
  },

  /* ------------------------- gerenciamento de admins ------------------- */
  openAdminModal() {
    $("#adm-search").value = "";
    $("#adm-results").innerHTML = "";
    this.renderAdminList();
    $("#admin-modal").classList.remove("hidden");
  },

  closeAdminModal() {
    $("#admin-modal").classList.add("hidden");
  },

  async renderAdminList() {
    try {
      const { admins } = await api("/api/admins");
      const ul = $("#adm-list");
      ul.innerHTML = "";
      admins.forEach(a => {
        const li = document.createElement("li");
        const self = a.id === (Auth.user && Auth.user.id);
        li.innerHTML = `<span>👑 ${escapeHtml(a.username)} <span class="meta">desde ${new Date(a.created_at).toLocaleDateString("pt-BR")}</span></span>
          <span>${self ? '<span class="hint">você</span>'
            : `<button class="ghost small" data-demote="${a.id}" title="Rebaixar para Aluno">Rebaixar</button>`}</span>`;
        ul.appendChild(li);
      });
    } catch (e) { toast(e.message, true); }
  },

  async createAdmin() {
    const username = $("#adm-user").value.trim();
    const password = $("#adm-pass").value;
    if (!username || !password) { toast("Informe usuário e senha do admin.", true); return; }
    try {
      await api("/api/admins", { method: "POST", body: JSON.stringify({ username, password }) });
      toast(`Admin "${username}" criado! 👑`);
      $("#adm-user").value = "";
      $("#adm-pass").value = "";
      await this.renderAdminList();
    } catch (e) { toast(e.message, true); }
  },

  async promote(uid) {
    try {
      await api("/api/admins", { method: "POST", body: JSON.stringify({ user_id: uid }) });
      toast("Usuário promovido a admin! 👑");
      $("#adm-search").value = "";
      $("#adm-results").innerHTML = "";
      await this.renderAdminList();
    } catch (e) { toast(e.message, true); }
  },

  async demote(uid) {
    if (!confirm("Rebaixar esse administrador para Aluno?")) return;
    try {
      await api("/api/admins/" + uid, { method: "DELETE" });
      toast("Admin rebaixado.");
      await this.renderAdminList();
    } catch (e) { toast(e.message, true); }
  },

  async searchUsers() {
    const q = $("#adm-search").value.trim();
    const box = $("#adm-results");
    if (!q) { box.innerHTML = ""; return; }
    try {
      const { users } = await api("/api/users?q=" + encodeURIComponent(q));
      box.innerHTML = "";
      users.forEach(u => {
        if (u.role === "Admin") return;
        const d = document.createElement("div");
        d.className = "feed-promote";
        d.innerHTML = `<span>${escapeHtml(u.username)} <span class="meta">(${escapeHtml(u.role)})</span></span>
          <button class="ghost small" data-promote="${u.id}">Promover →</button>`;
        box.appendChild(d);
      });
      if (!box.children.length) box.innerHTML = '<p class="hint">Nenhum candidato encontrado.</p>';
    } catch (e) { toast(e.message, true); }
  },
};

/* ------------------------- eventos da comunidade ----------------------- */
$("#feed-back").addEventListener("click", () => { Feed.view = "list"; Feed.loadList(); });
$("#btn-post-novo").addEventListener("click", () => Feed.openPostEditor());
$("#btn-admin-painel").addEventListener("click", () => Feed.openAdminModal());

$("#btn-post-salvar").addEventListener("click", () => Feed.savePost());
$("#btn-post-cancelar").addEventListener("click", () => Feed.closePostEditor());
$("#post-modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) Feed.closePostEditor();
});

$("#btn-adm-criar").addEventListener("click", () => Feed.createAdmin());
$("#btn-adm-fechar").addEventListener("click", () => Feed.closeAdminModal());
$("#admin-modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) Feed.closeAdminModal();
});
$("#adm-search").addEventListener("input", () => Feed.searchUsers());

// Delegação de cliques dentro do conteúdo do feed (lista + detalhe).
$("#feed-content").addEventListener("click", async e => {
  const like = e.target.closest("[data-like]");
  const open = e.target.closest("[data-open]");
  const delC = e.target.closest("[data-del-c]");
  const editP = e.target.closest("[data-edit-post]");
  const delP = e.target.closest("[data-del-post]");
  const promote = e.target.closest("[data-promote]");
  const demote = e.target.closest("[data-demote]");
  if (like) return Feed.like(+like.dataset.like);
  if (open) return Feed.openPost(+open.dataset.open);
  if (delC) return Feed.delComment(Feed.postId, +delC.dataset.delC);
  if (editP) return Feed.openPostEditor(+editP.dataset.editPost);
  if (delP) return Feed.delPost(+delP.dataset.delPost);
  if (promote) return Feed.promote(+promote.dataset.promote);
  if (demote) return Feed.demote(+demote.dataset.demote);
});

$("#feed-content").addEventListener("submit", async e => {
  if (e.target.id === "comment-form") {
    e.preventDefault();
    return Feed.comment(Feed.postId);
  }
});

/* ============================= AUTENTICAÇÃO =============================
   Login simples com cookie de sessão assinado pelo Flask.
   Senhas nunca trafegam de volta: o back-end guarda apenas o hash PBKDF2.
   Logado ou não, TODA funcionalidade continua acessível — o login serve
   para atribuir as execuções do histórico a um usuário.
   ====================================================================== */
const Auth = {
  user: null,

  async refresh() {
    try { this.user = (await api("/api/me")).user; }
    catch (_) { this.user = null; }
    this.render();
    Datasets.refresh();
    if ($("#tab-history").classList.contains("active")) History.load();
    if ($("#tab-community").classList.contains("active")) Feed.load();
  },

  render() {
    const box = $("#auth-box");
    const overlay = $("#login-overlay");
    if (this.user) {
      if (overlay) overlay.classList.add("hidden");
      const badge = this.user.role === "Admin"
        ? '<span class="role-badge" title="Administrador">👑 Admin</span>' : "";
      box.innerHTML = `<span class="hello">👤 ${this.user.username}</span>${badge}` +
        `<button id="btn-logout" class="ghost small">Sair</button>`;
      $("#btn-logout").onclick = async () => {
        try { await api("/api/logout", { method: "POST" }); } catch (_) {}
        this.refresh();
        toast("Você saiu. Até logo!");
      };
      $("#hist-scope").classList.remove("hidden");
    } else {
      if (overlay) overlay.classList.remove("hidden");
      box.innerHTML = "";
      $("#hist-scope").value = "all";
      $("#hist-scope").classList.add("hidden");
    }
  },

  async submit(url, okMsg) {
    const username = $("#overlay-user").value.trim();
    const password = $("#overlay-pass").value;
    if (!username || !password) { toast("Informe usuário e senha.", true); return; }
    try {
      await api(url, { method: "POST", body: JSON.stringify({ username, password }) });
      toast(okMsg);
      await this.refresh();
    } catch (e) { toast(e.message, true); }
  },
};

document.addEventListener("DOMContentLoaded", () => {
  const btnLogin = $("#overlay-btn-login");
  const btnRegister = $("#overlay-btn-register");
  if (btnLogin) btnLogin.onclick = () => Auth.submit("/api/login", "Bem-vindo(a) de volta!");
  if (btnRegister) btnRegister.onclick = () => Auth.submit("/api/register", "Conta criada — você já está logado!");
});

/* =========================== AQUÁRIO ALEATÓRIO ========================== */
// Peixes decorativos: cada um nasce com posição, tamanho, imagem, direção,
// velocidade, opacidade e balanço sorteados, então "mergulham" pelo fundo.
const FISH_SRC = [
  "/static/assets/peixes/fish26.png",
  "/static/assets/peixes/fish20.png",
  "/static/assets/peixes/fish21.png",
];
const FISH_COUNT = 7;

function fishPickImage() {
  const r = Math.random();
  return r < 0.5 ? FISH_SRC[0] : r < 0.85 ? FISH_SRC[1] : FISH_SRC[2];
}

function fishRand(a, b) { return a + Math.random() * (b - a); }

// Velocidade gradual e suave: cada peixe tem uma velocidade-alvo sorteada e a
// velocidade real converge devagar até ela (lerp), re-sorteando o alvo a cada
// poucos segundos — o nado acelera/desacelera naturalmente, sem degraus.
const fishNextRoll = new WeakMap();

function fishTargetSpeed() { return fishRand(16, 64); }

function spawnFish(tank, isBobber) {
  const dir = Math.random() < 0.5 ? 1 : -1;   // +1 nada p/ direita, -1 p/ esquerda

  const fish = document.createElement("div");
  fish.className = "fish";
  fish.style.setProperty("--top", fishRand(4, 86).toFixed(1) + "%");
  fish.style.setProperty("--op", fishRand(0.35, 0.75).toFixed(2));

  const bob = document.createElement("div");
  bob.className = "bob";
  bob.style.setProperty("--bdur", fishRand(4.5, 8.5).toFixed(1) + "s");
  bob.style.setProperty("--bdelay", "-" + fishRand(0, 8).toFixed(1) + "s");

  const inner = document.createElement("div");
  inner.className = "in" + ((isBobber ? Math.random() < 0.5 : dir === -1) ? " flip" : "");
  inner.style.setProperty("--blur", fishRand(0.2, 1.2).toFixed(2) + "px");

  const img = document.createElement("img");
  img.src = fishPickImage();
  img.alt = "";
  img.style.width = fishRand(60, 320).toFixed(0) + "px";

  inner.appendChild(img);
  bob.appendChild(inner);
  fish.appendChild(bob);
  tank.appendChild(fish);

  if (isBobber) {                // paradinho: só balança no lugar
    fish.style.left = fishRand(3, 90).toFixed(1) + "%";
    return null;
  }

  const margin = 40 + parseInt(img.style.width, 10);
  const target = fishTargetSpeed() * dir;
  const swimmer = {
    el: fish, img, dir, margin,
    x: fishRand(-margin, document.documentElement.clientWidth + margin),
    v: target * fishRand(0.4, 1),   // começa em qualquer ritmo
    target,
  };
  fishNextRoll.set(fish, performance.now() + fishRand(3, 10) * 1000);
  return swimmer;
}

function initAquarium() {
  const tank = $("#fish-tank");
  if (!tank) return;

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const swimmers = [];
  for (let i = 0; i < FISH_COUNT; i++) {
    const s = spawnFish(tank, reduced ? true : Math.random() < 0.28);
    if (s) swimmers.push(s);
  }
  if (reduced || !swimmers.length) return;

  let last = performance.now();

  const step = now => {
    const dt = Math.min(0.1, (now - last) / 1000);   // dt em segundos (cap p/ abas inertes)
    last = now;
    const vw = document.documentElement.clientWidth;

    for (const s of swimmers) {
      // re-sorteia o alvo de velocidade (e às vezes o rumo), sempre suave
      if (now > fishNextRoll.get(s.el)) {
        fishNextRoll.set(s.el, now + fishRand(6, 16) * 1000);
        if (Math.random() < 0.18) s.dir = -s.dir;
        s.target = fishTargetSpeed() * s.dir;
      }
      s.v += (s.target - s.v) * Math.min(1, dt * 0.25);   // converge devagar até o alvo
      s.x += s.v * dt;

      // saiu da tela → reaparece do outro lado com topo e rumo novos
      if (s.x > vw + s.margin || s.x < -s.margin) {
        s.x = s.x > vw ? -s.margin : vw + s.margin;
        if (Math.random() < 0.18) s.dir = -s.dir;
        s.target = fishTargetSpeed() * s.dir;
        s.el.style.setProperty("--top", fishRand(4, 86).toFixed(1) + "%");
      }
      s.el.querySelector(".in").classList.toggle("flip", s.dir === -1);
      s.el.style.transform = `translate3d(${s.x.toFixed(1)}px, 0, 0)`;
    }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ================================== boot ================================ */
(async function boot() {
  try { META = await api("/api/meta"); } catch (e) { toast(e.message, true); }

  // Popula os selects de algoritmo (Ordenação e os dois competidores da Corrida)
  const options = META.sorting.map(a => `<option value="${a.id}">${a.name}</option>`).join("");
  $("#sort-algo").innerHTML = options;
  $("#race-algo-a").innerHTML = options;
  $("#race-algo-b").innerHTML = options;
  $("#race-algo-a").value = "merge";     // confronto inicial clássico:
  $("#race-algo-b").value = "bubble";    // O(n log n) contra O(n²)

  Sort.fillInfo();
  $("#search-info").innerHTML = algoCard(META.search, "binary");
  Grid.fillInfo();

  Sort.randomize(+$("#size").value);
  Search.randomize(+$("#search-size").value);
  Search.build();
  Search.pickTarget();
  Grid.build(Grid.rows, Grid.cols);
  Race.newVector();
  Datasets.refresh();
  Auth.refresh();          // descobre se já há sessão ativa e monta o cabeçalho

  // Popula o aquário aleatório ao fundo
  initAquarium();

  // Contador de visitas estilo 2002 (com dados honestos: nº de execuções
  // registradas no PostgreSQL). O elemento só existe se o rodapé existir.
  try {
    const counter = $("#hit-counter");
    if (counter) {
      const s = await api("/api/stats");
      counter.textContent = String(s.total_runs).padStart(6, "0");
    }
  } catch (_) {}
})();
