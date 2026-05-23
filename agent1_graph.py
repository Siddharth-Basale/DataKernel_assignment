

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

try:
    import chromadb
except ImportError:
    chromadb = None

try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
except ImportError:
    ChatOpenAI = None
    OpenAIEmbeddings = None

try:
    from langdetect import detect as _langdetect
    from langdetect import DetectorFactory

    DetectorFactory.seed = 42
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False


load_dotenv()

DEFAULT_DB_PATH    = "support.db"
CHROMA_PATH        = "chroma_store"
COLLECTION_NAME    = "resolved_ticket_replies"
CHROMA_DISTANCE    = "cosine"
EMBEDDING_MODEL    = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL         = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

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

# ── Taxonomy ──────────────────────────────────────────────────────────────────
CATEGORY_SUBCATEGORIES: Dict[str, List[str]] = {
    "account_access":    ["account_hacked", "address_not_updating", "cant_login",
                          "order_history_missing", "two_factor_issue"],
    "delivery":          ["delayed_delivery", "delivery_attempted_not_home", "not_delivered",
                          "package_stolen", "partial_order_delivered",
                          "tracking_not_updating", "wrong_address_delivered"],
    "fake_counterfeit":  ["brand_complaint", "fake_product", "listing_mismatch", "seller_fraud"],
    "payment_billing":   ["coupon_not_applied", "double_charged", "emi_not_applied",
                          "invoice_incorrect", "payment_deducted_order_failed"],
    "prime_subscription":["charged_after_cancellation", "free_delivery_not_applied",
                          "prime_benefits_not_showing", "video_not_accessible"],
    "product_quality":   ["counterfeit_suspected", "damaged_in_transit", "dead_on_arrival",
                          "missing_parts", "quality_not_as_described", "wrong_item_sent"],
    "refund_return":     ["exchange_not_processed", "partial_refund", "refund_not_received",
                          "refund_to_wrong_account", "return_pickup_not_scheduled",
                          "return_rejected"],
}

# Categories that must always escalate regardless of priority score
# (legal risk, security breach, brand fraud — never auto-reply)
ALWAYS_ESCALATE_CATEGORIES = {"fake_counterfeit"}
ALWAYS_ESCALATE_SUBCATEGORIES = {"account_hacked"}

# Simple issues the agent can resolve itself without RAG
AUTO_RESOLVE_SUBCATEGORIES = {"cant_login", "two_factor_issue", "prime_benefits_not_showing",
                               "video_not_accessible", "address_not_updating"}

BASE_SENTIMENTS = {
    "delivery": -0.55, "refund_return": -0.65, "product_quality": -0.60,
    "payment_billing": -0.70, "account_access": -0.50,
    "fake_counterfeit": -0.85, "prime_subscription": -0.45,
}
BASE_URGENCY = {
    "delivery": 0.55, "refund_return": 0.65, "product_quality": 0.60,
    "payment_billing": 0.80, "account_access": 0.70,
    "fake_counterfeit": 0.85, "prime_subscription": 0.40,
}

# Auto-resolve reply templates (no LLM tokens needed for these)
AUTO_RESOLVE_REPLIES: Dict[str, str] = {
    "cant_login": (
        "Hi {name}, I understand you're unable to log in. Please tap 'Forgot Password' and enter "
        "your registered email. An OTP will arrive within 3 minutes. If it doesn't, check your spam "
        "folder or reply here and we'll escalate to account recovery immediately."
    ),
    "two_factor_issue": (
        "Hi {name}, if you've lost access to your 2FA device, please go to Account Settings → "
        "Security → 'Can't access your authenticator?' and follow the recovery steps. "
        "If you're still blocked, reply with your registered email and we'll escalate to our "
        "account security team."
    ),
    "prime_benefits_not_showing": (
        "Hi {name}, Prime benefits sometimes take up to 2 hours to reflect after renewal. "
        "Please sign out, clear your app cache, and sign back in. If delivery charges still show "
        "for Prime-eligible items, reply here and we'll credit the delivery charge back immediately."
    ),
    "video_not_accessible": (
        "Hi {name}, Prime Video access issues are usually resolved by signing out and back in on "
        "your device. If a specific title shows 'not available', it may have geographic restrictions. "
        "For billing or subscription issues with Video, reply here and we'll escalate to our "
        "Prime team."
    ),
    "address_not_updating": (
        "Hi {name}, please try adding your new address from a desktop browser at amazon.in/address "
        "and set it as default there — the mobile app occasionally has a sync delay. "
        "If the issue persists after 30 minutes, reply here with your new address and we'll update "
        "it directly on our end."
    ),
}


# ═════════════════════════════════════════════════════════════════════════════
# State
# ═════════════════════════════════════════════════════════════════════════════

class Agent1State(TypedDict, total=False):
    ticket_id:        str
    db_path:          str
    ticket:           Dict[str, Any]
    customer_history: List[Dict[str, Any]]
    order_details:    Dict[str, Any]
    active_incident:  Optional[Dict[str, Any]]
    priority_score:   float
    frustration_level:str
    auto_escalate:    bool
    auto_resolve_now: bool          # NEW: early-route flag for simple issues
    similar_tickets:  List[Dict[str, Any]]
    suggested_reply:  str
    key_entities:     List[str]
    decision:         str
    reason:           str
    agent_steps:      List[str]     # always a Python list; serialised on DB write
    classification_confidence: float  # NEW: LLM classification confidence 0-1
    error:            str
    # Multilingual (merged from Agent 5)
    detected_language:       str
    detected_language_name:  str
    original_message:        str
    translated_message:      str
    translated_category:     str
    translated_sub_category: str
    translation_skipped:     bool
    english_reply:           str
    localized_reply:         str


# ═════════════════════════════════════════════════════════════════════════════
# Helpers — DB
# ═════════════════════════════════════════════════════════════════════════════

