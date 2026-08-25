-- Consolidação de nomes de produto decidida pela Stella (25/08/2026)
UPDATE produtos SET nome = 'Empresa Inteligente - DNA IA' WHERE nome = 'Empresa Inteligente';
-- fallback pra banco novo, onde "Empresa Inteligente" nunca existiu (o UPDATE acima não faz nada)
INSERT INTO produtos (nome) VALUES ('Empresa Inteligente - DNA IA') ON CONFLICT (nome) DO NOTHING;
INSERT INTO produtos (nome) VALUES ('Cobrança com IA') ON CONFLICT (nome) DO NOTHING;

-- Sequência padrão: troca o texto de exemplo pelas 3 etapas reais e completa a régua
UPDATE sequencia_etapas SET
  assunto = '{{nome_decisor}}, uma ideia rápida pra vocês',
  corpo = E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Encontrei a {{empresa}} pesquisando empresas da região e acredito que temos algo relevante pra contribuir com o crescimento de vocês.\n\nTrabalhamos ajudando empresas a tomar decisões mais inteligentes — desde estruturar processos até aplicar IA no dia a dia do negócio — sempre com foco em resultado prático, não em teoria.\n\nFaz sentido uma conversa rápida de 15 minutos essa semana pra eu entender melhor o momento da {{empresa}} e ver se conseguimos ajudar?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Sequência padrão') AND ordem = 1;

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: uma ideia rápida pra vocês',
  E'{{nome_decisor}}, retomando o contato,\n\nSei que a rotina é corrida, então vou direto ao ponto: empresas que aplicam as decisões certas — com base em dados e não em achismo — crescem de forma mais consistente e gastam menos tempo apagando incêndio.\n\nÉ exatamente isso que fazemos na Engenharia de Clientes: destravar esse tipo de crescimento pra negócios como a {{empresa}}.\n\nTopa 15 minutos pra eu te mostrar como isso funcionaria no caso de vocês?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Sequência padrão'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Última tentativa, {{nome_decisor}}',
  E'{{nome_decisor}}, não quero ocupar sua caixa de entrada à toa — esse é meu último contato por aqui.\n\nSe fizer sentido pra {{empresa}} conversar sobre crescimento inteligente em algum momento, é só responder esse e-mail que encontramos um horário rápido.\n\nSe não for o momento, sem problema — deixo a porta aberta.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Sequência padrão'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);

-- Sequência: Escola — Formação Lecionando na Geração IA (porta de entrada: palestra gratuita pros professores)
INSERT INTO sequencias_email (nome, ativa, origem, produto_id)
SELECT 'Escola — Formação Lecionando na Geração IA', TRUE, NULL,
       (SELECT id FROM produtos WHERE nome = 'Formação Lecionando na Geração IA')
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email WHERE nome = 'Escola — Formação Lecionando na Geração IA');

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
  'Convite: palestra gratuita sobre IA para a {{empresa}}',
  E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Nosso propósito é levar Inteligência Artificial com ética para dentro das escolas — formando professores e preparando alunos pra realidade produtiva e econômica da IA, sem perder de vista o senso crítico e o uso responsável da tecnologia.\n\nComo parte dessa iniciativa, oferecemos gratuitamente a Formação Lecionando na Geração IA: uma palestra pro corpo docente da {{empresa}} sobre como usar IA de forma ética e prática na rotina pedagógica — sem custo, sem compromisso.\n\nA ideia é gerar valor real pra gestão da escola antes de qualquer coisa. Precisamos apenas do apoio de vocês em abrir a escola pra nossa visita.\n\nPodemos conversar 15 minutos essa semana pra alinhar os detalhes?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Escola — Formação Lecionando na Geração IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 1);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: palestra gratuita sobre IA para a {{empresa}}',
  E'{{nome_decisor}}, retomando o convite,\n\nResumindo o que a {{empresa}} ganha com essa parceria, sem nenhum custo:\n\n- Formação Lecionando na Geração IA: palestra gratuita pros professores, com foco em uso ético e prático da IA em sala de aula.\n- Alunos com acesso à Formação Geração IA — aplicações reais de IA, empreendedorismo e um hackathon com premiação.\n- Um diferencial concreto pra escola mostrar às famílias: preparo real dos alunos pro futuro do trabalho, com responsabilidade.\n\nConsigo te mandar mais detalhes ou já agendar uma conversa rápida?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Escola — Formação Lecionando na Geração IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Últimas vagas — Formação Lecionando na Geração IA na {{empresa}}',
  E'{{nome_decisor}}, esse é meu último contato sobre o convite.\n\nEstamos fechando a agenda de escolas participantes. A palestra pros professores é gratuita, o processo é simples, e o objetivo é só gerar valor real pra gestão de vocês antes de qualquer proposta.\n\nSe fizer sentido, é só responder esse e-mail que já encontramos um horário. Se não for o momento, sem problema.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Escola — Formação Lecionando na Geração IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);

