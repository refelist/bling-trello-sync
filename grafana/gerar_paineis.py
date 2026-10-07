"""Gera os painéis do Grafana (grafana/paineis/*.json) a partir das visões do PostgreSQL.

Rode `python grafana/gerar_paineis.py` depois de mudar este arquivo e faça commit dos JSON.
"""

import json
from pathlib import Path

DESTINO = Path(__file__).parent / "paineis"
FONTE = {"type": "grafana-postgresql-datasource", "uid": "financeiro"}

AZUL = "#1F4E79"
VERDE = "#2E7D32"
VERMELHO = "#C62828"
LARANJA = "#EF6C00"
ROXO = "#6A1B9A"

EMPRESA = "empresa IN ($empresa)"


def consulta(sql: str, formato: str = "table") -> list[dict]:
    return [{
        "refId": "A",
        "datasource": FONTE,
        "editorMode": "code",
        "rawQuery": True,
        "format": formato,
        "rawSql": " ".join(sql.split()),
    }]


class Painel:
    def __init__(self, uid: str, titulo: str, descricao: str) -> None:
        self.uid = uid
        self.titulo = titulo
        self.descricao = descricao
        self.paineis: list[dict] = []

    def add(self, x: int, y: int, w: int, h: int, painel: dict) -> None:
        painel["id"] = len(self.paineis) + 1
        painel["gridPos"] = {"x": x, "y": y, "w": w, "h": h}
        painel["datasource"] = FONTE
        self.paineis.append(painel)

    def json(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.titulo,
            "description": self.descricao,
            "tags": ["financeiro"],
            "timezone": "utc",
            "editable": False,
            "graphTooltip": 1,
            "schemaVersion": 41,
            "version": 1,
            "refresh": "",
            "time": {"from": "now-12M/M", "to": "now"},
            "timepicker": {},
            "links": [{
                "title": "Páginas",
                "type": "dashboards",
                "tags": ["financeiro"],
                "asDropdown": False,
                "includeVars": True,
                "keepTime": True,
                "targetBlank": False,
                "icon": "dashboard",
            }],
            "templating": {"list": [{
                "name": "empresa",
                "label": "Empresa",
                "type": "query",
                "datasource": FONTE,
                "query": "SELECT DISTINCT empresa FROM vw_lancamento ORDER BY 1",
                "definition": "SELECT DISTINCT empresa FROM vw_lancamento ORDER BY 1",
                "multi": True,
                "includeAll": True,
                "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                "refresh": 1,
                "sort": 1,
                "options": [],
            }]},
            "annotations": {"list": []},
            "panels": self.paineis,
        }


def numero(titulo: str, sql: str, cor: str, unidade: str = "currencyBRL",
           descricao: str = "") -> dict:
    return {
        "type": "stat",
        "title": titulo,
        "description": descricao,
        "targets": consulta(sql),
        "fieldConfig": {
            "defaults": {
                "unit": unidade,
                "decimals": 0 if unidade == "none" else (1 if unidade == "percentunit" else 2),
                "color": {"mode": "fixed", "fixedColor": cor},
                "noValue": "0",
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value",
            "justifyMode": "center",
            "orientation": "auto",
            "wideLayout": True,
            "showPercentChange": False,
        },
    }


def cores_por_nome(cores: dict[str, str]) -> list[dict]:
    return [{
        "matcher": {"id": "byName", "options": nome},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": cor}}],
    } for nome, cor in cores.items()]


def colunas_mensais(titulo: str, sql: str, cores: dict[str, str] | None = None,
                    empilhar: bool = False, unidade: str = "currencyBRL") -> dict:
    """Barras por mês; a consulta devolve time, metric e value (uma série por metric)."""
    return {
        "type": "timeseries",
        "title": titulo,
        "targets": consulta(sql, "time_series"),
        "fieldConfig": {
            "defaults": {
                "unit": unidade,
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "bars",
                    "fillOpacity": 85,
                    "lineWidth": 1,
                    "barAlignment": 0,
                    "showPoints": "never",
                    "stacking": {"mode": "normal" if empilhar else "none", "group": "A"},
                    "axisPlacement": "auto",
                    "axisSoftMin": 0,
                },
            },
            "overrides": cores_por_nome(cores or {}),
        },
        "options": {
            "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "multi", "sort": "none"},
        },
    }


