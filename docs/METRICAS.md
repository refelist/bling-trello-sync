# Contrato de métricas financeiras

Fonte única de semântica para **Grafana** e **Power BI**. As visões curtas (`vw_dre`, …) são aliases da versão pinada (`vw_dre_v1`, …). Pinagem estável: `CONTRATO_METRICAS_VERSAO` em `bling_trello_sync/armazem.py`.

| Visão estável | Alias atual | Eixo de tempo | Semântica |
|---|---|---|---|
| `vw_dre_v1` | `vw_dre` | `competencia` | Competência dos títulos; receita positiva, despesa negativa; exclui `situacao = 5`; expõe `categoria_grupo` (pai). |
| `vw_fluxo_caixa_v1` | `vw_fluxo_caixa` | `data` (liquidação) | Caixa realizado via borderôs: `valor_pago + juros + acréscimo − desconto − tarifa` (saídas negativas). |
| `vw_faturamento_v1` | `vw_faturamento` | `data` (pedido) | Pedidos de venda; exclui `situacao_id = 12` (cancelado JH/JHS). |
| `vw_contas_em_aberto_v1` | `vw_contas_em_aberto` | `vencimento` | Saldo em aberto hoje (`situacao` 1/3/7 e saldo &gt; 0); independente do filtro de período dos painéis. |
| `vw_lancamento_v1` | `vw_lancamento` | emissão / competência / vencimento | União P/R; base do DRE e do em aberto. |
| `vw_coleta_meta_v1` | `vw_coleta_meta` | `coletado_em` | Última coleta por empresa (`ok`, `erros`, `bling_429`). |

**Não misturar eixos** ao comparar números: faturamento ≠ receita DRE ≠ entradas de caixa. O painel de conciliação na Visão Geral mostra os três no mesmo intervalo de calendário e os gaps.

## Changelog

### v1 (ESQUEMA_VERSAO 6)

- Congela a semântica pós-P0/P1: DRE com grupo de categoria; fluxo com juros/desconto/acréscimo/tarifa; faturamento sem cancelados; meta de coleta com contador 429.
- Introduz aliases `*_v1` + nomes curtos. Grafana e Power BI continuam nos nomes curtos; para pinagem explícita use `*_v1`.

Próxima quebra de semântica → criar `*_v2`, apontar os aliases curtos para v2 e acrescentar entrada neste changelog.
