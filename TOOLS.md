# ADK Tools Reference — [PRODUCT_NAME]

## Overview

All 6 tools live in `tools.py`. All read from `config.json` at module level.
All writes to `dashboard_state` use `threading.Lock` from `state.py`.

```python
# Top of tools.py — always
import json
import state

CONFIG = json.load(open('config.json'))
```

ADK uses the **docstring** of each function to decide when to call it.
Never remove or shorten docstrings.

---

## Tool 1 — get_product_info

```python
def get_product_info(plan: str) -> dict:
    """
    Get detailed information about a [PRODUCT_NAME] pricing plan.
    Use when the customer asks what a specific plan includes or what
    features are available at a given tier.
    """
    plans = {p['name'].lower(): p for p in CONFIG['plans']}
    result = plans.get(plan.lower())
    if not result:
        return {'error': f'Plan {plan} not found', 'available': list(plans.keys())}
    _log_tool_call('get_product_info', f'plan={plan}', result['name'])
    return result
```

**Returns:**
```json
{
  "name": "Professional",
  "price_monthly": 799,
  "user_limit": 15,
  "features": ["Unlimited comp analysis", "Full client portal", "..."],
  "ideal_for": "Regional brokerage firms with 5-15 brokers"
}
```

---

## Tool 2 — calculate_price

```python
def calculate_price(plan: str, num_users: int) -> dict:
    """
    Calculate the monthly and annual cost for a specific plan and team size.
    Call this when a customer asks how much it would cost for their team,
    or requests a custom quote. Always call this rather than doing the math
    in conversation — it ensures accuracy.
    """
    plans = {p['name'].lower(): p for p in CONFIG['plans']}
    plan_data = plans.get(plan.lower())
    if not plan_data:
        return {'error': f'Plan {plan} not found'}

    monthly = plan_data['price_monthly']
    annual = round(monthly * 12 * 0.85, 2)  # 15% annual discount
    per_user = round(monthly / max(num_users, 1), 2)

    result = {
        'plan': plan_data['name'],
        'num_users': num_users,
        'monthly_cost': monthly,
        'annual_cost': annual,
        'per_user_monthly': per_user,
        'annual_savings': round(monthly * 12 - annual, 2),
        'user_limit': plan_data['user_limit']
    }
    _log_tool_call('calculate_price', f'plan={plan}, users={num_users}', f'${monthly}/mo')
    return result
```

**Returns:**
```json
{
  "plan": "Professional",
  "num_users": 12,
  "monthly_cost": 799,
  "annual_cost": 8150.0,
  "per_user_monthly": 66.58,
  "annual_savings": 439.0,
  "user_limit": 15
}
```

---

## Tool 3 — compare_competitor

```python
def compare_competitor(competitor_name: str) -> dict:
    """
    Get an honest comparison between [PRODUCT_NAME] and a named competitor.
    Call this whenever a customer mentions a competitor by name, asks how we
    compare, or shows competitor pricing. Always call rather than relying on
    memory. For CoStar specifically: emphasize complementary positioning —
    [PRODUCT_NAME] sits on top of CoStar, not against it.
    """
    competitors = {c['name'].lower(): c for c in CONFIG['competitors']}
    result = competitors.get(competitor_name.lower())
    if not result:
        # Fuzzy match attempt
        for key, val in competitors.items():
            if competitor_name.lower() in key or key in competitor_name.lower():
                result = val
                break
    if not result:
        return {'error': f'Competitor {competitor_name} not found',
                'available': list(competitors.keys())}

    _log_tool_call('compare_competitor', f'competitor={competitor_name}', result['talking_point'][:50])
    return result
```

**Returns:**
```json
{
  "name": "Salesforce",
  "price": "$150/user/mo",
  "we_win": ["Live in one day", "No consultant needed", "CRE-specific out of the box"],
  "they_win": ["Larger ecosystem"],
  "talking_point": "Salesforce needs months and a consultant. We are live tomorrow."
}
```

---

## Tool 4 — generate_recommendation

```python
def generate_recommendation(team_size: int, pain_points: list, budget_range: str) -> dict:
    """
    Generate a personalized plan recommendation based on the customer's profile.
    Call this when the customer asks what you'd recommend, or when they signal
    they are ready to make a decision. Always tie the recommendation to their
    specific team size and the pain points they mentioned during discovery.
    """
    plans = CONFIG['plans']
    roi = CONFIG['roi_data']

    # Find smallest plan that fits team size
    recommended = None
    for plan in sorted(plans, key=lambda p: p['price_monthly']):
        if plan['user_limit'] >= team_size or plan['user_limit'] == 999:
            recommended = plan
            break

    if not recommended:
        recommended = plans[-1]  # Enterprise as fallback

    # Adjust: push toward Professional if comp/reporting pain
    if recommended['name'] == 'Starter':
        if any(p in ['comp_analysis', 'reporting', 'client_portal'] for p in pain_points):
            recommended = next(p for p in plans if p['name'] == 'Professional')

    # Adjust: down if tight budget and small team
    if budget_range == 'tight' and team_size <= 3:
        recommended = plans[0]  # Starter

    # ROI calculation
    monthly_hours_saved = roi['hours_saved_per_report'] * roi['reports_per_broker_per_month'] * team_size
    annual_roi = round((monthly_hours_saved * 12 * 75) - (recommended['price_monthly'] * 12), 0)
    # $75/hr assumed broker time value

    result = {
        'recommended_plan': recommended['name'],
        'monthly_cost': recommended['price_monthly'],
        'annual_cost': round(recommended['price_monthly'] * 12 * 0.85, 0),
        'team_size': team_size,
        'key_reasons': [
            f"Supports up to {recommended['user_limit']} brokers — fits your team",
            *[f for f in recommended['features'][:2]]
        ],
        'pain_points_addressed': pain_points,
        'roi_calculation': {
            'monthly_hours_saved': monthly_hours_saved,
            'annual_value': annual_roi,
            'payback_months': roi['payback_months']
        },
        'suggested_next_step': f"Start a 14-day free trial of {recommended['name']} — no credit card required"
    }
    _log_tool_call('generate_recommendation', f'team={team_size}', recommended['name'])
    return result
```

