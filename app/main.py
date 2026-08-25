"""App web de prospecção ativa + CRM — busca livre no Google Places, funil por
consultor, linha do tempo de atividades, agenda de tarefas e visão administrativa.

Não dispara WhatsApp automaticamente (decisão 17/08/2026) — cada prospect entra
com status "fila" pra abordagem manual do consultor (ligação ou WhatsApp,
conforme o que o prospect tiver disponível).
"""
import csv
import io
import os
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
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
from app.email_finder import buscar_email_no_site
from app.email_sender import (
    credenciais as credenciais_email,
    enviar_email,
    provedor as provedor_email,
    testar_envio,
    testar_envio_cache,
)
from app.email_receiver import buscar_respostas_novas

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
TIPO_ATIVIDADE_LABEL = {
    "ligacao": "Ligação", "whatsapp": "WhatsApp", "anotacao": "Anotação", "tarefa": "Tarefa",
    "email_automatico": "E-mail automático",
}
RESULTADO_VALIDOS = ["atendeu", "nao_atendeu", "agendou", "sem_interesse"]
TEMPERATURA_VALIDOS = ["quente", "morno", "frio"]
TEMPERATURA_LABEL = {"quente": "🔥 Quente", "morno": "🙂 Morno", "frio": "❄️ Frio"}

_serializer_descadastro = URLSafeSerializer(os.environ.get("SESSION_SECRET", "dev-secret-troque-em-producao"), salt="descadastro-email")
scheduler = BackgroundScheduler(timezone="UTC")


REMETENTE_INSTITUCIONAL = "Stella Maris"


def _preencher_template_email(texto: str, decisor_nome: str | None, empresa: str | None) -> str:
    return (
        texto.replace("{{nome_decisor}}", decisor_nome or empresa or "")
        .replace("{{empresa}}", empresa or "sua empresa")
        .replace("{{consultor_nome}}", REMETENTE_INSTITUCIONAL)
    )


def _melhor_sequencia_email(conn, origem_cadastro: str, produto_id: int | None):
    """Escolhe a sequência ativa mais específica pra essa combinação de origem (busca
    automática/manual/ads) + produto de interesse. Uma sequência com origem/produto em
    branco serve de curinga; a mais específica (as duas condições batendo) ganha."""
    return conn.execute(
        """
        SELECT id FROM sequencias_email
        WHERE ativa = TRUE
              AND (origem = %s OR origem IS NULL)
              AND (produto_id = %s OR produto_id IS NULL)
        ORDER BY (origem IS NOT NULL)::int + (produto_id IS NOT NULL)::int DESC, id
        LIMIT 1
        """,
        (origem_cadastro, produto_id),
    ).fetchone()


def _enfileirar_sequencia_email(conn, prospect_id: int) -> None:
    """Matricula (ou, se ainda não mandou nada, reajusta) o prospect na sequência de
    e-mail mais específica pra ele, se elegível: tem e-mail, não descadastrou e está
    em etapa inicial do funil. Não mexe em quem já recebeu pelo menos um e-mail, pra
    não trocar o texto no meio da conversa."""
    prospect = conn.execute(
        "SELECT decisor_email, status, sequencia_email_id, sequencia_etapa_atual, "
        "email_opt_out, produto_id, origem_cadastro FROM prospects WHERE id = %s",
        (prospect_id,),
    ).fetchone()
    if not prospect or not prospect["decisor_email"] or prospect["email_opt_out"]:
        return
    if prospect["status"] not in ("fila", "contatado"):
        return
    if prospect["sequencia_email_id"] and prospect["sequencia_etapa_atual"] > 0:
        return

    sequencia = _melhor_sequencia_email(conn, prospect["origem_cadastro"], prospect["produto_id"])
    if not sequencia or sequencia["id"] == prospect["sequencia_email_id"]:
        return
    primeira_etapa = conn.execute(
        "SELECT dias_apos_anterior FROM sequencia_etapas WHERE sequencia_id = %s ORDER BY ordem LIMIT 1",
        (sequencia["id"],),
    ).fetchone()
    if not primeira_etapa:
        return
    conn.execute(
        "UPDATE prospects SET sequencia_email_id = %s, sequencia_etapa_atual = 0, "
        "proximo_envio_email = NOW() + (%s || ' days')::interval WHERE id = %s",
        (sequencia["id"], primeira_etapa["dias_apos_anterior"], prospect_id),
    )


