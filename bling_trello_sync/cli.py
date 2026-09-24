"""Linha de comando da integração: a sincronização acontece quando este programa é executado."""

import argparse
import logging
from datetime import datetime, timedelta

from .bling import BlingClient
from .config import get_settings
from .oauth_local import autorizar
from .storage import Storage
from .sync import Sincronizador
from .trello import TrelloClient

logger = logging.getLogger(__name__)

FORMATO_ALTERACAO = "%Y-%m-%d %H:%M:%S"
FORMATO_DATA = "%Y-%m-%d"


def _construir() -> tuple[Sincronizador, BlingClient, TrelloClient, Storage]:
    settings = get_settings()
    storage = Storage(settings.database_path)
    bling = BlingClient(settings, storage)
    trello = TrelloClient(settings.trello_api_key, settings.trello_token)
    return Sincronizador(settings, storage, bling, trello), bling, trello, storage


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bling-trello", description="Sincroniza pedidos de venda do Bling com cards do Trello"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("autorizar", help="Autoriza o aplicativo no Bling e grava os tokens")

    p_sync = sub.add_parser(
        "sincronizar",
        help="Sincroniza os pedidos alterados desde a última execução (ou no período informado)",
    )
    p_sync.add_argument(
        "--desde",
        help="Considera pedidos alterados a partir deste momento (AAAA-MM-DD ou 'AAAA-MM-DD HH:MM:SS')",
    )
    p_sync.add_argument("--ate", help="Limite superior da alteração, mesmo formato de --desde")
    p_sync.add_argument(
        "--dias",
        type=int,
        help="Atalho para --desde: quantidade de dias para trás a partir de agora",
    )
    p_sync.add_argument(
        "--data-inicial", help="Filtra por data de emissão do pedido (AAAA-MM-DD), em vez de alteração"
    )
    p_sync.add_argument("--data-final", help="Data final de emissão (AAAA-MM-DD)")
    p_sync.add_argument(
        "--situacoes",
        help="IDs de situações do Bling separados por vírgula (apenas esses pedidos são sincronizados)",
    )
    p_sync.add_argument(
        "--tudo",
        action="store_true",
        help="Ignora a última execução e varre todos os pedidos que o filtro permitir",
    )
    p_sync.add_argument("--limite-paginas", type=int, default=100)

    p_pedido = sub.add_parser("sincronizar-pedido", help="Sincroniza um único pedido pelo ID do Bling")
    p_pedido.add_argument("pedido_id", type=int)

    sub.add_parser("listas-trello", help="Lista os IDs das listas do board configurado")
    sub.add_parser("labels-trello", help="Lista os IDs das etiquetas do board configurado")
    sub.add_parser("modulos-bling", help="Lista os módulos de situações do Bling")

    p_situacoes = sub.add_parser("situacoes-bling", help="Lista as situações de um módulo do Bling")
    p_situacoes.add_argument("id_modulo", type=int)

    return parser


def _normalizar_momento(valor: str) -> str:
    for formato in (FORMATO_ALTERACAO, FORMATO_DATA):
        try:
            return datetime.strptime(valor, formato).strftime(FORMATO_ALTERACAO)
        except ValueError:
            continue
    raise SystemExit(f"Data inválida: {valor!r}. Use AAAA-MM-DD ou 'AAAA-MM-DD HH:MM:SS'.")


def _janela_de_alteracao(args: argparse.Namespace, storage: Storage) -> tuple[str | None, str | None]:
    if args.data_inicial or args.data_final:
        return None, None
    if args.tudo:
        return None, None
    if args.desde:
        inicio = _normalizar_momento(args.desde)
    elif args.dias:
        inicio = (datetime.now() - timedelta(days=args.dias)).strftime(FORMATO_ALTERACAO)
    else:
        inicio = storage.obter_ultima_sincronizacao()
        if inicio is None:
            # Primeira execução sem filtro: cobre os últimos 30 dias.
            inicio = (datetime.now() - timedelta(days=30)).strftime(FORMATO_ALTERACAO)
            print(f"Primeira execução: sincronizando pedidos alterados desde {inicio}.")
    fim = _normalizar_momento(args.ate) if args.ate else None
    return inicio, fim


def _comando_sincronizar(args: argparse.Namespace, sincronizador: Sincronizador, storage: Storage) -> None:
    inicio_execucao = datetime.now().strftime(FORMATO_ALTERACAO)
    alteracao_inicial, alteracao_final = _janela_de_alteracao(args, storage)
    situacoes = (
        [int(item) for item in args.situacoes.split(",") if item.strip()] if args.situacoes else None
    )

    resumo = sincronizador.sincronizar_lote(
        data_alteracao_inicial=alteracao_inicial,
        data_alteracao_final=alteracao_final,
        data_inicial=args.data_inicial,
        data_final=args.data_final,
        ids_situacoes=situacoes,
        limite_paginas=args.limite_paginas,
    )

    print(
        f"{resumo.pedidos_encontrados} pedidos processados | "
        f"{resumo.cards_criados} cards criados | {resumo.cards_atualizados} atualizados | "
        f"{len(resumo.erros)} erros"
    )
    for pedido_id, erro in resumo.erros:
        print(f"  erro no pedido {pedido_id}: {erro}")

    if not resumo.erros and alteracao_final is None:
        storage.salvar_ultima_sincronizacao(inicio_execucao)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _construir_parser().parse_args(argv)
    sincronizador, bling, trello, storage = _construir()
    settings = get_settings()

    if args.comando == "autorizar":
        autorizar(bling)
        print("Tokens do Bling armazenados com sucesso.")
    elif args.comando == "sincronizar":
        _comando_sincronizar(args, sincronizador, storage)
    elif args.comando == "sincronizar-pedido":
        resultado = sincronizador.sincronizar_pedido(args.pedido_id)
        print(f"{resultado.acao}: {resultado.card_url or '-'}")
    elif args.comando == "listas-trello":
        for lista in trello.listar_listas(settings.trello_board_id):
            print(f"{lista['id']}  {lista['name']}")
    elif args.comando == "labels-trello":
        for label in trello.listar_labels(settings.trello_board_id):
            print(f"{label['id']}  {label.get('color')}  {label.get('name')}")
    elif args.comando == "modulos-bling":
        for modulo in bling.listar_modulos_situacoes():
            print(f"{modulo.get('id')}  {modulo.get('nome')}")
    elif args.comando == "situacoes-bling":
        for situacao in bling.listar_situacoes_do_modulo(args.id_modulo):
            print(f"{situacao.get('id')}  {situacao.get('nome')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
