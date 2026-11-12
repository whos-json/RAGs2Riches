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


  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  const form = document.getElementById("deal-form");
  const evaluateBtn = document.getElementById("evaluate-btn");
  const statusMessage = document.getElementById("status-message");
  const emptyState = document.getElementById("empty-state");
  const results = document.getElementById("results");
  const tabs = Array.from(document.querySelectorAll('[role="tab"]'));

  const el = (id) => document.getElementById(id);

  function setStatus(message) {
    statusMessage.textContent = message;
  }

  function setBusy(busy) {
    evaluateBtn.disabled = busy;
    evaluateBtn.textContent = busy ? "Evaluating..." : "Evaluate";
  }

  function readForm() {
    return {
      account_name: el("account_name").value,
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

  function fillSelect(id, options) {
    const select = el(id);
    select.replaceChildren(...options.map((option) => new Option(option, option)));
  }

  function setRows(tbody, rows) {
    tbody.replaceChildren(
      ...rows.map((cells) => {
        const tr = document.createElement("tr");
        for (const cell of cells) {
          const td = document.createElement("td");
          if (cell instanceof Node) {
            td.append(cell);
          } else {
            td.textContent = cell;
          }
          tr.append(td);
        }
        return tr;
      })
    );
  }

  function badge(text, variant) {
    const span = document.createElement("span");
    span.className = `badge badge-${variant}`;
    span.textContent = text;
    return span;
  }

  function recommendationVariant(recommendation) {
    if (recommendation.startsWith("PURSUE")) return "ok";
    if (recommendation === "QUALIFY_FURTHER") return "warn";
    return "bad";
  }

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
      const keys = { ArrowRight: 1, ArrowLeft: -1 };
      if (!(event.key in keys)) return;
      event.preventDefault();
      selectTab((index + keys[event.key] + tabs.length) % tabs.length);
    });
  });

  function renderResults(r) {
    const q = r.qualification;
    const f = q.framework_breakdown;
    const p = q.fit_points;
    const e = r.estimates;
    const eff = r.effort_allocation;
    const play = r.closing_playbook;

    el("window-title").textContent = `${r.deal_id} - ${r.account_name} - Deal Intelligence & Sales Copilot`;

    const rec = el("recommendation");
    rec.className = `badge badge-${recommendationVariant(q.pursue_recommendation)}`;
    rec.textContent = q.pursue_recommendation.replaceAll("_", " ");

    el("fit-bar").value = q.fit_score;
    el("fit-value").textContent = `${q.fit_score} / 100`;

    setRows(el("factor-rows"), [
      ["Budget", f.budget, String(p.budget)],
      ["Authority", f.authority, String(p.authority)],
      ["Need", f.need, String(p.need)],
      ["Timeline", f.timeline, String(p.timeline)],
      ["Stage", f.stage, String(p.stage)],
    ]);

    el("win-bar").value = e.win_probability_pct;
    el("win-value").textContent = `${e.win_probability_pct}%`;
    el("expected-value").value = money.format(e.estimated_revenue_usd);
    el("timeframe").value = `${e.estimated_timeframe_days} days`;
    el("confidence").value = e.confidence_level;

    el("tier").value = eff.tier;
    el("max-hours").value = `${eff.max_recommended_hours} hours`;
    el("resources").replaceChildren(
      ...eff.recommended_resources.map((text) => {
        const li = document.createElement("li");
        const label = document.createElement("label");
        const box = document.createElement("input");
        box.type = "checkbox";
        const span = document.createElement("span");
        span.textContent = text;
        label.append(box, span);
        li.append(label);
        return li;
      })
    );

    el("strategy").textContent = play.winning_strategy;
    el("risks").replaceChildren(
      ...play.key_risks_and_mitigations.map((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        return li;
      })
    );

    setRows(
      el("analogue-rows"),
      r.analogues.map((a) => [
        a.deal_id,
        a.account_name,
        badge(a.outcome, a.outcome === "WON" ? "ok" : "bad"),
        `${a.similarity_pct}%`,
      ])
    );

    el("status-fit").textContent = `Fit: ${q.fit_score}`;
    el("status-win").textContent = `Win: ${e.win_probability_pct}%`;
    el("status-confidence").textContent = `Confidence: ${e.confidence_level}`;
    el("status-analogues").textContent = `Analogues: ${r.analogues.length}`;

    emptyState.hidden = true;
    results.hidden = false;
    selectTab(0, false);
  }

  function clearResults() {
    results.hidden = true;
    emptyState.hidden = false;
    el("window-title").textContent = "Deal Intelligence & Sales Copilot";
    el("status-fit").textContent = "Fit: -";
    el("status-win").textContent = "Win: -";
    el("status-confidence").textContent = "Confidence: -";
    el("status-analogues").textContent = "Analogues: -";
    setStatus("Ready");
  }

  async function evaluate() {
    setBusy(true);
    setStatus("Evaluating deal...");
    try {
      const response = await fetch("/api/evaluate-deal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(readForm()),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.error || `Request failed with status ${response.status}`);
      }
      renderResults(body);
      setStatus(`Evaluated ${body.deal_id}`);
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (form.reportValidity()) {
      evaluate();
    }
  });

  form.addEventListener("reset", () => {
    // The reset event fires before the browser restores field defaults.
    setTimeout(clearResults, 0);
  });

  el("menu-new").addEventListener("click", () => {
    form.reset();
  });

  el("menu-about").addEventListener("click", () => {
    el("about-dialog").showModal();
  });

  async function init() {
    setStatus("Loading options...");
    try {
      const response = await fetch("/api/options");
      if (!response.ok) throw new Error(`options request failed (${response.status})`);
      const options = await response.json();
      fillSelect("industry", options.industries);
      fillSelect("stage", options.stages);
      fillSelect("sponsor", options.sponsors);
      fillSelect("need", options.needs);
      fillForm(SAMPLE);
      clearResults();
      evaluate();
    } catch (err) {
      setStatus(`Error: could not reach the local server (${err.message})`);
    }
  }

  init();
})();
