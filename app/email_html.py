"""Converte o corpo do e-mail, que a Stella escreve em texto simples no CRM, numa
versão HTML com links clicáveis.

Duas formas de link são aceitas no texto:
  - URL solta (https://...), que vira link com o próprio endereço como texto
  - [texto visível](https://...), pra dar nome ao link

O e-mail sai nas duas versões (texto e HTML). Quem lê em cliente que bloqueia HTML
continua recebendo o texto legível, e isso também ajuda na entrega.
"""
import html
import re

# Aceita só esquemas seguros: javascript: e data: em href são vetor de ataque, e
# como esse texto é editável pela tela do CRM não custa fechar a porta.
ESQUEMAS = ("https://", "http://", "mailto:", "tel:")

RE_MARKDOWN = re.compile(r"\[([^\]\n]+)\]\((\S+?)\)")
RE_URL_SOLTA = re.compile(r"(?<![\"'>=])\b((?:https?://|www\.)[^\s<>\"']+)")


def _url_segura(url: str) -> str | None:
    limpa = url.strip().rstrip(".,;:)")
    if limpa.startswith("www."):
        limpa = "https://" + limpa
    return limpa if limpa.lower().startswith(ESQUEMAS) else None


def _ancora(url: str, texto: str) -> str:
    return f'<a href="{url}" style="color:#1a5fb4;">{texto}</a>'


def texto_para_html(texto: str) -> str:
    """Escapa o texto, transforma links e devolve o corpo em HTML."""
    escapado = html.escape(texto)

    # Os links em markdown viram marcadores antes de procurar URL solta, senão o
    # endereço de dentro do parênteses seria linkado duas vezes.
    guardados: list[str] = []

    def guardar(m: re.Match) -> str:
        url = _url_segura(html.unescape(m.group(2)))
        if not url:
            return m.group(0)
        guardados.append(_ancora(html.escape(url, quote=True), m.group(1)))
        return f"\x00{len(guardados) - 1}\x00"

    corpo = RE_MARKDOWN.sub(guardar, escapado)

    def linkar(m: re.Match) -> str:
        bruta = html.unescape(m.group(1))
        url = _url_segura(bruta)
        if not url:
            return m.group(0)
        # pontuação final não faz parte do endereço, então volta pro texto
        sobra = m.group(1)[len(m.group(1).rstrip(".,;:)")):]
        return _ancora(html.escape(url, quote=True), html.escape(bruta[: len(bruta) - len(sobra)] or bruta)) + sobra

    corpo = RE_URL_SOLTA.sub(linkar, corpo)

    for i, ancora in enumerate(guardados):
        corpo = corpo.replace(f"\x00{i}\x00", ancora)

    corpo = corpo.replace("\n", "<br>\n")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif; font-size:14px; '
        'line-height:1.5; color:#222;">\n' + corpo + "\n</div>"
    )


def achatar_links(texto: str) -> str:
    """Versão texto puro: "[WhatsApp](url)" vira "WhatsApp (url)", porque a sintaxe
    de colchetes só faz sentido depois de virar HTML."""

    def trocar(m: re.Match) -> str:
        url = _url_segura(m.group(2))
        return f"{m.group(1)} ({url})" if url else m.group(0)

    return RE_MARKDOWN.sub(trocar, texto)
