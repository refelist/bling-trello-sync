#!/usr/bin/env bash
# Check-up do servidor: apps Bling→Trello, Grafana, banco, recursos. Não mostra senhas nem tokens.
# Uso: bash deploy/checkup.sh [dominio-do-grafana]
DOMINIO="${1:-jh-bi.duckdns.org}"
APPS="${APPS:-bling-trello:/root/bling-trello-sync bling-trello-2:/root/bling-trello-sync-2}"
FINANCEIROS="${FINANCEIROS:-bling-financeiro:/root/bling-financeiro bling-financeiro-jhs:/root/bling-financeiro-jhs}"
SENHA_GRAFANA_ARQ="${SENHA_GRAFANA_ARQ:-/root/senha-grafana.txt}"

ALERTAS=0
ok() { printf '  [OK]      %s\n' "$*"; }
atencao() { printf '  [ATENÇÃO] %s\n' "$*"; ALERTAS=$((ALERTAS + 1)); }
codigo() { curl -s -o /dev/null -m 15 -w '%{http_code}' "$@"; }
versao() {
  local pasta="$1" servico="$2" ramo atras
  git -C "$pasta" fetch -q 2>/dev/null || return 0
  ramo="$(git -C "$pasta" branch --show-current)"
  atras="$(git -C "$pasta" rev-list --count HEAD..origin/main 2>/dev/null)"
  if [ "$ramo" != main ]; then
    atencao "código no ramo '$ramo' em vez de main"
  elif [ "${atras:-0}" -gt 0 ]; then
    atencao "código $atras atualização(ões) atrás do GitHub (rode: cd $pasta && git pull && systemctl restart $servico)"
  else
    ok "código atualizado (main)"
  fi
}

echo "== Serviços"
for s in bling-trello bling-trello-2 grafana-server caddy postgresql; do
  estado="$(systemctl is-active "$s" 2>/dev/null)"
  [ "$estado" = active ] && ok "$s ligado" || atencao "$s está '$estado' (veja: journalctl -u $s -n 50)"
done

echo "== Recursos"
mem_livre="$(free -m | awk '/^Mem:/ {print $7}')"
swap_uso="$(free -m | awk '/^Swap:/ {print $3 "/" $2}')"
[ "${mem_livre:-0}" -ge 150 ] && ok "memória disponível ${mem_livre} MB (swap em uso: ${swap_uso} MB)" \
  || atencao "pouca memória: ${mem_livre} MB disponíveis (swap em uso: ${swap_uso} MB)"
swapon --show --noheadings | grep -q . || atencao "swap desligado"
disco="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
[ "${disco:-100}" -lt 85 ] && ok "disco ${disco}% usado" || atencao "disco ${disco}% usado"
oom="$(journalctl -k --since '24 hours ago' --no-pager 2>/dev/null | grep -ciE 'out of memory|killed process')"
[ "${oom:-0}" -eq 0 ] && ok "nenhum programa derrubado por falta de memória em 24h" \
  || atencao "$oom programa(s) derrubado(s) por falta de memória em 24h"
[ -f /var/run/reboot-required ] && atencao "o sistema pede reinício (rode 'reboot' num horário tranquilo)"

for par in $APPS; do
  servico="${par%%:*}"
  pasta="${par#*:}"
  echo "== App $servico ($pasta)"
  pid="$(systemctl show -p MainPID --value "$servico" 2>/dev/null)"
  porta="$(ss -ltnpH 2>/dev/null | grep "pid=${pid}," | awk '{print $4}' | sed 's/.*://' | head -1)"
  if [ -z "$porta" ] || [ "$pid" = 0 ]; then
    atencao "não achei a porta do app (ele está ligado?)"
    continue
  fi
  base="http://127.0.0.1:$porta"
  [ "$(codigo "$base/healthz")" = 200 ] && ok "responde (porta $porta)" || atencao "/healthz não respondeu 200"
  [ "$(codigo "$base/readyz")" = 200 ] && ok "pronto (token do Bling presente)" \
    || atencao "/readyz falhou: autorização do Bling ausente ou banco local indisponível"
  token="$(grep -m1 '^API_TOKEN=' "$pasta/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r\n')"
  if [ "${#token}" -lt 32 ]; then
    atencao "API_TOKEN ausente ou curto no .env"
  else
    [ "$(codigo "$base/trello/listas")" = 401 ] && ok "recusa acesso sem token" || atencao "rota protegida não recusou acesso sem token"
    [ "$(codigo -H "X-API-Key: $token" "$base/trello/listas")" = 200 ] && ok "aceita o token e alcança o Trello" \
      || atencao "rota protegida falhou com token (token errado ou Trello fora do ar)"
    vazou="$(journalctl -u "$servico" --since '7 days ago' --no-pager 2>/dev/null | grep -cF "$token")"
    [ "${vazou:-0}" -eq 0 ] && ok "token não aparece nos logs" || atencao "token aparece $vazou vez(es) nos logs: gere outro"
  fi
  unset token
  perms="$(stat -c %a "$pasta/.env" 2>/dev/null)"
  [ "$perms" = 600 ] && ok ".env protegido (600)" || atencao ".env com permissão $perms (rode: chmod 600 $pasta/.env)"
  erros="$(journalctl -u "$servico" --since '6 hours ago' --no-pager 2>/dev/null | grep -ciE 'traceback|exception|level=error| ERROR ')"
  [ "${erros:-0}" -eq 0 ] && ok "nenhum erro nos logs das últimas 6h" \
    || atencao "$erros linha(s) de erro nas últimas 6h (veja: journalctl -u $servico --since '6 hours ago' | grep -iE 'error|exception')"
  if grep -qiE '^COMPRAS_ATIVO=(true|1|sim)' "$pasta/.env" 2>/dev/null; then
    ultima="$(journalctl -u "$servico" --since '3 hours ago' --no-pager 2>/dev/null | grep 'Compras:' | tail -1 | grep -o 'Compras:.*' | cut -c1-110)"
    [ -n "$ultima" ] && ok "última rodada de compras: $ultima" || atencao "nenhuma rodada de compras registrada nas últimas 3h"
  fi
  versao "$pasta" "$servico"
