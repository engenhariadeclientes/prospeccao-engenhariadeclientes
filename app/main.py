"""App web de prospecção ativa + CRM — busca livre no Google Places, funil por
consultor, linha do tempo de atividades, agenda de tarefas e visão administrativa.

Não dispara WhatsApp automaticamente (decisão 17/08/2026) — cada prospect entra
com status "fila" pra abordagem manual do consultor (ligação ou WhatsApp,
conforme o que o prospect tiver disponível).
"""
import csv
import io
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    autenticar,
    consultor_logado,
    exigir_admin,
    exigir_login,
    existe_algum_consultor,
    gerar_hash,
)
from app.db import aplicar_schema, get_connection
from app.google_places import buscar_empresas, extrair_cidade_uf, extrair_telefone_valido

app = FastAPI(title="Prospecção Engenharia de Clientes")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "dev-secret-troque-em-producao"))
templates = Jinja2Templates(directory="app/templates")

STATUS_VALIDOS = ["fila", "contatado", "negociando", "ganho", "perdido"]
STATUS_LABEL = {
    "fila": "Fila",
    "contatado": "Contatado",
    "negociando": "Negociando",
    "ganho": "Ganho",
    "perdido": "Perdido",
}
TIPO_ATIVIDADE_LABEL = {"ligacao": "Ligação", "whatsapp": "WhatsApp", "anotacao": "Anotação", "tarefa": "Tarefa"}
RESULTADO_VALIDOS = ["atendeu", "nao_atendeu", "agendou", "sem_interesse"]


@app.on_event("startup")
def startup() -> None:
    aplicar_schema()


