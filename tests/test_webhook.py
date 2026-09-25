import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from bling_trello_sync.bling import validar_assinatura
from bling_trello_sync.config import get_settings
from bling_trello_sync.main import app, extrair_id_pedido, get_sincronizador
from bling_trello_sync.storage import Storage


class SincronizadorFake:
    def __init__(self) -> None:
        self.chamadas: list[int] = []

    def sincronizar_pedido(self, pedido_id: int):
        self.chamadas.append(pedido_id)
        return type("R", (), {"acao": "card_criado"})()


def _assinar(corpo: bytes, segredo: str) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def cliente(settings):
    Storage(settings.database_path)
    sincronizador = SincronizadorFake()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sincronizador] = lambda: sincronizador
    yield TestClient(app), sincronizador
    app.dependency_overrides.clear()


def test_validacao_de_assinatura():
    corpo = b'{"eventId":"1"}'
    assert validar_assinatura(corpo, _assinar(corpo, "segredo"), "segredo")
    assert not validar_assinatura(corpo, "sha256=deadbeef", "segredo")
    assert not validar_assinatura(corpo, None, "segredo")


def test_extrai_id_do_pedido():
    assert extrair_id_pedido({"id": 42}) == 42
    assert extrair_id_pedido({"pedido": {"id": "42"}}) == 42
    assert extrair_id_pedido({"numero": 7}) is None


def test_webhook_rejeita_assinatura_invalida(cliente):
    client, _ = cliente
    resposta = client.post(
        "/webhooks/bling",
        content=json.dumps({"eventId": "e1", "event": "order.created", "data": {"id": 1}}),
        headers={"X-Bling-Signature-256": "sha256=invalida"},
    )
    assert resposta.status_code == 401


def test_webhook_sincroniza_pedido(cliente, settings):
    client, sincronizador = cliente
    corpo = json.dumps({"eventId": "e1", "event": "order.created", "data": {"id": 12345678}}).encode()

    resposta = client.post(
        "/webhooks/bling",
        content=corpo,
        headers={"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)},
    )

    assert resposta.status_code == 202
    assert sincronizador.chamadas == [12345678]


def test_webhook_e_idempotente(cliente, settings):
    client, sincronizador = cliente
    corpo = json.dumps({"eventId": "e1", "event": "order.updated", "data": {"id": 99}}).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)}

    primeira = client.post("/webhooks/bling", content=corpo, headers=headers)
    segunda = client.post("/webhooks/bling", content=corpo, headers=headers)

    assert primeira.status_code == 202
    assert segunda.json()["status"] == "ignorado"
    assert len(sincronizador.chamadas) == 1


def test_webhook_ignora_outros_recursos(cliente, settings):
    client, sincronizador = cliente
    corpo = json.dumps({"eventId": "e2", "event": "product.created", "data": {"id": 1}}).encode()

    resposta = client.post(
        "/webhooks/bling",
        content=corpo,
        headers={"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)},
    )

    assert resposta.json()["status"] == "ignorado"
    assert sincronizador.chamadas == []
