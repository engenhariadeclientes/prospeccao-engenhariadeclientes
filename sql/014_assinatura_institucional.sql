-- A partir de 25/08/2026 todo e-mail automático é assinado institucionalmente como
-- "Stella Maris" (ver REMETENTE_INSTITUCIONAL em app/main.py), não mais com o nome
-- de quem assumiu o negócio. Ajusta o texto de abertura pra mencionar "fundadora".
UPDATE sequencia_etapas
SET corpo = REPLACE(corpo, 'Sou {{consultor_nome}}, da Engenharia de Clientes.', 'Sou {{consultor_nome}}, fundadora da Engenharia de Clientes.')
WHERE corpo LIKE '%Sou {{consultor_nome}}, da Engenharia de Clientes.%';
