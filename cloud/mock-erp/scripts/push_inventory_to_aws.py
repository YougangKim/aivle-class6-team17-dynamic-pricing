import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.main import InventoryRecord


def load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("재고 파일은 한 건 이상의 JSON 배열이어야 합니다.")
    if len(data) > 100:
        raise ValueError("한 번에 전송할 수 있는 재고는 최대 100건입니다.")

    now = datetime.now(timezone.utc).isoformat()
    records = []
    for index, raw_record in enumerate(data):
        try:
            record = InventoryRecord.model_validate(raw_record).model_dump(mode="json")
        except Exception as exc:
            raise ValueError(f"{path}의 {index + 1}번째 재고가 올바르지 않습니다: {exc}") from exc
        record["created_at"] = raw_record.get("created_at") or now
        record["updated_at"] = now
        records.append(record)
    return records


def post_records(url: str, token: str, records: list[dict]) -> dict:
    if not url.startswith("https://"):
        raise ValueError("AWS_SYNC_URL은 https:// 주소여야 합니다.")

    payload = {
        "source": "local-mock-erp",
        "data_type": "inventory",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-ERP-API-KEY": token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or not body.get("success"):
            raise RuntimeError(f"AWS 저장 실패: HTTP {response.status}, {body}")
        return body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Git에 저장된 Mock ERP 재고 JSON을 AWS RDS 연동 API로 전송합니다."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="sync-data/inventory.json",
        type=Path,
        help="전송할 재고 JSON 배열 파일",
    )
    args = parser.parse_args()

    url = os.getenv("AWS_SYNC_URL", "").strip()
    token = os.getenv("ERP_SHARED_TOKEN", "").strip()
    if not url or not token:
        print(
            "AWS_SYNC_URL과 ERP_SHARED_TOKEN 환경변수가 모두 필요합니다.",
            file=sys.stderr,
        )
        return 2

    try:
        records = load_records(args.path)
        result = post_records(url, token, records)
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        print(f"AWS API 오류: HTTP {exc.code}, {response_body}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"전송 실패: {exc}", file=sys.stderr)
        return 1

    print(
        "AWS RDS 반영 완료:",
        f"batch_id={result.get('batch_id')}",
        f"saved_count={result.get('saved_count')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
