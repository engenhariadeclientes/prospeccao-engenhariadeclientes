CREATE TABLE IF NOT EXISTS sequencias_email (
  id         SERIAL PRIMARY KEY,
  nome       TEXT NOT NULL UNIQUE,
  ativa      BOOLEAN NOT NULL DEFAULT TRUE,
  criado_em  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sequencia_etapas (
  id                  SERIAL PRIMARY KEY,
  sequencia_id        INTEGER NOT NULL REFERENCES sequencias_email(id) ON DELETE CASCADE,
  ordem               INTEGER NOT NULL,
  dias_apos_anterior  INTEGER NOT NULL DEFAULT 0,
  assunto             TEXT NOT NULL,
  corpo               TEXT NOT NULL,
  criado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS sequencia_etapas_sequencia_idx ON sequencia_etapas (sequencia_id, ordem);

INSERT INTO sequencias_email (nome, ativa)
SELECT 'Sequência padrão', TRUE
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
       'Contato — Engenharia de Clientes',
       E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Encontrei a {{empresa}} e gostaria de apresentar como ajudamos empresas como a sua a crescer de forma inteligente.\n\nPodemos conversar essa semana?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Sequência padrão'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id);

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS sequencia_email_id INTEGER REFERENCES sequencias_email(id) ON DELETE SET NULL;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS sequencia_etapa_atual INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS proximo_envio_email TIMESTAMPTZ;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS email_opt_out BOOLEAN NOT NULL DEFAULT FALSE;
