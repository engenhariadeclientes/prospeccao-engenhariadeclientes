ALTER TABLE prospects ADD COLUMN IF NOT EXISTS origem_cadastro TEXT NOT NULL DEFAULT 'manual';
UPDATE prospects SET origem_cadastro = 'busca_automatica' WHERE prospeccao_id IS NOT NULL AND origem_cadastro = 'manual';

ALTER TABLE sequencias_email ADD COLUMN IF NOT EXISTS origem TEXT;
ALTER TABLE sequencias_email ADD COLUMN IF NOT EXISTS produto_id INTEGER REFERENCES produtos(id) ON DELETE SET NULL;
-- "Sequência padrão" fica como fallback genérico (origem/produto em branco = serve pra qualquer combinação
-- que não tiver uma sequência mais específica cadastrada).
