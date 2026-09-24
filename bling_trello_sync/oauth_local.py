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


class _Handler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self) -> None:  # noqa: N802 - assinatura exigida por BaseHTTPRequestHandler
        query = parse_qs(urlparse(self.path).query)
        _Handler.code = (query.get("code") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGINA_OK)

    def log_message(self, *args: object) -> None:
        return


def _e_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in {"localhost", "127.0.0.1"}


def autorizar(bling: BlingClient) -> TokenBling:
    """Conduz o fluxo de autorização e devolve os tokens (já persistidos)."""
    url = bling.url_de_autorizacao(state=secrets.token_urlsafe(16))
    redirect_uri = bling.settings.bling_redirect_uri
    print("Abra a URL abaixo no navegador e autorize o aplicativo:\n")
    print(url, "\n")

    if _e_local(redirect_uri):
        destino = urlparse(redirect_uri)
        servidor = HTTPServer((destino.hostname or "localhost", destino.port or 80), _Handler)
        print(f"Aguardando o retorno em {redirect_uri} ...")
        servidor.handle_request()
        servidor.server_close()
        code = _Handler.code
    else:
        code = input("Cole aqui o valor do parâmetro 'code' da URL de retorno: ").strip()

    if not code:
        raise RuntimeError("Nenhum 'code' recebido. Refaça a autorização.")
    return bling.trocar_codigo_por_token(code)
