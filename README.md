# monarch-agent-sync

Pulls account, transaction, and balance data from Monarch Money on your local machine (residential IP — no VPC blocks) and syncs it to Supabase for your AI financial advisor agent to query.

Runs daily via launchd. Fully incremental — only fetches what's new.

---

## Architecture

```
Your Mac (residential IP)
      │
      ▼
Monarch Money API
      │  sync.py
      ▼
Supabase (monarch_accounts, monarch_transactions, monarch_balance_snapshots)
      │
      ▼
w-buffet agent — queries Supabase for financial analysis
```

---

## Setup

### Prerequisites

- macOS
- Python 3.11+
- Supabase project with the schema applied (see below)
- Monarch Money account

### 1. Clone and run setup

```bash
git clone https://github.com/sim1029/monarch-agent-sync.git
cd monarch-agent-sync
chmod +x setup.sh
./setup.sh
```

This installs dependencies, creates `.env`, and registers a daily launchd job at 6:00am.

### 2. Fill in credentials

```bash
open .env
```

| Variable | Where to find it |
|---|---|
| `MONARCH_EMAIL` | Your Monarch Money login email |
| `MONARCH_PASSWORD` | Your Monarch Money password |
| `MONARCH_MFA_SECRET_KEY` | Monarch → Settings → Security → Enable MFA → copy the **text code** (optional but recommended for headless runs) |
| `SUPABASE_URL` | Supabase Dashboard → Project Settings → API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Dashboard → Project Settings → API → `service_role` key |

### 3. Apply the schema

Open your Supabase project → **SQL Editor**, paste the contents of `schema.sql`, and run it.

### 4. Initial backfill

```bash
source .venv/bin/activate
python sync.py --start 2023-01-01
```

Adjust the start date to however far back you want history. After this, daily syncs handle the rest automatically.

---

## Usage

```bash
# Incremental sync (last 30 days)
python sync.py

# Backfill a specific date range
python sync.py --start 2024-01-01 --end 2024-06-30
```

Logs are written to `~/Library/Logs/monarch-agent-sync/`.

---

## Database Tables

| Table | Contents |
|---|---|
| `monarch_accounts` | All linked accounts — name, institution, type, current balance |
| `monarch_transactions` | Every transaction — date, merchant, amount, category, account |
| `monarch_balance_snapshots` | Daily balance per account — used for net worth over time |
| `monarch_sync_log` | Run history — timestamps, counts, errors |

---

## MFA Note

Monarch sometimes requires MFA on first login or after a session expires. Two options:

1. **MFA Secret Key (recommended):** Copy it from Monarch → Settings → Security → Enable MFA → the text code shown during setup. Set `MONARCH_MFA_SECRET_KEY` in `.env`. The script handles it automatically.

2. **Interactive:** If no secret key is set and MFA is triggered, the script will prompt you in the terminal for the code.

The session is saved to `.monarch_session` after first login — subsequent runs reuse it without re-authenticating (sessions last several months).
