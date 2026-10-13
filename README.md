# bling-trello-sync

Integração operacional entre o **Bling** (API v3) e as ferramentas internas da Refelist. O mesmo processo cobre **três frentes** independentes, ativáveis por configuração:

| Frente | Origem | Destino | Disparo |
|---|---|---|---|
| **Vendas** | Pedidos de venda + NFs | Cards no Trello | Webhook do Bling ou CLI |
| **Compras** | Pedidos de compra | Quadro Trello separado | Polling periódico (sem webhook no Bling) |
| **Financeiro** | Contas, borderôs, pedidos | Postgres (Power BI / Grafana) | Polling periódico ou CLI |

Duas contas Bling (**JH Shopping LTDA** e **JHS Shopping LTDA**) rodam como processos separados, cada um com o próprio SQLite operacional e o mesmo Postgres financeiro, separados pela coluna `empresa`.

## Visão geral da arquitetura

```
Bling (API + webhook)
        │
        ├─► vendas  ──► Trello (board de pedidos)
        ├─► compras ──► Trello (board de compras)   [COMPRAS_ATIVO]
        └─► financeiro ──► Postgres ──► Power BI / Grafana   [FINANCEIRO_ATIVO]
```

- **SQLite** (`DATABASE_PATH`): tokens OAuth do Bling, vínculo pedido→card, eventos de webhook e tickets OAuth.
- **Postgres** (`FINANCEIRO_DATABASE_URL`): base analítica compartilhada pelas duas empresas.
- **Servidor FastAPI** (`bling_trello_sync.main`): webhook, OAuth, rotas admin, loops de compras/financeiro.
- **CLI** (`bling_trello_sync.cli`): sincronização sob demanda, autorização local e utilitários.

As variáveis `TRELLO_*` são obrigatórias só para vendas/compras. Uma implantação só financeira pode deixá-las vazias.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.lock                    # pins reprodutíveis (CI/produção)
# ou, para desenvolvimento: pip install -r requirements-dev.txt
cp .env.example .env                                # conta 1 (JH Shopping) — preencha os <segredos>
# Segunda conta Bling (outra empresa no mesmo Postgres):
# cp .env.example.segunda-empresa /caminho/da-copia-2/.env
```

Há dois exemplos versionados: `.env.example` (**JH Shopping LTDA**, host `refelist-bling`) e `.env.example.segunda-empresa` (**JHS Shopping LTDA**, host `refelist-bling2`). As duas compartilham o mesmo Postgres e mudam Client Id Bling, mapas de situação/lojas e `FINANCEIRO_EMPRESA`.

**Não versionar** `.env`, tokens, senhas nem dumps do banco. Segredos ficam só no servidor (ou no gerenciador de segredos da equipe).

## Configuração

### 1. Aplicativo no Bling

1. No Bling: **Central de Extensões → Área do Integrador → Criar aplicativo**.
2. Escopos conforme a frente usada:
   - Vendas: **Pedidos de Venda** e **Notas Fiscais** (NF marca o checklist de itens faturados).
   - Compras: pedidos de compra (e categorias, se for exibir no card).
   - Financeiro: **Finanças** (contas a pagar/receber, categorias, contas financeiras, formas de pagamento).
   - O módulo **Situações** nem sempre aparece na lista de escopos; sem ele, use `NOMES_SITUACOES` no `.env`.
3. Link de redirecionamento:
   - Produção (servidor): `https://seu-dominio/oauth/bling/callback` → `BLING_REDIRECT_URI`.
   - CLI local: o helper `autorizar` usa o fluxo local documentado em `oauth_local`.
4. Copie o **Client Id** e o **Client Secret** para o `.env`.

### 2. Credenciais do Trello (vendas e/ou compras)

