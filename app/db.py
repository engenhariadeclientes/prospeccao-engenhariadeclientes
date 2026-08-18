"""Conexão com o Postgres e aplicação do schema no startup."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def get_connection() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def aplicar_schema() -> None:
    with get_connection() as conn:
        for arquivo in sorted(SQL_DIR.glob("*.sql")):
            conn.execute(arquivo.read_text(encoding="utf-8"))
        conn.commit()
