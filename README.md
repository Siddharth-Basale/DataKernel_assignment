# Customer Support Insight Platform Documentation

This project implements a local AI-powered customer support backend for the assignment dataset. The work completed here covers the FastAPI backend, SQLite storage, Chroma vector search, LangGraph Agent 1, and LangGraph Agent 2.

## What Was Built

- A FastAPI backend in `main.py`.
- A local SQLite database named `support.db`.
- Local Chroma vector persistence in `chroma_store/`.
- Agent 1 in `agent1_graph.py`.
- Agent 2 in `agent2_graph.py`.
- Graph PNG exports:
  - `agent1_graph.png`
  - `agent2_graph.png`
- OpenAPI/Swagger documentation with detailed schemas and examples.

## Data Flow

The backend follows this flow:

```text
dataset.csv -> SQLite seed -> Chroma vector seed -> ticket draft -> ticket submit -> Agent 1 decision
```

For anomaly detection:

```text
SQLite tickets -> Agent 2 volume scan -> z-score spike detection -> incident report -> incident table -> Agent 1 incident check
```

Agent 1 and Agent 2 coordinate through the database. Agent 2 writes incidents and SKU flags. Agent 1 reads those incidents when deciding whether a new ticket should be escalated.

## Database

The main table is `tickets`. It stores all 28 fields from `dataset.csv`, plus Agent 1 output fields:

- `agent_decision`
- `agent_reason`
- `agent_steps`
- `updated_at`

Agent 2 adds:

- `incidents`
- `sku_incident_flags`

## API Endpoints

### `GET /health`

Checks whether the backend and SQLite database are available.

Returns:

- service status
- SQLite database path
- number of stored tickets

Example response:

```json
{
  "status": "ok",
  "database": "support.db",
  "tickets": 10000
}
```

### `POST /seed`

Loads `dataset.csv` into SQLite and optionally builds the local Chroma vector store.

Query parameters:

- `refresh_vectors`
  - `true`: rebuild Chroma vectors from resolved tickets with existing agent replies.
  - `false`: only load CSV rows into SQLite.
- `max_vectors`
  - Optional cap for vector creation.
  - Useful for demos when you do not want to embed all resolved tickets.

Returns:

- number of rows loaded
- database path
- vector refresh status
- number of vectors added

### `GET /tickets`

Lists tickets from SQLite.

Query parameters:

- `limit`
- `offset`
- `category`
- `status`

Useful for browsing ticket data, filtering by issue type, or checking unresolved/escalated tickets.

### `GET /tickets/{ticket_id}`

Fetches one ticket by ID.

Returns the full stored ticket row, including:

- original CSV fields
- generated draft fields
- Agent 1 decision fields
- suggested reply if available

### `POST /tickets/draft`

Creates an enriched draft from minimal ticket input.

This endpoint is designed for the realistic flow where the user provides only the raw complaint context, and the backend generates the rest.

Important input fields:

- `message`
- `customer_tier`
- `product_sku`
- `order_value`
- `customer_name`
- `customer_id`
- `channel`
- `customer_country`
- `language`
- `product_category`
- `order_id`
- `order_date`

The backend generates:

- `resolution_status`
- `is_repeat_contact`
- `category`
- `sub_category`
- `sentiment_score`
- `frustration_level`
- `urgency_score`
- `revenue_at_risk`
- `summary`
- `key_entities`
- `suggested_fields_reason`
- `rag_examples`

The response includes two important objects:

- `draft`
  - Full detailed draft with RAG examples and explanation.
- `submit_payload`
  - Clean payload that can be copied directly into `/tickets/submit`.

### `POST /tickets/submit`

Submits a reviewed draft ticket.

Recommended usage:

1. Call `/tickets/draft`.
2. Review the generated fields.
3. Copy `submit_payload`.
4. Paste it into `/tickets/submit`.

This endpoint:

- stores the ticket in SQLite
- forces new submitted tickets to `pending`
- runs Agent 1 immediately
- returns the stored ticket and final Agent 1 state

### `POST /tickets/ingest`

Legacy direct ingest endpoint.

It accepts a full ticket payload, stores the ticket, and runs Agent 1 in one step.

This is still available for quick demos, but the preferred flow is:

```text
/tickets/draft -> /tickets/submit
```

### `POST /agent1/run/{ticket_id}`

Runs Agent 1 on an existing ticket.

This does not create a new ticket or append a follow-up message. It reloads the existing ticket from SQLite and reprocesses it.

Agent 1 can return one of three decisions:

- `suggest_reply`
  - Normal RAG-based response suggestion.
- `auto_resolve`
  - Used for simple known cases like `account_access/cant_login`.
- `escalate`
  - Used for risky tickets, active incidents, high-value orders, or critical-priority cases.

Agent 1 workflow:

```text
load ticket
get customer history
get order details
check active incidents
calculate priority
route to escalation or RAG reply generation
save final decision
```

### `POST /agent2/run`

Runs Agent 2 anomaly investigation.

Agent 2 follows the implementation-plan spike workflow.

Query parameters:

- `threshold`
  - Z-score threshold for anomaly selection.
  - Default: `2.0`
- `max_incidents`
  - Maximum incidents to create.
  - Default: `3`
- `start_date`
  - Historical scan start date.
  - Default: `2024-07-01`
- `end_date`
  - Historical scan end date.
  - Default: `2025-01-31`

Agent 2 does:

```text
scan category volumes
compute rolling 7-day z-scores
select anomaly windows
identify top SKUs
pull sample ticket summaries
synthesize incident report
write incident to SQLite
flag affected SKUs
```

The current implementation detects the three planned incidents:

- Samsung S24 delivery anomaly
- Sale season fake product anomaly
- Post-holiday refund backlog anomaly

### `GET /agent2/incidents`

Lists incidents created by Agent 2.

Query parameters:

- `active_only`
  - `true`: return only active incidents.
  - `false`: return all incidents.
- `limit`
  - Maximum number of incidents to return.

Returns:

- incident ID
- title
- severity
- category
- affected SKU
- date window
- z-score
- ticket count
- top SKUs
- pattern
- root cause
- recommended action
- sample ticket IDs
- full report

### `GET /insights`

Returns dashboard-style aggregate metrics.

Includes:

- total ticket count
- unresolved count
- revenue at risk
- average sentiment
- average urgency
- top categories
- top sub-categories
- language distribution
- status distribution
- sentiment by category

## Agent 1

Agent 1 is the ticket resolution agent.

Its goal is to decide:

```text
suggest reply
auto-resolve
escalate
```

Agent 1 uses:

- SQLite ticket data
- customer history
- order details
- active incidents from Agent 2
- Chroma vector search
- OpenAI chat generation
- formula-based priority scoring

Agent 1 writes back:

- `suggested_reply`
- `agent_decision`
- `agent_reason`
- `agent_steps`
- updated `resolution_status` when auto-resolved or escalated

## Agent 2

Agent 2 is the anomaly investigation agent.

Its goal is to detect business-level complaint spikes before humans manually inspect the data.

Agent 2 uses:

- daily category counts
- rolling 7-day mean
- rolling 7-day standard deviation
- z-score anomaly detection
- top SKU analysis
- sample ticket summaries
- OpenAI/fallback report synthesis

Agent 2 writes:

- incident records
- active SKU flags

Agent 1 then reads these incidents during escalation checks.

## Graph Images

Agent 1 graph:

```text
agent1_graph.png
```

Agent 2 graph:

```text
agent2_graph.png
```

These diagrams visualize the LangGraph node flow for each agent.
