-- temperatura do negócio, pra estimar probabilidade de fechamento
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS temperatura TEXT; -- quente | morno | frio

-- vários usuários podem colaborar no mesmo negócio (além do responsável principal
-- em prospects.consultor_id) e o negócio aparece no funil de todos eles
CREATE TABLE IF NOT EXISTS prospect_participantes (
  prospect_id   INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
  consultor_id  INTEGER NOT NULL REFERENCES consultores(id) ON DELETE CASCADE,
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (prospect_id, consultor_id)
);
