"""Envio de e-mail via SMTP do Gmail, usando uma Senha de app da conta remetente."""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

from app.rede import conectar_ipv4

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT_SSL = 465
SMTP_PORT_TLS = 587
TIMEOUT = 20


def credenciais() -> tuple[str | None, str | None]:
    """O Gmail mostra a Senha de app em blocos ("abcd efgh ijkl mnop") e colar com
    os espaços faz o login falhar com erro de autenticação, então tiramos aqui."""
    usuario = (os.environ.get("GMAIL_USER") or "").strip() or None
    senha_bruta = os.environ.get("GMAIL_APP_PASSWORD") or ""
    senha_app = "".join(senha_bruta.split()) or None
    return usuario, senha_app


class _SMTPIPv4(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return conectar_ipv4(host, port, timeout, self.source_address)


class _SMTPSSLIPv4(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        sock = conectar_ipv4(host, port, timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


def _abrir_sessao(porta: int) -> smtplib.SMTP:
    """Na 465 o TLS é imediato; na 587 sobe em texto claro e faz STARTTLS."""
    if porta == SMTP_PORT_SSL:
        return _SMTPSSLIPv4(SMTP_HOST, porta, timeout=TIMEOUT, context=ssl.create_default_context())
    sessao = _SMTPIPv4(SMTP_HOST, porta, timeout=TIMEOUT)
    sessao.starttls(context=ssl.create_default_context())
    sessao.ehlo()
    return sessao


def _conectar_autenticado(usuario: str, senha_app: str) -> smtplib.SMTP:
    """Tenta a 465 e cai pra 587 se ela estiver fechada — provedores de hospedagem
    costumam liberar só uma das duas."""
    erros = []
    for porta in (SMTP_PORT_SSL, SMTP_PORT_TLS):
        try:
            sessao = _abrir_sessao(porta)
            sessao.login(usuario, senha_app)
            return sessao
        except Exception as exc:
            erros.append(f"porta {porta}: {type(exc).__name__}: {exc}")
    raise OSError("; ".join(erros))


def testar_smtp() -> str:
    """Conecta e autentica sem enviar nada. Retorna "ok" ou a descrição do erro."""
    usuario, senha_app = credenciais()
    if not usuario or not senha_app:
        return "credenciais ausentes (GMAIL_USER / GMAIL_APP_PASSWORD)"
    try:
        sessao = _conectar_autenticado(usuario, senha_app)
        sessao.quit()
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
        sessao = _conectar_autenticado(usuario, senha_app)
        try:
            sessao.sendmail(usuario, [destinatario], mensagem.as_string())
        finally:
            sessao.quit()
        print(f"[email] enviado para {destinatario}: {assunto}", flush=True)
        return True
    except Exception as exc:
        print(f"[email] FALHA ao enviar para {destinatario}: {type(exc).__name__}: {exc}", flush=True)
        return False
