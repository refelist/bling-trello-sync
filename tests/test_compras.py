import json

import pytest

from bling_trello_sync.compras import (
    SincronizadorCompras,
    descricao_do_card,
    itens_do_checklist,
    titulo_do_card,
)
from bling_trello_sync.config import Settings
from bling_trello_sync.storage import Storage
from bling_trello_sync.trello import CardNaoEncontrado
from tests.test_sync import TrelloFake


@pytest.fixture
def settings_compras(tmp_path) -> Settings:
    return Settings(
        bling_client_id="client-id",
        bling_client_secret="client-secret",
        trello_api_key="trello-key",
        trello_token="trello-token",
        trello_board_id="board-1",
        trello_list_id_padrao="lista-entrada",
        trello_board_id_compras="board-compras",
        trello_list_id_padrao_compras="EM ABERTO",
        trello_list_id_por_situacao_compra=json.dumps(
            {"0": "EM ABERTO", "3": "EM ANDAMENTO", "1": "ATENDIDOS", "2": "CANCELADOS"}
        ),
        database_path=str(tmp_path / "teste.db"),
    )


@pytest.fixture
def compra() -> dict:
    return {
        "id": 99887766,
        "numero": "551",
        "data": "2026-02-10",
        "dataPrevista": "2026-02-20",
        "total": 2500.0,
        "totalProdutos": 2400.0,
        "fornecedor": {"id": 77},
        "situacao": {"valor": 0},
        "itens": [
            {
                "descricao": "Parafuso",
                "quantidade": 10,
                "valor": 5.0,
                "produto": {"id": 1, "codigo": "PAR-1"},
                "notaFiscal": {"id": 5, "quantidade": 10},
            },
            {
                "descricao": "Porca",
                "quantidade": 4,
                "valor": 2.0,
                "produto": {"id": 2, "codigo": "POR-1"},
            },
        ],
        "observacoes": "Retirar no fornecedor",
    }


class BlingComprasFake:
    def __init__(self, compra: dict) -> None:
        self.compra = compra
        self.paginas: list[list[dict]] = []
        self.filtros: list[dict] = []

    def obter_pedido_compra(self, pedido_id: int) -> dict:
        return self.compra

    def obter_contato(self, contato_id: int) -> dict:
        return {"id": contato_id, "nome": "Fornecedor Teste"}

    def listar_pedidos_compras(self, pagina: int = 1, **filtros) -> list[dict]:
        self.filtros.append({"pagina": pagina, **filtros})
        if pagina <= len(self.paginas):
            return self.paginas[pagina - 1]
        return []


class TrelloComprasFake(TrelloFake):
    def listar_listas(self, board_id):
        return [
            {"id": "lista-aberto", "name": "EM ABERTO"},
            {"id": "lista-andamento", "name": "EM ANDAMENTO"},
            {"id": "lista-atendidos", "name": "ATENDIDOS"},
            {"id": "lista-cancelados", "name": "CANCELADOS"},
        ]


def _sincronizador(settings, compra):
    storage = Storage(settings.database_path)
    trello = TrelloComprasFake()
    bling = BlingComprasFake(compra)
    return SincronizadorCompras(settings, storage, bling, trello), storage, trello, bling


def test_titulo_e_descricao(compra):
    assert titulo_do_card(compra, "Fornecedor Teste") == "Compra 551 - Fornecedor Teste"
    descricao = descricao_do_card(compra, "Fornecedor Teste")
    assert "Fornecedor Teste" in descricao
    assert "R$ 2.500,00" in descricao
    assert "Parafuso" in descricao
    assert "Em aberto" in descricao


def test_checklist_marca_itens_ja_recebidos(compra):
    itens = itens_do_checklist(compra)
    assert itens == [("10 x PAR-1 Parafuso", True), ("4 x POR-1 Porca", False)]


def test_cria_card_na_lista_da_situacao(settings_compras, compra):
    sincronizador, storage, trello, _bling = _sincronizador(settings_compras, compra)

    resultado = sincronizador.sincronizar_pedido(99887766)

    assert resultado.acao == "card_criado"
    assert trello.criados[0]["idList"] == "lista-aberto"
    assert trello.criados[0]["due"] == "2026-02-20T00:00:00.000Z"
    assert storage.obter_card_compra(99887766).card_id == "card-1"
    assert storage.obter_card(99887766) is None
    assert trello.itens_criados == [("chk-1", "10 x PAR-1 Parafuso"), ("chk-1", "4 x POR-1 Porca")]


def test_move_card_e_comenta_quando_situacao_muda(settings_compras, compra):
    sincronizador, _storage, trello, _bling = _sincronizador(settings_compras, compra)
    sincronizador.sincronizar_pedido(99887766)

    compra["situacao"] = {"valor": 1}
    resultado = sincronizador.sincronizar_pedido(99887766)

    assert resultado.acao == "card_atualizado"
    assert trello.atualizados[-1]["idList"] == "lista-atendidos"
    assert trello.comentarios[-1][1] == "Situação alterada no Bling para: Atendido"


def test_recria_card_apagado_no_trello(settings_compras, compra):
    sincronizador, _storage, trello, _bling = _sincronizador(settings_compras, compra)
    sincronizador.sincronizar_pedido(99887766)

    def falhar(*args, **kwargs):
        raise CardNaoEncontrado("404", 404)

    trello.atualizar_card = falhar
    resultado = sincronizador.sincronizar_pedido(99887766)

    assert resultado.acao == "card_criado"
    assert len(trello.criados) == 2


def test_lote_percorre_paginas(settings_compras, compra):
    sincronizador, _storage, _trello, bling = _sincronizador(settings_compras, compra)
    bling.paginas = [[{"id": 99887766}]]

    resumo = sincronizador.sincronizar_lote(dias=7)

    assert resumo.pedidos_encontrados == 1
    assert resumo.cards_criados == 1
    assert bling.filtros[0]["data_inicial"] is not None
    assert bling.filtros[0]["data_final"] is not None


def test_usa_lista_padrao_para_situacao_desconhecida(settings_compras, compra):
    compra["situacao"] = {"valor": 42}
    sincronizador, _storage, trello, _bling = _sincronizador(settings_compras, compra)

    sincronizador.sincronizar_pedido(99887766)

    assert trello.criados[0]["idList"] == "lista-aberto"
