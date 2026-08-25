-- Coloca "Stella Maris" literal no lugar do placeholder (pedido da Stella, 25/08/2026)
UPDATE sequencia_etapas SET corpo = REPLACE(corpo, '{{consultor_nome}}', 'Stella Maris');

-- Remove travessões usados no lugar de vírgula ou ponto final, ajustando pra vírgula
-- (continuação da frase) ou ponto (frases independentes) conforme o caso.

-- Sequência padrão
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'no dia a dia do negócio — sempre com foco em resultado prático',
  'no dia a dia do negócio, sempre com foco em resultado prático'
) WHERE corpo LIKE '%no dia a dia do negócio — sempre com foco em resultado prático%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'à toa — esse é meu último contato por aqui.',
  'à toa. Esse é meu último contato por aqui.'
) WHERE corpo LIKE '%à toa — esse é meu último contato por aqui.%';

-- Escola — Formação Lecionando na Geração IA
UPDATE sequencia_etapas SET assunto = REPLACE(
  assunto,
  'A Geração IA chegou à sua região — {{empresa}} foi contemplada',
  'A Geração IA chegou à sua região, {{empresa}} foi contemplada'
) WHERE assunto LIKE '%A Geração IA chegou à sua região — {{empresa}} foi contemplada%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'econômica da IA — sem perder de vista o senso crítico',
  'econômica da IA, sem perder de vista o senso crítico'
) WHERE corpo LIKE '%econômica da IA — sem perder de vista o senso crítico%';

-- Empresa Inteligente - DNA IA
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'cultura das empresas — não como ferramenta isolada',
  'cultura das empresas, não como ferramenta isolada'
) WHERE corpo LIKE '%cultura das empresas — não como ferramenta isolada%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'resolve problemas reais — e apoiamos a implementação',
  'resolve problemas reais, e apoiamos a implementação'
) WHERE corpo LIKE '%resolve problemas reais — e apoiamos a implementação%';

-- Método EP
UPDATE sequencia_etapas SET corpo = REPLACE(
  REPLACE(
    corpo,
    'de ponta a ponta — da atração até o aumento do LTV do paciente — ativando',
    'de ponta a ponta, da atração até o aumento do LTV do paciente, ativando'
  ),
  'atrair paciente novo — e deixa dinheiro na mesa',
  'atrair paciente novo, e deixa dinheiro na mesa'
) WHERE corpo LIKE '%de ponta a ponta — da atração%' OR corpo LIKE '%atrair paciente novo — e deixa dinheiro na mesa%';

-- Cobrança com IA
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'negociação de verdade — sem perder o cuidado',
  'negociação de verdade, sem perder o cuidado'
) WHERE corpo LIKE '%negociação de verdade — sem perder o cuidado%';
