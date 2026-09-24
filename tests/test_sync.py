from bling_trello_sync.storage import Storage
from bling_trello_sync.sync import Sincronizador, descricao_do_card, titulo_do_card


class BlingFake:
    def __init__(self, pedido: dict) -> None:
        self.pedido = pedido

    def obter_pedido_venda(self, pedido_id: int) -> dict:
        return self.pedido

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
    return Sincronizador(settings, storage, BlingFake(pedido), trello), storage, trello


def test_titulo_e_descricao(pedido):
    assert titulo_do_card(pedido) == "Pedido 123 - Cliente Teste"
    descricao = descricao_do_card(pedido, "Atendido")
    assert "Cliente Teste" in descricao
    assert "R$ 1.234,50" in descricao
    assert "Produto do Bling" in descricao


def test_cria_card_na_lista_da_situacao(settings, pedido):
    sincronizador, storage, trello = _sincronizador(settings, pedido)

    resultado = sincronizador.sincronizar_pedido(12345678, "created")

    assert resultado.acao == "card_criado"
    assert trello.criados[0]["idList"] == "lista-atendido"
    assert trello.criados[0]["due"] == "2026-01-20"
    assert storage.obter_card(12345678).card_id == "card-1"


def test_usa_lista_padrao_para_situacao_sem_mapeamento(settings, pedido):
    pedido["situacao"] = {"id": 999, "valor": 1}
    sincronizador, _, trello = _sincronizador(settings, pedido)

    sincronizador.sincronizar_pedido(12345678, "created")

    assert trello.criados[0]["idList"] == "lista-entrada"


def test_segunda_notificacao_atualiza_o_mesmo_card(settings, pedido):
    sincronizador, _, trello = _sincronizador(settings, pedido)
    sincronizador.sincronizar_pedido(12345678, "created")

    resultado = sincronizador.sincronizar_pedido(12345678, "updated")

    assert resultado.acao == "card_atualizado"
    assert len(trello.criados) == 1
    assert trello.atualizados[0]["id"] == "card-1"


def test_mudanca_de_situacao_move_card_e_comenta(settings, pedido):
    sincronizador, _, trello = _sincronizador(settings, pedido)
    pedido["situacao"] = {"id": 6, "valor": 1}
    sincronizador.sincronizar_pedido(12345678, "created")

    pedido["situacao"] = {"id": 9, "valor": 1}
    sincronizador.sincronizar_pedido(12345678, "updated")

    assert trello.atualizados[0]["idList"] == "lista-atendido"
    assert trello.comentarios[0][1] == "Situação alterada no Bling para: Atendido"


def test_pedido_excluido_arquiva_card(settings, pedido):
    sincronizador, storage, trello = _sincronizador(settings, pedido)
    sincronizador.sincronizar_pedido(12345678, "created")

    resultado = sincronizador.sincronizar_pedido(12345678, "deleted")

    assert resultado.acao == "card_arquivado"
    assert trello.atualizados[-1]["closed"] is True
    assert storage.obter_card(12345678) is None
