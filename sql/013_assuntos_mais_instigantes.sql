-- Ajuste de assuntos (e reescrita da abertura da Escola) revisado com a Stella em 25/08/2026:
-- ganchos de curiosidade em vez de descrição neutra, e "selecionada/contemplada" em vez de
-- liderar com "gratuito" na Escola (soa como "não deve valer muito").

-- Sequência padrão
UPDATE sequencia_etapas SET assunto = '{{empresa}}, o que a maioria das empresas erra sem perceber'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Sequência padrão') AND ordem = 1;
UPDATE sequencia_etapas SET assunto = 'Re: o que a maioria das empresas erra sem perceber'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Sequência padrão') AND ordem = 2;
UPDATE sequencia_etapas SET assunto = 'Fechando essa conversa, {{nome_decisor}}'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Sequência padrão') AND ordem = 3;

-- Escola — Formação Lecionando na Geração IA
UPDATE sequencia_etapas SET
  assunto = 'A Geração IA chegou à sua região — {{empresa}} foi contemplada',
  corpo = E'Olá {{nome_decisor}},\n\nSou {{consultor_nome}}, da Engenharia de Clientes. A Geração IA chegou à sua região, e a {{empresa}} foi contemplada pra participar dessa iniciativa: levar Inteligência Artificial com ética para dentro das escolas, formando professores e preparando alunos pra realidade produtiva e econômica da IA — sem perder de vista o senso crítico e o uso responsável da tecnologia.\n\nComo parte da iniciativa, a {{empresa}} tem acesso à Formação Lecionando na Geração IA: uma palestra pro corpo docente sobre como usar IA de forma ética e prática na rotina pedagógica, sem custo pra escola.\n\nA ideia é gerar valor real pra gestão de vocês antes de qualquer coisa. Precisamos apenas do apoio em abrir a escola pra nossa visita.\n\nPodemos conversar 15 minutos essa semana pra alinhar os detalhes?\n\nAbraço,\n{{consultor_nome}}\nEngenharia de Clientes'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Escola — Formação Lecionando na Geração IA') AND ordem = 1;
UPDATE sequencia_etapas SET assunto = 'Re: A Geração IA chegou à sua região — {{empresa}} foi contemplada'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Escola — Formação Lecionando na Geração IA') AND ordem = 2;
UPDATE sequencia_etapas SET assunto = 'Últimas vagas pra {{empresa}} este semestre'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Escola — Formação Lecionando na Geração IA') AND ordem = 3;

-- Empresa Inteligente - DNA IA
UPDATE sequencia_etapas SET assunto = '{{empresa}}, e se sua equipe já soubesse resolver isso com IA?'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Empresa Inteligente - DNA IA') AND ordem = 1;
UPDATE sequencia_etapas SET assunto = 'Re: e se sua equipe já soubesse resolver isso com IA?'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Empresa Inteligente - DNA IA') AND ordem = 2;
UPDATE sequencia_etapas SET assunto = 'Encerrando por aqui, {{nome_decisor}}'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Empresa Inteligente - DNA IA') AND ordem = 3;

-- Cobrança com IA
UPDATE sequencia_etapas SET assunto = '{{empresa}}, e se a cobrança se resolvesse sozinha (quase)?'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Cobrança com IA') AND ordem = 1;
UPDATE sequencia_etapas SET assunto = 'Re: e se a cobrança se resolvesse sozinha (quase)?'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Cobrança com IA') AND ordem = 2;
UPDATE sequencia_etapas SET assunto = 'Encerrando por aqui, {{nome_decisor}}'
WHERE sequencia_id = (SELECT id FROM sequencias_email WHERE nome = 'Cobrança com IA') AND ordem = 3;
