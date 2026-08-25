"""Envio de e-mail via SMTP do Gmail, usando uma Senha de app da conta remetente."""
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def credenciais() -> tuple[str | None, str | None]:
    """O Gmail mostra a Senha de app em blocos ("abcd efgh ijkl mnop") e colar com
    os espaços faz o login falhar com erro de autenticação, então tiramos aqui."""
    usuario = (os.environ.get("GMAIL_USER") or "").strip() or None
    senha_bruta = os.environ.get("GMAIL_APP_PASSWORD") or ""
    senha_app = "".join(senha_bruta.split()) or None
    return usuario, senha_app


def testar_smtp() -> str:
    """Conecta e autentica sem enviar nada. Retorna "ok" ou a descrição do erro."""
    usuario, senha_app = credenciais()
    if not usuario or not senha_app:
        return "credenciais ausentes (GMAIL_USER / GMAIL_APP_PASSWORD)"
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as servidor:
            servidor.login(usuario, senha_app)
        return "ok"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def enviar_email(destinatario: str, assunto: str, corpo: str, remetente_nome: str | None = None) -> bool:
    """Envia um e-mail em texto simples. Retorna False (sem levantar exceção) se
    as credenciais não estiverem configuradas ou o envio falhar — quem chama
    decide o que fazer com uma falha (ex.: tentar de novo mais tarde)."""
    usuario, senha_app = credenciais()
    if not usuario or not senha_app:
        print("[email] envio abortado: GMAIL_USER/GMAIL_APP_PASSWORD não configurados", flush=True)
        return False

    mensagem = MIMEText(corpo, "plain", "utf-8")
    mensagem["Subject"] = assunto
    mensagem["From"] = formataddr((remetente_nome, usuario)) if remetente_nome else usuario
    mensagem["To"] = destinatario

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as servidor:
            servidor.login(usuario, senha_app)
            servidor.sendmail(usuario, [destinatario], mensagem.as_string())
        print(f"[email] enviado para {destinatario}: {assunto}", flush=True)
        return True
    except Exception as exc:
        print(f"[email] FALHA ao enviar para {destinatario}: {type(exc).__name__}: {exc}", flush=True)
        return False
