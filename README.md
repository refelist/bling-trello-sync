# bling-trello-sync

Integração que lê os **pedidos de venda do Bling** (API v3) e cria/atualiza um **card no Trello** para cada pedido. Funciona de dois jeitos, com a mesma lógica de sincronização:

- **linha de comando**: sincroniza quando você roda o comando (ou por cron);
- **modo servidor** (`bling_trello_sync.main`): recebe o webhook do Bling e sincroniza o pedido no momento em que ele muda.

Cada sincronização:

1. busca os pedidos alterados desde a última execução (ou no período que você informar);
2. cria um card para o pedido que ainda não tem card, na lista correspondente à situação;
3. cria no card um checklist "Itens do pedido", com um item por produto, marcando automaticamente os produtos já faturados nas notas fiscais do pedido (os itens marcados à mão são preservados nas execuções seguintes);
4. comenta no card o número e a data de emissão de cada nota fiscal do pedido (uma vez por nota);
5. atualiza título, descrição e vencimento do card já existente e o move de lista se a situação mudou (deixando um comentário no card);
6. guarda o momento da execução para que a próxima continue de onde parou.

O vínculo `pedido → card` fica em um banco SQLite local, então um pedido nunca vira dois cards.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # preencha as credenciais
```

## Configuração

### 1. Aplicativo no Bling

1. No Bling: **Central de Extensões → Área do Integrador → Criar aplicativo**.
2. Escopos: **Pedidos de Venda** e **Notas Fiscais** (esse último é o que permite marcar no checklist os produtos já faturados; sem ele o checklist funciona, mas nada é marcado automaticamente). O módulo **Situações** nem sempre está disponível na lista de escopos; sem ele o card mostra o id da situação, a menos que você preencha `NOMES_SITUACOES`.
3. Link de redirecionamento: `http://localhost:8000/callback` (o mesmo valor de `BLING_REDIRECT_URI`).
4. Copie o **Client Id** e o **Client Secret** para o `.env`.

### 2. Credenciais do Trello

- API key: https://trello.com/power-ups/admin (crie um Power-Up e use a chave gerada) → `TRELLO_API_KEY`
- Token: gere a partir dessa chave e autorize na sua conta → `TRELLO_TOKEN`
- `TRELLO_BOARD_ID`: abra o board e acesse `https://trello.com/b/XXXX.json`, campo `id`

### 3. Autorizar o Bling (uma única vez)

```bash
python -m bling_trello_sync.cli autorizar
```

O comando mostra uma URL; abra no navegador, autorize e pronto — os tokens ficam salvos e são renovados sozinhos nas execuções seguintes.

### 4. Mapear situações para listas

```bash
python -m bling_trello_sync.cli listas-trello                    # IDs das listas do board
python -m bling_trello_sync.cli modulos-bling                    # módulos de situação do Bling
python -m bling_trello_sync.cli situacoes-bling <id_do_modulo>   # situações do módulo de vendas
python -m bling_trello_sync.cli situacoes-pedidos               # ids de situação vistos nos pedidos
```

Preencha `TRELLO_LIST_ID_POR_SITUACAO` no `.env`. A chave pode ser o id **ou** o nome da situação; o valor, o id **ou** o nome da lista (acentos e maiúsculas não importam):

```json
{"6":"PEDIDO EM ABERTO","21":"PEDIDO EM ABERTO","9":"EM TRANSITO","12":"CANCELADOS"}
```

Qualquer situação fora do mapa cai em `TRELLO_LIST_ID_PADRAO`.

Se `situacoes-bling` responder 403 (o app não tem o escopo de Situações), use `situacoes-pedidos` para ver os ids junto de números de pedido de exemplo e confira no Bling a qual situação cada um corresponde; `NOMES_SITUACOES` no `.env` dá nome a eles nos cards: `{"9":"Em aberto","12":"Atendido"}`.

### 5. Filtrar por loja (opcional)

Pedidos vindos de marketplaces chegam com a loja da integração. Para deixá-los de fora:

