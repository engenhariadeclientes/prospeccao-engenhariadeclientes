"""Leitura de respostas na caixa de entrada do Gmail via IMAP, usando a mesma
Senha de app do envio (SMTP e IMAP compartilham a mesma credencial no Gmail)."""
import email
import imaplib
import os
from email.header import decode_header
from email.utils import parseaddr

from app.rede import conectar_ipv4

IMAP_HOST = "imap.gmail.com"


class _IMAP4SSLIPv4(imaplib.IMAP4_SSL):
    def _create_socket(self, timeout=None):
        sock = conectar_ipv4(self.host, self.port, timeout or 20)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def _decodificar_cabecalho(valor: str) -> str:
    partes = decode_header(valor or "")
    return "".join(
        (p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p)
        for p, enc in partes
    )


def _extrair_texto(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain" and not parte.get_filename():
                payload = parte.get_payload(decode=True)
                if payload:
                    return payload.decode(parte.get_content_charset() or "utf-8", errors="ignore")
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")


def buscar_respostas_novas() -> list[dict]:
    """Busca e-mails não lidos na caixa de entrada. Retorna lista de
    {remetente, assunto, trecho}. Marca os e-mails encontrados como lidos
    (efeito colateral do fetch), pra não reprocessar na próxima passada.
    Falha em silêncio: credencial ausente ou IMAP fora do ar retorna lista vazia."""
    usuario = (os.environ.get("GMAIL_USER") or "").strip()
    senha_app = "".join((os.environ.get("GMAIL_APP_PASSWORD") or "").split())
    if not usuario or not senha_app:
        return []

    respostas = []
    try:
        with _IMAP4SSLIPv4(IMAP_HOST) as imap:
            imap.login(usuario, senha_app)
            imap.select("INBOX")
            status, dados = imap.search(None, "UNSEEN")
            if status != "OK" or not dados or not dados[0]:
                return []
            for num in dados[0].split():
                status, msg_dados = imap.fetch(num, "(RFC822)")
                if status != "OK" or not msg_dados or not msg_dados[0]:
                    continue
                msg = email.message_from_bytes(msg_dados[0][1])
                remetente = parseaddr(msg.get("From") or "")[1].lower()
                if not remetente:
                    continue
                assunto = _decodificar_cabecalho(msg.get("Subject") or "")
                trecho = _extrair_texto(msg).strip()[:500]
                respostas.append({"remetente": remetente, "assunto": assunto, "trecho": trecho})
    except (imaplib.IMAP4.error, OSError) as exc:
        print(f"[imap] falha lendo a caixa de entrada: {type(exc).__name__}: {exc}", flush=True)
        return []
    return respostas
