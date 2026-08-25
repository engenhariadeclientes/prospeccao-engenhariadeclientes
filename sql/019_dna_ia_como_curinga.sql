-- A "Sequência padrão" era genérica demais e, por ser o curinga, era justamente a que
-- mais disparava: todo negócio sem produto definido caía nela. Decisão da Stella
-- (25/08/2026): o curinga passa a ser o DNA IA, que é a oferta mais geral.
--
-- Zerar o produto_id do DNA IA faz ele casar com qualquer negócio. As sequências
-- específicas continuam ganhando dele quando o produto bate, porque _melhor_sequencia_email
-- ordena pela quantidade de condições preenchidas.
UPDATE sequencias_email SET produto_id = NULL
WHERE nome = 'Empresa Inteligente - DNA IA';

UPDATE sequencias_email SET ativa = FALSE
WHERE nome = 'Sequência padrão';