def _registrar_panorama_regua(conn, registrar) -> None:
    """Quando a fila está vazia, diz por quê: quantos têm e-mail, quantos estão
    matriculados e o que está travando cada um. Sem isso, "0 disparados" no painel
    é indistinguível de "está tudo funcionando e ninguém venceu ainda"."""
    c = conn.execute(
        """
        SELECT COUNT(*) FILTER (WHERE decisor_email IS NOT NULL AND decisor_email <> '') AS com_email,
               COUNT(*) FILTER (WHERE sequencia_email_id IS NOT NULL) AS na_regua,
               COUNT(*) FILTER (WHERE email_opt_out) AS opt_out,
               COUNT(*) FILTER (WHERE decisor_email IS NOT NULL AND decisor_email <> ''
                                AND sequencia_email_id IS NULL AND email_opt_out = FALSE
                                AND status IN ('fila', 'contatado')) AS elegivel_fora
        FROM prospects
        """
    ).fetchone()
    registrar(
        f"panorama: {c['com_email']} com e-mail, {c['na_regua']} na régua, "
        f"{c['opt_out']} descadastrados, {c['elegivel_fora']} elegíveis fora da régua"
    )
    for r in conn.execute(
        "SELECT id, status, sequencia_etapa_atual, proximo_envio_email FROM prospects "
        "WHERE sequencia_email_id IS NOT NULL ORDER BY proximo_envio_email LIMIT 5"
    ).fetchall():
        registrar(
            f"  #{r['id']} status={r['status']} etapa={r['sequencia_etapa_atual']} "
            f"próximo={r['proximo_envio_email']}"
        )


