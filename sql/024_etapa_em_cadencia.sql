-- Negócio em régua de e-mail ficava misturado na Fila, dando impressão de fila parada.
-- Marcar como "Contatado" seria pior: disparo automático não é contato feito por gente,
-- e inflaria a taxa de contato do time. Ganha etapa própria, entre as duas.
UPDATE prospects SET status = 'em_cadencia'
WHERE status = 'fila' AND sequencia_email_id IS NOT NULL;
