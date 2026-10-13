"""Golden queries do contrato de métricas (regressão SQL no CI)."""

from __future__ import annotations

import pytest

from bling_trello_sync.armazem import CONTRATO_METRICAS_VERSAO, Armazem


@pytest.fixture
def armazem(tmp_path) -> Armazem:
    return Armazem(str(tmp_path / "financeiro.db"))


def _popular_cenario(armazem: Armazem) -> None:
    """Cenário fixo: receita 200, despesa 50, fat 180, caixa líquido 147, aberto 50."""
    armazem.gravar(
        "categoria",
        [
            {
                "empresa": "E",
                "id": 1,
                "descricao": "Vendas",
                "tipo": 2,
                "id_categoria_pai": 0,
            },
            {
                "empresa": "E",
                "id": 2,
                "descricao": "Aluguel",
                "tipo": 1,
                "id_categoria_pai": 0,
            },
        ],
    )
    armazem.gravar(
        "conta_receber",
        [
            {
                "empresa": "E",
                "id": 1,
                "situacao": 2,
                "data_emissao": "2026-03-01",
                "competencia": "2026-03-01",
                "vencimento": "2026-03-10",
                "valor": 200.0,
                "saldo": 0.0,
                "valor_recebido": 200.0,
                "numero_documento": None,
                "historico": None,
                "categoria_id": 1,
                "portador_id": None,
                "forma_pagamento_id": None,
                "contato_id": None,
                "contato_nome": "Cliente",
                "origem_id": None,
                "origem_tipo": None,
                "origem_numero": None,
                "atualizado_em": "agora",
            }
        ],
    )
    armazem.gravar(
        "conta_pagar",
        [
            {
                "empresa": "E",
                "id": 2,
                "situacao": 1,
                "data_emissao": "2026-03-01",
                "competencia": "2026-03-01",
                "vencimento": "2026-03-15",
                "valor": 50.0,
                "saldo": 50.0,
                "valor_pago": 0.0,
                "numero_documento": None,
                "historico": None,
                "categoria_id": 2,
                "portador_id": None,
                "forma_pagamento_id": None,
                "contato_id": None,
                "contato_nome": "Fornecedor",
                "atualizado_em": "agora",
            }
        ],
    )
    armazem.gravar(
        "movimento_caixa",
        [
            {
                "empresa": "E",
                "bordero_id": 10,
                "conta_id": 1,
                "sequencia": 1,
                "tipo": "receber",
                "data": "2026-03-10",
                "valor_pago": 150.0,
                "juros": 0.0,
                "desconto": 0.0,
                "acrescimo": 0.0,
                "tarifa": 3.0,
                "categoria_id": 1,
                "portador_id": None,
                "contato_id": None,
                "contato_nome": "Cliente",
                "historico": None,
            }
        ],
    )
    armazem.gravar(
        "pedido_venda",
        [
            {
                "empresa": "E",
                "id": 1,
                "numero": "100",
                "data": "2026-03-05",
                "data_saida": None,
                "total": 180.0,
                "situacao_id": 9,
                "contato_id": None,
                "contato_nome": "Cliente",
                "loja_id": None,
                "vendedor_id": None,
                "atualizado_em": "agora",
            },
            {
                "empresa": "E",
                "id": 2,
                "numero": "101",
                "data": "2026-03-05",
                "data_saida": None,
                "total": 999.0,
                "situacao_id": 12,
                "contato_id": None,
                "contato_nome": "Cancelado",
                "loja_id": None,
                "vendedor_id": None,
                "atualizado_em": "agora",
            },
        ],
    )


def test_contrato_metricas_versao_pinada():
    assert CONTRATO_METRICAS_VERSAO == 1


def test_aliases_v1_coincidem_com_visoes_curtas(armazem):
    _popular_cenario(armazem)
    for curta, v1 in (
        ("vw_dre", "vw_dre_v1"),
        ("vw_fluxo_caixa", "vw_fluxo_caixa_v1"),
        ("vw_faturamento", "vw_faturamento_v1"),
        ("vw_contas_em_aberto", "vw_contas_em_aberto_v1"),
    ):
        a = armazem.ler(f"SELECT * FROM {curta} ORDER BY 1, 2, 3")
        b = armazem.ler(f"SELECT * FROM {v1} ORDER BY 1, 2, 3")
        assert a == b


def test_golden_margem_saldo_e_em_aberto(armazem):
    _popular_cenario(armazem)

    receita = armazem.ler(
        "SELECT SUM(valor) FROM vw_dre_v1 WHERE natureza = 'receita' AND empresa = 'E'"
    )[0][0]
    resultado = armazem.ler("SELECT SUM(valor) FROM vw_dre_v1 WHERE empresa = 'E'")[0][0]
    margem = armazem.ler(
        """SELECT SUM(valor) / NULLIF(SUM(CASE WHEN natureza = 'receita' THEN valor END), 0)
             FROM vw_dre_v1 WHERE empresa = 'E'"""
    )[0][0]
    assert receita == pytest.approx(200.0)
    assert resultado == pytest.approx(150.0)  # 200 − 50
    assert margem == pytest.approx(0.75)

    saldo = armazem.ler("SELECT SUM(valor) FROM vw_fluxo_caixa_v1 WHERE empresa = 'E'")[0][0]
    assert saldo == pytest.approx(147.0)  # 150 − 3 tarifa

    aberto = armazem.ler(
        "SELECT natureza, valor_em_aberto FROM vw_contas_em_aberto_v1 WHERE empresa = 'E'"
    )
    assert aberto == [("despesa", 50.0)]


def test_golden_conciliacao_periodo(armazem):
    """Mesmo calendário março/2026 nos três eixos — gaps esperados e estáveis."""
    _popular_cenario(armazem)
    fat, rec, ent = armazem.ler(
        """
        SELECT
          (SELECT COALESCE(SUM(total), 0) FROM vw_faturamento_v1
            WHERE empresa = 'E' AND data >= '2026-03-01' AND data < '2026-04-01'),
          (SELECT COALESCE(SUM(valor), 0) FROM vw_dre_v1
            WHERE natureza = 'receita' AND empresa = 'E'
              AND competencia >= '2026-03-01' AND competencia < '2026-04-01'),
          (SELECT COALESCE(SUM(valor), 0) FROM vw_fluxo_caixa_v1
            WHERE tipo = 'receber' AND empresa = 'E'
              AND data >= '2026-03-01' AND data < '2026-04-01')
        """
    )[0]
    assert fat == pytest.approx(180.0)  # cancelado excluído
    assert rec == pytest.approx(200.0)
    assert ent == pytest.approx(147.0)
    assert fat - rec == pytest.approx(-20.0)
    assert rec - ent == pytest.approx(53.0)
