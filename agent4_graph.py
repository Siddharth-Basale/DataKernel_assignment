# agent4_report.py — Weekly Insight Report Agent
# ─────────────────────────────────────────────────────────────────────────────
# Runs every Sunday at 06:00 (via Celery Beat) OR on-demand via
#   POST /api/agents/weekly-report/run
#
# What it does:
#   1. Pulls this week's ticket data + prior week for comparison
#   2. Computes business KPIs: revenue at risk, FCR rate, top categories,
#      sentiment trend, churn risk count, resolution SLA by tier
#   3. Calls LLM to write the "3 insights leadership cares about" + action items
#   4. Renders a self-contained HTML report and saves it to disk
#   5. Writes a report record to the weekly_reports table for the API to serve
#
# Cross-agent awareness:
#   • Pulls active incidents from Agent 2's incidents table
#   • Pulls high-churn customers from Agent 3's retention_queue table
#
# FastAPI endpoints (add to main.py):
#   GET  /api/agents/weekly-report/latest   — returns latest report metadata + HTML
#   GET  /api/agents/weekly-report/list     — returns list of past reports
#   POST /api/agents/weekly-report/run      — triggers on-demand generation
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None


load_dotenv()

DEFAULT_DB_PATH = "support.db"
REPORT_DIR      = os.getenv("REPORT_DIR", "weekly_reports")
CHAT_MODEL      = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ═════════════════════════════════════════════════════════════════════════════
# State
# ═════════════════════════════════════════════════════════════════════════════

class Agent4State(TypedDict, total=False):
    db_path:          str
    report_id:        str
    week_start:       str           # YYYY-MM-DD (Monday of report week)
    week_end:         str           # YYYY-MM-DD (Sunday)
    prior_start:      str           # prior week Monday
    prior_end:        str           # prior week Sunday
    kpis:             Dict[str, Any]
    trend_comparison: Dict[str, Any]
    active_incidents: List[Dict[str, Any]]
    churn_summary:    Dict[str, Any]
    narrative:        str           # LLM-generated executive narrative
    html_report:      str           # rendered HTML
    report_path:      str           # saved file path
    agent_steps:      List[str]


# ═════════════════════════════════════════════════════════════════════════════
# DB helpers
# ═════════════════════════════════════════════════════════════════════════════

