"""RailETA Phase 1 — SQLite connection helper."""
import sqlite3
from pathlib import Path
from .models import SCHEMA_SQL

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "railway.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


if __name__ == "__main__":
    conn = get_connection()
    init_schema(conn)
    print(f"Schema initialized at {DB_PATH}")
    conn.close()
