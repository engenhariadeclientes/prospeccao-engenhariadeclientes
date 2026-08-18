# prospeccao-engenhariadeclientes

App web de prospecção ativa B2B. Quem aciona digita **categoria** (livre, ex.:
"garantidora de receita condominial") e **cidade** (livre, ex.: "Blumenau, SC"),
o sistema busca empresas via Google Places API e monta uma fila de leads pra
abordagem manual — sem disparo automático de WhatsApp (contato frio via API
oficial exige template aprovado pela Meta e arrisca bloquear o número
comercial; ver decisão de 17/08/2026).

**Stack:** FastAPI + PostgreSQL, deploy no Railway.

## Fluxo

1. Operador busca por categoria + cidade na home (autenticado)
2. Sistema chama a Google Places API (Text Search) e grava os resultados com
   telefone válido em `prospects` (dedup automático por telefone)
3. Prospects entram com `status=fila` no funil (Kanban); o consultor aborda
   manualmente (ligação ou WhatsApp — qualquer um que o prospect tiver),
   registra o resultado do contato e move o status (fila → contatado →
   negociando → fechado/sem interesse)

## Login

Não tem autocadastro — o primeiro acesso é criado em `/setup` (só fica ativo
enquanto não existir nenhum consultor cadastrado). Depois disso, novos
consultores são adicionados por quem já está logado, em "Consultores".

## Variáveis de ambiente

- `DATABASE_URL` — Postgres (Railway injeta automaticamente se o serviço
  estiver linkado ao plugin Postgres do projeto)
- `GOOGLE_PLACES_API_KEY` — chave da Places API (New), habilitada no Google
  Cloud Console, com faturamento ativo
- `SESSION_SECRET` — chave aleatória usada pra assinar o cookie de sessão do
  login (gera com `python -c "import secrets; print(secrets.token_hex(32))"`)

## Setup local

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://...
export GOOGLE_PLACES_API_KEY=...
export SESSION_SECRET=...
uvicorn app.main:app --reload
```

O schema (`sql/*.sql`) é aplicado automaticamente no startup do app.