"""App web de prospecção ativa — busca livre no Google Places, sem depender de
config editada por dev: quem aciona escolhe categoria e cidade na hora.

Não dispara WhatsApp automaticamente (decisão 17/08/2026) — cada prospect entra
com status "fila" pra abordagem manual do consultor.
"""
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import aplicar_schema, get_connection
from app.google_places import buscar_empresas, extrair_cidade_uf, extrair_telefone_valido

app = FastAPI(title="Prospecção Engenharia de Clientes")
templates = Jinja2Templates(directory="app/templates")

STATUS_VALIDOS = {"fila", "contatado", "sem_interesse", "convertido"}


@app.on_event("startup")
def startup() -> None:
    aplicar_schema()


@app.get("/")
def index(request: Request, status: str = "fila"):
    status = status if status in STATUS_VALIDOS else "fila"
    with get_connection() as conn:
        prospects = conn.execute(
            "SELECT * FROM prospects WHERE status = %s ORDER BY criado_em DESC LIMIT 200",
            (status,),
        ).fetchall()
        buscas = conn.execute(
            "SELECT * FROM prospeccoes ORDER BY criado_em DESC LIMIT 20"
        ).fetchall()
        contagem = {
            row["status"]: row["total"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS total FROM prospects GROUP BY status"
            ).fetchall()
        }
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "prospects": prospects,
            "buscas": buscas,
            "contagem": contagem,
            "status_atual": status,
            "status_validos": sorted(STATUS_VALIDOS),
        },
    )


@app.post("/buscar")
def buscar(categoria: str = Form(...), cidade: str = Form(...), max_resultados: int = Form(40)):
    api_key = os.environ["GOOGLE_PLACES_API_KEY"]
    categoria = categoria.strip()
    cidade = cidade.strip()
    query = f"{categoria} em {cidade}"
    max_resultados = max(1, min(max_resultados, 120))

    encontrados = 0
    novos = 0
    agora = datetime.now(timezone.utc)

    with get_connection() as conn:
        prospeccao_id = conn.execute(
            "INSERT INTO prospeccoes (categoria, cidade, criado_em) VALUES (%s, %s, %s) RETURNING id",
            (categoria, cidade, agora),
        ).fetchone()["id"]

        for lugar in buscar_empresas(api_key, query, max_resultados=max_resultados):
            encontrados += 1
            nome = (lugar.get("displayName") or {}).get("text")
            telefone = extrair_telefone_valido(
                lugar.get("nationalPhoneNumber") or lugar.get("internationalPhoneNumber")
            )
            if not telefone:
                continue  # sem telefone válido não há como abordar

            lugar_cidade, uf = extrair_cidade_uf(lugar.get("formattedAddress"))
            row = conn.execute(
                """
                INSERT INTO prospects (prospeccao_id, nome, telefone, endereco, cidade, uf, categoria)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (telefone) WHERE telefone IS NOT NULL DO NOTHING
                RETURNING id
                """,
                (prospeccao_id, nome, telefone, lugar.get("formattedAddress"), lugar_cidade or cidade, uf, categoria),
            ).fetchone()
            if row:
                novos += 1

        conn.execute(
            "UPDATE prospeccoes SET resultados_encontrados = %s, leads_novos = %s WHERE id = %s",
            (encontrados, novos, prospeccao_id),
        )
        conn.commit()

    return RedirectResponse(url="/", status_code=303)


@app.post("/prospects/{prospect_id}/status")
def atualizar_status(prospect_id: int, status: str = Form(...)):
    if status not in STATUS_VALIDOS:
        return RedirectResponse(url="/", status_code=303)
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET status = %s, atualizado_em = NOW() WHERE id = %s",
            (status, prospect_id),
        )
        conn.commit()
    return RedirectResponse(url="/", status_code=303)
