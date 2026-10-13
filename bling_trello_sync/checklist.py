"""Reconciliador compartilhado do checklist de itens no Trello (vendas e compras)."""

from __future__ import annotations

from typing import Any

from .trello import TrelloClient

NOME_CHECKLIST = "Itens do pedido"


def sincronizar_checklist(
    trello: TrelloClient,
    card_id: str,
    itens: list[tuple[str, bool]],
    nome: str = NOME_CHECKLIST,
) -> None:
    """Mantém o checklist igual à lista de itens, preservando os já marcados à mão."""
    if not itens:
        return
    checklist = next(
        (c for c in trello.listar_checklists(card_id) if c.get("name") == nome),
        None,
    )
    if checklist is None:
        checklist = trello.criar_checklist(card_id, nome)

    existentes: dict[Any, Any] = {
        item.get("name"): item for item in checklist.get("checkItems") or []
    }
    nomes = {titulo for titulo, _ in itens}
    for titulo, concluido in itens:
        atual = existentes.get(titulo)
        if atual is None:
            trello.criar_item_checklist(checklist["id"], titulo, concluido)
        elif concluido and atual.get("state") != "complete":
            trello.marcar_item_checklist(card_id, atual["id"])
    for titulo, item in existentes.items():
        if titulo not in nomes:
            trello.remover_item_checklist(checklist["id"], item["id"])
