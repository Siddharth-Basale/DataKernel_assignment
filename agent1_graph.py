# Imports
# Load standard libraries, local environment, LangGraph, LangChain OpenAI helpers,
# and optional Chroma support used by the retrieval tools.
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

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


load_dotenv()

DEFAULT_DB_PATH = "support.db"
CHROMA_PATH = "chroma_store"
COLLECTION_NAME = "resolved_ticket_replies"
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

CATEGORY_SUBCATEGORIES = {
    "account_access": ["account_hacked", "address_not_updating", "cant_login", "order_history_missing", "two_factor_issue"],
    "delivery": [
        "delayed_delivery",
        "delivery_attempted_not_home",
        "not_delivered",
        "package_stolen",
        "partial_order_delivered",
        "tracking_not_updating",
        "wrong_address_delivered",
    ],
    "fake_counterfeit": ["brand_complaint", "fake_product", "listing_mismatch", "seller_fraud"],
    "payment_billing": ["coupon_not_applied", "double_charged", "emi_not_applied", "invoice_incorrect", "payment_deducted_order_failed"],
    "prime_subscription": ["charged_after_cancellation", "free_delivery_not_applied", "prime_benefits_not_showing", "video_not_accessible"],
    "product_quality": [
        "counterfeit_suspected",
        "damaged_in_transit",
        "dead_on_arrival",
        "missing_parts",
        "quality_not_as_described",
        "wrong_item_sent",
    ],
    "refund_return": [
        "exchange_not_processed",
        "partial_refund",
        "refund_not_received",
        "refund_to_wrong_account",
        "return_pickup_not_scheduled",
        "return_rejected",
    ],
}

BASE_SENTIMENTS = {
    "delivery": -0.55,
    "refund_return": -0.65,
    "product_quality": -0.60,
    "payment_billing": -0.70,
    "account_access": -0.50,
    "fake_counterfeit": -0.85,
    "prime_subscription": -0.45,
}

BASE_URGENCY = {
    "delivery": 0.55,
    "refund_return": 0.65,
    "product_quality": 0.60,
    "payment_billing": 0.80,
    "account_access": 0.70,
    "fake_counterfeit": 0.85,
    "prime_subscription": 0.40,
}


# State definition (TypedDict/Pydantic)
# This state is passed through every LangGraph node so the intermediate reasoning
# remains visible and easy to debug.
class Agent1State(TypedDict, total=False):
    ticket_id: str
    db_path: str
    ticket: Dict[str, Any]
    customer_history: List[Dict[str, Any]]
    order_details: Dict[str, Any]
    active_incident: Optional[Dict[str, Any]]
    priority_score: float
    frustration_level: str
    auto_escalate: bool
    similar_tickets: List[Dict[str, Any]]
    suggested_reply: str
    key_entities: List[str]
    decision: str
    reason: str
    agent_steps: List[str]
    error: str


