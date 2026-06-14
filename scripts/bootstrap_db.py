"""Bootstrap TimescaleDB for Kronos NSE.

Steps:
  1. Wait for the DB server to be healthy (max 30 s).
  2. Create the kronos_nse database if it does not already exist.
  3. Enable the timescaledb extension.
  4. Run all *.sql migrations in data/storage/migrations/ in order.
  5. Exit 0 on success, 1 on failure.

Usage:
    python scripts/bootstrap_db.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ── constants ────────────────────────────────────────────────────────────────
_DSN = os.getenv(
    "DATABASE_URL", "postgresql://postgres:kronos@localhost:5432/kronos_nse"
)
_POSTGRES_DSN = (
    _DSN.rsplit("/", 1)[0] + "/postgres"
)  # connect to postgres DB to create target
_DB_NAME = _DSN.rsplit("/", 1)[-1]
_MIGRATIONS = Path(__file__).parent.parent / "data" / "storage" / "migrations"
_TIMEOUT_S = 30


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _err(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr)


# ── wait for DB ───────────────────────────────────────────────────────────────


async def wait_for_db() -> None:
    """Poll until the DB server accepts connections (max _TIMEOUT_S seconds)."""
    print(f"[1/4] Waiting for TimescaleDB at {_POSTGRES_DSN} ...")
    deadline = time.monotonic() + _TIMEOUT_S
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = await asyncpg.connect(_POSTGRES_DSN, timeout=3)
            await conn.close()
            _ok(f"DB reachable (attempt {attempt})")
            return
        except Exception as exc:
            if time.monotonic() > deadline:
                _err(f"DB not reachable after {_TIMEOUT_S}s: {exc}")
                sys.exit(1)
            print(f"     attempt {attempt} failed: {exc!r} — retrying …")
            await asyncio.sleep(2)


# ── create DB ─────────────────────────────────────────────────────────────────


async def create_database() -> None:
    """Create the target database if it does not exist."""
    print(f"[2/4] Creating database '{_DB_NAME}' if not exists …")
    conn = await asyncpg.connect(_POSTGRES_DSN)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _DB_NAME
        )
        if exists:
            _ok(f"Database '{_DB_NAME}' already exists")
        else:
            # CREATE DATABASE cannot run inside a transaction block
            await conn.execute(f'CREATE DATABASE "{_DB_NAME}"')
            _ok(f"Database '{_DB_NAME}' created")
    finally:
        await conn.close()


# ── enable extension ──────────────────────────────────────────────────────────


async def enable_timescaledb() -> None:
    """Enable the TimescaleDB extension in the target database."""
    print("[3/4] Enabling TimescaleDB extension …")
    conn = await asyncpg.connect(_DSN)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
        version = await conn.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        )
        _ok(f"TimescaleDB extension enabled (version {version})")
    finally:
        await conn.close()


# ── run migrations ────────────────────────────────────────────────────────────


async def run_migrations() -> None:
    """Execute all *.sql migration files in order."""
    print(f"[4/4] Running migrations from {_MIGRATIONS} …")
    sql_files = sorted(_MIGRATIONS.glob("*.sql"))
    if not sql_files:
        _ok("No migration files found — nothing to run")
        return

    conn = await asyncpg.connect(_DSN)
    try:
        for path in sql_files:
            sql = path.read_text(encoding="utf-8")
            await conn.execute(sql)
            _ok(f"Applied: {path.name}")
    finally:
        await conn.close()


# ── entry point ───────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 52)
    print(" Kronos NSE — Database Bootstrap")
    print("=" * 52)
    try:
        await wait_for_db()
        await create_database()
        await enable_timescaledb()
        await run_migrations()
        print("\n✓ Bootstrap complete.\n")
    except SystemExit:
        raise
    except Exception as exc:
        _err(f"Bootstrap failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
