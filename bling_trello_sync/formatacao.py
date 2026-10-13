"""Formatação compartilhada de valores e datas do Bling para cards do Trello."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def moeda(valor: Any) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"


def quantidade(item: dict[str, Any]) -> float:
    try:
        return float(item.get("quantidade", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def data_para_trello(valor: Any) -> str | None:
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


def data_brasileira(valor: Any) -> str | None:
    """Formata datas do Bling (com ou sem hora, ISO ou não) como dd/mm/aaaa."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip().replace("T", " ")[:19]
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return None
