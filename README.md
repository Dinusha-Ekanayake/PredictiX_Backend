# PredictiX Backend

AI-powered asset management API built with FastAPI. Provides predictive maintenance forecasting, ticket categorization and priority scoring, asset lifecycle tracking, and warehouse/department management — backed by Supabase and ML models (scikit-learn, CatBoost, XGBoost, Hugging Face Transformers).

## Tech Stack

- **FastAPI** — REST API framework
- **Supabase** — PostgreSQL database and auth
- **SQLAlchemy + Alembic** — ORM and migrations
- **scikit-learn / CatBoost / XGBoost** — predictive maintenance models
- **Hugging Face Transformers (PyTorch)** — ticket categorization, priority scoring, asset summaries
- **SHAP** — model explainability

## Prerequisites

- Python 3.10+
- A Supabase project (for `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_KEY`)

## Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd PredictiX_backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Configure environment variables**

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<db>
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# Set to "true" to skip loading Hugging Face models on startup (faster cold start)
DISABLE_HF_MODELS=false
```

## Starting the Backend

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

Interactive API docs: `http://localhost:8000/docs`

### Disable Hugging Face models (optional)

Loading Transformer models on startup takes significant time. To skip this during development:

```bash
DISABLE_HF_MODELS=true uvicorn app.main:app --reload
```

## API Overview

| Router | Prefix | Description |
|---|---|---|
| Auth | `/auth` | Login, token validation |
| Assets | `/assets` | Asset CRUD and lifecycle |
| Predictions | `/predictions` | PdM classifier and regressor |
| Vehicle Predictions | `/vehicle-predictions` | Vehicle-specific maintenance |
| Warehouses | `/warehouses` | Warehouse management |
| Departments | `/departments` | Department management |
| Maintenance | `/maintenance` | Maintenance records |
| Tickets | `/tickets` | Support ticket management |
| Sensor Readings | `/sensor-readings` | IoT sensor data |
| Reports | `/reports` | Reporting endpoints |
| Notifications | `/notifications` | User notifications |
| Profile | `/profile` | User profiles |

Full route documentation is available at `/docs` when the server is running.
