from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Optional, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app import llm as llm_mod
from app.baseline import compute_baseline
from app.db import Deal
from app.normalize import size_tier, term_band
from app.redaction import alias, redact_text
from app.retrieval import find_analogues
from app.schemas import (
    Analogue,
    BaselineMetrics,
    ClosingPlaybook,
    DealInput,
    DealScorecard,
    EffortAllocation,
    Estimates,
    Evidence,
    Narrative,
    Qualification,
)

# Placeholder thresholds for demonstration. Calibrate against real outcomes (Phase 3).
PURSUE_HIGH_PRIORITY_WIN_PCT = 60.0
PURSUE_WIN_PCT = 40.0
HIGH_VALUE_FEE_SGD = 100_000
MID_VALUE_FEE_SGD = 30_000

SYSTEM_PROMPT = (
    "You are a commercial leasing deal strategist. Use ONLY the metrics and analogues provided. "
    "Do not invent win probabilities, fees, timeframes or client facts. "
    "In referenced_historical_deals, use only aliases from the analogues list, such as HIST-01."
)
HUMAN_PROMPT = "Deal and evidence (JSON):\n{payload}"


class WorkflowState(TypedDict, total=False):
    deal: dict
    llm: dict
    normalized: dict
    baseline: dict
    analogues: list[dict]
    alias_map: dict[str, str]
    narrative: dict
    narrative_source: str
    warnings: list[str]
    scorecard: dict


def _emitter(config: RunnableConfig) -> Callable[[dict], None]:
    return (config.get("configurable") or {}).get("emit") or (lambda _event: None)


def _instrumented(name: str, fn, summarize):
    """Wrap a node so start, end and error events are streamed to the UI."""

    def node(state: WorkflowState, config: RunnableConfig) -> dict:
        emit = _emitter(config)
        emit({"type": "node_start", "node": name, "ts": time.time()})
        started = time.perf_counter()
        try:
            update = fn(state)
        except Exception as exc:
            emit({"type": "node_error", "node": name, "error": f"{type(exc).__name__}: {exc}"})
            raise
        emit(
            {
                "type": "node_end",
                "node": name,
                "ts": time.time(),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "summary": summarize(update),
            }
        )
        return update

    node.__name__ = name
    return node


def _term_text(months: Optional[float]) -> str:
    return f"{months:g} mo" if months else "term n/a"


def _template_narrative(normalized: dict, baseline: BaselineMetrics, analogues: list[Analogue]) -> dict:
    industry = normalized.get("industry") or "unspecified industry"
    tier = normalized.get("size_tier") or "unspecified size"
    if baseline.median_fee_sgd is not None:
        fee_text = f"median gross fee SGD {baseline.median_fee_sgd:,.0f}"
    else:
        fee_text = "no fee benchmark"
    strategy = (
        f"Based on {baseline.n_comparables} comparable deals ({baseline.match_level}; {industry}, {tier}), "
        f"{fee_text}. Lead with a shortlist sized to the requirement and anchor on the closest precedent."
    )
    risks = []
    if normalized.get("lease_term_months") is None:
        median_term = (
            f"comparables median {baseline.median_lease_term_months:g} months"
            if baseline.median_lease_term_months
            else "no comparable term data"
        )
        risks.append(f"Risk: lease term not provided. Mitigation: confirm target term ({median_term}).")
    if baseline.win_rate_pct is None:
        risks.append(
            "Risk: source data has no WON/LOST outcomes. Mitigation: treat this playbook as descriptive, "
            "not a calibrated win forecast."
        )
    if baseline.n_comparables < 5:
        risks.append("Risk: few comparables. Mitigation: validate assumptions with the lead broker.")
    resources = ["Lead broker to validate requirement and shortlist within the comparable size band."]
    if baseline.median_fee_sgd and baseline.median_fee_sgd >= HIGH_VALUE_FEE_SGD:
        resources.append("Senior broker or principal to join early on this high-value mandate.")
    return {
        "winning_strategy": strategy,
        "key_risks_and_mitigations": risks,
        "recommended_resources": resources,
        "referenced_historical_deals": [a.deal_name for a in analogues[:3]],
    }


def _redacted_payload(normalized: dict, baseline: BaselineMetrics, analogues: list[Analogue], deal: dict) -> dict:
    """Send only what the model needs. Names, agents and raw IDs stay local."""
    return {
        "new_deal": {
            "industry": normalized.get("industry"),
            "size_sqft": normalized.get("size_sqft"),
            "size_tier": normalized.get("size_tier"),
            "lease_term_months": normalized.get("lease_term_months"),
            "gross_signing_rent_psf": normalized.get("gross_signing_rent_psf"),
            "property_alias": alias("PROPERTY", deal.get("property_name")),
            "notes": redact_text(deal.get("notes")),
        },
        "baseline": baseline.model_dump(),
        "analogues": [
            {
                "alias": f"HIST-{i:02d}",
                "industry": a.industry,
                "size_sqft": a.size_sqft,
                "lease_term_months": a.lease_term_months,
                "gross_fee_sgd": a.gross_fee_sgd,
                "outcome": a.outcome,
                "similarity": a.similarity,
            }
            for i, a in enumerate(analogues, start=1)
        ],
    }


