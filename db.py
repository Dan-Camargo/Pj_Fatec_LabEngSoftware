"""Conexão com o PostgreSQL — compartilhada por app.py e pelos módulos/bps."""
import os

import psycopg2

DB_CONF = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "dbname": os.environ.get("PGDATABASE", "algoviz"),
    "user": os.environ.get("PGUSER", "algoviz"),
    "password": os.environ.get("PGPASSWORD", "algoviz"),
}


def db():
    """Abre uma conexão nova com o banco (o chamador fecha com 'with')."""
    return psycopg2.connect(**DB_CONF)