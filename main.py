# Minimal FastAPI backend for the customer-support insight platform.
# It owns HTTP endpoints, SQLite setup, CSV loading, and aggregate queries.
import csv
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


load_dotenv()

DATASET_PATH = "dataset.csv"
DB_PATH = os.getenv("SUPPORT_DB_PATH", "support.db")

CSV_COLUMNS = [
    "ticket_id",
    "timestamp",
    "customer_id",
    "customer_name",
    "customer_tier",
    "channel",
    "customer_country",
    "language",
    "product_category",
    "product_sku",
    "order_id",
    "order_date",
    "order_value",
    "message",
    "agent_reply",
    "resolution_status",
    "resolution_time_hrs",
    "is_repeat_contact",
    "category",
    "sub_category",
    "sentiment_score",
    "frustration_level",
    "urgency_score",
    "revenue_at_risk",
    "summary",
    "key_entities",
    "suggested_reply",
    "embedding_id",
]

EXTRA_COLUMNS = ["agent_decision", "agent_reason", "agent_steps", "updated_at"]

NUMERIC_COLUMNS = {"order_value", "resolution_time_hrs", "sentiment_score", "urgency_score", "revenue_at_risk"}


class TicketIngest(BaseModel):
    ticket_id: Optional[str] = Field(None, description="Optional ticket identifier. If omitted, the backend creates one like TKT-XXXXXXXX.")
    timestamp: Optional[str] = Field(None, description="Ticket creation timestamp in YYYY-MM-DD HH:MM:SS format. Defaults to current UTC time.")
    customer_id: Optional[str] = Field(None, description="Optional customer UUID. Used to detect repeat contact and fetch customer history.")
    customer_name: str = Field("Customer", description="Customer display name used for personalized replies.")
    customer_tier: str = Field("regular", description="Customer tier: regular, prime, or prime_plus. Higher tiers increase escalation priority.")
    channel: str = Field("web", description="Support channel: chat, email, web, or app.")
    customer_country: str = Field("IN", description="Customer country code, for example IN, US, UK, AE, SG.")
    language: str = Field("en", description="Message language code. Dataset examples include en, hi, ta, te, bn.")
    product_category: str = Field("General", description="Business product category such as Electronics, Beauty & Health, Clothing.")
    product_sku: str = Field("UNKNOWN-SKU", description="Product SKU mentioned in the complaint. Used for incident checks and routing.")
    order_id: Optional[str] = Field(None, description="Optional order ID. If omitted, the backend creates an AMZ-style ID.")
    order_date: Optional[str] = Field(None, description="Order date in YYYY-MM-DD format. Defaults to current date.")
    order_value: float = Field(0.0, description="Order value. Used for urgency, priority, and revenue-at-risk calculations.")
    message: str = Field(..., description="Raw customer complaint. This is the primary AI/RAG input.")
    agent_reply: str = Field("", description="Existing support reply, usually empty for new tickets.")
    resolution_status: str = Field("pending", description="System status: pending, resolved, unresolved, or escalated. New submitted tickets are normally pending.")
    resolution_time_hrs: Optional[float] = Field(None, description="Resolution time in hours. Usually empty for new tickets.")
    is_repeat_contact: bool = Field(False, description="Whether this customer has contacted support before. Draft flow calculates this when customer_id is provided.")
    category: str = Field("delivery", description="Top-level issue category. In draft flow, this is AI/RAG suggested.")
    sub_category: str = Field("not_delivered", description="Fine-grained issue label. In draft flow, this is AI/RAG suggested.")
    sentiment_score: float = Field(-0.55, description="Formula/AI sentiment score from -1.0 to +0.2; more negative means more unhappy.")
    frustration_level: str = Field("high", description="Formula-derived frustration: low, medium, high, or critical.")
    urgency_score: float = Field(0.55, description="Formula-derived urgency from 0 to 1.")
    revenue_at_risk: Optional[float] = Field(None, description="Financial exposure. Calculated from unresolved/escalated high-frustration tickets.")
    summary: str = Field("", description="Short ticket summary for dashboard and agent context.")
    key_entities: Union[str, List[str]] = Field("", description="Extracted order IDs, SKUs, amounts, brands, and other useful entities.")
    suggested_reply: str = Field("", description="Agent 1 generated response suggestion.")
    embedding_id: str = Field("", description="Reference to vector record, if stored separately.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "customer_name": "Neha Verma",
                "customer_tier": "regular",
                "channel": "web",
                "customer_country": "IN",
                "language": "en",
                "product_category": "Beauty & Health",
                "product_sku": "WOW-SHAMPOO-300ML",
                "order_value": 1556.26,
                "message": "I received the wrong item in my sealed package. I ordered WOW shampoo but got something else entirely.",
                "resolution_status": "pending",
                "is_repeat_contact": False,
                "category": "product_quality",
                "sub_category": "wrong_item_sent",
                "sentiment_score": -0.6,
                "frustration_level": "high",
                "urgency_score": 0.608,
                "summary": "Wrong item sent instead of WOW shampoo.",
            }
        }
    }


