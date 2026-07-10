# EC2 Backend Deployment by Dinusha

## Instance Details

| Item | Value |
|---|---|
| Provider | AWS EC2 |
| Instance type | t3.micro (free tier eligible) |
| OS | Ubuntu 26.04 "Resolute" |
| Region | ap-south-1 (Mumbai) |
| Public IP | `13.232.200.154` |
| Backend URL | `https://13.232.200.154.sslip.io` |
| Repo path on EC2 | `/home/ubuntu/PredictiX_Backend` |
| SSH user | `ubuntu` |
| Key file | `C:\Users\Dinusha Ekanayake\Downloads\predictix-key.pem` |

---

## 1. AWS Setup

### Key Pair
- Type: RSA, `.pem` format
- Downloaded to Windows: `predictix-key.pem`
- Fixed Windows permissions (CodexSandboxUsers group caused "Bad permissions" error):

```powershell
$keyPath = "C:\Users\Dinusha Ekanayake\Downloads\predictix-key.pem"
$acl = Get-Acl $keyPath
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) }
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, "Read", "Allow")
$acl.AddAccessRule($rule)
Set-Acl $keyPath $acl
```

### Security Group Inbound Rules

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | 0.0.0.0/0 | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP (Certbot challenge) |
| 443 | TCP | 0.0.0.0/0 | HTTPS |
| 8000 | TCP | 0.0.0.0/0 | FastAPI (direct, optional) |

---

## 2. Server Setup (SSH)

### Connect
```bash
ssh -i "C:\Users\Dinusha Ekanayake\Downloads\predictix-key.pem" ubuntu@13.232.200.154
```

### System packages installed
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.14 python3.14-venv python3-pip git nginx certbot python3-certbot-nginx
```

> Ubuntu 26.04 ships Python 3.14 — `python3.12` does not exist on this OS.

---

## 3. Code Deployment

### Clone repo
```bash
cd /home/ubuntu
git clone https://YOUR_GITHUB_TOKEN@github.com/Dinusha-Ekanayake/PredictiX_Backend.git
cd PredictiX_Backend
git checkout dev
```

### Python virtual environment
```bash
python3.14 -m venv venv
source venv/bin/activate
```

### `requirements-prod.txt` (created on EC2 — excludes heavy ML packages)

```
sqlalchemy
alembic
apscheduler
psycopg[binary]
psycopg2-binary
python-jose
passlib[bcrypt]
pydantic-settings
python-multipart
requests
python-dotenv
email-validator
passlib==1.7.4
bcrypt==4.1.2
fastapi
uvicorn
pandas
numpy
scikit-learn
catboost
shap
supabase
lifelines
joblib
groq
nltk
langchain-groq
langchain-core
reportlab
```

> **Excluded:** `torch`, `transformers`, `sentence-transformers`, `huggingface_hub`, `safetensors`
> These would exceed the 8GB EBS disk. HuggingFace models run remotely via HF Hub (set `DISABLE_HF_MODELS=true`).

```bash
pip install -r requirements-prod.txt
pip install xgboost   # installed separately after initial disk space issue
```

### `.env` file
Created at `/home/ubuntu/PredictiX_Backend/.env` with all environment variables:
```
DATABASE_URL=...
SUPABASE_URL=...
SUPABASE_KEY=...
HF_TOKEN=...
HF_ASSET_SUMMARIZATION_REPO=...
GROQ_API_KEY=...
DISABLE_HF_MODELS=true
ALLOWED_ORIGINS=https://13.232.200.154.sslip.io
```

---

## 4. ML Model Files

All `.pkl` files in the repo are **Git LFS pointers** (134 bytes of text) — not real binaries.
Real model files were copied from Windows to EC2 using `scp`.

### Files copied via scp (from Windows PowerShell)

| File | Size | Destination |
|---|---|---|
| `predictix_xgboost_classifier_v6.pkl` | 5.7 MB | `pdm_classifier_model/` |
| `maintenance_classifier_features.pkl` | 573 B | `pdm_classifier_model/` |
| `predictix_pm_model_v5.pkl` | 97 MB | `pdm_regressor_model/` |
| `regression_selected_features.pkl` | 558 B | `pdm_regressor_model/` |
| `battery_aft.pkl` | ~858 KB | `survival_analysis/` |
| `brake_aft.pkl` | ~858 KB | `survival_analysis/` |
| `hydraulic_aft.pkl` | ~858 KB | `survival_analysis/` |
| `oil_aft.pkl` | ~858 KB | `survival_analysis/` |
| `tire_aft.pkl` | ~858 KB | `survival_analysis/` |

### scp command format
```powershell
scp -i "C:\Users\Dinusha Ekanayake\Downloads\predictix-key.pem" `
    "e:\...\model.pkl" `
    ubuntu@13.232.200.154:/home/ubuntu/PredictiX_Backend/app/ai/models/pdm_regressor_model/