def processar_fila_email() -> list[str]:
    """Rodado periodicamente pelo scheduler: envia o e-mail da vez pra quem estiver
    devido, e agenda a próxima etapa ou encerra a sequência. Devolve (e imprime no log)
    o que aconteceu em cada negócio, que é o único rastro de envio que sobra em produção."""
    relatorio: list[str] = []

    def registrar(linha: str) -> None:
        relatorio.append(linha)
        print(f"[fila-email] {linha}", flush=True)

    with get_connection() as conn:
        pendentes = conn.execute(
            """
            SELECT p.id, p.decisor_email, p.decisor_nome, p.nome AS empresa, p.sequencia_email_id,
                   p.sequencia_etapa_atual
            FROM prospects p
            WHERE p.sequencia_email_id IS NOT NULL AND p.proximo_envio_email <= NOW()
                  AND p.email_opt_out = FALSE AND p.status IN ('fila', 'contatado')
            """
        ).fetchall()
        registrar(f"{len(pendentes)} negócio(s) com e-mail vencido pra enviar")
        if not pendentes:
            _registrar_panorama_regua(conn, registrar)

        for p in pendentes:
            etapas = conn.execute(
                "SELECT assunto, corpo, dias_apos_anterior FROM sequencia_etapas "
                "WHERE sequencia_id = %s ORDER BY ordem",
                (p["sequencia_email_id"],),
            ).fetchall()
            if p["sequencia_etapa_atual"] >= len(etapas):
                registrar(f"#{p['id']} sequência concluída, saindo da régua")
                conn.execute(
                    "UPDATE prospects SET sequencia_email_id = NULL, proximo_envio_email = NULL WHERE id = %s",
                    (p["id"],),
                )
                continue

            etapa = etapas[p["sequencia_etapa_atual"]]
            token = _serializer_descadastro.dumps(p["id"])
            assunto = _preencher_template_email(etapa["assunto"], p["decisor_nome"], p["empresa"])
            corpo = _preencher_template_email(etapa["corpo"], p["decisor_nome"], p["empresa"])
            corpo += f"\n\n---\nNão quer mais receber esses e-mails? Cancele aqui: {BASE_URL}/email/descadastro/{token}"

            if not enviar_email(p["decisor_email"], assunto, corpo, REMETENTE_INSTITUCIONAL):
                registrar(f"#{p['id']} FALHOU o envio para {p['decisor_email']}, tenta de novo em 1h")
                conn.execute(
                    "UPDATE prospects SET proximo_envio_email = NOW() + INTERVAL '1 hour' WHERE id = %s",
                    (p["id"],),
                )
                continue

            registrar(f"#{p['id']} enviado para {p['decisor_email']} (etapa {p['sequencia_etapa_atual'] + 1}/{len(etapas)})")
            conn.execute(
                "INSERT INTO atividades (prospect_id, tipo, nota) VALUES (%s, 'email_automatico', %s)",
                (p["id"], f'Enviado: "{assunto}"'),
            )
            proxima_ordem = p["sequencia_etapa_atual"] + 1
            if proxima_ordem < len(etapas):
                dias = etapas[proxima_ordem]["dias_apos_anterior"]
                conn.execute(
                    "UPDATE prospects SET sequencia_etapa_atual = %s, "
                    "proximo_envio_email = NOW() + (%s || ' days')::interval WHERE id = %s",
                    (proxima_ordem, dias, p["id"]),
                )
            else:
                conn.execute(
                    "UPDATE prospects SET sequencia_etapa_atual = %s, sequencia_email_id = NULL, "
                    "proximo_envio_email = NULL WHERE id = %s",
                    (proxima_ordem, p["id"]),
                )
        conn.commit()
    return relatorio


def processar_fila_email_seguro() -> None:
    """Wrapper do scheduler: sem isso, uma exceção aqui dentro morre no APScheduler
    sem deixar rastro nenhum no log do Railway."""
    try:
        processar_fila_email()
    except Exception as exc:
        print(f"[fila-email] ERRO inesperado: {type(exc).__name__}: {exc}", flush=True)


def processar_respostas_email() -> None:
    """Rodado periodicamente pelo scheduler: lê a caixa de entrada, casa cada
    resposta com o prospect pelo e-mail do decisor, registra na linha do tempo
    e tira o lead da régua automática (a partir daí é conversa humana)."""
    respostas = buscar_respostas_novas()
    if not respostas:
        return
    with get_connection() as conn:
        for r in respostas:
            prospect = conn.execute(
                "SELECT id FROM prospects WHERE lower(decisor_email) = %s",
                (r["remetente"],),
            ).fetchone()
            if not prospect:
                continue
            nota = f'Resposta recebida: "{r["assunto"]}"'
            if r["trecho"]:
                nota += f"\n\n{r['trecho']}"
            conn.execute(
                "INSERT INTO atividades (prospect_id, tipo, nota) VALUES (%s, 'email_automatico', %s)",
                (prospect["id"], nota),
            )
            conn.execute(
                "UPDATE prospects SET sequencia_email_id = NULL, proximo_envio_email = NULL WHERE id = %s",
                (prospect["id"],),
            )
        conn.commit()


def processar_respostas_email_seguro() -> None:
    try:
        processar_respostas_email()
    except Exception as exc:
        print(f"[respostas-email] ERRO inesperado: {type(exc).__name__}: {exc}", flush=True)


BASE_URL = os.environ.get("BASE_URL", "https://crm.engenhariadeclientes.com.br")


