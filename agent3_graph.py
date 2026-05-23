# Imports
# Agent 3 scans high-contact customers, computes churn risk, estimates value,
# drafts retention offers, and writes a prioritized retention queue.
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None


load_dotenv()

DEFAULT_DB_PATH = "support.db"
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TIER_WEIGHTS = {"regular": 1.0, "prime": 1.5, "prime_plus": 2.0}


# State definition (TypedDict/Pydantic)
# This state keeps every customer-risk step visible for debugging and demos.
class Agent3State(TypedDict, total=False):
    db_path: str
    end_date: str
    lookback_days: int
    start_date: str
    min_ticket_count: int
    churn_threshold: float
    max_customers: int
    high_contact_customers: List[Dict[str, Any]]
    profiles: List[Dict[str, Any]]
    scored_customers: List[Dict[str, Any]]
    retention_queue: List[Dict[str, Any]]
    agent_steps: List[str]


# Tool functions
# These mirror the implementation plan: get high-contact customers, build profiles,
# compute churn score, estimate lifetime value, draft offers, and persist queue rows.
def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def ensure_agent3_tables(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS retention_queue (
                queue_id TEXT PRIMARY KEY,
                customer_id TEXT,
                customer_name TEXT,
                customer_tier TEXT,
                customer_country TEXT,
                language TEXT,
                ticket_count INTEGER,
                unresolved_count INTEGER,
                is_repeat INTEGER,
                top_issue TEXT,
                churn_score REAL,
                lifetime_value REAL,
                retention_priority REAL,
                drafted_offer TEXT,
                profile_json TEXT,
                active INTEGER DEFAULT 1,
                window_start TEXT,
                window_end TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()


def window_start_date(end_date: str, lookback_days: int) -> str:
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def get_high_contact_customers(
    db_path: str,
    start_date: str,
    end_date: str,
    min_ticket_count: int,
    max_customers: int,
) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT customer_id,
                   MAX(customer_name) AS customer_name,
                   MAX(customer_tier) AS customer_tier,
                   COUNT(1) AS ticket_count
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND customer_id IS NOT NULL
              AND TRIM(customer_id) != ''
            GROUP BY customer_id
            HAVING ticket_count >= ?
            ORDER BY ticket_count DESC
            LIMIT ?
            """,
            (start_date, end_date, min_ticket_count, max_customers * 4),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_customer_profile(db_path: str, customer_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticket_id, timestamp, customer_id, customer_name, customer_tier,
                   customer_country, language, category, sub_category, resolution_status,
                   frustration_level, is_repeat_contact, order_value, summary
            FROM tickets
            WHERE customer_id = ?
              AND substr(timestamp, 1, 10) BETWEEN ? AND ?
            ORDER BY timestamp DESC
            """,
            (customer_id, start_date, end_date),
        ).fetchall()

    tickets = [row_to_dict(row) for row in rows]
    if not tickets:
        return {"customer_id": customer_id, "tickets": []}

    latest = tickets[0]
    issue_counts: Dict[str, int] = {}
    for ticket in tickets:
        issue = ticket.get("category") or "unknown"
        issue_counts[issue] = issue_counts.get(issue, 0) + 1
    top_issue = sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)[0][0]

    return {
        "customer_id": customer_id,
        "customer_name": latest.get("customer_name"),
        "customer_tier": latest.get("customer_tier") or "regular",
        "customer_country": latest.get("customer_country"),
        "language": latest.get("language"),
        "top_issue": top_issue,
        "tickets": tickets,
    }


def compute_churn_score(profile: Dict[str, Any]) -> Dict[str, Any]:
    tickets = profile.get("tickets", [])
    ticket_count = len(tickets)
    unresolved_count = sum(
        1
        for ticket in tickets
        if ticket.get("resolution_status") in {"unresolved", "escalated", "pending"}
    )
    is_repeat = any(str(ticket.get("is_repeat_contact")).lower() == "true" for ticket in tickets)
    tier_weight = TIER_WEIGHTS.get(profile.get("customer_tier") or "regular", 1.0)
    churn_score = (ticket_count * 0.30) + (unresolved_count * 0.40) + (int(is_repeat) * 0.20) + (tier_weight * 0.10)
    return {
        "ticket_count": ticket_count,
        "unresolved_count": unresolved_count,
        "is_repeat": int(is_repeat),
        "churn_score": round(churn_score, 3),
    }


def compute_lifetime_value(profile: Dict[str, Any], end_date: str) -> float:
    end = datetime.strptime(end_date, "%Y-%m-%d")
    lifetime_value = 0.0
    for ticket in profile.get("tickets", []):
        value = float(ticket.get("order_value") or 0)
        ticket_date = datetime.strptime(str(ticket["timestamp"])[:10], "%Y-%m-%d")
        age_days = max((end - ticket_date).days, 0)
        recency_weight = max(0.35, 1 - (age_days / 365))
        lifetime_value += value * recency_weight
    return round(lifetime_value, 2)


