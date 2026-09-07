import os
import re
import psycopg2
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash

auth_bp = Blueprint("tela_login", __name__)

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,30}")

_db_handler = None


def set_db_handler(fn):
    global _db_handler
    _db_handler = fn


def get_db():
    if _db_handler is not None:
        return _db_handler()
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "algoviz"),
        user=os.environ.get("PGUSER", "algoviz"),
        password=os.environ.get("PGPASSWORD", "algoviz"),
    )


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, role FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
    return {"id": row[0], "username": row[1], "email": row[2],
            "role": row[3]} if row else None


@auth_bp.post("/api/login")
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return jsonify(error="Informe usuário e senha."), 400
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, email, password_hash, role FROM users WHERE username = %s",
            (username,))
        row = cur.fetchone()
    if row is None or not check_password_hash(row[3], password):
        return jsonify(error="Usuário ou senha incorretos."), 401
    session.clear()
    session["uid"] = row[0]
    return jsonify(id=row[0], username=row[1], email=row[2], role=row[4])


@auth_bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@auth_bp.get("/api/me")
def api_me():
    return jsonify(user=current_user())
