"""Conexões de saída forçadas em IPv4.

O container do Railway não tem rota IPv6 de saída, mas smtp.gmail.com e
imap.gmail.com anunciam AAAA — o Python tentava o IPv6 primeiro e morria com
"[Errno 101] Network is unreachable", o que derrubava todo o envio automático.
"""
import socket


def conectar_ipv4(host: str, porta: int, timeout: float | None = None, source_address=None) -> socket.socket:
    ultimo_erro: OSError | None = None
    for _familia, tipo, proto, _canonico, endereco in socket.getaddrinfo(
        host, porta, socket.AF_INET, socket.SOCK_STREAM
    ):
        sock = socket.socket(socket.AF_INET, tipo, proto)
        try:
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(endereco)
            return sock
        except OSError as exc:
            sock.close()
            ultimo_erro = exc
    raise ultimo_erro or OSError(f"nenhum endereço IPv4 para {host}:{porta}")
