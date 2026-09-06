"""CRUD de alunos — Blueprint Flask.

Mesmos campos do CRUD de professores, acrescido do RA (Registro Acadêmico),
que é único. Rotas registradas em app.register_blueprint(alunos_bp).
"""
import re

import psycopg2
from flask import Blueprint, jsonify, request

from db import db

alunos_bp = Blueprint("alunos", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _str(v):
    return str(v).strip()


def _parse_aluno(data):
    """Valida e normaliza os campos de um aluno vindo do front-end."""
    ra = _str(data.get("ra", ""))
    nome = _str(data.get("nome", ""))
    email = _str(data.get("email") or "")
    telefone = _str(data.get("telefone") or "")
    especialidade = _str(data.get("especialidade") or "")
    if not (1 <= len(ra) <= 30):
        raise ValueError("RA deve ter de 1 a 30 caracteres.")
    if not (1 <= len(nome) <= 120):
        raise ValueError("Nome deve ter de 1 a 120 caracteres.")
    if email and (len(email) > 120 or not EMAIL_RE.fullmatch(email)):
        raise ValueError("E-mail inválido.")
    if len(telefone) > 30:
        raise ValueError("Telefone deve ter no máximo 30 caracteres.")
    if len(especialidade) > 80:
        raise ValueError("Especialidade deve ter no máximo 80 caracteres.")
    return ra, nome, email or None, telefone or None, especialidade or None


@alunos_bp.get("/api/alunos")
def api_list_alunos():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, ra, nome, email, telefone, especialidade, criado_em"
            " FROM aluno ORDER BY nome")
        rows = cur.fetchall()
    out = [{"id": r[0], "ra": r[1], "nome": r[2], "email": r[3],
            "telefone": r[4], "especialidade": r[5],
            "criado_em": r[6].isoformat()} for r in rows]
    return jsonify(out)


@alunos_bp.post("/api/alunos")
def api_create_aluno():
    data = request.get_json(force=True, silent=True) or {}
    try:
        ra, nome, email, telefone, especialidade = _parse_aluno(data)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO aluno (ra, nome, email, telefone, especialidade)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (ra, nome, email, telefone, especialidade))
            aid = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Já existe um aluno com esse RA ou e-mail."), 409
    return jsonify(id=aid, nome=nome), 201


@alunos_bp.put("/api/alunos/<int:aid>")
def api_update_aluno(aid):
    data = request.get_json(force=True, silent=True) or {}
    try:
        ra, nome, email, telefone, especialidade = _parse_aluno(data)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE aluno SET ra=%s, nome=%s, email=%s, telefone=%s,"
                " especialidade=%s WHERE id=%s",
                (ra, nome, email, telefone, especialidade, aid))
            if cur.rowcount == 0:
                return jsonify(error="Aluno não encontrado."), 404
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Já existe um aluno com esse RA ou e-mail."), 409
    return jsonify(ok=True)


@alunos_bp.delete("/api/alunos/<int:aid>")
def api_delete_aluno(aid):
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM aluno WHERE id=%s", (aid,))
        if cur.rowcount == 0:
            return jsonify(error="Aluno não encontrado."), 404
    return jsonify(ok=True)