-- Tráfego Pago estava cadastrado como produto mas sem sequência própria, então caía
-- no curinga e recebia a oferta de DNA IA. Texto inicial escrito pra ser editado pela
-- Stella direto no CRM: descreve o ângulo comercial sem prometer número que não temos.
INSERT INTO produtos (nome) VALUES ('Tráfego Pago') ON CONFLICT (nome) DO NOTHING;

INSERT INTO sequencias_email (nome, ativa, origem, produto_id)
SELECT 'Tráfego Pago', TRUE, NULL, (SELECT id FROM produtos WHERE nome = 'Tráfego Pago')
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email WHERE nome = 'Tráfego Pago');

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
  '{{empresa}}, tráfego que traz cliente, não só clique',
  E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Muita empresa investe em anúncio e acompanha o resultado pelo número de cliques, quando o que paga a conta é cliente fechado.\n\nTrabalhamos tráfego pago colado no comercial: a campanha atrai, o lead é qualificado e acompanhado até a venda, e você enxerga quanto de cada real investido virou receita de verdade.\n\nFaz sentido uma conversa rápida de 15 minutos pra eu entender como está a operação de vocês hoje?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Tráfego Pago'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 1);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: tráfego que traz cliente, não só clique',
  E'{{nome_decisor}}, retomando o contato,\n\nNa maior parte das vezes o gargalo não está no anúncio, e sim no que acontece depois do clique: lead que demora a ser atendido, follow-up que não acontece, nenhum registro de onde a venda parou.\n\nQuando campanha e comercial trabalham juntos, o mesmo investimento rende mais, sem precisar aumentar verba.\n\nConsigo te mostrar como isso se aplicaria na {{empresa}} numa conversa rápida?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Tráfego Pago'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Última tentativa, {{nome_decisor}}',
  E'{{nome_decisor}}, esse é meu último contato por aqui.\n\nSe fizer sentido pra {{empresa}} enxergar o retorno real do que investe em anúncio, é só responder esse e-mail que encontramos um horário.\n\nSe não for o momento, sem problema.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Tráfego Pago'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);
