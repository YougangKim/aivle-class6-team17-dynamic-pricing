import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.main import app


OUTPUT_DIR = BASE_DIR / "exports" / "api-docs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

schema = app.openapi()
(OUTPUT_DIR / "openapi.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
)

method_order = {"get": 1, "post": 2, "put": 3, "patch": 4, "delete": 5}
lines = [
    "# 신선식품 Mock ERP API 문서",
    "",
    "> 버전 1.0.0 · 로컬 기본 주소 `http://127.0.0.1:8010`",
    "",
    "외부 ERP가 신선식품 재고 데이터를 관리하고 향후 AWS API Gateway로 일부 데이터를 전송하는 과정을 실습하기 위한 API입니다.",
    "",
    "## 빠른 확인",
    "",
    "- 실행 중인 API 문서: `http://127.0.0.1:8010/docs`",
    "- 상태 확인: `GET /health`",
    "- 재고 목록: `GET /api/inventory`",
    "- AWS 전송 미리보기: `GET /api/aws/payload-preview`",
    "- `openapi.json`은 Swagger Editor, Postman 등으로 가져올 수 있습니다.",
    "",
    "## 엔드포인트",
    "",
]

for path, operations in sorted(schema.get("paths", {}).items()):
    for method, operation in sorted(
        operations.items(), key=lambda item: method_order.get(item[0], 99)
    ):
        if method not in method_order:
            continue
        title = operation.get("summary") or operation.get("operationId") or "API"
        description = operation.get("description", "")
        lines.extend([
            f"### `{method.upper()} {path}`",
            "",
            f"**{title}**",
            "",
        ])
        if description:
            lines.extend([description, ""])

        parameters = operation.get("parameters", [])
        if parameters:
            lines.extend([
                "요청 파라미터:", "",
                "| 이름 | 위치 | 필수 | 설명 |",
                "|---|---|---:|---|",
            ])
            for parameter in parameters:
                lines.append(
                    f"| `{parameter.get('name', '')}` | {parameter.get('in', '')} | "
                    f"{'Y' if parameter.get('required') else 'N'} | {parameter.get('description', '')} |"
                )
            lines.append("")

        if "requestBody" in operation:
            lines.extend(["요청 본문: `application/json`", ""])

        responses = operation.get("responses", {})
        if responses:
            lines.extend([
                "응답:", "",
                "| 상태 코드 | 설명 |",
                "|---:|---|",
            ])
            for code, response in responses.items():
                lines.append(f"| `{code}` | {response.get('description', '')} |")
            lines.append("")

lines.extend([
    "## 재고 등록 요청 예시",
    "",
    "```json",
    json.dumps({
        "inventory_id": "INV000004",
        "store_id": "STORE001",
        "product_id": "PROD004",
        "lot_id": "LOT20260722001",
        "current_date": "2026-07-22",
        "manufacture_date": "2026-07-20",
        "expiry_date": "2026-07-27",
        "inbound_qty": 50,
        "daily_sold_qty": 0,
        "daily_waste_qty": 0,
        "current_stock_qty": 50,
        "reserved_qty": 0,
        "unit_cost": 3500,
        "unit_price": 4980,
        "discount_rate": 20,
        "inventory_status": "ON_SALE",
        "waste_reason": None,
        "weight_kg": 0.45,
    }, ensure_ascii=False, indent=2),
    "```",
    "",
    "`days_to_expiry`, `available_qty`, `discount_price`, `freshness_score`, `disposal_candidate`는 서버에서 계산합니다.",
    "",
    "## AWS 전송 주의사항",
    "",
    "`POST /api/aws/sync`는 `AWS_SYNC_URL`과 `ERP_SHARED_TOKEN`이 모두 설정된 경우에만 외부 HTTPS 요청을 실행합니다. 문서나 공개 저장소에 실제 비밀키를 포함하지 마세요.",
])

(OUTPUT_DIR / "API_GUIDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

print(OUTPUT_DIR)
