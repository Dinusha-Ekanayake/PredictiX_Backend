# PredictiX — AI-Powered Fleet & Asset Management Backend

PredictiX is a predictive maintenance platform for fleet and warehouse operations. It combines real-time IoT sensor ingestion, classical machine learning, and Hugging Face NLP models to surface failure risk, maintenance forecasts, and AI-generated summaries through a FastAPI REST API backed by Supabase PostgreSQL.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Database Models](#database-models)
- [API Endpoints](#api-endpoints)
- [ML / AI Components](#ml--ai-components)
- [Authentication](#authentication)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Getting Started](#getting-started)
- [Database Migrations](#database-migrations)
- [Seeding the Database](#seeding-the-database)
- [Development Notes](#development-notes)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | FastAPI + Uvicorn (ASGI) |
| Database | PostgreSQL via Supabase |
| ORM / Migrations | SQLAlchemy + Alembic |
| Auth | JWT (python-jose) + bcrypt |
| Classical ML | scikit-learn, CatBoost |
| NLP / GenAI | Hugging Face Transformers + PyTorch |
| Explainability | SHAP |
| Data | pandas, numpy |
| Config | pydantic-settings |

---

## Architecture Overview

```
Client (Frontend / IoT Devices)
         │
         ▼
  FastAPI Application (app/main.py)
         │
  ┌──────┴──────────────────────────────────┐
  │  Routers (26 API routers)               │
  │  Schemas (Pydantic validation)          │
  │  Services (business logic)              │
  │  Repositories (data access)             │
  └──────┬──────────────────────────────────┘
         │
  ┌──────┴──────────────┐    ┌─────────────────────────┐
  │  SQLAlchemy ORM     │    │  AI/ML Services          │
  │  (models.py)        │    │  • PDM Classifier        │
  └──────┬──────────────┘    │  • PDM Regressor         │
         │                   │  • HuggingFace NLP       │
         ▼                   │  • SHAP Explanations     │
  Supabase PostgreSQL        └─────────────────────────┘
```

---

## Project Structure

```
PredictiX_backend/
├── app/
│   ├── main.py                  # App entry point, lifespan, CORS, router registration
│   ├── models.py                # SQLAlchemy ORM models (20+ tables)
│   ├── deps.py                  # FastAPI dependencies (JWT auth, DB session)
│   ├── core/
│   │   ├── config.py            # Pydantic-settings configuration
│   │   └── security.py          # Password hashing, JWT utilities
│   ├── db/
│   │   ├── base.py              # SQLAlchemy declarative base
│   │   └── session.py           # Engine and SessionLocal initialization
│   ├── routers/                 # 26 API routers (one per domain)
│   ├── schemas/                 # Pydantic request/response schemas
│   ├── services/                # Business logic layer
│   ├── repositories/            # Data access layer (repository pattern)
│   ├── ai/
│   │   ├── models/              # Serialized ML model files (.pkl, safetensors)
│   │   │   ├── pdm_classifier_model/
│   │   │   ├── pdm_regressor_model/
│   │   │   ├── cost_estimation_model/
│   │   │   └── Sequence-to-Sequence (Seq2Seq) Models/
│   │   └── services/            # AI service implementations
│   └── kb/                      # Knowledge base / vector store utilities (WIP)
├── seed_data/                   # SQL fixtures and seeding scripts
├── alembic/                     # Alembic migration scripts
├── alembic.ini                  # Alembic configuration
├── requirements.txt             # Python dependencies
└── .env                         # Environment variables (not committed)
```

---

## Database Models

### Users & Organisation

| Model | Key Fields |
|---|---|
| `Profile` | user_id (Supabase auth), email, role, warehouse_id, department_id |
| `Warehouse` | name, location, total_assets, operational_assets |
| `Department` | name, warehouse_id |

### Assets

| Model | Key Fields |
|---|---|
| `Asset` | vin, make, model, year, type, status, health_band, criticality_score, mileage, assigned_to |
| `AssetAssignment` | asset_id, user_id, start_date, end_date |
| `AssetStatusHistory` | asset_id, previous_status, new_status, changed_by, timestamp |
| `AssetDocument` | asset_id, file_url, document_type |

### Operations

| Model | Key Fields |
|---|---|
| `MaintenanceEvent` | asset_id, event_type, status, cost, downtime_hours, vendor, scheduled_date |
| `SensorReading` | asset_id, timestamp, temperature, rpm, fuel_level, tire_pressure, battery_voltage, vibration, + JSONB payload |
| `Ticket` | asset_id, title, description, status, priority, category, ai_category, ai_summary |
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
| POST | `/auth/login` | Login with email + password, returns JWT |
| GET | `/auth/test` | Auth health check |

### Profiles & Users

| Method | Path | Description |
|---|---|---|
| GET | `/profiles` | List all profiles |
| POST | `/profiles` | Create profile |
| GET | `/profiles/{id}` | Get profile by ID |
| PUT | `/profiles/{id}` | Update profile |
| GET | `/profiles/me` | Current user's profile |
| PUT | `/profiles/me` | Update own profile |
| GET | `/profiles/me/assets` | Current user's assigned assets |
| GET | `/profiles/me/stats` | Asset count stats for current user |
| GET/POST | `/users` | User management |

### Organisation

| Method | Path | Description |
|---|---|---|
| GET/POST | `/warehouses` | Warehouse CRUD |
| GET/POST | `/departments` | Department CRUD |

### Assets

| Method | Path | Description |
|---|---|---|
| GET | `/assets` | List with filters: search, warehouse, status, health_band, criticality, mileage range, payload |
| POST | `/assets` | Create asset |
| GET | `/assets/count` | Filtered asset count |
| GET | `/assets/{id}` | Retrieve asset |
| PUT | `/assets/{id}` | Update asset |
| DELETE | `/assets/{id}` | Delete asset |
| GET/POST | `/asset-assignments` | Assignment records |
| GET | `/asset-status-history` | Status audit log |
| GET/POST | `/asset-documents` | Document management |
| GET/POST | `/asset-summaries` | AI-generated asset summaries |

### Maintenance & Sensors

| Method | Path | Description |
|---|---|---|
| GET/POST | `/maintenance` | Maintenance event CRUD |
| GET | `/sensor-readings` | Query sensor data |
| POST | `/sensor-readings` | Ingest IoT sensor reading |

### Tickets

| Method | Path | Description |
|---|---|---|
| GET/POST | `/tickets` | Ticket CRUD with status/asset filters |
| POST | `/tickets/categorize` | AI-powered ticket categorization |
| GET/POST | `/ticket-comments` | Discussion threads |
| GET/POST | `/ticket-attachments` | Ticket file uploads |
| GET | `/ticket-status-history` | Ticket audit trail |

### Predictions

| Method | Path | Description |
|---|---|---|
| POST | `/predictions/classification` | Binary failure probability (next 30 days) |
| POST | `/predictions/regression` | Days until next maintenance |
| POST | `/predictions/health-score` | Health band calculation (Good / Fair / Poor) |
| POST | `/predictions/full` | Combined classification + regression + health |
| GET | `/predictions/health` | Model service health check |
| GET | `/predictions/debug/features` | Expected feature schema |
| GET | `/predictions/runs` | Prediction run history |
| GET | `/predictions/failure/{asset_id}` | Latest failure prediction for asset |
| GET | `/predictions/cost/{asset_id}` | Cost estimate for asset |
| GET | `/predictions/ticket/{ticket_id}` | Predictions for ticket |
| POST | `/vehicle-predictions/{asset_id}` | Run full prediction and persist to DB |

### Explanations & Model Registry

| Method | Path | Description |
|---|---|---|
| GET | `/prediction-explanations` | SHAP explanations list |
| GET | `/prediction-explanations/{run_id}` | Explanation for a specific run |
| GET/POST | `/model-registry` | ML model metadata |

### Notifications

| Method | Path | Description |
|---|---|---|
| GET | `/notifications` | User notification feed (filter by status) |
| GET | `/notifications/unread` | Unread notifications only |
| PUT | `/notifications/{id}/mark-read` | Mark notification as read |
| GET/POST | `/notification-preferences` | Preference management |

### Reports & Dashboard

| Method | Path | Description |
|---|---|---|
| GET/POST | `/reports` | Report CRUD |
| GET/POST | `/report-sources` | Report data lineage |
| GET | `/warehouse-dashboard/summary` | Aggregated KPIs (health, tickets, costs, status breakdown) |

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/` | Root health check |
| GET | `/debug` | Development DB inspection helpers |

---

## ML / AI Components

### Local Models (loaded at startup)

#### 1. PDM Classifier — Failure Probability
- **File:** `app/ai/models/pdm_classifier_model/predictive_maintenance_model.pkl`
- **Type:** Binary classification (scikit-learn pipeline)
- **Input:** 30+ sensor and asset features (engine hours, tire health, battery voltage, odometer, etc.)
- **Output:** `maintenance_probability` (0–1), `risk_level` (Low / Medium / High / Critical), `recommended_action`

#### 2. PDM Regressor — Days Until Maintenance
- **File:** `app/ai/models/pdm_regressor_model/days_until_next_maintenance_regressor.pkl`
- **Type:** CatBoost regressor (supports SHAP)
- **Input:** Same feature set as classifier
- **Output:** `predicted_days_until_maintenance`, ranked feature importance (SHAP values)

#### 3. Health Score
- **Type:** Derived metric (rule-based mapping over sensor readings)
- **Output:** 0–100 score mapped to health band: `Good` / `Fair` / `Poor`

### Remote HuggingFace Models (optional, disabled by default)

Set `DISABLE_HF_MODELS=false` in `.env` to enable. Models are loaded lazily on first request and cached.

| Model | Repo | Task |
|---|---|---|
| Ticket Categorization | `HF_TICKET_CATEGORIZATION_REPO` | Sequence classification — predict ticket category |
| Ticket Summarization | `HF_TICKET_SUMMARIZATION_REPO` | Seq2Seq — generate ticket summary |
| Ticket Prioritization | `HF_TICKET_PRIORITIZATION_REPO` | Sequence classification — predict priority |
| Asset Summarization | `HF_ASSET_SUMMARIZATION_REPO` | Seq2Seq — natural language asset description |

Models automatically use GPU if CUDA is available, otherwise CPU.

### SHAP Explainability
CatBoost regressor predictions include per-feature SHAP values stored in `PredictionExplanation` and `PredictionFeatureImportance` tables for frontend rendering.

---

## Authentication

**Method:** JWT (HS256, 24-hour expiry)

**Login flow:**
1. `POST /auth/login` with `{ email, password, role }`
2. Server validates credentials and returns `{ access_token, token_type }`
3. Include token in all requests: `Authorization: Bearer <token>`
4. Token payload: `sub` (user_id), `email`, `role`, `exp`

**User resolution:** On each request, `get_current_user()` decodes the JWT and loads the `Profile` from the database. Falls back to a mock profile in development if not found.

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
DATABASE_PASSWORD=<your-db-password>
DATABASE_URL=postgresql+psycopg2://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres
DATABASE_KEY=sb_secret_...

# HuggingFace (required if DISABLE_HF_MODELS=false)
HF_TOKEN=hf_...
HF_TICKET_CATEGORIZATION_REPO=Dinusha-Ekanayake/predictix-ticket_categorization_model
HF_TICKET_SUMMARIZATION_REPO=Dinusha-Ekanayake/predictix-ticket_summarization_model
HF_TICKET_PRIORITIZATION_REPO=Dinusha-Ekanayake/predictix-ticket_prioritization_model
HF_ASSET_SUMMARIZATION_REPO=Dinusha-Ekanayake/predictix-asset_summarization_model

# Feature Flags
DISABLE_HF_MODELS=true    # set to false to enable HuggingFace models
DEFAULT_PASSWORD=Predictix@123
```

**CORS** is pre-configured for `localhost:3000`, `localhost:3001`, and `localhost:5173`.

---

## Getting Started

### Prerequisites

- Python 3.10+
- A Supabase project (PostgreSQL)
- (Optional) CUDA-capable GPU for faster HuggingFace inference

### Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd PredictiX_backend

# 2. Create and activate a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your Supabase and JWT credentials

# 5. Run database migrations
alembic upgrade head

# 6. Start the development server
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs` (Swagger UI)  
Alternative docs: `http://localhost:8000/redoc`

---

## Database Migrations

Alembic is used for schema migrations:

```bash
# Generate a new migration from model changes
alembic revision --autogenerate -m "description of change"

# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# View migration history
alembic history
```

---

## Seeding the Database

The `seed_data/` directory contains scripts and SQL fixtures for initial data:

```bash
# Step 1: Create Supabase Auth users from the employee roster CSV
python seed_data/create_supabase_users_from_roster.py

# Step 2: Seed warehouses, departments, assets, and sample records
python seed_data/seed.py
```

Fixtures are based on a fictional company **LankaLogix** (Colombo warehouse) with realistic vehicle data including full sensor readings, maintenance history, and tickets.

---

## Development Notes

### Test Users (Hardcoded for Development)

| Email | Password | Role |
|---|---|---|
| `nuwan.gunasekara.tra1@lankalogix.lk` | `user` | user |
| `anjali.warnakulasuriya.adm1@lankalogix.lk` | `admin` | admin |

### Disabling HuggingFace Models

Set `DISABLE_HF_MODELS=true` in `.env` to skip downloading and loading HuggingFace models. All other prediction endpoints remain fully functional. This is the recommended setting for development machines without a GPU or fast internet.

### Knowledge Base (WIP)

`app/kb/` contains early-stage vector store and document embedding utilities (`kb_vector_store.py`, `kb_documents.py`, `kb_annotator.py`). These are not yet exposed through API endpoints.

### Key Architectural Patterns

- **Repository pattern** — `vehicle_repository.py` abstracts DB queries from router logic
- **Service layer** — `prediction_service`, `ticket_categorization_service`, `asset_summary_service` encapsulate AI/ML orchestration
- **Dependency injection** — FastAPI `Depends()` wires DB sessions and the authenticated user into every handler
- **Lifespan context manager** — ML models are loaded once at startup and held in application state
- **Pydantic schemas** — All request/response bodies are validated; ORM models use `from_attributes=True`
