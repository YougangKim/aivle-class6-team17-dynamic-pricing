#!/usr/bin/env bash

set -Eeuo pipefail

SOURCE_DIR="${1:?usage: deploy.sh SOURCE_DIR RELEASE_ID}"
RELEASE_ID="${2:?usage: deploy.sh SOURCE_DIR RELEASE_ID}"
APP_ROOT="/opt/aivle/web-api"
RELEASE_DIR="${APP_ROOT}/releases/${RELEASE_ID}"
CURRENT_LINK="${APP_ROOT}/current"
NGINX_CONFIG="/etc/nginx/conf.d/aivle.conf"
SERVICE_FILE="/etc/systemd/system/aivle-web-api.service"
PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
BACKUP_DIR="$(mktemp -d /tmp/aivle-api-rollback.XXXXXX)"
HAD_NGINX_CONFIG=false
HAD_SERVICE_FILE=false

if [[ -f "${NGINX_CONFIG}" ]]; then
    cp -a "${NGINX_CONFIG}" "${BACKUP_DIR}/aivle.conf"
    HAD_NGINX_CONFIG=true
fi

if [[ -f "${SERVICE_FILE}" ]]; then
    cp -a "${SERVICE_FILE}" "${BACKUP_DIR}/aivle-web-api.service"
    HAD_SERVICE_FILE=true
fi

rollback() {
    local exit_code=$?
    trap - ERR
    echo "Deployment failed; restoring the previous API and Nginx configuration."

    if [[ -n "${PREVIOUS_RELEASE}" && -d "${PREVIOUS_RELEASE}" ]]; then
        ln -sfn "${PREVIOUS_RELEASE}" "${CURRENT_LINK}"
    else
        rm -f "${CURRENT_LINK}"
    fi

    if [[ "${HAD_SERVICE_FILE}" == "true" ]]; then
        cp -a "${BACKUP_DIR}/aivle-web-api.service" "${SERVICE_FILE}"
    else
        rm -f "${SERVICE_FILE}"
    fi

    if [[ "${HAD_NGINX_CONFIG}" == "true" ]]; then
        cp -a "${BACKUP_DIR}/aivle.conf" "${NGINX_CONFIG}"
    else
        rm -f "${NGINX_CONFIG}"
    fi

    systemctl daemon-reload || true
    if [[ -n "${PREVIOUS_RELEASE}" && "${HAD_SERVICE_FILE}" == "true" ]]; then
        systemctl restart aivle-web-api.service || true
    else
        systemctl stop aivle-web-api.service || true
    fi
    nginx -t && systemctl reload nginx || true
    rm -rf "${RELEASE_DIR}" "${BACKUP_DIR}"
    exit "${exit_code}"
}

trap rollback ERR

install -d -m 755 "${APP_ROOT}/releases"
rm -rf "${RELEASE_DIR}"
install -d -m 755 "${RELEASE_DIR}"
cp -a "${SOURCE_DIR}/." "${RELEASE_DIR}/"

python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${RELEASE_DIR}/.venv/bin/pip" install --requirement "${RELEASE_DIR}/requirements.txt"

cat > "${SERVICE_FILE}" <<'EOF'
[Unit]
Description=AIVLE dashboard RDS API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nginx
Group=nginx
WorkingDirectory=/opt/aivle/web-api/current
Environment=AWS_REGION=ap-northeast-2
Environment=DB_SECRET_ARN=aivle-rds-service-secret
Environment=DB_SSLMODE=require
Environment=RESULT_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/188876037193/aivle-dev-pricing-result-queue
ExecStart=/opt/aivle/web-api/current/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"
chown -R root:root "${RELEASE_DIR}"
find "${RELEASE_DIR}" -type d -exec chmod 755 {} \;
find "${RELEASE_DIR}" -type f -exec chmod 644 {} \;
chmod 755 "${RELEASE_DIR}/.venv/bin/"*

cat > "${NGINX_CONFIG}" <<'EOF'
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location = /health {
        access_log off;
        default_type text/plain;
        return 200 "ok";
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

systemctl daemon-reload
systemctl enable aivle-web-api.service
systemctl restart aivle-web-api.service
nginx -t
systemctl reload nginx

for attempt in $(seq 1 20); do
    if curl --fail --silent --show-error --max-time 5 \
        http://127.0.0.1:8000/health >/dev/null; then
        break
    fi
    if [[ "${attempt}" -eq 20 ]]; then
        systemctl status aivle-web-api.service --no-pager || true
        journalctl -u aivle-web-api.service -n 100 --no-pager || true
        exit 1
    fi
    sleep 2
done

curl --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:8000/ready >/dev/null
curl --fail --silent --show-error --max-time 15 \
    "http://127.0.0.1/api/inventory?store_id=S01" >/dev/null

find "${APP_ROOT}/releases" -mindepth 1 -maxdepth 1 -type d \
    ! -path "${RELEASE_DIR}" -mtime +7 -exec rm -rf {} +

trap - ERR
rm -rf "${BACKUP_DIR}"
echo "WEB API deployment and RDS smoke tests succeeded."
