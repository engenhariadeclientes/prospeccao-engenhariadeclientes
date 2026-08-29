-- WhatsApp achado no site institucional (link de clique-pra-conversar), separado
-- do telefone geral do Google Maps: a empresa publicou esse número
-- especificamente como canal de WhatsApp, então é mais confiável pra automação
-- (BotConversa) do que arriscar discar pra um fixo que apareceu no Maps.
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS whatsapp_telefone TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS whatsapp_origem TEXT;