class TicketDraftRequest(BaseModel):
    message: str = Field(..., description="Raw customer message. The draft endpoint classifies this and extracts entities.")
    customer_tier: str = Field(..., description="Customer tier: regular, prime, or prime_plus.")
    product_sku: str = Field(..., description="SKU involved in the complaint. Used for RAG context and active-incident checks.")
    order_value: float = Field(..., description="Order value. Used in urgency and frustration formulas.")
    customer_name: str = Field("Customer", description="Customer name for personalization.")
    customer_id: Optional[str] = Field(
        None,
        description="Existing customer UUID. If provided, repeat-contact is calculated from SQLite history.",
        examples=["0e96b788-ed3c-4cdd-864d-d96afb0858b9"],
    )
    channel: str = Field("web", description="Support channel: chat, email, web, or app.")
    customer_country: str = Field("IN", description="Customer country code.")
    language: str = Field("en", description="Message language code.")
    product_category: str = Field("General", description="Business product category.")
    order_id: Optional[str] = Field(
        None,
        description="Optional existing order ID. If omitted, /tickets/submit generates one.",
        examples=["AMZ-21A0B8C3-F"],
    )
    order_date: Optional[str] = Field(
        None,
        description="Optional order date in YYYY-MM-DD format. If omitted, /tickets/submit uses today's date.",
        examples=["2025-01-14"],
    )
    summary: str = Field("", description="Optional human-provided summary. If empty, the message prefix is used.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Escalation draft: Samsung S24 delivery incident",
                    "value": {
                        "message": "My Samsung S24 order shows delivered but I never received it. This is urgent.",
                        "customer_tier": "prime_plus",
                        "product_sku": "SAMSUNG-S24",
                        "order_value": 89999,
                        "customer_name": "Aarav Sharma",
                        "customer_id": "0e96b788-ed3c-4cdd-864d-d96afb0858b9",
                        "channel": "chat",
                        "customer_country": "IN",
                        "language": "en",
                        "product_category": "Electronics",
                        "order_id": "AMZ-S24DEMO-1",
                        "order_date": "2025-01-14",
                    },
                },
                {
                    "summary": "Normal RAG reply draft: wrong item sent",
                    "value": {
                        "message": "I received the wrong item in my sealed package. I ordered WOW shampoo but got something else entirely.",
                        "customer_tier": "regular",
                        "product_sku": "WOW-SHAMPOO-300ML",
                        "order_value": 1556.26,
                        "customer_name": "Neha Verma",
                        "customer_id": "b0604cae-73b2-4348-be15-8afe98369ce3",
                        "channel": "web",
                        "customer_country": "IN",
                        "language": "en",
                        "product_category": "Beauty & Health",
                        "order_id": "AMZ-WOWDEMO-1",
                        "order_date": "2025-01-10",
                    },
                },
            ]
        }
    }


class TicketSubmitRequest(TicketIngest):
    suggested_fields_reason: Optional[str] = Field(None, description="Human-readable explanation for the AI/RAG-generated draft fields.")
    rag_examples: List[Dict[str, Any]] = Field(default_factory=list, description="Similar resolved tickets used as RAG examples during drafting.")

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "message": "I received the wrong item in my sealed package. I ordered WOW shampoo but got something else entirely.",
                "customer_tier": "regular",
                "product_sku": "WOW-SHAMPOO-300ML",
                "order_value": 1556.26,
                "customer_name": "Neha Verma",
                "customer_id": "b0604cae-73b2-4348-be15-8afe98369ce3",
                "channel": "web",
                "customer_country": "IN",
                "language": "en",
                "product_category": "Beauty & Health",
                "order_id": "AMZ-WOWDEMO-1",
                "order_date": "2025-01-10",
                "resolution_status": "pending",
                "is_repeat_contact": False,
                "category": "product_quality",
                "sub_category": "wrong_item_sent",
                "sentiment_score": -0.6,
                "frustration_level": "high",
                "urgency_score": 0.608,
                "revenue_at_risk": 0.0,
                "summary": "Wrong item sent instead of WOW shampoo.",
                "key_entities": ["WOW-SHAMPOO-300ML"],
                "suggested_fields_reason": "RAG examples and message text indicate a wrong item sent issue.",
                "rag_examples": [],
            }
        },
    )


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service status.")
    database: str = Field(..., description="SQLite database path.")
    tickets: int = Field(..., description="Number of tickets currently stored.")


