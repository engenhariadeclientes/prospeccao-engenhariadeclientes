-- Dá ao prospect uma saída mais fácil que responder o e-mail: agendar direto ou
-- mandar mensagem. Os endereços vêm de configuracoes, então continuam trocáveis
-- num lugar só. Reexecutar não duplica, porque só mexe em quem ainda não tem.
UPDATE sequencia_etapas SET corpo = REPLACE(
  corpo,
  E'Abraço,',
  E'Se preferir, escolha um horário direto na minha agenda: {{link_agenda}}\nOu me chame no [WhatsApp]({{link_whatsapp}}).\n\nAbraço,'
)
WHERE corpo LIKE '%Abraço,%'
  AND corpo NOT LIKE '%{{link_agenda}}%';