```bash
python -m bling_trello_sync.cli lojas-bling            # ids de loja dos pedidos dos últimos 30 dias
```

No `.env`, `LOJAS_IGNORADAS=123,456` pula essas lojas; `LOJAS_PERMITIDAS=789` sincroniza apenas as listadas (e tem prioridade sobre a outra).

## Uso

```bash
# o caso normal: pedidos alterados desde a última execução
python -m bling_trello_sync.cli sincronizar

# últimos 7 dias, ignorando a última execução
python -m bling_trello_sync.cli sincronizar --dias 7

# período específico de alteração
python -m bling_trello_sync.cli sincronizar --desde "2026-01-01 00:00:00" --ate "2026-01-31 23:59:59"

# por data de emissão do pedido (carga inicial)
python -m bling_trello_sync.cli sincronizar --data-inicial 2026-01-01 --data-final 2026-01-31

# somente algumas situações
python -m bling_trello_sync.cli sincronizar --situacoes 6,9

# um pedido específico
python -m bling_trello_sync.cli sincronizar-pedido 12345678
```

Saída de exemplo:

```
23 pedidos processados | 5 cards criados | 18 atualizados | 0 erros
```

Na primeira execução sem filtro, a janela considerada é a dos últimos 30 dias. Se algum pedido falhar, o erro é listado e o marcador da última execução **não** avança, para que a próxima rodada tente de novo.

### Rodar automaticamente (opcional)

Se um dia quiser periodicidade sem lembrar de executar, basta agendar o mesmo comando, por exemplo de hora em hora no cron:

```
0 * * * * cd /caminho/do/projeto && .venv/bin/python -m bling_trello_sync.cli sincronizar >> sync.log 2>&1
```

## Modo servidor (webhook, tempo real)

O serviço FastAPI em `bling_trello_sync/main.py` expõe:

| Rota | Uso |
|---|---|
| `POST /webhooks/bling` | endereço a cadastrar no webhook do Bling |
| `GET /healthz` | verificação de saúde |
| `GET /oauth/bling/autorizar` e `GET /oauth/bling/callback` | autorização do Bling pelo navegador |
| `GET /trello/listas` | listas do board, para montar o mapa de situações |
| `POST /sincronizar/{pedido_id}` | sincroniza um pedido de venda sob demanda |
| `POST /sincronizar-compra/{pedido_id}` | sincroniza um pedido de compra sob demanda |

Rodar:

```bash
pip install -r requirements.txt
uvicorn bling_trello_sync.main:app --host 0.0.0.0 --port 8000
```

O endereço precisa ser público e em **HTTPS** para o Bling entregar os eventos. No `.env`, `BLING_REDIRECT_URI` passa a ser `https://seu-dominio/oauth/bling/callback` (o mesmo valor deve estar cadastrado no aplicativo do Bling).

Cada evento é validado pelo cabeçalho `X-Bling-Signature-256` (HMAC-SHA256 do corpo com o client secret); `VERIFICAR_ASSINATURA_WEBHOOK=false` desliga a checagem apenas para testes locais. O `eventId` é guardado no banco, então um evento reenviado não é processado duas vezes, e a sincronização roda em segundo plano para responder ao Bling dentro do tempo limite.

## Pedidos de compra

Os pedidos de compra vão para um **quadro separado** do Trello. O Bling não oferece webhook de pedido de compra, então esta parte funciona por consulta periódica: com `COMPRAS_ATIVO=true`, o serviço varre os pedidos de compra dos últimos `COMPRAS_DIAS` a cada `COMPRAS_INTERVALO_MINUTOS` minutos.

Cada card traz fornecedor, número, datas, total, categoria, frete por conta, itens e um checklist com um item por produto — marcado quando a quantidade já vinculada a uma nota fiscal de entrada cobre a quantidade comprada. A lista do card segue a situação do pedido (`0` Em aberto, `3` Em andamento, `1` Atendido, `2` Cancelado), configurada em `TRELLO_LIST_ID_POR_SITUACAO_COMPRA`. As observações e as observações internas do pedido viram comentários separados no card, publicados de novo só quando o texto muda.

