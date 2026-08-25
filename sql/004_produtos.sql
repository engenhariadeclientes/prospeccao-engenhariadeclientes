CREATE TABLE IF NOT EXISTS produtos (
  id          SERIAL PRIMARY KEY,
  nome        TEXT NOT NULL UNIQUE,
  criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- "Empresa Inteligente" foi removido dessa lista em 25/08/2026: a migration 012
-- renomeia esse produto pra "Empresa Inteligente - DNA IA", e reinseri-lo aqui a
-- cada startup recriaria o nome antigo e quebraria a constraint de nome único.
INSERT INTO produtos (nome) VALUES
  ('Formação Geração IA'),
  ('Formação Lecionando na Geração IA'),
  ('Tráfego Pago'),
  ('Método EP')
ON CONFLICT (nome) DO NOTHING;

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS produto_id INTEGER REFERENCES produtos(id);
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS valor_orcamento NUMERIC(12,2);
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS previsao_fechamento DATE;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS observacoes_produto TEXT;
