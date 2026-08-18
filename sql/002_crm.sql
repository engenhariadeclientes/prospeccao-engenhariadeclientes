CREATE TABLE IF NOT EXISTS consultores (
  id            SERIAL PRIMARY KEY,
  nome          TEXT NOT NULL,
  usuario       TEXT NOT NULL UNIQUE,
  senha_hash    TEXT NOT NULL,
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS consultor_id INTEGER REFERENCES consultores(id);

CREATE TABLE IF NOT EXISTS contatos_tentativas (
  id            SERIAL PRIMARY KEY,
  prospect_id   INTEGER NOT NULL REFERENCES prospects(id),
  consultor_id  INTEGER REFERENCES consultores(id),
  canal         TEXT NOT NULL DEFAULT 'ligacao',
  resultado     TEXT NOT NULL,
  nota          TEXT,
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS contatos_tentativas_prospect_idx ON contatos_tentativas (prospect_id);
