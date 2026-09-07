-- =====================================================================
-- Migração 002 — alterações da Letícia (05092026).
-- Vincula cada professor a um usuário de login com papel (role).
-- Em bancos já existentes, adiciona as colunas sem apagar dados:
--   users.role       -> papel do usuário ('Aluno' para quem já existe)
--   professor.login_id -> FK para users(id) usado pelo login do professor
-- =====================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(255) NOT NULL DEFAULT 'Aluno';
ALTER TABLE professor ADD COLUMN IF NOT EXISTS login_id INT REFERENCES users(id);