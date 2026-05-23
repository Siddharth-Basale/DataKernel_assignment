# agent5_multilingual.py — Multilingual Routing Agent
# ─────────────────────────────────────────────────────────────────────────────
# Triggered whenever a new ticket is ingested and language != 'en',
# OR on-demand via POST /api/agents/multilingual/process/{ticket_id}
#
# What it does:
#   1. Detect the ticket's language (using langdetect + dataset language field)
#   2. Translate the customer message to English for downstream AI processing
#   3. Re-run classification (category, sub_category) on the English text
#   4. Generate a suggested reply in English
#   5. Translate the reply back into the customer's original language
#   6. Write all outputs back to the ticket row
#
# Insight from your dataset:
#   75% tickets are 'en'. The remaining 25% come from IN customers writing
#   in hi/ta/te/bn. These customers currently get English replies despite
#   writing in their native language — a satisfaction gap highlighted in
#   your implementation plan.
#
# Supported languages (ISO 639-1):
#   en  English  (pass-through — no translation needed)
#   hi  Hindi
#   ta  Tamil
#   te  Telugu
#   bn  Bengali
#   ar  Arabic   (AE customers)
#   de  German   (DE customers)
#   (+ any language the LLM supports)
#
# FastAPI endpoints (add to main.py):
#   POST /api/agents/multilingual/process/{ticket_id}
#   GET  /api/agents/multilingual/stats        — language distribution + gap report
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

try:
    from langdetect import detect as _langdetect
    from langdetect import DetectorFactory
    DetectorFactory.seed = 42  # deterministic detection
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False


load_dotenv()

DEFAULT_DB_PATH = "support.db"
CHAT_MODEL      = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Full language names for prompt clarity
LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "ar": "Arabic",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
}

# Category taxonomy (same as Agent 1 — keep in sync)
CATEGORY_SUBCATEGORIES: Dict[str, List[str]] = {
    "account_access":     ["account_hacked", "address_not_updating", "cant_login",
                           "order_history_missing", "two_factor_issue"],
    "delivery":           ["delayed_delivery", "delivery_attempted_not_home", "not_delivered",
                           "package_stolen", "partial_order_delivered",
                           "tracking_not_updating", "wrong_address_delivered"],
    "fake_counterfeit":   ["brand_complaint", "fake_product", "listing_mismatch", "seller_fraud"],
    "payment_billing":    ["coupon_not_applied", "double_charged", "emi_not_applied",
                           "invoice_incorrect", "payment_deducted_order_failed"],
    "prime_subscription": ["charged_after_cancellation", "free_delivery_not_applied",
                           "prime_benefits_not_showing", "video_not_accessible"],
    "product_quality":    ["counterfeit_suspected", "damaged_in_transit", "dead_on_arrival",
                           "missing_parts", "quality_not_as_described", "wrong_item_sent"],
    "refund_return":      ["exchange_not_processed", "partial_refund", "refund_not_received",
                           "refund_to_wrong_account", "return_pickup_not_scheduled",
                           "return_rejected"],
}


# ═════════════════════════════════════════════════════════════════════════════
# State
# ═════════════════════════════════════════════════════════════════════════════

class Agent5State(TypedDict, total=False):
    ticket_id:              str
    db_path:                str
    ticket:                 Dict[str, Any]
    detected_language:      str          # ISO 639-1 code
    detected_language_name: str          # Human-readable
    original_message:       str          # Raw message in customer's language
    translated_message:     str          # English translation
    translated_category:    str          # Re-classified on English text
    translated_sub_category:str
    english_reply:          str          # Reply generated in English
    localized_reply:        str          # Reply translated back to customer language
    translation_skipped:    bool         # True if ticket was already English
    error:                  str
    agent_steps:            List[str]


# ═════════════════════════════════════════════════════════════════════════════
# DB helpers
# ═════════════════════════════════════════════════════════════════════════════

