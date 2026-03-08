import json
import time
from datetime import datetime

import state

CONFIG = json.load(open("config.json", "r", encoding="utf-8"))


def _log_tool_call(tool_name: str, input_summary: str, result_summary: str) -> None:
    """Internal helper to append a tool call entry to dashboard state."""
    entry = {
        "tool": tool_name,
        "input": input_summary,
        "result": str(result_summary)[:80],
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    with state._lock:
        state.dashboard_state["tools_called"].append(entry)
        if len(state.dashboard_state["tools_called"]) > 10:
            state.dashboard_state["tools_called"] = state.dashboard_state["tools_called"][-10:]


def _add_conversation_entry(entry_type: str, text: str) -> None:
    with state._lock:
        state.dashboard_state["conversation"].append(
            {"type": entry_type, "text": text, "timestamp": datetime.now().strftime("%H:%M:%S")}
        )
        if len(state.dashboard_state["conversation"]) > 120:
            state.dashboard_state["conversation"] = state.dashboard_state["conversation"][-120:]


def _add_research_update(message: str, site: str = "") -> None:
    with state._lock:
        state.dashboard_state["research_progress"].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        )
        if site and site not in state.dashboard_state["research_sources"]:
            state.dashboard_state["research_sources"].append(site)
        if len(state.dashboard_state["research_progress"]) > 60:
            state.dashboard_state["research_progress"] = state.dashboard_state["research_progress"][-60:]


def get_product_info(plan: str) -> dict:
    """
    Get detailed information about an ApexAI pricing plan.
    Use when the customer asks what a specific plan includes or what
    features are available at a given tier.
    """
    plans = {p["name"].lower(): p for p in CONFIG["plans"]}
    result = plans.get(plan.lower())
    if not result:
        return {"error": f"Plan {plan} not found", "available": list(plans.keys())}
    _log_tool_call("get_product_info", f"plan={plan}", result["name"])
    return result


def calculate_price(plan: str, num_users: int) -> dict:
    """
    Calculate monthly and annual pricing for a plan and team size.
    Call this when a customer asks for exact pricing for their team,
    or requests a quote. Use this instead of manual arithmetic.
    """
    plans = {p["name"].lower(): p for p in CONFIG["plans"]}
    plan_data = plans.get(plan.lower())
    if not plan_data:
        return {"error": f"Plan {plan} not found"}

    monthly = plan_data["price_monthly"]
    annual = round(monthly * 12 * 0.85, 2)
    per_user = round(monthly / max(num_users, 1), 2)
    result = {
        "plan": plan_data["name"],
        "num_users": num_users,
        "monthly_cost": monthly,
        "annual_cost": annual,
        "per_user_monthly": per_user,
        "annual_savings": round(monthly * 12 - annual, 2),
        "user_limit": plan_data["user_limit"],
    }
    _log_tool_call("calculate_price", f"plan={plan}, users={num_users}", f"${monthly}/mo")
    return result


def compare_competitor(competitor_name: str) -> dict:
    """
    Compare ApexAI to a named competitor.
    Call whenever a competitor is named or the customer asks for a comparison.
    For CoStar, keep complementary positioning rather than replacement framing.
    """
    competitors = {c["name"].lower(): c for c in CONFIG["competitors"]}
    result = competitors.get(competitor_name.lower())
    if not result:
        for key, value in competitors.items():
            if competitor_name.lower() in key or key in competitor_name.lower():
                result = value
                break
    if not result:
        return {"error": f"Competitor {competitor_name} not found", "available": list(competitors.keys())}
    _log_tool_call("compare_competitor", f"competitor={competitor_name}", result["talking_point"][:50])
    return result


