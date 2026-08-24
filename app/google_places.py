"""Cliente da Google Places API (New) — busca de empresas por texto livre."""
import re
import time
from typing import Iterator, Optional

import requests

BASE_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.displayName,places.nationalPhoneNumber,places.internationalPhoneNumber,places.formattedAddress,places.websiteUri"

DDD_UF = {
    11: "SP", 12: "SP", 13: "SP", 14: "SP", 15: "SP", 16: "SP", 17: "SP", 18: "SP", 19: "SP",
    21: "RJ", 22: "RJ", 24: "RJ",
    27: "ES", 28: "ES",
    31: "MG", 32: "MG", 33: "MG", 34: "MG", 35: "MG", 37: "MG", 38: "MG",
    41: "PR", 42: "PR", 43: "PR", 44: "PR", 45: "PR", 46: "PR",
    47: "SC", 48: "SC", 49: "SC",
    51: "RS", 53: "RS", 54: "RS", 55: "RS",
    61: "DF",
    62: "GO", 64: "GO",
    63: "TO",
    65: "MT", 66: "MT",
    67: "MS",
    68: "AC",
    69: "RO",
    71: "BA", 73: "BA", 74: "BA", 75: "BA", 77: "BA",
    79: "SE",
    81: "PE", 87: "PE",
    82: "AL",
    83: "PB",
    84: "RN",
    85: "CE", 88: "CE",
    86: "PI", 89: "PI",
    91: "PA", 93: "PA", 94: "PA",
    92: "AM", 97: "AM",
    95: "RR",
    96: "AP",
    98: "MA", 99: "MA",
}


def _headers(api_key: str) -> dict:
    return {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }


def buscar_empresas(api_key: str, query: str, max_resultados: int = 60) -> Iterator[dict]:
    """Text Search da Places API. Pagina via nextPageToken até max_resultados."""
    body = {"textQuery": query, "languageCode": "pt-BR"}
    coletados = 0
    proximo_token = None

    while coletados < max_resultados:
        if proximo_token:
            body["pageToken"] = proximo_token
            time.sleep(2)  # nextPageToken só fica válido após um pequeno intervalo

        resp = requests.post(BASE_URL, headers=_headers(api_key), json=body, timeout=30)
        resp.raise_for_status()
        corpo = resp.json()

        for lugar in corpo.get("places", []):
            if coletados >= max_resultados:
                return
            yield lugar
            coletados += 1

        proximo_token = corpo.get("nextPageToken")
        if not proximo_token:
            return


def extrair_telefone_valido(raw: Optional[str]) -> Optional[str]:
    """Normaliza telefone BR pra E.164. Retorna None se inválido/ausente."""
    if not raw:
        return None
    digitos = re.sub(r"\D", "", raw)
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos[2:]
    if len(digitos) < 10:
        return None
    ddd = int(digitos[0:2])
    if ddd not in DDD_UF:
        return None
    resto = digitos[2:]
    if len(resto) >= 9 and resto[0] == "9":
        numero = resto[0:9]
    elif len(resto) >= 8:
        numero = resto[0:8]
    else:
        return None
    return f"+55{ddd:02d}{numero}"


def extrair_cidade_uf(endereco_formatado: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Extrai "Cidade" e "UF" do formattedAddress da Places API (formato BR padrão,
    ex.: "Rua X, 123 - Bairro, Blumenau - SC, 89010-000, Brasil")."""
    if not endereco_formatado:
        return None, None
    for parte in [p.strip() for p in endereco_formatado.split(",")]:
        if " - " in parte:
            cidade, uf = parte.rsplit(" - ", 1)
            uf = uf.strip().upper()
            if len(uf) == 2:
                return cidade.strip(), uf
    return None, None
