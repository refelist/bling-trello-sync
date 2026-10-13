"""Gera os painéis do Grafana (grafana/paineis/*.json) a partir das visões do PostgreSQL.

Rode `python grafana/gerar_paineis.py` depois de mudar este arquivo e faça commit dos JSON.
"""

from __future__ import annotations

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
TZ = "America/Sao_Paulo"


def consulta(sql: str, formato: str = "table", ref: str = "A") -> list[dict]:
    return [{
        "refId": ref,
        "datasource": FONTE,
        "editorMode": "code",
        "rawQuery": True,
        "format": formato,
        "rawSql": " ".join(sql.split()),
    }]


class Painel:
    def __init__(
        self,
        uid: str,
        titulo: str,
        descricao: str,
        *,
        refresh: str = "",
    ) -> None:
        self.uid = uid
        self.titulo = titulo
        self.descricao = descricao
        self.refresh = refresh
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
            "timezone": TZ,
            "editable": False,
            "graphTooltip": 1,
            "schemaVersion": 41,
            "version": 1,
            "refresh": self.refresh,
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


def numero(
    titulo: str,
    sql: str,
    cor: str,
    unidade: str = "currencyBRL",
    descricao: str = "",
    *,
    limiares: list[dict] | None = None,
) -> dict:
    defaults: dict = {
        "unit": unidade,
        "decimals": 0 if unidade == "none" else (1 if unidade == "percentunit" else 2),
        "color": {"mode": "fixed", "fixedColor": cor},
        "noValue": "0",
    }
    if limiares:
        defaults["thresholds"] = {"mode": "absolute", "steps": limiares}
        defaults["color"] = {"mode": "thresholds"}
    return {
        "type": "stat",
        "title": titulo,
        "description": descricao,
        "targets": consulta(sql),
        "fieldConfig": {"defaults": defaults, "overrides": []},
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


def numero_delta(
    titulo: str,
    sql_atual: str,
    sql_anterior: str,
    cor: str,
    unidade: str = "currencyBRL",
    descricao: str = "",
) -> dict:
    """Stat do valor atual + % vs o período imediatamente anterior (mesma duração)."""
    sql = f"""
        WITH atual AS ({sql_atual}),
             anterior AS ({sql_anterior})
        SELECT (SELECT * FROM atual) AS "Valor",
               CASE WHEN (SELECT * FROM anterior) = 0 THEN NULL
                    ELSE ((SELECT * FROM atual) - (SELECT * FROM anterior))
                         / ABS((SELECT * FROM anterior))
               END AS "vs período anterior"
    """
    return {
        "type": "stat",
        "title": titulo,
        "description": descricao + " Compara com o período imediatamente anterior de mesma duração.",
        "targets": consulta(sql),
        "fieldConfig": {
            "defaults": {
                "unit": unidade,
                "decimals": 0 if unidade == "none" else (1 if unidade == "percentunit" else 2),
                "color": {"mode": "fixed", "fixedColor": cor},
                "noValue": "0",
            },
            "overrides": [{
                "matcher": {"id": "byName", "options": "vs período anterior"},
                "properties": [
                    {"id": "unit", "value": "percentunit"},
                    {"id": "decimals", "value": 1},
                    {"id": "custom.displayMode", "value": "color-background"},
                    {"id": "thresholds", "value": {
                        "mode": "absolute",
                        "steps": [
                            {"color": VERMELHO, "value": None},
                            {"color": VERDE, "value": 0},
                        ],
                    }},
                    {"id": "color", "value": {"mode": "thresholds"}},
                ],
            }],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^Valor$/", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value_and_name",
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


def colunas_mensais(
    titulo: str,
    sql: str,
    cores: dict[str, str] | None = None,
    empilhar: bool = False,
    unidade: str = "currencyBRL",
) -> dict:
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


def barras(
    titulo: str,
    sql: str,
    eixo: str,
    cor: str,
    horizontal: bool = True,
    descricao: str = "",
    cores: dict[str, str] | None = None,
) -> dict:
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


def tabela(
    titulo: str,
    sql: str,
    contagens: tuple[str, ...] = (),
    percentuais: tuple[str, ...] = (),
    descricao: str = "",
) -> dict:
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


def _janela(coluna: str, deslocar: bool = False) -> str:
    """Filtro de período Grafana; com deslocar=True usa a janela imediatamente anterior.

    Usa `$__from`/`$__to` (ms) — estáveis no datasource Postgres do Grafana.
    """
    t0 = "to_timestamp($__from / 1000.0)"
    t1 = "to_timestamp($__to / 1000.0)"
    if not deslocar:
        return f"{coluna} >= {t0} AND {coluna} < {t1}"
    return f"{coluna} >= {t0} - ({t1} - {t0}) AND {coluna} < {t0}"


def _soma(expr: str, de: str, onde: str, coluna_tempo: str, anterior: bool = False) -> str:
    return (
        f"SELECT COALESCE({expr}, 0) FROM {de} "
        f"WHERE {onde} AND {_janela(coluna_tempo, deslocar=anterior)}"
    )


FATURAMENTO = _soma("SUM(total)", "vw_faturamento", EMPRESA, "data")
FATURAMENTO_ANT = _soma("SUM(total)", "vw_faturamento", EMPRESA, "data", anterior=True)
RECEITA = _soma("SUM(valor)", "vw_dre", f"natureza = 'receita' AND {EMPRESA}", "competencia")
RECEITA_ANT = _soma("SUM(valor)", "vw_dre", f"natureza = 'receita' AND {EMPRESA}", "competencia", True)
DESPESAS = _soma("-SUM(valor)", "vw_dre", f"natureza = 'despesa' AND {EMPRESA}", "competencia")
RESULTADO = _soma("SUM(valor)", "vw_dre", EMPRESA, "competencia")
RESULTADO_ANT = _soma("SUM(valor)", "vw_dre", EMPRESA, "competencia", True)
MARGEM = (
    f"SELECT SUM(valor) / NULLIF(SUM(valor) FILTER (WHERE natureza = 'receita'), 0) "
    f"FROM vw_dre WHERE {EMPRESA} AND {_janela('competencia')}"
)
SALDO_CAIXA = _soma("SUM(valor)", "vw_fluxo_caixa", EMPRESA, "data")
SALDO_CAIXA_ANT = _soma("SUM(valor)", "vw_fluxo_caixa", EMPRESA, "data", True)


def em_aberto(natureza: str, filtro: str = "") -> str:
    return (
        f"SELECT COALESCE(SUM(valor_em_aberto), 0) FROM vw_contas_em_aberto "
        f"WHERE natureza = '{natureza}' AND {EMPRESA} {filtro}"
    )


ABERTO_DESCRICAO = "Tudo o que está em aberto hoje, independente do período escolhido."
FAT_MENSAL = (
    f"SELECT date_trunc('month', data)::timestamp AS time, empresa AS metric, SUM(total) AS value "
    f"FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data) GROUP BY 1, 2 ORDER BY 1"
)
ENTRADAS_SAIDAS = f"""
    SELECT to_char(date_trunc('month', data), 'MM/YY') AS "Mês",
           SUM(valor) FILTER (WHERE tipo = 'receber') AS "Entradas",
           -SUM(valor) FILTER (WHERE tipo = 'pagar') AS "Saídas"
      FROM vw_fluxo_caixa WHERE {EMPRESA} AND $__timeFilter(data)
     GROUP BY date_trunc('month', data) ORDER BY date_trunc('month', data)"""
CORES_CAIXA = {"Entradas": VERDE, "Saídas": VERMELHO}

SEMANTICA = (
    "Semântica: Faturamento = pedidos (exclui cancelados). "
    "Resultado/DRE = competência dos títulos. "
    "Caixa = borderôs líquidos. Δ = vs período anterior de mesma duração."
)

HORAS_COLETA = f"""
    SELECT COALESCE(
             EXTRACT(EPOCH FROM (NOW() - MAX(coletado_em::timestamptz))) / 3600.0,
             999
           )
      FROM vw_coleta_meta WHERE {EMPRESA}
"""


def visao_geral() -> Painel:
    p = Painel(
        "fin-visao-geral",
        "1. Visão Geral",
        "Resumo executivo do período. " + SEMANTICA,
        refresh="15m",
    )
    # Hero: 6 cartões (não 8) — receita/despesa ficam no DRE.
    herois = [
        ("Faturamento", FATURAMENTO, FATURAMENTO_ANT, AZUL, "currencyBRL",
         "Pedidos de venda no período (exclui cancelados)."),
        ("Resultado", RESULTADO, RESULTADO_ANT, AZUL, "currencyBRL",
         "Receita − despesas (competência)."),
        ("Margem", MARGEM, MARGEM, AZUL, "percentunit",
         "Resultado / receita (competência). Sem Δ (razão)."),
        ("Saldo do caixa", SALDO_CAIXA, SALDO_CAIXA_ANT, ROXO, "currencyBRL",
         "Entradas − saídas (borderôs, valor líquido)."),
        ("A receber em aberto", em_aberto("receita"), em_aberto("receita"), VERDE, "currencyBRL",
         ABERTO_DESCRICAO + " Sem Δ (saldo de hoje)."),
        ("A pagar em aberto", em_aberto("despesa"), em_aberto("despesa"), LARANJA, "currencyBRL",
         ABERTO_DESCRICAO + " Sem Δ (saldo de hoje)."),
    ]
    for i, (titulo, atual, anterior, cor, unidade, desc) in enumerate(herois):
        # Margem e em aberto: número simples (Δ não faz sentido ou é o mesmo SQL).
        if titulo in {"Margem", "A receber em aberto", "A pagar em aberto"}:
            painel = numero(titulo, atual, cor, unidade, desc)
        else:
            painel = numero_delta(titulo, atual, anterior, cor, unidade, desc)
        p.add((i % 6) * 4, (i // 6) * 4, 4, 4, painel)

    p.add(0, 4, 8, 3, numero(
        "Horas desde a última coleta",
        HORAS_COLETA,
        VERDE,
        "none",
        "Alerta visual: amarelo ≥ 3h, vermelho ≥ 6h sem sincronização Bling→Postgres.",
        limiares=[
            {"color": VERDE, "value": None},
            {"color": LARANJA, "value": 3},
            {"color": VERMELHO, "value": 6},
        ],
    ))
    p.add(8, 4, 16, 3, tabela(
        "Última coleta financeira",
        f"""SELECT empresa AS "Empresa", coletado_em AS "Coletado em",
                   CASE WHEN ok = 1 THEN 'ok' ELSE 'com erros' END AS "Status",
                   erros AS "Erros", resumo AS "Resumo"
              FROM vw_coleta_meta WHERE {EMPRESA} ORDER BY 1""",
        contagens=("Erros",),
        descricao="Momento da última sincronização por empresa.",
    ))

    p.add(0, 7, 12, 9, colunas_mensais("Faturamento mensal por empresa", FAT_MENSAL, empilhar=True))
    p.add(12, 7, 12, 9, barras(
        "Entradas x saídas de caixa", ENTRADAS_SAIDAS, "Mês", VERDE, False, cores=CORES_CAIXA,
    ))
    p.add(0, 16, 24, 5, tabela("Resumo por empresa", f"""
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
    p.add(0, 21, 24, 9, barras("Maiores gastos por grupo de categoria", f"""
        SELECT categoria_grupo AS "Grupo", -SUM(valor) AS "Despesas" FROM vw_dre
         WHERE natureza = 'despesa' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", "Grupo", VERMELHO,
        descricao="Agrega pela categoria pai quando existir; senão usa a própria categoria."))
    return p


def dre() -> Painel:
    p = Painel(
        "fin-dre",
        "2. DRE",
        "Receitas e despesas pela data de competência dos títulos (não é fluxo de caixa).",
    )
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
    p.add(12, 13, 12, 11, tabela("DRE por grupo e categoria", f"""
        SELECT CASE WHEN natureza = 'receita' THEN 'Receita' ELSE 'Despesa' END AS "Natureza",
               categoria_grupo AS "Grupo",
               categoria AS "Categoria",
               SUM(ABS(valor)) AS "Valor"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1, 2, 3 ORDER BY 1 DESC, 4 DESC"""))
    return p


def fluxo() -> Painel:
    p = Painel(
        "fin-fluxo",
        "3. Fluxo de Caixa",
        "Pagamentos e recebimentos efetivados (borderôs). "
        "Valor líquido = valor pago + juros + acréscimo − desconto − tarifa.",
    )
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
    p = Painel(
        "fin-faturamento",
        "4. Faturamento",
        "Pedidos de venda do Bling pela data do pedido (exclui situação cancelado, id 12).",
    )
    p.add(0, 0, 8, 4, numero_delta(
        "Faturamento", FATURAMENTO, FATURAMENTO_ANT, AZUL,
        descricao="Pedidos no período.",
    ))
    p.add(8, 0, 8, 4, numero(
        "Pedidos",
        f"SELECT COUNT(*) FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data)",
        AZUL, "none",
    ))
    p.add(16, 0, 8, 4, numero(
        "Ticket médio",
        f"SELECT AVG(total) FROM vw_faturamento WHERE {EMPRESA} AND $__timeFilter(data)",
        AZUL,
    ))
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
        SELECT CASE WHEN mes < date_trunc('month', current_date) THEN 'Atrasadas'
                    WHEN mes > date_trunc('month', current_date) + interval '11 months' THEN 'Depois'
                    ELSE to_char(mes, 'MM/YY') END AS "Mês",
               SUM(valor_em_aberto) AS "Em aberto"
          FROM (SELECT date_trunc('month', vencimento) AS mes, valor_em_aberto FROM vw_contas_em_aberto
                 WHERE natureza = '{natureza}' AND {EMPRESA} AND vencimento IS NOT NULL) v
         GROUP BY 1 ORDER BY MIN(mes)""",
        "Mês", cor, horizontal=False,
        descricao="Meses já passados aparecem juntos em Atrasadas; depois de 12 meses, em Depois."))
    p.add(12, 4, 12, 10, barras(f"Maiores {contatos}", f"""
        SELECT COALESCE(contato_nome, 'Sem nome') AS "{contato}", SUM(valor_em_aberto) AS "Em aberto"
          FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA}
         GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", contato, cor))
    p.add(0, 14, 24, 12, tabela("Próximos vencimentos e vencidos", f"""
        SELECT to_char(vencimento, 'DD/MM/YYYY') AS "Vencimento", empresa AS "Empresa",
               contato_nome AS "{contato}", categoria AS "Categoria", valor_em_aberto AS "Em aberto"
          FROM vw_contas_em_aberto WHERE natureza = '{natureza}' AND {EMPRESA}
         ORDER BY vencimento NULLS LAST LIMIT 200"""))
    return p


def gastos_receitas() -> Painel:
    p = Painel(
        "fin-gastos-receitas",
        "7. Gastos e Receitas",
        "Categorias de receita e despesa por competência, com grupo (categoria pai).",
    )
    p.add(0, 0, 12, 12, barras("Gastos por grupo", f"""
        SELECT categoria_grupo AS "Grupo", -SUM(valor) AS "Despesas" FROM vw_dre
         WHERE natureza = 'despesa' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", "Grupo", VERMELHO))
    p.add(12, 0, 12, 12, barras("Receitas por grupo", f"""
        SELECT categoria_grupo AS "Grupo", SUM(valor) AS "Receita" FROM vw_dre
         WHERE natureza = 'receita' AND {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", "Grupo", VERDE))
    p.add(0, 12, 24, 12, tabela("Grupo e categoria por empresa", f"""
        SELECT categoria_grupo AS "Grupo",
               categoria AS "Categoria",
               CASE WHEN natureza = 'receita' THEN 'Receita' ELSE 'Despesa' END AS "Natureza",
               empresa AS "Empresa", SUM(ABS(valor)) AS "Valor",
               SUM(ABS(valor))
                 / NULLIF(SUM(SUM(ABS(valor))) OVER (PARTITION BY natureza, empresa), 0) AS "% da empresa"
          FROM vw_dre WHERE {EMPRESA} AND $__timeFilter(competencia)
         GROUP BY 1, 2, 3, 4, natureza ORDER BY 3 DESC, 5 DESC""", percentuais=("% da empresa",)))
    return p


PAINEIS = {
    "1-visao-geral": visao_geral,
    "2-dre": dre,
    "3-fluxo-de-caixa": fluxo,
    "4-faturamento": faturamento,
    "5-contas-a-pagar": lambda: contas(
        "fin-pagar", "5. Contas a Pagar", "despesa", "Fornecedor", "fornecedores", LARANJA,
    ),
    "6-contas-a-receber": lambda: contas(
        "fin-receber", "6. Contas a Receber", "receita", "Cliente", "clientes", VERDE,
    ),
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
