(() => {
  "use strict";

  const SAMPLE = {
    account_name: "Northwind Payments",
    industry: "Fintech",
    employees: 900,
    deal_value_usd: 95000,
    stage: "Proposal",
    expected_close_days: 70,
    budget_confirmed: true,
    sponsor: "Executive engaged",
    need: "High",
    notes: "Migrating off a legacy vendor before Q4. Needs API latency for payment routing and compliance reporting. VP of Engineering is engaged.",
  };

  // Fields validated in the browser, in tab order. Messages replace the browser tooltip.
  const VALIDATED = [
    { id: "account_name", label: "Account name", kind: "text" },
    { id: "employees", label: "Employees", kind: "integer" },
    { id: "deal_value_usd", label: "Deal value", kind: "positive" },
    { id: "expected_close_days", label: "Expected close", kind: "integer" },
  ];

  const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const decFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
  const moneyFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const fmtInt = (n) => intFmt.format(n);
  const fmtMoney = (n) => moneyFmt.format(n);
  const fmtPct = (n) => `${decFmt.format(n)}%`;

  const el = (id) => document.getElementById(id);
  const form = el("deal-form");
  const evaluateBtn = el("evaluate-btn");
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));

  const state = {
    busy: false,
    optionsReady: false,
    analogues: [],
    selected: -1,
    submitted: null,
  };

  // ---------- Small DOM helpers (text only, never innerHTML) ----------

  function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function badge(text, variant, extraClass) {
    return node("span", `badge badge-${variant}${extraClass ? ` ${extraClass}` : ""}`, text);
  }

  function setStatus(message) {
    el("status").textContent = message;
  }

  function recommendationVariant(recommendation) {
    if (recommendation.startsWith("PURSUE")) return "ok";
    if (recommendation === "QUALIFY_FURTHER") return "warn";
    return "bad";
  }

  function setBar(id, value) {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    el(id).dataset.target = String(pct);
    el(id).style.width = `${pct}%`;
  }

  // ---------- Motion and feedback helpers ----------

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const prefersReduced = () => reduceMotion.matches;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const STEP_MS = 320;

  // Restarts a CSS animation class and staggers siblings through --i.
  function replay(elements, className) {
    elements.forEach((item, i) => {
      item.classList.remove(className);
      item.style.setProperty("--i", String(i));
      void item.offsetWidth;
      item.classList.add(className);
    });
  }

  // Bars restart from empty so they visibly fill. Without motion they simply show the value.
  function animateBars() {
    const bars = Array.from(document.querySelectorAll(".seg-fill"));
    if (prefersReduced()) return;
    bars.forEach((bar) => {
      bar.style.transition = "none";
      bar.style.width = "0%";
    });
    void document.body.offsetWidth;
    bars.forEach((bar) => {
      bar.style.transition = "";
      bar.style.width = `${bar.dataset.target || 0}%`;
    });
  }

  function countUp(target, to, format, duration = 900) {
    cancelAnimationFrame(target._raf);
    if (prefersReduced() || !Number.isFinite(to)) {
      target.textContent = format(to);
      return;
    }
    const started = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      target.textContent = format(t < 1 ? Math.round(to * eased) : to);
      if (t < 1) target._raf = requestAnimationFrame(step);
    };
    target._raf = requestAnimationFrame(step);
  }

  function toast(message, kind = "ok") {
    const box = el("toasts");
    while (box.children.length >= 3) box.firstElementChild.remove();
    const t = node("div", `toast toast-${kind}`, message);
    box.append(t);
    setTimeout(() => {
      t.classList.add("is-leaving");
      setTimeout(() => t.remove(), prefersReduced() ? 0 : 260);
    }, 3200);
  }

  function burst(origin) {
    if (prefersReduced()) return;
    const r = origin.getBoundingClientRect();
    const wrap = node("div", "confetti");
    wrap.setAttribute("aria-hidden", "true");
    wrap.style.transform = `translate(${r.left + r.width / 2}px, ${r.top + r.height / 2}px)`;
    const colors = ["#ffa11a", "#ffd84a", "#123f7f", "#1c6b1c", "#ffffff"];
    for (let i = 0; i < 28; i++) {
      const piece = document.createElement("i");
      const angle = Math.random() * Math.PI * 2;
      const dist = 60 + Math.random() * 130;
      piece.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
      piece.style.setProperty("--dy", `${Math.sin(angle) * dist + Math.random() * 70}px`);
      piece.style.setProperty("--rot", `${Math.round(Math.random() * 720 - 360)}deg`);
      piece.style.setProperty("--c", colors[i % colors.length]);
      wrap.append(piece);
    }
    document.body.append(wrap);
    setTimeout(() => wrap.remove(), 1400);
  }

  // Opt-in sound, off by default. Tones are synthesised, so nothing is downloaded.
  const sound = { on: false, ctx: null };
  try {
    sound.on = localStorage.getItem("dc-sound") === "on";
  } catch (err) {
    sound.on = false;
  }

  const TUNES = {
    click: [[660, 0, 0.04]],
    select: [[880, 0, 0.03]],
    on: [[440, 0, 0.06], [660, 0.06, 0.08]],
    success: [[523, 0, 0.09], [659, 0.09, 0.09], [784, 0.18, 0.16]],
    error: [[180, 0, 0.2, "sawtooth"]],
  };

  function beep(kind) {
    if (!sound.on) return;
    try {
      sound.ctx = sound.ctx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = sound.ctx;
      if (ctx.state === "suspended") ctx.resume();
      const now = ctx.currentTime;
      for (const [freq, offset, length, type = "square"] of TUNES[kind] || []) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = type;
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.04, now + offset);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + length);
        osc.connect(gain).connect(ctx.destination);
        osc.start(now + offset);
        osc.stop(now + offset + length + 0.02);
      }
    } catch (err) {
      sound.on = false;
    }
  }

  function renderSoundToggle() {
    const btn = el("sound-toggle");
    btn.textContent = sound.on ? "Sound: on" : "Sound: off";
    btn.classList.toggle("is-on", sound.on);
  }

  // ---------- Centre column modes ----------

  function showMode(mode) {
    el("empty-state").hidden = mode !== "empty";
    el("results").hidden = mode !== "results";
    if (mode !== "error") el("error-region").replaceChildren();
  }

  function showError({ title, message, retry }) {
    toast(title, "error");
    beep("error");
    const box = node("section", "box box-error");
    const head = node("div", "box-head head-error");
    head.append(node("h2", null, title));
    const body = node("div", "box-body error-body");
    body.append(node("p", null, message));
    let retryBtn = null;
    if (retry) {
      retryBtn = node("button", "btn", "Try again");
      retryBtn.type = "button";
      retryBtn.addEventListener("click", () => {
        showMode(state.analogues.length ? "results" : "empty");
        retry();
      });
      body.append(retryBtn);
    }
    box.append(head, body);
    showMode("error");
    el("error-region").replaceChildren(box);
    if (retryBtn) retryBtn.focus();
  }

  // ---------- Form ----------

  function fillSelect(id, options) {
    el(id).replaceChildren(...options.map((option) => new Option(option, option)));
  }

  function readForm() {
    return {
      account_name: el("account_name").value.trim(),
      industry: el("industry").value,
      employees: Number(el("employees").value),
      deal_value_usd: Number(el("deal_value_usd").value),
      stage: el("stage").value,
      expected_close_days: Number(el("expected_close_days").value),
      budget_confirmed: el("budget_confirmed").checked,
      sponsor: el("sponsor").value,
      need: el("need").value,
      notes: el("notes").value,
    };
  }

  function fillForm(values) {
    for (const [key, value] of Object.entries(values)) {
      const field = el(key);
      if (field.type === "checkbox") {
        field.checked = value;
      } else {
        field.value = value;
      }
    }
  }

  function blankForm() {
    for (const f of VALIDATED) el(f.id).value = "";
    el("notes").value = "";
    el("budget_confirmed").checked = false;
    for (const id of ["industry", "stage", "sponsor", "need"]) el(id).selectedIndex = 0;
    updateCount();
  }

  function updateCount() {
    const n = el("notes").value.length;
    const counter = el("notes-count");
    counter.textContent = `${fmtInt(n)} / 2,000`;
    counter.classList.toggle("is-near", n >= 1800);
  }

  // A tick appears beside each valid field. It is a shape, so it works without colour.
  function markValid(spec) {
    el(spec.id).closest(".field").classList.toggle("is-valid", fieldMessage(spec) === "");
  }

  function refreshValidity() {
    VALIDATED.forEach(markValid);
  }

  function fieldMessage(spec) {
    const input = el(spec.id);
    const raw = input.value.trim();
    if (spec.kind === "text") {
      if (!raw) return "Enter the account name.";
      if (raw.length > 120) return "Use 120 characters or fewer.";
      return "";
    }
    if (!raw) {
      return input.validity && input.validity.badInput
        ? `${spec.label} must be a number.`
        : `Enter ${spec.label.toLowerCase()}.`;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) return `${spec.label} must be a number.`;
    if (value <= 0) return `${spec.label} must be greater than zero.`;
    if (spec.kind === "integer" && !Number.isInteger(value)) return `${spec.label} must be a whole number.`;
    return "";
  }

  function showFieldError(spec, message) {
    const input = el(spec.id);
    el(`${spec.id}-error`).textContent = message;
    if (message) {
      input.setAttribute("aria-invalid", "true");
    } else {
      input.removeAttribute("aria-invalid");
    }
  }

  function validateField(spec) {
    const message = fieldMessage(spec);
    showFieldError(spec, message);
    markValid(spec);
    return message;
  }

  function clearFieldErrors() {
    for (const spec of VALIDATED) showFieldError(spec, "");
  }

  function validateAll() {
    const invalid = VALIDATED.filter((spec) => validateField(spec));
    return invalid;
  }

  for (const spec of VALIDATED) {
    const input = el(spec.id);
    input.addEventListener("input", () => {
      if (input.getAttribute("aria-invalid") === "true") validateField(spec);
      else markValid(spec);
    });
    input.addEventListener("change", () => {
      if (input.value.trim()) validateField(spec);
    });
  }

  // ---------- Busy state ----------

  function setBusy(busy) {
    state.busy = busy;
    evaluateBtn.setAttribute("aria-disabled", String(busy));
    evaluateBtn.classList.toggle("is-busy", busy);
    el("evaluate-label").textContent = busy ? "Evaluating..." : "Evaluate";
    el("loading").hidden = !busy;
    document.body.classList.toggle("is-loading", busy);
  }

  // Lights up the three inference steps in turn so the wait is visible. Skipped when motion is reduced.
  function runSteps() {
    const items = Array.from(el("steps").children);
    items.forEach((li) => (li.className = ""));
    if (prefersReduced()) {
      items.forEach((li) => (li.className = "is-done"));
      return { done: Promise.resolve(), cancel() {} };
    }
    let cancelled = false;
    const done = (async () => {
      for (const li of items) {
        if (cancelled) return;
        li.className = "is-active";
        await sleep(STEP_MS);
        li.className = "is-done";
      }
    })();
    return { done, cancel() { cancelled = true; } };
  }

  // ---------- Tabs ----------

  function selectTab(index, focus = true) {
    tabs.forEach((tab, i) => {
      const selected = i === index;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      el(tab.getAttribute("aria-controls")).hidden = !selected;
    });
    if (focus) tabs[index].focus();
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(index));
    tab.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      selectTab(next);
    });
  });

  // ---------- Analogues ----------

  function textBlock(label, value) {
    const block = node("div", "detail-block");
    block.append(node("span", "label", label));
    if (Array.isArray(value)) {
      const list = node("ul", "risk-list");
      for (const item of value) list.append(node("li", null, String(item)));
      block.append(list);
    } else {
      block.append(node("p", null, String(value)));
    }
    return block;
  }

  function renderDetail(a) {
    const detail = el("analogue-detail");
    const meta = node("div", "detail-meta");
    meta.append(
      badge(a.outcome, a.outcome === "WON" ? "ok" : "bad"),
      node("span", "chip", a.industry),
      node("span", "chip", fmtMoney(a.deal_value_usd)),
      node("span", null, `${fmtInt(a.similarity_pct)}% match`)
    );
    const title = node("h3", null, `${a.account_name} `);
    title.append(node("span", "mono", a.deal_id));

    const parts = [title, meta];
    if (a.notes) parts.push(textBlock("Deal notes", a.notes));
    if (a.outcome === "WON") {
      if (a.tactics) parts.push(textBlock("What worked", a.tactics));
    } else {
      if (a.failure_reason) parts.push(textBlock("Why it was lost", a.failure_reason));
      if (a.mitigation) parts.push(textBlock("Mitigation", a.mitigation));
    }
    detail.replaceChildren(...parts);
  }

  // Marks the same analogue as current in both the rail list and the table, and shows its detail.
  function markSelected(index) {
    state.selected = index;
    document.querySelectorAll("[data-analogue-index]").forEach((btn) => {
      const active = Number(btn.dataset.analogueIndex) === index;
      if (active) {
        btn.setAttribute("aria-current", "true");
      } else {
        btn.removeAttribute("aria-current");
      }
      const row = btn.closest("tr");
      if (row) row.classList.toggle("is-selected", active);
    });
    renderDetail(state.analogues[index]);
  }

  function selectAnalogue(index, fromRail) {
    const a = state.analogues[index];
    if (!a) return;
    markSelected(index);
    beep("select");
    setStatus(`Selected ${a.account_name}, ${a.outcome}, ${fmtInt(a.similarity_pct)}% match. Details are in the Analogues tab.`);

    if (fromRail) {
      selectTab(2, false);
      el("playbook-box").scrollIntoView({ block: "nearest" });
      el("analogue-detail").focus({ preventScroll: true });
    }
  }

  function analogueButton(className, index) {
    const btn = node("button", className);
    btn.type = "button";
    btn.dataset.analogueIndex = String(index);
    return btn;
  }

  function renderAnalogues(analogues) {
    state.analogues = analogues;

    // Compact ranked list in the right rail.
    const items = analogues.slice(0, 5).map((a, i) => {
      const li = document.createElement("li");
      li.style.setProperty("--i", String(i));
      const btn = analogueButton("rank-btn", i);
      btn.addEventListener("click", () => selectAnalogue(i, true));
      const side = node("span", "rank-side");
      const sim = node("span", null, `${fmtInt(a.similarity_pct)}%`);
      sim.append(node("span", "sr-only", " match"));
      side.append(badge(a.outcome, a.outcome === "WON" ? "ok" : "bad"), sim);
      btn.append(
        node("span", "rank-num", `${i + 1}.`),
        node("span", "rank-name", a.account_name),
        side,
        node("span", "rank-sub", `${a.deal_id} - ${a.industry}`)
      );
      li.append(btn);
      return li;
    });
    el("top5-list").replaceChildren(...items);
    el("top5-empty").hidden = analogues.length > 0;
    el("top5-list").hidden = analogues.length === 0;
    el("top5-hint").hidden = analogues.length === 0;

    // Full table in the Analogues tab.
    const rows = analogues.map((a, i) => {
      const tr = document.createElement("tr");
      const first = document.createElement("td");
      const btn = analogueButton("row-btn", i);
      btn.textContent = a.account_name;
      btn.addEventListener("click", () => selectAnalogue(i, false));
      first.append(
        btn,
        node("span", "row-sub", `${a.deal_id} - ${a.industry} - ${fmtMoney(a.deal_value_usd)}`)
      );
      const outcome = document.createElement("td");
      outcome.append(badge(a.outcome, a.outcome === "WON" ? "ok" : "bad"));
      const match = node("td", "num", `${fmtInt(a.similarity_pct)}%`);
      tr.append(first, outcome, match);
      return tr;
    });
    el("analogue-rows").replaceChildren(...rows);
  }

  // ---------- Results ----------

  function riskItem(text) {
    const li = document.createElement("li");
    const match = /^Risk:\s*([\s\S]*?)\s*Mitigation:\s*([\s\S]*)$/.exec(text);
    if (!match) {
      li.textContent = text;
      return li;
    }
    const risk = node("span");
    risk.append(node("strong", null, "Risk "), document.createTextNode(match[1]));
    const fix = node("span");
    fix.append(node("strong", null, "Mitigation "), document.createTextNode(match[2]));
    li.append(risk, fix);
    return li;
  }

  function renderResults(r, submitted) {
    const q = r.qualification;
    const f = q.framework_breakdown;
    const p = q.fit_points;
    const e = r.estimates;
    const eff = r.effort_allocation;
    const play = r.closing_playbook;
    const base = r.baseline;
    const recText = q.pursue_recommendation.replaceAll("_", " ");
    const recVariant = recommendationVariant(q.pursue_recommendation);

    document.title = `${r.deal_id} - ${r.account_name} - Deal Copilot`;

    // Hero
    el("hero-account").textContent = r.account_name;
    el("hero-deal-id").textContent = r.deal_id;
    el("hero-industry").textContent = submitted.industry;
    el("hero-stage").textContent = submitted.stage;
    const heroRec = el("hero-rec");
    heroRec.className = `badge badge-lg badge-${recVariant}`;
    heroRec.textContent = recText;
    setBar("hero-fit-bar", q.fit_score);
    setBar("hero-win-bar", e.win_probability_pct);
    countUp(el("hero-fit"), q.fit_score, fmtInt);
    countUp(el("hero-win"), e.win_probability_pct, fmtPct);
    countUp(el("hero-ev"), e.estimated_revenue_usd, fmtMoney);
    countUp(el("hero-time"), e.estimated_timeframe_days, (n) => `${fmtInt(n)} days`);
    state.lastResult = r;

    // Qualification
    const factorRows = [
      ["Budget", f.budget, p.budget],
      ["Authority", f.authority, p.authority],
      ["Need", f.need, p.need],
      ["Timeline", f.timeline, p.timeline],
      ["Stage", f.stage, p.stage],
    ].map(([name, assessment, points]) => {
      const tr = document.createElement("tr");
      const th = node("th", null, name);
      th.scope = "row";
      tr.append(th, node("td", null, String(assessment)), node("td", "num", fmtInt(points)));
      return tr;
    });
    el("factor-rows").replaceChildren(...factorRows);
    el("fit-total").textContent = `${fmtInt(q.fit_score)} / 100`;
    // Maximum points per factor, matching the engine's scoring weights.
    const MAX_POINTS = { Budget: 20, Authority: 25, Need: 20, Timeline: 15, Stage: 20 };
    const gaps = [
      ["Budget", p.budget],
      ["Authority", p.authority],
      ["Need", p.need],
      ["Timeline", p.timeline],
      ["Stage", p.stage],
    ]
      .map(([name, points]) => ({ name, points, missing: MAX_POINTS[name] - points }))
      .filter((g) => g.missing > 0)
      .sort((a, b) => b.missing - a.missing);
    el("qual-gap").textContent = gaps.length
      ? `${gaps[0].name} is the biggest gap: ${fmtInt(gaps[0].points)} of ${MAX_POINTS[gaps[0].name]} points.` +
        (gaps[1] ? ` Next: ${gaps[1].name}, ${fmtInt(gaps[1].points)} of ${MAX_POINTS[gaps[1].name]}.` : "")
      : "Every factor scored full points.";
    const qualRec = el("qual-rec");
    qualRec.className = `badge badge-${recVariant}`;
    qualRec.textContent = recText;

    // Estimates
    countUp(el("est-win"), e.win_probability_pct, fmtPct);
    countUp(el("est-ev"), e.estimated_revenue_usd, fmtMoney);
    countUp(el("est-time"), e.estimated_timeframe_days, (n) => `${fmtInt(n)} days`);
    el("est-conf").textContent = e.confidence_level;
    el("est-hist").textContent = `${fmtPct(base.win_rate_pct)} (${base.basis})`;
    el("est-fit").textContent = `${fmtInt(q.fit_score)} / 100`;
    el("est-sample").textContent = `${fmtInt(base.sample_size)} deals`;
    el("est-note").textContent =
      `Win probability blends 60% historical win rate with 40% fit score. Expected value is deal value times win probability. ` +
      `Timeframe averages your ${fmtInt(submitted.expected_close_days)}-day estimate with the ${fmtInt(base.median_cycle_days)}-day historical median. ` +
      `Confidence is ${e.confidence_level} because ${fmtInt(base.sample_size)} similar deals were found.`;

    // Effort
    el("eff-tier").textContent = eff.tier;
    el("eff-hours").textContent = `${fmtInt(eff.max_recommended_hours)} hours`;
    el("resources").replaceChildren(
      ...eff.recommended_resources.map((text) => {
        const li = document.createElement("li");
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        label.append(box, node("span", null, text));
        li.append(label);
        return li;
      })
    );

    // Playbook
    el("strategy").textContent = play.winning_strategy;
    el("referenced").replaceChildren(
      ...play.referenced_historical_deals.map((id) => node("li", "chip mono", id))
    );
    el("risks").replaceChildren(
      ...play.key_risks_and_mitigations.map((text, i) => {
        const li = riskItem(text);
        li.style.setProperty("--i", String(i));
        return li;
      })
    );

    // Analogues
    renderAnalogues(r.analogues);
    el("analogue-detail").replaceChildren();
    if (r.analogues.length) markSelected(0);

    // Baseline
    el("base-basis").textContent = base.basis;
    el("base-sample").textContent = `${fmtInt(base.sample_size)} deals`;
    el("base-win").textContent = fmtPct(base.win_rate_pct);
    el("base-value").textContent = fmtMoney(base.median_deal_value_usd);
    el("base-cycle").textContent = `${fmtInt(base.median_cycle_days)} days`;
    el("base-empty").hidden = true;
    el("base-list").hidden = false;

    showMode("results");
    selectTab(0, false);
    updateChecklist();

    animateBars();
    if (!prefersReduced()) {
      replay(
        Array.from(document.querySelectorAll("#hero, #results .grid > .box, .rail-right > .box")),
        "reveal-item"
      );
      replay([heroRec], "pop-in");
      if (q.pursue_recommendation === "PURSUE_HIGH_PRIORITY") {
        setTimeout(() => burst(heroRec), 450);
      }
    }
  }

  function resetResults() {
    state.lastResult = null;
    el("eff-progress").textContent = "";
    state.analogues = [];
    state.selected = -1;
    state.submitted = null;
    document.title = "Deal Copilot - Deal Intelligence & Sales Copilot";
    el("top5-list").replaceChildren();
    el("top5-list").hidden = true;
    el("top5-hint").hidden = true;
    el("top5-empty").hidden = false;
    el("base-list").hidden = true;
    el("base-empty").hidden = false;
    el("analogue-detail").replaceChildren();
    el("analogue-rows").replaceChildren();
    showMode("empty");
    selectTab(0, false);
  }

  // ---------- Server calls ----------

  async function evaluate() {
    if (state.busy) return;

    const invalid = validateAll();
    if (invalid.length) {
      el(invalid[0].id).focus();
      const message =
        invalid.length === 1 ? "1 field needs attention." : `${invalid.length} fields need attention.`;
      setStatus(message);
      toast(message, "error");
      beep("error");
      if (navigator.vibrate) navigator.vibrate(80);
      if (!prefersReduced()) replay(invalid.map((spec) => el(spec.id).closest(".field")), "shake");
      return;
    }

    if (!state.optionsReady) {
      await loadOptions();
      if (!state.optionsReady) return;
    }

    const payload = readForm();
    evaluateBtn.classList.remove("is-attract");
    setBusy(true);
    setStatus("Evaluating deal...");
    const steps = runSteps();
    try {
      const [response] = await Promise.all([
        fetch("/api/evaluate-deal", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }),
        steps.done,
      ]);
      let body = null;
      try {
        body = await response.json();
      } catch (parseError) {
        body = null;
      }

      if (response.status === 400 && body && body.error) {
        showError({ title: "Check the deal details", message: body.error });
        setStatus("The server rejected the deal details.");
        return;
      }
      if (!response.ok || !body) {
        showError({
          title: "Evaluation failed",
          message: `The server returned an unexpected response (status ${response.status}). Try again in a moment.`,
          retry: evaluate,
        });
        setStatus("Evaluation failed.");
        return;
      }

      state.submitted = payload;
      renderResults(body, payload);
      const rec = body.qualification.pursue_recommendation.replaceAll("_", " ");
      toast(`${body.account_name}: ${rec}`);
      beep("success");
      setStatus(
        `Evaluated ${body.account_name} (${body.deal_id}): ${rec}, fit ${body.qualification.fit_score}, win ${body.estimates.win_probability_pct}%.`
      );
      if (window.matchMedia("(max-width: 639px)").matches) {
        el("hero").scrollIntoView({ block: "start" });
      }
    } catch (err) {
      steps.cancel();
      showError({
        title: "Can't reach the local server",
        message: "The request did not go through. Check that Deal Copilot is still running, then try again.",
        retry: evaluate,
      });
      setStatus("Server unreachable.");
    } finally {
      setBusy(false);
    }
  }

  async function loadOptions() {
    setStatus("Loading form options...");
    try {
      const response = await fetch("/api/options");
      if (!response.ok) throw new Error(`status ${response.status}`);
      const options = await response.json();
      fillSelect("industry", options.industries);
      fillSelect("stage", options.stages);
      fillSelect("sponsor", options.sponsors);
      fillSelect("need", options.needs);
      state.optionsReady = true;
      setStatus("Ready.");
    } catch (err) {
      state.optionsReady = false;
      showError({
        title: "Can't reach the local server",
        message: "The form options could not be loaded. Check that Deal Copilot is still running, then try again.",
        retry: loadOptions,
      });
      setStatus("Server unreachable.");
    }
  }

  // ---------- Actions ----------

  function loadSample() {
    if (!state.optionsReady) {
      setStatus("Form options are not loaded yet. Use Try again first.");
      return;
    }
    fillForm(SAMPLE);
    clearFieldErrors();
    refreshValidity();
    updateCount();
    toast("Sample deal loaded.");
    beep("click");
    if (!prefersReduced()) replay([el("deal-form").closest(".box")], "flash");
    setStatus("Sample deal loaded. Press Evaluate to score it.");
  }

  function clearAll() {
    blankForm();
    clearFieldErrors();
    refreshValidity();
    resetResults();
    toast("Form and results cleared.");
    setStatus("Form and results cleared.");
    el("account_name").focus();
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    evaluate();
  });
  el("sample-btn").addEventListener("click", loadSample);
  el("clear-btn").addEventListener("click", clearAll);
  el("notes").addEventListener("input", updateCount);

  // Checklist progress.
  function updateChecklist() {
    const boxes = Array.from(el("resources").querySelectorAll("input"));
    const note = el("eff-progress");
    if (!boxes.length) {
      note.textContent = "";
      note.classList.remove("is-complete");
      return false;
    }
    const done = boxes.filter((box) => box.checked).length;
    const complete = done === boxes.length;
    note.classList.toggle("is-complete", complete);
    note.textContent = complete ? "All steps done." : `${done} of ${boxes.length} steps done`;
    return complete;
  }

  el("resources").addEventListener("change", () => {
    if (updateChecklist()) {
      toast("All steps done. Ready to go.");
      beep("success");
      if (!prefersReduced()) replay([el("eff-tier").closest(".box")], "flash");
    } else {
      beep("select");
    }
  });

  // Copy summary.
  function summaryText(r) {
    const q = r.qualification;
    const e = r.estimates;
    const eff = r.effort_allocation;
    return [
      `${r.account_name} (${r.deal_id}): ${q.pursue_recommendation.replaceAll("_", " ")}`,
      `Fit ${q.fit_score}/100 | Win ${e.win_probability_pct}% | Expected value ${fmtMoney(e.estimated_revenue_usd)} | ${e.estimated_timeframe_days} days | Confidence ${e.confidence_level}`,
      `Effort: ${eff.tier}, up to ${eff.max_recommended_hours} hours`,
      `Strategy: ${r.closing_playbook.winning_strategy}`,
      `Closest analogues: ${r.closing_playbook.referenced_historical_deals.join(", ")}`,
    ].join("\n");
  }

  function legacyCopy(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("copy failed");
  }

  el("copy-btn").addEventListener("click", async () => {
    if (!state.lastResult) return;
    const btn = el("copy-btn");
    const text = summaryText(state.lastResult);
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        legacyCopy(text);
      }
      btn.textContent = "Copied";
      btn.classList.add("is-done");
      toast("Summary copied to clipboard.");
      beep("success");
      setStatus("Summary copied to clipboard.");
      setTimeout(() => {
        btn.textContent = "Copy summary";
        btn.classList.remove("is-done");
      }, 1600);
    } catch (err) {
      toast("Could not copy. Select the text and copy it by hand.", "error");
      beep("error");
      setStatus("Copy failed.");
    }
  });

  // Sound toggle.
  el("sound-toggle").addEventListener("click", () => {
    sound.on = !sound.on;
    try {
      localStorage.setItem("dc-sound", sound.on ? "on" : "off");
    } catch (err) {
      // Storage can be blocked. The setting then lasts for this visit only.
    }
    renderSoundToggle();
    beep("on");
    setStatus(sound.on ? "Sound effects on." : "Sound effects off.");
  });

  // Click sounds and press ripples for every control, handled in one place.
  document.addEventListener("click", (event) => {
    if (event.target.closest(".btn, .tab, .rank-btn, .row-btn, .nav-link:not(.nav-toggle)")) beep("click");
  });

  document.addEventListener("pointerdown", (event) => {
    const btn = event.target.closest(".btn");
    if (!btn || prefersReduced() || btn.getAttribute("aria-disabled") === "true") return;
    const rect = btn.getBoundingClientRect();
    const dot = node("span", "ripple");
    dot.style.left = `${event.clientX - rect.left}px`;
    dot.style.top = `${event.clientY - rect.top}px`;
    btn.append(dot);
    setTimeout(() => dot.remove(), 600);
  });

  document.querySelector('[data-nav="playbook"]').addEventListener("click", (event) => {
    if (el("results").hidden) {
      event.preventDefault();
      setStatus("Evaluate a deal to see its closing playbook.");
    }
  });

  renderSoundToggle();
  updateCount();
  evaluateBtn.classList.add("is-attract");
  loadOptions();
})();
