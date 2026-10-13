#!/usr/bin/env bash
# Backup do SQLite operacional e do Postgres financeiro.
# Uso: bash deploy/backup.sh /caminho/do/destino
set -euo pipefail

DESTINO="${1:?Informe a pasta de destino, ex.: bash deploy/backup.sh /var/backups/bling}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PASTA="$DESTINO/$STAMP"
mkdir -p "$PASTA"

# Ajuste se as pastas no servidor forem outras.
APP_JH="${APP_JH:-/opt/bling-trello-sync}"
APP_JHS="${APP_JHS:-/opt/bling-trello-sync-jhs}"

for app in "$APP_JH" "$APP_JHS"; do
  if [ -f "$app/bling_trello_sync.db" ]; then
    nome="$(basename "$app")"
    sqlite3 "$app/bling_trello_sync.db" ".backup '$PASTA/${nome}.sqlite'"
  fi
done

if command -v pg_dump >/dev/null 2>&1; then
  # Usa o usuário local ou PGPASSWORD; ajuste conforme o servidor.
  pg_dump -Fc -d "${FINANCEIRO_DB:-financeiro}" -f "$PASTA/financeiro.dump"
fi

echo "Backup em $PASTA"
