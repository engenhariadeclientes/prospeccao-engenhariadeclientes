-- A sequência da Escola precisa atender dois produtos: "Formação Geração IA" (o curso
-- dos alunos, que é o objetivo comercial) e "Formação Lecionando na Geração IA" (a
-- palestra gratuita pros professores, que é a porta de entrada). Mesmo texto pros dois,
-- então duplicar a sequência duplicaria o conteúdo a manter: o vínculo com produto vira
-- uma lista.
CREATE TABLE IF NOT EXISTS sequencia_produtos (
  sequencia_id INTEGER NOT NULL REFERENCES sequencias_email(id) ON DELETE CASCADE,
  produto_id   INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
  PRIMARY KEY (sequencia_id, produto_id)
);

-- Espelha os vínculos que já existiam, pra não mudar o comportamento de nada.
INSERT INTO sequencia_produtos (sequencia_id, produto_id)
SELECT id, produto_id FROM sequencias_email WHERE produto_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- A palestra continua caindo na sequência da Escola, mas o produto principal dela passa
-- a ser o curso, que é o que a escola de fato contrata (decisão da Stella, 25/08/2026).
INSERT INTO sequencia_produtos (sequencia_id, produto_id)
SELECT s.id, p.id
FROM sequencias_email s, produtos p
WHERE s.nome = 'Escola — Formação Lecionando na Geração IA'
  AND p.nome = 'Formação Geração IA'
ON CONFLICT DO NOTHING;

UPDATE sequencias_email SET produto_id = (SELECT id FROM produtos WHERE nome = 'Formação Geração IA')
WHERE nome = 'Escola — Formação Lecionando na Geração IA';
