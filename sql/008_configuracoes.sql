-- controle manual do admin sobre a liberação de novas buscas (substitui a
-- trava 100% automática por fila pendente, que travava sem opção de override)
CREATE TABLE IF NOT EXISTS configuracoes (
  chave   TEXT PRIMARY KEY,
  valor   TEXT NOT NULL
);
INSERT INTO configuracoes (chave, valor) VALUES ('busca_liberada', 'true')
ON CONFLICT (chave) DO NOTHING;