-- Sequência: Empresa Inteligente - DNA IA (empresas em geral)
INSERT INTO sequencias_email (nome, ativa, origem, produto_id)
SELECT 'Empresa Inteligente - DNA IA', TRUE, NULL,
       (SELECT id FROM produtos WHERE nome = 'Empresa Inteligente - DNA IA')
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email WHERE nome = 'Empresa Inteligente - DNA IA');

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
  '{{empresa}}, e se a IA fizesse parte da cultura de vocês?',
  E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Trabalhamos levando a IA pro centro da cultura das empresas — não como ferramenta isolada, mas como um novo jeito de pensar o dia a dia, amadurecendo o time pra enxergar oportunidades de IA nos próprios processos.\n\nConduzimos um processo real de transformação: imersão, ferramentas práticas, cases de sucesso e depois a prática guiada, onde o próprio time propõe onde a IA resolve problemas reais — e apoiamos a implementação do que for factível.\n\nFaz sentido uma conversa rápida de 15 minutos pra entender o momento da {{empresa}}?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Empresa Inteligente - DNA IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 1);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: e se a IA fizesse parte da cultura de vocês?',
  E'{{nome_decisor}}, retomando o contato,\n\nO DNA IA não é um curso — é um processo que transforma como a {{empresa}} resolve problemas no dia a dia, com cada colaborador propondo e ajudando a implementar soluções de IA nos próprios processos.\n\nEmpresas que fazem essa mudança de cultura saem na frente, com menos tempo apagando incêndio e mais eficiência estrutural.\n\nTopa 15 minutos pra eu te mostrar como funcionaria na {{empresa}}?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Empresa Inteligente - DNA IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Última tentativa, {{nome_decisor}}',
  E'{{nome_decisor}}, esse é meu último contato por aqui.\n\nSe fizer sentido pra {{empresa}} repensar como a IA entra na cultura do time, é só responder esse e-mail que encontramos um horário rápido.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Empresa Inteligente - DNA IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);

-- Sequência: Método EP (clínicas/dentistas — jornada do paciente + tráfego)
INSERT INTO sequencias_email (nome, ativa, origem, produto_id)
SELECT 'Método EP', TRUE, NULL, (SELECT id FROM produtos WHERE nome = 'Método EP')
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email WHERE nome = 'Método EP');

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
  '{{empresa}}, e se cada paciente gerasse mais valor ao longo do tempo?',
  E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Ajudamos clínicas a acelerar o comercial de ponta a ponta — da atração até o aumento do LTV do paciente — ativando a jornada do paciente com IA: relacionamento contínuo, cuidado constante e mais retorno financeiro da carteira.\n\nNa prática: o paciente entra na jornada e não sai mais.\n\nFaz sentido 15 minutos essa semana pra eu entender o momento da {{empresa}} e mostrar como isso funcionaria aí?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Método EP'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 1);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: e se cada paciente gerasse mais valor ao longo do tempo?',
  E'{{nome_decisor}}, retomando o contato,\n\nMuita clínica foca só em atrair paciente novo — e deixa dinheiro na mesa na carteira que já tem. O Método EP vira essa chave: ativa a jornada do paciente já existente, gerando relacionamento contínuo e mais eficiência financeira sem depender só de captação nova.\n\nConsigo te mostrar como isso se aplicaria na {{empresa}} em uma conversa rápida?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Método EP'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Última tentativa, {{nome_decisor}}',
  E'{{nome_decisor}}, esse é meu último contato por aqui.\n\nSe fizer sentido pra {{empresa}} aumentar o retorno da carteira de pacientes com IA, é só responder esse e-mail.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Método EP'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);

-- Sequência: Cobrança com IA (administradoras/escritórios de cobrança)
INSERT INTO sequencias_email (nome, ativa, origem, produto_id)
SELECT 'Cobrança com IA', TRUE, NULL, (SELECT id FROM produtos WHERE nome = 'Cobrança com IA')
WHERE NOT EXISTS (SELECT 1 FROM sequencias_email WHERE nome = 'Cobrança com IA');

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 1, 0,
  '{{empresa}}, cobrança inteligente sem perder o relacionamento',
  E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. Trabalhamos com uma régua de cobrança com IA que segue rigorosamente as políticas de cobrança vigentes, reduz o custo operacional inicial e mantém sua equipe humana livre pro que realmente exige atenção pessoal: negociações delicadas e casos críticos.\n\nJá temos case em operação no mercado condominial, com alto índice de retorno.\n\nFaz sentido uma conversa rápida de 15 minutos pra eu mostrar como isso se aplicaria na {{empresa}}?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Cobrança com IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 1);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 2, 3,
  'Re: cobrança inteligente sem perder o relacionamento',
  E'{{nome_decisor}}, retomando o contato,\n\nO diferencial da nossa régua de cobrança com IA é o equilíbrio: automação no follow-up do dia a dia, mas com a equipe humana preservada pros casos que exigem negociação de verdade — sem perder o cuidado com a fidelização de quem paga.\n\nConsigo te mostrar os resultados do case do mercado condominial em uma conversa rápida?\n\nAbraço,\n{{consultor_nome}}'
FROM sequencias_email s
WHERE s.nome = 'Cobrança com IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 2);

INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo)
SELECT s.id, 3, 7,
  'Última tentativa, {{nome_decisor}}',
  E'{{nome_decisor}}, esse é meu último contato por aqui.\n\nSe fizer sentido reduzir custo de cobrança sem perder relacionamento na {{empresa}}, é só responder esse e-mail.\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
FROM sequencias_email s
WHERE s.nome = 'Cobrança com IA'
  AND NOT EXISTS (SELECT 1 FROM sequencia_etapas e WHERE e.sequencia_id = s.id AND e.ordem = 3);
