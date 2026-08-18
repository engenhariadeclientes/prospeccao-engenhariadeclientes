ALTER TABLE consultores ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE prospeccoes ADD COLUMN IF NOT EXISTS criado_por_consultor_id INTEGER REFERENCES consultores(id);

-- Linha do tempo genérica por prospect: ligação, whatsapp, anotação ou tarefa agendada
-- (substitui contatos_tentativas, que fica órfã sem uso — app nunca teve dados reais nela)
CREATE TABLE IF NOT EXISTS atividades (
  id            SERIAL PRIMARY KEY,
  prospect_id   INTEGER NOT NULL REFERENCES prospects(id),
  consultor_id  INTEGER REFERENCES consultores(id),
  tipo          TEXT NOT NULL,     -- ligacao | whatsapp | anotacao | tarefa
  resultado     TEXT,              -- atendeu | nao_atendeu | agendou | sem_interesse (ligacao/whatsapp)
  nota          TEXT,
  data_agendada TIMESTAMPTZ,       -- só tarefa: quando deve acontecer
  concluida     BOOLEAN NOT NULL DEFAULT FALSE,  -- só relevante pra tarefa
  criado_em     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS atividades_prospect_idx ON atividades (prospect_id);
CREATE INDEX IF NOT EXISTS atividades_consultor_idx ON atividades (consultor_id);
CREATE INDEX IF NOT EXISTS atividades_agenda_idx ON atividades (data_agendada) WHERE tipo = 'tarefa' AND concluida = FALSE;
