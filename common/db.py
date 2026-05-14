"""Postgres helpers: connection-pool factory + audit-event writer.

The `audit_events` table is **separate** from the LangGraph checkpointer
tables. Checkpoints let us *resume* a paused graph; audit_events give us a
queryable, structured timeline of every decision and HITL interaction.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import psycopg
from psycopg_pool import AsyncConnectionPool

from common.schemas import AuditEntry


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    return (
        f"postgresql://{os.environ.get('PG_USER', 'hitl')}:"
        f"{os.environ.get('PG_PASSWORD', 'hitl')}@"
        f"{os.environ.get('PG_HOST', 'localhost')}:"
        f"{os.environ.get('PG_PORT', '1505')}/"
        f"{os.environ.get('PG_DB', 'hitl_audit')}"
    )


@asynccontextmanager
async def pg_pool() -> AsyncIterator[AsyncConnectionPool]:
    pool = AsyncConnectionPool(
        conninfo=database_url(),
        max_size=10,
        kwargs={"autocommit": True, "row_factory": psycopg.rows.dict_row},
        open=False,
    )
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


async def write_audit_event(
    pool: AsyncConnectionPool,
    *,
    thread_id: str,
    pr_url: str,
    entry: AuditEntry,
) -> None:
    """Append one structured audit row. Called from every node in the graph.

    `thread_id` and `pr_url` are session-context columns (used for grouping
    and filtering); all other fields come from the `AuditEntry` so they map
    1-to-1 with first-class SQL columns.
    """
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO audit_events (
                timestamp, thread_id, pr_url,
                agent_id, action, confidence, risk_level,
                reviewer_id, decision, reason, execution_time_ms
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry.timestamp, thread_id, pr_url,
                entry.agent_id, entry.action, entry.confidence, entry.risk_level,
                entry.reviewer_id, entry.decision, entry.reason, entry.execution_time_ms,
            ),
        )


async def replay_events(
    pool: AsyncConnectionPool, thread_id: str
) -> list[dict[str, Any]]:
    """Return every event for a thread, ordered by time. Used by audit/replay.py."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, timestamp, agent_id, action, confidence, risk_level,
                   reviewer_id, decision, reason, execution_time_ms
              FROM audit_events
             WHERE thread_id = %s
             ORDER BY id
            """,
            (thread_id,),
        )
        return await cur.fetchall()
