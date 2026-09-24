import logging
from dataclasses import dataclass, field
from typing import Any

from .bling import BlingClient
from .config import Settings
from .storage import Storage
from .trello import TrelloClient

logger = logging.getLogger(__name__)


def _moeda(valor: Any) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"


def titulo_do_card(pedido: dict[str, Any]) -> str:
    numero = pedido.get("numero") or pedido.get("id")
    contato = (pedido.get("contato") or {}).get("nome", "Sem contato")
    return f"Pedido {numero} - {contato}"


def descricao_do_card(pedido: dict[str, Any], nome_situacao: str | None = None) -> str:
    contato = pedido.get("contato") or {}
    loja = pedido.get("loja") or {}
    linhas = [
        f"**Pedido Bling:** {pedido.get('numero', '-')} (id `{pedido.get('id', '-')}`)",
        f"**Cliente:** {contato.get('nome', '-')} - {contato.get('numeroDocumento', '-')}",
        f"**Data:** {pedido.get('data', '-')} | **Prevista:** {pedido.get('dataPrevista', '-')}",
        f"**Total:** {_moeda(pedido.get('total'))} (produtos {_moeda(pedido.get('totalProdutos'))})",
    ]
    if nome_situacao:
        linhas.append(f"**Situação:** {nome_situacao}")
    if loja.get("id"):
        linhas.append(f"**Loja:** {loja.get('id')}")
    if pedido.get("numeroLoja"):
        linhas.append(f"**Nº na loja:** {pedido['numeroLoja']}")

    itens = pedido.get("itens") or []
    if itens:
        linhas.append("")
        linhas.append("**Itens:**")
        for item in itens:
            quantidade = item.get("quantidade", 0)
            linhas.append(
                f"- {item.get('codigo', '')} {item.get('descricao', '')} — "
                f"{quantidade:g} x {_moeda(item.get('valor'))}".strip()
            )

    observacoes = pedido.get("observacoes")
    if observacoes:
        linhas.extend(["", f"**Observações:** {observacoes}"])

    return "\n".join(linhas)


@dataclass
class ResultadoSync:
    pedido_id: int
    acao: str
    card_id: str | None = None
    card_url: str | None = None


@dataclass
class ResumoExecucao:
    pedidos_encontrados: int = 0
    cards_criados: int = 0
    cards_atualizados: int = 0
    erros: list[tuple[int, str]] = field(default_factory=list)

    def registrar(self, resultado: ResultadoSync) -> None:
        if resultado.acao == "card_criado":
            self.cards_criados += 1
        elif resultado.acao == "card_atualizado":
            self.cards_atualizados += 1


class Sincronizador:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        bling: BlingClient,
        trello: TrelloClient,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.bling = bling
        self.trello = trello
        self._cache_situacoes: dict[int, str] = {}

    def _nome_situacao(self, situacao_id: int | None) -> str | None:
        if situacao_id is None:
            return None
        if situacao_id not in self._cache_situacoes:
            try:
                self._cache_situacoes[situacao_id] = self.bling.obter_situacao(situacao_id).get("nome", "")
            except Exception:  # noqa: BLE001 - nome da situação é informativo
                logger.warning("Não foi possível obter o nome da situação %s", situacao_id)
                return None
        return self._cache_situacoes[situacao_id] or None

    def sincronizar_pedido(self, pedido_id: int) -> ResultadoSync:
        pedido = self.bling.obter_pedido_venda(pedido_id)
        situacao_id = (pedido.get("situacao") or {}).get("id")
        nome_situacao = self._nome_situacao(situacao_id)
        id_list = self.settings.lista_para_situacao(situacao_id)
        nome = titulo_do_card(pedido)
        descricao = descricao_do_card(pedido, nome_situacao)
        due = pedido.get("dataPrevista") or None

        existente = self.storage.obter_card(pedido_id)
        if existente is None:
            card = self.trello.criar_card(
                id_list=id_list,
                nome=nome,
                descricao=descricao,
                due=due,
                id_labels=self.settings.trello_label_ids,
            )
            self.storage.salvar_card(pedido_id, card["id"], card["shortUrl"], situacao_id)
            logger.info("Card criado para o pedido %s: %s", pedido_id, card["shortUrl"])
            return ResultadoSync(pedido_id, "card_criado", card["id"], card["shortUrl"])

        card = self.trello.atualizar_card(
            existente.card_id,
            nome=nome,
            descricao=descricao,
            id_list=id_list,
            due=due,
            closed=False,
        )
        self.storage.salvar_card(pedido_id, card["id"], card["shortUrl"], situacao_id)
        if existente.situacao_id != situacao_id and nome_situacao:
            self.trello.comentar(existente.card_id, f"Situação alterada no Bling para: {nome_situacao}")
        logger.info("Card atualizado para o pedido %s: %s", pedido_id, card["shortUrl"])
        return ResultadoSync(pedido_id, "card_atualizado", card["id"], card["shortUrl"])

    def sincronizar_lote(
        self,
        data_alteracao_inicial: str | None = None,
        data_alteracao_final: str | None = None,
        data_inicial: str | None = None,
        data_final: str | None = None,
        ids_situacoes: list[int] | None = None,
        limite_paginas: int = 100,
    ) -> ResumoExecucao:
        """Busca os pedidos de venda que atendem ao filtro e cria/atualiza os cards."""
        resumo = ResumoExecucao()
        pagina = 1
        while pagina <= limite_paginas:
            pedidos = self.bling.listar_pedidos_vendas(
                pagina=pagina,
                data_inicial=data_inicial,
                data_final=data_final,
                data_alteracao_inicial=data_alteracao_inicial,
                data_alteracao_final=data_alteracao_final,
                ids_situacoes=ids_situacoes,
            )
            if not pedidos:
                break
            for pedido in pedidos:
                pedido_id = int(pedido["id"])
                resumo.pedidos_encontrados += 1
                try:
                    resumo.registrar(self.sincronizar_pedido(pedido_id))
                except Exception as erro:  # noqa: BLE001 - um pedido com erro não para a execução
                    logger.exception("Falha ao sincronizar o pedido %s", pedido_id)
                    resumo.erros.append((pedido_id, str(erro)))
            pagina += 1
        return resumo