- API key: https://trello.com/power-ups/admin → `TRELLO_API_KEY`
- Token autorizado com essa chave → `TRELLO_TOKEN`
- `TRELLO_BOARD_ID`: abra o board e acesse `https://trello.com/b/XXXX.json`, campo `id`
- Compras: `TRELLO_BOARD_ID_COMPRAS` e mapas `TRELLO_LIST_ID_*_COMPRA*`

### 3. Autorizar o Bling (uma vez por instância)

**CLI (desenvolvimento / primeira carga):**

```bash
python -m bling_trello_sync.cli autorizar
```

**Produção (servidor):** emita um ticket one-time e abra a URL no navegador (o `API_TOKEN` não vai na query string):

```bash
curl -s -X POST https://seu-dominio/oauth/bling/ticket \
  -H "Authorization: Bearer $API_TOKEN"
# abra o campo "autorizar" (?ticket=…) no navegador
```

Os tokens ficam no SQLite e são renovados automaticamente.

### 4. Mapear situações → listas (vendas)

```bash
python -m bling_trello_sync.cli listas-trello
python -m bling_trello_sync.cli modulos-bling
python -m bling_trello_sync.cli situacoes-bling <id_do_modulo>
python -m bling_trello_sync.cli situacoes-pedidos
```

Preencha `TRELLO_LIST_ID_POR_SITUACAO`. A chave pode ser o id **ou** o nome da situação; o valor, o id **ou** o nome da lista (acentos e maiúsculas não importam):

```json
{"6":"PEDIDO EM ABERTO","21":"PEDIDO EM ABERTO","9":"EM TRANSITO","12":"CANCELADOS"}
```

Situações fora do mapa usam `TRELLO_LIST_ID_PADRAO`. Se `situacoes-bling` retornar 403, use `situacoes-pedidos` e `NOMES_SITUACOES`.

### 5. Filtrar por loja (opcional)

```bash
python -m bling_trello_sync.cli lojas-bling
```

`LOJAS_IGNORADAS=123,456` exclui; `LOJAS_PERMITIDAS=789` restringe (tem prioridade).

## Uso — vendas (CLI)

Cada sincronização de venda:

1. busca pedidos alterados desde a última execução (ou o período informado);
2. cria o card na lista da situação, com checklist "Itens do pedido" (marca itens já faturados nas NFs; marcações manuais são preservadas);
3. comenta número e data de cada NF uma vez;
4. atualiza título, descrição, vencimento e lista se a situação mudou;
5. grava o ponto da execução no SQLite (um pedido nunca vira dois cards).

```bash
python -m bling_trello_sync.cli sincronizar
python -m bling_trello_sync.cli sincronizar --dias 7
python -m bling_trello_sync.cli sincronizar --desde "2026-01-01 00:00:00" --ate "2026-01-31 23:59:59"
python -m bling_trello_sync.cli sincronizar --data-inicial 2026-01-01 --data-final 2026-01-31
python -m bling_trello_sync.cli sincronizar --situacoes 6,9
python -m bling_trello_sync.cli sincronizar-pedido 12345678
```

Na primeira execução sem filtro, a janela padrão é de 30 dias. Se houver erro, o marcador de última sincronização **não** avança.

## Modo servidor (produção)

O serviço FastAPI em `bling_trello_sync.main` expõe:

| Rota | Uso | Auth |
|---|---|---|
| `POST /webhooks/bling` | webhook de pedidos de venda | assinatura HMAC do Bling |
| `GET /healthz` | liveness | aberta |
| `GET /readyz` | readiness (SQLite + token Bling) | aberta |
| `GET /metrics` | contadores (HTTP 429 e erros do Bling) | aberta |
| `POST /oauth/bling/ticket` | ticket one-time para autorizar no navegador | `API_TOKEN` |
| `GET /oauth/bling/autorizar` | inicia OAuth do Bling | `?ticket=` (uso único, 5 min) |
| `GET /oauth/bling/callback` | retorno OAuth | `state` emitido por `/autorizar` |
| `GET /trello/listas` | listas do board | `API_TOKEN` |
| `POST /sincronizar/{pedido_id}` | sync manual de venda | `API_TOKEN` |
| `POST /sincronizar-compra/{pedido_id}` | sync manual de compra | `API_TOKEN` |

