import os
import re
import time
import heapq
import secrets
from collections import deque

import psycopg2
from flask import Flask, request, jsonify, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

from migrate import run_migrations

from algoviz.auth import ApiError, auth_bp, require_admin, require_login
from algoviz.comunidade import comunidade_bp
from algoviz.db import DB_CONF, current_user, db
from algoviz.visualizacao import viz_bp

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Chave que o Flask usa para assinar o cookie de sessão. Gerada uma única vez
# e guardada em arquivo para que os logins sobrevivam a reinícios do serviço.
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")


def _load_secret_key():
    if os.environ.get("FLASK_SECRET"):
        return os.environ["FLASK_SECRET"]
    try:
        with open(_KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        with open(_KEY_FILE, "w") as f:
            f.write(key)
        os.chmod(_KEY_FILE, 0o600)  # só o dono do arquivo pode ler
        return key


app.secret_key = _load_secret_key()
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

app.register_blueprint(auth_bp)
app.register_blueprint(comunidade_bp)
app.register_blueprint(viz_bp)


# -------------------------------- rotas ------------------------------------

@app.errorhandler(ValueError)
def on_value_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(ApiError)
def on_api_error(e):
    return jsonify(error=str(e)), e.status


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# Aplica as migrações pendentes (001_initial, 002_leticia_roles, ...) antes de
# servir. Também funciona como passo separado do deploy: python migrate.py
run_migrations()

# "algoviz" é o admin raiz: criado se não existir e sempre garantido com
# papel de Admin (idempotente mesmo quando a conta foi criada como Aluno).
with db() as _conn, _conn.cursor() as _cur:
    _cur.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'Admin')"
        " ON CONFLICT (username) DO UPDATE SET role = 'Admin'",
        ("algoviz", generate_password_hash("algoviz")),
    )

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "8000"))
    serve(app, host="0.0.0.0", port=port, threads=4)
