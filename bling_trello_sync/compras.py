"""Sincronização dos pedidos de compra do Bling com um quadro próprio do Trello.

O Bling não envia webhook de pedido de compra, então esta parte funciona por consulta
periódica: a cada execução são lidos os pedidos de compra do período configurado.
"""

import logging
from datetime import date, timedelta
from typing import Any

from .bling import BlingClient
from .config import Settings, normalizar
from .storage import Storage
from .sync import (
    NOME_CHECKLIST,
    ResultadoSync,
    ResumoExecucao,
    _data_para_trello,
    _moeda,
    _quantidade,
)
from .trello import CardNaoEncontrado, TrelloClient

logger = logging.getLogger(__name__)

NOMES_SITUACAO_COMPRA = {0: "Em aberto", 1: "Atendido", 2: "Cancelado", 3: "Em andamento"}

FRETE_POR_CONTA = {
    0: "Remetente (CIF)",
    1: "Destinatário (FOB)",
    2: "Terceiros",
    3: "Transporte próprio por conta do remetente",
    4: "Transporte próprio por conta do destinatário",
    9: "Sem ocorrência de transporte",
}


def nome_da_situacao(pedido: dict[str, Any]) -> str | None:
    situacao = pedido.get("situacao") or {}
    nome = situacao.get("nome") or situacao.get("descricao")
    if nome:
        return str(nome)
    valor = situacao.get("valor")
    return NOMES_SITUACAO_COMPRA.get(valor) if isinstance(valor, int) else None


def titulo_do_card(pedido: dict[str, Any], fornecedor: str | None) -> str:
    numero = pedido.get("numero") or pedido.get("id")
    return f"Compra {numero} - {fornecedor or 'Sem fornecedor'}"


def frete_por_conta(pedido: dict[str, Any]) -> str | None:
    transporte = pedido.get("transporte") or {}
    valor = transporte.get("fretePorConta")
    if valor is None:
        return None
    return FRETE_POR_CONTA.get(valor, str(valor))


def descricao_do_card(
    pedido: dict[str, Any], fornecedor: str | None, categoria: str | None = None
) -> str:
    linhas = [
        f"**Pedido de compra:** {pedido.get('numero', '-')} (id `{pedido.get('id', '-')}`)",
        f"**Fornecedor:** {fornecedor or '-'}",
        f"**Data:** {pedido.get('data', '-')} | **Prevista:** {pedido.get('dataPrevista', '-')}",
        f"**Total:** {_moeda(pedido.get('total'))} (produtos {_moeda(pedido.get('totalProdutos'))})",
    ]
    situacao = nome_da_situacao(pedido)
    if situacao:
        linhas.append(f"**Situação:** {situacao}")
    if categoria:
        linhas.append(f"**Categoria:** {categoria}")
    frete = frete_por_conta(pedido)
    if frete:
        linhas.append(f"**Frete por conta:** {frete}")
    if pedido.get("ordemCompra"):
        linhas.append(f"**Ordem de compra:** {pedido['ordemCompra']}")

    itens = pedido.get("itens") or []
    if itens:
        linhas.extend(["", "**Itens:**"])
        for item in itens:
            linhas.append(
                f"- {_codigo_do_item(item)} {item.get('descricao', '')} — "
                f"{_quantidade(item):g} x {_moeda(item.get('valor'))}".strip()
            )

    return "\n".join(linhas)


def _codigo_do_item(item: dict[str, Any]) -> str:
    produto = item.get("produto") or {}
    return str(produto.get("codigo") or item.get("codigoFornecedor") or "")


