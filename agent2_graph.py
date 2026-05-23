# agent2_graph.py — Anomaly Investigation Agent
# ─────────────────────────────────────────────────────────────────────────────
# KEY FIX: Spike detection is now driven ENTIRELY by Z-score computation.
# The old PLAN_SPIKE_WINDOWS list has been removed. The agent discovers
# anomalies by scanning all categories over the full date range, grouping
# consecutive spike days into windows, then ranking by peak Z-score.
#
# PLAN_SPIKE_WINDOWS is retained only as EXPECTED_SPIKES — a validation
# fixture used in tests to confirm the detector catches the known events.
# It plays NO role in detection logic.
#
# Pipeline:
#   scan_category_volumes
#     → compute_zscores
#       → cluster_spike_windows   ← NEW: groups consecutive spike days
#         → select_candidates     ← CHANGED: ranks by z_score, no hardcoding
#           → investigate_candidates
#             → persist_incidents
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
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

# ── Validation fixture only — NOT used in detection ───────────────────────────
# These are the three known spikes in the dataset. Kept here so the test suite
# can confirm the Z-score detector finds them. Detection code never reads this.
EXPECTED_SPIKES = [
    {"category": "delivery",        "approx_start": "2024-08-10", "approx_end": "2024-08-25"},
    {"category": "fake_counterfeit","approx_start": "2024-11-15", "approx_end": "2024-11-30"},
    {"category": "refund_return",   "approx_start": "2025-01-05", "approx_end": "2025-01-20"},
]

# Minimum gap between two separate spike windows for the same category (days).
# Days closer than this are merged into one continuous window.
SPIKE_MERGE_GAP_DAYS = 3


# ═════════════════════════════════════════════════════════════════════════════
# State
# ═════════════════════════════════════════════════════════════════════════════

class Agent2State(TypedDict, total=False):
    db_path:        str
    threshold:      float           # Z-score threshold to flag a day as a spike
    max_incidents:  int
    start_date:     str
    end_date:       str
    daily_counts:   List[Dict[str, Any]]
    zscores:        List[Dict[str, Any]]
    spike_windows:  List[Dict[str, Any]]   # NEW: clustered spike windows
    candidates:     List[Dict[str, Any]]
    investigated:   List[Dict[str, Any]]
    incidents:      List[Dict[str, Any]]
    agent_steps:    List[str]


