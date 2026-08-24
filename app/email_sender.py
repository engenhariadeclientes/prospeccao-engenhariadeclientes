"""Envio de e-mail via SMTP do Gmail, usando uma Senha de app da conta remetente."""
import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def enviar_email(destinatario: str, assunto: str, corpo: str) -> bool:
    """Envia um e-mail em texto simples. Retorna False (sem levantar exceção) se
    as credenciais não estiverem configuradas ou o envio falhar — quem chama
    decide o que fazer com uma falha (ex.: tentar de novo mais tarde)."""
    usuario = os.environ.get("GMAIL_USER")
    senha_app = os.environ.get("GMAIL_APP_PASSWORD")
    if not usuario or not senha_app:
        return False

    mensagem = MIMEText(corpo, "plain", "utf-8")
    mensagem["Subject"] = assunto
    mensagem["From"] = usuario
    mensagem["To"] = destinatario

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as servidor:
            servidor.login(usuario, senha_app)
            servidor.sendmail(usuario, [destinatario], mensagem.as_string())
        return True
    except (smtplib.SMTPException, OSError):
        return False
