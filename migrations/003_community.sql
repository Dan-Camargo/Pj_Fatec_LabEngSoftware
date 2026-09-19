-- =====================================================================
-- Migração 003 — comunidade (feed/blog).
-- Posts escritos por administradores; usuários logados comentam e
-- curtem. Likes são toggle: PK (post_id, user_id).
-- =====================================================================

CREATE TABLE IF NOT EXISTS posts (
    id          SERIAL PRIMARY KEY,
    author_id   INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(120) NOT NULL,
    body        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comments (
    id         SERIAL PRIMARY KEY,
    post_id    INT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id  INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS post_likes (
    post_id    INT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);