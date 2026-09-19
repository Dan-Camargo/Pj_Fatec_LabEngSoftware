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

DB_CONF = {
    "host": os.environ.get("PGHOST", "127.0.0.1"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "dbname": os.environ.get("PGDATABASE", "algoviz"),
    "user": os.environ.get("PGUSER", "algoviz"),
    "password": os.environ.get("PGPASSWORD", "algoviz"),
}

MAX_N = 200
MAX_OPS = 60000
MAX_GRID_CELLS = 30 * 50

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


# --------------------------- autenticação -----------------------------------

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


@app.post("/api/register")
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


@app.post("/api/login")
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


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def api_me():
    return jsonify(user=current_user())


class ApiError(Exception):
    """Erro de API com status HTTP próprio (401, 403, 404, ...)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class TooManyOps(Exception):
    pass


class Rec:
    """Grava a trilha de operações que o front-end reproduz como animação."""

    def __init__(self):
        self.ops = []

    def _add(self, op):
        if len(self.ops) >= MAX_OPS:
            raise TooManyOps()
        self.ops.append(op)

    def cmp(self, i, j):
        self._add({"t": "c", "a": i, "b": j})

    def swap(self, i, j):
        self._add({"t": "s", "a": i, "b": j})

    def write(self, i, v):
        self._add({"t": "w", "a": i, "v": v})

    def pivot(self, i):
        self._add({"t": "p", "a": i})

    def done(self, i):
        self._add({"t": "d", "a": i})


# ----------------------------- ordenação -----------------------------------

def bubble_sort(a, r, st):
    n = len(a)
    for end in range(n - 1, 0, -1):
        swapped = False
        for i in range(end):
            r.cmp(i, i + 1)
            st["cmp"] += 1
            if a[i] > a[i + 1]:
                a[i], a[i + 1] = a[i + 1], a[i]
                r.swap(i, i + 1)
                st["swp"] += 1
                swapped = True
        r.done(end)
        if not swapped:
            break
    r.done(0)


def insertion_sort(a, r, st):
    for i in range(1, len(a)):
        key = a[i]
        j = i - 1
        while j >= 0:
            r.cmp(j, j + 1)
            st["cmp"] += 1
            if a[j] > key:
                a[j + 1] = a[j]
                r.write(j + 1, a[j])
                st["swp"] += 1
                j -= 1
            else:
                break
        a[j + 1] = key
        r.write(j + 1, key)
        st["swp"] += 1


def selection_sort(a, r, st):
    n = len(a)
    for i in range(n - 1):
        m = i
        for j in range(i + 1, n):
            r.cmp(m, j)
            st["cmp"] += 1
            if a[j] < a[m]:
                m = j
        if m != i:
            a[i], a[m] = a[m], a[i]
            r.swap(i, m)
            st["swp"] += 1
        r.done(i)
    r.done(n - 1)


def merge_sort(a, r, st):
    tmp = [0] * len(a)

    def ms(lo, hi):
        if hi - lo < 1:
            return
        mid = (lo + hi) // 2
        ms(lo, mid)
        ms(mid + 1, hi)
        i, j, k = lo, mid + 1, lo
        while i <= mid and j <= hi:
            r.cmp(i, j)
            st["cmp"] += 1
            if a[i] <= a[j]:
                tmp[k] = a[i]
                i += 1
            else:
                tmp[k] = a[j]
                j += 1
            k += 1
        while i <= mid:
            tmp[k] = a[i]
            i += 1
            k += 1
        while j <= hi:
            tmp[k] = a[j]
            j += 1
            k += 1
        for idx in range(lo, hi + 1):
            a[idx] = tmp[idx]
            r.write(idx, tmp[idx])
            st["swp"] += 1

    ms(0, len(a) - 1)


def quick_sort(a, r, st):
    def qs(lo, hi):
        if lo > hi:
            return
        if lo == hi:
            r.done(lo)
            return
        r.pivot(hi)
        p = a[hi]
        i = lo
        for j in range(lo, hi):
            r.cmp(j, hi)
            st["cmp"] += 1
            if a[j] < p:
                if i != j:
                    a[i], a[j] = a[j], a[i]
                    r.swap(i, j)
                    st["swp"] += 1
                i += 1
        if i != hi:
            a[i], a[hi] = a[hi], a[i]
            r.swap(i, hi)
            st["swp"] += 1
        r.done(i)
        qs(lo, i - 1)
        qs(i + 1, hi)

    qs(0, len(a) - 1)


def heap_sort(a, r, st):
    n = len(a)

    def sift(i, size):
        while True:
            l, rt, big = 2 * i + 1, 2 * i + 2, i
            if l < size:
                r.cmp(l, big)
                st["cmp"] += 1
                if a[l] > a[big]:
                    big = l
            if rt < size:
                r.cmp(rt, big)
                st["cmp"] += 1
                if a[rt] > a[big]:
                    big = rt
            if big == i:
                return
            a[i], a[big] = a[big], a[i]
            r.swap(i, big)
            st["swp"] += 1
            i = big

    for i in range(n // 2 - 1, -1, -1):
        sift(i, n)
    for end in range(n - 1, 0, -1):
        a[0], a[end] = a[end], a[0]
        r.swap(0, end)
        st["swp"] += 1
        r.done(end)
        sift(0, end)
    r.done(0)


SORTS = {
    "bubble": bubble_sort,
    "insertion": insertion_sort,
    "selection": selection_sort,
    "merge": merge_sort,
    "quick": quick_sort,
    "heap": heap_sort,
}


def run_sort(algorithm, values):
    fn = SORTS.get(algorithm)
    if fn is None:
        raise ValueError("Algoritmo de ordenação desconhecido: %r" % algorithm)
    rec = Rec()
    st = {"cmp": 0, "swp": 0}
    arr = list(values)
    t0 = time.perf_counter()
    try:
        fn(arr, rec, st)
    except TooManyOps:
        raise ValueError(
            "Entrada grande demais para %s (%d operações). Reduza o tamanho."
            % (algorithm, MAX_OPS)
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if arr != sorted(values):
        raise RuntimeError("bug: vetor final não está ordenado")
    return {
        "algorithm": algorithm,
        "initial": values,
        "ops": rec.ops,
        "stats": {"comparisons": st["cmp"], "swaps": st["swp"],
                  "elapsed_ms": round(elapsed_ms, 3)},
    }


# --------------------------- busca binária ---------------------------------

def binary_search(values, target):
    rec = Rec()
    st = {"cmp": 0}
    lo, hi = 0, len(values) - 1
    found_at = -1

    class BinRec:
        pass

    ops = rec.ops
    t0 = time.perf_counter()
    while lo <= hi:
        if len(ops) >= MAX_OPS:
            raise TooManyOps()
        ops.append({"t": "r", "a": lo, "b": hi})
        mid = (lo + hi) // 2
        ops.append({"t": "m", "a": mid})
        st["cmp"] += 1
        if values[mid] == target:
            found_at = mid
            ops.append({"t": "f", "a": mid})
            break
        if values[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    if found_at < 0:
        ops.append({"t": "nf"})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "initial": values,
        "target": target,
        "found_index": found_at,
        "ops": ops,
        "stats": {"comparisons": st["cmp"], "swaps": 0,
                  "elapsed_ms": round(elapsed_ms, 3)},
    }


# ---------------------------- grafos / grade -------------------------------

def neighbors(rc, rows, cols, walls):
    r, c = rc
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in walls:
            yield nr, nc


def reconstruct(parent, start, end):
    path = []
    cur = end
    while cur is not None:
        path.append(list(cur))
        cur = parent.get(cur)
    path.reverse()
    return path if path and path[0] == list(start) else []


def solve_path(rows, cols, walls, start, end, algorithm):
    if not (0 <= start[0] < rows and 0 <= start[1] < cols):
        raise ValueError("Início fora da grade")
    if not (0 <= end[0] < rows and 0 <= end[1] < cols):
        raise ValueError("Fim fora da grade")

    wallset = {(int(r), int(c)) for r, c in walls}
    s, e = tuple(start), tuple(end)
    visited_order = []
    parent = {s: None}

    def visit(node):
        visited_order.append([node[0], node[1]])

    t0 = time.perf_counter()
    if algorithm == "bfs":
        q = deque([s])
        seen = {s}
        while q:
            cur = q.popleft()
            visit(cur)
            if cur == e:
                break
            for nb in neighbors(cur, rows, cols, wallset):
                if nb not in seen:
                    seen.add(nb)
                    parent[nb] = cur
                    q.append(nb)
    elif algorithm == "dfs":
        stack = [s]
        seen = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            visit(cur)
            if cur == e:
                break
            for nb in neighbors(cur, rows, cols, wallset):
                if nb not in seen:
                    parent.setdefault(nb, cur)
                    stack.append(nb)
    elif algorithm == "astar":

        def h(n):
            return abs(n[0] - e[0]) + abs(n[1] - e[1])

        g = {s: 0}
        pq = [(h(s), 0, s)]
        counter = 1
        while pq:
            _, _, cur = heapq.heappop(pq)
            visit(cur)
            if cur == e:
                break
            for nb in neighbors(cur, rows, cols, wallset):
                ng = g[cur] + 1
                if nb not in g or ng < g[nb]:
                    g[nb] = ng
                    parent[nb] = cur
                    heapq.heappush(pq, (ng + h(nb), counter, nb))
                    counter += 1
    else:
        raise ValueError("Algoritmo de caminho desconhecido: %r" % algorithm)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    path = reconstruct(parent, s, e)
    return {
        "visited": visited_order,
        "path": path,
        "stats": {"comparisons": len(visited_order), "swaps": len(path),
                  "elapsed_ms": round(elapsed_ms, 3)},
    }


# ------------------------------ metadados ----------------------------------

META = {
    "sorting": [
        {"id": "bubble", "name": "Bubble Sort",
         "best": "O(n)", "avg": "O(n²)", "worst": "O(n²)", "space": "O(1)",
         "desc": "Compara pares adjacentes e troca quando estão fora de ordem; o maior 'flutua' para o fim a cada passada."},
        {"id": "insertion", "name": "Insertion Sort",
         "best": "O(n)", "avg": "O(n²)", "worst": "O(n²)", "space": "O(1)",
         "desc": "Insere cada elemento na posição correta dentro do prefixo já ordenado, como ao organizar cartas na mão."},
        {"id": "selection", "name": "Selection Sort",
         "best": "O(n²)", "avg": "O(n²)", "worst": "O(n²)", "space": "O(1)",
         "desc": "Seleciona o menor elemento do trecho não ordenado e o coloca no início; faz poucas trocas."},
        {"id": "merge", "name": "Merge Sort",
         "best": "O(n log n)", "avg": "O(n log n)", "worst": "O(n log n)", "space": "O(n)",
         "desc": "Divide e conquista: divide ao meio, ordena cada metade e intercala (merge) as soluções."},
        {"id": "quick", "name": "Quick Sort",
         "best": "O(n log n)", "avg": "O(n log n)", "worst": "O(n²)", "space": "O(log n)",
         "desc": "Escolhe um pivô, particiona em menores/maiores e repete recursivamente nas duas partes."},
        {"id": "heap", "name": "Heap Sort",
         "best": "O(n log n)", "avg": "O(n log n)", "worst": "O(n log n)", "space": "O(1)",
         "desc": "Constrói um max-heap no próprio vetor e extrai o maior elemento repetidamente."},
    ],
    "search": [
        {"id": "binary", "name": "Busca Binária",
         "best": "O(1)", "avg": "O(log n)", "worst": "O(log n)", "space": "O(1)",
         "desc": "Em vetor ordenado, compara com o meio e descarta metade do intervalo a cada passo."},
    ],
    "path": [
        {"id": "bfs", "name": "BFS (largura)",
         "avg": "O(V+E)", "worst": "O(V+E)", "space": "O(V)",
         "desc": "Explora em camadas usando fila; garante o caminho mais curto em grafos sem peso."},
        {"id": "dfs", "name": "DFS (profundidade)",
         "avg": "O(V+E)", "worst": "O(V+E)", "space": "O(V)",
         "desc": "Mergulha o mais fundo possível com pilha antes de retroceder (backtracking); não garante menor caminho."},
        {"id": "astar", "name": "A*",
         "avg": "O(E)", "worst": "O(V·E)", "space": "O(V)",
         "desc": "Busca informada guiada por heurística (distância de Manhattan); foca a exploração rumo ao destino."},
    ],
}


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


@app.get("/api/meta")
def api_meta():
    return jsonify(META)


@app.post("/api/sort")
def api_sort():
    data = request.get_json(force=True, silent=True) or {}
    algorithm = str(data.get("algorithm", ""))
    values = data.get("values")
    if not isinstance(values, list):
        return jsonify(error="Envie 'values' como lista."), 400
    if not values or len(values) > MAX_N:
        return jsonify(error="A lista deve ter entre 1 e %d elementos." % MAX_N), 400
    clean = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int):
            return jsonify(error="Todos os valores devem ser inteiros."), 400
        clean.append(v)
    try:
        result = run_sort(algorithm, clean)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(result)


@app.post("/api/search")
def api_search():
    data = request.get_json(force=True, silent=True) or {}
    values = data.get("values")
    target = data.get("target")
    if not isinstance(values, list) or not values or len(values) > MAX_N:
        return jsonify(error="Lista inválida (1..%d itens)." % MAX_N), 400
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        return jsonify(error="Todos os valores devem ser inteiros."), 400
    if values != sorted(values):
        return jsonify(error="A busca binária exige lista ordenada."), 400
    if isinstance(target, bool) or not isinstance(target, int):
        return jsonify(error="'target' deve ser inteiro."), 400
    try:
        return jsonify(binary_search(values, target))
    except TooManyOps:
        return jsonify(error="Demasiadas operações."), 400


@app.post("/api/path")
def api_path():
    data = request.get_json(force=True, silent=True) or {}
    try:
        rows = int(data["rows"])
        cols = int(data["cols"])
    except Exception:
        return jsonify(error="rows/cols obrigatórios."), 400
    if not (1 <= rows <= 30 and 1 <= cols <= 50) or rows * cols > MAX_GRID_CELLS:
        return jsonify(error="Grade muito grande."), 400
    walls = data.get("walls") or []
    start, end = data.get("start"), data.get("end")
    if not isinstance(start, list) or len(start) != 2 or \
       not isinstance(end, list) or len(end) != 2:
        return jsonify(error="start/end devem ser [linha, coluna]."), 400
    try:
        result = solve_path(rows, cols, walls, start, end,
                            str(data.get("algorithm", "")))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(result)


@app.post("/api/runs")
def api_save_run():
    data = request.get_json(force=True, silent=True) or {}
    algorithm = str(data.get("algorithm", ""))[:40]
    category = str(data.get("category", ""))[:20]

    def as_int(key, default=0):
        v = data.get(key, default)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return default
        return int(v)

    def as_num(key, default=0.0):
        v = data.get(key, default)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return float(default)
        return float(v)

    if not algorithm or category not in ("sorting", "search", "path"):
        return jsonify(error="Registro incompleto."), 400
    user = current_user()  # pode ser None (visitante anônimo)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs (algorithm, category, input_size, comparisons,"
            " swaps, elapsed_ms, user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " RETURNING id",
            (algorithm, category, as_int("input_size"), as_int("comparisons"),
             as_int("swaps"), as_num("elapsed_ms"),
             user["id"] if user else None),
        )
        rid = cur.fetchone()[0]
    return jsonify(id=rid), 201


@app.get("/api/runs")
def api_list_runs():
    try:
        limit = min(max(int(request.args.get("limit", 25)), 1), 200)
    except ValueError:
        limit = 25
    # ?mine=1 filtra apenas as execuções do usuário logado
    mine = request.args.get("mine") == "1"
    user = current_user()
    if mine and user is None:
        return jsonify(error="Faça login para ver suas execuções."), 401

    sql = ("SELECT r.id, r.algorithm, r.category, r.input_size, r.comparisons,"
           " r.swaps, r.elapsed_ms, r.created_at,"
           " coalesce(u.username, 'visitante')"
           " FROM runs r LEFT JOIN users u ON u.id = r.user_id")
    params = []
    if mine:
        sql += " WHERE r.user_id = %s"
        params.append(user["id"])
    sql += " ORDER BY r.id DESC LIMIT %s"
    params.append(limit)

    with db() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out = [{"id": r[0], "algorithm": r[1], "category": r[2],
            "input_size": r[3], "comparisons": r[4], "swaps": r[5],
            "elapsed_ms": float(r[6]), "created_at": r[7].isoformat(),
            "user": r[8]}
           for r in rows]
    return jsonify(out)


@app.get("/api/stats")
def api_stats():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), coalesce(sum(input_size),0) FROM runs")
        total, total_items = cur.fetchone()
        cur.execute(
            "SELECT algorithm, category, count(*) AS execucoes,"
            " round(avg(input_size)) AS n_medio,"
            " round(avg(comparisons)) AS cmp_medio,"
            " round(avg(swaps)) AS swp_medio,"
            " round(avg(elapsed_ms)::numeric, 3) AS ms_medio"
            " FROM runs GROUP BY algorithm, category"
            " ORDER BY category, algorithm")
        by_algo = [dict(zip(
            ["algorithm", "category", "runs", "n_avg", "cmp_avg",
             "swp_avg", "ms_avg"], r)) for r in cur.fetchall()]
    return jsonify(total_runs=total, total_items=total_items,
                   by_algorithm=by_algo)


@app.post("/api/datasets")
def api_save_dataset():
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name", "")).strip()
    values = data.get("values")
    kind = str(data.get("kind", "sort"))
    if not (1 <= len(name) <= 80):
        return jsonify(error="Nome deve ter 1..80 caracteres."), 400
    if not isinstance(values, list) or not values or len(values) > MAX_N:
        return jsonify(error="Valores inválidos."), 400
    if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
        return jsonify(error="Somente inteiros."), 400
    if kind not in ("sort", "search"):
        kind = "sort"
    payload = ",".join(map(str, values))
    user = current_user()
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO datasets (name, kind, payload, user_id)"
                " VALUES (%s,%s,%s,%s) RETURNING id",
                (name, kind, payload, user["id"] if user else None))
            did = cur.fetchone()[0]
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="Já existe um conjunto com esse nome."), 409
    return jsonify(id=did), 201


@app.get("/api/datasets")
def api_list_datasets():
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.id, d.name, d.kind, d.payload, d.created_at,"
            " coalesce(u.username, 'visitante')"
            " FROM datasets d LEFT JOIN users u ON u.id = d.user_id"
            " ORDER BY d.id DESC LIMIT 100")
        rows = cur.fetchall()
    out = [{"id": r[0], "name": r[1], "kind": r[2],
            "values": [int(x) for x in r[3].split(",")],
            "created_at": r[4].isoformat(), "owner": r[5]} for r in rows]
    return jsonify(out)


@app.delete("/api/datasets/<int:did>")
def api_delete_dataset(did):
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM datasets WHERE id=%s", (did,))
        deleted = cur.rowcount
    if not deleted:
        return jsonify(error="Conjunto não encontrado."), 404
    return jsonify(ok=True)


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


@app.get("/api/posts")
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


@app.post("/api/posts")
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


@app.get("/api/posts/<int:pid>")
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


@app.put("/api/posts/<int:pid>")
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


@app.delete("/api/posts/<int:pid>")
def api_delete_post(pid):
    require_admin()
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM posts WHERE id=%s", (pid,))
        if cur.rowcount == 0:
            raise ApiError("Post não encontrado.", 404)
    return jsonify(ok=True)


@app.post("/api/posts/<int:pid>/comments")
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


@app.delete("/api/posts/<int:pid>/comments/<int:cid>")
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


@app.post("/api/posts/<int:pid>/like")
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


# ------------------------------ gestão de admins -------------------------


@app.get("/api/admins")
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


@app.get("/api/users")
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


@app.post("/api/admins")
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


@app.delete("/api/admins/<int:uid>")
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
