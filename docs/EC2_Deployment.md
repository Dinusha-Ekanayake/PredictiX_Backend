# Backend deployment on AWS EC2

This runbook covers how the PredictiX API runs in production, how a release reaches the instance, and how to rebuild the instance from nothing. The frontend is deployed separately on Vercel; see the frontend repository's `docs/DEPLOYMENT.md`.

## 1. Production topology

| Item | Value |
|---|---|
| Instance | t3.micro (2 vCPU, 1 GB RAM, 8 GB gp3), ap-south-1 |
| OS / Python | Ubuntu 26.04 LTS, Python 3.14 (the distribution default) |
| Public host | `https://13.232.200.154.sslip.io` (sslip.io resolves the name to the IP) |
| App directory | `/home/ubuntu/PredictiX_Backend` (a git clone of this repository) |
| Process | systemd unit `predictix` running uvicorn on `127.0.0.1:8000`, one worker |
| Edge | nginx on 80/443 with a Let's Encrypt certificate (certbot renews it) |
| Configuration | `/home/ubuntu/PredictiX_Backend/.env`, read by systemd |

```
browser ──HTTPS/WSS──▶ nginx :443 ──HTTP──▶ uvicorn 127.0.0.1:8000 ──▶ Supabase Postgres / Storage
                                                       └────────────▶ Groq, Hugging Face Spaces
```

The API runs one worker on purpose: the scheduler (the nightly prediction batch and the reminder mail) has to run in exactly one process.

### What the instance installs

The instance installs **`requirements-prod.txt`**, the server runtime. It excludes torch and the local embedding model, which would not fit in 1 GB of RAM and an 8 GB disk. `requirements.txt` adds those for development, CI and knowledge-base ingestion.

| Feature | On EC2 |
|---|---|
| PdM, cost and survival models | Loaded locally from the files tracked in git (`app/ai/models/`), with checksums verified |
| Ticket categorisation, priority and summaries | Private Hugging Face Spaces (`HF_AI_SPACE_URL`, `TICKET_SUMMARY_SPACE`, `ASSET_SUMMARY_SPACE`) |
| Chatbot knowledge search | Queries are embedded on the instance by ONNX Runtime with the official ONNX export of all-MiniLM-L6-v2. It produces the same vectors as the ingestion model (cosine ≥ 0.9999, `test_onnx_embedder.py`) at about 5 ms per query, and the deploy script caches it. The hosted Hugging Face endpoint is only a last resort |
| Nightly knowledge-base refresh | Not scheduled, because it needs the local model; run it from a workstation (section 6) |
| PDF export (`/reports/render-pdf`) | Headless Chromium through Playwright; without it the route answers 503 and the frontend falls back to the print dialog |

The CI job **EC2 compatibility (Python 3.14)** installs `requirements-prod.txt` on Python 3.14 exactly as the instance does. It then starts the API and loads every shipped model (`scripts/deploy/check_runtime.py --server`). A dependency that breaks the instance fails CI before it can be deployed.

## 2. How a release is deployed

Releases are automatic and gated:

1. A change merges to `main` through a pull request from `dev`.
2. **CI** runs on `main`: static checks, unit tests on Python 3.12 and 3.14, integration and functional tests.
3. When CI succeeds, **Deploy to EC2** (`.github/workflows/deploy.yml`) connects over SSH. It runs `scripts/deploy/ec2_deploy.sh`, taking the script from the commit being deployed.
4. The script:
   - checks `.env` and free disk space;
   - installs the **exact commit CI tested**;
   - runs `pip install -r requirements-prod.txt` and restarts the service;
   - requires `GET /` to report `models_loaded: true`.

   If the health check fails, it reinstalls the previous commit and restarts it, then fails the job with the service log attached.
5. The workflow then checks the public URL through nginx.