```

> These files show as "modified" in git on EC2 (real binaries replacing LFS pointers).
> **Never commit them.** Back up to `/tmp/` before any `git reset --hard`, then restore after.

---

## 5. Code Fixes Applied

### Fix 1: `ModuleNotFoundError: transformers` at startup
**File:** `app/ai/services/asset_summary_service.py`
Moved `from transformers import ...` inside the function, guarded by `DISABLE_HF_MODELS` check (lazy import).

### Fix 2: `ModuleNotFoundError: sentence_transformers` at startup
**File:** `app/ai/services/knowledge_service.py`
Moved `from sentence_transformers import SentenceTransformer` inside `_get_model()` (lazy import).

### Fix 3: `invalid load key, 'v'` — LFS pointer instead of real pkl
Copied real binary files via `scp`.

### Fix 4: `No module named 'predictor_name'` — wrong loader
**File:** `app/main.py` — `_load_pickle()`
Added joblib fallback since the regressor bundle was saved with `joblib.dump`:
```python
def _load_pickle(path: Path):
    try:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    except Exception:
        return joblib.load(path)
```

### Fix 5: `AttributeError: 'dict' object has no attribute 'predict'`
Both pkl files are **dict bundles**, not bare model objects.

**Classifier bundle keys:** `model`, `threshold`, `feature_cols`, `categorical_cols`
**Regressor bundle keys:** `explainer_model` (CatBoost — use this), `feature_cols`, `categorical_cols`

Fixed in `app/main.py` — `_load_pdm_models()`:
```python
clf_bundle = _load_pickle(CLF_MODEL_PATH)
if isinstance(clf_bundle, dict):
    clf_model            = clf_bundle["model"]
    clf_features         = list(clf_bundle.get("feature_cols", []))
    clf_threshold        = float(clf_bundle.get("threshold", 0.5))
    clf_categorical_cols = list(clf_bundle.get("categorical_cols", []))

reg_bundle = _load_pickle(REG_MODEL_PATH)
if isinstance(reg_bundle, dict):
    reg_model            = reg_bundle["explainer_model"]  # CatBoost
    reg_features         = list(reg_bundle.get("feature_cols", []))
    reg_categorical_cols = list(reg_bundle.get("categorical_cols", []))
```

Also updated `app/ai/services/batch_prediction_service.py`:
- `_run_regressor()` accepts `reg_categorical_cols` directly (removed `get_cat_feature_indices()`)
- `run_batch_for_asset()` and `run_batch_for_all_assets()` each gained a `reg_categorical_cols` parameter

---

## 6. systemd Service

**File:** `/etc/systemd/system/predictix.service`
```ini
[Unit]
Description=PredictiX FastAPI Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/PredictiX_Backend
EnvironmentFile=/home/ubuntu/PredictiX_Backend/.env
ExecStart=/home/ubuntu/PredictiX_Backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable predictix
sudo systemctl start predictix
```

---

## 7. Nginx + HTTPS (sslip.io + Certbot)

### Why it was needed
Frontend is hosted on Vercel (HTTPS). Browsers block HTTP API calls from HTTPS pages (Mixed Content error).

### sslip.io domain
Free IP-based DNS — `13.232.200.154.sslip.io` automatically resolves to `13.232.200.154`.
No registration required.

### Install + issue SSL certificate
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo certbot --nginx -d 13.232.200.154.sslip.io
```

### `/etc/nginx/sites-available/default` — HTTPS block
```nginx
server {
    listen 443 ssl;
    server_name 13.232.200.154.sslip.io;

    ssl_certificate /etc/letsencrypt/live/13.232.200.154.sslip.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/13.232.200.154.sslip.io/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 8. Frontend Configuration

**Vercel environment variable:**
```
NEXT_PUBLIC_API_URL = https://13.232.200.154.sslip.io
```

**CORS in `app/main.py`** (hardcoded):
```python
"https://predicti-x-frontend.vercel.app",
"https://predicti-x-frontend-dinusha-ekanayakes-projects.vercel.app",
```

---

## 9. Service Management Commands

| Task | Command (run from SSH session) |
|---|---|
| Check status | `sudo systemctl status predictix --no-pager` |
| View live logs | `sudo journalctl -u predictix -f` |
| Start service | `sudo systemctl start predictix` |
| Stop service | `sudo systemctl stop predictix` |
| Restart service | `sudo systemctl restart predictix` |
| Pull latest + restart | `git pull origin dev && sudo systemctl restart predictix` |
| Check memory | `free -h` |
| Check disk | `df -h` |

### SSH command (from Windows)
```powershell
ssh -i "C:\Users\Dinusha Ekanayake\Downloads\predictix-key.pem" ubuntu@13.232.200.154
```

---

## 10. Important Notes

- **Binary model files are NOT in git** — must be re-copied via `scp` if the instance is re-created or `git reset --hard` is run.
- **Back up binaries to `/tmp/`** on EC2 before any reset. Note: `/tmp/` is wiped on instance reboot — re-copy from Windows if the instance was stopped.
- **If the EC2 instance is stopped and started, the public IP may change** — update the `NEXT_PUBLIC_API_URL` in Vercel if that happens.
- **Free tier duration:** 12 months from account creation, then ~$7.50/month for t3.micro.
- **Memory usage at idle:** ~430 MB — tight on 1 GB RAM. Avoid triggering multiple batch prediction runs simultaneously.
- **`DISABLE_HF_MODELS=true`** — HuggingFace inference models are called remotely via HF Hub; torch/transformers are not installed locally.
