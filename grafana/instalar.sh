#!/usr/bin/env bash
# Instala ou atualiza o Grafana com os painéis financeiros. Pode ser rodado de novo sem problema.
# Uso (como root, dentro da pasta do repositório): bash grafana/instalar.sh refelist-bi.duckdns.org
set -euo pipefail

DOMINIO="${1:?Informe o domínio, por exemplo: bash grafana/instalar.sh refelist-bi.duckdns.org}"
PASTA_REPO="$(cd "$(dirname "$0")/.." && pwd)"
SENHA_BANCO_ARQ=/root/senha-powerbi.txt
SENHA_GRAFANA_ARQ=/root/senha-grafana.txt
ENV_FINANCEIRO=/etc/grafana/financeiro.env
PAINEIS=/var/lib/grafana/dashboards/financeiro
# prefer = tenta TLS e cai para plain em localhost; override com GRAFANA_PG_SSLMODE=require|disable
SSLMODE="${GRAFANA_PG_SSLMODE:-prefer}"

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

echo ">> Segredos em EnvironmentFile (não embute senha no YAML versionado)"
install -d -o root -g grafana -m 750 /etc/grafana
if [ ! -f "$ENV_FINANCEIRO" ]; then
    if [ -f "$SENHA_BANCO_ARQ" ]; then
        SENHA_BANCO="$(head -n 1 "$SENHA_BANCO_ARQ" | tr -d '\r\n')"
    else
        echo "Crie $ENV_FINANCEIRO com GF_FINANCEIRO_PG_PASSWORD=... ou $SENHA_BANCO_ARQ"
        exit 1
    fi
    umask 027
    cat > "$ENV_FINANCEIRO" <<ENV
# Gerado por grafana/instalar.sh — chmod 640, grupo grafana
GF_FINANCEIRO_PG_PASSWORD=$SENHA_BANCO
GRAFANA_PG_SSLMODE=$SSLMODE
ENV
    chown root:grafana "$ENV_FINANCEIRO"
    chmod 640 "$ENV_FINANCEIRO"
    echo "   criado $ENV_FINANCEIRO a partir de $SENHA_BANCO_ARQ"
else
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FINANCEIRO"
    set +a
    SSLMODE="${GRAFANA_PG_SSLMODE:-$SSLMODE}"
    [ -n "${GF_FINANCEIRO_PG_PASSWORD:-}" ] || {
        echo "$ENV_FINANCEIRO sem GF_FINANCEIRO_PG_PASSWORD"
        exit 1
    }
fi

echo ">> Configurando a conexão com o banco e os painéis"
install -d -o root -g grafana -m 750 \
    /etc/grafana/provisioning/datasources \
    /etc/grafana/provisioning/dashboards \
    /etc/grafana/provisioning/alerting
install -m 640 -o root -g grafana /dev/null /etc/grafana/provisioning/datasources/financeiro.yaml
# Senha via expansão de env do processo grafana-server (EnvironmentFile).
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
      sslmode: $SSLMODE
      postgresVersion: 1400
      maxOpenConns: 5
    secureJsonData:
      password: \$GF_FINANCEIRO_PG_PASSWORD
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
if [ -f "$PASTA_REPO/grafana/alertas/financeiro.yaml" ]; then
    install -m 640 -o root -g grafana \
        "$PASTA_REPO/grafana/alertas/financeiro.yaml" \
        /etc/grafana/provisioning/alerting/financeiro.yaml
fi

mkdir -p /etc/systemd/system/grafana-server.service.d
cat > /etc/systemd/system/grafana-server.service.d/financeiro.conf <<CONF
[Service]
EnvironmentFile=-$ENV_FINANCEIRO
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

if ! command -v caddy >/dev/null 2>&1; then
    echo ">> Instalando o Caddy (HTTPS)"
    apt-get install -y -q debian-keyring debian-archive-keyring curl >/dev/null
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q >/dev/null
    apt-get install -y -q caddy >/dev/null
fi
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
fi

if ! grep -q "^$DOMINIO" /etc/caddy/Caddyfile; then
    echo ">> Publicando https://$DOMINIO pelo Caddy"
    cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.antes-grafana
    printf '\n%s {\n\treverse_proxy 127.0.0.1:3000\n}\n' "$DOMINIO" >> /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
    systemctl reload caddy
fi

echo "PRONTO: abra https://$DOMINIO e entre com o usuário admin (senha em $SENHA_GRAFANA_ARQ)"