class VectorSeedResponse(BaseModel):
    status: str = Field(..., description="ready, skipped, or failed.")
    collection: Optional[str] = Field(None, description="Chroma collection name.")
    persist_path: Optional[str] = Field(None, description="Local Chroma persistence directory.")
    vectors_added: Optional[int] = Field(None, description="Number of vectors embedded and added.")
    error: Optional[str] = Field(None, description="Failure message if vector refresh failed.")


class SeedResponse(BaseModel):
    rows_loaded: int = Field(..., description="Number of CSV rows inserted or upserted into SQLite.")
    database: str = Field(..., description="SQLite database path.")
    vectors: VectorSeedResponse = Field(..., description="Chroma vector refresh result.")


class TicketListResponse(BaseModel):
    total: int = Field(..., description="Total matching tickets before pagination.")
    limit: int = Field(..., description="Page size.")
    offset: int = Field(..., description="Pagination offset.")
    items: List[Dict[str, Any]] = Field(..., description="Ticket rows from SQLite.")


class TicketDraftResponse(BaseModel):
    draft: Dict[str, Any] = Field(..., description="AI/RAG enriched ticket draft to review before final submission.")
    submit_payload: Dict[str, Any] = Field(
        ...,
        description="Clean copy-paste payload for POST /tickets/submit. It removes debug-only RAG examples.",
    )
    next_step: str = Field(..., description="Instruction for submitting the confirmed draft.")


class TicketSubmitResponse(BaseModel):
    ticket_id: str = Field(..., description="Stored ticket ID.")
    stored_ticket: Dict[str, Any] = Field(..., description="Ticket row stored in SQLite after submission.")
    agent_state: Dict[str, Any] = Field(..., description="Final LangGraph Agent 1 state, including decision and steps.")


class AgentRunResponse(BaseModel):
    ticket_id: str = Field(..., description="Ticket processed by Agent 1.")
    agent_state: Dict[str, Any] = Field(..., description="Final LangGraph Agent 1 state.")


class Agent2RunResponse(BaseModel):
    incidents: List[Dict[str, Any]] = Field(..., description="Incidents created or refreshed by Agent 2.")
    agent_steps: List[str] = Field(..., description="Agent 2 progress log.")
    candidate_count: int = Field(..., description="Number of anomaly candidates selected for investigation.")


class IncidentListResponse(BaseModel):
    total: int = Field(..., description="Number of incidents returned.")
    items: List[Dict[str, Any]] = Field(..., description="Persisted incidents from SQLite.")


class Agent3RunResponse(BaseModel):
    retention_queue: List[Dict[str, Any]] = Field(..., description="Retention queue rows created or refreshed by Agent 3.")
    agent_steps: List[str] = Field(..., description="Agent 3 progress log.")
    selected_count: int = Field(..., description="Number of customers selected above churn threshold.")
    window_start: str = Field(..., description="Start date of the customer-risk scan window.")
    window_end: str = Field(..., description="End date of the customer-risk scan window.")


class RetentionQueueResponse(BaseModel):
    total: int = Field(..., description="Number of retention queue rows returned.")
    items: List[Dict[str, Any]] = Field(..., description="Persisted retention queue rows from SQLite.")


class CountItem(BaseModel):
    name: str = Field(..., description="Group name.")
    count: int = Field(..., description="Number of matching tickets.")


class InsightsResponse(BaseModel):
    totals: Dict[str, Any] = Field(..., description="Overall ticket count, unresolved count, revenue at risk, and averages.")
    top_categories: List[CountItem] = Field(..., description="Most frequent top-level issue categories.")
    top_sub_categories: List[CountItem] = Field(..., description="Most frequent fine-grained issue labels.")
    language_distribution: List[CountItem] = Field(..., description="Ticket counts by language.")
    status_distribution: List[CountItem] = Field(..., description="Ticket counts by resolution status.")
    sentiment_by_category: List[Dict[str, Any]] = Field(..., description="Per-category sentiment and revenue-at-risk aggregates.")


