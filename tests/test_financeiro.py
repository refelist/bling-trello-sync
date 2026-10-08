import pytest

from bling_trello_sync.armazem import Armazem
from bling_trello_sync.financeiro import (
    ColetorFinanceiro,
    janelas_do_periodo,
    linha_conta_pagar,
    linha_conta_receber,
    linhas_do_bordero,
)


@pytest.fixture
def armazem(tmp_path) -> Armazem:
    return Armazem(str(tmp_path / "financeiro.db"))


class BlingFake:
    def __init__(self) -> None:
        self.contas_receber = [
            {"id": 1, "situacao": 2, "valor": 100.0, "vencimento": "2026-01-10"},
        ]
        self.contas_pagar = [
            {"id": 7, "situacao": 1, "valor": 250.0, "vencimento": "2026-02-05"},
        ]
        self.detalhes_lidos: list[int] = []

    def listar_categorias_receitas_despesas(self, pagina=1, limite=100):
        if pagina > 1:
            return []
        return [{"id": 10, "descricao": "Vendas", "tipo": 2, "idCategoriaPai": 0}]

    def listar_contas_financeiras(self, pagina=1, limite=100):
        if pagina > 1:
            return []
        return [{"id": 20, "descricao": "Banco X", "tipo": "conta_bancaria"}]

    def listar_formas_pagamentos(self, pagina=1, limite=100):
        if pagina > 1:
            return []
        return [{"id": 30, "descricao": "Boleto", "tipoPagamento": 2, "situacao": 1}]

    def listar_contas_receber(self, pagina=1, limite=100, tipo_filtro_data="E", **kwargs):
        if pagina > 1 or tipo_filtro_data != "E":
            return []
        return self.contas_receber

    def obter_conta_receber(self, conta_id):
        self.detalhes_lidos.append(conta_id)
        return {
            "id": conta_id,
            "situacao": 2,
            "valor": 100.0,
            "saldo": 0.0,
            "vencimento": "2026-01-10",
            "dataEmissao": "2026-01-01",
            "competencia": "2026-01-01",
            "categoria": {"id": 10},
            "portador": {"id": 20},
            "contato": {"id": 5, "nome": "Cliente", "numeroDocumento": "1"},
            "origem": {"id": 99, "tipoOrigem": "Pedido de venda", "numero": "123"},
            "borderos": [500],
        }

    def listar_contas_pagar(self, pagina=1, limite=100, **kwargs):
        if pagina > 1 or "data_emissao_inicial" not in kwargs:
            return []
        return self.contas_pagar

    def obter_conta_pagar(self, conta_id):
        self.detalhes_lidos.append(conta_id)
        return {
            "id": conta_id,
            "situacao": 1,
            "valor": 250.0,
            "saldo": 250.0,
            "vencimento": "2026-02-05",
            "dataEmissao": "2026-01-15",
            "categoria": {"id": 10},
            "contato": {"id": 8, "nome": "Fornecedor"},
        }

    def obter_bordero(self, bordero_id):
        return {
            "id": bordero_id,
            "data": "2026-01-11",
            "historico": "Recebimento",
            "portador": {"id": 20},
            "categoria": {"id": 10},
            "pagamentos": [
                {
                    "contato": {"id": 5, "nome": "Cliente"},
                    "valorPago": 100.0,
                    "juros": 0.0,
                    "desconto": 0.0,
                    "acrescimo": 0.0,
                    "tarifa": 1.5,
                }
            ],
        }

    def listar_pedidos_vendas(self, pagina=1, limite=100, **kwargs):
        if pagina > 1:
            return []
        return [
            {
                "id": 900,
                "numero": 55,
                "data": "2026-01-05",
                "total": 1500.0,
                "situacao": {"id": 9},
                "contato": {"id": 5, "nome": "Cliente"},
                "loja": {"id": 3},
            }
        ]


def _coletor(settings, armazem) -> tuple[ColetorFinanceiro, BlingFake]:
    bling = BlingFake()
    configurado = settings.model_copy(update={"financeiro_empresa": "Empresa 1"})
    return ColetorFinanceiro(configurado, bling, armazem), bling


def test_valor_recebido_vem_do_saldo():
    linha = linha_conta_receber(
        {"id": 1, "situacao": 3, "valor": 100.0, "saldo": 40.0}, "Empresa 1", "agora"
    )
    assert linha["valor_recebido"] == 60.0


def test_conta_pagar_em_aberto_nao_tem_valor_pago():
    linha = linha_conta_pagar(
        {"id": 1, "situacao": 1, "valor": 80.0, "saldo": 80.0}, "Empresa 1", "agora"
    )
    assert linha["valor_pago"] == 0.0
    assert linha["vencimento"] is None


def test_bordero_gera_um_movimento_por_pagamento():
    bordero = {
        "id": 3,
        "data": "2026-01-11 10:00:00",
        "pagamentos": [{"valorPago": 10.0}, {"valorPago": 20.0}],
    }
    linhas = linhas_do_bordero(bordero, "Empresa 1", "pagar", conta_id=7)
    assert [linha["valor_pago"] for linha in linhas] == [10.0, 20.0]
    assert linhas[0]["data"] == "2026-01-11"
    assert linhas[0]["conta_id"] == 7