# ═════════════════════════════════════════════════════════════════════════════
# DB helpers
# ═════════════════════════════════════════════════════════════════════════════

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
                incident_id    TEXT PRIMARY KEY,
                title          TEXT,
                severity       TEXT,
                category       TEXT,
                affected_sku   TEXT,
                start_date     TEXT,
                end_date       TEXT,
                z_score        REAL,
                ticket_count   INTEGER,
                top_skus       TEXT,
                pattern        TEXT,
                root_cause     TEXT,
                recommended_action TEXT,
                sample_ticket_ids  TEXT,
                report         TEXT,
                active         INTEGER DEFAULT 1,
                created_at     TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sku_incident_flags (
                product_sku      TEXT PRIMARY KEY,
                incident_id      TEXT,
                category         TEXT,
                severity         TEXT,
                active_incident  INTEGER DEFAULT 1,
                updated_at       TEXT
            )
            """
        )
        conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# Tool functions
# ═════════════════════════════════════════════════════════════════════════════

def scan_category_volumes(
    db_path: str, start_date: str, end_date: str
) -> List[Dict[str, Any]]:
    """Return daily ticket counts per category for the full date range."""
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
    """
    For every (category, date) pair that has at least 8 preceding days of data,
    compute the Z-score against a 7-day rolling window.

    Formula (from implementation plan):
        rolling_mean = mean(counts[i-7 : i])
        rolling_std  = std(counts[i-7 : i])
        z_score      = (count[i] - rolling_mean) / rolling_std
    Returns all computed rows, including those below the threshold — callers filter.
    """
    by_category: Dict[str, Dict[str, int]] = {}
    for row in daily_counts:
        by_category.setdefault(row["category"], {})[row["date"]] = int(row["count"])

    zscores: List[Dict[str, Any]] = []
    for category, counts_by_date in by_category.items():
        dates = sorted(counts_by_date)
        for index, date in enumerate(dates):
            if index < 7:
                continue
            prev_counts = [counts_by_date[dates[p]] for p in range(index - 7, index)]
            mean = sum(prev_counts) / 7
            variance = sum((v - mean) ** 2 for v in prev_counts) / 6  # sample std
            std = sqrt(variance)
            z_score = 0.0 if std < 1e-9 else (counts_by_date[date] - mean) / std
            zscores.append(
                {
                    "date":         date,
                    "category":     category,
                    "count":        counts_by_date[date],
                    "rolling_mean": round(mean, 3),
                    "rolling_std":  round(std, 3),
                    "z_score":      round(z_score, 3),
                }
            )
    return zscores


def cluster_spike_windows(
    zscores: List[Dict[str, Any]],
    threshold: float,
    merge_gap_days: int = SPIKE_MERGE_GAP_DAYS,
) -> List[Dict[str, Any]]:
    """
    NEW — core detection logic (replaces PLAN_SPIKE_WINDOWS).

    Groups consecutive spike days (Z > threshold) per category into windows.
    Two spike days in the same category separated by ≤ merge_gap_days of
    non-spike days are merged into one window (handles weekends / low-volume gaps).

    Returns a list of windows, each containing:
        category, start_date, end_date, peak_z_score,
        spike_day_count, title (auto-generated)
    Sorted by peak_z_score descending so the caller gets the worst spikes first.
    """
    # Collect spike days per category
    spike_days: Dict[str, List[str]] = {}
    for row in zscores:
        if row["z_score"] >= threshold:
            spike_days.setdefault(row["category"], []).append(row["date"])

    windows: List[Dict[str, Any]] = []

    for category, days in spike_days.items():
        days_sorted = sorted(days)
        # Group into contiguous windows with gap tolerance
        groups: List[List[str]] = []
        current_group: List[str] = [days_sorted[0]]

        for prev_day, next_day in zip(days_sorted, days_sorted[1:]):
            prev_dt = datetime.strptime(prev_day, "%Y-%m-%d")
            next_dt = datetime.strptime(next_day, "%Y-%m-%d")
            if (next_dt - prev_dt).days <= merge_gap_days + 1:
                current_group.append(next_day)
            else:
                groups.append(current_group)
                current_group = [next_day]
        groups.append(current_group)

        for group in groups:
            if len(group) < 2:
                # Single isolated spike day — may be noise, skip unless very high
                peak = max(
                    r["z_score"]
                    for r in zscores
                    if r["category"] == category and r["date"] in group
                )
                if peak < threshold * 1.5:
                    continue

            start_date = group[0]
            end_date   = group[-1]
            peak_z     = max(
                r["z_score"]
                for r in zscores
                if r["category"] == category and start_date <= r["date"] <= end_date
            )
            title = _auto_title(category, start_date)
            windows.append(
                {
                    "category":        category,
                    "start_date":      start_date,
                    "end_date":        end_date,
                    "peak_z_score":    round(peak_z, 3),
                    "spike_day_count": len(group),
                    "title":           title,
                }
            )

    windows.sort(key=lambda w: (w["peak_z_score"], w["spike_day_count"]), reverse=True)
    return windows


def _auto_title(category: str, start_date: str) -> str:
    """Generate a human-readable title from category + period."""
    month_str = datetime.strptime(start_date, "%Y-%m-%d").strftime("%b %Y")
    labels = {
        "delivery":         "Delivery complaint spike",
        "fake_counterfeit": "Fake/counterfeit product spike",
        "refund_return":    "Refund & return spike",
        "payment_billing":  "Payment & billing spike",
        "product_quality":  "Product quality spike",
        "account_access":   "Account access spike",
        "prime_subscription": "Prime subscription spike",
    }
    base = labels.get(category, f"{category.replace('_', ' ').title()} spike")
    return f"{base} — {month_str}"


def identify_top_skus(
    db_path: str, category: str, start_date: str, end_date: str, limit: int = 5
) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT product_sku, COUNT(1) AS count
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


def identify_top_subcategories(
    db_path: str, category: str, start_date: str, end_date: str, limit: int = 5
) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT sub_category, COUNT(1) AS count
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
        raise RuntimeError("langchain-openai is not installed.")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.2)


def fallback_report(candidate: Dict[str, Any], samples: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Rule-based fallback for when no LLM key is configured.
    Unlike the old version, the rules key off category + sub-category patterns
    from the actual sampled tickets — not hardcoded SKU names.
    """
    category    = candidate["category"]
    affected_sku = candidate["affected_sku"]
    top_sub     = ", ".join(
        item["sub_category"] for item in candidate.get("top_subcategories", [])[:3]
    )
    # Derive the dominant sub-category from samples for richer messaging
    sub_counts: Dict[str, int] = {}
    for s in samples:
        sub_counts[s.get("sub_category", "")] = sub_counts.get(s.get("sub_category", ""), 0) + 1
    dominant_sub = max(sub_counts, key=sub_counts.get) if sub_counts else top_sub

    category_templates = {
        "delivery": (
            f"Customers report {category} issues concentrated in '{dominant_sub}' sub-category.",
            "Possible logistics bottleneck or carrier handoff failure during the spike window.",
            "Prioritise re-routing affected orders, send proactive tracking updates, and escalate unresolved tickets to logistics team.",
        ),
        "fake_counterfeit": (
            f"Fake/counterfeit complaints surged, primarily '{dominant_sub}'. Multiple SKUs affected.",
            "Third-party seller quality failure or organised listing fraud likely during high-traffic period.",
            "Suspend high-complaint third-party sellers, auto-refund verified counterfeit cases, audit affected listings.",
        ),
        "refund_return": (
            f"Refund/return volume spiked — dominant issue: '{dominant_sub}'.",
            "Return processing backlog, possibly from a prior high-volume sales event.",
            "Increase refund queue capacity, notify customers proactively with revised ETAs, auto-approve small-value claims.",
        ),
        "payment_billing": (
            f"Payment complaints spiked, mainly '{dominant_sub}' for {affected_sku}.",
            "Payment gateway or UPI routing issue during the spike window.",
            "Escalate gateway logs to payments engineering, auto-process verified double-charge refunds.",
        ),
        "product_quality": (
            f"Product quality complaints increased for {affected_sku}, dominant issue: '{dominant_sub}'.",
            "Possible batch quality control failure or transit damage pattern.",
            "Quarantine flagged SKU batches, coordinate with supplier QC, auto-approve replacements.",
        ),
    }
    pat, cause, action = category_templates.get(
        category,
        (
            f"{category} spike detected for {affected_sku}. Top issues: {top_sub}.",
            "Operational anomaly requiring human review.",
            "Assign to operations lead for root-cause investigation.",
        ),
    )
    return {"pattern": pat, "root_cause": cause, "recommended_action": action}


