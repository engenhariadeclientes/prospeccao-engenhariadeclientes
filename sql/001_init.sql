CREATE TABLE IF NOT EXISTS prospeccoes (
  id            SERIAL PRIMARY KEY,
  categoria     TEXT NOT NULL,   -- texto livre digitado pelo operador (ex.: "garantidora de receita")
  cidade        TEXT NOT NULL,   -- texto livre digitado pelo operador (ex.: "Blumenau, SC")
  criado_por    TEXT,            -- e-mail de quem acionou a busca
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resultados_encontrados INTEGER NOT NULL DEFAULT 0,
  leads_novos   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prospects (
  id                SERIAL PRIMARY KEY,
  prospeccao_id     INTEGER REFERENCES prospeccoes(id),
  nome              TEXT,
  telefone          TEXT,        -- normalizado E.164 BR (+55...)
  endereco          TEXT,
  cidade            TEXT,
  uf                CHAR(2),
  categoria         TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'fila',  -- fila | contatado | sem_interesse | convertido
  observacao        TEXT,
  criado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  atualizado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS prospects_telefone_idx ON prospects (telefone) WHERE telefone IS NOT NULL;
CREATE INDEX IF NOT EXISTS prospects_status_idx ON prospects (status);