def linha(titulo: str, sql: str, cor: str) -> dict:
    return {
        "type": "timeseries",
        "title": titulo,
        "targets": consulta(sql, "time_series"),
        "fieldConfig": {
            "defaults": {
                "unit": "currencyBRL",
                "color": {"mode": "fixed", "fixedColor": cor},
                "custom": {
                    "drawStyle": "line",
                    "lineWidth": 2,
                    "fillOpacity": 15,
                    "showPoints": "never",
                    "lineInterpolation": "linear",
                },
            },
            "overrides": [],
        },
        "options": {
            "legend": {"showLegend": False, "displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "single", "sort": "none"},
        },
    }


def barras(titulo: str, sql: str, eixo: str, cor: str, horizontal: bool = True,
           descricao: str = "", cores: dict[str, str] | None = None) -> dict:
    """Barras com rótulo de texto; a ordem das barras é a ordem das linhas da consulta."""
    return {
        "type": "barchart",
        "title": titulo,
        "description": descricao,
        "targets": consulta(sql),
        "fieldConfig": {
            "defaults": {
                "unit": "currencyBRL",
                "color": {"mode": "fixed", "fixedColor": cor},
                "custom": {"fillOpacity": 85, "lineWidth": 0, "axisSoftMin": 0},
            },
            "overrides": cores_por_nome(cores or {}),
        },
        "options": {
            "orientation": "horizontal" if horizontal else "vertical",
            "xField": eixo,
            "showValue": "auto",
            "barWidth": 0.8,
            "groupWidth": 0.7,
            "stacking": "none",
            "xTickLabelRotation": 0 if horizontal else -45,
            "xTickLabelMaxLength": 28,
            "legend": {"showLegend": bool(cores), "displayMode": "list", "placement": "bottom"},
            "tooltip": {"mode": "single", "sort": "none"},
        },
    }


def tabela(titulo: str, sql: str, contagens: tuple[str, ...] = (), percentuais: tuple[str, ...] = (),
           descricao: str = "") -> dict:
    overrides = [{
        "matcher": {"id": "byName", "options": nome},
        "properties": [{"id": "unit", "value": "none"}, {"id": "decimals", "value": 0}],
    } for nome in contagens] + [{
        "matcher": {"id": "byName", "options": nome},
        "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}],
    } for nome in percentuais]
    return {
        "type": "table",
        "title": titulo,
        "description": descricao,
        "targets": consulta(sql),
        "fieldConfig": {
            "defaults": {"unit": "currencyBRL", "decimals": 2, "custom": {"align": "auto", "minWidth": 90}},
            "overrides": overrides,
        },
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
    }


# Somas reaproveitadas pelos cartões
FATURAMENTO = f"SELECT COALESCE(SUM(total), 0) FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data)"
RECEITA = (f"SELECT COALESCE(SUM(valor), 0) FROM vw_dre WHERE natureza = 'receita' AND {EMPRESA} "
           "AND $__timeFilter(competencia)")
DESPESAS = (f"SELECT COALESCE(-SUM(valor), 0) FROM vw_dre WHERE natureza = 'despesa' AND {EMPRESA} "
            "AND $__timeFilter(competencia)")
RESULTADO = f"SELECT COALESCE(SUM(valor), 0) FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)"
MARGEM = (f"SELECT SUM(valor) / NULLIF(SUM(valor) FILTER (WHERE natureza = 'receita'), 0) FROM vw_dre "
          f"WHERE {EMPRESA} AND $__timeFilter(competencia)")
SALDO_CAIXA = f"SELECT COALESCE(SUM(valor), 0) FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data)"


def em_aberto(natureza: str, filtro: str = "") -> str:
    return (f"SELECT COALESCE(SUM(valor_em_aberto), 0) FROM vw_contas_em_aberto "
            f"WHERE natureza = '{natureza}' AND {EMPRESA} {filtro}")


ABERTO_DESCRICAO = "Tudo o que está em aberto hoje, independente do período escolhido."
FAT_MENSAL = (f"SELECT date_trunc('month', data)::timestamp AS time, empresa AS metric, SUM(total) AS value "
              f"FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1, 2 ORDER BY 1")
ENTRADAS_SAIDAS = (f"""
    SELECT to_char(date_trunc('month', data), 'MM/YY') AS "Mês",
           SUM(valor) FILTER (WHERE tipo = 'receber') AS "Entradas",
           -SUM(valor) FILTER (WHERE tipo = 'pagar') AS "Saídas"
      FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data)
     GROUP BY date_trunc('month', data) ORDER BY date_trunc('month', data)""")
CORES_CAIXA = {"Entradas": VERDE, "Saídas": VERMELHO}


def visao_geral() -> Painel:
    p = Painel("fin-visao-geral", "1. Visão Geral",
               "Resumo do período: faturamento, resultado, caixa e contas em aberto.")
    cartoes = [
        ("Faturamento", FATURAMENTO, AZUL, "currencyBRL", ""),
        ("Receita", RECEITA, VERDE, "currencyBRL", ""),
        ("Despesas", DESPESAS, VERMELHO, "currencyBRL", ""),
        ("Resultado", RESULTADO, AZUL, "currencyBRL", ""),
        ("Margem", MARGEM, AZUL, "percentunit", ""),
        ("Saldo do caixa", SALDO_CAIXA, ROXO, "currencyBRL", "Entradas menos saídas no período."),
        ("A receber em aberto", em_aberto("receita"), VERDE, "currencyBRL", ABERTO_DESCRICAO),
        ("A pagar em aberto", em_aberto("despesa"), LARANJA, "currencyBRL", ABERTO_DESCRICAO),
    ]
    for i, (titulo, sql, cor, unidade, descricao) in enumerate(cartoes):
        p.add((i % 4) * 6, (i // 4) * 3, 6, 3, numero(titulo, sql, cor, unidade, descricao))
    p.add(0, 6, 12, 9, colunas_mensais("Faturamento mensal por empresa", FAT_MENSAL, empilhar=True))
    p.add(12, 6, 12, 9, barras("Entradas x saídas de caixa", ENTRADAS_SAIDAS, "Mês", VERDE, False,
                                cores=CORES_CAIXA))
    p.add(0, 15, 24, 5, tabela("Resumo por empresa", f"""
        WITH f AS (SELECT empresa, SUM(total) fat FROM vw_faturamento
                     WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1),
             d AS (SELECT empresa, SUM(valor) FILTER (WHERE natureza = 'receita') rec,
                          -SUM(valor) FILTER (WHERE natureza = 'despesa') desp, SUM(valor) res
                     FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia) GROUP BY 1),
             a AS (SELECT empresa, SUM(valor_em_aberto) FILTER (WHERE natureza = 'receita') arec,
                          SUM(valor_em_aberto) FILTER (WHERE natureza = 'despesa') apag
                     FROM vw_contas_em_aberto WHERE {EMPRESA} GROUP BY 1),
             e AS (SELECT empresa FROM f UNION SELECT empresa FROM d UNION SELECT empresa FROM a)
        SELECT e.empresa AS "Empresa", f.fat AS "Faturamento", d.rec AS "Receita", d.desp AS "Despesas",
               d.res AS "Resultado", a.arec AS "A receber em aberto", a.apag AS "A pagar em aberto"
          FROM e LEFT JOIN f USING (empresa) LEFT JOIN d USING (empresa) LEFT JOIN a USING (empresa)
         ORDER BY 1"""))
    p.add(0, 20, 24, 9, barras("Maiores gastos por categoria", f"""
        SELECT categoria AS "Categoria", -SUM(valor) AS "Despesas" FROM vw_dre
         WHERE natureza = 'despesa' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", "Categoria", VERMELHO))
    return p


def dre() -> Painel:
    p = Painel("fin-dre", "2. DRE", "Receitas e despesas pela data de competência.")
    for i, (titulo, sql, cor, unidade) in enumerate([
        ("Receita", RECEITA, VERDE, "currencyBRL"),
        ("Despesas", DESPESAS, VERMELHO, "currencyBRL"),
        ("Resultado", RESULTADO, AZUL, "currencyBRL"),
        ("Margem", MARGEM, AZUL, "percentunit"),
    ]):
        p.add(i * 6, 0, 6, 4, numero(titulo, sql, cor, unidade))
    p.add(0, 4, 14, 9, barras("Receita x despesas por mês", f"""
        SELECT to_char(date_trunc('month', competencia), 'MM/YY') AS "Mês",
               SUM(valor) FILTER (WHERE natureza = 'receita') AS "Receita",
               -SUM(valor) FILTER (WHERE natureza = 'despesa') AS "Despesas"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY date_trunc('month', competencia) ORDER BY date_trunc('month', competencia)""",
        "Mês", VERDE, False, cores={"Receita": VERDE, "Despesas": VERMELHO}))
    p.add(14, 4, 10, 9, colunas_mensais("Resultado por mês", f"""
        SELECT date_trunc('month', competencia)::timestamp AS time, 'Resultado' AS metric, SUM(valor) AS value
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia) GROUP BY 1, 2 ORDER BY 1""",
        {"Resultado": AZUL}))
    p.add(0, 13, 12, 11, tabela("Resultado por empresa", f"""
        SELECT empresa AS "Empresa",
               SUM(valor) FILTER (WHERE natureza = 'receita') AS "Receita",
               -SUM(valor) FILTER (WHERE natureza = 'despesa') AS "Despesas",
               SUM(valor) AS "Resultado",
               SUM(valor) / NULLIF(SUM(valor) FILTER (WHERE natureza = 'receita'), 0) AS "Margem"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia) GROUP BY 1 ORDER BY 1""",
        percentuais=("Margem",)))
    p.add(12, 13, 12, 11, tabela("DRE por categoria", f"""
        SELECT CASE WHEN natureza = 'receita' THEN 'Receita' ELSE 'Despesa' END AS "Natureza",
               categoria AS "Categoria", SUM(ABS(valor)) AS "Valor"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC"""))
    return p


def fluxo() -> Painel:
    p = Painel("fin-fluxo", "3. Fluxo de Caixa", "Pagamentos e recebimentos efetivados (borderôs do Bling).")
    for i, (titulo, sql, cor) in enumerate([
        ("Entradas", f"SELECT COALESCE(SUM(valor), 0) FROM vw_fluxo_caixa WHERE tipo = 'receber' "
                     f"AND {EMPRESA} AND $__timeFilter(data)", VERDE),
        ("Saídas", f"SELECT COALESCE(-SUM(valor), 0) FROM vw_fluxo_caixa WHERE tipo = 'pagar' AND {EMPRESA} "
                   "AND $__timeFilter(data)", VERMELHO),
        ("Saldo do período", SALDO_CAIXA, AZUL),
    ]):
        p.add(i * 8, 0, 8, 4, numero(titulo, sql, cor))
    p.add(0, 4, 24, 8, linha("Saldo acumulado no período", f"""
        SELECT data::timestamp AS time, SUM(SUM(valor)) OVER (ORDER BY data) AS "Saldo"
          FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY data ORDER BY 1""", AZUL))
    p.add(0, 12, 12, 9, barras("Entradas x saídas por mês", ENTRADAS_SAIDAS, "Mês", VERDE, False,
                                cores=CORES_CAIXA))
    p.add(12, 12, 12, 9, tabela("Por conta financeira", f"""
        SELECT COALESCE(conta_financeira, 'Sem conta') AS "Conta",
               SUM(valor) FILTER (WHERE tipo = 'receber') AS "Entradas",
               -SUM(valor) FILTER (WHERE tipo = 'pagar') AS "Saídas",
               SUM(valor) AS "Saldo"
          FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1 ORDER BY 4 DESC"""))
    p.add(0, 21, 24, 10, tabela("Por categoria", f"""
        SELECT COALESCE(categoria, 'Sem categoria') AS "Categoria",
               SUM(valor) FILTER (WHERE tipo = 'receber') AS "Entradas",
               -SUM(valor) FILTER (WHERE tipo = 'pagar') AS "Saídas",
               SUM(valor) AS "Saldo"
          FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1 ORDER BY 4"""))
    return p


def faturamento() -> Painel:
    p = Painel("fin-faturamento", "4. Faturamento", "Pedidos de venda do Bling pela data do pedido.")
    p.add(0, 0, 8, 4, numero("Faturamento", FATURAMENTO, AZUL))
    p.add(8, 0, 8, 4, numero("Pedidos", f"SELECT COUNT(*) FROM vw_faturamento WHERE {EMPRESA} "
                                        "AND $__timeFilter(data)", AZUL, "none"))
    p.add(16, 0, 8, 4, numero("Ticket médio", f"SELECT AVG(total) FROM vw_faturamento WHERE {EMPRESA} "
                                              "AND $__timeFilter(data)", AZUL))
    p.add(0, 4, 14, 9, colunas_mensais("Faturamento mensal por empresa", FAT_MENSAL, empilhar=True))
    p.add(14, 4, 10, 9, tabela("Por empresa", f"""
        SELECT empresa AS "Empresa", COUNT(*) AS "Pedidos", SUM(total) AS "Faturamento",
               AVG(total) AS "Ticket médio"
          FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1 ORDER BY 1""",
        contagens=("Pedidos",)))
    p.add(0, 13, 12, 11, barras("Maiores clientes", f"""
        SELECT COALESCE(contato_nome, 'Sem nome') AS "Cliente", SUM(total) AS "Faturamento"
          FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", "Cliente", AZUL))
    p.add(12, 13, 12, 11, colunas_mensais("Pedidos por mês", f"""
        SELECT date_trunc('month', data)::timestamp AS time, empresa AS metric, COUNT(*) AS value
          FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1, 2 ORDER BY 1""",
        empilhar=True, unidade="none"))
    return p


def contas(uid: str, titulo: str, natureza: str, contato: str, contatos: str, cor: str) -> Painel:
    p = Painel(uid, titulo, ABERTO_DESCRICAO)
    for i, (rotulo, filtro) in enumerate([
        ("Em aberto", ""),
        ("Vencido", "AND vencimento < current_date"),
        ("Vence nos próximos 30 dias", "AND vencimento BETWEEN current_date AND current_date + 30"),
    ]):
        p.add(i * 6, 0, 6, 4, numero(rotulo, em_aberto(natureza, filtro), cor, descricao=ABERTO_DESCRICAO))
    quantidade = f"SELECT COUNT(*) FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA}"
    p.add(18, 0, 6, 4, numero("Contas em aberto", quantidade, cor, "none"))
    p.add(0, 4, 12, 10, barras("Em aberto por mês de vencimento", f"""
        SELECT to_char(date_trunc('month', vencimento), 'MM/YY') AS "Mês", SUM(valor_em_aberto) AS "Em aberto"
          FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA} AND vencimento IS NOT NULL
         GROUP BY date_trunc('month', vencimento) ORDER BY date_trunc('month', vencimento)""",
        "Mês", cor, horizontal=False))
    p.add(12, 4, 12, 10, barras(f"Maiores {contatos}", f"""
        SELECT COALESCE(contato_nome, 'Sem nome') AS "{contato}", SUM(valor_em_aberto) AS "Em aberto"
          FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA}
         GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", contato, cor))
    p.add(0, 14, 24, 12, tabela("Próximos vencimentos e vencidos", f"""
        SELECT to_char(vencimento, 'DD/MM/YYYY') AS "Vencimento", empresa AS "Empresa",
               contato_nome AS "{contato}", categoria AS "Categoria", valor_em_aberto AS "Em aberto"
          FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA}
         ORDER BY vencimento NULLS LAST LIMIT 500"""))
    return p


def gastos_receitas() -> Painel:
    p = Painel("fin-gastos-receitas", "7. Gastos e Receitas",
               "Categorias de receita e despesa por competência.")
    p.add(0, 0, 12, 12, barras("Gastos por categoria", f"""
        SELECT categoria AS "Categoria", -SUM(valor) AS "Despesas" FROM vw_dre
         WHERE natureza = 'despesa' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", "Categoria", VERMELHO))
    p.add(12, 0, 12, 12, barras("Receitas por categoria", f"""
        SELECT categoria AS "Categoria", SUM(valor) AS "Receita" FROM vw_dre
         WHERE natureza = 'receita' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", "Categoria", VERDE))
    p.add(0, 12, 24, 12, tabela("Categorias por empresa", f"""
        SELECT categoria AS "Categoria",
               CASE WHEN natureza = 'receita' THEN 'Receita' ELSE 'Despesa' END AS "Natureza",
               empresa AS "Empresa", SUM(ABS(valor)) AS "Valor",
               SUM(ABS(valor))
                 / NULLIF(SUM(SUM(ABS(valor))) OVER (PARTITION BY natureza, empresa), 0) AS "% da empresa"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1, 2, 3, natureza ORDER BY 2 DESC, 4 DESC""", percentuais=("% da empresa",)))
    return p


PAINEIS = {
    "1-visao-geral": visao_geral,
    "2-dre": dre,
    "3-fluxo-de-caixa": fluxo,
    "4-faturamento": faturamento,
    "5-contas-a-pagar": lambda: contas("fin-pagar", "5. Contas a Pagar", "despesa",
                                       "Fornecedor", "fornecedores", LARANJA),
    "6-contas-a-receber": lambda: contas("fin-receber", "6. Contas a Receber", "receita",
                                         "Cliente", "clientes", VERDE),
    "7-gastos-e-receitas": gastos_receitas,
}


def main() -> None:
    DESTINO.mkdir(exist_ok=True)
    for arquivo in DESTINO.glob("*.json"):
        arquivo.unlink()
    for nome, criar in PAINEIS.items():
        conteudo = json.dumps(criar().json(), ensure_ascii=False, indent=2)
        (DESTINO / f"{nome}.json").write_text(conteudo + "\n", encoding="utf-8")
    print(f"{len(PAINEIS)} painéis gravados em {DESTINO}")


if __name__ == "__main__":
    main()
