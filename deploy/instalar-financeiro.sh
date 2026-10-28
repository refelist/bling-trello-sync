#!/usr/bin/env bash
# Instala a coleta financeira (Bling → Postgres → Grafana) separada dos apps do Trello,
# com app Bling, token, pasta e agenda próprios. Pode rodar de novo: só faz o que falta.
# Uso: bash deploy/instalar-financeiro.sh jh|jhs
set -euo pipefail
case "${1:-}" in
  jh)  ORIGEM=/root/bling-trello-sync;   APP=bling-trello;   UNIDADE=bling-financeiro ;;
  jhs) ORIGEM=/root/bling-trello-sync-2; APP=bling-trello-2; UNIDADE=bling-financeiro-jhs ;;
  *) echo "Uso: bash deploy/instalar-financeiro.sh jh|jhs"; exit 1 ;;
esac
DESTINO="/root/$UNIDADE"
ENV="$DESTINO/.env"
passo() { printf '\n== %s\n' "$*"; }
valor() { grep -m1 "^$1=" "$2" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true; }
tem_token() {
  (cd "$DESTINO" && .venv/bin/python -c "import sys
from bling_trello_sync.config import get_settings
from bling_trello_sync.storage import Storage
sys.exit(0 if Storage(get_settings().database_path).obter_token() else 1)")
}

BASE="$(valor BLING_REDIRECT_URI "$ORIGEM/.env" | tr -d '"' | sed 's#/oauth/bling/callback.*##')"
[ -n "$BASE" ] || { echo "Não achei BLING_REDIRECT_URI em $ORIGEM/.env"; exit 1; }
REDIRECT="$BASE/financeiro/autorizado"
# O retorno do Bling cai no app $APP (página 404) e fica no log de acesso dele; pega de lá
# para não depender de alguém copiar e colar (o code do Bling vence em ~1 minuto).
capturar_retorno() {
  timeout 1800 journalctl -u "$APP" -f -n0 -o cat \
    | grep -m1 -o '/financeiro/autorizado?[^ "]*' | sed 's#^#https://retorno#' || true
}

passo "Código em $DESTINO"
if [ ! -d "$DESTINO/.git" ]; then
  git clone -q "$ORIGEM" "$DESTINO"
  git -C "$DESTINO" remote set-url origin "$(git -C "$ORIGEM" remote get-url origin)"
fi
git -C "$DESTINO" fetch -q origin
git -C "$DESTINO" checkout -q main
git -C "$DESTINO" pull -q --ff-only
[ -x "$DESTINO/.venv/bin/python" ] || python3 -m venv "$DESTINO/.venv"
"$DESTINO/.venv/bin/pip" install -q -r "$DESTINO/requirements.txt"
git -C "$DESTINO" log -1 --format='versão %h'

passo "Configuração ($ENV)"
if [ ! -s "$ENV" ]; then
  echo "Link de redirecionamento do app financeiro no Bling: $REDIRECT"
  read -rp "Client Id do app financeiro: " cid
  read -rsp "Client Secret (não aparece ao digitar): " csec; echo
  if [ -z "$cid" ] || [ -z "$csec" ]; then echo "Client Id e Client Secret são obrigatórios."; exit 1; fi
  (
    umask 077
    {
      echo "BLING_CLIENT_ID=$cid"
      echo "BLING_CLIENT_SECRET=$csec"
      echo "BLING_REDIRECT_URI=$REDIRECT"
      echo "DATABASE_PATH=$DESTINO/financeiro.db"
      for k in FINANCEIRO_EMPRESA FINANCEIRO_DATABASE_URL FINANCEIRO_DIAS FINANCEIRO_DIAS_FUTUROS \
        FINANCEIRO_FILTROS_EMISSAO_DIAS FINANCEIRO_FILTROS_SECUNDARIOS_DIAS FINANCEIRO_DIAS_PEDIDOS \
        FINANCEIRO_FILTROS_COMPLETOS BLING_INTERVALO_MINIMO_MS; do
        v="$(valor "$k" "$ORIGEM/.env")"
        if [ -n "$v" ]; then echo "$k=$v"; fi
      done
    } > "$ENV"
  )
  unset csec
fi
chmod 600 "$ENV"
grep -q '^FINANCEIRO_DATABASE_URL=' "$ENV" || { echo "Falta FINANCEIRO_DATABASE_URL em $ENV"; exit 1; }
echo "ok ($(valor FINANCEIRO_EMPRESA "$ENV"))"

passo "Autorização no Bling"
if tem_token; then
  echo "já autorizado"
else
  echo "Abra o link abaixo, logado no Bling da empresa certa, confira tudo com ✓ verde e autorize."
  echo "Pode mandar o link para outra pessoa (vale este link, não os antigos). Depois de autorizar aparece"
  echo "uma página 'Not Found': é normal, o servidor pega o retorno sozinho. Deixe esta janela aberta (até 30 min)."
  (cd "$DESTINO" && .venv/bin/python -m bling_trello_sync.cli autorizar < <(capturar_retorno)) || true
  tem_token || { echo "Autorização não concluída. Rode este script de novo."; exit 1; }
fi

passo "Agenda de hora em hora ($UNIDADE.timer)"
install -m 644 "$DESTINO/deploy/$UNIDADE.service" "$DESTINO/deploy/$UNIDADE.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q --now "$UNIDADE.timer"
echo "próxima coleta: $(systemctl show -p NextElapseUSecRealtime --value "$UNIDADE.timer")"

passo "Tirando a coleta financeira do app $APP"
if grep -qiE '^FINANCEIRO_ATIVO=(true|1|sim|yes)' "$ORIGEM/.env"; then
  sed -i -E 's/^FINANCEIRO_ATIVO=.*/FINANCEIRO_ATIVO=false/' "$ORIGEM/.env"
  systemctl restart "$APP"
  echo "desligada no $APP (o Trello continua igual)"
else
  echo "já estava desligada"
fi

passo "Primeira coleta (pode levar alguns minutos)"
if systemctl start "$UNIDADE.service"; then
  journalctl -u "$UNIDADE" -n 40 --no-pager -o cat | grep -E 'Linhas gravadas|erro em' | tail -5 | cut -c1-200
  echo "RESULTADO: coleta financeira separada funcionando."
else
  journalctl -u "$UNIDADE" -n 40 --no-pager -o cat | grep -v "HTTP Request" | tail -8 | cut -c1-200
  echo "RESULTADO: a primeira coleta falhou (veja acima). A agenda tenta de novo de hora em hora."
  exit 1
fi