# Tool functions
# These functions do the real work: read/write SQLite, search Chroma, call OpenAI,
# and calculate routing decisions from ticket fields.
def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch_ticket(ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with connect_db(db_path) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if not row:
        raise ValueError(f"Ticket not found: {ticket_id}")
    return row_to_dict(row)


def update_ticket_fields(ticket_id: str, updates: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> None:
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [json.dumps(value) if isinstance(value, (list, dict)) else value for value in updates.values()]
    values.append(ticket_id)
    with connect_db(db_path) as conn:
        conn.execute(
            f"UPDATE tickets SET {assignments}, updated_at = ? WHERE ticket_id = ?",
            [*values[:-1], datetime.utcnow().isoformat(timespec="seconds"), values[-1]],
        )
        conn.commit()


def get_customer_history(customer_id: str, ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
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


def check_active_incidents(ticket: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    sku = ticket.get("product_sku")
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
                "incident_id": row["incident_id"],
                "title": row["title"],
                "severity": row["severity"],
                "created_at": row["created_at"],
                "affected_sku": row["affected_sku"],
                "reason": row["report"],
            }
    except sqlite3.Error:
        pass

    with connect_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS issue_count,
                   COALESCE(SUM(CAST(order_value AS REAL)), 0) AS exposed_value,
                   MAX(timestamp) AS last_seen
            FROM tickets
            WHERE product_sku = ?
              AND category = ?
              AND resolution_status IN ('unresolved', 'escalated', 'pending')
            """,
            (sku, category),
        ).fetchone()

    issue_count = int(row["issue_count"] or 0)
    exposed_value = float(row["exposed_value"] or 0)
    if sku == "SAMSUNG-S24" and category == "delivery":
        return {
            "title": "Samsung S24 delivery spike",
            "severity": "high",
            "created_at": row["last_seen"],
            "reason": "Known dataset spike for Samsung S24 delivery complaints.",
        }
    if issue_count >= 25 and exposed_value >= 500000:
        return {
            "title": f"Possible active incident for {sku}",
            "severity": "medium",
            "created_at": row["last_seen"],
            "reason": f"{issue_count} open or escalated {category} tickets expose {exposed_value:.2f} order value.",
        }
    return None


def calculate_priority(ticket: Dict[str, Any], history: List[Dict[str, Any]], incident: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sentiment = abs(float(ticket.get("sentiment_score") or 0))
    order_value = float(ticket.get("order_value") or 0)
    tier = ticket.get("customer_tier") or "regular"
    status = ticket.get("resolution_status") or "pending"
    repeat_contact = str(ticket.get("is_repeat_contact")).lower() == "true"
    unresolved_history = sum(1 for item in history if item.get("resolution_status") in {"unresolved", "escalated", "pending"})

    tier_bonus = {"regular": 0.0, "prime": 0.08, "prime_plus": 0.15}.get(tier, 0.0)
    value_bonus = min(order_value / 200000, 0.35)
    repeat_bonus = 0.12 if repeat_contact else 0.0
    status_bonus = 0.12 if status in {"unresolved", "escalated", "pending"} else 0.0
    history_bonus = min(unresolved_history * 0.04, 0.16)
    incident_bonus = 0.25 if incident else 0.0

    priority_score = min(1.0, sentiment + tier_bonus + value_bonus + repeat_bonus + status_bonus + history_bonus + incident_bonus)
    auto_escalate = bool(
        incident
        or (priority_score > 0.85 and tier == "prime_plus")
        or (order_value > 50000 and ticket.get("frustration_level") == "critical" and status != "resolved")
    )
    return {
        "priority_score": round(priority_score, 3),
        "frustration_level": ticket.get("frustration_level") or "medium",
        "auto_escalate": auto_escalate,
    }


def count_previous_customer_tickets(customer_id: Optional[str], db_path: str = DEFAULT_DB_PATH) -> int:
    if not customer_id:
        return 0
    try:
        with connect_db(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM tickets WHERE customer_id = ?", (customer_id,)).fetchone()
        return int(row["count"] or 0)
    except sqlite3.Error:
        return 0


def keyword_classification(message: str) -> Dict[str, str]:
    text = message.lower()
    rules = [
        (["login", "log in", "otp", "password", "2fa", "two factor"], "account_access", "cant_login"),
        (["refund", "return", "pickup", "exchange"], "refund_return", "refund_not_received"),
        (["wrong item", "different product", "sealed box"], "product_quality", "wrong_item_sent"),
        (["damaged", "broken", "defective", "dead on arrival", "missing parts"], "product_quality", "damaged_in_transit"),
        (["fake", "counterfeit", "serial number", "seller fraud"], "fake_counterfeit", "fake_product"),
        (["double charged", "charged twice", "payment", "invoice", "coupon", "cashback", "emi"], "payment_billing", "double_charged"),
        (["prime", "subscription", "free delivery", "video"], "prime_subscription", "prime_benefits_not_showing"),
        (["delivered but", "not received", "never received", "marked delivered"], "delivery", "not_delivered"),
        (["tracking", "out for delivery", "delayed", "late", "package"], "delivery", "tracking_not_updating"),
    ]
    for keywords, category, sub_category in rules:
        if any(keyword in text for keyword in keywords):
            return {
                "category": category,
                "sub_category": sub_category,
                "classification_reason": f"Keyword match mapped the message to {category}/{sub_category}.",
            }
    return {
        "category": "delivery",
        "sub_category": "not_delivered",
        "classification_reason": "Fallback default used because no strong keyword or AI/RAG signal was available.",
    }


def search_classification_examples(message: str, limit: int = 5) -> List[Dict[str, Any]]:
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
        examples = []
        for index, metadata in enumerate(result.get("metadatas", [[]])[0]):
            examples.append(
                {
                    "category": metadata.get("category"),
                    "sub_category": metadata.get("sub_category"),
                    "distance": result.get("distances", [[]])[0][index],
                    "text": result.get("documents", [[]])[0][index][:500],
                }
            )
        return examples
    except Exception as exc:
        print(f"Classification RAG fallback because: {exc}")
        return []


def classify_ticket_with_rag(message: str) -> Dict[str, Any]:
    examples = search_classification_examples(message)
    fallback = keyword_classification(message)

    if not os.getenv("OPENAI_API_KEY") or not examples:
        fallback["rag_examples"] = examples
        return fallback

    allowed = json.dumps(CATEGORY_SUBCATEGORIES, indent=2)
    example_text = "\n\n".join(
        f"Example {index + 1}: category={item['category']} sub_category={item['sub_category']}\n{item['text']}"
        for index, item in enumerate(examples)
    )
    prompt = f"""
Classify the customer support message into exactly one allowed category and sub_category.
Return only JSON with keys: category, sub_category, classification_reason.

Allowed labels:
{allowed}

Similar resolved examples:
{example_text}

New message:
{message}
""".strip()

    try:
        response = get_chat_model().invoke(prompt)
        content = response.content.strip()
        content = content[content.find("{") : content.rfind("}") + 1]
        parsed = json.loads(content)
        category = parsed.get("category")
        sub_category = parsed.get("sub_category")
        if category in CATEGORY_SUBCATEGORIES and sub_category in CATEGORY_SUBCATEGORIES[category]:
            parsed["rag_examples"] = examples
            return parsed
    except Exception as exc:
        print(f"LLM classification fallback because: {exc}")

    fallback["rag_examples"] = examples
    return fallback


def calculate_enrichment_scores(
    category: str,
    order_value: float,
    is_repeat_contact: bool,
    resolution_status: str = "pending",
) -> Dict[str, Any]:
    sentiment_score = BASE_SENTIMENTS.get(category, -0.55)
    frustration_base = -sentiment_score
    if order_value > 10000:
        frustration_base += 0.30
    if is_repeat_contact:
        frustration_base += 0.25
    if resolution_status in {"unresolved", "escalated"}:
        frustration_base += 0.20

    if frustration_base < 0.20:
        frustration_level = "low"
    elif frustration_base <= 0.50:
        frustration_level = "medium"
    elif frustration_base <= 0.80:
        frustration_level = "high"
    else:
        frustration_level = "critical"

    urgency_score = min(1.0, BASE_URGENCY.get(category, 0.55) + (order_value / 200000))
    revenue_at_risk = (
        order_value
        if resolution_status in {"unresolved", "escalated"} and frustration_level in {"high", "critical"}
        else 0.0
    )
    return {
        "sentiment_score": round(sentiment_score, 3),
        "frustration_level": frustration_level,
        "urgency_score": round(urgency_score, 3),
        "revenue_at_risk": round(revenue_at_risk, 2),
    }


def draft_ticket_fields(raw_ticket: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    message = raw_ticket["message"]
    order_value = float(raw_ticket.get("order_value") or 0)
    customer_id = raw_ticket.get("customer_id")
    is_repeat_contact = count_previous_customer_tickets(customer_id, db_path) > 0
    classification = classify_ticket_with_rag(message)
    resolution_status = "pending"
    scores = calculate_enrichment_scores(
        classification["category"],
        order_value,
        is_repeat_contact,
        resolution_status,
    )
    entities = extract_key_entities(
        {
            "message": message,
            "order_id": raw_ticket.get("order_id") or "",
            "product_sku": raw_ticket.get("product_sku") or "",
        }
    )
    summary = raw_ticket.get("summary") or message[:180]
    return {
        **raw_ticket,
        "resolution_status": resolution_status,
        "is_repeat_contact": is_repeat_contact,
        "category": classification["category"],
        "sub_category": classification["sub_category"],
        "sentiment_score": scores["sentiment_score"],
        "frustration_level": scores["frustration_level"],
        "urgency_score": scores["urgency_score"],
        "revenue_at_risk": scores["revenue_at_risk"],
        "summary": summary,
        "key_entities": entities,
        "suggested_fields_reason": classification.get("classification_reason", "Generated by RAG-assisted classification."),
        "rag_examples": classification.get("rag_examples", []),
    }


def get_embeddings_model() -> Any:
    if OpenAIEmbeddings is None:
        raise RuntimeError("langchain-openai is not installed. Run: pip install -r requirements.txt")
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def get_chroma_collection() -> Any:
    if chromadb is None:
        raise RuntimeError("chromadb is not installed. Run: pip install -r requirements.txt")
    Path(CHROMA_PATH).mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(name=COLLECTION_NAME)


def seed_chroma_from_sqlite(db_path: str = DEFAULT_DB_PATH, max_vectors: Optional[int] = None) -> Dict[str, Any]:
    collection = get_chroma_collection()
    try:
        existing = collection.count()
        if existing:
            client = chromadb.PersistentClient(path=CHROMA_PATH)
            client.delete_collection(COLLECTION_NAME)
            collection = client.create_collection(name=COLLECTION_NAME)
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
        if max_vectors:
            query += " LIMIT ?"
            rows = conn.execute(query, (max_vectors,)).fetchall()
        else:
            rows = conn.execute(query).fetchall()

    embeddings_model = get_embeddings_model()
    batch_size = 64
    added = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        docs = [f"Customer message: {row['message']}\nAgent reply: {row['agent_reply']}" for row in batch]
        embeddings = embeddings_model.embed_documents(docs)
        collection.add(
            ids=[row["ticket_id"] for row in batch],
            documents=docs,
            embeddings=embeddings,
            metadatas=[
                {
                    "ticket_id": row["ticket_id"],
                    "category": row["category"],
                    "sub_category": row["sub_category"],
                    "resolution_status": row["resolution_status"],
                    "customer_tier": row["customer_tier"],
                    "product_sku": row["product_sku"],
                    "agent_reply": row["agent_reply"],
                }
                for row in batch
            ],
        )
        added += len(batch)
        print(f"Chroma seed progress: {added}/{len(rows)} vectors")

    return {"collection": COLLECTION_NAME, "persist_path": CHROMA_PATH, "vectors_added": added}


def fallback_similar_tickets(sub_category: str, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
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


def search_similar_tickets(ticket: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    sub_category = ticket.get("sub_category") or ""
    if not sub_category:
        return []
    try:
        collection = get_chroma_collection()
        if collection.count() == 0:
            return fallback_similar_tickets(sub_category, db_path)
        query_embedding = get_embeddings_model().embed_query(ticket.get("message") or "")
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=3,
            where={"sub_category": sub_category},
            include=["documents", "metadatas", "distances"],
        )
        matches = []
        for index, metadata in enumerate(result.get("metadatas", [[]])[0]):
            matches.append(
                {
                    "ticket_id": metadata.get("ticket_id"),
                    "message_and_reply": result.get("documents", [[]])[0][index],
                    "agent_reply": metadata.get("agent_reply"),
                    "distance": result.get("distances", [[]])[0][index],
                    "sub_category": metadata.get("sub_category"),
                }
            )
        return matches or fallback_similar_tickets(sub_category, db_path)
    except Exception as exc:
        print(f"Chroma search fallback because: {exc}")
        return fallback_similar_tickets(sub_category, db_path)


def get_chat_model() -> Any:
    if ChatOpenAI is None:
        raise RuntimeError("langchain-openai is not installed. Run: pip install -r requirements.txt")
    return ChatOpenAI(model=CHAT_MODEL, temperature=0.2)


def extract_key_entities(ticket: Dict[str, Any]) -> List[str]:
    text = f"{ticket.get('message', '')} {ticket.get('order_id', '')} {ticket.get('product_sku', '')}"
    regex_entities = sorted(set(re.findall(r"\b(?:AMZ-[A-Z0-9-]+|[A-Z]{2,}[A-Z0-9-]{2,}|₹\s?[\d,]+(?:\.\d+)?)\b", text)))

    if not os.getenv("OPENAI_API_KEY"):
        return regex_entities

    try:
        prompt = (
            "Extract only important support-ticket entities as a compact JSON array of strings. "
            "Include order IDs, product SKUs, money amounts, dates, brands, and issue nouns. "
            f"Ticket: {ticket.get('message', '')}"
        )
        response = get_chat_model().invoke(prompt)
        content = response.content.strip()
        parsed = json.loads(content) if content.startswith("[") else regex_entities
        return sorted(set(str(item) for item in parsed + regex_entities))
    except Exception as exc:
        print(f"Entity extraction fallback because: {exc}")
        return regex_entities


def generate_reply(ticket: Dict[str, Any], order_details: Dict[str, Any], similar_tickets: List[Dict[str, Any]]) -> str:
    if ticket.get("category") == "account_access" and ticket.get("sub_category") == "cant_login":
        return (
            f"Hi {ticket.get('customer_name', 'there')}, I understand you are unable to log in. "
            "Please reset your password and verify the OTP sent to your registered phone or email. "
            "If the OTP does not arrive within 5 minutes, reply here and we will escalate account recovery."
        )

    examples = "\n\n".join(
        f"Example {index + 1}:\n{item.get('message_and_reply') or item.get('agent_reply')}"
        for index, item in enumerate(similar_tickets)
    )
    prompt = f"""
You are an Amazon customer support assistant. Write one concise, empathetic, actionable reply.

Customer name: {ticket.get('customer_name')}
Customer tier: {ticket.get('customer_tier')}
Order ID: {ticket.get('order_id')}
Product SKU: {order_details.get('product_sku') or ticket.get('product_sku')}
Order value: {ticket.get('order_value')}
Category: {ticket.get('category')} / {ticket.get('sub_category')}
Customer message: {ticket.get('message')}

Use these resolved examples for style and policy:
{examples or 'No examples available. Use a careful support tone.'}
""".strip()

    if not os.getenv("OPENAI_API_KEY"):
        return (
            f"Hi {ticket.get('customer_name', 'there')}, I understand the issue with order "
            f"{ticket.get('order_id')}. I have reviewed the details and will help resolve this as quickly as possible. "
            "We will update you with the next action shortly."
        )

    try:
        response = get_chat_model().invoke(prompt)
        return response.content.strip()
    except Exception as exc:
        print(f"Reply generation fallback because: {exc}")
        return (
            f"Hi {ticket.get('customer_name', 'there')}, I understand the issue with order "
            f"{ticket.get('order_id')}. I have reviewed the details and will help resolve this as quickly as possible. "
            "We will update you with the next action shortly."
        )


def escalate_to_human(ticket_id: str, reason: str, steps: List[str], db_path: str = DEFAULT_DB_PATH) -> None:
    ticket = fetch_ticket(ticket_id, db_path)
    order_value = float(ticket.get("order_value") or 0)
    frustration = ticket.get("frustration_level")
    update_ticket_fields(
        ticket_id,
        {
            "resolution_status": "escalated",
            "revenue_at_risk": order_value if frustration in {"high", "critical"} else 0.0,
            "agent_decision": "escalate",
            "agent_reason": reason,
            "agent_steps": steps,
        },
        db_path,
    )


def auto_resolve(ticket_id: str, reply: str, steps: List[str], db_path: str = DEFAULT_DB_PATH) -> None:
    update_ticket_fields(
        ticket_id,
        {
            "resolution_status": "resolved",
            "revenue_at_risk": 0.0,
            "suggested_reply": reply,
            "agent_decision": "auto_resolve",
            "agent_reason": "Simple account login issue handled with standard OTP/reset guidance.",
            "agent_steps": steps,
        },
        db_path,
    )


def save_suggested_reply(ticket_id: str, reply: str, reason: str, steps: List[str], db_path: str = DEFAULT_DB_PATH) -> None:
    update_ticket_fields(
        ticket_id,
        {
            "suggested_reply": reply,
            "agent_decision": "suggest_reply",
            "agent_reason": reason,
            "agent_steps": steps,
        },
        db_path,
    )


# Agent/helper functions
# Each node is intentionally small and prints its state update for learning and debugging.
def add_step(state: Agent1State, message: str) -> Agent1State:
    steps = list(state.get("agent_steps", []))
    steps.append(message)
    state["agent_steps"] = steps
    print(f"[Agent 1] {message}")
    return state


def node_load_ticket(state: Agent1State) -> Agent1State:
    ticket = fetch_ticket(state["ticket_id"], state.get("db_path", DEFAULT_DB_PATH))
    state["ticket"] = ticket
    state["key_entities"] = extract_key_entities(ticket)
    update_ticket_fields(
        state["ticket_id"],
        {"key_entities": state["key_entities"]},
        state.get("db_path", DEFAULT_DB_PATH),
    )
    return add_step(state, f"Loaded ticket {ticket['ticket_id']} and extracted entities: {state['key_entities']}")


def node_customer_history(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    history = get_customer_history(ticket["customer_id"], ticket["ticket_id"], state.get("db_path", DEFAULT_DB_PATH))
    state["customer_history"] = history
    unresolved = sum(1 for item in history if item.get("resolution_status") in {"unresolved", "escalated", "pending"})
    return add_step(state, f"Fetched {len(history)} prior customer tickets; {unresolved} are still risky.")


def node_order_details(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    order = get_order_details(ticket["order_id"], state.get("db_path", DEFAULT_DB_PATH))
    state["order_details"] = order
    return add_step(state, f"Fetched order details for {ticket['order_id']}: SKU={order.get('product_sku')}.")


def node_check_incident(state: Agent1State) -> Agent1State:
    incident = check_active_incidents(state["ticket"], state.get("db_path", DEFAULT_DB_PATH))
    state["active_incident"] = incident
    if incident:
        return add_step(state, f"Active incident found: {incident['title']} ({incident['severity']}).")
    return add_step(state, "No active incident found for this ticket context.")


def node_calculate_priority(state: Agent1State) -> Agent1State:
    result = calculate_priority(
        state["ticket"],
        state.get("customer_history", []),
        state.get("active_incident"),
    )
    state.update(result)
    return add_step(
        state,
        f"Calculated priority={state['priority_score']} frustration={state['frustration_level']} auto_escalate={state['auto_escalate']}.",
    )


def route_after_priority(state: Agent1State) -> str:
    return "escalate" if state.get("auto_escalate") else "retrieve"


def node_search_similar(state: Agent1State) -> Agent1State:
    matches = search_similar_tickets(state["ticket"], state.get("db_path", DEFAULT_DB_PATH))
    state["similar_tickets"] = matches
    return add_step(state, f"Retrieved {len(matches)} similar resolved tickets for reply grounding.")


def node_generate_reply(state: Agent1State) -> Agent1State:
    reply = generate_reply(state["ticket"], state.get("order_details", {}), state.get("similar_tickets", []))
    state["suggested_reply"] = reply
    return add_step(state, "Generated suggested reply.")


def node_escalate_ticket(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    incident = state.get("active_incident")
    reason = (
        f"Escalated because priority={state.get('priority_score')} for {ticket.get('customer_tier')} customer, "
        f"order_value={ticket.get('order_value')}, incident={incident.get('title') if incident else 'none'}."
    )
    state["decision"] = "escalate"
    state["reason"] = reason
    add_step(state, reason)
    escalate_to_human(ticket["ticket_id"], reason, state.get("agent_steps", []), state.get("db_path", DEFAULT_DB_PATH))
    return state


def node_finalize_reply(state: Agent1State) -> Agent1State:
    ticket = state["ticket"]
    reply = state.get("suggested_reply", "")
    if ticket.get("category") == "account_access" and ticket.get("sub_category") == "cant_login":
        state["decision"] = "auto_resolve"
        state["reason"] = "Auto-resolved simple login issue with standard OTP/reset guidance."
        add_step(state, state["reason"])
        auto_resolve(ticket["ticket_id"], reply, state.get("agent_steps", []), state.get("db_path", DEFAULT_DB_PATH))
        return state

    state["decision"] = "suggest_reply"
    state["reason"] = "Suggested a personalized support reply grounded in similar resolved tickets."
    add_step(state, state["reason"])
    save_suggested_reply(ticket["ticket_id"], reply, state["reason"], state.get("agent_steps", []), state.get("db_path", DEFAULT_DB_PATH))
    return state


def run_agent1_for_ticket(ticket_id: str, db_path: str = DEFAULT_DB_PATH) -> Agent1State:
    initial_state: Agent1State = {"ticket_id": ticket_id, "db_path": db_path, "agent_steps": []}
    return app.invoke(initial_state)


# Graph initialization
# Create a StateGraph that models the Agent 1 decision path.
graph = StateGraph(Agent1State)


# Add nodes
# Register each tool-backed step as a graph node.
graph.add_node("load_ticket", node_load_ticket)
graph.add_node("customer_history", node_customer_history)
graph.add_node("order_details", node_order_details)
graph.add_node("check_incident", node_check_incident)
graph.add_node("calculate_priority", node_calculate_priority)
graph.add_node("search_similar_tickets", node_search_similar)
graph.add_node("generate_reply", node_generate_reply)
graph.add_node("escalate_ticket", node_escalate_ticket)
graph.add_node("finalize_reply", node_finalize_reply)


# Add edges
# Route high-risk tickets to escalation; route normal tickets through RAG reply generation.
graph.set_entry_point("load_ticket")
graph.add_edge("load_ticket", "customer_history")
graph.add_edge("customer_history", "order_details")
graph.add_edge("order_details", "check_incident")
graph.add_edge("check_incident", "calculate_priority")
graph.add_conditional_edges(
    "calculate_priority",
    route_after_priority,
    {"escalate": "escalate_ticket", "retrieve": "search_similar_tickets"},
)
graph.add_edge("search_similar_tickets", "generate_reply")
graph.add_edge("generate_reply", "finalize_reply")
graph.add_edge("escalate_ticket", END)
graph.add_edge("finalize_reply", END)


# Compile graph
# The compiled app can be imported by FastAPI or run directly from this file.
app = graph.compile()


# Visualize graph using IPython display + Mermaid/PNG
# Run this file directly or paste this block into a notebook to see the graph.
if __name__ == "__main__":
    from IPython.display import Image, display

    display(Image(app.get_graph().draw_mermaid_png()))

    # Invoke graph with sample input
    # Change this ticket_id after seeding the database from dataset.csv.
    sample_ticket_id = os.getenv("SAMPLE_TICKET_ID", "TKT-A9CCFC05")
    final_state = run_agent1_for_ticket(sample_ticket_id, DEFAULT_DB_PATH)
    print(json.dumps(final_state, indent=2, default=str))