app = FastAPI(
    title="Customer Support Insight Platform - Agent 1 + Agent 2 + Agent 3",
    version="1.3.0",
    description=(
        "Local FastAPI backend for AI-powered customer support triage. "
        "Use `/tickets/draft` to enrich a minimal customer complaint, review the generated fields, "
        "then send the confirmed object to `/tickets/submit` to store it and run LangGraph Agent 1."
    ),
    contact={"name": "Datakernel Assignment Demo"},
    openapi_tags=[
        {"name": "System", "description": "Health checks and dataset seeding."},
        {"name": "Tickets", "description": "Ticket listing, drafting, submission, and lookup."},
        {"name": "Agent 1", "description": "LangGraph ticket resolution agent: suggest reply, auto-resolve, or escalate."},
        {"name": "Agent 2", "description": "LangGraph anomaly investigation agent: detect spikes, create incidents, and flag SKUs."},
        {"name": "Agent 3", "description": "LangGraph customer risk agent: score churn risk and draft retention offers."},
        {"name": "Insights", "description": "Dashboard-style aggregate metrics from SQLite."},
    ],
)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def column_definition(column: str) -> str:
    if column == "ticket_id":
        return "ticket_id TEXT PRIMARY KEY"
    if column in NUMERIC_COLUMNS:
        return f"{column} REAL"
    return f"{column} TEXT"


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True) if Path(DB_PATH).parent != Path(".") else None
    columns = [column_definition(column) for column in CSV_COLUMNS]
    columns.extend([f"{column} TEXT" for column in EXTRA_COLUMNS])
    with connect_db() as conn:
        conn.execute(f"CREATE TABLE IF NOT EXISTS tickets ({', '.join(columns)})")
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


def normalize_csv_value(column: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    if column in NUMERIC_COLUMNS:
        try:
            return float(value)
        except ValueError:
            return None
    return str(value)


def insert_ticket(row: Dict[str, Any]) -> None:
    payload = {column: normalize_csv_value(column, row.get(column)) for column in CSV_COLUMNS}
    payload["ticket_id"] = payload["ticket_id"] or f"TKT-{uuid.uuid4().hex[:8].upper()}"
    columns = CSV_COLUMNS
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "ticket_id")
    with connect_db() as conn:
        conn.execute(
            f"""
            INSERT INTO tickets ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(ticket_id) DO UPDATE SET {updates}
            """,
            [payload[column] for column in columns],
        )
        conn.commit()


def build_ingest_row(ticket: Any) -> Dict[str, Any]:
    if isinstance(ticket, dict):
        if "message" not in ticket:
            raise ValueError("message is required")
        data = TicketIngest(message=ticket["message"]).model_dump()
        data.update(ticket)
    else:
        data = ticket.model_dump() if hasattr(ticket, "model_dump") else ticket.dict()
    now = datetime.utcnow()
    data["ticket_id"] = data["ticket_id"] or f"TKT-{uuid.uuid4().hex[:8].upper()}"
    data["timestamp"] = data["timestamp"] or now.strftime("%Y-%m-%d %H:%M:%S")
    data["customer_id"] = data["customer_id"] or str(uuid.uuid4())
    data["order_id"] = data["order_id"] or f"AMZ-{uuid.uuid4().hex[:10].upper()}"
    data["order_date"] = data["order_date"] or now.strftime("%Y-%m-%d")
    if data["revenue_at_risk"] is None:
        risky_status = data["resolution_status"] in {"unresolved", "escalated", "pending"}
        risky_frustration = data["frustration_level"] in {"high", "critical"}
        data["revenue_at_risk"] = data["order_value"] if risky_status and risky_frustration else 0.0
    if not data["summary"]:
        data["summary"] = data["message"][:180]
    data["is_repeat_contact"] = str(data["is_repeat_contact"])
    return data


