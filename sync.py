#!/usr/bin/env python3
"""monarch-agent-sync — pull Monarch Money data → Supabase.

Run manually:
    python sync.py

Run with a date range override (backfill):
    python sync.py --start 2024-01-01 --end 2024-12-31

Environment variables are loaded from .env in the same directory.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from monarchmoney import MonarchMoney, RequireMFAException
from supabase import create_client, Client

# App-level logging only — suppress noisy HTTP/network libraries
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
log = logging.getLogger("monarch-sync")

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

MONARCH_EMAIL          = os.environ["MONARCH_EMAIL"]
MONARCH_PASSWORD       = os.environ["MONARCH_PASSWORD"]
MONARCH_MFA_SECRET_KEY = os.environ.get("MONARCH_MFA_SECRET_KEY")  # optional
SUPABASE_URL           = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY   = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# How many days back to sync transactions by default (incremental)
DEFAULT_LOOKBACK_DAYS = 1

# Session file — avoids re-login every run
SESSION_FILE = Path(__file__).parent / ".monarch_session"


# ── Supabase client ───────────────────────────────────────────────────────────

def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ── Monarch login ─────────────────────────────────────────────────────────────

async def get_monarch() -> MonarchMoney:
    mm = MonarchMoney(session_file=str(SESSION_FILE))

    if SESSION_FILE.exists():
        try:
            mm.load_session(str(SESSION_FILE))
            log.info("Loaded saved Monarch session")
            return mm
        except Exception:
            log.warning("Saved session invalid, re-authenticating...")
            SESSION_FILE.unlink(missing_ok=True)

    log.info("Logging in to Monarch Money as %s", MONARCH_EMAIL)
    try:
        await mm.login(
            email=MONARCH_EMAIL,
            password=MONARCH_PASSWORD,
            save_session=True,
            use_saved_session=False,
            mfa_secret_key=MONARCH_MFA_SECRET_KEY,
        )
    except RequireMFAException:
        log.info("MFA required — Monarch should have emailed you a code")
        code = input("Enter the MFA code from your email: ").strip()
        await mm.multi_factor_authenticate(
            MONARCH_EMAIL, MONARCH_PASSWORD, code, trusted_device=True,
        )

    mm.save_session(str(SESSION_FILE))
    log.info("Authenticated with Monarch Money (session saved)")
    return mm


# ── Sync helpers ──────────────────────────────────────────────────────────────

def _log_start(sb: Client) -> int:
    log.info("Starting sync run...")
    result = sb.table("monarch_sync_log").insert({
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }).execute()
    return result.data[0]["id"]


def _log_finish(sb: Client, log_id: int, **counts) -> None:
    sb.table("monarch_sync_log").update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        **counts,
    }).eq("id", log_id).execute()


def _log_error(sb: Client, log_id: int, error: str) -> None:
    sb.table("monarch_sync_log").update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error_message": error,
    }).eq("id", log_id).execute()


# ── Account sync ──────────────────────────────────────────────────────────────

async def sync_accounts(mm: MonarchMoney, sb: Client) -> list[dict]:
    log.info("Syncing accounts...")
    raw = await mm.get_accounts()
    accounts = raw.get("accounts", [])

    rows = []
    for a in accounts:
        row = {
            "id":               a["id"],
            "name":             a["displayName"],
            "institution_name": (a.get("institution") or {}).get("name"),
            "type":             (a.get("type") or {}).get("name"),
            "subtype":          (a.get("subtype") or {}).get("name"),
            "current_balance":  a.get("currentBalance"),
            "currency":         a.get("currencyCode", "USD"),
            "is_closed":        a.get("isClosedAt") is not None,
            "is_hidden":        a.get("hideFromList", False),
            "synced_at":        datetime.now(timezone.utc).isoformat(),
        }
        rows.append(row)

    if rows:
        sb.table("monarch_accounts").upsert(rows, on_conflict="id").execute()

    log.info("Synced %d accounts", len(rows))
    return accounts


# ── Balance snapshots ─────────────────────────────────────────────────────────

async def sync_balance_snapshots(accounts: list[dict], sb: Client) -> int:
    log.info("Writing balance snapshots...")
    today = date.today().isoformat()
    rows = []

    for a in accounts:
        balance = a.get("currentBalance")
        if balance is None:
            continue
        rows.append({
            "account_id":    a["id"],
            "balance":       balance,
            "snapshot_date": today,
            "synced_at":     datetime.now(timezone.utc).isoformat(),
        })

    if rows:
        # on_conflict: if a snapshot already exists for today, update the balance
        sb.table("monarch_balance_snapshots").upsert(
            rows, on_conflict="account_id,snapshot_date"
        ).execute()

    log.info("Wrote %d snapshots", len(rows))
    return len(rows)


# ── Transaction sync ──────────────────────────────────────────────────────────

async def sync_transactions(
    mm: MonarchMoney,
    sb: Client,
    start: date,
    end: date,
) -> int:
    log.info("Syncing transactions %s → %s", start, end)

    # Monarch returns up to 100 per call — paginate
    limit = 500
    offset = 0
    total_synced = 0

    while True:
        raw = await mm.get_transactions(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            limit=limit,
            offset=offset,
        )
        txns = raw.get("allTransactions", {}).get("results", [])
        if not txns:
            break

        rows = []
        for t in txns:
            rows.append({
                "id":            t["id"],
                "account_id":    (t.get("account") or {}).get("id"),
                "date":          t["date"],
                "merchant_name": (t.get("merchant") or {}).get("name") or t.get("merchantName"),
                "original_name": t.get("originalName"),
                "amount":        t["amount"],
                "category":      (t.get("category") or {}).get("name"),
                "category_group": (t.get("category") or {}).get("group", {}).get("name") if t.get("category") else None,
                "is_pending":    t.get("isPending", False),
                "notes":         t.get("notes"),
                "synced_at":     datetime.now(timezone.utc).isoformat(),
            })

        sb.table("monarch_transactions").upsert(rows, on_conflict="id").execute()
        total_synced += len(rows)
        log.info("Upserted %d transactions so far...", total_synced)

        if len(txns) < limit:
            break
        offset += limit

    log.info("Synced %d transactions total", total_synced)
    return total_synced


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(start: date | None, end: date | None) -> None:
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    log.info("monarch-agent-sync starting")
    log.info("Date range: %s → %s", start, end)

    sb = get_supabase()
    log_id = _log_start(sb)

    try:
        mm = await get_monarch()
        accounts = await sync_accounts(mm, sb)
        snapshots = await sync_balance_snapshots(accounts, sb)
        # Chunk into monthly ranges to avoid timeouts on large backfills
        txn_count = 0
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(
                date(chunk_start.year + (chunk_start.month // 12),
                     (chunk_start.month % 12) + 1, 1) - timedelta(days=1),
                end,
            )
            txn_count += await sync_transactions(mm, sb, chunk_start, chunk_end)
            chunk_start = chunk_end + timedelta(days=1)

        _log_finish(sb, log_id,
                    accounts_synced=len(accounts),
                    transactions_synced=txn_count,
                    snapshots_written=snapshots)

        log.info("Sync complete — %d accounts, %d transactions, %d snapshots",
                 len(accounts), txn_count, snapshots)

    except Exception as e:
        log.error("Sync failed: %s", e, exc_info=True)
        _log_error(sb, log_id, str(e))
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Monarch Money → Supabase")
    parser.add_argument("--start", type=date.fromisoformat, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end",   type=date.fromisoformat, help="End date   (YYYY-MM-DD)")
    args = parser.parse_args()
    asyncio.run(main(args.start, args.end))