def test_coleta_grava_tabelas_e_visoes(settings, armazem):
    coletor, _ = _coletor(settings, armazem)
    resumo = coletor.coletar(dias=30)

    assert resumo.erros == []
    assert armazem.ler("SELECT COUNT(*) FROM conta_receber")[0][0] == 1
    assert armazem.ler("SELECT COUNT(*) FROM conta_pagar")[0][0] == 1
    assert armazem.ler("SELECT COUNT(*) FROM movimento_caixa")[0][0] == 1
    assert armazem.ler("SELECT COUNT(*) FROM pedido_venda")[0][0] == 1
    assert armazem.ler("SELECT COUNT(*) FROM contato")[0][0] == 2

    dre = dict(armazem.ler("SELECT natureza, SUM(valor) FROM vw_dre GROUP BY natureza"))
    assert dre == {"receita": 100.0, "despesa": -250.0}

    caixa = armazem.ler("SELECT SUM(valor) FROM vw_fluxo_caixa")[0][0]
    assert caixa == 100.0

    aberto = armazem.ler("SELECT natureza, valor_em_aberto FROM vw_contas_em_aberto")
    assert aberto == [("despesa", 250.0)]


def test_segunda_coleta_nao_relê_contas_inalteradas(settings, armazem):
    coletor, bling = _coletor(settings, armazem)
    coletor.coletar(dias=30)
    bling.detalhes_lidos.clear()

    coletor.coletar(dias=30)
    assert bling.detalhes_lidos == []

    bling.contas_receber[0]["situacao"] = 1
    coletor.coletar(dias=30)
    assert bling.detalhes_lidos == [1]


def test_recarregar_tudo_forca_a_releitura(settings, armazem):
    coletor, bling = _coletor(settings, armazem)
    coletor.coletar(dias=30)
    bling.detalhes_lidos.clear()

    coletor.coletar(dias=30, recarregar_tudo=True)
    assert sorted(bling.detalhes_lidos) == [1, 7]


def test_empresas_diferentes_convivem_na_mesma_base(settings, armazem):
    coletor_um, _ = _coletor(settings, armazem)
    coletor_um.coletar(dias=30)
    coletor_dois = ColetorFinanceiro(
        settings.model_copy(update={"financeiro_empresa": "Empresa 2"}), BlingFake(), armazem
    )
    coletor_dois.coletar(dias=30)

    empresas = armazem.ler("SELECT DISTINCT empresa FROM conta_receber ORDER BY empresa")
    assert empresas == [("Empresa 1",), ("Empresa 2",)]
    assert armazem.ler("SELECT COUNT(*) FROM conta_receber")[0][0] == 2


def test_periodo_longo_e_dividido_em_janelas_de_ate_366_dias():
    assert janelas_do_periodo("2025-10-05", "2027-10-05") == [
        ("2025-10-05", "2026-10-05"),
        ("2026-10-06", "2027-10-05"),
    ]
    assert janelas_do_periodo("2026-01-01", "2026-01-31") == [("2026-01-01", "2026-01-31")]


def test_coleta_consulta_o_bling_em_janelas_de_ate_366_dias(settings, armazem):
    coletor, bling = _coletor(settings, armazem)
    periodos: list[tuple[str, str]] = []
    original = bling.listar_contas_receber

    def listar(pagina=1, limite=100, tipo_filtro_data="E", data_inicial=None, data_final=None):
        periodos.append((data_inicial, data_final))
        return original(pagina=pagina, limite=limite, tipo_filtro_data=tipo_filtro_data)

    bling.listar_contas_receber = listar
    coletor.coletar(data_inicial="2025-10-05", data_final="2027-10-05")

    assert set(periodos) == {("2025-10-05", "2026-10-05"), ("2026-10-06", "2027-10-05")}
    assert armazem.ler("SELECT COUNT(*) FROM conta_receber")[0][0] == 1


def test_data_zerada_do_bling_vira_vazia():
    conta = {"id": 1, "situacao": 1, "valor": 10.0, "vencimento": "0000-00-00", "dataEmissao": ""}
    linha = linha_conta_pagar(conta, "Empresa 1", "2026-01-01T00:00:00")
    assert linha["vencimento"] is None
    assert linha["data_emissao"] is None


def test_nome_do_contato_que_veio_so_com_codigo_e_buscado_no_cadastro(settings, armazem):
    coletor, bling = _coletor(settings, armazem)
    original = bling.obter_conta_pagar
    bling.obter_conta_pagar = lambda conta_id: {**original(conta_id), "contato": {"id": 8}}
    buscados: list[int] = []

    def obter_contato(contato_id):
        buscados.append(contato_id)
        return {"id": contato_id, "nome": "Fornecedor do cadastro", "numeroDocumento": "2"}

    bling.obter_contato = obter_contato
    coletor.coletar(dias=30)
    coletor.coletar(dias=30)

    assert buscados == [8]
    aberto = armazem.ler("SELECT contato_nome FROM vw_contas_em_aberto WHERE natureza = 'despesa'")
    assert aberto == [("Fornecedor do cadastro",)]
