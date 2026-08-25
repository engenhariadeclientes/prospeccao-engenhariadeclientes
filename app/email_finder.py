"""Busca best-effort de e-mail de contato no site institucional de uma empresa.

Só olha páginas públicas (home + páginas comuns de contato) e extrai endereços
que a própria empresa já publicou pra ser contatada. Falha em silêncio: se o
site estiver fora do ar, bloquear bots ou não ter e-mail visível, retorna None
e alguém da equipe completa manualmente depois.
"""
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

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


def buscar_email_no_site(site: str) -> Optional[str]:
    """Tenta achar um e-mail de contato no site. Best-effort: nunca levanta exceção."""
    base = _normalizar_url(site)
    if not base:
        return None

    candidatos: list[str] = []
    for caminho in CAMINHOS_CONTATO:
        try:
            resp = requests.get(urljoin(base, caminho), headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code >= 400:
                continue
            candidatos.extend(_emails_validos(resp.text))
        except requests.RequestException:
            continue
        if candidatos:
            break

    return _melhor_email(candidatos)