def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_load_json_list(value: Any) -> List[Any]:
    """
    FIX P6: Deserialise a value that was stored as a JSON string back to a
    Python list. Never raises — returns [] on any failure.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = {key: row[key] for key in row.keys()}
    # P6: auto-deserialise list columns when reading back from SQLite
    for col in ("agent_steps", "key_entities", "rag_examples", "similar_tickets"):
        if col in d and isinstance(d[col], str):
            d[col] = _safe_load_json_list(d[col])
    return d


def fetch_ticket(ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if not row:
        raise ValueError(f"Ticket not found: {ticket_id}")
    return row_to_dict(row)


def update_ticket_fields(
    ticket_id: str,
    updates: Dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """
    FIX P6: Serialise list/dict values to JSON before writing; they are
    deserialised automatically by row_to_dict when read back.
    """
    if not updates:
        return
    serialised = {
        k: json.dumps(v) if isinstance(v, (list, dict)) else v
        for k, v in updates.items()
    }
    assignments = ", ".join(f"{k} = ?" for k in serialised)
    values = list(serialised.values())
    values.append(datetime.utcnow().isoformat(timespec="seconds"))
    values.append(ticket_id)
    with connect_db(db_path) as conn:
        conn.execute(
            f"UPDATE tickets SET {assignments}, updated_at = ? WHERE ticket_id = ?",
            values,
        )
        conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# Helpers — AI clients
# ═════════════════════════════════════════════════════════════════════════════

def get_chat_model() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai not installed.")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.2)


# ── Multilingual helpers (merged from Agent 5) ────────────────────────────────

def llm_detect_language(message: str) -> Tuple[str, str]:
    if HAS_LANGDETECT and len(message) >= 20:
        try:
            code = _langdetect(message)
            return code, LANGUAGE_NAMES.get(code, code.upper())
        except Exception:
            pass
    if not os.getenv("OPENAI_API_KEY"):
        return "en", "English"
    prompt = (
        f"Detect the language of this customer support message.\n"
        f'Reply with ONLY JSON: {{"code": "hi", "name": "Hindi"}}\n'
        f"Message: {message[:300]}"
    )
    try:
        resp = get_chat_model().invoke(prompt)
        content = resp.content.strip()
        content = content[content.find("{") : content.rfind("}") + 1]
        parsed = json.loads(content)
        code = parsed.get("code", "en")
        return code, parsed.get("name", LANGUAGE_NAMES.get(code, code.upper()))
    except Exception:
        return "en", "English"


def llm_translate_to_english(message: str, source_language: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return message
    prompt = (
        f"Translate this customer support message from {source_language} to English.\n"
        f"Preserve tone, urgency, and all details. Return ONLY the translation.\n\n"
        f"Original:\n{message}"
    )
    try:
        return get_chat_model().invoke(prompt).content.strip()
    except Exception:
        return message


def llm_classify_english(english_message: str) -> Tuple[str, str]:
    if not os.getenv("OPENAI_API_KEY"):
        return "delivery", "not_delivered"
    taxonomy_str = json.dumps(CATEGORY_SUBCATEGORIES, indent=2)
    prompt = (
        f"Classify into category and sub_category. Return ONLY JSON.\n"
        f"Taxonomy:\n{taxonomy_str}\n\nMessage:\n{english_message[:500]}"
    )
    try:
        resp = get_chat_model().invoke(prompt)
        content = resp.content.strip()
        content = content[content.find("{") : content.rfind("}") + 1]
        parsed = json.loads(content)
        cat = parsed.get("category", "delivery")
        sub = parsed.get("sub_category", "not_delivered")
        if cat not in CATEGORY_SUBCATEGORIES:
            cat = "delivery"
        if sub not in CATEGORY_SUBCATEGORIES.get(cat, []):
            sub = CATEGORY_SUBCATEGORIES[cat][0]
        return cat, sub
    except Exception:
        return "delivery", "not_delivered"


def llm_translate_reply(english_reply: str, target_language_name: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        return english_reply
    prompt = (
        f"Translate this support reply from English to {target_language_name}.\n"
        f"Preserve professional, empathetic tone. Return ONLY the translation.\n\n"
        f"{english_reply}"
    )
    try:
        return get_chat_model().invoke(prompt).content.strip()
    except Exception:
        return english_reply


def ensure_multilingual_table(db_path: str) -> None:
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


def log_multilingual_run(state: Agent1State) -> None:
    if state.get("translation_skipped"):
        return
    db_path = state.get("db_path", DEFAULT_DB_PATH)
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
                state["ticket_id"],
                state.get("detected_language", "en"),
                (state.get("original_message") or "")[:500],
                (state.get("translated_message") or "")[:500],
                (state.get("localized_reply") or "")[:500],
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def multilingual_key_entities(state: Agent1State) -> List[str]:
    ticket = state.get("ticket", {})
    entities = _safe_load_json_list(ticket.get("key_entities"))
    if not isinstance(entities, list):
        entities = []
    tag = f"[multilingual] detected={state.get('detected_language_name', '?')}"
    if tag not in entities:
        entities.append(tag)
    return entities


def persist_multilingual_fields(state: Agent1State) -> None:
    """Save message_en and reclassified category without a customer reply."""
    if state.get("translation_skipped"):
        return
    updates: Dict[str, Any] = {"key_entities": multilingual_key_entities(state)}
    if state.get("translated_message"):
        updates["message_en"] = state["translated_message"]
    if not state.get("translation_skipped"):
        if state.get("translated_category"):
            updates["category"] = state["translated_category"]
        if state.get("translated_sub_category"):
            updates["sub_category"] = state["translated_sub_category"]
    if len(updates) > 1 or updates.get("message_en"):
        update_ticket_fields(
            state["ticket_id"], updates, state.get("db_path", DEFAULT_DB_PATH),
        )


def localize_outgoing_reply(state: Agent1State, english_reply: str) -> str:
    state["english_reply"] = english_reply
    if state.get("translation_skipped") or state.get("detected_language") == "en":
        state["localized_reply"] = english_reply
        return english_reply
    localized = llm_translate_reply(
        english_reply, state.get("detected_language_name", "English"),
    )
    state["localized_reply"] = localized
    return localized


def save_agent1_outcome(
    ticket_id: str,
    state: Agent1State,
    *,
    suggested_reply: str,
    agent_decision: str,
    agent_reason: str,
    resolution_status: Optional[str] = None,
    revenue_at_risk: Optional[float] = None,
) -> None:
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    updates: Dict[str, Any] = {
        "suggested_reply": suggested_reply,
        "agent_decision":  agent_decision,
        "agent_reason":    agent_reason,
        "agent_steps":     state.get("agent_steps", []),
        "key_entities":    multilingual_key_entities(state),
    }
    if resolution_status:
        updates["resolution_status"] = resolution_status
    if revenue_at_risk is not None:
        updates["revenue_at_risk"] = revenue_at_risk
    if state.get("translated_message") and not state.get("translation_skipped"):
        updates["message_en"] = state["translated_message"]
    if not state.get("translation_skipped"):
        if state.get("translated_category"):
            updates["category"] = state["translated_category"]
        if state.get("translated_sub_category"):
            updates["sub_category"] = state["translated_sub_category"]
    update_ticket_fields(ticket_id, updates, db_path)
    log_multilingual_run(state)


def get_embeddings_model() -> Any:
    if OpenAIEmbeddings is None:
        raise RuntimeError("langchain-openai not installed.")
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def get_chroma_collection() -> Any:
    if chromadb is None:
        raise RuntimeError("chromadb not installed.")
    Path(CHROMA_PATH).mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": CHROMA_DISTANCE},
    )


def distances_to_similarity_percent(distances: List[float]) -> List[int]:
    """Map Chroma distances to 0–100 scores. Uses relative ranking when absolute cosine scores collapse to 0."""
    if not distances:
        return []

    def _relative() -> List[int]:
        mn, mx = min(distances), max(distances)
        if mx <= mn:
            return [100] * len(distances)
        return [
            max(0, min(100, round(100.0 * (1.0 - (d - mn) / (mx - mn)))))
            for d in distances
        ]

    if all(0.0 <= d <= 2.0 for d in distances):
        absolute = [max(0, min(100, round((1.0 - d) * 100))) for d in distances]
        if max(absolute) > 0:
            return absolute
        return _relative()
    return _relative()


# ═════════════════════════════════════════════════════════════════════════════
# Tool: get_customer_history
# ═════════════════════════════════════════════════════════════════════════════

def get_customer_history(
    customer_id: str,
    ticket_id: str,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticket_id, timestamp, category, sub_category, resolution_status,
                   is_repeat_contact, frustration_level, order_value, summary
            FROM tickets
            WHERE customer_id = ? AND ticket_id != ?
            ORDER BY timestamp DESC
            LIMIT 10
            """,
            (customer_id, ticket_id),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Tool: get_order_details