def _quantidade_recebida(item: dict[str, Any]) -> float:
    """Quantidade do item já vinculada a uma nota fiscal de entrada."""
    nota = item.get("notaFiscal") or {}
    try:
        return float(nota.get("quantidade", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def itens_do_checklist(pedido: dict[str, Any]) -> list[tuple[str, bool]]:
    """Um item por produto do pedido, marcado quando já foi todo recebido em nota."""
    itens = []
    for item in pedido.get("itens") or []:
        quantidade = _quantidade(item)
        nome = f"{quantidade:g} x {_codigo_do_item(item)} {item.get('descricao', '')}"
        nome = nome.replace("  ", " ").strip()
        recebida = _quantidade_recebida(item)
        itens.append((nome, quantidade > 0 and recebida + 1e-6 >= quantidade))
    return itens


class SincronizadorCompras:
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
        self._fornecedores: dict[int, str] = {}
        self._categorias: dict[int, str] = {}
        self._listas_por_nome: dict[str, str] | None = None

    def _id_da_lista(self, valor: str) -> str:
        if self._listas_por_nome is None:
            self._listas_por_nome = {
                normalizar(lista["name"]): lista["id"]
                for lista in self.trello.listar_listas(self.settings.trello_board_id_compras)
            }
        return self._listas_por_nome.get(normalizar(valor), valor)

    def _nome_fornecedor(self, pedido: dict[str, Any]) -> str | None:
        fornecedor = pedido.get("fornecedor") or {}
        nome = fornecedor.get("nome")
        if nome:
            return str(nome)
        contato_id = fornecedor.get("id")
        if not contato_id:
            return None
        contato_id = int(contato_id)
        if contato_id not in self._fornecedores:
            try:
                contato = self.bling.obter_contato(contato_id)
            except Exception as erro:  # noqa: BLE001 - o nome é informativo
                logger.warning("Falha ao buscar o fornecedor %s: %s", contato_id, erro)
                return None
            self._fornecedores[contato_id] = str(contato.get("nome") or contato_id)
        return self._fornecedores[contato_id]

    def _nome_categoria(self, pedido: dict[str, Any]) -> str | None:
        categoria = pedido.get("categoria") or {}
        descricao = categoria.get("descricao") or categoria.get("nome")
        if descricao:
            return str(descricao)
        categoria_id = categoria.get("id")
        if not categoria_id:
            return None
        categoria_id = int(categoria_id)
        if categoria_id not in self._categorias:
            try:
                dados = self.bling.obter_categoria_receita_despesa(categoria_id)
            except Exception as erro:  # noqa: BLE001 - a categoria é informativa
                logger.warning("Falha ao buscar a categoria %s: %s", categoria_id, erro)
                return None
            self._categorias[categoria_id] = str(dados.get("descricao") or categoria_id)
        return self._categorias[categoria_id]

    def _comentar_observacoes(self, card_id: str, pedido_id: int, pedido: dict[str, Any]) -> None:
        """Publica observações e observações internas em comentários separados, sem repetir."""
        textos = (
            ("observacoes", "Observações", pedido.get("observacoes")),
            ("observacoesInternas", "Observações internas", pedido.get("observacoesInternas")),
        )
        for tipo, rotulo, texto in textos:
            texto = (texto or "").strip()
            if not texto:
                continue
            if self.storage.registrar_comentario_compra(pedido_id, tipo, texto):
                self.trello.comentar(card_id, f"**{rotulo}:** {texto}")

    def _sincronizar_checklist(self, card_id: str, itens: list[tuple[str, bool]]) -> None:
        if not itens:
            return
        checklist = next(
            (c for c in self.trello.listar_checklists(card_id) if c.get("name") == NOME_CHECKLIST),
            None,
        )
        if checklist is None:
            checklist = self.trello.criar_checklist(card_id, NOME_CHECKLIST)

        existentes = {item.get("name"): item for item in checklist.get("checkItems") or []}
        nomes = {nome for nome, _ in itens}
        for nome, recebido in itens:
            atual = existentes.get(nome)
            if atual is None:
                self.trello.criar_item_checklist(checklist["id"], nome, recebido)
            elif recebido and atual.get("state") != "complete":
                self.trello.marcar_item_checklist(card_id, atual["id"])
        for nome, item in existentes.items():
            if nome not in nomes:
                self.trello.remover_item_checklist(checklist["id"], item["id"])

    def sincronizar_pedido(self, pedido_id: int) -> ResultadoSync:
        pedido = self.bling.obter_pedido_compra(pedido_id)
        situacao = pedido.get("situacao") or {}
        valor = situacao.get("valor")
        nome_situacao = nome_da_situacao(pedido)
        id_list = self._id_da_lista(self.settings.lista_para_situacao_compra(valor, nome_situacao))
        fornecedor = self._nome_fornecedor(pedido)
        nome = titulo_do_card(pedido, fornecedor)
        descricao = descricao_do_card(pedido, fornecedor, self._nome_categoria(pedido))
        due = _data_para_trello(pedido.get("dataPrevista"))
        itens = itens_do_checklist(pedido)

        existente = self.storage.obter_card_compra(pedido_id)
        if existente is not None:
            try:
                card = self.trello.atualizar_card(
                    existente.card_id,
                    nome=nome,
                    descricao=descricao,
                    id_list=id_list,
                    due=due,
                    closed=False,
                )
            except CardNaoEncontrado:
                logger.warning(
                    "Card %s da compra %s não existe mais no Trello; criando outro",
                    existente.card_id,
                    pedido_id,
                )
                existente = None

        if existente is None:
            card = self.trello.criar_card(
                id_list=id_list,
                nome=nome,
                descricao=descricao,
                due=due,
                id_labels=self.settings.trello_label_ids,
            )
            self.storage.salvar_card_compra(pedido_id, card["id"], card["shortUrl"], valor)
            self._sincronizar_checklist(card["id"], itens)
            self._comentar_observacoes(card["id"], pedido_id, pedido)
            logger.info("Card criado para a compra %s: %s", pedido_id, card["shortUrl"])
            return ResultadoSync(pedido_id, "card_criado", card["id"], card["shortUrl"])

        self.storage.salvar_card_compra(pedido_id, card["id"], card["shortUrl"], valor)
        self._sincronizar_checklist(card["id"], itens)
        self._comentar_observacoes(card["id"], pedido_id, pedido)
        if existente.situacao_id != valor and valor is not None:
            self.trello.comentar(
                card["id"], f"Situação alterada no Bling para: {nome_situacao or valor}"
            )
        logger.info("Card atualizado para a compra %s: %s", pedido_id, card["shortUrl"])
        return ResultadoSync(pedido_id, "card_atualizado", card["id"], card["shortUrl"])

    def sincronizar_lote(
        self,
        dias: int | None = None,
        data_inicial: str | None = None,
        data_final: str | None = None,
        limite_paginas: int = 100,
    ) -> ResumoExecucao:
        """Varre os pedidos de compra do período e cria/atualiza os cards do quadro de compras."""
        if data_inicial is None:
            janela = dias if dias is not None else self.settings.compras_dias
            data_inicial = (date.today() - timedelta(days=janela)).strftime("%Y-%m-%d")
        if data_final is None:
            # O Bling ignora o período quando recebe apenas a data inicial.
            data_final = date.today().strftime("%Y-%m-%d")
        resumo = ResumoExecucao()
        pagina = 1
        while pagina <= limite_paginas:
            pedidos = self.bling.listar_pedidos_compras(
                pagina=pagina, data_inicial=data_inicial, data_final=data_final
            )
            if not pedidos:
                break
            for pedido in pedidos:
                pedido_id = int(pedido["id"])
                resumo.pedidos_encontrados += 1
                try:
                    resumo.registrar(self.sincronizar_pedido(pedido_id))
                except Exception as erro:  # noqa: BLE001 - um pedido com erro não para a execução
                    logger.exception("Falha ao sincronizar a compra %s", pedido_id)
                    resumo.erros.append((pedido_id, str(erro)))
            pagina += 1
        return resumo