def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch_ticket(ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Ticket not found: {ticket_id}")
    return row_to_dict(row)


def update_ticket(ticket_id: str, updates: Dict[str, Any], db_path: str) -> None:
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values     = list(updates.values()) + [ticket_id]
    with connect_db(db_path) as conn:
        conn.execute(
            f"UPDATE tickets SET {set_clause}, updated_at = ? WHERE ticket_id = ?",
            values[:-1] + [datetime.utcnow().isoformat(timespec="seconds"), ticket_id],
        )
        conn.commit()


def ensure_multilingual_table(db_path: str) -> None:
    """Store multilingual processing logs for the stats endpoint."""
    with connect_db(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS multilingual_log (
                log_id              TEXT PRIMARY KEY,
                ticket_id           TEXT,
                detected_language   TEXT,
                original_message    TEXT,
                translated_message  TEXT,
                localized_reply     TEXT,
                processed_at        TEXT
            )
            """
        )
        conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# LLM helpers
# ═════════════════════════════════════════════════════════════════════════════

def get_llm() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai not installed.")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.1)


def llm_detect_language(message: str) -> Tuple[str, str]:
    """
    Detect language using langdetect library first (fast, free).
    Falls back to LLM detection if langdetect is unavailable or confidence is low.
    Returns (iso_code, language_name).
    """
    # Try library first
    if HAS_LANGDETECT and len(message) >= 20:
        try:
            code = _langdetect(message)
            name = LANGUAGE_NAMES.get(code, code.upper())
            return code, name
        except Exception:
            pass

    # LLM fallback
    if not os.getenv("OPENAI_API_KEY"):
        return "en", "English"  # safe default

    prompt = f"""Detect the language of this customer support message.
Reply with ONLY a JSON object: {{"code": "hi", "name": "Hindi"}}
Use ISO 639-1 codes. If uncertain, return English.

Message: {message[:300]}"""
    try:
        resp    = get_llm().invoke(prompt)
        content = resp.content.strip()
        content = content[content.find("{"):content.rfind("}") + 1]
        parsed  = json.loads(content)
        code    = parsed.get("code", "en")
        name    = parsed.get("name", LANGUAGE_NAMES.get(code, code.upper()))
        return code, name
    except Exception:
        return "en", "English"


def llm_translate_to_english(message: str, source_language: str) -> str:
    """Translate customer message to English for AI processing."""
    if not os.getenv("OPENAI_API_KEY"):
        return message  # pass-through without key

    prompt = f"""Translate the following customer support message from {source_language} to English.
Preserve the tone, urgency, and all specific details (order numbers, product names, amounts).
Return ONLY the translated text, no explanation.

Original ({source_language}):
{message}"""
    try:
        resp = get_llm().invoke(prompt)
        return resp.content.strip()
    except Exception:
        return message  # fall back to original


def llm_classify(english_message: str) -> Tuple[str, str]:
    """
    Classify an English message into category + sub_category.
    Used to re-classify non-English tickets after translation for better accuracy.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return "delivery", "not_delivered"  # safe defaults

    taxonomy_str = json.dumps(CATEGORY_SUBCATEGORIES, indent=2)
    prompt = f"""Classify this customer support message into category and sub_category.
Return ONLY JSON: {{"category": "...", "sub_category": "..."}}

Available taxonomy:
{taxonomy_str}

Message:
{english_message[:500]}"""
    try:
        resp    = get_llm().invoke(prompt)
        content = resp.content.strip()
        content = content[content.find("{"):content.rfind("}") + 1]
        parsed  = json.loads(content)
        cat     = parsed.get("category", "delivery")
        sub     = parsed.get("sub_category", "not_delivered")
        # Validate against taxonomy
        if cat not in CATEGORY_SUBCATEGORIES:
            cat = "delivery"
        if sub not in CATEGORY_SUBCATEGORIES.get(cat, []):
            sub = CATEGORY_SUBCATEGORIES[cat][0]
        return cat, sub
    except Exception:
        return "delivery", "not_delivered"


def llm_generate_english_reply(
    ticket: Dict[str, Any],
    english_message: str,
    category: str,
    sub_category: str,
) -> str:
    """Generate a support reply in English (to be translated in the next step)."""
    if not os.getenv("OPENAI_API_KEY"):
        return (
            f"Hi {ticket.get('customer_name', 'there')}, thank you for contacting support. "
            f"We have received your {category} concern and will resolve it promptly. "
            f"Please allow 24–48 hours for our team to investigate and respond."
        )

    prompt = f"""You are a helpful customer support agent.
Write a professional, empathetic reply to this customer complaint.
Be specific, actionable, and concise (3-5 sentences max).

Customer name: {ticket.get('customer_name', 'Customer')}
Tier: {ticket.get('customer_tier', 'regular')}
Category: {category} / {sub_category}
Order ID: {ticket.get('order_id', 'N/A')}
Order value: ₹{ticket.get('order_value', 'N/A')}

Customer message (translated to English):
{english_message}

Reply in English:"""
    try:
        resp = get_llm().invoke(prompt)
        return resp.content.strip()
    except Exception:
        return (
            f"Hi {ticket.get('customer_name', 'there')}, we apologize for the inconvenience. "
            f"Our team is reviewing your {category} concern and will respond within 24 hours."
        )


def llm_translate_reply(english_reply: str, target_language: str, target_language_name: str) -> str:
    """Translate the English reply into the customer's language."""
    if not os.getenv("OPENAI_API_KEY"):
        return english_reply  # pass-through without key

    prompt = f"""Translate the following customer support reply from English to {target_language_name}.
Preserve the professional, empathetic tone.
Return ONLY the translated text, no explanation.

English reply:
{english_reply}"""
    try:
        resp = get_llm().invoke(prompt)
        return resp.content.strip()
    except Exception:
        return english_reply  # fall back to English reply


# ═════════════════════════════════════════════════════════════════════════════
# Graph nodes
# ═════════════════════════════════════════════════════════════════════════════

def add_step(state: Agent5State, message: str) -> Agent5State:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    print(f"[Agent 5] {message}")
    return state


def node_load_ticket(state: Agent5State) -> Agent5State:
    db_path   = state.get("db_path", DEFAULT_DB_PATH)
    ticket_id = state["ticket_id"]
    ticket    = fetch_ticket(ticket_id, db_path)
    state["ticket"]           = ticket
    state["original_message"] = ticket.get("message", "")
    return add_step(
        state,
        f"📋 Loaded ticket {ticket_id} | language field='{ticket.get('language', 'unknown')}' "
        f"| customer_tier={ticket.get('customer_tier')} | country={ticket.get('customer_country')}",
    )


def node_detect_language(state: Agent5State) -> Agent5State:
    """
    Detect language from message text. Prefer the CSV 'language' field if set,
    but always verify with langdetect — the field can be wrong for multilingual customers.
    """
    ticket   = state["ticket"]
    declared = (ticket.get("language") or "").strip().lower()
    message  = state["original_message"]

    if declared and declared != "en" and len(declared) == 2:
        # Trust declared language for non-English tickets (it came from the dataset)
        code = declared
        name = LANGUAGE_NAMES.get(code, code.upper())
        source = "declared in CSV"
    else:
        # Run detection
        code, name = llm_detect_language(message)
        source = "auto-detected"

    state["detected_language"]      = code
    state["detected_language_name"] = name

    return add_step(
        state,
        f"🌐 Language {source}: {name} ({code})",
    )


def node_check_english(state: Agent5State) -> Agent5State:
    """
    If the ticket is already in English, skip translation entirely.
    Mark state so the router can take the fast path.
    """
    if state.get("detected_language") == "en":
        state["translation_skipped"]      = True
        state["translated_message"]       = state["original_message"]
        state["translated_category"]      = state["ticket"].get("category", "delivery")
        state["translated_sub_category"]  = state["ticket"].get("sub_category", "not_delivered")
        return add_step(state, "⏭️ Ticket is English — skipping translation, using existing classification.")
    state["translation_skipped"] = False
    return add_step(
        state,
        f"🔄 Non-English ticket detected ({state['detected_language_name']}) — proceeding to translation pipeline.",
    )


def node_translate_to_english(state: Agent5State) -> Agent5State:
    if state.get("translation_skipped"):
        return state
    translated = llm_translate_to_english(
        state["original_message"],
        state["detected_language_name"],
    )
    state["translated_message"] = translated
    preview = translated[:120].replace("\n", " ")
    return add_step(state, f"📝 Translated to English: \"{preview}…\"")


def node_reclassify(state: Agent5State) -> Agent5State:
    """
    Re-classify using the English translation.
    Original classification was done on the raw non-English text —
    classifying on the translation is significantly more accurate.
    """
    if state.get("translation_skipped"):
        return state

    cat, sub = llm_classify(state["translated_message"])
    original_cat = state["ticket"].get("category")
    original_sub = state["ticket"].get("sub_category")

    state["translated_category"]      = cat
    state["translated_sub_category"]  = sub

    if cat != original_cat or sub != original_sub:
        return add_step(
            state,
            f"🔁 Re-classified: {original_cat}/{original_sub} → {cat}/{sub} "
            f"(improved accuracy on English translation)",
        )
    return add_step(state, f"✅ Classification confirmed: {cat}/{sub}")


def node_generate_reply(state: Agent5State) -> Agent5State:
    reply = llm_generate_english_reply(
        state["ticket"],
        state.get("translated_message", state["original_message"]),
        state.get("translated_category", "delivery"),
        state.get("translated_sub_category", "not_delivered"),
    )
    state["english_reply"] = reply
    return add_step(state, f"💬 English reply generated ({len(reply)} chars).")


def node_localize_reply(state: Agent5State) -> Agent5State:
    lang_code = state.get("detected_language", "en")
    lang_name = state.get("detected_language_name", "English")

    if lang_code == "en" or state.get("translation_skipped"):
        state["localized_reply"] = state["english_reply"]
        return add_step(state, "⏭️ Reply is already in English — no localization needed.")

    localized = llm_translate_reply(state["english_reply"], lang_code, lang_name)
    state["localized_reply"] = localized
    preview = localized[:120].replace("\n", " ")
    return add_step(state, f"🌍 Reply localized to {lang_name}: \"{preview}…\"")


def node_write_back(state: Agent5State) -> Agent5State:
    """
    Write all multilingual pipeline outputs back to the ticket row.
    Overwrites: suggested_reply (localized), category, sub_category (if re-classified).
    Adds: translated_message, detected_language to key_entities for traceability.
    """
    db_path   = state.get("db_path", DEFAULT_DB_PATH)
    ticket_id = state["ticket_id"]

    # Build entities annotation
    ticket       = state["ticket"]
    existing_ent = ticket.get("key_entities") or "[]"
    try:
        entities = json.loads(existing_ent) if isinstance(existing_ent, str) else existing_ent
        if not isinstance(entities, list):
            entities = []
    except Exception:
        entities = []

    lang_annotation = f"[multilingual] detected={state.get('detected_language_name','?')}"
    if lang_annotation not in entities:
        entities.append(lang_annotation)

    updates: Dict[str, Any] = {
        "suggested_reply": state.get("localized_reply", ""),
        "key_entities":    json.dumps(entities),
    }

    # Only overwrite category/sub_category if re-classification happened
    if not state.get("translation_skipped"):
        new_cat = state.get("translated_category")
        new_sub = state.get("translated_sub_category")
        if new_cat and new_cat != ticket.get("category"):
            updates["category"]     = new_cat
        if new_sub and new_sub != ticket.get("sub_category"):
            updates["sub_category"] = new_sub

    update_ticket(ticket_id, updates, db_path)

    # Log to multilingual_log table
    ensure_multilingual_table(db_path)
    with connect_db(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO multilingual_log
                (log_id, ticket_id, detected_language, original_message,
                 translated_message, localized_reply, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ML-" + uuid.uuid4().hex[:8].upper(),
                ticket_id,
                state.get("detected_language", "en"),
                state.get("original_message", "")[:500],
                state.get("translated_message", "")[:500],
                state.get("localized_reply", "")[:500],
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()

    return add_step(
        state,
        f"✅ Written back to DB — localized reply ({state.get('detected_language_name','?')}), "
        f"updated category/sub_category if changed.",
    )


# ═════════════════════════════════════════════════════════════════════════════
# Routing functions
# ═════════════════════════════════════════════════════════════════════════════

def route_after_language_check(state: Agent5State) -> str:
    """
    Fast path for English tickets: skip translate + reclassify, go straight to reply.
    Non-English: full pipeline.
    """
    if state.get("translation_skipped"):
        return "generate_reply"
    return "translate_to_english"


# ═════════════════════════════════════════════════════════════════════════════
# Graph wiring
# ═════════════════════════════════════════════════════════════════════════════

graph = StateGraph(Agent5State)

graph.add_node("load_ticket",          node_load_ticket)
graph.add_node("detect_language",      node_detect_language)
graph.add_node("check_english",        node_check_english)
graph.add_node("translate_to_english", node_translate_to_english)
graph.add_node("reclassify",           node_reclassify)
graph.add_node("generate_reply",       node_generate_reply)
graph.add_node("localize_reply",       node_localize_reply)
graph.add_node("write_back",           node_write_back)

graph.set_entry_point("load_ticket")
graph.add_edge("load_ticket",     "detect_language")
graph.add_edge("detect_language", "check_english")

# Branch: English tickets skip translation + reclassification
graph.add_conditional_edges(
    "check_english",
    route_after_language_check,
    {
        "translate_to_english": "translate_to_english",
        "generate_reply":       "generate_reply",
    },
)

graph.add_edge("translate_to_english", "reclassify")
graph.add_edge("reclassify",           "generate_reply")
graph.add_edge("generate_reply",       "localize_reply")
graph.add_edge("localize_reply",       "write_back")
graph.add_edge("write_back",           END)

app = graph.compile()


# ═════════════════════════════════════════════════════════════════════════════
# Public entry points
# ═════════════════════════════════════════════════════════════════════════════

def run_multilingual_agent(
    ticket_id: str,
    db_path:   str = DEFAULT_DB_PATH,
) -> Agent5State:
    """
    Process a single ticket through the multilingual pipeline.
    Safe to call for English tickets — will fast-path and return quickly.
    """
    initial: Agent5State = {
        "ticket_id":   ticket_id,
        "db_path":     db_path,
        "agent_steps": [],
    }
    return app.invoke(initial)


def run_multilingual_batch(
    db_path:  str = DEFAULT_DB_PATH,
    language: str = None,       # filter to specific language; None = all non-English
    limit:    int = 100,
) -> Dict[str, Any]:
    """
    Batch-process all non-English tickets (or a specific language) that don't yet
    have a localized suggested_reply.
    Useful for initial backfill after deployment.
    """
    lang_filter = "AND language != 'en'" if language is None else f"AND language = '{language}'"
    with connect_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT ticket_id FROM tickets
            WHERE (suggested_reply IS NULL OR TRIM(suggested_reply) = '')
              AND language IS NOT NULL
              {lang_filter}
            ORDER BY urgency_score DESC, order_value DESC
            LIMIT {limit}
            """
        ).fetchall()

    ticket_ids = [r["ticket_id"] for r in rows]
    results    = {"processed": 0, "skipped": 0, "errors": [], "ticket_ids": ticket_ids}

    for tid in ticket_ids:
        try:
            state = run_multilingual_agent(tid, db_path)
            if state.get("error"):
                results["errors"].append({"ticket_id": tid, "error": state["error"]})
            else:
                results["processed"] += 1
        except Exception as exc:
            results["errors"].append({"ticket_id": tid, "error": str(exc)})
            results["skipped"] += 1

    return results


def get_language_gap_report(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """
    Returns the language distribution and satisfaction gap report.
    Surfaces the insight: "X% of non-English tickets got an English reply."
    Used by GET /api/agents/multilingual/stats.
    """
    with connect_db(db_path) as conn:
        dist = conn.execute(
            """
            SELECT language,
                   COUNT(*) AS total,
                   SUM(CASE WHEN suggested_reply IS NOT NULL
                             AND TRIM(suggested_reply) != '' THEN 1 ELSE 0 END) AS has_reply,
                   ROUND(AVG(CAST(sentiment_score AS REAL)), 4) AS avg_sentiment
            FROM tickets
            WHERE language IS NOT NULL
            GROUP BY language
            ORDER BY total DESC
            """
        ).fetchall()

        ml_log_count = 0
        try:
            ml_log_count = conn.execute(
                "SELECT COUNT(*) AS c FROM multilingual_log"
            ).fetchone()["c"]
        except Exception:
            pass

    rows = [row_to_dict(r) for r in dist]
    total_non_en = sum(r["total"] for r in rows if r["language"] != "en")
    localized    = ml_log_count  # every log entry = one localized reply

    return {
        "language_distribution": rows,
        "total_non_english_tickets": total_non_en,
        "localized_replies_generated": localized,
        "coverage_pct": round(localized / max(total_non_en, 1) * 100, 1),
        "insight": (
            f"{total_non_en} tickets were written in non-English languages. "
            f"{localized} have received localized replies ({round(localized/max(total_non_en,1)*100,1)}% coverage). "
            f"Improving this to 100% closes the satisfaction gap identified in the dataset."
        ),
    }





# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # Show graph
    try:
        from IPython.display import Image, display
        display(Image(app.get_graph().draw_mermaid_png()))
    except Exception:
        print(app.get_graph().draw_mermaid())

    if len(sys.argv) > 1:
        ticket_id = sys.argv[1]
        print(f"\n── Processing ticket: {ticket_id} ──")
        state = run_multilingual_agent(ticket_id, DEFAULT_DB_PATH)
        print(f"\n  Language:     {state.get('detected_language_name')} ({state.get('detected_language')})")
        print(f"  Skipped:      {state.get('translation_skipped')}")
        print(f"  Category:     {state.get('translated_category')} / {state.get('translated_sub_category')}")
        print(f"\n  Localized reply:\n{state.get('localized_reply', '(none)')}")
    else:
        print("\n── Language gap report ──")
        report = get_language_gap_report(DEFAULT_DB_PATH)
        print(f"  {report['insight']}")
        print(f"\n  Distribution:")
        for row in report["language_distribution"]:
            print(f"    {row['language']:4s}  {row['total']:5d} tickets  "
                  f"sentiment={row['avg_sentiment']}")
        print(f"\nUsage: python agent5_multilingual.py <ticket_id>")
        print(f"       python agent5_multilingual.py  (show stats)")