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
from fastapi.staticfiles import StaticFiles
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

app = FastAPI(title="CRM - Engenharia de Clientes")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "dev-secret-troque-em-producao"))
app.mount("/static", StaticFiles(directory="app/static"), name="static")
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
TEMPERATURA_VALIDOS = ["quente", "morno", "frio"]
TEMPERATURA_LABEL = {"quente": "🔥 Quente", "morno": "🙂 Morno", "frio": "❄️ Frio"}


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


def _busca_liberada(conn) -> bool:
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave = 'busca_liberada'").fetchone()
    return row is None or row["valor"] == "true"


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
    with get_connection() as conn:
        conn.execute("INSERT INTO logins (consultor_id) VALUES (%s)", (consultor["id"],))
        conn.commit()
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
def funil(
    request: Request,
    ver: str = "meu",
    q: str = "",
    produto_id: str = "",
    prazo_de: str = "",
    prazo_ate: str = "",
    sem_acao: str = "",
):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    condicoes = []
    parametros = []

    if consultor["is_admin"] and ver != "meu":
        if ver.isdigit():
            condicoes.append(
                "(p.consultor_id = %s OR EXISTS (SELECT 1 FROM prospect_participantes pp "
                "WHERE pp.prospect_id = p.id AND pp.consultor_id = %s))"
            )
            parametros.extend([int(ver), int(ver)])
    else:
        condicoes.append(
            "(p.consultor_id = %s OR (p.status = 'fila' AND p.consultor_id IS NULL) "
            "OR EXISTS (SELECT 1 FROM prospect_participantes pp WHERE pp.prospect_id = p.id AND pp.consultor_id = %s))"
        )
        parametros.extend([consultor["id"], consultor["id"]])

    if q.strip():
        condicoes.append("(p.nome ILIKE %s OR p.decisor_nome ILIKE %s)")
        termo = f"%{q.strip()}%"
        parametros.extend([termo, termo])

    if produto_id.isdigit():
        condicoes.append("p.produto_id = %s")
        parametros.append(int(produto_id))

    if prazo_de:
        condicoes.append("p.previsao_fechamento >= %s")
        parametros.append(prazo_de)

    if prazo_ate:
        condicoes.append("p.previsao_fechamento <= %s")
        parametros.append(prazo_ate)

    if sem_acao:
        condicoes.append(
            "NOT EXISTS (SELECT 1 FROM atividades a WHERE a.prospect_id = p.id "
            "AND a.tipo = 'tarefa' AND a.concluida = FALSE)"
        )

    where_sql = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""

    with get_connection() as conn:
        consultores = conn.execute("SELECT id, nome, is_admin FROM consultores ORDER BY nome").fetchall()
        produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()

        prospects = conn.execute(
            f"""
            SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome,
                   pa.nota AS proxima_acao_nota, pa.data_agendada AS proxima_acao_data
            FROM prospects p
            LEFT JOIN consultores c ON c.id = p.consultor_id
            LEFT JOIN produtos pr ON pr.id = p.produto_id
            LEFT JOIN LATERAL (
                SELECT nota, data_agendada FROM atividades a
                WHERE a.prospect_id = p.id AND a.tipo = 'tarefa' AND a.concluida = FALSE
                ORDER BY a.data_agendada ASC NULLS LAST LIMIT 1
            ) pa ON TRUE
            {where_sql}
            ORDER BY p.criado_em DESC
            """,
            parametros,
        ).fetchall()

        buscas = conn.execute(
            """
            SELECT pr.*, c.nome AS criado_por_nome FROM prospeccoes pr
            LEFT JOIN consultores c ON c.id = pr.criado_por_consultor_id
            ORDER BY pr.criado_em DESC LIMIT 10
            """
        ).fetchall()
        fila_pendente = conn.execute("SELECT COUNT(*) AS total FROM prospects WHERE status = 'fila'").fetchone()["total"]
        busca_liberada = _busca_liberada(conn)
        contexto = _contexto_base(request, conn)

    colunas = {status: [] for status in STATUS_VALIDOS}
    for p in prospects:
        colunas[p["status"]].append(p)

    somas_coluna = {
        status: sum((p["valor_orcamento"] or 0) for p in colunas[status])
        for status in STATUS_VALIDOS
    }

    contexto.update({
        "colunas": colunas,
        "somas_coluna": somas_coluna,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "temperatura_label": TEMPERATURA_LABEL,
        "consultores": consultores,
        "produtos": produtos,
        "buscas": buscas,
        "ver": ver,
        "q": q,
        "produto_id": produto_id,
        "prazo_de": prazo_de,
        "prazo_ate": prazo_ate,
        "sem_acao": sem_acao,
        "fila_pendente": fila_pendente,
        "busca_liberada": busca_liberada,
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
        if not _busca_liberada(conn):
            # admin controla manualmente quando novas buscas ficam liberadas (decisão 18/08/2026, Stella)
            return RedirectResponse(url="/", status_code=303)

        categoria_aquisicao_google_maps = conn.execute(
            "SELECT id FROM categorias_aquisicao WHERE nome = 'Google Maps'"
        ).fetchone()
        categoria_aquisicao_id = categoria_aquisicao_google_maps["id"] if categoria_aquisicao_google_maps else None

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
                INSERT INTO prospects (prospeccao_id, nome, telefone, endereco, cidade, uf, categoria, categoria_aquisicao_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (telefone) WHERE telefone IS NOT NULL DO NOTHING
                RETURNING id
                """,
                (prospeccao_id, nome, telefone, lugar.get("formattedAddress"), lugar_cidade or cidade, uf, categoria, categoria_aquisicao_id),
            ).fetchone()
            if row:
                novos += 1

        conn.execute(
            "UPDATE prospeccoes SET resultados_encontrados = %s, leads_novos = %s WHERE id = %s",
            (encontrados, novos, prospeccao_id),
        )
        conn.commit()

    return RedirectResponse(url="/", status_code=303)


@app.post("/busca/toggle")
def alternar_busca_liberada(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        liberada = _busca_liberada(conn)
        conn.execute(
            "UPDATE configuracoes SET valor = %s WHERE chave = 'busca_liberada'",
            ("false" if liberada else "true",),
        )
        conn.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/prospeccoes/{prospeccao_id}/excluir")
def excluir_prospeccao(request: Request, prospeccao_id: int):
    """Descarta uma busca (prospecção) inteira e os prospects que ela trouxe —
    ex.: um lote de teste que não deve contaminar o funil real."""
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("DELETE FROM prospects WHERE prospeccao_id = %s", (prospeccao_id,))
        conn.execute("DELETE FROM prospeccoes WHERE id = %s", (prospeccao_id,))
        conn.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/prospects/novo")
def prospect_novo_form(request: Request):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()
        canais_aquisicao = conn.execute("SELECT id, nome FROM canais_aquisicao ORDER BY nome").fetchall()
        categorias_aquisicao = conn.execute("SELECT id, nome FROM categorias_aquisicao ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)
    contexto.update({
        "produtos": produtos,
        "canais_aquisicao": canais_aquisicao,
        "categorias_aquisicao": categorias_aquisicao,
        "erro": None,
    })
    return templates.TemplateResponse("prospect_novo.html", contexto)


@app.post("/prospects/novo")
def prospect_novo_criar(
    request: Request,
    nome: str = Form(...),
    telefone: str = Form(...),
    cidade: str = Form(""),
    uf: str = Form(""),
    categoria: str = Form(""),
    produto_id: str = Form(""),
    canal_aquisicao_id: str = Form(""),
    categoria_aquisicao_id: str = Form(""),
):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    telefone_normalizado = extrair_telefone_valido(telefone)
    if not telefone_normalizado:
        with get_connection() as conn:
            produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()
            canais_aquisicao = conn.execute("SELECT id, nome FROM canais_aquisicao ORDER BY nome").fetchall()
            categorias_aquisicao = conn.execute("SELECT id, nome FROM categorias_aquisicao ORDER BY nome").fetchall()
            contexto = _contexto_base(request, conn)
        contexto.update({
            "produtos": produtos, "canais_aquisicao": canais_aquisicao, "categorias_aquisicao": categorias_aquisicao,
            "erro": "Telefone inválido — use um número de celular/fixo brasileiro com DDD.",
        })
        return templates.TemplateResponse("prospect_novo.html", contexto)

    with get_connection() as conn:
        existente = conn.execute("SELECT id FROM prospects WHERE telefone = %s", (telefone_normalizado,)).fetchone()
        if existente:
            return RedirectResponse(url=f"/prospects/{existente['id']}", status_code=303)

        row = conn.execute(
            """
            INSERT INTO prospects (
                nome, telefone, cidade, uf, categoria, consultor_id, status,
                produto_id, canal_aquisicao_id, categoria_aquisicao_id, criado_por_consultor_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'fila', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                nome.strip(), telefone_normalizado, cidade.strip() or None, (uf.strip().upper() or None),
                categoria.strip() or None, consultor["id"],
                int(produto_id) if produto_id else None,
                int(canal_aquisicao_id) if canal_aquisicao_id else None,
                int(categoria_aquisicao_id) if categoria_aquisicao_id else None,
                consultor["id"],
            ),
        ).fetchone()
        conn.commit()
    return RedirectResponse(url=f"/prospects/{row['id']}", status_code=303)


# ---------------------------------------------------------------- prospect

@app.get("/prospects/{prospect_id}")
def prospect_detalhe(request: Request, prospect_id: int):
    redirect = exigir_login(request)
    if redirect:
        return redirect

    with get_connection() as conn:
        prospect = conn.execute(
            """
            SELECT p.*, c.nome AS consultor_nome, pr.nome AS produto_nome, m.nome AS motivo_perda_nome,
                   ca.nome AS canal_aquisicao_nome, cat.nome AS categoria_aquisicao_nome
            FROM prospects p
            LEFT JOIN consultores c ON c.id = p.consultor_id
            LEFT JOIN produtos pr ON pr.id = p.produto_id
            LEFT JOIN motivos_perda m ON m.id = p.motivo_perda_id
            LEFT JOIN canais_aquisicao ca ON ca.id = p.canal_aquisicao_id
            LEFT JOIN categorias_aquisicao cat ON cat.id = p.categoria_aquisicao_id
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
        proxima_acao = conn.execute(
            """
            SELECT id, nota, data_agendada FROM atividades
            WHERE prospect_id = %s AND tipo = 'tarefa' AND concluida = FALSE
            ORDER BY data_agendada ASC NULLS LAST LIMIT 1
            """,
            (prospect_id,),
        ).fetchone()
        consultores = conn.execute("SELECT id, nome FROM consultores ORDER BY nome").fetchall()
        produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()
        motivos_perda = conn.execute("SELECT id, nome FROM motivos_perda ORDER BY nome").fetchall()
        canais_aquisicao = conn.execute("SELECT id, nome FROM canais_aquisicao ORDER BY nome").fetchall()
        categorias_aquisicao = conn.execute("SELECT id, nome FROM categorias_aquisicao ORDER BY nome").fetchall()
        participantes = conn.execute(
            """
            SELECT c.id, c.nome FROM prospect_participantes pp
            JOIN consultores c ON c.id = pp.consultor_id
            WHERE pp.prospect_id = %s ORDER BY c.nome
            """,
            (prospect_id,),
        ).fetchall()
        contexto = _contexto_base(request, conn)

    ids_participantes = {p["id"] for p in participantes}
    consultores_disponiveis = [
        c for c in consultores if c["id"] != prospect["consultor_id"] and c["id"] not in ids_participantes
    ]

    contexto.update({
        "prospect": prospect,
        "timeline": timeline,
        "proxima_acao": proxima_acao,
        "consultores": consultores,
        "produtos": produtos,
        "motivos_perda": motivos_perda,
        "canais_aquisicao": canais_aquisicao,
        "categorias_aquisicao": categorias_aquisicao,
        "participantes": participantes,
        "consultores_disponiveis": consultores_disponiveis,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "tipo_label": TIPO_ATIVIDADE_LABEL,
        "resultado_validos": RESULTADO_VALIDOS,
        "temperatura_validos": TEMPERATURA_VALIDOS,
        "temperatura_label": TEMPERATURA_LABEL,
    })
    return templates.TemplateResponse("prospect_detalhe.html", contexto)


@app.post("/prospects/{prospect_id}/participantes")
def adicionar_participante(request: Request, prospect_id: int, consultor_id: str = Form(...)):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    if consultor_id:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO prospect_participantes (prospect_id, consultor_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (prospect_id, int(consultor_id)),
            )
            conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/participantes/{consultor_id}/remover")
def remover_participante(request: Request, prospect_id: int, consultor_id: int):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM prospect_participantes WHERE prospect_id = %s AND consultor_id = %s",
            (prospect_id, consultor_id),
        )
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


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
    canal_aquisicao_id: str = Form(""),
    categoria_aquisicao_id: str = Form(""),
    decisor_nome: str = Form(""),
    decisor_telefone: str = Form(""),
    decisor_email: str = Form(""),
    decisor_endereco: str = Form(""),
    decisor_aniversario: str = Form(""),
    decisor_redes_sociais: str = Form(""),
    temperatura: str = Form(""),
):
    produto_val = int(produto_id) if produto_id else None
    valor_val = _parsear_valor_brl(valor_orcamento)
    previsao_val = previsao_fechamento or None
    canal_val = int(canal_aquisicao_id) if canal_aquisicao_id else None
    categoria_val = int(categoria_aquisicao_id) if categoria_aquisicao_id else None
    temperatura_val = temperatura if temperatura in TEMPERATURA_VALIDOS else None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE prospects
            SET produto_id = %s, valor_orcamento = %s, previsao_fechamento = %s,
                observacoes_produto = %s, canal_aquisicao_id = %s, categoria_aquisicao_id = %s,
                decisor_nome = %s, decisor_telefone = %s, decisor_email = %s,
                decisor_endereco = %s, decisor_aniversario = %s, decisor_redes_sociais = %s,
                temperatura = %s, atualizado_em = NOW()
            WHERE id = %s
            """,
            (
                produto_val, valor_val, previsao_val, observacoes_produto.strip() or None,
                canal_val, categoria_val,
                decisor_nome.strip() or None, decisor_telefone.strip() or None, decisor_email.strip() or None,
                decisor_endereco.strip() or None, decisor_aniversario or None, decisor_redes_sociais.strip() or None,
                temperatura_val,
                prospect_id,
            ),
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
            """
            SELECT c.id, c.nome, c.usuario, c.is_admin, c.criado_em,
                   (SELECT MAX(criado_em) FROM logins l WHERE l.consultor_id = c.id) AS ultimo_acesso
            FROM consultores c ORDER BY c.nome
            """
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


@app.post("/consultores/{consultor_id}/senha")
def consultores_resetar_senha(request: Request, consultor_id: int, nova_senha: str = Form(...)):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute(
            "UPDATE consultores SET senha_hash = %s WHERE id = %s",
            (gerar_hash(nova_senha), consultor_id),
        )
        conn.commit()
    return RedirectResponse(url="/consultores", status_code=303)


@app.get("/log-acesso")
def log_acesso(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        logins = conn.execute(
            """
            SELECT l.criado_em, c.nome, c.usuario
            FROM logins l JOIN consultores c ON c.id = l.consultor_id
            ORDER BY l.criado_em DESC LIMIT 200
            """
        ).fetchall()
        contexto = _contexto_base(request, conn)
    contexto["logins"] = logins
    return templates.TemplateResponse("log_acesso.html", contexto)


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

        por_canal_aquisicao = conn.execute(
            """
            SELECT ca.nome, COUNT(*) AS total, COUNT(*) FILTER (WHERE p.status = 'ganho') AS ganhos
            FROM prospects p JOIN canais_aquisicao ca ON ca.id = p.canal_aquisicao_id
            GROUP BY ca.nome ORDER BY total DESC
            """
        ).fetchall()

        por_categoria_aquisicao = conn.execute(
            """
            SELECT cat.nome, COUNT(*) AS total, COUNT(*) FILTER (WHERE p.status = 'ganho') AS ganhos
            FROM prospects p JOIN categorias_aquisicao cat ON cat.id = p.categoria_aquisicao_id
            GROUP BY cat.nome ORDER BY total DESC
            """
        ).fetchall()

        por_temperatura = conn.execute(
            """
            SELECT temperatura, COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'ganho') AS ganhos,
                   COALESCE(SUM(valor_orcamento), 0) AS valor_total
            FROM prospects
            WHERE temperatura IS NOT NULL AND status NOT IN ('ganho', 'perdido')
            GROUP BY temperatura
            """
        ).fetchall()
        por_temperatura = {row["temperatura"]: row for row in por_temperatura}

        sem_proxima_acao = conn.execute(
            """
            SELECT COUNT(*) AS total FROM prospects p
            WHERE p.status NOT IN ('ganho', 'perdido')
                  AND NOT EXISTS (
                      SELECT 1 FROM atividades a
                      WHERE a.prospect_id = p.id AND a.tipo = 'tarefa' AND a.concluida = FALSE
                  )
            """
        ).fetchone()["total"]

        contexto = _contexto_base(request, conn)

    contexto.update({
        "funil_counts": funil_counts,
        "total_prospects": total_prospects,
        "status_validos": STATUS_VALIDOS,
        "status_label": STATUS_LABEL,
        "temperatura_validos": TEMPERATURA_VALIDOS,
        "temperatura_label": TEMPERATURA_LABEL,
        "atividade_por_consultor": atividade_por_consultor,
        "prospects_por_consultor": prospects_por_consultor,
        "valor_por_status": valor_por_status,
        "motivos_perda_ranking": motivos_perda_ranking,
        "por_canal_aquisicao": por_canal_aquisicao,
        "por_categoria_aquisicao": por_categoria_aquisicao,
        "por_temperatura": por_temperatura,
        "sem_proxima_acao": sem_proxima_acao,
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


@app.get("/canais-aquisicao")
def canais_aquisicao_lista(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        canais = conn.execute("SELECT id, nome, criado_em FROM canais_aquisicao ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)
    contexto["canais"] = canais
    return templates.TemplateResponse("canais_aquisicao.html", contexto)


@app.post("/canais-aquisicao")
def canais_aquisicao_criar(request: Request, nome: str = Form(...)):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("INSERT INTO canais_aquisicao (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (nome.strip(),))
        conn.commit()
    return RedirectResponse(url="/canais-aquisicao", status_code=303)


@app.get("/categorias-aquisicao")
def categorias_aquisicao_lista(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        categorias = conn.execute("SELECT id, nome, criado_em FROM categorias_aquisicao ORDER BY nome").fetchall()
        contexto = _contexto_base(request, conn)
    contexto["categorias"] = categorias
    return templates.TemplateResponse("categorias_aquisicao.html", contexto)


@app.post("/categorias-aquisicao")
def categorias_aquisicao_criar(request: Request, nome: str = Form(...)):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("INSERT INTO categorias_aquisicao (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING", (nome.strip(),))
        conn.commit()
    return RedirectResponse(url="/categorias-aquisicao", status_code=303)


@app.get("/export.csv")
def exportar_csv(request: Request):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    with get_connection() as conn:
        if consultor["is_admin"]:
            prospects = conn.execute(
                """
                SELECT p.nome, p.telefone, p.cidade, p.uf, p.categoria, p.status,
                       c.nome AS consultor_nome, p.criado_em
                FROM prospects p
                LEFT JOIN consultores c ON c.id = p.consultor_id
                ORDER BY p.criado_em DESC
                """
            ).fetchall()
        else:
            prospects = conn.execute(
                """
                SELECT p.nome, p.telefone, p.cidade, p.uf, p.categoria, p.status,
                       c.nome AS consultor_nome, p.criado_em
                FROM prospects p
                LEFT JOIN consultores c ON c.id = p.consultor_id
                WHERE p.consultor_id = %s OR (p.status = 'fila' AND p.consultor_id IS NULL)
                      OR EXISTS (SELECT 1 FROM prospect_participantes pp
                                 WHERE pp.prospect_id = p.id AND pp.consultor_id = %s)
                ORDER BY p.criado_em DESC
                """,
                (consultor["id"], consultor["id"]),
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
