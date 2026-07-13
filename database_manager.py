"""SQLite persistence layer for CARE cloud server metrics."""

from __future__ import annotations

import random
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Final, Iterator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_DIR: Final[Path] = Path(__file__).resolve().parent / "database"
DATABASE_PATH: Final[Path] = DATABASE_DIR / "care.db"

SERVER_COUNT: Final[int] = 10
SERVER_ID_PREFIX: Final[str] = "SRV"

CPU_WARNING: Final[float] = 75.0
CPU_FAULTY: Final[float] = 90.0
RAM_WARNING: Final[float] = 80.0
RAM_FAULTY: Final[float] = 92.0
DISK_WARNING: Final[float] = 85.0
DISK_FAULTY: Final[float] = 95.0

CREATE_TABLE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS cloud_servers (
    server_id TEXT PRIMARY KEY,
    cpu_usage REAL NOT NULL,
    ram_usage REAL NOT NULL,
    disk_usage REAL NOT NULL,
    network_usage REAL NOT NULL,
    running_vms INTEGER NOT NULL,
    active_tasks INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_updated TEXT NOT NULL
);
"""


class ServerStatus(str, Enum):
    HEALTHY = "Healthy"
    WARNING = "Warning"
    FAULTY = "Faulty"


@dataclass(frozen=True)
class CloudServer:
    server_id: str
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    network_usage: float
    running_vms: int
    active_tasks: int
    status: ServerStatus
    last_updated: datetime


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row factory enabled."""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Domain logic
# ---------------------------------------------------------------------------


def derive_status(cpu: float, ram: float, disk: float) -> ServerStatus:
    """Classify server health from resource utilization."""
    if cpu >= CPU_FAULTY or ram >= RAM_FAULTY or disk >= DISK_FAULTY:
        return ServerStatus.FAULTY
    if cpu >= CPU_WARNING or ram >= RAM_WARNING or disk >= DISK_WARNING:
        return ServerStatus.WARNING
    return ServerStatus.HEALTHY


def _generate_server_metrics(server_index: int) -> dict[str, object]:
    """Build a single server metric payload for insert/update."""
    cpu = round(random.uniform(12, 98), 1)
    ram = round(random.uniform(18, 97), 1)
    disk = round(random.uniform(25, 99), 1)
    network = round(random.uniform(5, 950), 1)
    status = derive_status(cpu, ram, disk)

    return {
        "server_id": f"{SERVER_ID_PREFIX}-{server_index:03d}",
        "cpu_usage": cpu,
        "ram_usage": ram,
        "disk_usage": disk,
        "network_usage": network,
        "running_vms": random.randint(1, 12),
        "active_tasks": random.randint(0, 48),
        "status": status.value,
        "last_updated": _utc_now_iso(),
    }


def _row_to_cloud_server(row: sqlite3.Row) -> CloudServer:
    return CloudServer(
        server_id=row["server_id"],
        cpu_usage=float(row["cpu_usage"]),
        ram_usage=float(row["ram_usage"]),
        disk_usage=float(row["disk_usage"]),
        network_usage=float(row["network_usage"]),
        running_vms=int(row["running_vms"]),
        active_tasks=int(row["active_tasks"]),
        status=ServerStatus(row["status"]),
        last_updated=_parse_timestamp(row["last_updated"]),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def initialize_database() -> None:
    """Create database file, schema, and seed data on first run."""
    with get_connection() as connection:
        connection.execute(CREATE_TABLE_SQL)
        row_count = connection.execute("SELECT COUNT(*) FROM cloud_servers").fetchone()[0]
        if row_count == 0:
            _seed_sample_servers(connection)


def _seed_sample_servers(connection: sqlite3.Connection) -> None:
    """Insert initial sample servers when the table is empty."""
    insert_sql = """
        INSERT INTO cloud_servers (
            server_id,
            cpu_usage,
            ram_usage,
            disk_usage,
            network_usage,
            running_vms,
            active_tasks,
            status,
            last_updated
        ) VALUES (
            :server_id,
            :cpu_usage,
            :ram_usage,
            :disk_usage,
            :network_usage,
            :running_vms,
            :active_tasks,
            :status,
            :last_updated
        );
    """
    for index in range(1, SERVER_COUNT + 1):
        connection.execute(insert_sql, _generate_server_metrics(index))


def fetch_all_servers() -> list[CloudServer]:
    """Return all cloud servers ordered by server ID."""
    initialize_database()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM cloud_servers ORDER BY server_id ASC;"
        ).fetchall()
    return [_row_to_cloud_server(row) for row in rows]


def refresh_server_metrics() -> None:
    """Regenerate simulated metrics for every server in the database."""
    initialize_database()
    update_sql = """
        UPDATE cloud_servers
        SET
            cpu_usage = :cpu_usage,
            ram_usage = :ram_usage,
            disk_usage = :disk_usage,
            network_usage = :network_usage,
            running_vms = :running_vms,
            active_tasks = :active_tasks,
            status = :status,
            last_updated = :last_updated
        WHERE server_id = :server_id;
    """
    with get_connection() as connection:
        server_ids = connection.execute(
            "SELECT server_id FROM cloud_servers ORDER BY server_id ASC;"
        ).fetchall()
        for index, row in enumerate(server_ids, start=1):
            metrics = _generate_server_metrics(index)
            metrics["server_id"] = row["server_id"]
            connection.execute(update_sql, metrics)