done

for par in $FINANCEIROS; do
  servico="${par%%:*}"
  pasta="${par#*:}"
  [ -f "/etc/systemd/system/$servico.timer" ] || continue
  echo "== Coleta financeira $servico ($pasta)"
  [ "$(systemctl is-active "$servico.timer")" = active ] && ok "agenda ligada (próxima: $(systemctl show -p NextElapseUSecRealtime --value "$servico.timer"))" \
    || atencao "agenda desligada (rode: systemctl enable --now $servico.timer)"
  resultado="$(systemctl show -p Result --value "$servico.service")"
  [ "$resultado" = success ] && ok "última execução terminou bem" \
    || atencao "última execução falhou: $resultado (veja: journalctl -u $servico -n 50)"
  perms="$(stat -c %a "$pasta/.env" 2>/dev/null)"
  [ "$perms" = 600 ] && ok ".env protegido (600)" || atencao ".env com permissão $perms (rode: chmod 600 $pasta/.env)"
  erros="$(journalctl -u "$servico" --since '6 hours ago' --no-pager 2>/dev/null | grep -ciE 'traceback|exception|level=error| ERROR |erro em')"
  [ "${erros:-0}" -eq 0 ] && ok "nenhum erro nos logs das últimas 6h" \
    || atencao "$erros linha(s) de erro nas últimas 6h (veja: journalctl -u $servico --since '6 hours ago' | grep -iE 'error|erro em')"
  for app in $APPS; do
    if grep -qiE '^FINANCEIRO_ATIVO=(true|1|sim|yes)' "${app#*:}/.env" 2>/dev/null \
      && [ "$(grep -m1 '^FINANCEIRO_EMPRESA=' "${app#*:}/.env")" = "$(grep -m1 '^FINANCEIRO_EMPRESA=' "$pasta/.env")" ]; then
      atencao "${app%%:*} também coleta o financeiro desta empresa (deixe FINANCEIRO_ATIVO=false no .env dele)"
    fi
  done
  versao "$pasta" "$servico.timer"
done

echo "== Grafana"
[ "$(codigo http://127.0.0.1:3000/api/health)" = 200 ] && ok "Grafana responde no servidor" || atencao "Grafana não responde em 127.0.0.1:3000"
if [ -r "$SENHA_GRAFANA_ARQ" ]; then
  saude="$(curl -s -m 30 -u "admin:$(head -n1 "$SENHA_GRAFANA_ARQ" | tr -d '\r\n')" \
    http://127.0.0.1:3000/api/datasources/uid/financeiro/health)"
  echo "$saude" | grep -q '"status":"OK"' && ok "Grafana lê o banco financeiro" \
    || atencao "Grafana não lê o banco: $(echo "$saude" | cut -c1-150)"
else
  atencao "não achei $SENHA_GRAFANA_ARQ para testar a conexão do Grafana com o banco"
fi
[ "$(codigo "https://$DOMINIO/api/health")" = 200 ] && ok "https://$DOMINIO abre pela internet" \
  || atencao "https://$DOMINIO não abriu pela internet (Caddy, DNS ou certificado)"
validade="$(echo | timeout 15 openssl s_client -servername "$DOMINIO" -connect "$DOMINIO:443" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
if [ -n "$validade" ]; then
  dias=$(( ( $(date -d "$validade" +%s) - $(date +%s) ) / 86400 ))
  [ "$dias" -ge 14 ] && ok "certificado HTTPS válido por mais $dias dias" || atencao "certificado HTTPS vence em $dias dias"
fi

echo "== Banco financeiro"
coletas="$(cd /tmp && sudo -u postgres psql -d financeiro -tA -F '|' -c \
  "SELECT empresa, round(extract(epoch FROM localtimestamp - coletado_em::timestamp) / 3600, 1), ok, erros FROM coleta_meta ORDER BY empresa" 2>&1)"
if [ -z "$coletas" ] || echo "$coletas" | grep -qiE 'error|erro|could not'; then
  atencao "não consegui ler a última coleta: $(echo "$coletas" | head -1 | cut -c1-150)"
else
  while IFS='|' read -r empresa horas sucesso nerros; do
    if [ "$sucesso" = t ] && awk "BEGIN {exit !($horas < 3)}"; then
      ok "$empresa: última coleta há ${horas}h, $nerros erro(s) de item"
    else
      atencao "$empresa: última coleta há ${horas}h, ok=$sucesso, $nerros erro(s) de item"
    fi
  done <<< "$coletas"
fi
tamanho="$(cd /tmp && sudo -u postgres psql -d financeiro -tAc "SELECT pg_size_pretty(pg_database_size('financeiro'))" 2>/dev/null)"
[ -n "$tamanho" ] && ok "tamanho do banco: $tamanho"

echo
if [ "$ALERTAS" -eq 0 ]; then
  echo "RESULTADO: tudo certo."
else
  echo "RESULTADO: $ALERTAS ponto(s) de atenção acima."
fi
