# bling-trello-sync

Programa de linha de comando que lê os **pedidos de venda do Bling** (API v3) e cria/atualiza um **card no Trello** para cada pedido. A sincronização acontece **quando você roda o programa** — não há servidor nem webhook.

Cada execução:

1. busca os pedidos alterados desde a última execução (ou no período que você informar);
2. cria um card para o pedido que ainda não tem card, na lista correspondente à situação;
3. atualiza título, descrição e vencimento do card já existente e o move de lista se a situação mudou (deixando um comentário no card);
4. guarda o momento da execução para que a próxima continue de onde parou.

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
2. Escopo: **Pedidos de Venda**. O módulo **Situações** nem sempre está disponível na lista de escopos; sem ele o card mostra o id da situação, a menos que você preencha `NOMES_SITUACOES`.
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
```

Preencha `TRELLO_LIST_ID_POR_SITUACAO` no `.env` com o JSON `"id da situação": "id da lista"`. Qualquer situação fora do mapa cai em `TRELLO_LIST_ID_PADRAO`.

Se `situacoes-bling` responder 403 (o app não tem o escopo de Situações), os ids aparecem no log da sincronização e nos cards; use `NOMES_SITUACOES` no `.env` para dar nome a eles: `{"9":"Em aberto","12":"Atendido"}`.

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

## Testes

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```
