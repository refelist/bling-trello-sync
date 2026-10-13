import time

import httpx
import pytest

from bling_trello_sync.bling import BlingClient
from bling_trello_sync.config import Settings
from bling_trello_sync.formatacao import data_brasileira, data_para_trello, moeda, quantidade
from bling_trello_sync.metricas import metricas
from bling_trello_sync.storage import Storage, TokenBling


def test_settings_financeiro_sem_trello(tmp_path):
    settings = Settings(
        _env_file=None,
        bling_client_id="id",
        bling_client_secret="secret",
        financeiro_ativo=True,
        database_path=str(tmp_path / "ops.db"),
    )
    assert not settings.trello_configurado
    with pytest.raises(ValueError, match="TRELLO_API_KEY"):
        settings.exigir_trello()


def test_settings_trello_configurado(settings):
    assert settings.trello_configurado
    settings.exigir_trello()


def test_purgar_eventos_remove_apenas_done_antigos(settings):
    storage = Storage(settings.database_path)
    storage.registrar_evento("velho")
    storage.reclamar_evento("em-andamento")
    with storage._conexao() as conn:
        conn.execute(
            "UPDATE evento_processado SET processado_em = ? WHERE event_id = ?",
            (time.time() - 40 * 86400, "velho"),
        )

    assert storage.purgar_eventos(dias=30) == 1
    assert not storage.evento_ja_processado("velho")
    assert storage.reclamar_evento("em-andamento") is False


def test_purgar_eventos_dias_zero_nao_apaga(settings):
    storage = Storage(settings.database_path)
    storage.registrar_evento("keep")
    assert storage.purgar_eventos(dias=0) == 0
    assert storage.evento_ja_processado("keep")


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (10, "R$ 10,00"),
        ("1.5", "R$ 1,50"),
        (None, "-"),
        ("x", "-"),
    ],
)
def test_moeda(valor, esperado):
    assert moeda(valor) == esperado


def test_quantidade_e_datas():
    assert quantidade({"quantidade": "2.5"}) == 2.5
    assert quantidade({}) == 0.0
    assert data_para_trello("2026-01-20") == "2026-01-20T00:00:00.000Z"
    assert data_para_trello("0001-01-01") is None
    assert data_brasileira("2026-01-20T15:30:00") == "20/01/2026"


def test_metricas_429(settings, monkeypatch):
    monkeypatch.setattr("bling_trello_sync.bling.time.sleep", lambda _: None)
    antes = metricas.instantaneo()["bling_429"]
    storage = Storage(settings.database_path)
    storage.salvar_token(TokenBling("token", "refresh", time.time() + 3600))
    respostas = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"data": {"id": 1}}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return respostas.pop(0)

    bling = BlingClient(settings, storage, httpx.Client(transport=httpx.MockTransport(handler)))
    assert bling.obter_pedido_venda(1) == {"id": 1}
    assert metricas.instantaneo()["bling_429"] == antes + 1