---

## Tool 5 — update_customer_profile

```python
def update_customer_profile(attribute: str, value: str) -> dict:
    """
    Store a piece of information learned about the customer during the conversation.
    Call this immediately whenever the customer reveals anything about their business:
    company name, team size, deal types, current tools, pain points, budget range,
    decision timeline, number of stakeholders, or monthly deal volume.
    Do not wait — call it in the same turn you learn it.
    """
    valid_attributes = [
        'company', 'team_size', 'deal_types', 'current_tools', 'pain_points',
        'budget_range', 'decision_timeline', 'stakeholders', 'deal_volume_monthly',
        'contact_name', 'role'
    ]
    with state._lock:
        state.dashboard_state['profile'][attribute] = value
        state.dashboard_state['strategy'] = f"Profile updated: learned {attribute}"
    _log_tool_call('update_customer_profile', f'{attribute}={value}', 'saved')
    return state.dashboard_state['profile']
```

**Attributes Jordan should capture:**
| Attribute | Example Value | When to Capture |
|-----------|--------------|-----------------|
| company | "Jones Lang LaSalle" | First mention |
| team_size | "12" | When stated |
| deal_types | "office and retail" | When stated |
| current_tools | "CoStar and Excel" | CRITICAL — triggers pitch |
| pain_points | "comp reports take 3-4 hours" | When described |
| budget_range | "flexible" / "tight" | When signaled |
| decision_timeline | "this quarter" | When stated |
| stakeholders | "need to loop in my partner" | When mentioned |
| deal_volume_monthly | "8-10 deals" | When stated |

---

## Tool 6 — update_sales_stage

```python
def update_sales_stage(stage: str, reason: str) -> dict:
    """
    Update the current sales stage as the conversation progresses.
    Call this whenever the conversation moves to a new stage. Include a
    specific reason that explains what triggered the transition — not just
    the stage name. Valid stages: GREETING, DISCOVERY, PITCH,
    OBJECTION_HANDLING, CLOSING, FOLLOW_UP.
    """
    valid_stages = ['GREETING', 'DISCOVERY', 'PITCH', 'OBJECTION_HANDLING', 'CLOSING', 'FOLLOW_UP']
    if stage not in valid_stages:
        return {'error': f'Invalid stage. Must be one of: {valid_stages}'}

    from datetime import datetime
    transition = {
        'stage': stage,
        'reason': reason,
        'timestamp': datetime.now().isoformat()
    }
    with state._lock:
        state.dashboard_state['stage_history'].append(transition)
        state.dashboard_state['stage'] = stage
        state.dashboard_state['strategy'] = reason

    _log_tool_call('update_sales_stage', f'stage={stage}', reason[:60])
    return {
        'current_stage': stage,
        'reason': reason,
        'stage_history': state.dashboard_state['stage_history']
    }
```

**Good reasons (specific):**
- `"Customer confirmed CoStar+Excel workflow — core pain identified"`
- `"Customer asked about Salesforce pricing — entering competitor defense"`
- `"Customer said 'what would you recommend' — moving to close"`

**Bad reasons (vague):**
- `"Moving to pitch"`
- `"Stage change"`

---

## Helper — _log_tool_call

```python
def _log_tool_call(tool_name: str, input_summary: str, result_summary: str):
    """Internal helper — call from every tool to log to dashboard state."""
    from datetime import datetime
    entry = {
        'tool': tool_name,
        'input': input_summary,
        'result': str(result_summary)[:80],
        'timestamp': datetime.now().strftime('%H:%M:%S')
    }
    with state._lock:
        state.dashboard_state['tools_called'].append(entry)
        # Keep last 10 only
        if len(state.dashboard_state['tools_called']) > 10:
            state.dashboard_state['tools_called'] = state.dashboard_state['tools_called'][-10:]
```

---

## Stage Transition Logic (for generate_prompt.py)

```
Signal                          → Tool Call Sequence
──────                            ──────────────────
Customer answers opening Q      → update_sales_stage('DISCOVERY', reason)
Customer mentions team size     → update_customer_profile('team_size', value)
Customer mentions CoStar+Excel  → update_customer_profile('current_tools', value)
                                  update_sales_stage('PITCH', 'Core pain confirmed')
Customer names a competitor     → compare_competitor(name)
Customer asks for price         → calculate_price(plan, num_users)
Customer asks for recommendation→ generate_recommendation(team_size, pains, budget)
                                  update_sales_stage('CLOSING', reason)
Customer signals objection      → update_sales_stage('OBJECTION_HANDLING', reason)
```
