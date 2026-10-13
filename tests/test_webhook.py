import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from bling_trello_sync.bling import validar_assinatura
from bling_trello_sync.config import get_settings
from bling_trello_sync.main import app, extrair_id_pedido, get_sincronizador, get_sincronizador_compras
from bling_trello_sync.storage import Storage


class SincronizadorFake:
    def __init__(self, falhar: bool = False) -> None:
        self.chamadas: list[int] = []
        self.falhar = falhar

    def sincronizar_pedido(self, pedido_id: int):
        self.chamadas.append(pedido_id)
        if self.falhar:
            raise RuntimeError("falha simulada")
        return type("R", (), {"acao": "card_criado"})()


def _assinar(corpo: bytes, segredo: str) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def cliente(settings):
    settings.api_token = "token-teste"
    Storage(settings.database_path)
    sincronizador = SincronizadorFake()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sincronizador] = lambda: sincronizador
    app.dependency_overrides[get_sincronizador_compras] = lambda: sincronizador
    yield TestClient(app), sincronizador, settings
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
    client, _, _ = cliente
    resposta = client.post(
        "/webhooks/bling",
        content=json.dumps({"eventId": "e1", "event": "order.created", "data": {"id": 1}}),
        headers={"X-Bling-Signature-256": "sha256=invalida"},
    )
    assert resposta.status_code == 401


def test_webhook_sincroniza_pedido(cliente, settings):
    client, sincronizador, _ = cliente
    corpo = json.dumps({"eventId": "e1", "event": "order.created", "data": {"id": 12345678}}).encode()

    resposta = client.post(
        "/webhooks/bling",
        content=corpo,
        headers={"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)},
    )

    assert resposta.status_code == 202
    assert sincronizador.chamadas == [12345678]
    assert Storage(settings.database_path).evento_ja_processado("e1")


def test_webhook_e_idempotente(cliente, settings):
    client, sincronizador, _ = cliente
    corpo = json.dumps({"eventId": "e1", "event": "order.updated", "data": {"id": 99}}).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)}

    primeira = client.post("/webhooks/bling", content=corpo, headers=headers)
    segunda = client.post("/webhooks/bling", content=corpo, headers=headers)

    assert primeira.status_code == 202
    assert segunda.json()["status"] == "ignorado"
    assert len(sincronizador.chamadas) == 1


def test_webhook_reprocessa_quando_a_sincronizacao_falha(settings):
    settings.api_token = "token-teste"
    Storage(settings.database_path)
    sincronizador = SincronizadorFake(falhar=True)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sincronizador] = lambda: sincronizador
    client = TestClient(app)
    corpo = json.dumps({"eventId": "e-falha", "event": "order.created", "data": {"id": 7}}).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)}

    primeira = client.post("/webhooks/bling", content=corpo, headers=headers)
    assert primeira.status_code == 202
    assert not Storage(settings.database_path).evento_ja_processado("e-falha")

    sincronizador.falhar = False
    segunda = client.post("/webhooks/bling", content=corpo, headers=headers)
    assert segunda.status_code == 202
    assert sincronizador.chamadas == [7, 7]
    assert Storage(settings.database_path).evento_ja_processado("e-falha")
    app.dependency_overrides.clear()


def test_claim_atomico_impede_dois_processamentos(settings):
    storage = Storage(settings.database_path)
    assert storage.reclamar_evento("e-dup")
    assert not storage.reclamar_evento("e-dup")
    storage.liberar_evento("e-dup")
    assert storage.reclamar_evento("e-dup")
    storage.concluir_evento("e-dup")
    assert storage.evento_ja_processado("e-dup")
    assert not storage.reclamar_evento("e-dup")