Properties:
- **Idempotent.** Re-running a deploy of the running, healthy commit changes nothing.
- **Exact.** Only commits on the target branch are accepted, and branch and commit values are validated before use.
- **Serialised.** Two deploys never overlap, and a running deploy is never cancelled.

To deploy by hand, use **Actions → Deploy to EC2 → Run workflow** and pick the branch. On the instance itself:

```bash
cd /home/ubuntu/PredictiX_Backend
bash scripts/deploy/ec2_deploy.sh /home/ubuntu/PredictiX_Backend predictix main
```

### GitHub configuration

Environment **`production`** (Settings → Environments). Adding a required reviewer there makes every deploy wait for approval.

| Secret | Value |
|---|---|
| `EC2_HOST` | `13.232.200.154` |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | Private key of a deploy key pair (the full PEM text) |
| `EC2_APP_DIR` | `/home/ubuntu/PredictiX_Backend` |
| `EC2_SERVICE_NAME` | `predictix` |
| `EC2_PORT` | Optional, defaults to 22 |
| `EC2_HOST_FINGERPRINT` | Recommended: SHA256 host key fingerprint, so the job refuses an impostor host |

| Variable | Value |
|---|---|
| `BACKEND_PUBLIC_URL` | `https://13.232.200.154.sslip.io/` |

Get the fingerprint from a trusted machine:

```bash
ssh-keyscan -t ed25519 13.232.200.154 2>/dev/null | ssh-keygen -lf - | awk '{print $2}'
```

## 3. Building the instance from scratch

### 3.1 AWS

Launch Ubuntu 26.04 on t3.micro with a gp3 volume. 8 GB works: the server install is held under 1.9 GB by a CI budget. 16 GB costs about USD 0.65 more per month and leaves room for log growth and upgrades.

Security group inbound rules:

| Port | Source | Purpose |
|---|---|---|
| 22 | Your IP, plus GitHub Actions if deploys are automatic | SSH |
| 80 | 0.0.0.0/0 | HTTP to HTTPS redirect, certbot challenge |
| 443 | 0.0.0.0/0 | HTTPS / WSS |

Do **not** open 8000. The API listens on loopback only, and a public 8000 would bypass TLS.

### 3.2 System packages and swap

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx

# 1 GB swap: headroom for pip installs and PDF rendering on 1 GB of RAM
# (use 2G on a 16 GB volume).
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3.3 Code and dependencies

Clone with a read-only deploy key (repository Settings → Deploy keys), not a personal token:

```bash
cd /home/ubuntu
git clone git@github.com:Dinusha-Ekanayake/PredictiX_Backend.git
cd PredictiX_Backend
git checkout main
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install --prefer-binary -r requirements-prod.txt
./venv/bin/python -m playwright install chromium
HF_HUB_OFFLINE=0 ./venv/bin/python -m app.chatbot.onnx_embedder   # query embedding model
sudo ./venv/bin/python -m playwright install-deps chromium   # shared libraries Chromium needs
```

The live models are ordinary files in git, so the clone already contains them; nothing has to be copied by hand. Older model versions under `app/ai/models/**/old/` are Git LFS pointers and are not used at runtime.

### 3.4 Configuration

Create `.env` from `.env.example`, then make it readable only by its owner (`chmod 600 .env`). The deploy script refuses to run without the first four settings below.

| Setting | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Supabase Postgres connection string |
| `JWT_SECRET` | yes | Long random value. The API refuses to start without it, and changing it signs everyone out |
| `SUPABASE_URL` | yes | |
| `SUPABASE_KEY` | yes | Server key; `SUPABASE_SERVICE_ROLE_KEY` is also read where uploads need it |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | Storage uploads and admin user management |
| `ENV` | yes | `production`. Hides the API docs and drops the localhost CORS origins |
| `ALLOWED_ORIGINS` | if needed | Extra frontend origins, comma-separated (the Vercel production domains are built in) |
| `GROQ_API_KEY`, `CHATBOT_GROQ_API_KEY`, `WH_GROQ_API_KEY` | yes | LLM features |
| `HF_TOKEN`, `HF_TOKEN_space` | yes | Private Hugging Face Spaces and the hosted embedding endpoint |
| `HF_AI_SPACE_URL`, `TICKET_SUMMARY_SPACE`, `ASSET_SUMMARY_SPACE` | yes | Ticket and asset models |
| `SCHEDULER_ENABLED` | | `true` on this instance only. Every other copy of the API (dev, CI) must set `false` |
| `KB_REFRESH_ENABLED` | | Leave unset; it is detected automatically and is off on this instance |

