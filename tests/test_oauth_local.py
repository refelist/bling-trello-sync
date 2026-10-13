import secrets
from urllib.parse import parse_qs, urlparse

import pytest

from bling_trello_sync.oauth_local import autorizar


class BlingFake:
    def __init__(self) -> None:
        self.settings = type("S", (), {"bling_redirect_uri": "https://exemplo.com/callback"})()
        self.ultimo_state: str | None = None
        self.codigo: str | None = None

    def url_de_autorizacao(self, state: str) -> str:
        self.ultimo_state = state
        return f"https://bling.example/authorize?state={state}"

    def trocar_codigo_por_token(self, code: str):
        self.codigo = code
        return type("T", (), {"access_token": "a", "refresh_token": "r", "expira_em": 1.0})()


def test_autorizar_cli_rejeita_state_invalido(monkeypatch):
    bling = BlingFake()
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://exemplo.com/callback?code=abc&state=errado",
    )
    with pytest.raises(RuntimeError, match="state"):
        autorizar(bling)


def test_autorizar_cli_aceita_state_correto(monkeypatch):
    bling = BlingFake()
    state_box: dict[str, str] = {}

    def fake_url(state: str) -> str:
        state_box["state"] = state
        return f"https://bling.example/authorize?state={state}"

    bling.url_de_autorizacao = fake_url  # type: ignore[method-assign]

    def responder(_: str) -> str:
        return f"https://exemplo.com/callback?code=codigo-ok&state={state_box['state']}"

    monkeypatch.setattr("builtins.input", responder)
    token = autorizar(bling)
    assert bling.codigo == "codigo-ok"
    assert token.access_token == "a"


def test_compare_digest_exige_state_exato():
    esperado = secrets.token_urlsafe(16)
    query = parse_qs(urlparse(f"https://x/?code=1&state={esperado}").query)
    assert secrets.compare_digest((query.get("state") or [""])[0], esperado)
