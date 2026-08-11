from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row


@lru_cache(maxsize=1)
def get_db_secret() -> dict[str, Any]:
    """Read the RDS credentials once and cache them for the process lifetime."""
    secret_arn = os.getenv("DB_SECRET_ARN", "").strip()
    if not secret_arn:
        raise RuntimeError("DB_SECRET_ARN 환경변수가 없습니다.")

    client = boto3.client(
        "secretsmanager",
        region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
    )
    result = client.get_secret_value(SecretId=secret_arn)
    raw = result.get("SecretString")
    if not raw:
        raw = base64.b64decode(result["SecretBinary"]).decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("DB Secret은 JSON 객체여야 합니다.")
    return value


def db_settings() -> dict[str, Any]:
    secret = get_db_secret()
    return {
        "host": secret.get("host") or os.environ["DB_HOST"],
        "port": int(secret.get("port") or os.getenv("DB_PORT", "5432")),
        "dbname": secret.get("dbname") or os.getenv("DB_NAME", "aivle_db"),
        "user": secret["username"],
        "password": secret["password"],
    }


def connect_rds() -> psycopg.Connection:
    return psycopg.connect(
        **db_settings(),
        connect_timeout=5,
        sslmode=os.getenv("DB_SSLMODE", "require"),
        row_factory=dict_row,
    )