def test_webhook_libera_evento_quando_pedido_e_ignorado(settings):
    settings.api_token = "token-teste"
    Storage(settings.database_path)

    class Ignorado:
        def sincronizar_pedido(self, pedido_id: int):
            return type("R", (), {"acao": "ignorado"})()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sincronizador] = lambda: Ignorado()
    client = TestClient(app)
    corpo = json.dumps({"eventId": "e-ign", "event": "order.created", "data": {"id": 5}}).encode()
    headers = {"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)}

    assert client.post("/webhooks/bling", content=corpo, headers=headers).status_code == 202
    assert not Storage(settings.database_path).evento_ja_processado("e-ign")
    # Sem claim residual: um novo envio pode ser processado.
    assert Storage(settings.database_path).reclamar_evento("e-ign")
    app.dependency_overrides.clear()


def test_webhook_ignora_outros_recursos(cliente, settings):
    client, sincronizador, _ = cliente
    corpo = json.dumps({"eventId": "e2", "event": "product.created", "data": {"id": 1}}).encode()

    resposta = client.post(
        "/webhooks/bling",
        content=corpo,
        headers={"X-Bling-Signature-256": _assinar(corpo, settings.bling_client_secret)},
    )

    assert resposta.json()["status"] == "ignorado"
    assert sincronizador.chamadas == []


def test_rotas_administrativas_exigem_token(cliente):
    client, _, _ = cliente
    assert client.get("/trello/listas").status_code == 401
    assert client.post("/sincronizar/1").status_code == 401
    assert client.post("/sincronizar-compra/1").status_code == 401
    assert client.post("/oauth/bling/ticket").status_code == 401
    assert client.get("/oauth/bling/autorizar").status_code == 401
    assert client.get("/trello/listas", params={"token": "token-teste"}).status_code == 401


def test_sincronizar_manual_aceita_bearer(cliente):
    client, sincronizador, settings = cliente
    resposta = client.post(
        "/sincronizar/42",
        headers={"Authorization": f"Bearer {settings.api_token}"},
    )
    assert resposta.status_code == 200
    assert sincronizador.chamadas == [42]


def test_healthz_continua_aberto(cliente):
    client, _, _ = cliente
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_exige_token_bling(cliente, settings):
    import time

    from bling_trello_sync.storage import TokenBling

    client, _, _ = cliente
    assert client.get("/readyz").status_code == 503
    Storage(settings.database_path).salvar_token(TokenBling("a", "r", time.time() + 3600))
    assert client.get("/readyz").json() == {"status": "ready"}


def test_oauth_ticket_abre_autorizar(cliente, settings):
    client, _, _ = cliente
    ticket_resp = client.post(
        "/oauth/bling/ticket",
        headers={"Authorization": f"Bearer {settings.api_token}"},
    )
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()["ticket"]

    class BlingFake:
        def url_de_autorizacao(self, state: str) -> str:
            return f"https://bling.example/authorize?state={state}"

    from bling_trello_sync.main import get_bling

    app.dependency_overrides[get_bling] = lambda: BlingFake()
    resposta = client.get("/oauth/bling/autorizar", params={"ticket": ticket}, follow_redirects=False)
    assert resposta.status_code in (302, 307)
    # Ticket é de uso único.
    assert client.get("/oauth/bling/autorizar", params={"ticket": ticket}).status_code == 401


def test_oauth_callback_rejeita_state_invalido(cliente):
    client, _, _ = cliente
    resposta = client.get("/oauth/bling/callback", params={"code": "abc", "state": "errado"})
    assert resposta.status_code == 400


def test_oauth_callback_aceita_state_emitido(cliente, settings):
    client, _, _ = cliente
    storage = Storage(settings.database_path)
    storage.salvar_oauth_state("state-ok")

    class BlingFake:
        def trocar_codigo_por_token(self, code: str):
            assert code == "codigo-bling"

    from bling_trello_sync.main import get_bling

    app.dependency_overrides[get_bling] = lambda: BlingFake()
    resposta = client.get("/oauth/bling/callback", params={"code": "codigo-bling", "state": "state-ok"})
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "autorizado"
    assert not storage.consumir_oauth_state("state-ok")


def test_rota_sem_api_token_configurado_devolve_503(settings):
    settings.api_token = ""
    Storage(settings.database_path)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    assert client.get("/trello/listas").status_code == 503
    app.dependency_overrides.clear()