def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def ensure_report_table(db_path: str) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_reports (
                report_id    TEXT PRIMARY KEY,
                week_start   TEXT,
                week_end     TEXT,
                kpis         TEXT,
                narrative    TEXT,
                html_path    TEXT,
                created_at   TEXT
            )
            """
        )
        conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# Data extraction helpers
# ═════════════════════════════════════════════════════════════════════════════

def fetch_kpis(db_path: str, start: str, end: str) -> Dict[str, Any]:
    """Compute all business KPIs for a given date window."""
    with connect_db(db_path) as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*)                                              AS total_tickets,
                SUM(CASE WHEN resolution_status = 'resolved'   THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN resolution_status = 'unresolved' THEN 1 ELSE 0 END) AS unresolved,
                SUM(CASE WHEN resolution_status = 'escalated'  THEN 1 ELSE 0 END) AS escalated,
                SUM(CASE WHEN is_repeat_contact IN ('True','true','1') THEN 1 ELSE 0 END) AS repeat_contacts,
                ROUND(AVG(CAST(sentiment_score  AS REAL)), 4)        AS avg_sentiment,
                ROUND(AVG(CAST(urgency_score    AS REAL)), 4)        AS avg_urgency,
                ROUND(SUM(CAST(revenue_at_risk  AS REAL)), 2)        AS total_revenue_at_risk,
                ROUND(AVG(CAST(resolution_time_hrs AS REAL)), 2)     AS avg_resolution_hrs,
                SUM(CASE WHEN frustration_level IN ('high','critical') THEN 1 ELSE 0 END) AS high_frustration_count
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()

        top_categories = conn.execute(
            """
            SELECT category, COUNT(*) AS count,
                   ROUND(SUM(CAST(revenue_at_risk AS REAL)), 2) AS revenue_at_risk
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
            LIMIT 7
            """,
            (start, end),
        ).fetchall()

        tier_sla = conn.execute(
            """
            SELECT customer_tier,
                   COUNT(*) AS tickets,
                   ROUND(AVG(CAST(resolution_time_hrs AS REAL)), 2) AS avg_resolution_hrs,
                   SUM(CASE WHEN resolution_status='resolved' THEN 1 ELSE 0 END) AS resolved
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
              AND customer_tier IS NOT NULL
            GROUP BY customer_tier
            ORDER BY avg_resolution_hrs ASC
            """,
            (start, end),
        ).fetchall()

        channel_dist = conn.execute(
            """
            SELECT channel, COUNT(*) AS count
            FROM tickets
            WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
            GROUP BY channel ORDER BY count DESC
            """,
            (start, end),
        ).fetchall()

    t = row_to_dict(totals)
    for key in (
        "total_tickets",
        "resolved",
        "unresolved",
        "escalated",
        "repeat_contacts",
        "high_frustration_count",
        "total_revenue_at_risk",
        "avg_sentiment",
        "avg_urgency",
        "avg_resolution_hrs",
    ):
        if t.get(key) is None:
            t[key] = 0
    total = max(t["total_tickets"] or 0, 1)
    fcr_rate = round((1 - (t["repeat_contacts"] or 0) / total) * 100, 1)

    return {
        **t,
        "fcr_rate":       fcr_rate,
        "top_categories": [row_to_dict(r) for r in top_categories],
        "tier_sla":       [row_to_dict(r) for r in tier_sla],
        "channel_dist":   [row_to_dict(r) for r in channel_dist],
    }


def fetch_active_incidents(db_path: str) -> List[Dict[str, Any]]:
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT incident_id, title, severity, category, affected_sku,
                       start_date, end_date, z_score, ticket_count,
                       pattern, recommended_action
                FROM incidents
                WHERE active = 1
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                        WHEN 'medium'   THEN 3 ELSE 4
                    END
                LIMIT 5
                """
            ).fetchall()
        return [row_to_dict(r) for r in rows]
    except Exception:
        return []


def fetch_churn_summary(db_path: str) -> Dict[str, Any]:
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT COUNT(*) AS queue_size,
                       ROUND(AVG(churn_score), 2) AS avg_churn_score,
                       ROUND(SUM(lifetime_value), 2) AS total_clv_at_risk
                FROM retention_queue
                WHERE created_at >= date('now', '-7 days')
                """
            ).fetchone()
        return row_to_dict(rows) if rows else {}
    except Exception:
        return {}


def get_chat_model() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai not installed.")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.3)


# ═════════════════════════════════════════════════════════════════════════════
# LLM narrative generation
# ═════════════════════════════════════════════════════════════════════════════

def _top_category_summary(kpis: Dict[str, Any]) -> str:
    cats = kpis.get("top_categories") or []
    if not cats:
        return "N/A (no tickets in period)"
    top = cats[0]
    return f"{top.get('category', 'N/A')} ({top.get('count', 0)} tickets)"


def generate_narrative(
    kpis: Dict[str, Any],
    prior_kpis: Dict[str, Any],
    incidents: List[Dict[str, Any]],
    churn: Dict[str, Any],
) -> str:
    """
    Ask the LLM to write the executive narrative for the weekly report.
    Returns Markdown string with:
      - 3 key insights leadership cares about
      - Week-over-week comparison
      - Top recommended actions
    """
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_narrative(kpis, prior_kpis, incidents, churn)

    def pct_change(curr, prev) -> str:
        if not prev or prev == 0:
            return "N/A"
        chg = ((curr - prev) / abs(prev)) * 100
        arrow = "▲" if chg > 0 else "▼"
        return f"{arrow} {abs(chg):.1f}%"

    prompt = f"""You are the AI insight engine for a customer support platform.
Write a concise executive weekly report in Markdown.
Structure: exactly 3 insight sections, then a "Recommended Actions" section.
Tone: direct, data-backed, no fluff. Use ₹ for currency.