def aggregate_counts(column: str, limit: int = 10) -> List[Dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT {column} AS name, COUNT(*) AS count
            FROM tickets
            WHERE {column} IS NOT NULL AND TRIM({column}) != ''
            GROUP BY {column}
            ORDER BY count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def run_agent(ticket_id: str) -> Dict[str, Any]:
    try:
        from agent1_graph import run_agent1_for_ticket
    except Exception as exc:
        raise RuntimeError("Agent 1 dependencies are missing. Run: pip install -r requirements.txt") from exc
    return run_agent1_for_ticket(ticket_id, DB_PATH)


def refresh_chroma_vectors(max_vectors: Optional[int] = None) -> Dict[str, Any]:
    try:
        from agent1_graph import seed_chroma_from_sqlite
    except Exception as exc:
        raise RuntimeError("Chroma/LangChain dependencies are missing. Run: pip install -r requirements.txt") from exc
    return seed_chroma_from_sqlite(DB_PATH, max_vectors=max_vectors)


def draft_ticket(raw_ticket: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from agent1_graph import draft_ticket_fields
    except Exception as exc:
        raise RuntimeError("Draft enrichment dependencies are missing. Run: pip install -r requirements.txt") from exc
    return draft_ticket_fields(raw_ticket, DB_PATH)


def run_agent2(
    threshold: float,
    max_incidents: int,
    start_date: str,
    end_date: str,
) -> Dict[str, Any]:
    try:
        from agent2_graph import run_agent2_investigation
    except Exception as exc:
        raise RuntimeError("Agent 2 dependencies are missing. Run: pip install -r requirements.txt") from exc
    return run_agent2_investigation(DB_PATH, threshold, max_incidents, start_date, end_date)


def run_agent3(
    end_date: str,
    lookback_days: int,
    min_ticket_count: int,
    churn_threshold: float,
    max_customers: int,
) -> Dict[str, Any]:
    try:
        from agent3_graph import run_agent3_customer_risk
    except Exception as exc:
        raise RuntimeError("Agent 3 dependencies are missing. Run: pip install -r requirements.txt") from exc
    return run_agent3_customer_risk(DB_PATH, end_date, lookback_days, min_ticket_count, churn_threshold, max_customers)


def build_submit_payload(draft: Dict[str, Any]) -> Dict[str, Any]:
    submit_fields = [
        "ticket_id",
        "timestamp",
        "customer_id",
        "customer_name",
        "customer_tier",
        "channel",
        "customer_country",
        "language",
        "product_category",
        "product_sku",
        "order_id",
        "order_date",
        "order_value",
        "message",
        "agent_reply",
        "resolution_status",
        "resolution_time_hrs",
        "is_repeat_contact",
        "category",
        "sub_category",
        "sentiment_score",
        "frustration_level",
        "urgency_score",
        "revenue_at_risk",
        "summary",
        "key_entities",
        "suggested_reply",
        "embedding_id",
    ]
    return {field: draft[field] for field in submit_fields if field in draft and draft[field] is not None}


def decode_incident_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = row_to_dict(row)
    for field in ["top_skus", "sample_ticket_ids"]:
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except json.JSONDecodeError:
                data[field] = []
        else:
            data[field] = []
    data["active"] = bool(data.get("active"))
    return data


def decode_retention_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = row_to_dict(row)
    data["is_repeat"] = bool(data.get("is_repeat"))
    data["active"] = bool(data.get("active"))
    data.pop("profile_json", None)
    return data


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Check API and SQLite status",
    description="Returns service status, SQLite database path, and the current ticket count.",
)
def health() -> Dict[str, Any]:
    init_db()
    with connect_db() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM tickets").fetchone()["count"]
    return {"status": "ok", "database": DB_PATH, "tickets": count}


@app.post(
    "/seed",
    response_model=SeedResponse,
    tags=["System"],
    summary="Load dataset.csv and optionally refresh Chroma vectors",
    description=(
        "Upserts every row from `dataset.csv` into SQLite. "
        "When `refresh_vectors=true`, resolved tickets with non-empty agent replies are embedded into local Chroma. "
        "Use `max_vectors` for low-cost demos."
    ),
)
def seed(
    refresh_vectors: Annotated[
        bool,
        Query(description="If true, rebuild local Chroma vectors after loading CSV rows."),
    ] = True,
    max_vectors: Annotated[
        Optional[int],
        Query(description="Optional cap for quick demos to reduce OpenAI embedding calls."),
    ] = None,
) -> Dict[str, Any]:
    init_db()
    if not Path(DATASET_PATH).exists():
        raise HTTPException(status_code=404, detail=f"{DATASET_PATH} not found")

    loaded = 0
    with open(DATASET_PATH, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            insert_ticket(row)
            loaded += 1

    vector_result: Dict[str, Any] = {"status": "skipped"}
    if refresh_vectors:
        try:
            vector_result = refresh_chroma_vectors(max_vectors=max_vectors)
            vector_result["status"] = "ready"
        except Exception as exc:
            vector_result = {"status": "failed", "error": str(exc)}

    return {"rows_loaded": loaded, "database": DB_PATH, "vectors": vector_result}


@app.get(
    "/tickets",
    response_model=TicketListResponse,
    tags=["Tickets"],
    summary="List tickets with optional filters",
    description="Returns paginated ticket rows from SQLite. Filter by category and/or resolution status for demo views.",
)
def list_tickets(
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum tickets to return.")] = 20,
    offset: Annotated[int, Query(ge=0, description="Number of matching tickets to skip.")] = 0,
    category: Annotated[Optional[str], Query(description="Optional top-level category filter, such as delivery.")] = None,
    status: Annotated[Optional[str], Query(description="Optional resolution status filter: pending, resolved, unresolved, escalated.")] = None,
) -> Dict[str, Any]:
    init_db()
    where = []
    params: List[Any] = []
    if category:
        where.append("category = ?")
        params.append(category)
    if status:
        where.append("resolution_status = ?")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM tickets
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) AS count FROM tickets {where_sql}", params).fetchone()["count"]
    return {"total": total, "limit": limit, "offset": offset, "items": [row_to_dict(row) for row in rows]}


@app.post(
    "/tickets/draft",
    response_model=TicketDraftResponse,
    tags=["Tickets"],
    summary="Generate an AI/RAG enriched ticket draft",
    description=(
        "Send only the minimal customer complaint fields. The backend suggests category/sub_category with RAG-assisted AI, "
        "calculates sentiment/frustration/urgency from assignment formulas, extracts key entities, and returns a draft for review."
    ),
)
def create_ticket_draft(
    ticket: Annotated[
        TicketDraftRequest,
        Body(
            openapi_examples={
                "escalation_incident": {
                    "summary": "Escalation draft: Samsung S24 delivery incident",
                    "description": "Includes customer_id, order_id, and order_date. Should draft as delivery/not_delivered and later escalate on submit.",
                    "value": {
                        "message": "My Samsung S24 order shows delivered but I never received it. This is urgent.",
                        "customer_tier": "prime_plus",
                        "product_sku": "SAMSUNG-S24",
                        "order_value": 89999,
                        "customer_name": "Aarav Sharma",
                        "customer_id": "0e96b788-ed3c-4cdd-864d-d96afb0858b9",
                        "channel": "chat",
                        "customer_country": "IN",
                        "language": "en",
                        "product_category": "Electronics",
                        "order_id": "AMZ-S24DEMO-1",
                        "order_date": "2025-01-14",
                    },
                },
                "normal_rag_reply": {
                    "summary": "Normal RAG draft: wrong item sent",
                    "description": "Should draft as product_quality/wrong_item_sent and later generate a suggested reply on submit.",
                    "value": {
                        "message": "I received the wrong item in my sealed package. I ordered WOW shampoo but got something else entirely.",
                        "customer_tier": "regular",
                        "product_sku": "WOW-SHAMPOO-300ML",
                        "order_value": 1556.26,
                        "customer_name": "Neha Verma",
                        "customer_id": "b0604cae-73b2-4348-be15-8afe98369ce3",
                        "channel": "web",
                        "customer_country": "IN",
                        "language": "en",
                        "product_category": "Beauty & Health",
                        "order_id": "AMZ-WOWDEMO-1",
                        "order_date": "2025-01-10",
                    },
                },
                "auto_resolve_login": {
                    "summary": "Auto-resolve draft: login/OTP issue",
                    "description": "Should draft as account_access/cant_login and later auto-resolve on submit.",
                    "value": {
                        "message": "I cannot login to my account because OTP is not working.",
                        "customer_tier": "regular",
                        "product_sku": "ACCOUNT-LOGIN",
                        "order_value": 0,
                        "customer_name": "Rahul Mehta",
                        "customer_id": "9a89f73b-d7f6-40a8-a1d4-356301da9bd9",
                        "channel": "app",
                        "customer_country": "IN",
                        "language": "en",
                        "product_category": "Account",
                        "order_id": "AMZ-LOGINDEMO-1",
                        "order_date": "2025-01-16",
                    },
                },
            }
        ),
    ],
) -> Dict[str, Any]:
    init_db()
    data = ticket.model_dump() if hasattr(ticket, "model_dump") else ticket.dict()
    try:
        draft = draft_ticket(data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "draft": draft,
        "submit_payload": build_submit_payload(draft),
        "next_step": "Copy submit_payload into POST /tickets/submit after reviewing or editing it.",
    }


@app.post(
    "/tickets/submit",
    response_model=TicketSubmitResponse,
    tags=["Tickets"],
    summary="Submit a reviewed draft and run Agent 1",
    description=(
        "Paste the `draft` object returned by `/tickets/draft`, optionally edit fields, and submit it. "
        "The backend stores the ticket as pending, then runs LangGraph Agent 1 to suggest a reply, auto-resolve, or escalate."
    ),
)
def submit_ticket(ticket: TicketSubmitRequest) -> Dict[str, Any]:
    init_db()
    try:
        row = build_ingest_row(ticket)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row["resolution_status"] = "pending"
    insert_ticket(row)
    try:
        final_state = run_agent(row["ticket_id"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "ticket_id": row["ticket_id"],
        "stored_ticket": get_ticket(row["ticket_id"]),
        "agent_state": final_state,
    }


@app.get(
    "/tickets/{ticket_id}",
    response_model=Dict[str, Any],
    tags=["Tickets"],
    summary="Get one ticket by ID",
    description="Returns the complete SQLite row for a single ticket, including Agent 1 fields if processed.",
)
def get_ticket(ticket_id: str) -> Dict[str, Any]:
    init_db()
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return row_to_dict(row)


@app.post(
    "/tickets/ingest",
    response_model=AgentRunResponse,
    tags=["Tickets"],
    summary="Direct ticket ingest shortcut",
    description=(
        "Legacy one-step demo endpoint. It accepts a full ticket payload, stores it, and runs Agent 1 immediately. "
        "Prefer `/tickets/draft` followed by `/tickets/submit` for the clearer review flow."
    ),
)
def ingest_ticket(ticket: TicketIngest) -> Dict[str, Any]:
    init_db()
    row = build_ingest_row(ticket)
    insert_ticket(row)
    try:
        final_state = run_agent(row["ticket_id"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ticket_id": row["ticket_id"], "agent_state": final_state}


@app.post(
    "/agent1/run/{ticket_id}",
    response_model=AgentRunResponse,
    tags=["Agent 1"],
    summary="Run Agent 1 on an existing ticket",
    description=(
        "Loads an existing ticket from SQLite and runs the LangGraph Agent 1 workflow again. "
        "This does not create a follow-up message; it reprocesses the stored ticket."
    ),
)
def run_agent1(ticket_id: str) -> Dict[str, Any]:
    init_db()
    try:
        final_state = run_agent(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ticket_id": ticket_id, "agent_state": final_state}


@app.post(
    "/agent2/run",
    response_model=Agent2RunResponse,
    tags=["Agent 2"],
    summary="Run Agent 2 anomaly investigation",
    description=(
        "Runs the Day-9 anomaly investigation flow from the implementation plan. "
        "It scans historical category volumes, computes 7-day rolling z-scores, investigates the plan's three known spike windows, "
        "writes incidents to SQLite, and flags affected SKUs for Agent 1."
    ),
)
def run_agent2_endpoint(
    threshold: Annotated[float, Query(description="Z-score threshold for selecting anomaly windows.")] = 2.0,
    max_incidents: Annotated[int, Query(ge=1, le=10, description="Maximum incidents to create in one run.")] = 3,
    start_date: Annotated[str, Query(description="Start date for historical scan, YYYY-MM-DD.")] = "2024-07-01",
    end_date: Annotated[str, Query(description="End date for historical scan, YYYY-MM-DD.")] = "2025-01-31",
) -> Dict[str, Any]:
    init_db()
    try:
        state = run_agent2(threshold, max_incidents, start_date, end_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "incidents": state.get("incidents", []),
        "agent_steps": state.get("agent_steps", []),
        "candidate_count": len(state.get("candidates", [])),
    }


@app.get(
    "/agent2/incidents",
    response_model=IncidentListResponse,
    tags=["Agent 2"],
    summary="List persisted Agent 2 incidents",
    description="Returns incidents written by Agent 2. Agent 1 reads these active incidents during escalation checks.",
)
def list_agent2_incidents(
    active_only: Annotated[bool, Query(description="If true, return only active incidents.")] = True,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum incidents to return.")] = 20,
) -> Dict[str, Any]:
    init_db()
    where_sql = "WHERE active = 1" if active_only else ""
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM incidents
            {where_sql}
            ORDER BY created_at DESC, severity DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = [decode_incident_row(row) for row in rows]
    return {"total": len(items), "items": items}


@app.post(
    "/agent3/run",
    response_model=Agent3RunResponse,
    tags=["Agent 3"],
    summary="Run Agent 3 customer risk scan",
    description=(
        "Runs the Day-10 customer risk flow from the implementation plan. "
        "It scans high-contact customers in a lookback window, computes churn risk, estimates recent lifetime value, "
        "drafts personalized retention offers, and writes a prioritized retention queue."
    ),
)
def run_agent3_endpoint(
    end_date: Annotated[str, Query(description="End date for the customer-risk scan, YYYY-MM-DD. Defaults to seeded dataset end window.")] = "2025-01-31",
    lookback_days: Annotated[int, Query(ge=1, le=365, description="How many days before end_date to scan.")] = 90,
    min_ticket_count: Annotated[int, Query(ge=2, le=20, description="Minimum tickets in the window to consider a customer high-contact.")] = 2,
    churn_threshold: Annotated[float, Query(description="Minimum churn score required for retention queue inclusion.")] = 3.0,
    max_customers: Annotated[int, Query(ge=1, le=100, description="Maximum customers to write to the retention queue.")] = 20,
) -> Dict[str, Any]:
    init_db()
    try:
        state = run_agent3(end_date, lookback_days, min_ticket_count, churn_threshold, max_customers)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "retention_queue": state.get("retention_queue", []),
        "agent_steps": state.get("agent_steps", []),
        "selected_count": len(state.get("retention_queue", [])),
        "window_start": state.get("start_date", ""),
        "window_end": state.get("end_date", end_date),
    }


@app.get(
    "/agent3/retention-queue",
    response_model=RetentionQueueResponse,
    tags=["Agent 3"],
    summary="List Agent 3 retention queue",
    description="Returns the prioritized retention queue written by Agent 3, sorted by retention priority.",
)
def list_agent3_retention_queue(
    active_only: Annotated[bool, Query(description="If true, return only active queue rows.")] = True,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum queue rows to return.")] = 20,
) -> Dict[str, Any]:
    init_db()
    where_sql = "WHERE active = 1" if active_only else ""
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM retention_queue
            {where_sql}
            ORDER BY retention_priority DESC, churn_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = [decode_retention_row(row) for row in rows]
    return {"total": len(items), "items": items}


@app.get(
    "/insights",
    response_model=InsightsResponse,
    tags=["Insights"],
    summary="Get dashboard aggregate metrics",
    description="Returns leadership/dashboard metrics such as top issues, status distribution, sentiment, and revenue at risk.",
)
def insights() -> Dict[str, Any]:
    init_db()
    with connect_db() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS ticket_count,
                   SUM(CASE WHEN resolution_status IN ('unresolved', 'pending', 'escalated') THEN 1 ELSE 0 END) AS unresolved_count,
                   COALESCE(SUM(CAST(revenue_at_risk AS REAL)), 0) AS revenue_at_risk,
                   AVG(CAST(sentiment_score AS REAL)) AS avg_sentiment,
                   AVG(CAST(urgency_score AS REAL)) AS avg_urgency
            FROM tickets
            """
        ).fetchone()
        by_category = conn.execute(
            """
            SELECT category,
                   COUNT(*) AS tickets,
                   AVG(CAST(sentiment_score AS REAL)) AS avg_sentiment,
                   SUM(CAST(revenue_at_risk AS REAL)) AS revenue_at_risk
            FROM tickets
            GROUP BY category
            ORDER BY tickets DESC
            """
        ).fetchall()

    return {
        "totals": row_to_dict(totals),
        "top_categories": aggregate_counts("category", 10),
        "top_sub_categories": aggregate_counts("sub_category", 10),
        "language_distribution": aggregate_counts("language", 10),
        "status_distribution": aggregate_counts("resolution_status", 10),
        "sentiment_by_category": [row_to_dict(row) for row in by_category],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
