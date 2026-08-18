CREATE TABLE IF NOT EXISTS motivos_perda (
  id          SERIAL PRIMARY KEY,
  nome        TEXT NOT NULL UNIQUE,
  criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO motivos_perda (nome) VALUES
  ('Sem orçamento'),
  ('Não é o decisor'),
  ('Fechou com concorrente'),
  ('Não retornou contato'),
  ('Fora do perfil'),
  ('Timing ruim / remarcar futuramente')
ON CONFLICT (nome) DO NOTHING;

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS motivo_perda_id INTEGER REFERENCES motivos_perda(id);

-- alinha a taxonomia de estágio com ganho/perdido (nomenclatura de CRM padrão)
UPDATE prospects SET status = 'ganho' WHERE status = 'fechado';
UPDATE prospects SET status = 'perdido' WHERE status = 'sem_interesse';