def _parsear_valor_brl(bruto: str) -> float | None:
    """Aceita formato BR digitado (1.500,00) e o valor já normalizado que volta
    no campo pré-preenchido pelo Jinja (1500.00, sem vírgula)."""
    texto = bruto.strip()
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _contar_pendencias(conn, consultor_id: int) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total FROM atividades
        WHERE tipo = 'tarefa' AND concluida = FALSE AND consultor_id = %s
              AND data_agendada <= (NOW() + INTERVAL '1 day')
        """,
        (consultor_id,),
    ).fetchone()
    return row["total"]


# ---------------------------------------------------------------- login/setup

@app.get("/setup")
def setup_form(request: Request):
    if existe_algum_consultor():
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("setup.html", {"request": request})


@app.post("/setup")
def setup_submit(nome: str = Form(...), usuario: str = Form(...), senha: str = Form(...)):
    if existe_algum_consultor():
        return RedirectResponse(url="/login", status_code=303)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO consultores (nome, usuario, senha_hash, is_admin) VALUES (%s, %s, %s, TRUE)",
            (nome.strip(), usuario.strip(), gerar_hash(senha)),
        )
        conn.commit()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login")
def login_form(request: Request):
    if not existe_algum_consultor():
        return RedirectResponse(url="/setup", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "erro": None})


@app.post("/login")
def login_submit(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    consultor = autenticar(usuario.strip(), senha)
    if not consultor:
        return templates.TemplateResponse("login.html", {"request": request, "erro": "Usuário ou senha inválidos."})
    request.session["consultor"] = consultor
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


def _contexto_base(request: Request, conn) -> dict:
    consultor = consultor_logado(request)
    return {"request": request, "consultor": consultor, "pendencias": _contar_pendencias(conn, consultor["id"])}


# --------------------------------------------------------------------- funil

@app.get("/")
def funil(request: Request, ver: str = "meu"):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    with get_connection() as conn:
        consultores = conn.execute("SELECT id, nome, is_admin FROM consultores ORDER BY nome").fetchall()

        if consultor["is_admin"] and ver != "meu":
            filtro_consultor_id = int(ver) if ver.isdigit() else None
            if filtro_consultor_id:
                prospects = conn.execute(
                    """
                    SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome FROM prospects p
                    LEFT JOIN consultores c ON c.id = p.consultor_id
                    LEFT JOIN produtos pr ON pr.id = p.produto_id
                    WHERE p.consultor_id = %s ORDER BY p.criado_em DESC
                    """,
                    (filtro_consultor_id,),
                ).fetchall()
            else:
                prospects = conn.execute(
                    """
                    SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome FROM prospects p
                    LEFT JOIN consultores c ON c.id = p.consultor_id
                    LEFT JOIN produtos pr ON pr.id = p.produto_id
                    ORDER BY p.criado_em DESC
                    """
                ).fetchall()
        else:
            prospects = conn.execute(
                """
                SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome FROM prospects p
                LEFT JOIN consultores c ON c.id = p.consultor_id
                LEFT JOIN produtos pr ON pr.id = p.produto_id
                WHERE p.consultor_id = %s OR (p.status = 'fila' AND p.consultor_id IS NULL)
                ORDER BY p.criado_em DESC
                """,
                (consultor["id"],),
            ).fetchall()

        buscas = conn.execute(
            """
            SELECT pr.*, c.nome AS criado_por_nome FROM prospeccoes pr
            LEFT JOIN consultores c ON c.id = pr.criado_por_consultor_id
            ORDER BY pr.criado_em DESC LIMIT 10
            """
        ).fetchall()
        contexto = _contexto_base(request, conn)

    colunas = {status: [] for status in STATUS_VALIDOS}
    for p in prospects:
        colunas[p["status"]].append(p)

    contexto.update({
        "colunas": colunas,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "consultores": consultores,
        "buscas": buscas,
        "ver": ver,
    })
    return templates.TemplateResponse("kanban.html", contexto)


@app.post("/buscar")
def buscar(request: Request, categoria: str = Form(...), cidade: str = Form(...), max_resultados: int = Form(40)):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

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
            "INSERT INTO prospeccoes (categoria, cidade, criado_em, criado_por_consultor_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (categoria, cidade, agora, consultor["id"]),
        ).fetchone()["id"]

        for lugar in buscar_empresas(api_key, query, max_resultados=max_resultados):
            encontrados += 1
            nome = (lugar.get("displayName") or {}).get("text")
            telefone = extrair_telefone_valido(
                lugar.get("nationalPhoneNumber") or lugar.get("internationalPhoneNumber")
            )
            if not telefone:
                continue

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


# ---------------------------------------------------------------- prospect

@app.get("/prospects/{prospect_id}")
def prospect_detalhe(request: Request, prospect_id: int):
    redirect = exigir_login(request)
    if redirect:
        return redirect

    with get_connection() as conn:
        prospect = conn.execute(
            """
            SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome, m.nome AS motivo_perda_nome
            FROM prospects p
            LEFT JOIN consultores c ON c.id = p.consultor_id
            LEFT JOIN produtos pr ON pr.id = p.produto_id
            LEFT JOIN motivos_perda m ON m.id = p.motivo_perda_id
            WHERE p.id = %s
            """,
            (prospect_id,),
        ).fetchone()
        timeline = conn.execute(
            """
            SELECT a.*, c.nome AS consultor_nome
            FROM atividades a LEFT JOIN consultores c ON c.id = a.consultor_id
            WHERE a.prospect_id = %s
            ORDER BY a.criado_em DESC
            """,
            (prospect_id,),
        ).fetchall()
        consultores = conn.execute("SELECT id, nome FROM consultores ORDER BY nome").fetchall()
        produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()
        motivos_perda = conn.execute("SELECT id, nome FROM motivos_perda ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)

    contexto.update({
        "prospect": prospect,
        "timeline": timeline,
        "consultores": consultores,
        "produtos": produtos,
        "motivos_perda": motivos_perda,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "tipo_label": TIPO_ATIVIDADE_LABEL,
        "resultado_validos": RESULTADO_VALIDOS,
    })
    return templates.TemplateResponse("prospect_detalhe.html", contexto)


@app.post("/prospects/{prospect_id}/status")
def atualizar_status(prospect_id: int, status: str = Form(...), motivo_perda_id: str = Form("")):
    if status not in STATUS_VALIDOS:
        return RedirectResponse(url="/", status_code=303)
    motivo_val = int(motivo_perda_id) if (status == "perdido" and motivo_perda_id) else None
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET status = %s, motivo_perda_id = %s, atualizado_em = NOW() WHERE id = %s",
            (status, motivo_val, prospect_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/consultor")
def atribuir_consultor(prospect_id: int, consultor_id: str = Form(...)):
    valor = int(consultor_id) if consultor_id else None
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET consultor_id = %s, atualizado_em = NOW() WHERE id = %s",
            (valor, prospect_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/negocio")
def atualizar_negocio(
    prospect_id: int,
    produto_id: str = Form(""),
    valor_orcamento: str = Form(""),
    previsao_fechamento: str = Form(""),
    observacoes_produto: str = Form(""),
):
    produto_val = int(produto_id) if produto_id else None
    valor_val = _parsear_valor_brl(valor_orcamento)
    previsao_val = previsao_fechamento or None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE prospects
            SET produto_id = %s, valor_orcamento = %s, previsao_fechamento = %s,
                observacoes_produto = %s, atualizado_em = NOW()
            WHERE id = %s
            """,
            (produto_val, valor_val, previsao_val, observacoes_produto.strip() or None, prospect_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/assumir")
def assumir_prospect(request: Request, prospect_id: int):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET consultor_id = %s, status = CASE WHEN status = 'fila' THEN 'contatado' ELSE status END, "
            "atualizado_em = NOW() WHERE id = %s AND consultor_id IS NULL",
            (consultor["id"], prospect_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/atividades")
def registrar_atividade(
    request: Request,
    prospect_id: int,
    tipo: str = Form(...),
    resultado: str = Form(""),
    nota: str = Form(""),
    data_agendada: str = Form(""),
):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    agendada = datetime.fromisoformat(data_agendada) if (tipo == "tarefa" and data_agendada) else None

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO atividades (prospect_id, consultor_id, tipo, resultado, nota, data_agendada)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (prospect_id, consultor["id"], tipo, resultado or None, nota.strip() or None, agendada),
        )
        # quem registra a primeira atividade de contato (não anotação/tarefa) assume o prospect se ninguém tiver assumido
        if tipo in ("ligacao", "whatsapp"):
            conn.execute(
                "UPDATE prospects SET consultor_id = COALESCE(consultor_id, %s), "
                "status = CASE WHEN status = 'fila' THEN 'contatado' ELSE status END, atualizado_em = NOW() "
                "WHERE id = %s",
                (consultor["id"], prospect_id),
            )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/atividades/{atividade_id}/concluir")
def concluir_atividade(request: Request, atividade_id: int, voltar: str = Form("/agenda")):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("UPDATE atividades SET concluida = TRUE WHERE id = %s", (atividade_id,))
        conn.commit()
    return RedirectResponse(url=voltar, status_code=303)


# --------------------------------------------------------------------- agenda

@app.get("/agenda")
def agenda(request: Request):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    with get_connection() as conn:
        tarefas = conn.execute(
            """
            SELECT a.*, p.nome AS prospect_nome, p.telefone AS prospect_telefone, c.nome AS consultor_nome
            FROM atividades a
            JOIN prospects p ON p.id = a.prospect_id
            LEFT JOIN consultores c ON c.id = a.consultor_id
            WHERE a.tipo = 'tarefa' AND a.concluida = FALSE
                  AND (a.consultor_id = %s OR %s)
            ORDER BY a.data_agendada NULLS LAST
            """,
            (consultor["id"], consultor["is_admin"]),
        ).fetchall()
        contexto = _contexto_base(request, conn)

    agora = datetime.now(timezone.utc)
    atrasadas, hoje, proximas = [], [], []
    for t in tarefas:
        if not t["data_agendada"]:
            proximas.append(t)
        elif t["data_agendada"] < agora.replace(hour=0, minute=0, second=0, microsecond=0):
            atrasadas.append(t)
        elif t["data_agendada"].date() == agora.date():
            hoje.append(t)
        else:
            proximas.append(t)

    contexto.update({"atrasadas": atrasadas, "hoje": hoje, "proximas": proximas})
    return templates.TemplateResponse("agenda.html", contexto)


# ---------------------------------------------------------------- consultores

@app.get("/consultores")
def consultores_lista(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        consultores = conn.execute(
            "SELECT id, nome, usuario, is_admin, criado_em FROM consultores ORDER BY nome"
        ).fetchall()
        contexto = _contexto_base(request, conn)
    contexto["consultores"] = consultores
    return templates.TemplateResponse("consultores.html", contexto)


@app.post("/consultores")
def consultores_criar(
    request: Request,
    nome: str = Form(...),
    usuario: str = Form(...),
    senha: str = Form(...),
    is_admin: str = Form(""),
):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO consultores (nome, usuario, senha_hash, is_admin) VALUES (%s, %s, %s, %s)",
            (nome.strip(), usuario.strip(), gerar_hash(senha), bool(is_admin)),
        )
        conn.commit()
    return RedirectResponse(url="/consultores", status_code=303)


# --------------------------------------------------------------------- admin

@app.get("/admin")
def admin_dashboard(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect

    with get_connection() as conn:
        funil_counts = {
            row["status"]: row["total"]
            for row in conn.execute("SELECT status, COUNT(*) AS total FROM prospects GROUP BY status").fetchall()
        }
        total_prospects = sum(funil_counts.values()) or 1

        atividade_por_consultor = conn.execute(
            """
            SELECT c.nome,
                   COUNT(*) FILTER (WHERE a.tipo = 'ligacao') AS ligacoes,
                   COUNT(*) FILTER (WHERE a.tipo = 'whatsapp') AS whatsapps,
                   COUNT(*) FILTER (WHERE a.tipo = 'anotacao') AS anotacoes,
                   COUNT(*) FILTER (WHERE a.tipo = 'tarefa' AND a.concluida) AS tarefas_concluidas,
                   COUNT(*) AS total
            FROM atividades a
            JOIN consultores c ON c.id = a.consultor_id
            WHERE a.criado_em >= NOW() - INTERVAL '30 days'
            GROUP BY c.nome
            ORDER BY total DESC
            """
        ).fetchall()

        prospects_por_consultor = conn.execute(
            """
            SELECT c.nome,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE p.status = 'ganho') AS ganhos,
                   COALESCE(SUM(p.valor_orcamento) FILTER (WHERE p.status = 'ganho'), 0) AS valor_ganho
            FROM prospects p
            JOIN consultores c ON c.id = p.consultor_id
            GROUP BY c.nome
            ORDER BY total DESC
            """
        ).fetchall()

        valor_por_status = {
            row["status"]: row["total_valor"]
            for row in conn.execute(
                "SELECT status, COALESCE(SUM(valor_orcamento), 0) AS total_valor FROM prospects GROUP BY status"
            ).fetchall()
        }

        motivos_perda_ranking = conn.execute(
            """
            SELECT m.nome, COUNT(*) AS total
            FROM prospects p JOIN motivos_perda m ON m.id = p.motivo_perda_id
            WHERE p.status = 'perdido'
            GROUP BY m.nome ORDER BY total DESC
            """
        ).fetchall()

        contexto = _contexto_base(request, conn)

    contexto.update({
        "funil_counts": funil_counts,
        "total_prospects": total_prospects,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "atividade_por_consultor": atividade_por_consultor,
        "prospects_por_consultor": prospects_por_consultor,
        "valor_por_status": valor_por_status,
        "motivos_perda_ranking": motivos_perda_ranking,
    })
    return templates.TemplateResponse("admin.html", contexto)


# ------------------------------------------------------- catálogos (admin)

@app.get("/produtos")
def produtos_lista(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        produtos = conn.execute("SELECT id, nome, criado_em FROM produtos ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)
    contexto["produtos"] = produtos
    return templates.TemplateResponse("produtos.html", contexto)


@app.post("/produtos")
def produtos_criar(request: Request, nome: str = Form(...)):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("INSERT INTO produtos (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (nome.strip(),))
        conn.commit()
    return RedirectResponse(url="/produtos", status_code=303)


@app.get("/motivos-perda")
def motivos_perda_lista(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        motivos = conn.execute("SELECT id, nome, criado_em FROM motivos_perda ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)
    contexto["motivos"] = motivos
    return templates.TemplateResponse("motivos_perda.html", contexto)


@app.post("/motivos-perda")
def motivos_perda_criar(request: Request, nome: str = Form(...)):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("INSERT INTO motivos_perda (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (nome.strip(),))
        conn.commit()
    return RedirectResponse(url="/motivos-perda", status_code=303)


@app.get("/export.csv")
def exportar_csv(request: Request):
    redirect = exigir_login(request)
    if redirect:
        return redirect

    with get_connection() as conn:
        prospects = conn.execute(
            """
            SELECT p.nome, p.telefone, p.cidade, p.uf, p.categoria, p.status,
                   c.nome AS consultor_nome, p.criado_em
            FROM prospects p
            LEFT JOIN consultores c ON c.id = p.consultor_id
            ORDER BY p.criado_em DESC
            """
        ).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Nome", "Telefone", "Cidade", "UF", "Categoria", "Status", "Consultor", "Criado em"])
    for p in prospects:
        writer.writerow([
            p["nome"], p["telefone"], p["cidade"], p["uf"], p["categoria"],
            STATUS_LABEL.get(p["status"], p["status"]), p["consultor_nome"] or "",
            p["criado_em"].strftime("%d/%m/%Y %H:%M"),
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=prospects.csv"},
    )
