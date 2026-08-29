"""Busca best-effort de e-mail e WhatsApp de contato no site institucional de uma
empresa.

Só olha páginas públicas (home + páginas comuns de contato) e extrai o que a
própria empresa já publicou pra ser contatada. Falha em silêncio: se o site
estiver fora do ar, bloquear bots ou não ter nada visível, retorna None e
alguém da equipe completa manualmente depois.
"""
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from app.google_places import extrair_telefone_valido

TIMEOUT = 5
CAMINHOS_CONTATO = ["", "/contato", "/contact", "/fale-conosco", "/sobre", "/about"]
# Escala de prioridade: e-mails com cara institucional primeiro (secretaria, direção...),
# comercial/vendas por último — abordagem institucional gera mais abertura que "boa de venda".
PREFIXOS_PRIORITARIOS = [
    "secretaria", "diretoria", "direcao", "institucional", "presidencia", "coordenacao",
    "contato", "rh", "financeiro", "administrativo",
    "comercial", "vendas", "atendimento", "sac", "faleconosco",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EXTENSOES_IGNORADAS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
DOMINIOS_IGNORADOS = ("sentry.io", "wixpress.com", "example.com", "godaddy.com", "schema.org", "w3.org")

# Link de clique-para-conversar do WhatsApp: o número vem cru na própria URL, sem
# máscara nenhuma — é daí que tiramos o telefone que o BotConversa precisa (a
# empresa já publicou esse número como o canal de WhatsApp dela, então costuma ser
# mais confiável que o telefone geral do Google Maps).
WHATSAPP_LINK_REGEX = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com/send\S*?phone=|web\.whatsapp\.com/send\S*?phone=)(\d{10,15})"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EngenhariaDeClientesBot/1.0)"}


def _normalizar_url(site: str) -> Optional[str]:
    site = (site or "").strip()
    if not site:
        return None
    if not site.startswith("http://") and not site.startswith("https://"):
        site = "https://" + site
    parsed = urlparse(site)
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _emails_validos(html: str) -> list[str]:
    candidatos = set(EMAIL_REGEX.findall(html or ""))
    validos = []
    for email in candidatos:
        email_lower = email.lower()
        if email_lower.endswith(EXTENSOES_IGNORADAS):
            continue
        if any(dominio in email_lower for dominio in DOMINIOS_IGNORADOS):
            continue
        validos.append(email_lower)
    return validos


def _melhor_email(candidatos: list[str]) -> Optional[str]:
    if not candidatos:
        return None
    for prefixo in PREFIXOS_PRIORITARIOS:
        for email in candidatos:
            if email.startswith(prefixo):
                return email
    return candidatos[0]


def _whatsapp_no_html(html: str) -> Optional[str]:
    """Primeiro link de clique-pra-conversar achado, normalizado pra E.164."""
    for numero_cru in WHATSAPP_LINK_REGEX.findall(html or ""):
        valido = extrair_telefone_valido(numero_cru)
        if valido:
            return valido
    return None


def buscar_contatos_no_site(site: str) -> dict[str, Optional[str]]:
    """Varre o site em busca de e-mail e WhatsApp de contato, na mesma passada
    (uma requisição por página, não duas). Best-effort: nunca levanta exceção.

    O WhatsApp que sai daqui é o telefone em E.164 — o que o BotConversa consome
    pra disparar. O link de clique-pra-conversar (bom pra abrir rápido na mão,
    mas inútil pra automação) dá pra remontar a partir do telefone quando
    precisar: https://wa.me/<telefone sem o '+'>."""
    base = _normalizar_url(site)
    if not base:
        return {"email": None, "whatsapp": None}

    emails: list[str] = []
    whatsapp: Optional[str] = None
    for caminho in CAMINHOS_CONTATO:
        try:
            resp = requests.get(urljoin(base, caminho), headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code >= 400:
                continue
            if not emails:
                emails.extend(_emails_validos(resp.text))
            if not whatsapp:
                whatsapp = _whatsapp_no_html(resp.text)
        except requests.RequestException:
            continue
        if emails and whatsapp:
            break

    return {"email": _melhor_email(emails), "whatsapp": whatsapp}
