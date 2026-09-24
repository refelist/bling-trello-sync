"""Utilitários de linha de comando: descobrir IDs e importar pedidos já existentes."""

import argparse
import logging

from .bling import BlingClient
from .config import get_settings
from .storage import Storage
from .sync import Sincronizador
from .trello import TrelloClient

logger = logging.getLogger(__name__)


def _construir() -> tuple[Sincronizador, BlingClient, TrelloClient]:
    settings = get_settings()
    storage = Storage(settings.database_path)
    bling = BlingClient(settings, storage)
    trello = TrelloClient(settings.trello_api_key, settings.trello_token)
    return Sincronizador(settings, storage, bling, trello), bling, trello


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="bling-trello")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("listas-trello", help="Lista os IDs das listas do board configurado")
    sub.add_parser("labels-trello", help="Lista os IDs das etiquetas do board configurado")
    sub.add_parser("modulos-bling", help="Lista os módulos de situações do Bling")

    p_situacoes = sub.add_parser("situacoes-bling", help="Lista as situações de um módulo do Bling")
    p_situacoes.add_argument("id_modulo", type=int)

    p_backfill = sub.add_parser("backfill", help="Cria cards para pedidos já existentes no Bling")
    p_backfill.add_argument("--data-inicial", required=True, help="Formato AAAA-MM-DD")
    p_backfill.add_argument("--data-final", required=True, help="Formato AAAA-MM-DD")
    p_backfill.add_argument("--limite-paginas", type=int, default=20)

    args = parser.parse_args(argv)
    sincronizador, bling, trello = _construir()
    settings = get_settings()

    if args.comando == "listas-trello":
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
    elif args.comando == "backfill":
        pagina = 1
        total = 0
        while pagina <= args.limite_paginas:
            pedidos = bling.listar_pedidos_vendas(
                pagina=pagina, data_inicial=args.data_inicial, data_final=args.data_final
            )
            if not pedidos:
                break
            for pedido in pedidos:
                sincronizador.sincronizar_pedido(int(pedido["id"]))
                total += 1
            pagina += 1
        print(f"{total} pedidos sincronizados")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