def _effort_tier(median_fee: Optional[float]) -> tuple[str, int]:
    if median_fee is not None and median_fee >= HIGH_VALUE_FEE_SGD:
        return "Tier 1 - High Touch", 25
    if median_fee is not None and median_fee >= MID_VALUE_FEE_SGD:
        return "Tier 2 - Standard", 12
    return "Tier 3 - Light", 6


def _confidence(baseline: BaselineMetrics) -> str:
    if baseline.n_comparables >= 20 and baseline.outcome_coverage >= 20:
        return "HIGH"
    if baseline.n_comparables >= 10:
        return "MEDIUM"
    return "LOW"


def _data_gaps(normalized: dict, baseline: BaselineMetrics) -> list[str]:
    gaps = []
    if baseline.win_rate_pct is None:
        gaps.append("No WON/LOST outcomes in source data: win probability unavailable.")
    gaps.append("No deal-created or first-contact date in source: sales cycle and timeframe unavailable.")
    gaps.append("No qualification data (budget, authority, need, timeline): fit score unavailable.")
    if normalized.get("size_sqft") is None:
        gaps.append("Size not provided: size-tier comparables skipped.")
    if normalized.get("lease_term_months") is None:
        gaps.append("Lease term not provided.")
    if baseline.n_comparables < 5:
        gaps.append(f"Only {baseline.n_comparables} comparables matched: estimates are low-confidence.")
    return gaps