This week's KPIs:
  Total tickets:        {kpis.get('total_tickets')} ({pct_change(kpis.get('total_tickets',0), prior_kpis.get('total_tickets',0))} vs last week)
  Revenue at risk:      ₹{kpis.get('total_revenue_at_risk'):,.2f} ({pct_change(kpis.get('total_revenue_at_risk',0), prior_kpis.get('total_revenue_at_risk',0))})
  FCR rate:             {kpis.get('fcr_rate')}% ({pct_change(kpis.get('fcr_rate',0), prior_kpis.get('fcr_rate',0))})
  Avg sentiment:        {kpis.get('avg_sentiment')} (prior: {prior_kpis.get('avg_sentiment')})
  Avg resolution hrs:   {kpis.get('avg_resolution_hrs')} (prior: {prior_kpis.get('avg_resolution_hrs')})
  High frustration:     {kpis.get('high_frustration_count')} tickets
  Top category:         {_top_category_summary(kpis)}

Active incidents (from Agent 2 anomaly detection):
{json.dumps([{'title': i['title'], 'severity': i['severity'], 'action': i['recommended_action']} for i in incidents], indent=2)}

Churn risk queue (from Agent 3):
  Customers flagged: {churn.get('queue_size', 'N/A')}
  Avg churn score:   {churn.get('avg_churn_score', 'N/A')}
  CLV at risk:       ₹{churn.get('total_clv_at_risk', 0):,.2f}

Write the 3 insights and recommended actions now.
"""
    try:
        resp = get_chat_model().invoke(prompt)
        return resp.content.strip()
    except Exception as exc:
        print(f"[Agent 4] Narrative generation failed: {exc}")
        return _fallback_narrative(kpis, prior_kpis, incidents, churn)


def _fallback_narrative(kpis, prior_kpis, incidents, churn) -> str:
    top_cat = _top_category_summary(kpis).split(" (")[0]
    rar     = kpis.get("total_revenue_at_risk", 0)
    fcr     = kpis.get("fcr_rate", 0)
    inc_str = "\n".join(f"- **{i['title']}** ({i['severity']}): {i['recommended_action']}" for i in incidents[:3])
    return f"""## 3 Key Insights This Week

### 1. Revenue exposure remains significant
₹{rar:,.2f} of revenue is tied to unresolved, high-frustration tickets.
The top complaint category is **{top_cat}** — resolving it first recovers the most value.

### 2. First-Contact Resolution rate is {fcr}%
Industry benchmark is 85%. Closing this gap requires better suggested-reply quality
and faster routing of repeat contacts to senior agents.

### 3. Anomaly alerts require action
{len(incidents)} active incidents detected by the anomaly agent this week.
{inc_str if inc_str else "No active incidents."}

