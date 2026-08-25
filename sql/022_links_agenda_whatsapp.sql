-- Links usados nos e-mails ficam em configuração, não no texto de cada etapa: assim a
-- Stella troca o endereço da agenda num lugar só e todas as sequências acompanham.
INSERT INTO configuracoes (chave, valor) VALUES ('link_agenda', '') ON CONFLICT (chave) DO NOTHING;
INSERT INTO configuracoes (chave, valor) VALUES ('link_whatsapp', '') ON CONFLICT (chave) DO NOTHING;
