"""Envio de e-mail com dois caminhos possíveis.

Preferido: API HTTPS da Resend. O Railway só libera SMTP de saída no plano Pro —
nos demais as portas 465/587 simplesmente expiram, que era a razão de nenhum
e-mail da régua sair. Como HTTPS passa em qualquer plano, basta ter
RESEND_API_KEY definida que o envio usa esse caminho.

Alternativo: SMTP do Gmail com Senha de app, usado quando não há chave da Resend.
"""
import os
import smtplib
import time
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr

import requests

from app.rede import conectar_ipv4

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT_SSL = 465
SMTP_PORT_TLS = 587
TIMEOUT = 20
RESEND_URL = "https://api.resend.com/emails"


def credenciais() -> tuple[str | None, str | None]:
    """O Gmail mostra a Senha de app em blocos ("abcd efgh ijkl mnop") e colar com
    os espaços faz o login falhar com erro de autenticação, então tiramos aqui."""
    usuario = (os.environ.get("GMAIL_USER") or "").strip() or None
    senha_bruta = os.environ.get("GMAIL_APP_PASSWORD") or ""
    senha_app = "".join(senha_bruta.split()) or None
    return usuario, senha_app


def _chave_resend() -> str | None:
    return (os.environ.get("RESEND_API_KEY") or "").strip() or None


def _endereco_remetente() -> str | None:
    """EMAIL_REMETENTE permite enviar por um domínio verificado na Resend; sem ela,
    cai pro endereço do Gmail."""
    return (os.environ.get("EMAIL_REMETENTE") or "").strip() or (credenciais()[0])


# --- caminho HTTPS (Resend) ---------------------------------------------------


def _enviar_via_resend(destinatario: str, assunto: str, corpo: str, remetente_nome: str | None) -> bool:
    chave = _chave_resend()
    remetente = _endereco_remetente()
    if not remetente:
        print("[email] Resend configurada mas falta EMAIL_REMETENTE/GMAIL_USER", flush=True)
        return False

    payload = {
        "from": formataddr((remetente_nome, remetente)) if remetente_nome else remetente,
        "to": [destinatario],
        "subject": assunto,
        "text": corpo,
    }
    # As respostas precisam cair na caixa que o leitor IMAP acompanha.
    resposta_para = credenciais()[0]
    if resposta_para and resposta_para != remetente:
        payload["reply_to"] = resposta_para

    try:
        r = requests.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {chave}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        print(f"[email] FALHA de rede na Resend para {destinatario}: {type(exc).__name__}: {exc}", flush=True)
        return False

    if r.status_code >= 300:
        print(f"[email] FALHA na Resend para {destinatario}: HTTP {r.status_code} {r.text[:300]}", flush=True)
        return False
    print(f"[email] enviado (Resend) para {destinatario}: {assunto}", flush=True)
    return True


# --- caminho SMTP (Gmail) -----------------------------------------------------


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
    """Tenta a 465 e cai pra 587 se ela estiver fechada."""
    erros = []
    for porta in (SMTP_PORT_SSL, SMTP_PORT_TLS):
        try:
            sessao = _abrir_sessao(porta)
            sessao.login(usuario, senha_app)
            return sessao
        except Exception as exc:
            erros.append(f"porta {porta}: {type(exc).__name__}: {exc}")
    raise OSError("; ".join(erros))


def _enviar_via_smtp(destinatario: str, assunto: str, corpo: str, remetente_nome: str | None) -> bool:
    usuario, senha_app = credenciais()
    if not usuario or not senha_app:
        print("[email] envio abortado: nem RESEND_API_KEY nem GMAIL_USER/GMAIL_APP_PASSWORD configurados", flush=True)
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
        print(f"[email] enviado (SMTP) para {destinatario}: {assunto}", flush=True)
        return True
    except Exception as exc:
        print(f"[email] FALHA no SMTP para {destinatario}: {type(exc).__name__}: {exc}", flush=True)
        return False


# --- interface pública --------------------------------------------------------


def provedor() -> str:
    return "resend" if _chave_resend() else "smtp"


def testar_envio() -> str:
    """Verifica a credencial do provedor ativo sem mandar e-mail nenhum."""
    if _chave_resend():
        if not _endereco_remetente():
            return "resend: falta EMAIL_REMETENTE (endereço do domínio verificado)"
        try:
            r = requests.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {_chave_resend()}"},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            return f"resend: {type(exc).__name__}: {exc}"
        if r.status_code >= 300:
            return f"resend: HTTP {r.status_code} {r.text[:200]}"
        return f"resend: ok (remetente {_endereco_remetente()})"

    usuario, senha_app = credenciais()
    if not usuario or not senha_app:
        return "sem provedor: defina RESEND_API_KEY ou GMAIL_USER/GMAIL_APP_PASSWORD"
    try:
        sessao = _conectar_autenticado(usuario, senha_app)
        sessao.quit()
        return "smtp: ok"
    except Exception as exc:
        return f"smtp: {type(exc).__name__}: {exc}"


_cache_credencial: tuple[float, str] | None = None


def testar_envio_cache(validade_segundos: int = 300) -> str:
    """Versão com cache pra usar em página web: o teste real abre conexão e pode
    levar dezenas de segundos quando a porta está bloqueada."""
    global _cache_credencial
    agora = time.monotonic()
    if _cache_credencial and agora - _cache_credencial[0] < validade_segundos:
        return _cache_credencial[1]
    resultado = testar_envio()
    _cache_credencial = (agora, resultado)
    return resultado


def enviar_email(destinatario: str, assunto: str, corpo: str, remetente_nome: str | None = None) -> bool:
    """Envia um e-mail em texto simples. Retorna False (sem levantar exceção) se
    o envio falhar — quem chama decide o que fazer com a falha."""
    if _chave_resend():
        return _enviar_via_resend(destinatario, assunto, corpo, remetente_nome)
    return _enviar_via_smtp(destinatario, assunto, corpo, remetente_nome)