def _verificar_email_no_boot() -> None:
    """Checa o login SMTP e, se EMAIL_TESTE_PARA estiver definida, manda um único
    e-mail de verificação. Roda fora do caminho do startup porque conexão de saída
    bloqueada fica pendurada bem além do timeout do smtplib."""
    try:
        print(f"[startup] provedor de e-mail ({provedor_email()}): {testar_envio_cache()}", flush=True)
        destino = (os.environ.get("EMAIL_TESTE_PARA") or "").strip()
        if destino:
            ok = enviar_email(
                destino,
                "CRM: teste de disparo automático",
                "Esse e-mail foi enviado pelo próprio CRM da Engenharia de Clientes para "
                "confirmar que o disparo automático está funcionando.\n\n"
                "Se ele chegou, a régua de e-mail consegue enviar normalmente.",
                REMETENTE_INSTITUCIONAL,
            )
            print(f"[startup] e-mail de teste para {destino}: {'enviado' if ok else 'FALHOU'}", flush=True)
    except Exception as exc:
        print(f"[startup] verificação de e-mail falhou: {type(exc).__name__}: {exc}", flush=True)


@app.on_event("startup")
def startup() -> None:
    aplicar_schema()
    # next_run_time=agora: sem isso o primeiro ciclo só rodaria 5 min depois de subir,
    # e todo deploy/restart zerava a contagem antes de qualquer envio acontecer.
    agora = datetime.now(timezone.utc)
    scheduler.add_job(
        processar_fila_email_seguro, "interval", minutes=5, id="fila_email",
        replace_existing=True, next_run_time=agora + timedelta(seconds=20),
    )
    scheduler.add_job(
        processar_respostas_email_seguro, "interval", minutes=5, id="respostas_email",
        replace_existing=True, next_run_time=agora + timedelta(seconds=40),
    )
    scheduler.start()
    print("[startup] scheduler ligado: fila de e-mail e leitura de respostas a cada 5 min", flush=True)
    # Numa thread separada: se o SMTP de saída estiver bloqueado, a conexão fica pendurada
    # e travaria a subida da aplicação inteira se rodasse aqui no caminho do startup.
    threading.Thread(target=_verificar_email_no_boot, daemon=True).start()