```bash
# ajuste WorkingDirectory/EnvironmentFile em deploy/*.service e depois:
sudo cp deploy/bling-trello-sync.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bling-trello-sync
# segunda conta:
sudo cp deploy/bling-trello-sync-jhs.service /etc/systemd/system/
sudo systemctl enable --now bling-trello-sync-jhs
```

Ou manualmente: `uvicorn bling_trello_sync.main:app --host 127.0.0.1 --port 8000` (HTTPS via reverse proxy/Caddy).

No `.env`, defina `BLING_REDIRECT_URI=https://seu-dominio/oauth/bling/callback` e um `API_TOKEN` longo. Rotas admin aceitam só `Authorization: Bearer …` ou `X-API-Key` — **nunca** na query string.

O webhook valida `X-Bling-Signature-256` (HMAC-SHA256 do corpo com o client secret). `VERIFICAR_ASSINATURA_WEBHOOK=false` só para testes locais. A sync roda em background para responder ao Bling em até ~5s. O `eventId` é reservado atomicamente (`processing`) e só vira `done` após sucesso; falha ou pedido ignorado (filtro de loja) libera o claim para reenvio. Eventos `done` mais antigos que `EVENTOS_RETENCAO_DIAS` (padrão 30) são purgados no boot e nos loops.

## Pedidos de compra

Quadro Trello separado. Sem webhook no Bling: com `COMPRAS_ATIVO=true`, o serviço varre os últimos `COMPRAS_DIAS` a cada `COMPRAS_INTERVALO_MINUTOS`.

O card traz fornecedor, datas, total, categoria, frete por conta, itens e checklist (marcado quando a NF de entrada cobre a quantidade). Situações `0`–`3` mapeiam em `TRELLO_LIST_ID_POR_SITUACAO_COMPRA`. Observações e observações internas viram comentários distintos, republicados só quando o texto muda.

```bash
python -m bling_trello_sync.cli listas-trello-compras
python -m bling_trello_sync.cli sincronizar-compras --dias 30
python -m bling_trello_sync.cli sincronizar-compra 12345678
```

## Financeiro (Power BI / Grafana)

Independente do Trello. Com `FINANCEIRO_ATIVO=true` o serviço atualiza o banco a cada `FINANCEIRO_INTERVALO_MINUTOS`:

```bash
python -m bling_trello_sync.cli sincronizar-financeiro --dias 365
python -m bling_trello_sync.cli sincronizar-financeiro --data-inicial 2025-01-01 --data-final 2026-12-31
```

`FINANCEIRO_DATABASE_URL` aceita Postgres (`postgresql://…`, recomendado) ou SQLite. Cada instância grava com `FINANCEIRO_EMPRESA`; as duas contas Bling podem apontar para o mesmo banco.

Coletado: contas a receber/pagar, borderôs (com juros, desconto, acréscimo, tarifa e sequência de pagamento), pedidos de venda e dimensões (categoria, conta financeira, forma de pagamento, contato). Detalhe de conta só é relido quando situação, valor ou vencimento mudam (`--recarregar-tudo` força).

Tabelas: `conta_receber`, `conta_pagar`, `movimento_caixa`, `pedido_venda`, `categoria`, `conta_financeira`, `forma_pagamento`, `contato`. Visões: `vw_lancamento`, `vw_dre`, `vw_fluxo_caixa`, `vw_contas_em_aberto`, `vw_faturamento`.

### Banco no servidor

