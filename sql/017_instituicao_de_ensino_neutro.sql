-- Evita erro de concordância de gênero (Colégio X pede "o", Escola X pede "a") trocando
-- o artigo + nome da empresa por "sua instituição de ensino", que serve pra qualquer caso.
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'e a {{empresa}} foi contemplada pra participar dessa iniciativa',
  'e sua instituição de ensino foi contemplada pra participar dessa iniciativa'
) WHERE corpo LIKE '%e a {{empresa}} foi contemplada pra participar dessa iniciativa%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'Como parte da iniciativa, a {{empresa}} tem acesso',
  'Como parte da iniciativa, sua instituição de ensino tem acesso'
) WHERE corpo LIKE '%Como parte da iniciativa, a {{empresa}} tem acesso%';

UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  'Resumindo o que a {{empresa}} ganha com essa parceria',
  'Resumindo o que sua instituição de ensino ganha com essa parceria'
) WHERE corpo LIKE '%Resumindo o que a {{empresa}} ganha com essa parceria%';