## Recommended Actions
- Prioritise {top_cat} tickets for human review this week.
- Review churn queue: {churn.get('queue_size', 0)} at-risk customers with ₹{churn.get('total_clv_at_risk', 0):,.0f} CLV.
- Target FCR improvement in sub-categories with the highest repeat-contact rate.
"""


# ═════════════════════════════════════════════════════════════════════════════
# HTML renderer
# ═════════════════════════════════════════════════════════════════════════════

def render_html_report(
    report_id: str,
    week_start: str,
    week_end: str,
    kpis: Dict[str, Any],
    prior_kpis: Dict[str, Any],
    incidents: List[Dict[str, Any]],
    churn: Dict[str, Any],
    narrative: str,
) -> str:
    """Return a self-contained HTML string for the weekly report."""

    def pct_badge(curr, prev) -> str:
        if not prev or prev == 0:
            return ""
        chg = ((curr - prev) / abs(prev)) * 100
        color = "#16a34a" if chg <= 0 else "#dc2626"  # green=improved, red=worse
        # For sentiment and FCR, direction is flipped
        arrow = "▲" if chg > 0 else "▼"
        return f'<span style="color:{color};font-size:12px;margin-left:6px">{arrow} {abs(chg):.1f}%</span>'

    # Sentiment: more negative = worse, so ▼ is bad
    sent_badge = pct_badge(kpis.get("avg_sentiment", 0), prior_kpis.get("avg_sentiment", 0))
    fcr_badge  = pct_badge(kpis.get("fcr_rate", 0), prior_kpis.get("fcr_rate", 0))
    rar_badge  = pct_badge(kpis.get("total_revenue_at_risk", 0), prior_kpis.get("total_revenue_at_risk", 0))

    category_rows = "".join(
        f"""<tr>
            <td style="padding:8px 12px">{c['category']}</td>
            <td style="padding:8px 12px;text-align:right">{c['count']}</td>
            <td style="padding:8px 12px;text-align:right">₹{c.get('revenue_at_risk',0):,.2f}</td>
        </tr>"""
        for c in kpis.get("top_categories", [])
    )

    incident_rows = "".join(
        f"""<tr>
            <td style="padding:8px 12px">{i['title']}</td>
            <td style="padding:8px 12px">
                <span style="background:{'#fef2f2' if i['severity']=='critical' else '#fefce8'};
                             color:{'#991b1b' if i['severity']=='critical' else '#854d0e'};
                             padding:2px 8px;border-radius:9999px;font-size:12px">
                    {i['severity']}
                </span>
            </td>
            <td style="padding:8px 12px;font-size:13px">{i['recommended_action']}</td>
        </tr>"""
        for i in incidents
    )

    # Convert Markdown narrative to basic HTML (headings + bold)
    import re
    narrative_html = narrative
    narrative_html = re.sub(r"^### (.+)$", r"<h4 style='margin:16px 0 4px'>\1</h4>", narrative_html, flags=re.M)
    narrative_html = re.sub(r"^## (.+)$",  r"<h3 style='margin:20px 0 6px'>\1</h3>",  narrative_html, flags=re.M)
    narrative_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", narrative_html)
    narrative_html = re.sub(r"^- (.+)$", r"<li>\1</li>", narrative_html, flags=re.M)
    narrative_html = re.sub(r"(<li>.*</li>\n?)+", r"<ul style='margin:8px 0 8px 20px'>\g<0></ul>", narrative_html, flags=re.S)
    narrative_html = narrative_html.replace("\n\n", "<br><br>").replace("\n", " ")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Support Insight Report — {week_start} to {week_end}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;line-height:1.6}}
  .page{{max-width:900px;margin:0 auto;padding:40px 24px}}
  .header{{background:#1e293b;color:#fff;border-radius:12px;padding:28px 32px;margin-bottom:28px}}
  .header h1{{font-size:22px;font-weight:600}}
  .header p{{color:#94a3b8;font-size:14px;margin-top:4px}}
  .badge{{display:inline-block;background:#3b82f6;color:#fff;border-radius:6px;padding:2px 10px;font-size:12px;margin-left:8px}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}}
  .kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:18px 20px}}
  .kpi .label{{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.05em}}
  .kpi .value{{font-size:24px;font-weight:700;margin-top:4px;color:#0f172a}}
  .section{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:24px;margin-bottom:20px}}
  .section h2{{font-size:16px;font-weight:600;margin-bottom:16px;color:#0f172a}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th{{background:#f1f5f9;text-align:left;padding:8px 12px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#64748b}}
  tr:nth-child(even){{background:#f8fafc}}
  .narrative{{line-height:1.7;font-size:15px;color:#334155}}
  .footer{{text-align:center;color:#94a3b8;font-size:12px;margin-top:32px}}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <h1>Weekly Customer Support Insight Report
      <span class="badge">Agent 4</span>
    </h1>
    <p>Period: {week_start} → {week_end} &nbsp;·&nbsp; Report ID: {report_id} &nbsp;·&nbsp; Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
  </div>

  <!-- KPI grid -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Total tickets</div>
      <div class="value">{kpis.get('total_tickets',0):,}{pct_badge(kpis.get('total_tickets',0), prior_kpis.get('total_tickets',0))}</div>
    </div>
    <div class="kpi">
      <div class="label">Revenue at risk</div>
      <div class="value">₹{kpis.get('total_revenue_at_risk',0)/100000:.1f}L{rar_badge}</div>
    </div>
    <div class="kpi">
      <div class="label">FCR rate</div>
      <div class="value">{kpis.get('fcr_rate',0)}%{fcr_badge}</div>
    </div>
    <div class="kpi">
      <div class="label">Avg sentiment</div>
      <div class="value">{kpis.get('avg_sentiment',0):.3f}{sent_badge}</div>
    </div>
    <div class="kpi">
      <div class="label">Avg resolution</div>
      <div class="value">{kpis.get('avg_resolution_hrs',0) or '—'} hrs</div>
    </div>
    <div class="kpi">
      <div class="label">Churn queue</div>
      <div class="value">{churn.get('queue_size',0)} customers</div>
    </div>
  </div>

  <!-- AI Narrative -->
  <div class="section">
    <h2>Executive Narrative (AI-generated)</h2>
    <div class="narrative">{narrative_html}</div>
  </div>

  <!-- Top categories -->
  <div class="section">
    <h2>Ticket volume & revenue at risk by category</h2>
    <table>
      <thead><tr><th>Category</th><th style="text-align:right">Tickets</th><th style="text-align:right">Revenue at risk</th></tr></thead>
      <tbody>{category_rows}</tbody>
    </table>
  </div>

  <!-- Active incidents -->
  <div class="section">
    <h2>Active incidents (from Agent 2)</h2>
    {"<p style='color:#64748b;font-size:14px'>No active incidents this week.</p>" if not incidents else f"<table><thead><tr><th>Incident</th><th>Severity</th><th>Recommended action</th></tr></thead><tbody>{incident_rows}</tbody></table>"}
  </div>

  <!-- Tier SLA -->
  <div class="section">
    <h2>Resolution SLA by customer tier</h2>
    <table>
      <thead><tr><th>Tier</th><th style="text-align:right">Tickets</th><th style="text-align:right">Avg resolution (hrs)</th></tr></thead>
      <tbody>{"".join(f"<tr><td style='padding:8px 12px'>{t['customer_tier']}</td><td style='padding:8px 12px;text-align:right'>{t['tickets']}</td><td style='padding:8px 12px;text-align:right'>{t['avg_resolution_hrs']}</td></tr>" for t in kpis.get('tier_sla', []))}</tbody>
    </table>
  </div>

  <div class="footer">
    Amazon Customer Support AI Platform · Agent 4 Weekly Report · {report_id}
  </div>
</div>
</body>
</html>"""


