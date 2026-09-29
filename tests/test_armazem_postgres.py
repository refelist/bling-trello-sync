"""Roda a coleta contra um PostgreSQL de verdade quando FINANCEIRO_TEST_POSTGRES está definido."""

import os

import pytest
from test_financeiro import BlingFake, _coletor

from bling_trello_sync.armazem import Armazem

URL = os.environ.get("FINANCEIRO_TEST_POSTGRES")

pytestmark = pytest.mark.skipif(not URL, reason="sem PostgreSQL de teste")


@pytest.fixture
def armazem_pg() -> Armazem:
    assert URL
    armazem = Armazem(URL)
    tabelas = (
        "conta_receber",
        "conta_pagar",
        "movimento_caixa",
        "pedido_venda",
        "contato",
        "categoria",
        "conta_financeira",
        "forma_pagamento",
    )
    with armazem.conexao() as conn:
        cursor = conn.cursor()
        for tabela in tabelas:
            cursor.execute(f"DELETE FROM {tabela}")
    return armazem


def test_coleta_no_postgres(settings, armazem_pg):
    coletor, _ = _coletor(settings, armazem_pg)
    resumo = coletor.coletar(dias=30)

    assert resumo.erros == []
    assert armazem_pg.ler("SELECT COUNT(*) FROM conta_receber")[0][0] == 1
    assert armazem_pg.ler("SELECT COUNT(*) FROM movimento_caixa")[0][0] == 1

    dre = dict(armazem_pg.ler("SELECT natureza, SUM(valor) FROM vw_dre GROUP BY natureza"))
    assert dre == {"receita": 100.0, "despesa": -250.0}


def test_upsert_nao_duplica_no_postgres(settings, armazem_pg):
    coletor, _ = _coletor(settings, armazem_pg)
    coletor.coletar(dias=30)
    coletor.coletar(dias=30, recarregar_tudo=True)

    assert armazem_pg.ler("SELECT COUNT(*) FROM conta_receber")[0][0] == 1
    assert armazem_pg.ler("SELECT COUNT(*) FROM movimento_caixa")[0][0] == 1


def test_duas_empresas_no_postgres(settings, armazem_pg):
    from bling_trello_sync.financeiro import ColetorFinanceiro

    coletor, _ = _coletor(settings, armazem_pg)
    coletor.coletar(dias=30)
    ColetorFinanceiro(
        settings.model_copy(update={"financeiro_empresa": "Empresa 2"}), BlingFake(), armazem_pg
    ).coletar(dias=30)

    empresas = armazem_pg.ler("SELECT DISTINCT empresa FROM conta_receber ORDER BY empresa")
    assert empresas == [("Empresa 1",), ("Empresa 2",)]
