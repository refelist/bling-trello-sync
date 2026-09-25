import time

import httpx
import pytest

from bling_trello_sync.bling import BlingClient
from bling_trello_sync.storage import Storage, TokenBling


@pytest.fixture
def storage_com_token(settings) -> Storage:
    storage = Storage(settings.database_path)
    storage.salvar_token(TokenBling("token", "refresh", time.time() + 3600))
    return storage


def _cliente(settings, storage, respostas: list[httpx.Response]) -> BlingClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return respostas.pop(0)

    return BlingClient(settings, storage, httpx.Client(transport=httpx.MockTransport(handler)))


def test_get_repete_apos_limite_de_taxa(settings, storage_com_token, monkeypatch):
    monkeypatch.setattr("bling_trello_sync.bling.time.sleep", lambda _: None)
    respostas = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"data": {"id": 1}}),
    ]
    bling = _cliente(settings, storage_com_token, respostas)

    assert bling.obter_pedido_venda(1) == {"id": 1}
    assert respostas == []


def test_get_desiste_apos_varias_respostas_429(settings, storage_com_token, monkeypatch):
    monkeypatch.setattr("bling_trello_sync.bling.time.sleep", lambda _: None)
    respostas = [httpx.Response(429) for _ in range(6)]
    bling = _cliente(settings, storage_com_token, respostas)

    with pytest.raises(httpx.HTTPStatusError):
        bling.obter_pedido_venda(1)
