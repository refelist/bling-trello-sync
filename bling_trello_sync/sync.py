import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .bling import BlingClient
from .config import Settings
from .storage import Storage
from .trello import CardNaoEncontrado, TrelloClient

logger = logging.getLogger(__name__)


def _moeda(valor: Any) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"


def _data_para_trello(valor: Any) -> str | None:
    """Converte a data do Bling para ISO-8601; datas ausentes ou zeradas viram None."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip()
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            momento = datetime.strptime(texto, formato)
        except ValueError:
            continue
        if momento.date() == date(1, 1, 1):
            return None
        return momento.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return None


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
    situacao_id = (pedido.get("situacao") or {}).get("id")
    if nome_situacao:
        linhas.append(f"**Situação:** {nome_situacao}")
    elif situacao_id is not None:
        linhas.append(f"**Situação:** {situacao_id}")
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


NOME_CHECKLIST = "Itens do pedido"


def itens_do_checklist(pedido: dict[str, Any]) -> list[str]:
    """Um item de checklist por produto do pedido."""
    itens = []
    for item in pedido.get("itens") or []:
        quantidade = item.get("quantidade", 0)
        try:
            quantidade_texto = f"{float(quantidade):g}"
        except (TypeError, ValueError):
            quantidade_texto = str(quantidade)
        codigo = item.get("codigo") or ""
        descricao = item.get("descricao") or ""
        itens.append(f"{quantidade_texto} x {codigo} {descricao}".replace("  ", " ").strip())
    return itens


@dataclass
class ResultadoSync:
    pedido_id: int
    acao: str
    card_id: str | None = None
    card_url: str | None = None


@dataclass
class ResumoExecucao:
    pedidos_encontrados: int = 0
    pedidos_ignorados: int = 0
    cards_criados: int = 0
    cards_atualizados: int = 0
    erros: list[tuple[int, str]] = field(default_factory=list)

    def registrar(self, resultado: ResultadoSync) -> None:
        if resultado.acao == "ignorado":
            self.pedidos_ignorados += 1
        elif resultado.acao == "card_criado":
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
        self._situacoes_indisponiveis = False

    def _nome_situacao(self, situacao_id: int | None, pedido: dict[str, Any]) -> str | None:
        """Nome da situação: mapa do .env, depois o próprio pedido e, por fim, a API do Bling."""
        if situacao_id is None:
            return None
        configurado = self.settings.nome_para_situacao(situacao_id)
        if configurado:
            return configurado
        situacao = pedido.get("situacao") or {}
        no_pedido = situacao.get("nome") or situacao.get("descricao")
        if no_pedido:
            return str(no_pedido)
        if self._situacoes_indisponiveis:
            return None
        if situacao_id not in self._cache_situacoes:
            try:
                self._cache_situacoes[situacao_id] = self.bling.obter_situacao(situacao_id).get("nome", "")
            except Exception:  # noqa: BLE001 - nome da situação é informativo
                self._situacoes_indisponiveis = True
                logger.warning(
                    "Sem acesso às situações do Bling; use NOMES_SITUACOES no .env para exibir os nomes"
                )
                return None
        return self._cache_situacoes[situacao_id] or None

    def _sincronizar_checklist(self, card_id: str, itens: list[str]) -> None:
        """Mantém o checklist igual aos produtos do pedido, preservando os itens já marcados."""
        if not itens:
            return
        checklist = next(
            (c for c in self.trello.listar_checklists(card_id) if c.get("name") == NOME_CHECKLIST),
            None,
        )
        if checklist is None:
            checklist = self.trello.criar_checklist(card_id, NOME_CHECKLIST)

        existentes = {item.get("name"): item for item in checklist.get("checkItems") or []}
        for nome in itens:
            if nome not in existentes:
                self.trello.criar_item_checklist(checklist["id"], nome)
        for nome, item in existentes.items():
            if nome not in itens:
                self.trello.remover_item_checklist(checklist["id"], item["id"])

    def sincronizar_pedido(self, pedido_id: int) -> ResultadoSync:
        pedido = self.bling.obter_pedido_venda(pedido_id)
        loja_id = (pedido.get("loja") or {}).get("id")
        if not self.settings.loja_sincronizavel(loja_id):
            logger.info("Pedido %s ignorado: loja %s fora do filtro", pedido_id, loja_id)
            return ResultadoSync(pedido_id, "ignorado")
        situacao_id = (pedido.get("situacao") or {}).get("id")
        nome_situacao = self._nome_situacao(situacao_id, pedido)
        id_list = self.settings.lista_para_situacao(situacao_id)
        nome = titulo_do_card(pedido)
        descricao = descricao_do_card(pedido, nome_situacao)
        due = _data_para_trello(pedido.get("dataPrevista"))

        existente = self.storage.obter_card(pedido_id)
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
                    "Card %s do pedido %s não existe mais no Trello; criando outro",
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
            self.storage.salvar_card(pedido_id, card["id"], card["shortUrl"], situacao_id)
            self._sincronizar_checklist(card["id"], itens_do_checklist(pedido))
            logger.info("Card criado para o pedido %s: %s", pedido_id, card["shortUrl"])
            return ResultadoSync(pedido_id, "card_criado", card["id"], card["shortUrl"])

        self.storage.salvar_card(pedido_id, card["id"], card["shortUrl"], situacao_id)
        self._sincronizar_checklist(card["id"], itens_do_checklist(pedido))
        if existente.situacao_id != situacao_id and situacao_id is not None:
            self.trello.comentar(
                existente.card_id,
                f"Situação alterada no Bling para: {nome_situacao or situacao_id}",
            )
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
                loja_id = (pedido.get("loja") or {}).get("id")
                if loja_id is not None and not self.settings.loja_sincronizavel(loja_id):
                    resumo.pedidos_ignorados += 1
                    continue
                try:
                    resumo.registrar(self.sincronizar_pedido(pedido_id))
                except Exception as erro:  # noqa: BLE001 - um pedido com erro não para a execução
                    logger.exception("Falha ao sincronizar o pedido %s", pedido_id)
                    resumo.erros.append((pedido_id, str(erro)))
            pagina += 1
        return resumo