# ═════════════════════════════════════════════════════════════════════════════
# Graph nodes
# ═════════════════════════════════════════════════════════════════════════════

def add_step(state: Agent4State, message: str) -> Agent4State:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    line = f"[Agent 4] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    return state


def node_init(state: Agent4State) -> Agent4State:
    """Derive week/prior-week date windows and assign a report_id."""
    # If week_start not provided, use last complete Mon-Sun week
    if not state.get("week_start"):
        today = datetime.utcnow().date()
        # Most recent Monday
        monday = today - timedelta(days=today.weekday())
        # Last week's Monday
        last_monday = monday - timedelta(days=7)
        state["week_start"] = last_monday.isoformat()
        state["week_end"]   = (last_monday + timedelta(days=6)).isoformat()
    elif not state.get("week_end"):
        ws = datetime.strptime(state["week_start"], "%Y-%m-%d").date()
        state["week_end"] = (ws + timedelta(days=6)).isoformat()

    ws = datetime.strptime(state["week_start"], "%Y-%m-%d")
    state["prior_start"] = (ws - timedelta(days=7)).strftime("%Y-%m-%d")
    state["prior_end"]   = (ws - timedelta(days=1)).strftime("%Y-%m-%d")
    state["report_id"]   = "RPT-" + uuid.uuid4().hex[:8].upper()

    ensure_report_table(state.get("db_path", DEFAULT_DB_PATH))
    return add_step(
        state,
        f"📅 Report period: {state['week_start']} → {state['week_end']} "
        f"| Prior: {state['prior_start']} → {state['prior_end']}",
    )


def node_compute_kpis(state: Agent4State) -> Agent4State:
    db = state.get("db_path", DEFAULT_DB_PATH)
    kpis       = fetch_kpis(db, state["week_start"], state["week_end"])
    prior_kpis = fetch_kpis(db, state["prior_start"], state["prior_end"])
    state["kpis"]             = kpis
    state["trend_comparison"] = prior_kpis
    return add_step(
        state,
        f"📊 KPIs computed — {kpis['total_tickets']} tickets, "
        f"₹{kpis['total_revenue_at_risk']:,.0f} at risk, FCR={kpis['fcr_rate']}%",
    )


def node_fetch_context(state: Agent4State) -> Agent4State:
    db = state.get("db_path", DEFAULT_DB_PATH)
    state["active_incidents"] = fetch_active_incidents(db)
    state["churn_summary"]    = fetch_churn_summary(db)
    return add_step(
        state,
        f"🔗 Cross-agent context: {len(state['active_incidents'])} active incidents, "
        f"churn queue size={state['churn_summary'].get('queue_size', 'N/A')}",
    )


