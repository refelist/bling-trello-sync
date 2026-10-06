"""Coleta os dados financeiros do Bling e grava no banco lido pelo Power BI.

Cada conta do Bling roda uma cópia do programa e grava na mesma base, identificada pela
coluna `empresa`, de modo que os relatórios possam mostrar uma empresa, a outra ou as duas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import product
from typing import Any

from .armazem import Armazem, versao_da_conta
from .bling import BlingClient
from .config import Settings

logger = logging.getLogger(__name__)

MAIOR_PERIODO_DIAS = 366


def janelas_do_periodo(inicio: str, fim: str, dias: int = MAIOR_PERIODO_DIAS) -> list[tuple[str, str]]:
    """Divide o período em janelas de até `dias` dias, o máximo que o Bling aceita por consulta."""
    atual = date.fromisoformat(inicio)
    ultimo = date.fromisoformat(fim)
    janelas: list[tuple[str, str]] = []
    while atual <= ultimo:
        final = min(atual + timedelta(days=dias - 1), ultimo)
        janelas.append((atual.isoformat(), final.isoformat()))
        atual = final + timedelta(days=1)
    return janelas


@dataclass
class ResumoFinanceiro:
    linhas: dict[str, int] = field(default_factory=dict)
    erros: list[tuple[str, str]] = field(default_factory=list)

    def somar(self, tabela: str, quantidade: int) -> None:
        self.linhas[tabela] = self.linhas.get(tabela, 0) + quantidade

    def __str__(self) -> str:
        partes = [f"{tabela}: {total}" for tabela, total in sorted(self.linhas.items())]
        return " | ".join(partes) if partes else "nada gravado"


def _float(valor: Any) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _int(valor: Any) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _data(valor: Any) -> str | None:
    """Mantém só a parte AAAA-MM-DD; devolve None quando o Bling manda vazio ou "0000-00-00"."""
    texto = str(valor or "").strip()[:10]
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        return None


def _texto(valor: Any) -> str | None:
    texto = str(valor or "").strip()
    return texto or None


def linha_categoria(categoria: dict[str, Any], empresa: str) -> dict[str, Any]:
    return {
        "empresa": empresa,
        "id": _int(categoria.get("id")),
        "descricao": _texto(categoria.get("descricao")),
        "tipo": _int(categoria.get("tipo")),
        "id_categoria_pai": _int(categoria.get("idCategoriaPai")),
    }


def linha_conta_financeira(conta: dict[str, Any], empresa: str) -> dict[str, Any]:
    return {
        "empresa": empresa,
        "id": _int(conta.get("id")),
        "descricao": _texto(conta.get("descricao")),
        "tipo": _texto(conta.get("tipo")),
    }


def linha_forma_pagamento(forma: dict[str, Any], empresa: str) -> dict[str, Any]:
    return {
        "empresa": empresa,
        "id": _int(forma.get("id")),
        "descricao": _texto(forma.get("descricao")),
        "tipo_pagamento": _int(forma.get("tipoPagamento")),
        "situacao": _int(forma.get("situacao")),
    }


def linha_contato(contato: dict[str, Any], empresa: str) -> dict[str, Any] | None:
    contato_id = _int(contato.get("id"))
    if contato_id is None:
        return None
    return {
        "empresa": empresa,
        "id": contato_id,
        "nome": _texto(contato.get("nome")),
        "documento": _texto(contato.get("numeroDocumento")),
        "tipo": _texto(contato.get("tipo")),
    }


def _valor_liquidado(conta: dict[str, Any]) -> float | None:
    """Parte já paga/recebida: valor da conta menos o saldo em aberto."""
    valor = _float(conta.get("valor"))
    saldo = _float(conta.get("saldo"))
    if valor is None:
        return None
    if saldo is None:
        return valor if _int(conta.get("situacao")) == 2 else None
    return round(valor - saldo, 2)


def linha_conta_receber(conta: dict[str, Any], empresa: str, agora: str) -> dict[str, Any]:
    contato = conta.get("contato") or {}
    origem = conta.get("origem") or {}
    return {
        "empresa": empresa,
        "id": _int(conta.get("id")),
        "situacao": _int(conta.get("situacao")),
        "data_emissao": _data(conta.get("dataEmissao")),
        "competencia": _data(conta.get("competencia")),
        "vencimento": _data(conta.get("vencimento")),
        "valor": _float(conta.get("valor")),
        "saldo": _float(conta.get("saldo")),
        "valor_recebido": _valor_liquidado(conta),
        "numero_documento": _texto(conta.get("numeroDocumento")),
        "historico": _texto(conta.get("historico")),
        "categoria_id": _int((conta.get("categoria") or {}).get("id")),
        "portador_id": _int((conta.get("portador") or {}).get("id")),
        "forma_pagamento_id": _int((conta.get("formaPagamento") or {}).get("id")),
        "contato_id": _int(contato.get("id")),
        "contato_nome": _texto(contato.get("nome")),
        "vendedor_id": _int((conta.get("vendedor") or {}).get("id")),
        "origem_tipo": _texto(origem.get("tipoOrigem")),
        "origem_id": _int(origem.get("id")),
        "origem_numero": _texto(origem.get("numero")),
        "atualizado_em": agora,
    }


def linha_conta_pagar(conta: dict[str, Any], empresa: str, agora: str) -> dict[str, Any]:
    contato = conta.get("contato") or {}
    return {
        "empresa": empresa,
        "id": _int(conta.get("id")),
        "situacao": _int(conta.get("situacao")),
        "data_emissao": _data(conta.get("dataEmissao")),
        "competencia": _data(conta.get("competencia")),
        "vencimento": _data(conta.get("vencimento")),
        "valor": _float(conta.get("valor")),
        "saldo": _float(conta.get("saldo")),
        "valor_pago": _valor_liquidado(conta),
        "numero_documento": _texto(conta.get("numeroDocumento")),
        "historico": _texto(conta.get("historico")),
        "categoria_id": _int((conta.get("categoria") or {}).get("id")),
        "portador_id": _int((conta.get("portador") or {}).get("id")),
        "forma_pagamento_id": _int((conta.get("formaPagamento") or {}).get("id")),
        "contato_id": _int(contato.get("id")),
        "contato_nome": _texto(contato.get("nome")),
        "atualizado_em": agora,
    }


def linhas_do_bordero(
    bordero: dict[str, Any], empresa: str, tipo: str, conta_id: int
) -> list[dict[str, Any]]:
    """Um movimento de caixa por pagamento do borderô, ligado à conta que o originou."""
    linhas = []
    for pagamento in bordero.get("pagamentos") or []:
        contato = pagamento.get("contato") or {}
        linhas.append(
            {
                "empresa": empresa,
                "bordero_id": _int(bordero.get("id")),
                "conta_id": conta_id,
                "tipo": tipo,
                "data": _data(bordero.get("data")),
                "valor_pago": _float(pagamento.get("valorPago")),
                "juros": _float(pagamento.get("juros")),
                "desconto": _float(pagamento.get("desconto")),
                "acrescimo": _float(pagamento.get("acrescimo")),
                "tarifa": _float(pagamento.get("tarifa")),
                "categoria_id": _int((bordero.get("categoria") or {}).get("id")),
                "portador_id": _int((bordero.get("portador") or {}).get("id")),
                "contato_id": _int(contato.get("id")),
                "contato_nome": _texto(contato.get("nome")),
                "historico": _texto(bordero.get("historico")),
            }
        )
    return linhas


def linha_pedido_venda(pedido: dict[str, Any], empresa: str, agora: str) -> dict[str, Any]:
    contato = pedido.get("contato") or {}
    return {
        "empresa": empresa,
        "id": _int(pedido.get("id")),
        "numero": _texto(pedido.get("numero")),
        "data": _data(pedido.get("data")),
        "data_saida": _data(pedido.get("dataSaida")),
        "total": _float(pedido.get("total")),
        "situacao_id": _int((pedido.get("situacao") or {}).get("id")),
        "contato_id": _int(contato.get("id")),
        "contato_nome": _texto(contato.get("nome")),
        "loja_id": _int((pedido.get("loja") or {}).get("id")),
        "vendedor_id": _int((pedido.get("vendedor") or {}).get("id")),
        "atualizado_em": agora,
    }


class ColetorFinanceiro:
    def __init__(self, settings: Settings, bling: BlingClient, armazem: Armazem) -> None:
        self.settings = settings
        self.bling = bling
        self.armazem = armazem
        self.empresa = settings.financeiro_empresa

    def _paginar(self, buscar: Any, limite_paginas: int = 200) -> list[dict[str, Any]]:
        registros: list[dict[str, Any]] = []
        for pagina in range(1, limite_paginas + 1):
            lote = buscar(pagina)
            if not lote:
                break
            registros.extend(lote)
        return registros

    def coletar_dimensoes(self, resumo: ResumoFinanceiro) -> None:
        categorias = self._paginar(lambda p: self.bling.listar_categorias_receitas_despesas(pagina=p))
        resumo.somar(
            "categoria",
            self.armazem.gravar("categoria", [linha_categoria(c, self.empresa) for c in categorias]),
        )

        contas = self._paginar(lambda p: self.bling.listar_contas_financeiras(pagina=p))
        resumo.somar(
            "conta_financeira",
            self.armazem.gravar(
                "conta_financeira", [linha_conta_financeira(c, self.empresa) for c in contas]
            ),
        )

        formas = self._paginar(lambda p: self.bling.listar_formas_pagamentos(pagina=p))
        resumo.somar(
            "forma_pagamento",
            self.armazem.gravar(
                "forma_pagamento", [linha_forma_pagamento(f, self.empresa) for f in formas]
            ),
        )

    def _contas_receber_do_periodo(self, inicio: str, fim: str) -> dict[int, dict[str, Any]]:
        """Contas a receber emitidas, vencidas ou recebidas no período, sem repetir."""
        encontradas: dict[int, dict[str, Any]] = {}
        for (ini, fin), tipo_filtro in product(janelas_do_periodo(inicio, fim), ("E", "V", "R")):
            registros = self._paginar(
                lambda p, t=tipo_filtro, i=ini, f=fin: self.bling.listar_contas_receber(
                    pagina=p, tipo_filtro_data=t, data_inicial=i, data_final=f
                )
            )
            for registro in registros:
                conta_id = _int(registro.get("id"))
                if conta_id is not None:
                    encontradas[conta_id] = registro
        return encontradas

    def _contas_pagar_do_periodo(self, inicio: str, fim: str) -> dict[int, dict[str, Any]]:
        encontradas: dict[int, dict[str, Any]] = {}
        filtros = [
            {f"data_{campo}_inicial": ini, f"data_{campo}_final": fin}
            for ini, fin in janelas_do_periodo(inicio, fim)
            for campo in ("emissao", "vencimento", "pagamento")
        ]
        for filtro in filtros:
            registros = self._paginar(
                lambda p, f=filtro: self.bling.listar_contas_pagar(pagina=p, **f)
            )
            for registro in registros:
                conta_id = _int(registro.get("id"))
                if conta_id is not None:
                    encontradas[conta_id] = registro
        return encontradas

    def _coletar_contas(
        self,
        tabela: str,
        encontradas: dict[int, dict[str, Any]],
        obter_detalhe: Any,
        montar_linha: Any,
        tipo_movimento: str,
        resumo: ResumoFinanceiro,
        recarregar_tudo: bool,
    ) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        conhecidas = {} if recarregar_tudo else self.armazem.versoes_das_contas(tabela, self.empresa)
        borderos_gravados = self.armazem.borderos_conhecidos(self.empresa)
        linhas: list[dict[str, Any]] = []
        contatos: list[dict[str, Any]] = []
        movimentos: list[dict[str, Any]] = []

        for conta_id, resumida in encontradas.items():
            versao = versao_da_conta(
                resumida.get("situacao"), resumida.get("valor"), _data(resumida.get("vencimento"))
            )
            if conhecidas.get(conta_id) == versao:
                continue
            try:
                detalhe = obter_detalhe(conta_id)
            except Exception as erro:  # noqa: BLE001 - uma conta com erro não para a coleta
                logger.warning("Falha ao ler a conta %s de %s: %s", conta_id, tabela, erro)
                resumo.erros.append((f"{tabela}:{conta_id}", str(erro)))
                continue
            detalhe = {**resumida, **detalhe, "id": conta_id}
            linhas.append(montar_linha(detalhe, self.empresa, agora))
            contato = linha_contato(detalhe.get("contato") or {}, self.empresa)
            if contato is not None:
                contatos.append(contato)
            for bordero_id in detalhe.get("borderos") or []:
                identificador = _int(bordero_id)
                if identificador is None or identificador in borderos_gravados:
                    continue
                try:
                    bordero = self.bling.obter_bordero(identificador)
                except Exception as erro:  # noqa: BLE001 - o borderô é complementar
                    logger.warning("Falha ao ler o borderô %s: %s", identificador, erro)
                    resumo.erros.append((f"bordero:{identificador}", str(erro)))
                    continue
                movimentos.extend(
                    linhas_do_bordero(bordero, self.empresa, tipo_movimento, conta_id)
                )
                borderos_gravados.add(identificador)

        resumo.somar(tabela, self.armazem.gravar(tabela, linhas))
        resumo.somar("contato", self.armazem.gravar("contato", _sem_repetir(contatos, ("id",))))
        resumo.somar(
            "movimento_caixa",
            self.armazem.gravar(
                "movimento_caixa", _sem_repetir(movimentos, ("bordero_id", "conta_id"))
            ),
        )

    def coletar_pedidos_venda(self, inicio: str, fim: str, resumo: ResumoFinanceiro) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        pedidos: list[dict[str, Any]] = []
        for ini, fin in janelas_do_periodo(inicio, fim):
            pedidos.extend(
                self._paginar(
                    lambda p, i=ini, f=fin: self.bling.listar_pedidos_vendas(
                        pagina=p, data_inicial=i, data_final=f
                    )
                )
            )
        linhas = [linha_pedido_venda(pedido, self.empresa, agora) for pedido in pedidos]
        resumo.somar("pedido_venda", self.armazem.gravar("pedido_venda", linhas))

    def coletar(
        self,
        dias: int | None = None,
        data_inicial: str | None = None,
        data_final: str | None = None,
        recarregar_tudo: bool = False,
    ) -> ResumoFinanceiro:
        if data_inicial is None:
            janela = dias if dias is not None else self.settings.financeiro_dias
            data_inicial = (date.today() - timedelta(days=janela)).strftime("%Y-%m-%d")
        if data_final is None:
            # O Bling só respeita o período quando recebe também a data final.
            data_final = (date.today() + timedelta(days=self.settings.financeiro_dias_futuros)).strftime(
                "%Y-%m-%d"
            )

        resumo = ResumoFinanceiro()
        self.coletar_dimensoes(resumo)
        self._coletar_contas(
            "conta_receber",
            self._contas_receber_do_periodo(data_inicial, data_final),
            self.bling.obter_conta_receber,
            linha_conta_receber,
            "receber",
            resumo,
            recarregar_tudo,
        )
        self._coletar_contas(
            "conta_pagar",
            self._contas_pagar_do_periodo(data_inicial, data_final),
            self.bling.obter_conta_pagar,
            linha_conta_pagar,
            "pagar",
            resumo,
            recarregar_tudo,
        )
        self.coletar_pedidos_venda(data_inicial, data_final, resumo)
        logger.info("Coleta financeira de %s a %s: %s", data_inicial, data_final, resumo)
        return resumo


def _sem_repetir(linhas: list[dict[str, Any]], chaves: tuple[str, ...]) -> list[dict[str, Any]]:
    unicas: dict[tuple[Any, ...], dict[str, Any]] = {}
    for linha in linhas:
        unicas[tuple(linha[chave] for chave in chaves)] = linha
    return list(unicas.values())
