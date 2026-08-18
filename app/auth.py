"""Login simples por usuário/senha (poucos consultores, sem autocadastro)."""
import hashlib
import os

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.db import get_connection


def gerar_hash(senha: str) -> str:
    salt = os.urandom(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, 100_000)
    return f"{salt.hex()}${derivado.hex()}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    salt_hex, derivado_hex = senha_hash.split("$")
    salt = bytes.fromhex(salt_hex)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, 100_000)
    return derivado.hex() == derivado_hex


def autenticar(usuario: str, senha: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, nome, usuario, senha_hash, is_admin FROM consultores WHERE usuario = %s",
            (usuario,),
        ).fetchone()
    if row and verificar_senha(senha, row["senha_hash"]):
        return {"id": row["id"], "nome": row["nome"], "usuario": row["usuario"], "is_admin": row["is_admin"]}
    return None


def existe_algum_consultor() -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM consultores LIMIT 1").fetchone()
    return row is not None


def consultor_logado(request: Request) -> dict | None:
    return request.session.get("consultor")


def exigir_login(request: Request):
    consultor = consultor_logado(request)
    if not consultor:
        return RedirectResponse(url="/login", status_code=303)
    return None


def exigir_admin(request: Request):
    redirect = exigir_login(request)
    if redirect:
        return redirect
    consultor = consultor_logado(request)
    if not consultor.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)
    return None