def synthesize_report(candidate: Dict[str, Any], samples: List[Dict[str, Any]]) -> Dict[str, str]:
    """Call LLM to synthesize an incident report from sampled ticket summaries."""
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_report(candidate, samples)

    sample_text = "\n".join(
        f"- {s['ticket_id']} | {s['product_sku']} | {s['sub_category']} | {s['summary']}"
        for s in samples
    )
    prompt = f"""You are Agent 2, an anomaly investigation agent for e-commerce customer support.
Analyse the ticket summaries below and write a concise incident report.
Return ONLY a JSON object with exactly these keys: pattern, root_cause, recommended_action.
No markdown fences, no preamble.

Anomaly context:
  category       = {candidate['category']}
  affected_sku   = {candidate['affected_sku']}
  date_range     = {candidate['start_date']} to {candidate['end_date']}
  peak_z_score   = {candidate['z_score']}
  ticket_count   = {candidate['ticket_count']}
  top_sub_cats   = {[s['sub_category'] for s in candidate.get('top_subcategories', [])[:5]]}

Sample ticket summaries (use ONLY these, not external knowledge):
{sample_text}
"""
    try:
        response = get_chat_model().invoke(prompt)
        content  = response.content.strip()
        content  = content[content.find("{") : content.rfind("}") + 1]
        parsed   = json.loads(content)
        if all(k in parsed for k in ["pattern", "root_cause", "recommended_action"]):
            return {k: str(parsed[k]) for k in ["pattern", "root_cause", "recommended_action"]}
    except Exception as exc:
        print(f"[Agent 2] Report synthesis failed, using fallback: {exc}")
    return fallback_report(candidate, samples)


