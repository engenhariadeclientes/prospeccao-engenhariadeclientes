-- Completa a limpeza de travessões que a migration 015 deixou passar
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'O DNA IA não é um curso — é um processo que transforma',
  'O DNA IA não é um curso. É um processo que transforma'
) WHERE corpo LIKE '%O DNA IA não é um curso — é um processo que transforma%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'Formação Geração IA — aplicações reais de IA, empreendedorismo e um hackathon com premiação.',
  'Formação Geração IA, com aplicações reais de IA, empreendedorismo e um hackathon com premiação.'
) WHERE corpo LIKE '%Formação Geração IA — aplicações reais de IA%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'decisões mais inteligentes — desde estruturar processos',
  'decisões mais inteligentes, desde estruturar processos'
) WHERE corpo LIKE '%decisões mais inteligentes — desde estruturar processos%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'decisões certas — com base em dados e não em achismo — crescem de forma mais consistente',
  'decisões certas, com base em dados e não em achismo, crescem de forma mais consistente'
) WHERE corpo LIKE '%decisões certas — com base em dados e não em achismo — crescem de forma mais consistente%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'sem problema — deixo a porta aberta.',
  'sem problema. Deixo a porta aberta.'
) WHERE corpo LIKE '%sem problema — deixo a porta aberta.%';

-- Reforça a prova social do case de cobrança (pedido da Stella, 25/08/2026)
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'Já temos case em operação no mercado condominial, com alto índice de retorno.',
  'Já temos case em operação em uma das maiores garantidoras de receita condominiais do Brasil, com alto índice de retorno.'
) WHERE corpo LIKE '%Já temos case em operação no mercado condominial, com alto índice de retorno.%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'Consigo te mostrar os resultados do case do mercado condominial em uma conversa rápida?',
  'Consigo te mostrar os resultados desse case, de uma das maiores garantidoras de receita condominiais do Brasil, em uma conversa rápida?'
) WHERE corpo LIKE '%Consigo te mostrar os resultados do case do mercado condominial em uma conversa rápida?%';