### 3.5 Service and nginx

The unit and site files are versioned in `deploy/`:

```bash
sudo cp deploy/systemd/predictix.service /etc/systemd/system/predictix.service
sudo systemctl daemon-reload
sudo systemctl enable --now predictix

sudo cp deploy/nginx/predictix.conf /etc/nginx/sites-available/predictix
sudo sed -i 's/api.example.com/13.232.200.154.sslip.io/g' /etc/nginx/sites-available/predictix
sudo ln -sf /etc/nginx/sites-available/predictix /etc/nginx/sites-enabled/predictix
sudo rm -f /etc/nginx/sites-enabled/default
sudo certbot --nginx -d 13.232.200.154.sslip.io
sudo nginx -t && sudo systemctl reload nginx
```

The nginx site:
- forwards WebSocket upgrades, which realtime notifications depend on;
- allows 25 MB uploads;
- waits up to 300 s for LLM-backed requests.

### 3.6 Verify

```bash
./venv/bin/python scripts/deploy/check_runtime.py --server   # environment fit to serve
curl -s http://127.0.0.1:8000/                                # {"models_loaded": true, ...}
curl -s https://13.232.200.154.sslip.io/                      # same, through nginx and TLS
```

## 4. Operations

| Task | Command |
|---|---|
| Status | `sudo systemctl status predictix --no-pager` |
| Live log | `sudo journalctl -u predictix -f` |
| Restart | `sudo systemctl restart predictix` |
| Deployed commit | `git -C /home/ubuntu/PredictiX_Backend log --oneline -1` |
| Memory / disk | `free -h`, `df -h /` |
| Certificate renewal test | `sudo certbot renew --dry-run` |

## 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Deploy fails with "JWT_SECRET is missing from .env" | Add it to `.env`; the API cannot start without it |
| Deploy fails with "only N MB free" | Clear the pip and Playwright caches: `rm -rf ~/.cache/pip`, then `df -h` |
| Knowledge answers fall back to help articles | Run `check_runtime.py --server`. If the embedding model is missing, run `HF_HUB_OFFLINE=0 ./venv/bin/python -m app.chatbot.onnx_embedder` |
| `models_loaded: false` | Read `journalctl -u predictix`. The cause is usually a checksum mismatch (`app/ai/models/model_checksums.json`) or a model file missing from the checkout |
| Notifications never arrive | nginx is not forwarding `Upgrade`; use `deploy/nginx/predictix.conf` |
| Browser CORS error | The frontend origin is missing; add it to `ALLOWED_ORIGINS` and restart |
| PDF export opens the print dialog | Chromium or its libraries are missing; run the two `playwright install` commands in 3.3 |
| Service restarts under load | `MemoryMax` was reached; confirm the swap is active (`swapon --show`) |
| Public IP changed after stop/start | Attach an Elastic IP, or update `EC2_HOST`, the certificate host name and the frontend's `NEXT_PUBLIC_API_URL` |

## 6. Knowledge-base refresh

Bulk ingestion embeds passages with the local model, which the instance does not install. Run it from a workstation or CI with the full `requirements.txt`:

```bash
python -m app.kb.pipeline ingest --only D01   # ticket patterns
python -m app.kb.pipeline status
```

A source whose content has not changed is skipped by its fingerprint, so re-running it is harmless.
