"""Autorização OAuth2 do Bling executada localmente, sem precisar de servidor publicado."""

import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .bling import BlingClient
from .storage import TokenBling

PAGINA_OK = b"""<html><head><meta charset="utf-8"></head>
<body style="font-family: sans-serif">
<h2>Autorizacao concluida</h2><p>Pode fechar esta aba e voltar ao terminal.</p>
</body></html>"""

PAGINA_ERRO = b"""<html><head><meta charset="utf-8"></head>
<body style="font-family: sans-serif">
<h2>Falha na autorizacao</h2><p>State invalido ou ausente. Feche e tente de novo no terminal.</p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    esperado: str = ""

    def do_GET(self) -> None:  # noqa: N802 - assinatura exigida por BaseHTTPRequestHandler
        query = parse_qs(urlparse(self.path).query)
        code = (query.get("code") or [None])[0]
        state = (query.get("state") or [None])[0]
        ok = bool(code) and bool(state) and secrets.compare_digest(state, _Handler.esperado)
        if ok:
            _Handler.code = code
            _Handler.state = state
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGINA_OK if ok else PAGINA_ERRO)

    def log_message(self, *args: object) -> None:
        return


def _e_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in {"localhost", "127.0.0.1"}


def autorizar(bling: BlingClient) -> TokenBling:
    """Conduz o fluxo de autorização e devolve os tokens (já persistidos)."""
    esperado = secrets.token_urlsafe(16)
    url = bling.url_de_autorizacao(state=esperado)
    redirect_uri = bling.settings.bling_redirect_uri
    print("Abra a URL abaixo no navegador e autorize o aplicativo:\n")
    print(url, "\n")

    if _e_local(redirect_uri):
        destino = urlparse(redirect_uri)
        _Handler.esperado = esperado
        _Handler.code = None
        _Handler.state = None
        servidor = HTTPServer((destino.hostname or "localhost", destino.port or 80), _Handler)
        print(f"Aguardando o retorno em {redirect_uri} ...")
        servidor.handle_request()
        servidor.server_close()
        code = _Handler.code
        state = _Handler.state
    else:
        retorno = input(
            "Cole aqui a URL completa de retorno (com code e state): "
        ).strip()
        query = parse_qs(urlparse(retorno).query)
        code = (query.get("code") or [None])[0]
        state = (query.get("state") or [None])[0]
        if not code and retorno and "://" not in retorno:
            # Compatibilidade: só o code, se o usuário colar o valor antigo.
            code = retorno
            state = input("Cole também o parâmetro 'state' da URL de retorno: ").strip() or None

    if not code:
        raise RuntimeError("Nenhum 'code' recebido. Refaça a autorização.")
    if not state or not secrets.compare_digest(state, esperado):
        raise RuntimeError("Parâmetro 'state' inválido ou ausente. Refaça a autorização.")
    return bling.trocar_codigo_por_token(code)