def severity_for(candidate: Dict[str, Any]) -> str:
    z_score      = float(candidate.get("z_score") or 0)
    ticket_count = int(candidate.get("ticket_count") or 0)
    if z_score >= 5 or ticket_count >= 250:
        return "critical"
    if z_score >= 3 or ticket_count >= 75:
        return "high"
    if z_score >= 2:
        return "medium"
    return "low"


def create_incident(
    db_path: str,
    candidate: Dict[str, Any],
    report: Dict[str, str],
    samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    ensure_agent2_tables(db_path)
    stable_key  = f"{candidate['category']}-{candidate['affected_sku']}-{candidate['start_date']}-{candidate['end_date']}"
    incident_id = "INC-" + uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex[:10].upper()
    severity    = severity_for(candidate)
    sample_ids  = [s["ticket_id"] for s in samples]
    full_report = (
        f"Pattern: {report['pattern']}\n"
        f"Root cause: {report['root_cause']}\n"
        f"Recommended action: {report['recommended_action']}"
    )
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO incidents (
                incident_id, title, severity, category, affected_sku,
                start_date, end_date, z_score, ticket_count, top_skus,
                pattern, root_cause, recommended_action,
                sample_ticket_ids, report, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
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
                json.dumps(sample_ids),
                full_report,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()

    return {
        "incident_id":  incident_id,
        "title":        candidate["title"],
        "severity":     severity,
        "category":     candidate["category"],
        "affected_sku": candidate["affected_sku"],
        "start_date":   candidate["start_date"],
        "end_date":     candidate["end_date"],
        "z_score":      candidate["z_score"],
        "ticket_count": candidate["ticket_count"],
        "top_skus":     candidate.get("top_skus", []),
        "sample_ticket_ids": sample_ids,
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
                ) VALUES (?, ?, ?, ?, 1, ?)
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


# ═════════════════════════════════════════════════════════════════════════════
# Graph nodes
# ═════════════════════════════════════════════════════════════════════════════

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
    unique_cats  = len({r["category"] for r in daily_counts})
    unique_dates = len({r["date"] for r in daily_counts})
    return add_step(
        state,
        f"📊 Scanned {len(daily_counts)} (date, category) volume rows "
        f"across {unique_cats} categories and {unique_dates} unique days.",
    )


def node_compute_zscores(state: Agent2State) -> Agent2State:
    zscores = compute_zscores(state.get("daily_counts", []))
    state["zscores"] = zscores
    threshold = state.get("threshold", 2.0)
    spikes    = [r for r in zscores if r["z_score"] >= threshold]
    cats_with_spikes = sorted({r["category"] for r in spikes})
    return add_step(
        state,
        f"🔢 Z-scores computed for {len(zscores)} rows. "
        f"Found {len(spikes)} spike-days (Z ≥ {threshold}) "
        f"across categories: {cats_with_spikes}.",
    )


def node_cluster_windows(state: Agent2State) -> Agent2State:
    """
    NEW NODE — pure Z-score driven window discovery.
    Groups consecutive spike days into anomaly windows.
    No hardcoded dates or category names.
    """
    windows = cluster_spike_windows(
        state.get("zscores", []),
        threshold=state.get("threshold", 2.0),
        merge_gap_days=SPIKE_MERGE_GAP_DAYS,
    )
    state["spike_windows"] = windows
    summary = [
        f"{w['category']}({w['start_date']}→{w['end_date']}, Z={w['peak_z_score']})"
        for w in windows[:6]
    ]
    return add_step(
        state,
        f"🪟 Clustered spike days into {len(windows)} anomaly windows: {summary}",
    )


def node_select_candidates(state: Agent2State) -> Agent2State:
    """
    Converts clustered spike windows into investigation candidates by
    fetching ticket counts, top SKUs, and sub-categories for each window.
    Ranks by peak Z-score. Caps at max_incidents.
    """
    db_path   = state.get("db_path", DEFAULT_DB_PATH)
    windows   = state.get("spike_windows", [])
    max_inc   = state.get("max_incidents", 5)
    candidates: List[Dict[str, Any]] = []

    for window in windows[:max_inc * 2]:  # over-fetch, trim after ranking
        cat        = window["category"]
        start_date = window["start_date"]
        end_date   = window["end_date"]

        with connect_db(db_path) as conn:
            ticket_count = conn.execute(
                """
                SELECT COUNT(1) AS count FROM tickets
                WHERE category = ?
                  AND substr(timestamp, 1, 10) BETWEEN ? AND ?
                """,
                (cat, start_date, end_date),
            ).fetchone()["count"]

        top_skus     = identify_top_skus(db_path, cat, start_date, end_date)
        top_sub_cats = identify_top_subcategories(db_path, cat, start_date, end_date)

        if not top_skus:
            continue

        top_share    = top_skus[0]["count"] / max(int(ticket_count), 1)
        affected_sku = top_skus[0]["product_sku"] if top_share >= 0.35 else "MULTIPLE"

        candidates.append(
            {
                "title":            window["title"],
                "category":         cat,
                "start_date":       start_date,
                "end_date":         end_date,
                "z_score":          window["peak_z_score"],
                "ticket_count":     int(ticket_count),
                "top_skus":         top_skus,
                "top_subcategories":top_sub_cats,
                "affected_sku":     affected_sku,
            }
        )

    # Rank: primary = peak Z-score, secondary = ticket count
    candidates.sort(key=lambda c: (c["z_score"], c["ticket_count"]), reverse=True)
    state["candidates"] = candidates[:max_inc]
    return add_step(
        state,
        f"🎯 Selected top {len(state['candidates'])} candidates for investigation "
        f"(ranked by Z-score, capped at max_incidents={max_inc}).",
    )


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
            f"🔍 Investigated '{candidate['title']}' — "
            f"{len(samples)} samples, affected_sku={candidate['affected_sku']}, "
            f"Z={candidate['z_score']}.",
        )
    state["investigated"] = investigated
    return state


def node_persist_incidents(state: Agent2State) -> Agent2State:
    incidents = []
    for item in state.get("investigated", []):
        incident = create_incident(
            state["db_path"], item, item["report_parts"], item["samples"]
        )
        flag_sku(state["db_path"], incident)
        incidents.append(incident)
        add_step(
            state,
            f"✅ Persisted {incident['incident_id']} (severity={incident['severity']}) "
            f"and flagged SKU scope for Agent 1.",
        )
    state["incidents"] = incidents
    return state


# ═════════════════════════════════════════════════════════════════════════════
# Graph wiring
# ═════════════════════════════════════════════════════════════════════════════

graph = StateGraph(Agent2State)

graph.add_node("scan_category_volumes",    node_scan_volumes)
graph.add_node("compute_zscores",          node_compute_zscores)
graph.add_node("cluster_spike_windows",    node_cluster_windows)   # NEW
graph.add_node("select_candidates",        node_select_candidates)
graph.add_node("investigate_candidates",   node_investigate_candidates)
graph.add_node("persist_incidents",        node_persist_incidents)

graph.set_entry_point("scan_category_volumes")
graph.add_edge("scan_category_volumes",  "compute_zscores")
graph.add_edge("compute_zscores",        "cluster_spike_windows")  # NEW
graph.add_edge("cluster_spike_windows",  "select_candidates")
graph.add_edge("select_candidates",      "investigate_candidates")
graph.add_edge("investigate_candidates", "persist_incidents")
graph.add_edge("persist_incidents",      END)

app = graph.compile()


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def run_agent2_investigation(
    db_path:       str   = DEFAULT_DB_PATH,
    threshold:     float = 2.0,
    max_incidents: int   = 5,
    start_date:    str   = "2024-07-01",
    end_date:      str   = "2025-01-31",
) -> Agent2State:
    """
    Run the full anomaly investigation pipeline.

    Args:
        db_path:       Path to SQLite database.
        threshold:     Z-score threshold for flagging a day as a spike (default 2.0).
        max_incidents: Maximum number of incidents to create per run (default 5).
        start_date:    Start of the scan window.
        end_date:      End of the scan window.

    Returns:
        Final Agent2State with all intermediate artifacts and created incidents.
    """
    initial: Agent2State = {
        "db_path":       db_path,
        "threshold":     threshold,
        "max_incidents": max_incidents,
        "start_date":    start_date,
        "end_date":      end_date,
        "agent_steps":   [],
    }
    return app.invoke(initial)


# ═════════════════════════════════════════════════════════════════════════════
# Validation helper (test suite use only)
# ═════════════════════════════════════════════════════════════════════════════

def validate_against_expected(incidents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Checks that every EXPECTED_SPIKE was caught by the detector.
    Used in tests; never called by the main pipeline.
    """
    found    = []
    missed   = []
    detected_cats = {inc["category"]: inc for inc in incidents}

    for expected in EXPECTED_SPIKES:
        cat = expected["category"]
        if cat not in detected_cats:
            missed.append(expected)
            continue
        inc = detected_cats[cat]
        # Check date ranges overlap (generous ±7 day tolerance)
        exp_start = datetime.strptime(expected["approx_start"], "%Y-%m-%d")
        exp_end   = datetime.strptime(expected["approx_end"], "%Y-%m-%d")
        inc_start = datetime.strptime(inc["start_date"], "%Y-%m-%d")
        inc_end   = datetime.strptime(inc["end_date"], "%Y-%m-%d")
        overlap   = inc_start <= exp_end + timedelta(days=7) and inc_end >= exp_start - timedelta(days=7)
        if overlap:
            found.append({"expected": expected, "detected": inc})
        else:
            missed.append(expected)

    return {
        "total_expected": len(EXPECTED_SPIKES),
        "found":          len(found),
        "missed":         len(missed),
        "recall":         round(len(found) / len(EXPECTED_SPIKES), 3),
        "details":        found,
        "missed_details": missed,
    }


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        from IPython.display import Image, display
        display(Image(app.get_graph().draw_mermaid_png()))
    except Exception:
        print(app.get_graph().draw_mermaid())

    final_state = run_agent2_investigation(DEFAULT_DB_PATH)

    print("\n── Incidents created ──")
    for inc in final_state.get("incidents", []):
        print(f"  {inc['incident_id']} | {inc['severity']:8s} | Z={inc['z_score']} | {inc['title']}")

    print("\n── Validation against expected spikes ──")
    validation = validate_against_expected(final_state.get("incidents", []))
    print(f"  Recall: {validation['recall']*100:.0f}%  "
          f"({validation['found']}/{validation['total_expected']} expected spikes detected)")
    if validation["missed_details"]:
        print(f"  Missed: {[m['category'] for m in validation['missed_details']]}")