@app.get("/diagnostico/email")
def diagnostico_email(request: Request, token: str = "", teste_para: str = "", forcar: int = 0):
    """Raio-x da régua de e-mail pra depurar sem precisar de acesso ao banco: estado das
    credenciais, do scheduler e da fila. Protegido por DIAG_TOKEN (se a variável não
    estiver definida, a rota fica desligada)."""
    esperado = os.environ.get("DIAG_TOKEN")
    if not esperado or token != esperado:
        return PlainTextResponse("não encontrado", status_code=404)

    usuario, senha = credenciais_email()
    relatorio: dict = {
        "gmail_user": usuario,
        "senha_app_tamanho": len(senha) if senha else 0,
        "provedor": provedor_email(),
        "credencial": testar_envio(),
        "base_url": BASE_URL,
        "jobs": [
            {"id": j.id, "proxima_execucao": str(getattr(j, "next_run_time", None))}
            for j in scheduler.get_jobs()
        ],
    }

    if teste_para:
        ok = enviar_email(
            teste_para,
            "Teste da régua de e-mail do CRM",
            "Esse é um envio de teste automático do CRM da Engenharia de Clientes.\n"
            "Se você recebeu isso, o disparo automático está funcionando.",
            REMETENTE_INSTITUCIONAL,
        )
        relatorio["envio_teste"] = {"para": teste_para, "enviado": ok}

    with get_connection() as conn:
        contagens = conn.execute(
            """
            SELECT COUNT(*) FILTER (WHERE decisor_email IS NOT NULL AND decisor_email <> '') AS com_email,
                   COUNT(*) FILTER (WHERE sequencia_email_id IS NOT NULL) AS matriculados,
                   COUNT(*) FILTER (WHERE email_opt_out) AS opt_out,
                   COUNT(*) FILTER (WHERE sequencia_email_id IS NOT NULL AND proximo_envio_email <= NOW()
                                    AND email_opt_out = FALSE AND status IN ('fila', 'contatado')) AS vencidos
            FROM prospects
            """
        ).fetchone()
        relatorio["contagens"] = dict(contagens)
        relatorio["sequencias_ativas"] = [
            dict(r)
            for r in conn.execute(
                "SELECT s.id, s.nome, s.origem, s.produto_id, "
                "(SELECT COUNT(*) FROM sequencia_etapas e WHERE e.sequencia_id = s.id) AS etapas "
                "FROM sequencias_email s WHERE s.ativa = TRUE ORDER BY s.id"
            ).fetchall()
        ]
        relatorio["na_regua"] = [
            {
                "id": r["id"], "nome": r["nome"], "email": r["decisor_email"], "status": r["status"],
                "sequencia_id": r["sequencia_email_id"], "etapa": r["sequencia_etapa_atual"],
                "proximo_envio": str(r["proximo_envio_email"]),
            }
            for r in conn.execute(
                "SELECT id, nome, decisor_email, status, sequencia_email_id, sequencia_etapa_atual, "
                "proximo_envio_email FROM prospects WHERE sequencia_email_id IS NOT NULL "
                "ORDER BY proximo_envio_email LIMIT 20"
            ).fetchall()
        ]
        relatorio["com_email_fora_da_regua"] = [
            {"id": r["id"], "nome": r["nome"], "email": r["decisor_email"], "status": r["status"],
             "opt_out": r["email_opt_out"]}
            for r in conn.execute(
                "SELECT id, nome, decisor_email, status, email_opt_out FROM prospects "
                "WHERE decisor_email IS NOT NULL AND decisor_email <> '' AND sequencia_email_id IS NULL "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
        ]
        relatorio["ultimas_atividades_email"] = [
            {"prospect_id": r["prospect_id"], "nota": r["nota"], "criado_em": str(r["criado_em"])}
            for r in conn.execute(
                "SELECT prospect_id, nota, criado_em FROM atividades WHERE tipo = 'email_automatico' "
                "ORDER BY id DESC LIMIT 10"
            ).fetchall()
        ]

    if forcar:
        relatorio["execucao_forcada"] = processar_fila_email()

    return JSONResponse(relatorio)


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
def buscar(
    request: Request,
    categoria: str = Form(...),
    cidade: str = Form(...),
    max_resultados: int = Form(40),
    produto_id: str = Form(""),
):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)

    api_key = os.environ["GOOGLE_PLACES_API_KEY"]
    categoria = categoria.strip()
    cidade = cidade.strip()
    query = f"{categoria} em {cidade}"
    max_resultados = max(1, min(max_resultados, 120))
    produto_val = int(produto_id) if produto_id else None

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
            site = lugar.get("websiteUri")
            email_captado = buscar_email_no_site(site) if site else None
            row = conn.execute(
                """
                INSERT INTO prospects (prospeccao_id, nome, telefone, endereco, cidade, uf, categoria, categoria_aquisicao_id, site, decisor_email, email_origem, origem_cadastro, produto_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'busca_automatica', %s)
                ON CONFLICT (telefone) WHERE telefone IS NOT NULL DO NOTHING
                RETURNING id
                """,
                (
                    prospeccao_id, nome, telefone, lugar.get("formattedAddress"), lugar_cidade or cidade, uf,
                    categoria, categoria_aquisicao_id, site,
                    email_captado, "site" if email_captado else None, produto_val,
                ),
            ).fetchone()
            if row:
                novos += 1
                if email_captado:
                    _enfileirar_sequencia_email(conn, row["id"])

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
                   ca.nome AS canal_aquisicao_nome, cat.nome AS categoria_aquisicao_nome,
                   se.nome AS sequencia_nome,
                   (SELECT COUNT(*) FROM sequencia_etapas WHERE sequencia_id = se.id) AS sequencia_total_etapas
            FROM prospects p
            LEFT JOIN consultores c ON c.id = p.consultor_id
            LEFT JOIN produtos pr ON pr.id = p.produto_id
            LEFT JOIN motivos_perda m ON m.id = p.motivo_perda_id
            LEFT JOIN canais_aquisicao ca ON ca.id = p.canal_aquisicao_id
            LEFT JOIN categorias_aquisicao cat ON cat.id = p.categoria_aquisicao_id
            LEFT JOIN sequencias_email se ON se.id = p.sequencia_email_id
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
                temperatura = %s,
                email_origem = CASE WHEN decisor_email IS DISTINCT FROM %s THEN 'manual' ELSE email_origem END,
                atualizado_em = NOW()
            WHERE id = %s
            """,
            (
                produto_val, valor_val, previsao_val, observacoes_produto.strip() or None,
                canal_val, categoria_val,
                decisor_nome.strip() or None, decisor_telefone.strip() or None, decisor_email.strip() or None,
                decisor_endereco.strip() or None, decisor_aniversario or None, decisor_redes_sociais.strip() or None,
                temperatura_val,
                decisor_email.strip() or None,
                prospect_id,
            ),
        )
        _enfileirar_sequencia_email(conn, prospect_id)
        conn.commit()
    return RedirectResponse(url=f"/prospects/{prospect_id}", status_code=303)


@app.post("/prospects/{prospect_id}/email/matricular")
def prospect_matricular_email(request: Request, prospect_id: int):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        _enfileirar_sequencia_email(conn, prospect_id)
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
def admin_dashboard(request: Request, data_de: str = "", data_ate: str = ""):
    redirect = exigir_admin(request)
    if redirect:
        return redirect

    hoje_date = datetime.now(timezone.utc).date()
    hoje = hoje_date.isoformat()
    seis_dias_atras = (hoje_date - timedelta(days=6)).isoformat()
    vinte_nove_dias_atras = (hoje_date - timedelta(days=29)).isoformat()
    data_de = data_de or hoje
    data_ate = data_ate or hoje

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
            WHERE a.criado_em::date BETWEEN %s AND %s
            GROUP BY c.nome
            ORDER BY total DESC
            """,
            (data_de, data_ate),
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

        metricas_email = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM prospects WHERE decisor_email IS NOT NULL) AS total_contatos_email,
              (SELECT COUNT(*) FROM atividades WHERE tipo = 'email_automatico' AND nota LIKE 'Enviado:%%') AS emails_disparados,
              (SELECT COUNT(DISTINCT prospect_id) FROM atividades WHERE tipo = 'email_automatico' AND nota LIKE 'Resposta recebida:%%') AS emails_respondidos
            """
        ).fetchone()

        contexto = _contexto_base(request, conn)

    contexto.update({
        "metricas_email": metricas_email,
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
        "data_de": data_de,
        "data_ate": data_ate,
        "hoje": hoje,
        "seis_dias_atras": seis_dias_atras,
        "vinte_nove_dias_atras": vinte_nove_dias_atras,
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


# --------------------------------------------------------- e-mail automático

@app.get("/email/descadastro/{token}")
def email_descadastro(token: str):
    try:
        prospect_id = _serializer_descadastro.loads(token)
    except BadSignature:
        return PlainTextResponse("Link inválido.", status_code=400)
    with get_connection() as conn:
        conn.execute(
            "UPDATE prospects SET email_opt_out = TRUE, sequencia_email_id = NULL, "
            "proximo_envio_email = NULL WHERE id = %s",
            (prospect_id,),
        )
        conn.commit()
    return PlainTextResponse("Você não vai mais receber e-mails automáticos nossos. Obrigado.")


ORIGEM_CADASTRO_LABEL = {
    "busca_automatica": "Busca automática (outbound)",
    "manual": "Cadastro manual",
    "ads": "Anúncios",
}


@app.get("/sequencias-email")
def sequencias_email_lista(
    request: Request,
    recap_processados: str = "",
    recap_sites: str = "",
    recap_emails: str = "",
    recap_erros: str = "",
    recap_erro: str = "",
):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        sequencias = conn.execute(
            """
            SELECT s.id, s.nome, s.ativa, s.origem, s.produto_id, p.nome AS produto_nome
            FROM sequencias_email s LEFT JOIN produtos p ON p.id = s.produto_id
            ORDER BY s.nome
            """
        ).fetchall()
        etapas = conn.execute(
            "SELECT id, sequencia_id, ordem, dias_apos_anterior, assunto, corpo FROM sequencia_etapas ORDER BY sequencia_id, ordem"
        ).fetchall()
        produtos = conn.execute("SELECT id, nome FROM produtos ORDER BY nome").fetchall()
        candidatos_matricula = conn.execute(
            "SELECT COUNT(*) AS total FROM prospects "
            "WHERE decisor_email IS NOT NULL AND email_opt_out = FALSE "
            "AND status IN ('fila', 'contatado') AND sequencia_email_id IS NULL"
        ).fetchone()["total"]
        candidatos_recaptura = conn.execute(
            "SELECT COUNT(*) AS total FROM prospects "
            "WHERE site IS NOT NULL AND decisor_email IS NULL AND status IN ('fila', 'contatado')"
        ).fetchone()["total"]
        candidatos_sem_site = conn.execute(
            "SELECT COUNT(*) AS total FROM prospects "
            "WHERE site IS NULL AND decisor_email IS NULL AND status IN ('fila', 'contatado')"
        ).fetchone()["total"]
        contexto = _contexto_base(request, conn)
    etapas_por_sequencia: dict[int, list] = {}
    for e in etapas:
        etapas_por_sequencia.setdefault(e["sequencia_id"], []).append(e)
    contexto.update({
        "sequencias": sequencias,
        "etapas_por_sequencia": etapas_por_sequencia,
        "produtos": produtos,
        "origem_label": ORIGEM_CADASTRO_LABEL,
        "candidatos_matricula": candidatos_matricula,
        "candidatos_recaptura": candidatos_recaptura,
        "candidatos_sem_site": candidatos_sem_site,
        "recap_processados": recap_processados,
        "recap_sites": recap_sites,
        "recap_emails": recap_emails,
        "recap_erros": recap_erros,
        "recap_erro": recap_erro,
        "email_provedor": provedor_email(),
        "email_credencial": testar_envio_cache(),
    })
    return templates.TemplateResponse("sequencias_email.html", contexto)


@app.post("/sequencias-email/matricular-existentes")
def sequencias_email_matricular_existentes(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM prospects WHERE decisor_email IS NOT NULL AND email_opt_out = FALSE "
                "AND status IN ('fila', 'contatado') AND sequencia_email_id IS NULL"
            ).fetchall()
        ]
        for prospect_id in ids:
            _enfileirar_sequencia_email(conn, prospect_id)
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)


@app.post("/sequencias-email/recapturar-emails")
def sequencias_email_recapturar_emails(request: Request):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        candidatos = conn.execute(
            "SELECT id, site FROM prospects WHERE site IS NOT NULL AND decisor_email IS NULL "
            "AND status IN ('fila', 'contatado') LIMIT 50"
        ).fetchall()
        for c in candidatos:
            email_captado = buscar_email_no_site(c["site"])
            if email_captado:
                conn.execute(
                    "UPDATE prospects SET decisor_email = %s, email_origem = 'site' WHERE id = %s",
                    (email_captado, c["id"]),
                )
                _enfileirar_sequencia_email(conn, c["id"])
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)


@app.post("/sequencias-email/recapturar-sites")
def sequencias_email_recapturar_sites(request: Request):
    """Pra leads antigos que nunca tiveram o site capturado (de antes dessa
    funcionalidade existir): busca de novo no Google Places por nome+cidade só
    pra achar o site, e a partir dele tenta o e-mail. Cada item aqui consome
    uma chamada paga da API do Google, então o lote é bem menor que o de
    recapturar-emails (que é de graça, só visita o site que já se conhece)."""
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        return RedirectResponse(url="/sequencias-email?recap_erro=sem_api_key", status_code=303)

    processados = sites_achados = emails_achados = erros = 0
    with get_connection() as conn:
        candidatos = conn.execute(
            "SELECT id, nome, cidade FROM prospects WHERE site IS NULL AND decisor_email IS NULL "
            "AND status IN ('fila', 'contatado') AND nome IS NOT NULL LIMIT 20"
        ).fetchall()
        for c in candidatos:
            processados += 1
            query = f"{c['nome']} {c['cidade']}" if c["cidade"] else c["nome"]
            try:
                primeiro = next(buscar_empresas(api_key, query, max_resultados=1), None)
            except Exception as exc:
                erros += 1
                print(f"[recapturar-sites] erro buscando '{query}': {exc}")
                continue
            if not primeiro:
                continue
            site = primeiro.get("websiteUri")
            if not site:
                continue
            sites_achados += 1
            email_captado = buscar_email_no_site(site)
            conn.execute(
                "UPDATE prospects SET site = %s, decisor_email = COALESCE(decisor_email, %s), "
                "email_origem = CASE WHEN %s IS NOT NULL THEN 'site' ELSE email_origem END WHERE id = %s",
                (site, email_captado, email_captado, c["id"]),
            )
            if email_captado:
                emails_achados += 1
                _enfileirar_sequencia_email(conn, c["id"])
        conn.commit()
    return RedirectResponse(
        url=f"/sequencias-email?recap_processados={processados}&recap_sites={sites_achados}"
            f"&recap_emails={emails_achados}&recap_erros={erros}",
        status_code=303,
    )


@app.post("/sequencias-email")
def sequencias_email_criar(
    request: Request,
    nome: str = Form(...),
    origem: str = Form(""),
    produto_id: str = Form(""),
):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sequencias_email (nome, origem, produto_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (nome) DO NOTHING",
            (nome.strip(), origem or None, int(produto_id) if produto_id else None),
        )
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)


@app.post("/sequencias-email/{sequencia_id}/toggle")
def sequencias_email_toggle(request: Request, sequencia_id: int):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("UPDATE sequencias_email SET ativa = NOT ativa WHERE id = %s", (sequencia_id,))
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)


@app.post("/sequencias-email/{sequencia_id}/etapas")
def sequencia_etapa_criar(
    request: Request,
    sequencia_id: int,
    dias_apos_anterior: int = Form(0),
    assunto: str = Form(...),
    corpo: str = Form(...),
):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        proxima_ordem = conn.execute(
            "SELECT COALESCE(MAX(ordem), 0) + 1 AS ordem FROM sequencia_etapas WHERE sequencia_id = %s",
            (sequencia_id,),
        ).fetchone()["ordem"]
        conn.execute(
            "INSERT INTO sequencia_etapas (sequencia_id, ordem, dias_apos_anterior, assunto, corpo) "
            "VALUES (%s, %s, %s, %s, %s)",
            (sequencia_id, proxima_ordem, dias_apos_anterior, assunto.strip(), corpo.strip()),
        )
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)


@app.post("/sequencias-email/etapas/{etapa_id}/excluir")
def sequencia_etapa_excluir(request: Request, etapa_id: int):
    redirect = exigir_admin(request)
    if redirect:
        return redirect
    with get_connection() as conn:
        conn.execute("DELETE FROM sequencia_etapas WHERE id = %s", (etapa_id,))
        conn.commit()
    return RedirectResponse(url="/sequencias-email", status_code=303)
