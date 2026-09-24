import pytest

from bling_trello_sync.storage import Storage
from bling_trello_sync.sync import (
    Sincronizador,
    _data_para_trello,
    descricao_do_card,
    titulo_do_card,
)


class BlingFake:
    def __init__(self, pedido: dict) -> None:
        self.pedido = pedido
        self.filtros: list[dict] = []
        self.paginas: list[list[dict]] = []

    def obter_pedido_venda(self, pedido_id: int) -> dict:
        return self.pedido

    def listar_pedidos_vendas(self, pagina: int = 1, **filtros) -> list[dict]:
        self.filtros.append({"pagina": pagina, **filtros})
        if pagina <= len(self.paginas):
            return self.paginas[pagina - 1]
        return []

    def obter_situacao(self, situacao_id: int) -> dict:
        return {"id": situacao_id, "nome": "Atendido"}


class TrelloFake:
    def __init__(self) -> None:
        self.criados: list[dict] = []
        self.atualizados: list[dict] = []
        self.comentarios: list[tuple[str, str]] = []

    def criar_card(self, id_list, nome, descricao, due=None, id_labels=None):
        card = {"id": "card-1", "shortUrl": "https://trello.com/c/abc", "idList": id_list, "name": nome}
        self.criados.append({"idList": id_list, "name": nome, "desc": descricao, "due": due})
        return card

    def atualizar_card(self, card_id, nome=None, descricao=None, id_list=None, due=None, closed=None):
        self.atualizados.append(
            {"id": card_id, "name": nome, "idList": id_list, "due": due, "closed": closed}
        )
        return {"id": card_id, "shortUrl": "https://trello.com/c/abc"}

    def comentar(self, card_id, texto):
        self.comentarios.append((card_id, texto))
        return {}


def _sincronizador(settings, pedido):
    storage = Storage(settings.database_path)
    trello = TrelloFake()
    bling = BlingFake(pedido)
    return Sincronizador(settings, storage, bling, trello), storage, trello, bling


def test_titulo_e_descricao(pedido):
    assert titulo_do_card(pedido) == "Pedido 123 - Cliente Teste"
    descricao = descricao_do_card(pedido, "Atendido")
    assert "Cliente Teste" in descricao
    assert "R$ 1.234,50" in descricao
    assert "Produto do Bling" in descricao


def test_cria_card_na_lista_da_situacao(settings, pedido):
    sincronizador, storage, trello, _bling = _sincronizador(settings, pedido)

    resultado = sincronizador.sincronizar_pedido(12345678)

    assert resultado.acao == "card_criado"
    assert trello.criados[0]["idList"] == "lista-atendido"
    assert trello.criados[0]["due"] == "2026-01-20T00:00:00.000Z"
    assert storage.obter_card(12345678).card_id == "card-1"


def test_usa_lista_padrao_para_situacao_sem_mapeamento(settings, pedido):
    pedido["situacao"] = {"id": 999, "valor": 1}
    sincronizador, _, trello, _bling = _sincronizador(settings, pedido)

    sincronizador.sincronizar_pedido(12345678)

    assert trello.criados[0]["idList"] == "lista-entrada"


def test_segunda_notificacao_atualiza_o_mesmo_card(settings, pedido):
    sincronizador, _, trello, _bling = _sincronizador(settings, pedido)
    sincronizador.sincronizar_pedido(12345678)

    resultado = sincronizador.sincronizar_pedido(12345678)

    assert resultado.acao == "card_atualizado"
    assert len(trello.criados) == 1
    assert trello.atualizados[0]["id"] == "card-1"


def test_mudanca_de_situacao_move_card_e_comenta(settings, pedido):
    sincronizador, _, trello, _bling = _sincronizador(settings, pedido)
    pedido["situacao"] = {"id": 6, "valor": 1}
    sincronizador.sincronizar_pedido(12345678)

    pedido["situacao"] = {"id": 9, "valor": 1}
    sincronizador.sincronizar_pedido(12345678)

    assert trello.atualizados[0]["idList"] == "lista-atendido"
    assert trello.comentarios[0][1] == "Situação alterada no Bling para: Atendido"




def test_sincronizar_lote_percorre_paginas_e_resume(settings, pedido):
    sincronizador, _, trello, bling = _sincronizador(settings, pedido)
    bling.paginas = [[{"id": 1}, {"id": 2}], [{"id": 1}]]

    resumo = sincronizador.sincronizar_lote(data_alteracao_inicial="2026-01-10 08:00:00")

    assert resumo.pedidos_encontrados == 3
    assert resumo.cards_criados == 2
    assert resumo.cards_atualizados == 1
    assert resumo.erros == []
    assert bling.filtros[0]["data_alteracao_inicial"] == "2026-01-10 08:00:00"
    assert len(trello.criados) == 2


def test_sincronizar_lote_registra_erro_e_continua(settings, pedido):
    sincronizador, _, trello, bling = _sincronizador(settings, pedido)
    bling.paginas = [[{"id": 1}, {"id": 2}]]
    original = sincronizador.sincronizar_pedido

    def falha_no_primeiro(pedido_id):
        if pedido_id == 1:
            raise RuntimeError("500 do Bling")
        return original(pedido_id)

    sincronizador.sincronizar_pedido = falha_no_primeiro

    resumo = sincronizador.sincronizar_lote()

    assert resumo.erros == [(1, "500 do Bling")]
    assert resumo.cards_criados == 1


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("2026-09-30", "2026-09-30T00:00:00.000Z"),
        ("2026-09-30 14:05:00", "2026-09-30T14:05:00.000Z"),
        ("0000-00-00", None),
        ("", None),
        (None, None),
    ],
)
def test_data_para_trello(valor, esperado):
    assert _data_para_trello(valor) == esperado


def test_nome_da_situacao_vem_do_env_sem_chamar_o_bling(settings, pedido):
    settings.nomes_situacoes = {"9": "Em aberto"}
    sincronizador, _, trello, bling = _sincronizador(settings, pedido)

    def nao_deve_ser_chamado(situacao_id):
        raise AssertionError("não deveria consultar as situações do Bling")

    bling.obter_situacao = nao_deve_ser_chamado

    sincronizador.sincronizar_pedido(12345678)

    assert "**Situação:** Em aberto" in trello.criados[0]["desc"]


def test_sem_acesso_as_situacoes_usa_o_id(settings, pedido):
    sincronizador, _, trello, bling = _sincronizador(settings, pedido)
    chamadas = []

    def sem_permissao(situacao_id):
        chamadas.append(situacao_id)
        raise RuntimeError("403 Forbidden")

    bling.obter_situacao = sem_permissao
    bling.paginas = [[{"id": 1}, {"id": 2}]]

    sincronizador.sincronizar_lote()

    assert chamadas == [9]
    assert "**Situação:** 9" in trello.criados[0]["desc"]
