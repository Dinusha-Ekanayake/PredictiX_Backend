# PredictiX — AI-Powered Fleet & Asset Management Backend

PredictiX is a predictive maintenance platform for fleet and warehouse operations. It combines real-time IoT sensor ingestion, classical machine learning (CatBoost, scikit-learn), Weibull AFT survival analysis, SHAP explainability, and Groq LLM agents to surface failure risk, maintenance forecasts, AI-generated reports, and real-time notifications through a FastAPI REST API backed by Supabase PostgreSQL.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Database Models](#database-models)
- [API Endpoints](#api-endpoints)
- [ML / AI Components](#ml--ai-components)
- [Dashboard Caching](#dashboard-caching)
- [Authentication](#authentication)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Getting Started](#getting-started)
- [Database Migrations](#database-migrations)
- [Seeding the Database](#seeding-the-database)
- [Deployment](#deployment)
- [Background Jobs](#background-jobs)
- [Development Notes](#development-notes)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | FastAPI + Uvicorn (ASGI) |
| Database | PostgreSQL via Supabase |
| ORM / Migrations | SQLAlchemy + Alembic |
| Authentication | JWT (python-jose) + bcrypt |
| ML — Classification | scikit-learn pipeline (failure probability) |
| ML — Regression | CatBoost (days until maintenance) |
| ML — Survival | Lifelines / Weibull AFT (component RUL) |
| Explainability | SHAP |
| NLP / GenAI | Groq Llama-3.3-70B, LangChain, HuggingFace Transformers + PyTorch |
| PDF Generation | ReportLab |
| Task Scheduling | APScheduler (hourly PDM batch) |
| Data Processing | pandas, numpy |
| Config | pydantic-settings |
| Python Version | 3.12 |

---

## Architecture Overview

```
Client (Frontend / IoT Devices)
         │
         ▼
  FastAPI Application (app/main.py)
         │
  ┌──────┴──────────────────────────────────────────┐
  │  36 Routers (one per domain)                    │
  │  17 Pydantic Schema modules (validation)        │
  │  11 Service modules (business logic)            │
  │  Repository layer (data access)                 │
  └──────┬──────────────────────────────────────────┘
         │
  ┌──────┴──────────────┐    ┌──────────────────────────────┐
  │  SQLAlchemy ORM     │    │  AI / ML Services            │
  │  (models.py)        │    │  • PDM Classifier            │
  └──────┬──────────────┘    │  • PDM Regressor (CatBoost)  │
         │                   │  • Survival Analysis          │
         ▼                   │  • SHAP Explainability        │
  Supabase PostgreSQL        │  • Groq LLM Agent (RAG)      │
  (ap-southeast-2)           │  • HuggingFace NLP (optional) │
                             └──────────────────────────────┘
         │
  ┌──────┴──────────────────────┐
  │  Dashboard Cache            │
  │  (TTL-based in-memory)      │
  │  AI Summary Cache           │
  │  (background refresh)       │
  └─────────────────────────────┘
```

---

## Project Structure

```
PredictiX_backend/
├── app/
│   ├── main.py                      # FastAPI entry point, lifespan, CORS, router registration
│   ├── models.py                    # SQLAlchemy ORM — 20+ database tables
│   ├── deps.py                      # JWT auth + DB session dependency injection
│   ├── core/
│   │   ├── config.py                # Pydantic Settings
│   │   ├── security.py              # Password hashing & JWT utilities
│   │   └── storage.py               # File storage helpers
│   ├── db/
│   │   ├── base.py                  # SQLAlchemy declarative base
│   │   ├── session.py               # Engine and SessionLocal initialization
│   │   └── supabase_client.py       # Supabase Python client setup
│   ├── routers/                     # 36 API router modules (one per domain)
│   ├── schemas/                     # Pydantic request/response models (17 files)
│   ├── services/
│   │   ├── dashboard_cache.py       # TTL-based full-response payload cache
│   │   ├── ai_summary_cache.py      # Non-blocking background AI summary refresh
│   │   ├── report_service.py        # Report generation orchestration
│   │   ├── pdf_render.py            # ReportLab PDF builder
│   │   ├── pdf_styles.py            # PDF styling templates
│   │   ├── notification_service.py  # Multi-channel notifications
│   │   ├── in_app_notification_service.py
│   │   └── user_ticket_service.py
│   ├── agents/
│   │   └── report_agents.py         # Groq RAG agent for warehouse reports
│   ├── ai/
│   │   ├── models/                  # Serialized ML model files (.pkl, .safetensors)
│   │   │   ├── pdm_classifier_model/
│   │   │   ├── pdm_regressor_model/
│   │   │   ├── cost_estimation_model/
│   │   │   └── survival_analysis/
│   │   ├── services/                # AI orchestration (12 modules)
│   │   └── agent/                   # Tool-calling Groq agent loop + tools
│   ├── kb/                          # Knowledge base & vector store (WIP)
│   └── tests/                       # Unit tests
├── seed_data/                       # SQL fixtures and demo data scripts
├── alembic/                         # Database migration scripts
├── docs/                            # Developer notes and lessons
├── requirements.txt
├── Procfile                         # Heroku / Railway deployment config
├── railway.toml
├── render.yaml
├── nixpacks.toml
└── alembic.ini
```

---

## Database Models

### Organisation & Users

| Model | Key Fields |
|---|---|
| `Profile` | user_id (Supabase auth), email, role, warehouse_id, department_id |
| `Warehouse` | name, city, timezone, climate_zone, total_assets |
| `Department` | name, warehouse_id |

### Assets & Operations

| Model | Key Fields |
|---|---|
| `Asset` | vin, make, model, year, type, status, health_band, criticality_score, mileage |
| `AssetAssignment` | asset_id, user_id, start_date, end_date |
| `AssetStatusHistory` | asset_id, previous_status, new_status, changed_by, timestamp |
| `AssetDocument` | asset_id, file_url, document_type |
| `MaintenanceEvent` | asset_id, event_type, status, cost, downtime_hours, vendor, scheduled_date |
| `SensorReading` | asset_id, timestamp, temperature, rpm, fuel_level, tire_pressure, battery_voltage, vibration, custom JSONB |

### Tickets

| Model | Key Fields |
|---|---|
| `Ticket` | asset_id, title, description, status, priority, category, ai_category, ai_summary, closed_at |
| `TicketComment` | ticket_id, author_id, body, is_internal |
| `TicketAttachment` | ticket_id, file_url |
| `TicketStatusHistory` | ticket_id, previous_status, new_status, changed_by |

### Predictions & ML

| Model | Key Fields |
|---|---|
| `PredictionRun` | asset_id, model_name, model_version, input_snapshot, timestamp |
| `AssetFailurePrediction` | asset_id, run_id, health_score, failure_probability, days_until_maintenance, risk_level |
| `AssetCostPrediction` | asset_id, run_id, estimated_cost, min_cost, max_cost |
| `TicketPrediction` | ticket_id, run_id, predicted_category, predicted_priority, ai_summary |
| `PredictionExplanation` | run_id, feature_importances (JSON) |
| `PredictionFeatureImportance` | run_id, feature_name, importance_score, rank |
| `ModelRegistry` | model_name, version, framework, metrics, is_active |

### Notifications & Reporting

| Model | Key Fields |
|---|---|
| `Notification` | user_id, type, channel, message, is_read, asset_id, ticket_id |
| `UserNotificationPreference` | user_id, notification_type, channel, enabled |
| `Report` | title, type, generated_by, output (JSON) |
| `ReportSource` | report_id, source_type, source_id, relevance_score |

---

## API Endpoints

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | Login with email + password + role, returns JWT |
| GET | `/auth/test` | Auth health check |

### Profiles & Users

| Method | Path | Description |
|---|---|---|
| GET/POST | `/profiles` | Profile list and creation |
| GET/PUT | `/profiles/{id}` | Get or update profile |
| GET/PUT | `/profiles/me` | Current user's profile |
| GET | `/profiles/me/assets` | Assigned assets |
| GET | `/profiles/me/stats` | Asset count stats |
| GET/POST | `/users` | User management CRUD |

### Organisation

| Method | Path | Description |
|---|---|---|
| GET/POST/PUT/DELETE | `/warehouses` | Warehouse CRUD |
| GET/POST/PUT/DELETE | `/departments` | Department CRUD |

### Assets

| Method | Path | Description |
|---|---|---|
| GET | `/assets` | List with filters (search, warehouse, status, health_band, criticality) |
| POST | `/assets` | Create asset |
| GET/PUT/DELETE | `/assets/{id}` | Retrieve, update, delete asset |
| GET/POST | `/asset-assignments` | Assignment records |
| GET | `/asset-status-history` | Status audit log |
| GET/POST | `/asset-documents` | Document management |
| GET/POST | `/asset-summaries/generate` | AI-generated asset descriptions |
| POST | `/asset-reports/{asset_id}` | Generate full PDF report to Supabase Storage |
| GET | `/asset-reports/dummy/pdf` | Dummy PDF for styling test |

### Maintenance & Sensors

| Method | Path | Description |
|---|---|---|
| GET/POST/PUT/DELETE | `/maintenance` | Maintenance event CRUD |
| GET | `/sensor-readings` | Query historical sensor data |
| POST | `/sensor-readings` | Ingest IoT sensor reading |

### Tickets

| Method | Path | Description |
|---|---|---|
| GET/POST/PUT/DELETE | `/tickets` | Ticket CRUD with filters |
| POST | `/tickets/categorize` | AI-powered ticket categorisation |
| GET/POST | `/ticket-comments` | Discussion threads |
| GET/POST | `/ticket-attachments` | File uploads |
| GET | `/ticket-status-history` | Audit trail |
| GET/POST/PUT/DELETE | `/user/tickets` | User-facing ticket interface |

### Predictions

| Method | Path | Description |
|---|---|---|
| POST | `/predictions/classification` | Failure probability (0–1) |
| POST | `/predictions/regression` | Days until maintenance |
| POST | `/predictions/full` | Combined prediction + SHAP |
| GET | `/predictions/runs` | Prediction run history |
| GET | `/predictions/failure/{asset_id}` | Latest failure prediction |
| GET | `/predictions/cost/{asset_id}` | Cost estimate |
| POST | `/vehicle-predictions/{asset_id}` | Run full prediction and persist to DB |
| GET | `/batch-predictions` | Batch run management |
| GET | `/prediction-explanations/{run_id}` | SHAP values for a run |
| GET/POST | `/model-registry` | ML model versioning |

### Survival Analysis

| Method | Path | Description |
|---|---|---|
| GET | `/survival/summary` | Weibull AFT survival curves for warehouse fleet |
| GET | `/survival/watchlist` | Assets with RUL < 30 days |

### Dashboards

| Method | Path | Description |
|---|---|---|
| GET | `/admin-dashboard/summary` | Full admin KPI payload (cached) |
| GET | `/warehouse-dashboard/summary` | Warehouse KPI payload (cached) |
| GET | `/warehouse-dashboard/generate-report` | RAG-powered AI warehouse report via Groq |
| POST | `/warehouse-dashboard/notify-print` | Log a report print event |
| GET | `/warehouse-dashboard/maintenance-schedule` | Predictive maintenance schedule |

### Notifications & Reports

| Method | Path | Description |
|---|---|---|
| GET | `/notifications` | User notification feed |
| PUT | `/notifications/{id}/mark-read` | Mark as read |
| GET/POST | `/notification-preferences` | Preference management |
| GET/POST | `/reports` | Report metadata CRUD |
| GET/POST | `/faqs` | Knowledge base CRUD |

### Chatbot & WebSocket

| Method | Path | Description |
|---|---|---|
| POST | `/chatbot/ask` | Legacy RAG Q&A (no auth) |
| POST | `/chatbot/agent` | Tool-calling Groq agent (JWT required) |
| WS | `/ws` | Real-time WebSocket connection |

---

## ML / AI Components

### Local Models (loaded at startup)

| Model | File | Task | Output |
|---|---|---|---|
| PDM Classifier | `app/ai/models/pdm_classifier_model/predictive_maintenance_model.pkl` | Failure probability | 0–1 score, risk level, recommended action |
| PDM Regressor | `app/ai/models/pdm_regressor_model/days_until_next_maintenance_regressor.pkl` | Days until maintenance | Numeric estimate + SHAP importances |
| Survival Analysis | `app/ai/models/survival_analysis/` | Component RUL (Weibull AFT) | Survival curves, 30/90-day risk flags |

### Remote HuggingFace Models (optional, disabled by default)

Set `DISABLE_HF_MODELS=false` in `.env` to enable. Models load lazily on first request and are cached in memory. GPU is used automatically when available.

| Purpose | Repo |
|---|---|
| Ticket categorisation | `Dinusha-Ekanayake/predictix-ticket_categorization_model` |
| Ticket summarisation | `Dinusha-Ekanayake/predictix-ticket_summarization_model` |
| Ticket prioritisation | `AroshN/priority_classif_xgb` |
| Asset summarisation | `Dinusha-Ekanayake/predictix-asset_summarization_model` |

### Groq LLM Agent

- **Model:** `llama-3.3-70b-versatile`
- **Warehouse reports:** `GET /warehouse-dashboard/generate-report` — queries 8 live PostgreSQL tables, injects context into Groq, returns structured JSON with 5 AI sections
- **Chatbot agent:** `POST /chatbot/agent` — tool-calling loop with 11+ tools (asset lookup, prediction run, ticket query, etc.)
- **Rate-limit handling:** On Groq 429 errors, the AI summary cache backs off automatically for 90 minutes (matching the free-tier daily TPD reset window)

### SHAP Explainability

CatBoost regressor predictions include per-feature SHAP values stored in `PredictionExplanation` and `PredictionFeatureImportance` tables, served to the frontend for risk driver visualisation.

---

## Dashboard Caching

Both dashboard endpoints use a TTL-based in-memory `DashboardCache` to eliminate repeated network round-trips to Supabase (each query adds ~170–250ms RTT to ap-southeast-2):

- **First request** — builds the full payload synchronously (consolidated SQL queries with `FILTER` aggregates and `width_bucket()`)
- **Within TTL** — returns cached payload instantly (~15ms)
- **After TTL** — returns stale payload immediately, starts a background thread to refresh

The admin dashboard AI summary is managed separately by `ai_summary_cache.py`:

- Refreshes every 10 minutes in a background daemon thread
- Never blocks the request path
- Falls back to a data-driven KPI string when no LLM summary is available

Configure TTL via environment variables:

```env
ADMIN_DASHBOARD_TTL=60         # seconds (default 60)
WAREHOUSE_DASHBOARD_TTL=60
ADMIN_AI_SUMMARY_TTL=600       # seconds (default 600)
```

---

## Authentication

**Method:** JWT HS256, 60-minute expiry

```
POST /auth/login
Body:     { "email": "...", "password": "...", "role": "ADMIN" | "USER" }
Response: { "access_token": "...", "token_type": "bearer" }

Protected routes: Authorization: Bearer <token>
```

**Token payload:** `sub` (user_id), `email`, `role`, `warehouse_id`, `exp`

**Demo accounts (development seed data — LankaLogix):**

| Email | Password | Role |
|---|---|---|
| `anjali.warnakulasuriya.adm1@lankalogix.lk` | `admin` | ADMIN |
| `nuwan.gunasekara.tra1@lankalogix.lk` | `user` | USER |

---

## Configuration & Environment Variables

Create a `.env` file in the project root:

```env
# JWT
JWT_SECRET=your-secret-uuid-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=sb_publishable_...
SUPABASE_SERVICE_ROLE_KEY=<service-role-jwt>
PROJECT_REF=<project-ref>

# Database
DATABASE_URL=postgresql+psycopg2://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
DATABASE_PASSWORD=<your-db-password>
DATABASE_KEY=sb_secret_...

# Groq (AI reports and chatbot agent — required for LLM features)
GROQ_API_KEY=gsk_...

# HuggingFace (required only if DISABLE_HF_MODELS=false)
DISABLE_HF_MODELS=true
HF_TOKEN=hf_...
HF_TICKET_CATEGORIZATION_REPO=Dinusha-Ekanayake/predictix-ticket_categorization_model
HF_TICKET_SUMMARIZATION_REPO=Dinusha-Ekanayake/predictix-ticket_summarization_model
HF_TICKET_PRIORITIZATION_REPO=AroshN/priority_classif_xgb
HF_ASSET_SUMMARIZATION_REPO=Dinusha-Ekanayake/predictix-asset_summarization_model
ENABLE_HF_WARMER=false

# PDM Batch Job
BATCH_RUN_ON_STARTUP=false
BATCH_INTERVAL_HOURS=24

# Dashboard Cache TTLs (seconds)
ADMIN_DASHBOARD_TTL=60
WAREHOUSE_DASHBOARD_TTL=60
ADMIN_AI_SUMMARY_TTL=600

# CORS (comma-separated)
ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.vercel.app

# Misc
DEFAULT_PASSWORD=Predictix@123
```

**CORS** is pre-configured for `localhost:3000`, `localhost:3001`, `localhost:5173`, `127.0.0.1:*`, `192.168.56.1:*`, and the Vercel deployment URL.

---

## Getting Started

### Prerequisites

- Python 3.12
- A Supabase project (PostgreSQL database)
- Groq API key — free tier at [console.groq.com](https://console.groq.com)
- (Optional) CUDA-capable GPU for HuggingFace inference

### Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd PredictiX_backend

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your Supabase credentials, JWT secret, and Groq API key

# 5. Apply database migrations
alembic upgrade head

# 6. Start the development server
uvicorn app.main:app --reload --port 8000
```

The API is available at `http://localhost:8000`.

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a migration from model changes
alembic revision --autogenerate -m "description"

# Roll back one migration
alembic downgrade -1

# View migration history
alembic history
```

---

## Seeding the Database

The `seed_data/` directory contains scripts and SQL fixtures based on the fictional company **LankaLogix** — a multi-warehouse Sri Lankan logistics company with realistic vehicle data, sensor readings, maintenance history, and tickets.

```bash
# Step 1: Create Supabase Auth users from the employee roster
python seed_data/create_supabase_users_from_roster.py

# Step 2: Seed warehouses, departments, assets, and operational records
python seed_data/seed.py
```

---

## Deployment

The backend is pre-configured for one-command deployment on several platforms:

```bash
# Production command (Railway / Render / Heroku)
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Set all required environment variables in your platform's dashboard. The `railway.toml`, `render.yaml`, `Procfile`, and `nixpacks.toml` are committed and ready to use.

---

## Background Jobs

APScheduler runs a PDM batch prediction job at startup (if enabled) and then on an hourly interval:

1. Reads the latest sensor readings for every asset
2. Runs the local PDM classifier and regressor models
3. Writes results to `asset_failure_predictions` and `asset_cost_predictions`
4. Triggers in-app notifications for newly critical assets

```env
BATCH_RUN_ON_STARTUP=true    # Run immediately on server start
BATCH_INTERVAL_HOURS=24       # Repeat every N hours
```

---

## Development Notes

### Disabling HuggingFace Models

Set `DISABLE_HF_MODELS=true` (default) to skip downloading and loading HuggingFace models at startup. All prediction, dashboard, and report endpoints remain fully functional. Only the NLP ticket categorisation and asset summarisation quality is reduced (rule-based fallback used instead).

### Key Architectural Patterns

- **Repository pattern** — `vehicle_repository.py` abstracts DB queries from router logic
- **Service layer** — AI/ML orchestration is encapsulated in `app/ai/services/` and `app/services/`
- **Dependency injection** — FastAPI `Depends()` wires DB sessions and the authenticated user into every handler
- **Lifespan context manager** — ML models are loaded once at startup and held in application state
- **Pydantic validation** — All request/response bodies are fully typed with `from_attributes=True` for ORM compatibility
- **Dashboard caching** — `DashboardCache` and `ai_summary_cache` decouple request latency from Supabase network RTT

### Knowledge Base (WIP)

`app/kb/` contains early-stage vector store and document embedding utilities (`kb_vector_store.py`, `kb_documents.py`, `kb_annotator.py`). These power SHAP-enriched annotations in warehouse reports and are not yet exposed as standalone API endpoints.
