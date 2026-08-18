CREATE TABLE IF NOT EXISTS categorias_aquisicao (
  id          SERIAL PRIMARY KEY,
  nome        TEXT NOT NULL UNIQUE,
  criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO categorias_aquisicao (nome) VALUES
  ('Google Maps'), ('PAP'), ('Evento'), ('Parceiros Pagos')
ON CONFLICT (nome) DO NOTHING;

CREATE TABLE IF NOT EXISTS canais_aquisicao (
  id          SERIAL PRIMARY KEY,
  nome        TEXT NOT NULL UNIQUE,
  criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO canais_aquisicao (nome) VALUES
  ('ADS Insta'), ('ADS Google'), ('Site Orgânico'), ('Instagram Orgânico'),
  ('LinkedIn Orgânico'), ('ADS TikTok'), ('TikTok Orgânico'), ('Indicação')
ON CONFLICT (nome) DO NOTHING;

ALTER TABLE prospects ADD COLUMN IF NOT EXISTS canal_aquisicao_id INTEGER REFERENCES canais_aquisicao(id);
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS categoria_aquisicao_id INTEGER REFERENCES categorias_aquisicao(id);

-- prospects vindos da prospecção ativa (Google Places) entram automaticamente
-- na categoria "Google Maps" (decisão 18/08/2026, Stella)
UPDATE prospects SET categoria_aquisicao_id = (SELECT id FROM categorias_aquisicao WHERE nome = 'Google Maps')
WHERE prospeccao_id IS NOT NULL AND categoria_aquisicao_id IS NULL;

-- cadastro manual de negócio (fora da busca automática)
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS criado_por_consultor_id INTEGER REFERENCES consultores(id);

-- dados do decisor (pessoa de contato), separados dos dados da empresa
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_nome TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_telefone TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_email TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_endereco TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_aniversario DATE;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS decisor_redes_sociais TEXT;

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS prospects_nome_trgm_idx ON prospects USING gin (nome gin_trgm_ops);
CREATE INDEX IF NOT EXISTS prospects_decisor_nome_trgm_idx ON prospects USING gin (decisor_nome gin_trgm_ops);

CREATE TABLE IF NOT EXISTS logins (
  id            SERIAL PRIMARY KEY,
  consultor_id  INTEGER NOT NULL REFERENCES consultores(id),
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS logins_consultor_idx ON logins (consultor_id);

-- permite excluir uma prospecção (busca) inteira e seus prospects de uma vez
-- (ex.: descartar um lote de teste) sem travar em atividades já registradas
ALTER TABLE atividades DROP CONSTRAINT IF EXISTS atividades_prospect_id_fkey;
ALTER TABLE atividades ADD CONSTRAINT atividades_prospect_id_fkey
  FOREIGN KEY (prospect_id) REFERENCES prospects(id) ON DELETE CASCADE;