```bash
apt install -y postgresql
sudo -u postgres psql -c "CREATE DATABASE financeiro" \
  -c "CREATE USER bling_app PASSWORD 'senha-do-programa'" \
  -c "CREATE USER powerbi PASSWORD 'senha-do-power-bi'"
sudo -u postgres psql -d financeiro \
  -c "GRANT ALL ON SCHEMA public TO bling_app" \
  -c "GRANT USAGE ON SCHEMA public TO powerbi" \
  -c "ALTER DEFAULT PRIVILEGES FOR ROLE bling_app IN SCHEMA public GRANT SELECT ON TABLES TO powerbi"
```

O usuário `powerbi` só lê. O PostgreSQL fica escutando apenas em `localhost`, então o Power BI de outro computador acessa por um túnel SSH (`ssh -L 5432:localhost:5432 root@servidor`) e conecta em `localhost:5432`.

Os testes contra um PostgreSQL de verdade rodam quando a variável está definida:

```bash
FINANCEIRO_TEST_POSTGRES=postgresql://bling_app:senha@localhost:5432/financeiro pytest
```

### Relatório Power BI

Projeto em `powerbi/` (PBIP: TMDL + PBIR). Capa com números principais e slides Visão Geral, DRE, Fluxo de Caixa, Faturamento, Contas a Pagar/Receber e Gastos e Receitas. Filtros **Empresa**, **Ano**, **Mês** e **Dia** sincronizados; botão **Limpar filtros**. No Desktop, Ctrl+clique nos botões.

1. Ative em *Arquivo > Opções > Recursos de visualização*: **PBIR** e **TMDL**; reinicie.
2. Túnel SSH: `ssh -N -L 5432:localhost:5432 root@<ip-do-servidor>`.
3. Abra `powerbi/Financeiro Bling.pbip`. Parâmetros `Servidor` (`localhost:5432`) e `Banco` (`financeiro`); credenciais do usuário `powerbi` em *Transformar dados*.
4. Opcional: *Salvar como* `.pbix` para compartilhar.

DRE usa competência; fluxo de caixa usa a data do pagamento/recebimento efetivo.

### Painéis Grafana

Alternativa no navegador, no próprio servidor, com as mesmas visões:

1. Subdomínio DuckDNS (ex.: `refelist-bi`) apontando para o servidor.
2. `bash grafana/instalar.sh refelist-bi.duckdns.org` — instala Grafana, conecta com `powerbi`, carrega painéis, HTTPS via Caddy; senha admin em `/root/senha-grafana.txt`.
3. Cadastre usuários **Viewer** em *Administração > Usuários*.

Painéis gerados por `grafana/gerar_paineis.py`; após alterar o script, rode-o, faça commit dos JSON em `grafana/paineis/` e rode `instalar.sh` de novo.

## Backup

O SQLite operacional usa `PRAGMA journal_mode=WAL`. O Postgres financeiro alimenta os painéis.

```bash
sudo bash deploy/backup.sh /var/backups/bling
```

O script gera dump SQLite de cada instância e `pg_dump -Fc` do banco `financeiro`. Guarde fora do servidor. Restaurar Postgres: `pg_restore -d financeiro arquivo.dump`. No SQLite, pare o serviço e substitua o `.db` (e `-wal`/`-shm` se existirem).

## Desenvolvimento e CI

```bash
pip install -r requirements-dev.txt
pytest --cov=bling_trello_sync --cov-fail-under=70
ruff check .
```

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda em push/PR com Python **3.10** e **3.12**: `ruff check` + `pytest` com cobertura mínima de 70%. Dependências de runtime vêm de `requirements.lock`.

### Convenções de repositório

- Commits pequenos e descritivos (inglês imperativo no título, corpo explicando o *porquê*).
- Não versionar `.env`, credenciais, `.coverage` nem artefatos locais.
- Preferir PR revisável por frente (segurança, sync, financeiro, BI) em vez de misturar tudo.
- Após deploy: conferir `/healthz`, `/readyz`, um webhook de teste, um card Trello e um painel Grafana/Power BI.