# ═════════════════════════════════════════════════════════════════════════════

def get_order_details(order_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT order_id, order_value, order_date, product_sku, product_category
            FROM tickets
            WHERE order_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()
    return row_to_dict(row) if row else {}


# ═════════════════════════════════════════════════════════════════════════════
# Tool: check_active_incidents
# FIX P3 — reads ONLY from the incidents table written by Agent 2.
#           No hardcoded SKUs. No fallback heuristic. If Agent 2 hasn't run,
#           this returns None and the ticket routes normally.
# ═════════════════════════════════════════════════════════════════════════════

def check_active_incidents(
    ticket: Dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    sku      = ticket.get("product_sku")
    category = ticket.get("category")
    if not sku or not category:
        return None

    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                """
                SELECT incident_id, title, severity, created_at, report, affected_sku
                FROM incidents
                WHERE active = 1
                  AND category = ?
                  AND (affected_sku = ? OR affected_sku = 'MULTIPLE')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (category, sku),
            ).fetchone()
        if row:
            return {
                "incident_id":   row["incident_id"],
                "title":         row["title"],
                "severity":      row["severity"],
                "created_at":    row["created_at"],
                "affected_sku":  row["affected_sku"],
                "reason":        row["report"],
            }
    except sqlite3.OperationalError:
        # incidents table doesn't exist yet — Agent 2 hasn't run. That's fine.
        pass

    return None


# ═════════════════════════════════════════════════════════════════════════════
# Tool: calculate_priority
# ═════════════════════════════════════════════════════════════════════════════

def calculate_priority(
    ticket:   Dict[str, Any],
    history:  List[Dict[str, Any]],
    incident: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    sentiment        = abs(float(ticket.get("sentiment_score") or 0))
    order_value      = float(ticket.get("order_value") or 0)
    tier             = ticket.get("customer_tier") or "regular"
    status           = ticket.get("resolution_status") or "pending"
    repeat_contact   = str(ticket.get("is_repeat_contact")).lower() == "true"
    unresolved_hist  = sum(
        1 for t in history
        if t.get("resolution_status") in {"unresolved", "escalated", "pending"}
    )

    tier_bonus     = {"regular": 0.0, "prime": 0.08, "prime_plus": 0.15}.get(tier, 0.0)
    value_bonus    = min(order_value / 200_000, 0.35)
    repeat_bonus   = 0.12 if repeat_contact else 0.0
    status_bonus   = 0.12 if status in {"unresolved", "escalated", "pending"} else 0.0
    history_bonus  = min(unresolved_hist * 0.04, 0.16)
    incident_bonus = 0.25 if incident else 0.0

    priority_score = min(1.0, sentiment + tier_bonus + value_bonus + repeat_bonus
                         + status_bonus + history_bonus + incident_bonus)

    sub = ticket.get("sub_category") or ""
    incident_severity = (incident or {}).get("severity", "").lower()
    # Active incidents raise priority but must not block simple auto-resolve templates.
    incident_forces_escalate = bool(
        incident
        and incident_severity == "critical"
        and sub not in AUTO_RESOLVE_SUBCATEGORIES
    )

    auto_escalate = bool(
        incident_forces_escalate
        or (priority_score > 0.85 and tier == "prime_plus")
        or (order_value > 100_000 and tier in {"prime", "prime_plus"})
        or (
            order_value > 50_000
            and ticket.get("frustration_level") == "critical"
            and status != "resolved"
        )
    )

    return {
        "priority_score":   round(priority_score, 3),
        "frustration_level": ticket.get("frustration_level") or "medium",
        "auto_escalate":    auto_escalate,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Tool: classify_ticket  (FIX P4)
# Primary: LLM with OpenAI.  Fallback: keyword rules.  No more RAG-first.
# ═════════════════════════════════════════════════════════════════════════════

def _keyword_classify(message: str) -> Dict[str, Any]:
    """Last-resort keyword classifier — used ONLY when there is no API key."""
    text  = message.lower()
    rules = [
        (["login", "log in", "otp", "password", "2fa", "two factor", "locked out"],
         "account_access", "cant_login"),
        (["account hacked", "unauthorized", "someone placed", "fraud"],
         "account_access", "account_hacked"),
        (["refund not received", "refund", "return", "pickup", "exchange"],
         "refund_return", "refund_not_received"),
        (["wrong item", "different product", "wrong model", "wrong color"],
         "product_quality", "wrong_item_sent"),
        (["damaged", "broken", "cracked", "shattered", "dead on arrival", "not working"],
         "product_quality", "damaged_in_transit"),
        (["fake", "counterfeit", "serial number", "not genuine", "original"],
         "fake_counterfeit", "fake_product"),
        (["double charged", "charged twice", "two debits", "duplicate charge"],
         "payment_billing", "double_charged"),
        (["payment failed", "money deducted", "upi", "net banking"],
         "payment_billing", "payment_deducted_order_failed"),
        (["coupon", "cashback", "discount not applied", "promo"],
         "payment_billing", "coupon_not_applied"),
        (["emi", "installment", "full amount charged"],
         "payment_billing", "emi_not_applied"),
        (["prime", "subscription", "prime video", "free delivery not"],
         "prime_subscription", "prime_benefits_not_showing"),
        (["marked delivered", "not received", "never received", "delivery photo"],
         "delivery", "not_delivered"),
        (["delayed", "late", "hasn't arrived", "waiting", "past expected"],
         "delivery", "delayed_delivery"),
        (["tracking", "in transit", "no update"],
         "delivery", "tracking_not_updating"),
        (["stolen", "left outside", "unattended", "lobby"],
         "delivery", "package_stolen"),
    ]
    for keywords, category, sub_category in rules:
        if any(kw in text for kw in keywords):
            return {
                "category": category,
                "sub_category": sub_category,
                "classification_reason": f"Keyword fallback: matched '{category}/{sub_category}'.",
                "confidence": 0.4,
            }
    return {
        "category": "delivery",
        "sub_category": "delayed_delivery",
        "classification_reason": "Default fallback — no strong signal found.",
        "confidence": 0.2,
    }


def classify_ticket_with_llm(message: str, rag_examples: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    FIX P4 — LLM is the PRIMARY classifier.
    RAG examples are passed as optional few-shot context to improve accuracy.
    Keywords only activate when OPENAI_API_KEY is absent.
    Returns: {category, sub_category, classification_reason, confidence}
    """
    if not os.getenv("OPENAI_API_KEY"):
        result = _keyword_classify(message)
        result["rag_examples"] = rag_examples or []
        return result

    allowed_json = json.dumps(CATEGORY_SUBCATEGORIES, indent=2)

    few_shot_block = ""
    if rag_examples:
        few_shot_block = "\n\nSimilar resolved tickets for reference:\n" + "\n".join(
            f"  [{i+1}] category={ex['category']} sub_category={ex['sub_category']}\n"
            f"       Message: {ex.get('text','')[:120]}"
            for i, ex in enumerate(rag_examples[:5])
        )

    prompt = f"""You are a customer support classifier for an Amazon-like e-commerce platform.

Classify the message below into exactly one category and sub_category from the allowed list.
Return ONLY a JSON object with these keys:
  - category          (string, from allowed list)
  - sub_category      (string, from allowed list under that category)
  - classification_reason  (string, ≤ 20 words explaining your choice)
  - confidence        (float 0.0–1.0, how certain you are)

Allowed taxonomy:
{allowed_json}
{few_shot_block}

Customer message:
\"\"\"{message}\"\"\"

Rules:
- Pick the MOST SPECIFIC sub_category that fits.
- If the customer mentions both payment and delivery, pick whichever is the primary complaint.
- Do NOT output markdown fences, only raw JSON.
"""

    try:
        response = get_chat_model().invoke(prompt)
        content  = response.content.strip()
        # Strip any accidental markdown fences
        content  = re.sub(r"^```[a-z]*\n?", "", content, flags=re.MULTILINE)
        content  = re.sub(r"```$", "", content, flags=re.MULTILINE).strip()
        # Extract the JSON object
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found in LLM response")
        parsed = json.loads(content[start:end+1])

        cat = parsed.get("category", "")
        sub = parsed.get("sub_category", "")
        if cat in CATEGORY_SUBCATEGORIES and sub in CATEGORY_SUBCATEGORIES[cat]:
            parsed["rag_examples"] = rag_examples or []
            return parsed
        else:
            # LLM hallucinated a label — try to recover
            print(f"[Agent 1] LLM returned invalid label {cat}/{sub}, falling back to keywords")
    except Exception as exc:
        print(f"[Agent 1] LLM classification error: {exc}")

    # Keyword fallback
    result = _keyword_classify(message)
    result["rag_examples"] = rag_examples or []
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Tool: search_similar_tickets (Chroma RAG)
# ═════════════════════════════════════════════════════════════════════════════

def _fallback_similar_tickets(sub_category: str, db_path: str) -> List[Dict[str, Any]]:
    """SQL fallback when Chroma is unavailable."""
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ticket_id, message, agent_reply, resolution_status, sub_category
            FROM tickets
            WHERE resolution_status = 'resolved'
              AND sub_category = ?
              AND agent_reply IS NOT NULL
              AND TRIM(agent_reply) != ''
            ORDER BY timestamp DESC
            LIMIT 3
            """,
            (sub_category,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def search_similar_tickets(
    ticket:         Dict[str, Any],
    db_path:        str = DEFAULT_DB_PATH,
    n_results:      int = 3,
    query_message:  Optional[str] = None,
) -> List[Dict[str, Any]]:
    sub_category = ticket.get("sub_category") or ""
    message      = query_message or ticket.get("message") or ""
    if not sub_category or not message:
        return []

    try:
        collection = get_chroma_collection()
        if collection.count() == 0:
            return _fallback_similar_tickets(sub_category, db_path)

        query_embedding = get_embeddings_model().embed_query(message)
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"sub_category": sub_category},
            include=["documents", "metadatas", "distances"],
        )
        distances    = result.get("distances", [[]])[0]
        similarities = distances_to_similarity_percent(distances)
        matches = [
            {
                "ticket_id":         meta.get("ticket_id"),
                "message_and_reply": result.get("documents", [[]])[0][i],
                "agent_reply":       meta.get("agent_reply"),
                "distance":          distances[i],
                "similarity_percent":similarities[i],
                "sub_category":      meta.get("sub_category"),
            }
            for i, meta in enumerate(result.get("metadatas", [[]])[0])
        ]
        return matches or _fallback_similar_tickets(sub_category, db_path)

    except Exception as exc:
        print(f"[Agent 1] Chroma search error ({exc}), using SQL fallback")
        return _fallback_similar_tickets(sub_category, db_path)


def search_classification_examples(message: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Pull RAG examples used as few-shot context for LLM classification."""
    try:
        collection = get_chroma_collection()
        if collection.count() == 0:
            return []
        query_embedding = get_embeddings_model().embed_query(message)
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )
        distances    = result.get("distances", [[]])[0]
        similarities = distances_to_similarity_percent(distances)
        return [
            {
                "ticket_id":         meta.get("ticket_id"),
                "category":          meta.get("category"),
                "sub_category":      meta.get("sub_category"),
                "text":              result.get("documents", [[]])[0][i],
                "agent_reply":       meta.get("agent_reply"),
                "distance":          distances[i],
                "similarity_percent":similarities[i],
            }
            for i, meta in enumerate(result.get("metadatas", [[]])[0])
        ]
    except Exception as exc:
        print(f"[Agent 1] Classification RAG lookup error: {exc}")
        return []


# ═════════════════════════════════════════════════════════════════════════════
# Tool: extract_key_entities
# ═════════════════════════════════════════════════════════════════════════════

def extract_key_entities(ticket: Dict[str, Any]) -> List[str]:
    text  = f"{ticket.get('message','')}\n{ticket.get('order_id','')}\n{ticket.get('product_sku','')}"
    regex = sorted(set(re.findall(
        r"\b(?:AMZ-[A-Z0-9-]+|TKT-[A-Z0-9]+|[A-Z]{2,}[A-Z0-9-]{2,}|₹\s?[\d,]+(?:\.\d+)?)\b",
        text,
    )))

    if not os.getenv("OPENAI_API_KEY"):
        return regex

    try:
        prompt = (
            "Extract all important customer-support entities from the ticket text as a JSON array of strings. "
            "Include: order IDs, product SKUs, money amounts (with ₹ symbol), dates, brand names, "
            "and key issue nouns. Return ONLY the JSON array, no fences.\n\n"
            f"Ticket: {ticket.get('message','')}"
        )
        response = get_chat_model().invoke(prompt)
        content  = response.content.strip().lstrip("```json").rstrip("```").strip()
        parsed   = json.loads(content) if content.startswith("[") else regex
        return sorted(set(str(e) for e in parsed + regex))
    except Exception as exc:
        print(f"[Agent 1] Entity extraction error: {exc}")
        return regex


# ═════════════════════════════════════════════════════════════════════════════
# Tool: generate_reply
# ═════════════════════════════════════════════════════════════════════════════

def generate_reply(
    ticket:         Dict[str, Any],
    order_details:  Dict[str, Any],
    similar_tickets: List[Dict[str, Any]],
) -> str:
    name = ticket.get("customer_name", "there")

    # Template replies for known auto-resolve patterns (no tokens wasted)
    sub = ticket.get("sub_category", "")
    if sub in AUTO_RESOLVE_REPLIES:
        return AUTO_RESOLVE_REPLIES[sub].format(name=name.split()[0])

    few_shot = "\n\n".join(
        f"Example {i+1}:\n{ex.get('message_and_reply') or ex.get('agent_reply','')}"
        for i, ex in enumerate(similar_tickets)
    )

    prompt = f"""You are a senior Amazon customer support agent. Write one concise, empathetic, 
actionable reply to this customer complaint. Be specific — reference the order ID, SKU, and amount.

Customer name:  {name}
Customer tier:  {ticket.get('customer_tier')}
Order ID:       {ticket.get('order_id')}
Product SKU:    {order_details.get('product_sku') or ticket.get('product_sku')}
Order value:    ₹{ticket.get('order_value')}
Category:       {ticket.get('category')} / {ticket.get('sub_category')}
Frustration:    {ticket.get('frustration_level')}
Message:        {ticket.get('message')}

Style examples from resolved similar tickets:
{few_shot or 'No examples available. Use a careful, empathetic support tone.'}

Rules:
- Start with "Hi {name.split()[0]},"
- Acknowledge the specific issue in the first sentence
- Give a concrete action or timeline (not vague "we will help")
- For prime_plus or high order values, offer a goodwill gesture (small credit / priority handling)
- Keep it under 80 words
"""

    if not os.getenv("OPENAI_API_KEY"):
        return (
            f"Hi {name.split()[0]}, I understand the issue with order {ticket.get('order_id')}. "
            "I've reviewed the details and will help resolve this as quickly as possible. "
            "You'll receive an update within 24 hours."
        )

    try:
        return get_chat_model().invoke(prompt).content.strip()
    except Exception as exc:
        print(f"[Agent 1] Reply generation error: {exc}")
        return (
            f"Hi {name.split()[0]}, I understand the issue with order {ticket.get('order_id')}. "
            "I've reviewed the details and will help resolve this quickly."
        )


# ═════════════════════════════════════════════════════════════════════════════
# Tool: enrichment scores
# ═════════════════════════════════════════════════════════════════════════════

def calculate_enrichment_scores(
    category:          str,
    order_value:       float,
    is_repeat_contact: bool,
    resolution_status: str = "pending",
) -> Dict[str, Any]:
    sentiment_score   = BASE_SENTIMENTS.get(category, -0.55)
    frustration_base  = -sentiment_score
    if order_value > 10_000:      frustration_base += 0.30
    if is_repeat_contact:          frustration_base += 0.25
    if resolution_status in {"unresolved", "escalated"}:
        frustration_base += 0.20

    if frustration_base < 0.20:    frustration_level = "low"
    elif frustration_base <= 0.50: frustration_level = "medium"
    elif frustration_base <= 0.80: frustration_level = "high"
    else:                           frustration_level = "critical"

    urgency_score  = min(1.0, BASE_URGENCY.get(category, 0.55) + (order_value / 200_000))
    revenue_at_risk = (
        order_value
        if resolution_status in {"unresolved", "escalated"}
        and frustration_level in {"high", "critical"}
        else 0.0
    )
    return {
        "sentiment_score":   round(sentiment_score, 3),
        "frustration_level": frustration_level,
        "urgency_score":     round(urgency_score, 3),
        "revenue_at_risk":   round(revenue_at_risk, 2),
    }


def count_previous_customer_tickets(
    customer_id: Optional[str],
    db_path:     str = DEFAULT_DB_PATH,
) -> int:
    if not customer_id:
        return 0
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM tickets WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
        return int(row["count"] or 0)
    except sqlite3.Error:
        return 0


def _message_for_rag_and_classify(raw_ticket: Dict[str, Any]) -> Tuple[str, str]:
    """Return (message_for_llm, message_for_embedding). Non-English → English for RAG."""
    message = raw_ticket.get("message") or ""
    lang = (raw_ticket.get("language") or "").strip().lower()
    if lang and lang != "en":
        lang_name = LANGUAGE_NAMES.get(lang, lang.upper())
        english = llm_translate_to_english(message, lang_name)
        return english, english
    return message, message


def draft_ticket_fields(
    raw_ticket: Dict[str, Any],
    db_path:    str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    message       = raw_ticket["message"]
    order_value   = float(raw_ticket.get("order_value") or 0)
    customer_id   = raw_ticket.get("customer_id")
    is_repeat     = count_previous_customer_tickets(customer_id, db_path) > 0

    classify_msg, rag_query = _message_for_rag_and_classify(raw_ticket)
    rag_examples   = search_classification_examples(rag_query)
    classification = classify_ticket_with_llm(classify_msg, rag_examples)

    resolution_status = "pending"
    scores = calculate_enrichment_scores(
        classification["category"], order_value, is_repeat, resolution_status,
    )
    entities = extract_key_entities({
        "message":     message,
        "order_id":    raw_ticket.get("order_id") or "",
        "product_sku": raw_ticket.get("product_sku") or "",
    })
    summary = raw_ticket.get("summary") or message[:180]

    return {
        **raw_ticket,
        "resolution_status":      resolution_status,
        "is_repeat_contact":      is_repeat,
        "category":               classification["category"],
        "sub_category":           classification["sub_category"],
        "sentiment_score":        scores["sentiment_score"],
        "frustration_level":      scores["frustration_level"],
        "urgency_score":          scores["urgency_score"],
        "revenue_at_risk":        scores["revenue_at_risk"],
        "summary":                summary,
        "key_entities":           entities,
        "suggested_fields_reason":classification.get("classification_reason", "LLM-classified."),
        "rag_examples":           classification.get("rag_examples", []),
    }


# ═════════════════════════════════════════════════════════════════════════════
# DB write helpers (used by nodes)
# ═════════════════════════════════════════════════════════════════════════════

def escalate_to_human(
    ticket_id: str,
    reason:    str,
    steps:     List[str],
    db_path:   str = DEFAULT_DB_PATH,
) -> None:
    ticket      = fetch_ticket(ticket_id, db_path)
    order_value = float(ticket.get("order_value") or 0)
    frustration = ticket.get("frustration_level")
    update_ticket_fields(ticket_id, {
        "resolution_status": "escalated",
        "revenue_at_risk":   order_value if frustration in {"high", "critical"} else 0.0,
        "agent_decision":    "escalate",
        "agent_reason":      reason,
        "agent_steps":       steps,   # serialised by update_ticket_fields
    }, db_path)


def auto_resolve(
    ticket_id: str,
    reply:     str,
    reason:    str,
    steps:     List[str],
    db_path:   str = DEFAULT_DB_PATH,
) -> None:
    update_ticket_fields(ticket_id, {
        "resolution_status": "resolved",
        "revenue_at_risk":   0.0,
        "suggested_reply":   reply,
        "agent_decision":    "auto_resolve",
        "agent_reason":      reason,
        "agent_steps":       steps,
    }, db_path)


def save_suggested_reply(
    ticket_id: str,
    reply:     str,
    reason:    str,
    steps:     List[str],
    db_path:   str = DEFAULT_DB_PATH,
) -> None:
    update_ticket_fields(ticket_id, {
        "suggested_reply": reply,
        "agent_decision":  "suggest_reply",
        "agent_reason":    reason,
        "agent_steps":     steps,
    }, db_path)


# ═════════════════════════════════════════════════════════════════════════════
# Chroma seeding helper (unchanged from v1, preserved here for completeness)
# ═════════════════════════════════════════════════════════════════════════════

def seed_chroma_from_sqlite(
    db_path:     str = DEFAULT_DB_PATH,
    max_vectors: Optional[int] = None,
) -> Dict[str, Any]:
    collection = get_chroma_collection()
    try:
        if collection.count():
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            client.delete_collection(COLLECTION_NAME)
            collection = client.create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": CHROMA_DISTANCE},
            )
    except Exception:
        collection = get_chroma_collection()

    with connect_db(db_path) as conn:
        query = """
            SELECT ticket_id, message, agent_reply, category, sub_category,
                   resolution_status, customer_tier, product_sku
            FROM tickets
            WHERE resolution_status = 'resolved'
              AND agent_reply IS NOT NULL
              AND TRIM(agent_reply) != ''
            ORDER BY timestamp DESC
        """
        rows = (
            conn.execute(query + " LIMIT ?", (max_vectors,)).fetchall()
            if max_vectors else
            conn.execute(query).fetchall()
        )

    model   = get_embeddings_model()
    added   = 0
    batch_sz = 64
    for start in range(0, len(rows), batch_sz):
        batch = rows[start:start + batch_sz]
        docs  = [
            f"Customer message: {r['message']}\nAgent reply: {r['agent_reply']}"
            for r in batch
        ]
        embeds = model.embed_documents(docs)
        collection.add(
            ids=[r["ticket_id"] for r in batch],
            documents=docs,
            embeddings=embeds,
            metadatas=[{
                "ticket_id":        r["ticket_id"],
                "category":         r["category"],
                "sub_category":     r["sub_category"],
                "resolution_status":r["resolution_status"],
                "customer_tier":    r["customer_tier"],
                "product_sku":      r["product_sku"],
                "agent_reply":      r["agent_reply"],
            } for r in batch],
        )
        added += len(batch)
        print(f"[Chroma seed] {added}/{len(rows)} vectors")

    return {"collection": COLLECTION_NAME, "persist_path": CHROMA_PATH, "vectors_added": added}


# ═════════════════════════════════════════════════════════════════════════════
# Step helper
# ═════════════════════════════════════════════════════════════════════════════

def add_step(state: Agent1State, message: str) -> Agent1State:
    # P6 FIX: always work with a proper Python list
    steps = _safe_load_json_list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    line = f"[Agent 1] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))
    return state


# ═════════════════════════════════════════════════════════════════════════════
# ── GRAPH NODES ───────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

# ── Node 1: load_ticket ───────────────────────────────────────────────────────
def node_load_ticket(state: Agent1State) -> Agent1State:
    ticket = fetch_ticket(state["ticket_id"], state.get("db_path", DEFAULT_DB_PATH))
    state["ticket"]       = ticket
    state["agent_steps"]  = []          # fresh list on every run
    state["key_entities"] = extract_key_entities(ticket)
    update_ticket_fields(
        state["ticket_id"],
        {"key_entities": state["key_entities"]},
        state.get("db_path", DEFAULT_DB_PATH),
    )
    return add_step(state,
        f"Loaded ticket {ticket['ticket_id']} | "
        f"category={ticket.get('category')} sub={ticket.get('sub_category')} | "
        f"tier={ticket.get('customer_tier')} | "
        f"order_value=₹{ticket.get('order_value')} | "
        f"entities={state['key_entities']}"
    )


def node_prepare_language(state: Agent1State) -> Agent1State:
    """Detect language, translate to English for processing, reclassify if needed."""
    ticket = state["ticket"]
    message = ticket.get("message") or ""
    state["original_message"] = message

    declared = (ticket.get("language") or "").strip().lower()
    if declared and declared != "en" and len(declared) == 2:
        code, name = declared, LANGUAGE_NAMES.get(declared, declared.upper())
        source = "declared in ticket"
    else:
        code, name = llm_detect_language(message)
        source = "auto-detected"

    state["detected_language"] = code
    state["detected_language_name"] = name

    if code == "en":
        state["translation_skipped"] = True
        state["translated_message"] = message
        state["translated_category"] = ticket.get("category", "")
        state["translated_sub_category"] = ticket.get("sub_category", "")
        return add_step(state, f"Language {source}: English — processing in original language.")

    state["translation_skipped"] = False
    translated = llm_translate_to_english(message, name)
    state["translated_message"] = translated

    orig_cat = ticket.get("category")
    orig_sub = ticket.get("sub_category")
    cat, sub = llm_classify_english(translated)
    state["translated_category"] = cat
    state["translated_sub_category"] = sub

    ticket = dict(ticket)
    ticket["message"] = translated
    ticket["category"] = cat
    ticket["sub_category"] = sub
    state["ticket"] = ticket

    reclass_note = (
        f" Re-classified: {orig_cat}/{orig_sub} -> {cat}/{sub}."
        if cat != orig_cat or sub != orig_sub
        else f" Classification confirmed: {cat}/{sub}."
    )
    preview = translated[:100].replace("\n", " ")
    return add_step(
        state,
        f"Language {source}: {name} ({code}). Translated for processing: \"{preview}…\".{reclass_note}",
    )


# ── Node 2: customer_history ──────────────────────────────────────────────────
def node_customer_history(state: Agent1State) -> Agent1State:
    ticket  = state["ticket"]
    history = get_customer_history(
        ticket["customer_id"], ticket["ticket_id"],
        state.get("db_path", DEFAULT_DB_PATH),
    )
    state["customer_history"] = history
    unresolved = sum(
        1 for t in history
        if t.get("resolution_status") in {"unresolved", "escalated", "pending"}
    )
    return add_step(state,
        f"Customer history: {len(history)} prior tickets | {unresolved} still open/unresolved"
    )


# ── Node 3: order_details ─────────────────────────────────────────────────────
def node_order_details(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    order  = get_order_details(ticket["order_id"], state.get("db_path", DEFAULT_DB_PATH))
    state["order_details"] = order
    return add_step(state,
        f"Order details: order_id={ticket['order_id']} | "
        f"SKU={order.get('product_sku')} | "
        f"value=₹{order.get('order_value')} | "
        f"date={order.get('order_date')}"
    )


# ── Node 4: check_incident ────────────────────────────────────────────────────
# FIX P3: ONLY reads from incidents table written by Agent 2. Zero hardcoding.
def node_check_incident(state: Agent1State) -> Agent1State:
    incident = check_active_incidents(state["ticket"], state.get("db_path", DEFAULT_DB_PATH))
    state["active_incident"] = incident
    if incident:
        return add_step(state,
            f"🚨 Active incident: '{incident['title']}' | "
            f"severity={incident['severity']} | "
            f"SKU={incident.get('affected_sku')}"
        )
    return add_step(state, "No active Agent-2 incident for this SKU/category.")


# ── Route A: after check_incident ─────────────────────────────────────────────
# Always run priority — routing happens in route_after_priority so simple issues
# (cant_login, etc.) can still auto-resolve during a category-wide incident.
def route_after_incident(state: Agent1State) -> str:
    return "calculate_priority"


# ── Node 5: calculate_priority ────────────────────────────────────────────────
def node_calculate_priority(state: Agent1State) -> Agent1State:
    result = calculate_priority(
        state["ticket"],
        state.get("customer_history", []),
        state.get("active_incident"),
    )
    state.update(result)
    return add_step(state,
        f"Priority score={state['priority_score']} | "
        f"frustration={state['frustration_level']} | "
        f"auto_escalate={state['auto_escalate']}"
    )


# ── Route B: after calculate_priority — 3-way split ──────────────────────────
# FIX P1 (main branch) + FIX P5 (auto-resolve detected here, not in finalize)
def route_after_priority(state: Agent1State) -> str:
    ticket = state["ticket"]
    cat    = ticket.get("category", "")
    sub    = ticket.get("sub_category", "")

    # P5 FIX: detect auto-resolvable tickets HERE, before any RAG/reply work
    if sub in AUTO_RESOLVE_SUBCATEGORIES and not state.get("auto_escalate"):
        return "auto_resolve_direct"

    # FIX P1: always-escalate categories — legal/security risk
    if cat in ALWAYS_ESCALATE_CATEGORIES or sub in ALWAYS_ESCALATE_SUBCATEGORIES:
        return "escalate_direct"

    if state.get("auto_escalate"):
        return "escalate_direct"

    return "retrieve_similar"


# ── Node 6a: escalate_ticket (from either route) ──────────────────────────────
def node_escalate_ticket(state: Agent1State) -> Agent1State:
    ticket   = state["ticket"]
    incident = state.get("active_incident")
    cat      = ticket.get("category", "")
    sub      = ticket.get("sub_category", "")

    if cat in ALWAYS_ESCALATE_CATEGORIES or sub in ALWAYS_ESCALATE_SUBCATEGORIES:
        reason = (
            f"Escalated — category '{cat}/{sub}' requires legal/security review. "
            f"Never suggest a reply for fraud or security breach tickets. "
            f"Customer tier: {ticket.get('customer_tier')} | "
            f"Order value: ₹{ticket.get('order_value')}"
        )
    elif incident:
        reason = (
            f"Escalated — active incident '{incident['title']}' "
            f"(severity={incident['severity']}) flagged by Agent 2 for SKU "
            f"'{incident.get('affected_sku')}'. "
            f"Priority score: {state.get('priority_score')} | "
            f"Customer tier: {ticket.get('customer_tier')}"
        )
    else:
        reason = (
            f"Escalated — priority_score={state.get('priority_score')} "
            f"for {ticket.get('customer_tier')} customer | "
            f"order_value=₹{ticket.get('order_value')} | "
            f"frustration={state.get('frustration_level')}"
        )

    state["decision"] = "escalate"
    state["reason"]   = reason
    add_step(state, f"🔺 DECISION: ESCALATE — {reason}")
    persist_multilingual_fields(state)
    escalate_to_human(
        ticket["ticket_id"], reason,
        state.get("agent_steps", []),
        state.get("db_path", DEFAULT_DB_PATH),
    )
    return state


# ── Node 6b: auto_resolve_direct ─────────────────────────────────────────────
# FIX P5: auto-resolve happens before any reply generation or RAG search
def node_auto_resolve(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    sub    = ticket.get("sub_category", "cant_login")
    name   = ticket.get("customer_name", "there")
    english = AUTO_RESOLVE_REPLIES.get(sub, AUTO_RESOLVE_REPLIES["cant_login"])
    english = english.format(name=name.split()[0])
    reason = f"Auto-resolved '{sub}' — standard guidance reply issued."

    localized = localize_outgoing_reply(state, english)
    if not state.get("translation_skipped"):
        add_step(
            state,
            f"Localized auto-resolve reply to {state.get('detected_language_name', '?')}.",
        )

    state["suggested_reply"] = localized
    state["decision"]        = "auto_resolve"
    state["reason"]          = reason
    add_step(state, f"✅ DECISION: AUTO-RESOLVE — {sub}")
    save_agent1_outcome(
        ticket["ticket_id"],
        state,
        suggested_reply=localized,
        agent_decision="auto_resolve",
        agent_reason=reason,
        resolution_status="resolved",
        revenue_at_risk=0.0,
    )
    return state


# ── Node 7: search_similar_tickets ───────────────────────────────────────────
def node_search_similar(state: Agent1State) -> Agent1State:
    query_msg = state.get("translated_message") or state["ticket"].get("message")
    matches = search_similar_tickets(
        state["ticket"],
        state.get("db_path", DEFAULT_DB_PATH),
        query_message=query_msg,
    )
    state["similar_tickets"] = matches
    pcts = [f"{m['similarity_percent']}%" for m in matches if "similarity_percent" in m]
    return add_step(state,
        f"RAG: retrieved {len(matches)} similar resolved tickets "
        f"(similarities: {', '.join(pcts) or 'SQL fallback'})"
    )


# ── Node 8: generate_reply ────────────────────────────────────────────────────
def node_generate_reply(state: Agent1State) -> Agent1State:
    english = generate_reply(
        state["ticket"],
        state.get("order_details", {}),
        state.get("similar_tickets", []),
    )
    state["english_reply"] = english
    localized = localize_outgoing_reply(state, english)
    state["suggested_reply"] = localized
    step = "Generated personalised RAG-grounded reply."
    if not state.get("translation_skipped"):
        step += f" Localized to {state.get('detected_language_name', '?')}."
    return add_step(state, step)


# ── Node 9: save_reply ────────────────────────────────────────────────────────
# FIX P5: no auto-resolve logic here — that was moved to route_after_priority
def node_save_reply(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    reply  = state.get("suggested_reply", "")
    reason = (
        f"Suggested personalised reply grounded in {len(state.get('similar_tickets',[]))} "
        f"similar resolved tickets via RAG."
    )
    state["decision"] = "suggest_reply"
    state["reason"]   = reason
    add_step(state, f"💬 DECISION: SUGGEST REPLY — {reason}")
    save_agent1_outcome(
        ticket["ticket_id"],
        state,
        suggested_reply=reply,
        agent_decision="suggest_reply",
        agent_reason=reason,
    )
    return state


# ═════════════════════════════════════════════════════════════════════════════
# Graph wiring
# ═════════════════════════════════════════════════════════════════════════════

graph = StateGraph(Agent1State)

# Register nodes
graph.add_node("load_ticket",          node_load_ticket)
graph.add_node("prepare_language",     node_prepare_language)
graph.add_node("customer_history",     node_customer_history)
graph.add_node("order_details",        node_order_details)
graph.add_node("check_incident",       node_check_incident)
graph.add_node("calculate_priority",   node_calculate_priority)
graph.add_node("search_similar",       node_search_similar)
graph.add_node("generate_reply",       node_generate_reply)
graph.add_node("save_reply",           node_save_reply)
graph.add_node("escalate_ticket",      node_escalate_ticket)
graph.add_node("auto_resolve_ticket",  node_auto_resolve)

# Fixed edges (always happen)
graph.set_entry_point("load_ticket")
graph.add_edge("load_ticket",      "prepare_language")
graph.add_edge("prepare_language", "customer_history")
graph.add_edge("customer_history", "order_details")
graph.add_edge("order_details",    "check_incident")

# ── Branch A: after check_incident ───────────────────────────────────────────
# Critical severity incident → skip priority → escalate immediately
# Otherwise → run priority calculation
graph.add_conditional_edges(
    "check_incident",
    route_after_incident,
    {
        "escalate_direct":    "escalate_ticket",   # critical incident bypass
        "calculate_priority": "calculate_priority",
    },
)

# ── Branch B: after calculate_priority (4-way) ───────────────────────────────
# auto_resolve_direct → simple issue, template reply, no LLM
# escalate_direct     → legal/security/VIP/high-value route
# retrieve_similar    → normal RAG path
graph.add_conditional_edges(
    "calculate_priority",
    route_after_priority,
    {
        "auto_resolve_direct": "auto_resolve_ticket",
        "escalate_direct":     "escalate_ticket",
        "retrieve_similar":    "search_similar",
    },
)

# Normal RAG path
graph.add_edge("search_similar",  "generate_reply")
graph.add_edge("generate_reply",  "save_reply")

# Terminal edges
graph.add_edge("escalate_ticket",     END)
graph.add_edge("auto_resolve_ticket", END)
graph.add_edge("save_reply",          END)

# Compile
app = graph.compile()


# ═════════════════════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def run_agent1_for_ticket(
    ticket_id: str,
    db_path:   str = DEFAULT_DB_PATH,
) -> Agent1State:
    initial: Agent1State = {
        "ticket_id":   ticket_id,
        "db_path":     db_path,
        "agent_steps": [],
    }
    return app.invoke(initial)


def run_multilingual_agent(ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> Agent1State:
    """Backward-compatible alias — multilingual is built into Agent 1."""
    return run_agent1_for_ticket(ticket_id, db_path)


def run_multilingual_batch(
    db_path:  str = DEFAULT_DB_PATH,
    language: Optional[str] = None,
    limit:    int = 100,
) -> Dict[str, Any]:
    lang_filter = "AND language != 'en'" if language is None else f"AND language = '{language}'"
    with connect_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT ticket_id FROM tickets
            WHERE language IS NOT NULL
              {lang_filter}
            ORDER BY urgency_score DESC, order_value DESC
            LIMIT {limit}
            """
        ).fetchall()

    ticket_ids = [r["ticket_id"] for r in rows]
    results = {"processed": 0, "skipped": 0, "errors": [], "ticket_ids": ticket_ids}

    for tid in ticket_ids:
        try:
            state = run_agent1_for_ticket(tid, db_path)
            if state.get("error"):
                results["errors"].append({"ticket_id": tid, "error": state["error"]})
            else:
                results["processed"] += 1
        except Exception as exc:
            results["errors"].append({"ticket_id": tid, "error": str(exc)})
            results["skipped"] += 1

    return results


def get_language_gap_report(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
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
    localized = ml_log_count

    return {
        "language_distribution": rows,
        "total_non_english_tickets": total_non_en,
        "localized_replies_generated": localized,
        "coverage_pct": round(localized / max(total_non_en, 1) * 100, 1),
        "insight": (
            f"{total_non_en} tickets were written in non-English languages. "
            f"{localized} have received localized replies via Agent 1 "
            f"({round(localized / max(total_non_en, 1) * 100, 1)}% coverage)."
        ),
    }


# ═════════════════════════════════════════════════════════════════════════════
# CLI / notebook
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        from IPython.display import Image, display
        display(Image(app.get_graph().draw_mermaid_png()))
    except Exception:
        print(app.get_graph().draw_mermaid())

    sample_id = os.getenv("SAMPLE_TICKET_ID", "TKT-AC2AE5B0")
    result    = run_agent1_for_ticket(sample_id, DEFAULT_DB_PATH)
    print(json.dumps(result, indent=2, default=str))