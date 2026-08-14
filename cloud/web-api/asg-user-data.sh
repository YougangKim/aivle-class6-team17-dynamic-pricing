#!/bin/bash
set -Eeuo pipefail

AWS_REGION="ap-northeast-2"
S3_BUCKET="aivle-web-git-update-s3-1888-7603-7193"

for attempt in $(seq 1 30); do
  work_dir="$(mktemp -d /tmp/aivle-bootstrap.XXXXXX)"

  if aws s3 cp "s3://${S3_BUCKET}/releases/web-api-latest.zip" "${work_dir}/web-api.zip" --region "${AWS_REGION}" \
    && unzip -q "${work_dir}/web-api.zip" -d "${work_dir}/web-api" \
    && bash "${work_dir}/web-api/deploy.sh" "${work_dir}/web-api" "bootstrap-$(date +%s)" \
    && /usr/local/bin/deploy-aivle-web frontend-latest.zip; then
    rm -rf "${work_dir}"
    exit 0
  fi

  rm -rf "${work_dir}"
  sleep 10
done

exit 1