def build_graph(session_factory):
    """Compile the Deal Inference workflow as a LangGraph StateGraph."""

    def validate_input(state: WorkflowState) -> dict:
        deal = DealInput.model_validate(state["deal"])
        industry = (deal.industry or "").strip() or None
        tier = size_tier(deal.size_sqft)
        normalized = {
            "industry": industry,
            "size_sqft": deal.size_sqft,
            "size_tier": tier,
            "lease_term_months": deal.lease_term_months,
            "lease_term_band": term_band(deal.lease_term_months),
            "gross_signing_rent_psf": deal.gross_signing_rent_psf,
            "property_name": deal.property_name,
        }
        warnings = list(state.get("warnings", []))
        if deal.size_sqft is None:
            warnings.append("Size not provided: size-tier comparables skipped.")
        return {"normalized": normalized, "warnings": warnings}

    def sql_baseline(state: WorkflowState) -> dict:
        with session_factory() as session:
            deals = session.scalars(select(Deal)).all()
        metrics = compute_baseline(deals, state["normalized"], exclude_name=state["deal"].get("deal_name"))
        return {"baseline": metrics.model_dump()}

    def analogue_retrieval(state: WorkflowState) -> dict:
        with session_factory() as session:
            deals = session.scalars(select(Deal)).all()
        analogues = find_analogues(
            deals,
            state["normalized"],
            k=5,
            exclude_name=state["deal"].get("deal_name"),
        )
        alias_map = {f"HIST-{i:02d}": a.deal_name for i, a in enumerate(analogues, start=1)}
        return {"analogues": [a.model_dump() for a in analogues], "alias_map": alias_map}

    def llm_synthesis(state: WorkflowState) -> dict:
        normalized = state["normalized"]
        baseline = BaselineMetrics(**state["baseline"])
        analogues = [Analogue(**a) for a in state["analogues"]]
        warnings = list(state.get("warnings", []))
        selection = state["llm"]
        provider, model = selection["provider"], selection.get("model")

        if provider == "template":
            return {
                "narrative": _template_narrative(normalized, baseline, analogues),
                "narrative_source": "template",
                "warnings": warnings,
            }
        try:
            chat_model = llm_mod.build_chat_model(provider, model)
            payload = _redacted_payload(normalized, baseline, analogues, state["deal"])
            prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])
            chain = prompt | chat_model.with_structured_output(Narrative)
            result: Narrative = chain.invoke({"payload": json.dumps(payload, indent=2, default=str)})
            return {
                "narrative": result.model_dump(),
                "narrative_source": "llm",
                "warnings": warnings,
            }
        except Exception as exc:
            warnings.append(
                f"LLM '{provider}' failed ({type(exc).__name__}: {exc}); used template narrative instead."
            )
            return {
                "narrative": _template_narrative(normalized, baseline, analogues),
                "narrative_source": "template_fallback",
                "warnings": warnings,
            }

    def assemble_scorecard(state: WorkflowState) -> dict:
        deal = state["deal"]
        normalized = state["normalized"]
        baseline = BaselineMetrics(**state["baseline"])
        analogues = [Analogue(**a) for a in state["analogues"]]
        narrative = state["narrative"]
        analogue_names = [a.deal_name for a in analogues]

        referenced: list[str] = []
        for ref in narrative.get("referenced_historical_deals", []):
            name = state.get("alias_map", {}).get(ref, ref)
            if name in analogue_names and name not in referenced:
                referenced.append(name)
        if not referenced:
            referenced = analogue_names[:3]

        win = baseline.win_rate_pct
        if win is None:
            pursue = None
        elif win >= PURSUE_HIGH_PRIORITY_WIN_PCT:
            pursue = "PURSUE_HIGH_PRIORITY"
        elif win >= PURSUE_WIN_PCT:
            pursue = "PURSUE"
        else:
            pursue = "NURTURE"

        tier, hours = _effort_tier(baseline.median_fee_sgd)
        deal_id = deal.get("deal_name") or "NEW-" + hashlib.sha1(
            json.dumps(deal, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:8]
        llm_selection = state["llm"]

        scorecard = DealScorecard(
            deal_id=deal_id,
            qualification=Qualification(
                pursue_recommendation=pursue,
                fit_score=None,
                framework_breakdown={
                    "budget": "Not in source data",
                    "authority": "Not in source data",
                    "need": "Not in source data",
                    "timeline": "Not in source data",
                },
            ),
            estimates=Estimates(
                win_probability_pct=win,
                estimated_fee_sgd=baseline.median_fee_sgd,
                estimated_timeframe_days=None,
                confidence_level=_confidence(baseline),
            ),
            effort_allocation=EffortAllocation(
                tier=tier,
                recommended_resources=narrative.get("recommended_resources", []),
                max_recommended_hours=hours,
            ),
            closing_playbook=ClosingPlaybook(
                winning_strategy=narrative["winning_strategy"],
                key_risks_and_mitigations=narrative.get("key_risks_and_mitigations", []),
                referenced_historical_deals=referenced,
            ),
            evidence=Evidence(baseline=baseline, analogues=analogues),
            data_gaps=_data_gaps(normalized, baseline),
            warnings=state.get("warnings", []),
            narrative_source=state["narrative_source"],
            llm_provider=llm_selection["provider"],
            llm_model=llm_selection.get("model"),
        )
        return {"scorecard": scorecard.model_dump()}

    def _summary_validate(u):
        n = u["normalized"]
        return f"industry={n['industry'] or 'n/a'}, tier={n['size_tier'] or 'n/a'}, term={_term_text(n['lease_term_months'])}"

    def _summary_baseline(u):
        b = u["baseline"]
        fee = f"{b['median_fee_sgd']:,.0f}" if b["median_fee_sgd"] else "n/a"
        return f"{b['n_comparables']} comparables ({b['match_level']}), median fee SGD {fee}"

    def _summary_analogues(u):
        names = [a["deal_name"] for a in u["analogues"]]
        return f"top {len(names)}: {', '.join(names[:3])}" if names else "no analogues found"

    def _summary_llm(u):
        return f"narrative source: {u['narrative_source']}"

    def _summary_assemble(u):
        s = u["scorecard"]
        return f"{s['effort_allocation']['tier']}, confidence {s['estimates']['confidence_level']}"

    graph = StateGraph(WorkflowState)
    graph.add_node("validate_input", _instrumented("validate_input", validate_input, _summary_validate))
    graph.add_node("sql_baseline", _instrumented("sql_baseline", sql_baseline, _summary_baseline))
    graph.add_node("analogue_retrieval", _instrumented("analogue_retrieval", analogue_retrieval, _summary_analogues))
    graph.add_node("llm_synthesis", _instrumented("llm_synthesis", llm_synthesis, _summary_llm))
    graph.add_node("assemble_scorecard", _instrumented("assemble_scorecard", assemble_scorecard, _summary_assemble))
    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "sql_baseline")
    graph.add_edge("sql_baseline", "analogue_retrieval")
    graph.add_edge("analogue_retrieval", "llm_synthesis")
    graph.add_edge("llm_synthesis", "assemble_scorecard")
    graph.add_edge("assemble_scorecard", END)
    return graph.compile()


def run_workflow(graph, deal: dict, llm_selection: dict, emit: Optional[Callable[[dict], None]] = None) -> dict:
    emit = emit or (lambda _event: None)
    model = llm_selection.get("model") or (
        llm_mod.PROVIDER_CATALOG[llm_selection["provider"]]["default_model"]
        if llm_selection["provider"] != "template"
        else None
    )
    emit({"type": "run_start", "provider": llm_selection["provider"], "model": model, "ts": time.time()})
    result = graph.invoke(
        {"deal": deal, "llm": llm_selection, "warnings": []},
        config={"configurable": {"emit": emit}},
    )
    return result["scorecard"]


def graph_spec(graph) -> dict[str, Any]:
    drawn = graph.get_graph()
    return {
        "nodes": list(drawn.nodes.keys()),
        "edges": [{"source": e.source, "target": e.target} for e in drawn.edges],
    }
