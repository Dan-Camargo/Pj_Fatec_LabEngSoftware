-- =====================================================================
-- Migração 001 — estado inicial do schema.
-- Extraído do commit 4141271 (antes das alterações de role/login).
-- =====================================================================

-- Execuções registradas pelo visualizador de algoritmos.
CREATE TABLE IF NOT EXISTS runs (
    id          SERIAL PRIMARY KEY,
    algorithm   VARCHAR(40)  NOT NULL,
    category    VARCHAR(20)  NOT NULL,
    input_size  INT          NOT NULL,
    comparisons INT DEFAULT 0,
    swaps       INT DEFAULT 0,
    elapsed_ms  NUMERIC(12,3) DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS datasets (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(80) UNIQUE NOT NULL,
    kind       VARCHAR(20) NOT NULL DEFAULT 'sort',
    payload    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Usuários do site. A senha NUNCA é salva em texto puro: guardamos só o
-- hash (PBKDF2 via werkzeug.security), então nem o banco vazado revela ela.
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(30) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Colunas opcionais que ligam cada execução/conjunto ao usuário que os criou
-- (NULL = executado por um visitante anônimo).
ALTER TABLE runs     ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id);
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id);

-- ====================== Plataforma de ensino =========================
-- Entidades do domínio: professor, aluno, agendamento, aula e tarefa.
-- Relacionamentos:
--   professor 1---N tarefa         (o professor cria as tarefas)
--   tarefa  N---N aluno           (uma tarefa vale para vários alunos)
--   aluno   1---N aula            (cada aula pertence a 1 aluno)
--   agendamento 1---N aula        (um agendamento pode conter várias aulas)
--   professor 1---N agendamento   (o professor marca vários agendamentos)
CREATE TABLE IF NOT EXISTS professor (
    id            SERIAL PRIMARY KEY,
    nome          VARCHAR(120) NOT NULL,
    email         VARCHAR(120) UNIQUE,
    telefone      VARCHAR(30),
    especialidade VARCHAR(80),
    criado_em     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aluno (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(120) NOT NULL,
    email     VARCHAR(120) UNIQUE,
    criado_em TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agendamento (
    id           SERIAL PRIMARY KEY,
    professor_id INT NOT NULL REFERENCES professor(id) ON DELETE CASCADE,
    titulo       VARCHAR(120) NOT NULL,
    descricao    TEXT,
    inicio       TIMESTAMPTZ,
    fim          TIMESTAMPTZ,
    criado_em    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS aula (
    id             SERIAL PRIMARY KEY,
    aluno_id       INT NOT NULL REFERENCES aluno(id) ON DELETE CASCADE,
    agendamento_id INT REFERENCES agendamento(id) ON DELETE SET NULL,
    conteudo       TEXT,
    status         VARCHAR(20) NOT NULL DEFAULT 'agendada',
    criado_em      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tarefa (
    id           SERIAL PRIMARY KEY,
    professor_id INT NOT NULL REFERENCES professor(id) ON DELETE CASCADE,
    titulo       VARCHAR(120) NOT NULL,
    descricao    TEXT,
    criado_em    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tarefa_aluno (
    tarefa_id INT NOT NULL REFERENCES tarefa(id) ON DELETE CASCADE,
    aluno_id  INT NOT NULL REFERENCES aluno(id) ON DELETE CASCADE,
    entregue  BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tarefa_id, aluno_id)
);