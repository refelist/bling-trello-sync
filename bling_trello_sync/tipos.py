"""Tipos leves dos payloads do Bling usados na sincronização."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class ContatoRef(TypedDict, total=False):
    id: int
    nome: str
    numeroDocumento: str


class SituacaoRef(TypedDict, total=False):
    id: int
    valor: int
    nome: str
    descricao: str


class LojaRef(TypedDict, total=False):
    id: int


class ItemPedido(TypedDict, total=False):
    codigo: str
    descricao: str
    quantidade: float
    valor: float
    produto: dict


class PedidoVenda(TypedDict, total=False):
    id: int
    numero: int | str
    data: str
    dataPrevista: str
    total: float
    totalProdutos: float
    contato: ContatoRef
    situacao: SituacaoRef
    loja: LojaRef
    itens: list[ItemPedido]
    observacoes: str
    notaFiscal: dict
    notasFiscais: list[dict]


class FornecedorRef(TypedDict, total=False):
    id: int
    nome: str


class PedidoCompra(TypedDict, total=False):
    id: int
    numero: int | str
    data: str
    dataPrevista: str
    total: float
    totalProdutos: float
    fornecedor: FornecedorRef
    situacao: SituacaoRef
    itens: list[ItemPedido]
    observacoes: str
    observacoesInternas: NotRequired[str]
    ordemCompra: str
    transporte: dict
    categoria: dict