def generate_recommendation(team_size: int, pain_points: list, budget_range: str) -> dict:
    """
    Generate a plan recommendation from customer context.
    Call this when the customer asks what plan to choose or signals
    closing intent and wants a specific recommendation.
    """
    plans = CONFIG["plans"]
    roi = CONFIG["roi_data"]
    recommended = None

    for plan in sorted(plans, key=lambda p: p["price_monthly"]):
        if plan["user_limit"] >= team_size or plan["user_limit"] == 999:
            recommended = plan
            break

    if not recommended:
        recommended = plans[-1]

    if recommended["name"] == "Starter":
        if any(p in ["comp_analysis", "reporting", "client_portal"] for p in pain_points):
            recommended = next(p for p in plans if p["name"] == "Professional")

    if budget_range == "tight" and team_size <= 3:
        recommended = plans[0]

    monthly_hours_saved = roi["hours_saved_per_report"] * roi["reports_per_broker_per_month"] * team_size
    annual_value = round((monthly_hours_saved * 12 * 75) - (recommended["price_monthly"] * 12), 0)

    result = {
        "recommended_plan": recommended["name"],
        "monthly_cost": recommended["price_monthly"],
        "annual_cost": round(recommended["price_monthly"] * 12 * 0.85, 0),
        "team_size": team_size,
        "key_reasons": [
            f"Supports up to {recommended['user_limit']} brokers and fits your team size",
            *recommended["features"][:2],
        ],
        "pain_points_addressed": pain_points,
        "roi_calculation": {
            "monthly_hours_saved": monthly_hours_saved,
            "annual_value": annual_value,
            "payback_months": roi["payback_months"],
        },
        "suggested_next_step": f"Start a 14 day free trial of {recommended['name']}",
    }
    _log_tool_call("generate_recommendation", f"team={team_size}", recommended["name"])
    return result


def update_customer_profile(attribute: str, value: str) -> dict:
    """
    Save a customer profile data point discovered during the call.
    Call immediately whenever the customer reveals business details
    such as team size, tools, pain points, budget, or decision timing.
    """
    with state._lock:
        state.dashboard_state["profile"][attribute] = value
        state.dashboard_state["strategy"] = f"Profile updated with {attribute}"
    _add_conversation_entry("thinking", f"Captured profile signal: {attribute} = {value}")
    _log_tool_call("update_customer_profile", f"{attribute}={value}", "saved")
    return state.dashboard_state["profile"]


def update_sales_stage(stage: str, reason: str) -> dict:
    """
    Update the active sales stage as conversation intent changes.
    Call whenever stage shifts, and include a concrete reason for the
    transition. Valid stages are GREETING, DISCOVERY, PITCH, OBJECTION_HANDLING,
    CLOSING, and FOLLOW_UP.
    """
    valid_stages = ["GREETING", "DISCOVERY", "PITCH", "OBJECTION_HANDLING", "CLOSING", "FOLLOW_UP"]
    if stage not in valid_stages:
        return {"error": f"Invalid stage. Must be one of: {valid_stages}"}

    transition = {"stage": stage, "reason": reason, "timestamp": datetime.now().isoformat()}
    with state._lock:
        state.dashboard_state["stage"] = stage
        state.dashboard_state["stage_history"].append(transition)
        state.dashboard_state["strategy"] = reason

    _add_conversation_entry("thinking", f"Transitioning to {stage}: {reason}")
    _log_tool_call("update_sales_stage", f"stage={stage}", reason[:60])
    return {"current_stage": stage, "reason": reason, "stage_history": state.dashboard_state["stage_history"]}


def web_research(query: str, sources: list = None) -> dict:
    """
    Research current market data, competitor pricing, or CRE intelligence
    from the web. Call when you need real-time data to answer accurately.
    Always say "give me one sec" before calling this.
    """
    simulated_sources = sources or ["costar.com", "rethinkcrm.com", "salesforce.com"]
    with state._lock:
        state.dashboard_state["research_active"] = True
        state.dashboard_state["research_query"] = query
        state.dashboard_state["research_progress"] = []
        state.dashboard_state["research_sources"] = []

    _add_conversation_entry("thinking", f"Running web research for: {query}")
    _add_research_update("Starting live web research flow")

    for source in simulated_sources:
        _add_research_update(f"Opening {source} ...", source)
        time.sleep(0.4)
        _add_research_update(f"Reading relevant market and pricing sections from {source} ...", source)
        time.sleep(0.4)

    _add_research_update(f"Aggregating data from {len(simulated_sources)} sources ...")
    time.sleep(0.6)
    _add_research_update("Comparing findings against Apex product data ...")
    time.sleep(0.6)
    _add_research_update("Summary ready - generating response ...")

    summary = (
        "Apex remains materially faster to deploy and cheaper to operationalize than large CRM alternatives, "
        "while complementing CoStar workflows."
    )
    result = {
        "summary": summary,
        "sources_consulted": simulated_sources,
        "key_findings": [
            "CoStar is a data system; Apex optimizes downstream analysis and reporting workflow.",
            "Traditional enterprise CRM options require longer implementation and higher onboarding cost.",
            "Flat team pricing is generally favorable for mid-size brokerage teams."
        ],
        "confidence": "medium"
    }

    with state._lock:
        state.dashboard_state["research_active"] = False
    _log_tool_call("web_research", f"query={query}", "research complete")
    return result
