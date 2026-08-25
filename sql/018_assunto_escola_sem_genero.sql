-- O assunto tinha "{{empresa}} foi contemplada" (concordância no feminino, quebra
-- pra "Colégio X"). Decisão da Stella: manter masculino como padrão no assunto.
UPDATE sequencia_etapas SET assunto = 'A Geração IA chegou à sua região, {{empresa}} foi contemplado'
WHERE assunto = 'A Geração IA chegou à sua região, {{empresa}} foi contemplada';

UPDATE sequencia_etapas SET assunto = 'Re: A Geração IA chegou à sua região, {{empresa}} foi contemplado'
WHERE assunto = 'Re: A Geração IA chegou à sua região, {{empresa}} foi contemplada';
