"""Camada de acesso ao banco — passo 1 da modularização.

Centraliza o que era o topo do app.py monolito (DB_CONF + db() +
current_user()) para que auth/visualizacao/comunidade importem de um
lugar só. Nenhuma regra de negócio mudou aqui.
"""

import os

import psycopg2
from flask import session

DB_CONF = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "dbname": os.environ.get("PGDATABASE", "algoviz"),
    "user": os.environ.get("PGUSER", "algoviz"),
    "password": os.environ.get("PGPASSWORD", "algoviz"),
}


def db():
    return psycopg2.connect(**DB_CONF)


def current_user():
    """Devolve {id, username, role} de quem está logado na sessão, ou None.

    O cookie do navegador guarda apenas o id assinado pelo Flask; aqui
    conferimos se esse usuário ainda existe no banco.
    """
    uid = session.get("uid")
    if not uid:
        return None
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, username, role FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "role": row[2] or "Aluno"}