def node_generate_narrative(state: Agent4State) -> Agent4State:
    narrative = generate_narrative(
        state["kpis"],
        state.get("trend_comparison", {}),
        state.get("active_incidents", []),
        state.get("churn_summary", {}),
    )
    state["narrative"] = narrative
    return add_step(state, "✍️ Executive narrative generated.")


def node_render_report(state: Agent4State) -> Agent4State:
    html = render_html_report(
        state["report_id"],
        state["week_start"],
        state["week_end"],
        state["kpis"],
        state.get("trend_comparison", {}),
        state.get("active_incidents", []),
        state.get("churn_summary", {}),
        state["narrative"],
    )
    state["html_report"] = html
    return add_step(state, "🎨 HTML report rendered.")


def node_save_report(state: Agent4State) -> Agent4State:
    os.makedirs(REPORT_DIR, exist_ok=True)
    filename = f"{state['week_start']}_weekly_report_{state['report_id']}.html"
    path     = os.path.join(REPORT_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(state["html_report"])
    state["report_path"] = path

    db = state.get("db_path", DEFAULT_DB_PATH)
    with connect_db(db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO weekly_reports
                (report_id, week_start, week_end, kpis, narrative, html_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["report_id"],
                state["week_start"],
                state["week_end"],
                json.dumps(state["kpis"]),
                state["narrative"],
                path,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()

    return add_step(
        state,
        f"💾 Report saved to {path} and indexed in weekly_reports table.",
    )


# ═════════════════════════════════════════════════════════════════════════════
# Graph wiring
# ═════════════════════════════════════════════════════════════════════════════

graph = StateGraph(Agent4State)

graph.add_node("init",               node_init)
graph.add_node("compute_kpis",       node_compute_kpis)
graph.add_node("fetch_context",      node_fetch_context)
graph.add_node("generate_narrative", node_generate_narrative)
graph.add_node("render_report",      node_render_report)
graph.add_node("save_report",        node_save_report)

graph.set_entry_point("init")
graph.add_edge("init",               "compute_kpis")
graph.add_edge("compute_kpis",       "fetch_context")
graph.add_edge("fetch_context",      "generate_narrative")
graph.add_edge("generate_narrative", "render_report")
graph.add_edge("render_report",      "save_report")
graph.add_edge("save_report",        END)

app = graph.compile()


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def run_weekly_report(
    db_path:    str           = DEFAULT_DB_PATH,
    week_start: Optional[str] = None,
    week_end:   Optional[str] = None,
) -> Agent4State:
    """
    Generate a weekly insight report.

    Args:
        db_path:    Path to SQLite DB.
        week_start: YYYY-MM-DD of the Monday to report on. Defaults to last week.
        week_end:   YYYY-MM-DD of the Sunday. Derived automatically if omitted.

    Returns:
        Final Agent4State with html_report and report_path populated.
    """
    initial: Agent4State = {
        "db_path":    db_path,
        "agent_steps": [],
    }
    if week_start:
        initial["week_start"] = week_start
    if week_end:
        initial["week_end"] = week_end
    return app.invoke(initial)


# ═════════════════════════════════════════════════════════════════════════════
# FastAPI route snippets (paste into main.py)
# ═════════════════════════════════════════════════════════════════════════════



# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    week_start = sys.argv[1] if len(sys.argv) > 1 else None
    state = run_weekly_report(DEFAULT_DB_PATH, week_start=week_start)
    print(f"\n✅ Report saved: {state.get('report_path')}")
    print(f"   Report ID:    {state.get('report_id')}")
    print(f"   Week:         {state.get('week_start')} → {state.get('week_end')}")
    print(f"\n── KPI snapshot ──")
    k = state.get("kpis", {})
    print(f"   Tickets:      {k.get('total_tickets')}")
    print(f"   Revenue risk: ₹{k.get('total_revenue_at_risk', 0):,.2f}")
    print(f"   FCR rate:     {k.get('fcr_rate')}%")
    print(f"   Avg sentiment:{k.get('avg_sentiment')}")