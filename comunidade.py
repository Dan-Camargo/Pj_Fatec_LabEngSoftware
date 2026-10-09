"""Comunidade / feed — passo 3 da modularização.

Feed de posts (só Admin publica), comentários e likes (qualquer logado),
movido do app.py monolito sem mudar 1 comportamento: mesmos paths,
métodos, mensagens e status. Plugado com
app.register_blueprint(comunidade_bp).
"""

from flask import Blueprint, jsonify, request

from auth import ApiError, require_admin, require_login
from db import db

comunidade_bp = Blueprint("comunidade", __name__)


# --------------------------- comunidade / feed ----------------------------

MAX_POST_BODY = 5000
MAX_COMMENT_BODY = 1000


def _post_row(cur, pid, uid):
    """Monta um dict de post com curtidas/comentários e liked_by_me."""
    cur.execute(
        "SELECT p.id, p.title, p.body, p.created_at, p.updated_at,"
        " u.id, u.username,"
        " (SELECT count(*) FROM post_likes l WHERE l.post_id = p.id),"
        " (SELECT count(*) FROM comments c WHERE c.post_id = p.id),"
        " EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id = p.id"
        "        AND l.user_id = %s)"
        " FROM posts p JOIN users u ON u.id = p.author_id"
        " WHERE p.id = %s",
        (uid, pid),
    )
    row = cur.fetchone()
    if row is None:
        raise ApiError("Post não encontrado.", 404)
    return {
        "id": row[0], "title": row[1], "body": row[2],
        "created_at": row[3].isoformat(), "updated_at": row[4].isoformat(),
        "author": {"id": row[5], "username": row[6]},
        "like_count": row[7], "comment_count": row[8], "liked_by_me": row[9],
    }


@comunidade_bp.get("/api/posts")
def api_list_posts():
    user = require_login()
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.title, left(p.body, 200), p.created_at,"
            " u.id, u.username,"
            " (SELECT count(*) FROM post_likes l WHERE l.post_id = p.id),"
            " (SELECT count(*) FROM comments c WHERE c.post_id = p.id),"
            " EXISTS(SELECT 1 FROM post_likes l WHERE l.post_id = p.id"
            "        AND l.user_id = %s)"
            " FROM posts p JOIN users u ON u.id = p.author_id"
            " ORDER BY p.id DESC LIMIT %s",
            (user["id"], limit),
        )
        rows = cur.fetchall()
    out = [{"id": r[0], "title": r[1], "excerpt": r[2],
            "created_at": r[3].isoformat(),
            "author": {"id": r[4], "username": r[5]},
            "like_count": r[6], "comment_count": r[7],
            "liked_by_me": r[8]} for r in rows]
    return jsonify(posts=out)


@comunidade_bp.post("/api/posts")
def api_create_post():
    admin = require_admin()
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (1 <= len(title) <= 120):
        raise ValueError("Título deve ter de 1 a 120 caracteres.")
    if not (1 <= len(body) <= MAX_POST_BODY):
        raise ValueError("Conteúdo deve ter de 1 a %d caracteres." % MAX_POST_BODY)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posts (author_id, title, body) VALUES (%s,%s,%s)"
            " RETURNING id",
            (admin["id"], title, body),
        )
        pid = cur.fetchone()[0]
    return jsonify(id=pid), 201


@comunidade_bp.get("/api/posts/<int:pid>")
def api_get_post(pid):
    user = require_login()
    with db() as conn, conn.cursor() as cur:
        post = _post_row(cur, pid, user["id"])
        cur.execute(
            "SELECT c.id, c.body, c.created_at, u.id, u.username"
            " FROM comments c JOIN users u ON u.id = c.author_id"
            " WHERE c.post_id = %s ORDER BY c.id ASC",
            (pid,),
        )
        comments = [{"id": r[0], "body": r[1], "created_at": r[2].isoformat(),
                     "author": {"id": r[3], "username": r[4]}} for r in cur.fetchall()]
    post["comments"] = comments
    return jsonify(post)


@comunidade_bp.put("/api/posts/<int:pid>")
def api_update_post(pid):
    require_admin()
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (1 <= len(title) <= 120):
        raise ValueError("Título deve ter de 1 a 120 caracteres.")
    if not (1 <= len(body) <= MAX_POST_BODY):
        raise ValueError("Conteúdo deve ter de 1 a %d caracteres." % MAX_POST_BODY)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE posts SET title=%s, body=%s, updated_at=now() WHERE id=%s",
            (title, body, pid),
        )
        if cur.rowcount == 0:
            raise ApiError("Post não encontrado.", 404)
    return jsonify(ok=True)


@comunidade_bp.delete("/api/posts/<int:pid>")
def api_delete_post(pid):
    require_admin()
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM posts WHERE id=%s", (pid,))
        if cur.rowcount == 0:
            raise ApiError("Post não encontrado.", 404)
    return jsonify(ok=True)


@comunidade_bp.post("/api/posts/<int:pid>/comments")
def api_add_comment(pid):
    user = require_login()
    data = request.get_json(force=True, silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not (1 <= len(body) <= MAX_COMMENT_BODY):
        raise ValueError("Comentário deve ter de 1 a %d caracteres." % MAX_COMMENT_BODY)
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM posts WHERE id=%s", (pid,))
        if cur.fetchone() is None:
            raise ApiError("Post não encontrado.", 404)
        cur.execute(
            "INSERT INTO comments (post_id, author_id, body) VALUES (%s,%s,%s)"
            " RETURNING id",
            (pid, user["id"], body),
        )
        cid = cur.fetchone()[0]
    return jsonify(id=cid), 201


@comunidade_bp.delete("/api/posts/<int:pid>/comments/<int:cid>")
def api_delete_comment(pid, cid):
    user = require_login()
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT author_id FROM comments WHERE id=%s AND post_id=%s",
            (cid, pid),
        )
        row = cur.fetchone()
        if row is None:
            raise ApiError("Comentário não encontrado.", 404)
        if row[0] != user["id"] and user["role"] != "Admin":
            raise ApiError("Você não pode remover esse comentário.", 403)
        cur.execute("DELETE FROM comments WHERE id=%s", (cid,))
    return jsonify(ok=True)


@comunidade_bp.post("/api/posts/<int:pid>/like")
def api_toggle_like(pid):
    user = require_login()
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM posts WHERE id=%s", (pid,))
        if cur.fetchone() is None:
            raise ApiError("Post não encontrado.", 404)
        cur.execute(
            "DELETE FROM post_likes WHERE post_id=%s AND user_id=%s",
            (pid, user["id"]),
        )
        if cur.rowcount:
            liked = False
        else:
            cur.execute(
                "INSERT INTO post_likes (post_id, user_id) VALUES (%s,%s)",
                (pid, user["id"]),
            )
            liked = True
        cur.execute("SELECT count(*) FROM post_likes WHERE post_id=%s", (pid,))
        count = cur.fetchone()[0]
    return jsonify(liked=liked, like_count=count)