Comandos:

```bash
python -m bling_trello_sync.cli listas-trello-compras
python -m bling_trello_sync.cli sincronizar-compras --dias 30
python -m bling_trello_sync.cli sincronizar-compra 12345678
```

## Financeiro (Power BI)

Parte independente do Trello: coleta o financeiro do Bling e grava em um banco que o Power BI lê. Com `FINANCEIRO_ATIVO=true` o próprio serviço atualiza o banco a cada `FINANCEIRO_INTERVALO_MINUTOS`; também dá para rodar sob demanda:

```bash
python -m bling_trello_sync.cli sincronizar-financeiro --dias 365
python -m bling_trello_sync.cli sincronizar-financeiro --data-inicial 2025-01-01 --data-final 2026-12-31
```

`FINANCEIRO_DATABASE_URL` aceita um PostgreSQL (`postgresql://usuario:senha@host:5432/banco`, recomendado, pois vários desktops leem o mesmo banco) ou o caminho de um arquivo SQLite. Cada cópia do programa grava com o nome em `FINANCEIRO_EMPRESA`, e as duas contas do Bling podem apontar para o mesmo banco: a coluna `empresa` permite ver uma, outra ou as duas somadas.

O que é coletado: contas a receber e a pagar (emitidas, vencendo ou liquidadas no período), os borderos de cada conta liquidada (pagamento efetivo, com juros, desconto, acréscimo e tarifa), pedidos de venda e as dimensões categoria, conta financeira, forma de pagamento e contato. Para poupar requisições, o detalhe de uma conta só é relido quando situação, valor ou vencimento mudam (`--recarregar-tudo` ignora essa checagem).

Tabelas: `conta_receber`, `conta_pagar`, `movimento_caixa`, `pedido_venda`, `categoria`, `conta_financeira`, `forma_pagamento`, `contato`. Visões prontas para os relatórios: `vw_lancamento`, `vw_dre` (competência), `vw_fluxo_caixa` (caixa realizado), `vw_contas_em_aberto` e `vw_faturamento`.

O aplicativo do Bling de cada conta precisa dos escopos de **Finanças** (contas a pagar, contas a receber, categorias de receitas e despesas, contas financeiras e formas de pagamento); sem eles a API responde 403.

### Relatório Power BI

O relatório fica em `powerbi/` no formato de projeto do Power BI (PBIP: modelo em TMDL e páginas em PBIR, arquivos de texto versionáveis). Páginas: Visão Geral, DRE, Fluxo de Caixa, Faturamento, Contas a Pagar, Contas a Receber e Gastos e Receitas. Todas têm o filtro **Empresa** (uma, outra ou as duas) e **Ano**, sincronizados entre as páginas.

Para abrir em um desktop:

1. Instale o Power BI Desktop (Microsoft Store) e, em *Arquivo > Opções > Recursos de visualização*, ative **Formato de relatório avançado (PBIR)** e **Armazenar modelo semântico usando o formato TMDL**; reinicie.
2. Abra um túnel SSH até o servidor e deixe a janela aberta: `ssh -N -L 5432:localhost:5432 root@<ip-do-servidor>`.
3. Abra `powerbi/Financeiro Bling.pbip`. Os parâmetros `Servidor` (`localhost:5432`) e `Banco` (`financeiro`) já apontam para o túnel; em *Transformar dados > Configurações da fonte de dados* informe o usuário `powerbi` e a senha dele (tipo **Banco de dados**). Clique em **Atualizar**.
4. Para ter um único arquivo, use *Arquivo > Salvar como* e escolha **.pbix**. Cada desktop pode abrir o mesmo `.pbix` (por exemplo numa pasta do OneDrive) e atualizar os dados pelo túnel.

O DRE soma pela data de competência e o fluxo de caixa pela data em que o valor foi efetivamente pago ou recebido.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```