def fallback_retention_offer(profile: Dict[str, Any], score: Dict[str, Any], lifetime_value: float) -> str:
    name = profile.get("customer_name") or "there"
    tier = profile.get("customer_tier") or "regular"
    issue = profile.get("top_issue") or "recent support issues"

    if issue == "delivery":
        action = "priority delivery monitoring and direct tracking updates on your next orders"
    elif issue == "refund_return":
        action = "priority refund review and a faster return-processing check on your open cases"
    elif issue == "payment_billing":
        action = "a billing specialist review and a goodwill Amazon Pay credit after verification"
    elif issue == "product_quality":
        action = "priority replacement support and a quality-check escalation for the affected products"
    else:
        action = "priority support review from a senior customer-care agent"

    return (
        f"Hi {name}, we noticed repeated {issue} concerns on your account and want to make this right. "
        f"As a {tier} customer, we are assigning {action}. "
        f"Your case has been prioritized because your churn risk score is {score['churn_score']} "
        f"and your recent order value is Rs. {lifetime_value:,.0f}."
    )


def clean_retention_offer(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("subject:"):
            continue
        if lower in {"best,", "best", "regards,", "regards", "sincerely,"}:
            continue
        if "[your name]" in lower or "customer support team" in lower:
            continue
        lines.append(line)
    cleaned = " ".join(lines)
    return cleaned[:900] if cleaned else text[:900]


def get_chat_model() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed. Run: pip install -r requirements.txt")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.25)


def draft_retention_offer(profile: Dict[str, Any], score: Dict[str, Any], lifetime_value: float) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_retention_offer(profile, score, lifetime_value)

    sample_issues = "\n".join(
        f"- {ticket.get('category')} / {ticket.get('sub_category')} | {ticket.get('resolution_status')} | {ticket.get('summary')}"
        for ticket in profile.get("tickets", [])[:5]
    )
    prompt = f"""
Write one concise retention offer message for a high-risk e-commerce customer.
Do not overpromise refunds. Be empathetic and concrete.
Return only the message body, no subject line, no signature, no placeholder names.

Customer name: {profile.get('customer_name')}
Tier: {profile.get('customer_tier')}
Top issue: {profile.get('top_issue')}
Churn score: {score['churn_score']}
Recent lifetime value: {lifetime_value}
Ticket count: {score['ticket_count']}
Open/unresolved count: {score['unresolved_count']}

Recent issue history:
{sample_issues}
""".strip()

    try:
        response = get_chat_model().invoke(prompt)
        return clean_retention_offer(response.content.strip())
    except Exception as exc:
        print(f"Agent 3 offer fallback because: {exc}")
        return fallback_retention_offer(profile, score, lifetime_value)


def write_to_retention_queue(
    db_path: str,
    profile: Dict[str, Any],
    score: Dict[str, Any],
    lifetime_value: float,
    retention_priority: float,
    offer: str,
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    ensure_agent3_tables(db_path)
    stable_key = f"{profile['customer_id']}-{start_date}-{end_date}"
    queue_id = "RET-" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex[:10].upper()
    row = {
        "queue_id": queue_id,
        "customer_id": profile["customer_id"],
        "customer_name": profile.get("customer_name"),
        "customer_tier": profile.get("customer_tier"),
        "customer_country": profile.get("customer_country"),
        "language": profile.get("language"),
        "ticket_count": score["ticket_count"],
        "unresolved_count": score["unresolved_count"],
        "is_repeat": score["is_repeat"],
        "top_issue": profile.get("top_issue"),
        "churn_score": score["churn_score"],
        "lifetime_value": lifetime_value,
        "retention_priority": round(retention_priority, 3),
        "drafted_offer": offer,
        "profile_json": json.dumps(profile),
        "active": 1,
        "window_start": start_date,
        "window_end": end_date,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO retention_queue (
                queue_id, customer_id, customer_name, customer_tier, customer_country,
                language, ticket_count, unresolved_count, is_repeat, top_issue,
                churn_score, lifetime_value, retention_priority, drafted_offer,
                profile_json, active, window_start, window_end, created_at
            )
            VALUES (
                :queue_id, :customer_id, :customer_name, :customer_tier, :customer_country,
                :language, :ticket_count, :unresolved_count, :is_repeat, :top_issue,
                :churn_score, :lifetime_value, :retention_priority, :drafted_offer,
                :profile_json, :active, :window_start, :window_end, :created_at
            )
            """,
            row,
        )
        conn.commit()
    public_row = dict(row)
    public_row.pop("profile_json", None)
    public_row["is_repeat"] = bool(public_row["is_repeat"])
    public_row["active"] = bool(public_row["active"])
    return public_row


# Agent/helper functions
# Nodes print short updates to make the nightly scan explainable.
def add_step(state: Agent3State, message: str) -> Agent3State:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    print(f"[Agent 3] {message}")
    return state


def node_get_high_contact_customers(state: Agent3State) -> Agent3State:
    ensure_agent3_tables(state.get("db_path", DEFAULT_DB_PATH))
    start_date = window_start_date(state["end_date"], state["lookback_days"])
    state["start_date"] = start_date
    customers = get_high_contact_customers(
        state["db_path"],
        start_date,
        state["end_date"],
        state["min_ticket_count"],
        state["max_customers"],
    )
    state["high_contact_customers"] = customers
    return add_step(state, f"Found {len(customers)} customers with at least {state['min_ticket_count']} tickets from {start_date} to {state['end_date']}.")


def node_get_customer_profiles(state: Agent3State) -> Agent3State:
    profiles = [
        get_customer_profile(state["db_path"], customer["customer_id"], state["start_date"], state["end_date"])
        for customer in state.get("high_contact_customers", [])
    ]
    state["profiles"] = [profile for profile in profiles if profile.get("tickets")]
    return add_step(state, f"Loaded {len(state['profiles'])} customer profiles with full ticket history.")


def node_score_customers(state: Agent3State) -> Agent3State:
    scored = []
    for profile in state.get("profiles", []):
        score = compute_churn_score(profile)
        lifetime_value = compute_lifetime_value(profile, state["end_date"])
        retention_priority = score["churn_score"] * math.log(lifetime_value + 1)
        if score["churn_score"] > state["churn_threshold"]:
            scored.append(
                {
                    "profile": profile,
                    "score": score,
                    "lifetime_value": lifetime_value,
                    "retention_priority": round(retention_priority, 3),
                }
            )
    scored.sort(key=lambda item: item["retention_priority"], reverse=True)
    state["scored_customers"] = scored[: state["max_customers"]]
    return add_step(state, f"Scored customers and selected {len(state['scored_customers'])} above churn threshold {state['churn_threshold']}.")


def node_draft_offers(state: Agent3State) -> Agent3State:
    queue_rows = []
    for item in state.get("scored_customers", []):
        offer = draft_retention_offer(item["profile"], item["score"], item["lifetime_value"])
        queue_rows.append({**item, "drafted_offer": offer})
        add_step(state, f"Drafted retention offer for {item['profile'].get('customer_name')} with churn_score={item['score']['churn_score']}.")
    state["retention_queue"] = queue_rows
    return state


def node_write_queue(state: Agent3State) -> Agent3State:
    persisted = []
    for item in state.get("retention_queue", []):
        row = write_to_retention_queue(
            state["db_path"],
            item["profile"],
            item["score"],
            item["lifetime_value"],
            item["retention_priority"],
            item["drafted_offer"],
            state["start_date"],
            state["end_date"],
        )
        persisted.append(row)
    state["retention_queue"] = persisted
    return add_step(state, f"Wrote {len(persisted)} customers to the retention queue.")


def run_agent3_customer_risk(
    db_path: str = DEFAULT_DB_PATH,
    end_date: str = "2025-01-31",
    lookback_days: int = 90,
    min_ticket_count: int = 2,
    churn_threshold: float = 3.0,
    max_customers: int = 20,
) -> Agent3State:
    initial_state: Agent3State = {
        "db_path": db_path,
        "end_date": end_date,
        "lookback_days": lookback_days,
        "min_ticket_count": min_ticket_count,
        "churn_threshold": churn_threshold,
        "max_customers": max_customers,
        "agent_steps": [],
    }
    return app.invoke(initial_state)


# Graph initialization
# Create the Agent 3 LangGraph workflow.
graph = StateGraph(Agent3State)


# Add nodes
# Register each customer-risk step as a graph node.
graph.add_node("get_high_contact_customers", node_get_high_contact_customers)
graph.add_node("get_customer_profiles", node_get_customer_profiles)
graph.add_node("score_customers", node_score_customers)
graph.add_node("draft_retention_offers", node_draft_offers)
graph.add_node("write_retention_queue", node_write_queue)


# Add edges
# Agent 3 runs linearly from customer scan to persisted queue.
graph.set_entry_point("get_high_contact_customers")
graph.add_edge("get_high_contact_customers", "get_customer_profiles")
graph.add_edge("get_customer_profiles", "score_customers")
graph.add_edge("score_customers", "draft_retention_offers")
graph.add_edge("draft_retention_offers", "write_retention_queue")
graph.add_edge("write_retention_queue", END)


# Compile graph
# The compiled app is imported by FastAPI and can also be run directly.
app = graph.compile()


# Visualize graph using IPython display + Mermaid/PNG
# Run this file directly or paste this block into a notebook to see the graph.
if __name__ == "__main__":
    from IPython.display import Image, display

    display(Image(app.get_graph().draw_mermaid_png()))

    # Invoke graph with sample input
    final_state = run_agent3_customer_risk(DEFAULT_DB_PATH)
    print(json.dumps(final_state, indent=2, default=str))
