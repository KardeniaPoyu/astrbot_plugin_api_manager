"""
SQLite-based route statistics store.

Tracks:
- Per-provider request count, error count, latency
- Per-group routing decisions
- Daily aggregates
"""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("astrbot.api_mgr")


@dataclass
class ProviderStats:
    """Aggregated statistics for a single provider."""
    provider_id: str = ""
    total_requests: int = 0
    total_errors: int = 0
    last_used: float = 0.0
    error_rate: float = 0.0


@dataclass
class RouteLog:
    """A single routing event."""
    id: int = 0
    timestamp: float = 0.0
    group_name: str = ""
    provider_id: str = ""
    scene: str = ""
    success: bool = True
    error_type: str = ""
    latency_ms: float = 0.0


class StatsStore:
    """SQLite store for per-provider routing statistics.

    The store file is placed in the plugin's directory as ``stats.db``.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS route_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        group_name TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        scene TEXT DEFAULT '',
        success INTEGER DEFAULT 1,
        error_type TEXT DEFAULT '',
        latency_ms REAL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_route_logs_provider ON route_logs(provider_id);
    CREATE INDEX IF NOT EXISTS idx_route_logs_time ON route_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_route_logs_group ON route_logs(group_name);
    """

    def __init__(self, db_path: str = ""):
        if not db_path:
            db_path = str(Path(__file__).parent.parent / "stats.db")
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        try:
            with self._get_conn() as conn:
                conn.executescript(self.SCHEMA)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            logger.info(f"StatsStore: Initialized at {self._db_path}")
        except Exception as e:
            logger.error(f"StatsStore: Failed to initialize: {e}")

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def log_route(
        self,
        group_name: str,
        provider_id: str,
        scene: str = "",
        success: bool = True,
        error_type: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Log a routing event."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO route_logs (timestamp, group_name, provider_id, scene, success, error_type, latency_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (time.time(), group_name, provider_id, scene, int(success), error_type, latency_ms),
                )
        except Exception as e:
            logger.warning(f"StatsStore: Failed to log route: {e}")

    def get_provider_stats(self, provider_id: str = "", days: int = 7) -> ProviderStats | list[ProviderStats]:
        """Get statistics for one or all providers.

        Args:
            provider_id: Specific provider ID, or empty for all.
            days: Lookback period in days.

        Returns:
            Single ProviderStats if provider_id is given, else list.
        """
        cutoff = time.time() - days * 86400

        try:
            with self._get_conn() as conn:
                if provider_id:
                    row = conn.execute(
                        "SELECT COUNT(*) as total, "
                        "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors, "
                        "MAX(timestamp) as last_used "
                        "FROM route_logs WHERE provider_id = ? AND timestamp >= ?",
                        (provider_id, cutoff),
                    ).fetchone()

                    total = int(row[0]) if row and row[0] else 0
                    errors = int(row[1]) if row and row[1] else 0
                    last = float(row[2]) if row and row[2] else 0.0

                    return ProviderStats(
                        provider_id=provider_id,
                        total_requests=total,
                        total_errors=errors,
                        last_used=last,
                        error_rate=errors / total if total > 0 else 0.0,
                    )

                else:
                    rows = conn.execute(
                        "SELECT provider_id, COUNT(*) as total, "
                        "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors, "
                        "MAX(timestamp) as last_used "
                        "FROM route_logs WHERE timestamp >= ? "
                        "GROUP BY provider_id ORDER BY total DESC",
                        (cutoff,),
                    ).fetchall()

                    results = []
                    for row in rows:
                        total = int(row[1]) if row[1] else 0
                        errors = int(row[2]) if row[2] else 0
                        results.append(ProviderStats(
                            provider_id=row[0],
                            total_requests=total,
                            total_errors=errors,
                            last_used=float(row[3]) if row[3] else 0.0,
                            error_rate=errors / total if total > 0 else 0.0,
                        ))
                    return results

        except Exception as e:
            logger.error(f"StatsStore: Failed to query stats: {e}")
            return ProviderStats(provider_id=provider_id) if provider_id else []

    def get_recent_errors(self, limit: int = 20) -> list[RouteLog]:
        """Get recent routing errors."""
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, timestamp, group_name, provider_id, scene, success, error_type, latency_ms "
                    "FROM route_logs WHERE success = 0 ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()

                return [
                    RouteLog(
                        id=int(r[0]),
                        timestamp=float(r[1]),
                        group_name=str(r[2]),
                        provider_id=str(r[3]),
                        scene=str(r[4]),
                        success=bool(r[5]),
                        error_type=str(r[6]),
                        latency_ms=float(r[7]),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"StatsStore: Failed to query errors: {e}")
            return []

    def get_group_summary(self, group_name: str = "", days: int = 7) -> list[dict]:
        """Get per-group routing summary."""
        cutoff = time.time() - days * 86400
        try:
            with self._get_conn() as conn:
                query = (
                    "SELECT group_name, provider_id, COUNT(*) as cnt, "
                    "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors "
                    "FROM route_logs WHERE timestamp >= ?"
                )
                params: list = [cutoff]

                if group_name:
                    query += " AND group_name = ?"
                    params.append(group_name)

                query += " GROUP BY group_name, provider_id ORDER BY cnt DESC"
                rows = conn.execute(query, tuple(params)).fetchall()

                return [
                    {
                        "group": str(r[0]),
                        "provider": str(r[1]),
                        "count": int(r[2]),
                        "errors": int(r[3]),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"StatsStore: Failed to query group summary: {e}")
            return []

    def prune_logs(self, older_than_days: int = 30) -> int:
        """Delete logs older than the specified days. Returns count of deleted rows."""
        cutoff = time.time() - older_than_days * 86400
        try:
            with self._get_conn() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM route_logs WHERE timestamp < ?",
                    (cutoff,),
                ).fetchone()[0]
                conn.execute(
                    "DELETE FROM route_logs WHERE timestamp < ?",
                    (cutoff,),
                )
                if count > 0:
                    conn.execute("VACUUM")
                    logger.info(f"StatsStore: Pruned {count} old log entries")
                return count
        except Exception as e:
            logger.error(f"StatsStore: Failed to prune logs: {e}")
            return 0