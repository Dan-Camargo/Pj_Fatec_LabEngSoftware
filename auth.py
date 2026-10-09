"""Autenticação e papéis — passo 2 da modularização.

Tudo que é "quem entra / quem é admin", movido do app.py monolito sem
mudar 1 comportamento: mesmos paths, métodos, mensagens e status.
Plugado no app fino com app.register_blueprint(auth_bp).
"""

import re

import psycopg2
from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from db import current_user, db

auth_bp = Blueprint("auth", __name__)


class ApiError(Exception):
    """Erro de API com status HTTP próprio (401, 403, 404, ...)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,30}")


def _validate_credentials(username, password):
    """Valida usuário/senha; levanta ValueError com mensagem amigável."""
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Usuário: 3 a 30 caracteres (letras, números e _).")
    if not 4 <= len(password) <= 100:
        raise ValueError("A senha deve ter entre 4 e 100 caracteres.")


def _insert_user(username, password, role="Aluno"):
    """Valida credenciais e insere usuário com o papel informado.

    Devolve o id criado e NÃO mexe na sessão — quem decide logar é a rota.
    """
    _validate_credentials(username, password)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)"
            " RETURNING id",
            (username, generate_password_hash(password), role),
        )
        return cur.fetchone()[0]


def require_login():
    user = current_user()
    if user is None:
        raise ApiError("Faça login para continuar.", 401)
    return user


def require_admin():
    user = require_login()
    if user["role"] != "Admin":
        raise ApiError("Acesso restrito aos administradores.", 403)
    return user


@auth_bp.post("/api/register")
def api_register():
    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    try:
        uid = _insert_user(username, password)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Esse nome de usuário já está em uso."), 409
    session.clear()
    session["uid"] = uid
    return jsonify(id=uid, username=username, role="Aluno"), 201


@auth_bp.post("/api/login")
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, password_hash, role FROM users WHERE username=%s",
                    (username,))
        row = cur.fetchone()
    # Mensagem genérica: não revelamos se o usuário existe ou se a senha falhou
    if row is None or not check_password_hash(row[1], password):
        return jsonify(error="Usuário ou senha incorretos."), 401
    session.clear()
    session["uid"] = row[0]
    return jsonify(id=row[0], username=username,
                   role=(row[2] or "Aluno"))


@auth_bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@auth_bp.get("/api/me")
def api_me():
    return jsonify(user=current_user())


# ------------------------------ gestão de admins -------------------------
# São regras sobre papéis, não sobre posts — por isso moram aqui, e não
# na comunidade.


@auth_bp.get("/api/admins")
def api_list_admins():
    require_admin()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, created_at FROM users"
            " WHERE role = 'Admin' ORDER BY username")
        rows = cur.fetchall()
    return jsonify(admins=[
        {"id": r[0], "username": r[1], "created_at": r[2].isoformat()}
        for r in rows])


@auth_bp.get("/api/users")
def api_search_users():
    require_admin()
    q = str(request.args.get("q", "")).strip()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, role FROM users"
            " WHERE username ILIKE %s ORDER BY username LIMIT 20",
            ("%" + q + "%",),
        )
        rows = cur.fetchall()
    return jsonify(users=[
        {"id": r[0], "username": r[1], "role": r[2] or "Aluno"} for r in rows])


@auth_bp.post("/api/admins")
def api_create_admin():
    require_admin()
    data = request.get_json(force=True, silent=True) or {}

    user_id = data.get("user_id")
    if user_id is not None:
        # Promove um usuário já existente a Admin.
        if isinstance(user_id, bool):
            raise ValueError("user_id inválido.")
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            raise ValueError("user_id inválido.")
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT username, role FROM users WHERE id=%s", (uid,))
            row = cur.fetchone()
            if row is None:
                raise ApiError("Usuário não encontrado.", 404)
            if row[1] == "Admin":
                return jsonify(error="%s já é administrador." % row[0]), 409
            cur.execute("UPDATE users SET role='Admin' WHERE id=%s", (uid,))
        return jsonify(id=uid, username=row[0], role="Admin"), 201

    # Cria uma conta nova de administrador do zero.
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    try:
        uid = _insert_user(username, password, "Admin")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Esse nome de usuário já está em uso."), 409
    return jsonify(id=uid, username=username, role="Admin"), 201


@auth_bp.delete("/api/admins/<int:uid>")
def api_demote_admin(uid):
    admin = require_admin()
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT username FROM users WHERE id=%s AND role='Admin'",
                    (uid,))
        row = cur.fetchone()
        if row is None:
            raise ApiError("Administrador não encontrado.", 404)
        if uid == admin["id"]:
            raise ApiError("Você não pode remover seu próprio acesso de admin.", 400)
        if row[0] == "algoviz":
            raise ApiError("O admin raiz 'algoviz' não pode ser rebaixado.", 400)
        cur.execute("SELECT count(*) FROM users WHERE role='Admin'")
        if cur.fetchone()[0] <= 1:
            raise ApiError("Não é possível remover o último administrador.", 400)
        cur.execute("UPDATE users SET role='Aluno' WHERE id=%s", (uid,))
    return jsonify(ok=True)
