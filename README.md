# Customer Support Insight Platform Documentation

This project implements a local AI-powered customer support platform for the assignment dataset. It includes a FastAPI backend, a React dashboard, SQLite storage, Chroma vector search, and three LangGraph agents.

## What Was Built

- A FastAPI backend in `main.py`.
- A local SQLite database named `support.db`.
- Local Chroma vector persistence in `chroma_store/`.
- Agent 1 in `agent1_graph.py`.
- Agent 2 in `agent2_graph.py`.
- Agent 3 in `agent3_graph.py`.
- Graph PNG exports:
  - `agent1_graph.png`
  - `agent2_graph.png`
  - `agent3_graph.png`
- OpenAPI/Swagger documentation with detailed schemas and examples.
- A React dashboard in `frontend/` (Vite + TypeScript + Tailwind).

## CI/CD (GitHub Actions)

| Workflow | When | What it does |
|----------|------|----------------|
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Every push/PR to `main` | Builds Docker image, compiles frontend, Python syntax check |
| [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) | After CI passes on `main` | POSTs to Render deploy hook |

**Render deploy hook (one-time):**

1. Render dashboard → your **Web Service** → **Settings** → **Deploy Hook** → copy URL  
2. GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**  
3. Name: `RENDER_DEPLOY_HOOK_URL`, value: paste the hook URL  

Push to `main` → CI runs → CD triggers a new Render deploy.

## Quick start (backend + frontend)

### Backend

```bash
pip install -r requirements.txt
# Set OPENAI_API_KEY in .env for full AI/RAG/agent runs
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The UI calls the API at `http://127.0.0.1:8000` by default (`VITE_API_BASE_URL`).

### First-run demo flow

1. Go to **Setup** and run **POST /seed** (optionally cap vectors with the slider).
2. Open **Dashboard** for KPIs, charts, and sentiment trends.
3. Use **New ticket** with demo presets (escalation / RAG / auto-resolve).
4. Run **Agent 2** on **Incidents**, then submit a Samsung S24 ticket to see cross-agent escalation.
5. Run **Agent 3** on **Retention** for the churn queue.

## Frontend routes

| Route | Purpose |
|-------|---------|
| `/` | Executive dashboard — top issues, sentiment trends, revenue at risk |
| `/tickets` | Ticket queue with search and filters |
| `/tickets/new` | Draft → review → submit wizard with RAG examples |
| `/tickets/:id` | Ticket detail, agent trace, customer history, SKU incident banner |
| `/incidents` | Agent 2 incidents and flagged SKUs |
| `/retention` | Agent 3 retention queue |
| `/agents` | Agent overview and LangGraph diagrams |
| `/setup` | Seed database and Chroma vectors |

## Data Flow

The backend follows this flow:

```text
dataset.csv -> SQLite seed -> Chroma vector seed -> ticket draft -> ticket submit -> Agent 1 decision
```

For anomaly detection:

```text
SQLite tickets -> Agent 2 volume scan -> z-score spike detection -> incident report -> incident table -> Agent 1 incident check
```

For customer risk:

```text
SQLite tickets -> Agent 3 customer scan -> churn score -> lifetime value -> drafted retention offer -> retention queue
```

Agent 1 and Agent 2 coordinate through the database. Agent 2 writes incidents and SKU flags. Agent 1 reads those incidents when deciding whether a new ticket should be escalated. Agent 3 writes a separate retention queue for high-risk customers.

## Database

The main table is `tickets`. It stores all 28 fields from `dataset.csv`, plus Agent 1 output fields:

- `agent_decision`
- `agent_reason`
- `agent_steps`
- `updated_at`

Agent 2 adds:

- `incidents`
- `sku_incident_flags`

Agent 3 adds:

- `retention_queue`

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

### `POST /agent3/run`

Runs Agent 3 customer risk analysis.

Agent 3 follows the implementation-plan churn/retention workflow.

Query parameters:

- `end_date`
  - End date for the customer-risk scan.
  - Default: `2025-01-31`
- `lookback_days`
  - Number of days before `end_date` to scan.
  - Default: `90`
- `min_ticket_count`
  - Minimum number of tickets required for a customer to be considered high-contact.
  - Default: `2`
- `churn_threshold`
  - Minimum churn score required for retention queue inclusion.
  - Default: `3.0`
- `max_customers`
  - Maximum customers to write to the queue in one run.
  - Default: `20`

Agent 3 does:

```text
get high-contact customers
load each customer profile
compute churn score
estimate recent lifetime value
rank by churn_score * log(lifetime_value + 1)
draft retention offer
write retention queue row
```

The churn score uses the assignment formula:

```text
churn_score =
  ticket_count * 0.30
  + unresolved_count * 0.40
  + is_repeat * 0.20
  + tier_weight * 0.10
```

Tier weights:

- `regular = 1.0`
- `prime = 1.5`
- `prime_plus = 2.0`

In this implementation, `unresolved_count` means open-risk tickets:

```text
unresolved
escalated
pending
```

This makes the queue reflect unresolved customer pain, not only one exact status string.

### `GET /agent3/retention-queue`

Lists retention queue rows created by Agent 3.

Query parameters:

- `active_only`
  - `true`: return only active queue rows.
  - `false`: return all queue rows.
- `limit`
  - Maximum number of queue rows to return.

Returns:

- queue ID
- customer ID
- customer name
- customer tier
- country
- language
- ticket count
- unresolved/open-risk ticket count
- repeat-contact flag
- top issue
- churn score
- lifetime value
- retention priority
- drafted retention offer
- scan window

### `GET /insights`

Returns dashboard-style aggregate metrics.

### `GET /insights/trends`

Returns weekly or daily sentiment and volume trends for charts.

### `GET /customers/{customer_id}/tickets`

Returns recent tickets for one customer (history panel).

### `GET /tickets/search`

Search by ticket ID, customer name, message, or SKU.

### `GET /tickets/filters`

Distinct values for category, status, tier, frustration, and channel filters.

### `GET /agent2/sku-flags`

Lists SKUs flagged by Agent 2 (read by Agent 1 on new tickets).

### `GET /system/setup`

Returns seed/vector/OpenAI status for the setup page.

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

## Agent 3

Agent 3 is the customer risk agent.

Its goal is to identify customers most likely to churn and prepare a retention queue.

Agent 3 uses:

- high-contact customer detection
- full customer ticket history
- churn score formula
- recent lifetime value estimation
- retention priority ranking
- OpenAI/fallback offer drafting

Agent 3 writes:

- retention queue rows
- personalized retention offers
- churn score and lifetime value
- customer risk context

The queue is sorted by:

```text
retention_priority = churn_score * log(lifetime_value + 1)
```

This keeps high-value customers important without letting one very large order dominate the entire queue.

## Graph Images

Agent 1 graph:

```text
agent1_graph.png
```

Agent 2 graph:

```text
agent2_graph.png
```

Agent 3 graph:

```text
agent3_graph.png
```

These diagrams visualize the LangGraph node flow for each agent.
