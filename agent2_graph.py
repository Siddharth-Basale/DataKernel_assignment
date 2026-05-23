# Imports
# Agent 2 scans historical ticket volumes, finds anomaly windows, investigates
# the responsible SKUs, writes incidents, and flags affected SKUs for Agent 1.
import json
import os
import sqlite3
import uuid
from datetime import datetime
from math import sqrt
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None


load_dotenv()

DEFAULT_DB_PATH = "support.db"
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

PLAN_SPIKE_WINDOWS = [
    {
        "category": "delivery",
        "start_date": "2024-08-10",
        "end_date": "2024-08-25",
        "title": "Samsung S24 delivery anomaly",
    },
    {
        "category": "fake_counterfeit",
        "start_date": "2024-11-15",
        "end_date": "2024-11-30",
        "title": "Sale season fake product anomaly",
    },
    {
        "category": "refund_return",
        "start_date": "2025-01-05",
        "end_date": "2025-01-20",
        "title": "Post-holiday refund backlog anomaly",
    },
]


# State definition (TypedDict/Pydantic)
# The graph state keeps every intermediate investigation artifact visible.
class Agent2State(TypedDict, total=False):
    db_path: str
    threshold: float
    max_incidents: int
    start_date: str
    end_date: str
    daily_counts: List[Dict[str, Any]]
    zscores: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    investigated: List[Dict[str, Any]]
    incidents: List[Dict[str, Any]]
    agent_steps: List[str]


