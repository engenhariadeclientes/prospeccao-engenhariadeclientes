CREATE TABLE IF NOT EXISTS produtos (
  id          SERIAL PRIMARY KEY,
  nome        TEXT NOT NULL UNIQUE,
  criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO produtos (nome) VALUES
  ('Formação Geração IA'),
  ('Formação Lecionando na Geração IA'),
  ('Empresa Inteligente'),
  ('Tráfego Pago'),
  ('Método EP')
ON CONFLICT (nome) DO NOTHING;

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS produto_id INTEGER REFERENCES produtos(id);
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS valor_orcamento NUMERIC(12,2);
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS previsao_fechamento DATE;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS observacoes_produto TEXT;
