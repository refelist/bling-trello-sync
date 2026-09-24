# bling-trello-sync

Integração que escuta o webhook de **Pedido de Venda** do Bling (API v3) e cria/atualiza um **card no Trello** para cada pedido, em tempo real.

- `order.created` → cria o card na lista correspondente à situação do pedido
- `order.updated` → atualiza título/descrição/vencimento e move o card se a situação mudou (com um comentário registrando a mudança)
- `order.deleted` → arquiva o card

Cada pedido tem no máximo um card: o vínculo `pedido → card` fica em SQLite, junto com os `eventId` já processados (o Bling pode reenviar o mesmo evento).

## Como rodar

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # preencha as credenciais
uvicorn bling_trello_sync.main:app --host 0.0.0.0 --port 8000
```

O serviço precisa estar publicado em uma URL HTTPS pública para o Bling entregar os webhooks (em desenvolvimento, use `ngrok http 8000`).

## Configuração

### 1. Aplicativo no Bling

1. No Bling: **Central de Extensões → Área do Integrador → Criar aplicativo**.
2. Escopo obrigatório: **Pedidos de Venda** (sem ele o recurso de webhook `order` nem aparece). Inclua também **Situações** se quiser o nome da situação no card.
3. Link de redirecionamento: `https://SEU_DOMINIO/oauth/bling/callback`.
4. Anote o **Client Id** e o **Client Secret** → `BLING_CLIENT_ID` / `BLING_CLIENT_SECRET`.
5. Aba **Webhooks**: cadastre o servidor `https://SEU_DOMINIO/webhooks/bling` e marque o recurso **Pedido de Venda** com as ações `created`, `updated` e `deleted`.

### 2. Credenciais do Trello

- API key: https://trello.com/power-ups/admin (crie um Power-Up e use a chave gerada) → `TRELLO_API_KEY`
- Token: gere o token a partir da própria chave e autorize na sua conta → `TRELLO_TOKEN`
- `TRELLO_BOARD_ID`: abra o board e acesse `https://trello.com/b/XXXX.json`, campo `id`.

### 3. Listas e mapeamento de situações

Com o `.env` preenchido:

```bash
python -m bling_trello_sync.cli listas-trello      # IDs das listas do board
python -m bling_trello_sync.cli modulos-bling      # módulos de situação do Bling
python -m bling_trello_sync.cli situacoes-bling <id_do_modulo_de_vendas>
```

Monte o mapa em `TRELLO_LIST_ID_POR_SITUACAO` (JSON `"id da situação": "id da lista"`); qualquer situação fora do mapa cai em `TRELLO_LIST_ID_PADRAO`.

### 4. Autorizar o Bling

Acesse `https://SEU_DOMINIO/oauth/bling/autorizar` no navegador e autorize. O `access_token` e o `refresh_token` ficam salvos no SQLite e são renovados automaticamente. Só depois dessa autorização o Bling começa a enviar eventos.

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `POST` | `/webhooks/bling` | Recebe os eventos (valida `X-Bling-Signature-256` e responde `202` em seguida, processando em background para respeitar o limite de 5s do Bling) |
| `GET` | `/oauth/bling/autorizar` | Inicia o OAuth2 |
| `GET` | `/oauth/bling/callback` | Recebe o `code` e grava os tokens |
| `GET` | `/trello/listas` | Lista as listas do board (para montar o mapeamento) |
| `POST` | `/sincronizar/{pedido_id}` | Sincroniza um pedido manualmente (reprocesso/teste) |
| `GET` | `/healthz` | Health check |

## Importar pedidos já existentes

```bash
python -m bling_trello_sync.cli backfill --data-inicial 2026-01-01 --data-final 2026-01-31
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```