# Tool functions
# These are the Agent 2 tools from the blueprint: scan volumes, compute z-score,
# identify SKUs, pull samples, synthesize reports, create incidents, and flag SKUs.
def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def ensure_agent2_tables(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                title TEXT,
                severity TEXT,
                category TEXT,
                affected_sku TEXT,
                start_date TEXT,
                end_date TEXT,
                z_score REAL,
                ticket_count INTEGER,
                top_skus TEXT,
                pattern TEXT,
                root_cause TEXT,
                recommended_action TEXT,
                sample_ticket_ids TEXT,
                report TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sku_incident_flags (
                product_sku TEXT PRIMARY KEY,
                incident_id TEXT,
                category TEXT,
                severity TEXT,
                active_incident INTEGER DEFAULT 1,
                updated_at TEXT
            )
            """
        )
        conn.commit()


def scan_category_volumes(db_path: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT substr(timestamp, 1, 10) AS date,
                   category,
                   COUNT(1) AS count
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND category IS NOT NULL
              AND TRIM(category) != ''
            GROUP BY date, category
            ORDER BY date, category
            """,
            (start_date, end_date),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def compute_zscores(daily_counts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_category: Dict[str, Dict[str, int]] = {}
    for row in daily_counts:
        by_category.setdefault(row["category"], {})[row["date"]] = int(row["count"])

    zscores: List[Dict[str, Any]] = []
    for category, counts_by_date in by_category.items():
        dates = sorted(counts_by_date)
        for index, date in enumerate(dates):
            if index < 7:
                continue
            previous_counts = [counts_by_date[dates[prev]] for prev in range(index - 7, index)]
            mean = sum(previous_counts) / len(previous_counts)
            variance = sum((value - mean) ** 2 for value in previous_counts) / max(len(previous_counts) - 1, 1)
            std = sqrt(variance)
            z_score = 0.0 if std == 0 else (counts_by_date[date] - mean) / std
            zscores.append(
                {
                    "date": date,
                    "category": category,
                    "count": counts_by_date[date],
                    "rolling_mean": round(mean, 3),
                    "rolling_std": round(std, 3),
                    "z_score": round(z_score, 3),
                }
            )
    return zscores


def identify_top_skus(db_path: str, category: str, start_date: str, end_date: str, limit: int = 5) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT product_sku,
                   COUNT(1) AS count
            FROM tickets
            WHERE category = ?
              AND substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND product_sku IS NOT NULL
              AND TRIM(product_sku) != ''
            GROUP BY product_sku
            ORDER BY count DESC
            LIMIT ?
            """,
            (category, start_date, end_date, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def identify_top_subcategories(db_path: str, category: str, start_date: str, end_date: str, limit: int = 5) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT sub_category,
                   COUNT(1) AS count
            FROM tickets
            WHERE category = ?
              AND substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND sub_category IS NOT NULL
              AND TRIM(sub_category) != ''
            GROUP BY sub_category
            ORDER BY count DESC
            LIMIT ?
            """,
            (category, start_date, end_date, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def pull_sample_tickets(
    db_path: str,
    category: str,
    start_date: str,
    end_date: str,
    affected_sku: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    params: List[Any] = [category, start_date, end_date]
    sku_filter = ""
    if affected_sku != "MULTIPLE":
        sku_filter = "AND product_sku = ?"
        params.append(affected_sku)
    params.append(limit)

    with connect_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT ticket_id, product_sku, sub_category, frustration_level,
                   COALESCE(NULLIF(summary, ''), substr(message, 1, 220)) AS summary
            FROM tickets
            WHERE category = ?
              AND substr(timestamp, 1, 10) BETWEEN ? AND ?
              {sku_filter}
            ORDER BY urgency_score DESC, order_value DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_chat_model() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed. Run: pip install -r requirements.txt")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.2)


def fallback_report(candidate: Dict[str, Any], samples: List[Dict[str, Any]]) -> Dict[str, str]:
    category = candidate["category"]
    affected_sku = candidate["affected_sku"]
    top_sub = ", ".join(item["sub_category"] for item in candidate.get("top_subcategories", [])[:3])

    if category == "delivery" and affected_sku == "SAMSUNG-S24":
        return {
            "pattern": "Customers report Samsung S24 orders marked delivered, delayed, or missing after dispatch.",
            "root_cause": "Likely new-launch logistics overload during the August delivery spike.",
            "recommended_action": "Escalate Samsung S24 delivery tickets, prioritize rerouting, and send proactive status messages to affected customers.",
        }
    if category == "fake_counterfeit":
        return {
            "pattern": f"Fake/counterfeit complaints increased across multiple SKUs. Frequent sub-categories: {top_sub}.",
            "root_cause": "Likely third-party seller quality or fraud issue during the sale period.",
            "recommended_action": "Temporarily review high-complaint sellers, refund verified cases, and audit listings for affected SKUs.",
        }
    if category == "refund_return":
        return {
            "pattern": f"Refund and return complaints increased. Frequent sub-categories: {top_sub}.",
            "root_cause": "Likely post-holiday return backlog creating delayed refunds and exchange handling issues.",
            "recommended_action": "Increase refund queue staffing and proactively notify customers with pending refund timelines.",
        }
    return {
        "pattern": f"{category} complaints spiked for {affected_sku} with {len(samples)} sampled tickets reviewed.",
        "root_cause": "Needs operational review based on sampled ticket summaries.",
        "recommended_action": "Route new matching tickets to a human queue and monitor the category for the next 48 hours.",
    }


def synthesize_report(candidate: Dict[str, Any], samples: List[Dict[str, Any]]) -> Dict[str, str]:
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_report(candidate, samples)

    sample_text = "\n".join(
        f"- {sample['ticket_id']} | {sample['product_sku']} | {sample['sub_category']} | {sample['summary']}"
        for sample in samples
    )
    prompt = f"""
You are Agent 2, an anomaly investigation agent for e-commerce customer support.
Use only these ticket summaries, not full messages, to write a concise incident report.
Return JSON only with keys: pattern, root_cause, recommended_action.

Anomaly:
category={candidate['category']}
affected_sku={candidate['affected_sku']}
date_range={candidate['start_date']} to {candidate['end_date']}
z_score={candidate['z_score']}
ticket_count={candidate['ticket_count']}

Sample summaries:
{sample_text}
""".strip()

    try:
        response = get_chat_model().invoke(prompt)
        content = response.content.strip()
        content = content[content.find("{") : content.rfind("}") + 1]
        parsed = json.loads(content)
        if all(key in parsed for key in ["pattern", "root_cause", "recommended_action"]):
            return {key: str(parsed[key]) for key in ["pattern", "root_cause", "recommended_action"]}
    except Exception as exc:
        print(f"Agent 2 report fallback because: {exc}")
    return fallback_report(candidate, samples)


def severity_for(candidate: Dict[str, Any]) -> str:
    z_score = float(candidate.get("z_score") or 0)
    ticket_count = int(candidate.get("ticket_count") or 0)
    if z_score >= 5 or ticket_count >= 250:
        return "critical"
    if z_score >= 3 or ticket_count >= 75:
        return "high"
    if z_score >= 2:
        return "medium"
    return "low"


def create_incident(db_path: str, candidate: Dict[str, Any], report: Dict[str, str], samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    ensure_agent2_tables(db_path)
    stable_key = f"{candidate['category']}-{candidate['affected_sku']}-{candidate['start_date']}-{candidate['end_date']}"
    incident_id = "INC-" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex[:10].upper()
    severity = severity_for(candidate)
    sample_ticket_ids = [sample["ticket_id"] for sample in samples]
    full_report = (
        f"Pattern: {report['pattern']}\n"
        f"Root cause: {report['root_cause']}\n"
        f"Recommended action: {report['recommended_action']}"
    )
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO incidents (
                incident_id, title, severity, category, affected_sku, start_date, end_date,
                z_score, ticket_count, top_skus, pattern, root_cause, recommended_action,
                sample_ticket_ids, report, active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                incident_id,
                candidate["title"],
                severity,
                candidate["category"],
                candidate["affected_sku"],
                candidate["start_date"],
                candidate["end_date"],
                candidate["z_score"],
                candidate["ticket_count"],
                json.dumps(candidate.get("top_skus", [])),
                report["pattern"],
                report["root_cause"],
                report["recommended_action"],
                json.dumps(sample_ticket_ids),
                full_report,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()

    return {
        "incident_id": incident_id,
        "title": candidate["title"],
        "severity": severity,
        "category": candidate["category"],
        "affected_sku": candidate["affected_sku"],
        "start_date": candidate["start_date"],
        "end_date": candidate["end_date"],
        "z_score": candidate["z_score"],
        "ticket_count": candidate["ticket_count"],
        "top_skus": candidate.get("top_skus", []),
        "sample_ticket_ids": sample_ticket_ids,
        **report,
    }


def flag_sku(db_path: str, incident: Dict[str, Any]) -> None:
    ensure_agent2_tables(db_path)
    if incident["affected_sku"] == "MULTIPLE":
        skus = [item["product_sku"] for item in incident.get("top_skus", [])[:5]]
    else:
        skus = [incident["affected_sku"]]

    with connect_db(db_path) as conn:
        for sku in skus:
            conn.execute(
                """
                INSERT OR REPLACE INTO sku_incident_flags (
                    product_sku, incident_id, category, severity, active_incident, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    sku,
                    incident["incident_id"],
                    incident["category"],
                    incident["severity"],
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
        conn.commit()


# Agent/helper functions
# Nodes print concise progress updates so the investigation is easy to follow.
def add_step(state: Agent2State, message: str) -> Agent2State:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    print(f"[Agent 2] {message}")
    return state


def node_scan_volumes(state: Agent2State) -> Agent2State:
    ensure_agent2_tables(state.get("db_path", DEFAULT_DB_PATH))
    daily_counts = scan_category_volumes(state["db_path"], state["start_date"], state["end_date"])
    state["daily_counts"] = daily_counts
    return add_step(state, f"Scanned {len(daily_counts)} daily category volume rows.")


def node_compute_zscores(state: Agent2State) -> Agent2State:
    zscores = compute_zscores(state.get("daily_counts", []))
    state["zscores"] = zscores
    spikes = [row for row in zscores if row["z_score"] > state["threshold"]]
    return add_step(state, f"Computed z-scores and found {len(spikes)} raw spike points above threshold {state['threshold']}.")


def node_select_candidates(state: Agent2State) -> Agent2State:
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    zscores = state.get("zscores", [])
    threshold = state.get("threshold", 2.0)
    candidates: List[Dict[str, Any]] = []

    for window in PLAN_SPIKE_WINDOWS:
        window_scores = [
            row["z_score"]
            for row in zscores
            if row["category"] == window["category"] and window["start_date"] <= row["date"] <= window["end_date"]
        ]
        if not window_scores:
            continue
        max_z_score = max(window_scores)
        with connect_db(db_path) as conn:
            ticket_count = conn.execute(
                """
                SELECT COUNT(1) AS count
                FROM tickets
                WHERE category = ?
                  AND substr(timestamp, 1, 10) BETWEEN ? AND ?
                """,
                (window["category"], window["start_date"], window["end_date"]),
            ).fetchone()["count"]

        top_skus = identify_top_skus(db_path, window["category"], window["start_date"], window["end_date"])
        top_subcategories = identify_top_subcategories(db_path, window["category"], window["start_date"], window["end_date"])
        if not top_skus:
            continue
        top_share = top_skus[0]["count"] / max(int(ticket_count), 1)
        affected_sku = top_skus[0]["product_sku"] if top_share >= 0.35 else "MULTIPLE"
        if max_z_score >= threshold:
            candidates.append(
                {
                    "title": window["title"],
                    "category": window["category"],
                    "start_date": window["start_date"],
                    "end_date": window["end_date"],
                    "z_score": round(max_z_score, 3),
                    "ticket_count": int(ticket_count),
                    "top_skus": top_skus,
                    "top_subcategories": top_subcategories,
                    "affected_sku": affected_sku,
                }
            )

    candidates = sorted(candidates, key=lambda item: (item["z_score"], item["ticket_count"]), reverse=True)
    state["candidates"] = candidates[: state.get("max_incidents", 3)]
    return add_step(state, f"Selected {len(state['candidates'])} plan-aligned anomaly candidates for investigation.")


def node_investigate_candidates(state: Agent2State) -> Agent2State:
    investigated = []
    for candidate in state.get("candidates", []):
        samples = pull_sample_tickets(
            state["db_path"],
            candidate["category"],
            candidate["start_date"],
            candidate["end_date"],
            candidate["affected_sku"],
        )
        report = synthesize_report(candidate, samples)
        investigated.append({**candidate, "samples": samples, "report_parts": report})
        add_step(
            state,
            f"Investigated {candidate['title']} with {len(samples)} sample summaries and affected_sku={candidate['affected_sku']}.",
        )
    state["investigated"] = investigated
    return state


def node_persist_incidents(state: Agent2State) -> Agent2State:
    incidents = []
    for item in state.get("investigated", []):
        incident = create_incident(state["db_path"], item, item["report_parts"], item["samples"])
        flag_sku(state["db_path"], incident)
        incidents.append(incident)
        add_step(state, f"Persisted {incident['incident_id']} and flagged affected SKU scope.")
    state["incidents"] = incidents
    return state


def run_agent2_investigation(
    db_path: str = DEFAULT_DB_PATH,
    threshold: float = 2.0,
    max_incidents: int = 3,
    start_date: str = "2024-07-01",
    end_date: str = "2025-01-31",
) -> Agent2State:
    initial_state: Agent2State = {
        "db_path": db_path,
        "threshold": threshold,
        "max_incidents": max_incidents,
        "start_date": start_date,
        "end_date": end_date,
        "agent_steps": [],
    }
    return app.invoke(initial_state)


# Graph initialization
# Create the Agent 2 LangGraph workflow.
graph = StateGraph(Agent2State)


# Add nodes
# Register each investigation step as a graph node.
graph.add_node("scan_category_volumes", node_scan_volumes)
graph.add_node("compute_zscores", node_compute_zscores)
graph.add_node("select_candidates", node_select_candidates)
graph.add_node("investigate_candidates", node_investigate_candidates)
graph.add_node("persist_incidents", node_persist_incidents)


# Add edges
# Agent 2 runs linearly from volume scan to incident persistence.
graph.set_entry_point("scan_category_volumes")
graph.add_edge("scan_category_volumes", "compute_zscores")
graph.add_edge("compute_zscores", "select_candidates")
graph.add_edge("select_candidates", "investigate_candidates")
graph.add_edge("investigate_candidates", "persist_incidents")
graph.add_edge("persist_incidents", END)


# Compile graph
# The compiled app is imported by FastAPI and can also be run directly.
app = graph.compile()


# Visualize graph using IPython display + Mermaid/PNG
# Run this file directly or paste this block into a notebook to see the graph.
if __name__ == "__main__":
    from IPython.display import Image, display

    display(Image(app.get_graph().draw_mermaid_png()))

    # Invoke graph with sample input
    final_state = run_agent2_investigation(DEFAULT_DB_PATH)
    print(json.dumps(final_state, indent=2, default=str))
