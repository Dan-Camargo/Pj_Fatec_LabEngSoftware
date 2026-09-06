"""Aplica as migrações de schema da pasta migrations/ em ordem.

Uso:
    python migrate.py          # aplica as pendentes e sai
    python migrate.py status   # só mostra o que já foi/nao foi aplicado

O controle é feito pela tabela schema_migrations (versão | nome | quando),
criada sob demanda. Cada migração roda dentro de uma transação e só é
marcada como aplicada se terminar sem erro, então o deploy é seguro
mesmo no meio de uma falha.
"""
import os
import re
import sys

import psycopg2

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

DB_CONF = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "dbname": os.environ.get("PGDATABASE", "algoviz"),
    "user": os.environ.get("PGUSER", "algoviz"),
    "password": os.environ.get("PGPASSWORD", "algoviz"),
}

_sql_re = re.compile(r"(\d+)_([^.\s]+)\.sql$", re.IGNORECASE)


def _list_migrations():
    out = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        m = _sql_re.match(name)
        if m:
            out.append((int(m.group(1)), name))
    return out


def run_migrations():
    conn = psycopg2.connect(**DB_CONF)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INT PRIMARY KEY,"
                " name VARCHAR(200) NOT NULL,"
                " applied_at TIMESTAMPTZ DEFAULT now())"
            )
            conn.commit()

        migrations = _list_migrations()
        if not migrations:
            print("Nenhuma migração encontrada.")
            return None

        for version, name in migrations:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                    if cur.fetchone():
                        continue
                    path = os.path.join(MIGRATIONS_DIR, name)
                    with open(path, encoding="utf-8") as f:
                        sql = f.read()
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                        (version, name),
                    )
                conn.commit()
                print("aplicada: %s" % name)
            except psycopg2.Error as e:
                conn.rollback()
                print("FALHOU: %s\n%s" % (name, e), file=sys.stderr)
                return False
        return True
    finally:
        conn.close()


def _status():
    conn = psycopg2.connect(**DB_CONF)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INT PRIMARY KEY,"
                " name VARCHAR(200) NOT NULL,"
                " applied_at TIMESTAMPTZ DEFAULT now())"
            )
            conn.commit()
            cur.execute("SELECT version, name, applied_at FROM schema_migrations"
                        " ORDER BY version")
            for v, name, at in cur.fetchall():
                print("%3d  %-40s %s" % (v, name, at))
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        _status()
    else:
        run_migrations()