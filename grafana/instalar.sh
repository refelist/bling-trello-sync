#!/usr/bin/env bash
# Instala ou atualiza o Grafana com os painéis financeiros. Pode ser rodado de novo sem problema.
# Uso (como root, dentro da pasta do repositório): bash grafana/instalar.sh refelist-bi.duckdns.org
set -euo pipefail

DOMINIO="${1:?Informe o domínio, por exemplo: bash grafana/instalar.sh refelist-bi.duckdns.org}"
PASTA_REPO="$(cd "$(dirname "$0")/.." && pwd)"
SENHA_BANCO_ARQ=/root/senha-powerbi.txt
SENHA_GRAFANA_ARQ=/root/senha-grafana.txt
PAINEIS=/var/lib/grafana/dashboards/financeiro

[ -f "$SENHA_BANCO_ARQ" ] || { echo "Não achei $SENHA_BANCO_ARQ (senha do usuário powerbi)"; exit 1; }

if ! dpkg -s grafana >/dev/null 2>&1; then
    echo ">> Instalando o Grafana"
    apt-get install -y -q apt-transport-https wget gnupg >/dev/null
    mkdir -p /etc/apt/keyrings
    wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/grafana.gpg
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
    apt-get update -q >/dev/null
    apt-get install -y -q grafana >/dev/null
fi

echo ">> Configurando a conexão com o banco e os painéis"
SENHA_BANCO="$(head -n 1 "$SENHA_BANCO_ARQ" | tr -d '\r\n')"
ASPA="'"
SENHA_YAML="${SENHA_BANCO//$ASPA/$ASPA$ASPA}"
install -d -o root -g grafana -m 750 /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards
install -m 640 -o root -g grafana /dev/null /etc/grafana/provisioning/datasources/financeiro.yaml
cat > /etc/grafana/provisioning/datasources/financeiro.yaml <<YAML
apiVersion: 1
datasources:
  - name: Financeiro
    uid: financeiro
    type: grafana-postgresql-datasource
    url: localhost:5432
    user: powerbi
    isDefault: true
    editable: false
    jsonData:
      database: financeiro
      sslmode: disable
      postgresVersion: 1400
      maxOpenConns: 5
    secureJsonData:
      password: '$SENHA_YAML'
YAML
cat > /etc/grafana/provisioning/dashboards/financeiro.yaml <<YAML
apiVersion: 1
providers:
  - name: Financeiro
    folder: Financeiro
    type: file
    disableDeletion: true
    allowUiUpdates: false
    options:
      path: $PAINEIS
YAML
chmod 640 /etc/grafana/provisioning/dashboards/financeiro.yaml
chgrp grafana /etc/grafana/provisioning/dashboards/financeiro.yaml
install -d -o grafana -g grafana "$PAINEIS"
rm -f "$PAINEIS"/*.json
install -m 644 -o grafana -g grafana "$PASTA_REPO"/grafana/paineis/*.json "$PAINEIS"/

mkdir -p /etc/systemd/system/grafana-server.service.d
cat > /etc/systemd/system/grafana-server.service.d/financeiro.conf <<CONF
[Service]
Environment=GF_SERVER_HTTP_ADDR=127.0.0.1
Environment=GF_SERVER_DOMAIN=$DOMINIO
Environment=GF_SERVER_ROOT_URL=https://$DOMINIO/
Environment=GF_SECURITY_COOKIE_SECURE=true
Environment=GF_USERS_ALLOW_SIGN_UP=false
Environment=GF_USERS_DEFAULT_LANGUAGE=pt-BR
Environment=GF_AUTH_ANONYMOUS_ENABLED=false
Environment=GF_ANALYTICS_REPORTING_ENABLED=false
Environment=GF_ANALYTICS_CHECK_FOR_UPDATES=false
Environment=GF_NEWS_NEWS_FEED_ENABLED=false
Environment=GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=$PAINEIS/1-visao-geral.json
CONF

echo ">> Iniciando o Grafana"
systemctl daemon-reload
systemctl enable grafana-server >/dev/null 2>&1
systemctl restart grafana-server
for _ in $(seq 60); do
    curl -sf http://127.0.0.1:3000/api/health >/dev/null && break
    sleep 2
done
curl -sf http://127.0.0.1:3000/api/health >/dev/null || { echo "O Grafana não respondeu; veja: journalctl -u grafana-server -n 50"; exit 1; }

if [ ! -s "$SENHA_GRAFANA_ARQ" ]; then
    echo ">> Criando a senha do administrador (usuário admin)"
    (umask 077; openssl rand -base64 24 | tr -d '/+=\n' | cut -c1-20 > "$SENHA_GRAFANA_ARQ")
    runuser -u grafana -- grafana cli --homepath /usr/share/grafana --config /etc/grafana/grafana.ini \
        admin reset-admin-password "$(cat "$SENHA_GRAFANA_ARQ")" >/dev/null
fi

if ! grep -q "^$DOMINIO" /etc/caddy/Caddyfile; then
    echo ">> Publicando https://$DOMINIO pelo Caddy"
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.antes-grafana
    printf '\n%s {\n\treverse_proxy 127.0.0.1:3000\n}\n' "$DOMINIO" >> /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
    systemctl reload caddy
fi

echo "PRONTO: abra https://$DOMINIO e entre com o usuário admin (senha em $SENHA_GRAFANA_ARQ)"
