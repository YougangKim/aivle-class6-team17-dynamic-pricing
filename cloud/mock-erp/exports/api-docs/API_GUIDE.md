# 신선식품 Mock ERP API 문서

> 버전 1.0.0 · 로컬 기본 주소 `http://127.0.0.1:8010`

외부 ERP가 신선식품 재고 데이터를 관리하고 향후 AWS API Gateway로 일부 데이터를 전송하는 과정을 실습하기 위한 API입니다.

## 빠른 확인

- 실행 중인 API 문서: `http://127.0.0.1:8010/docs`
- 상태 확인: `GET /health`
- 재고 목록: `GET /api/inventory`
- AWS 전송 미리보기: `GET /api/aws/payload-preview`
- `openapi.json`은 Swagger Editor, Postman 등으로 가져올 수 있습니다.

## 엔드포인트

### `GET /api/aws/payload-preview`

**Aws Payload Preview**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `limit` | query | N |  |

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |
| `422` | Validation Error |

### `POST /api/aws/sync`

**Sync To Aws**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `limit` | query | N |  |

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |
| `422` | Validation Error |

### `GET /api/inventory`

**List Inventory**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `store_id` | query | N |  |
| `product_id` | query | N |  |
| `inventory_status` | query | N |  |
| `disposal_candidate` | query | N |  |
| `limit` | query | N |  |

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |
| `422` | Validation Error |

### `POST /api/inventory`

**Create Inventory**

요청 본문: `application/json`

응답:

| 상태 코드 | 설명 |
|---:|---|
| `201` | Successful Response |
| `422` | Validation Error |

### `GET /api/inventory/{inventory_id}`

**Get Inventory**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `inventory_id` | path | Y |  |

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |
| `422` | Validation Error |

### `PUT /api/inventory/{inventory_id}`

**Update Inventory**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `inventory_id` | path | Y |  |

요청 본문: `application/json`

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |
| `422` | Validation Error |

### `DELETE /api/inventory/{inventory_id}`

**Delete Inventory**

요청 파라미터:

| 이름 | 위치 | 필수 | 설명 |
|---|---|---:|---|
| `inventory_id` | path | Y |  |

응답:

| 상태 코드 | 설명 |
|---:|---|
| `204` | Successful Response |
| `422` | Validation Error |

### `GET /health`

**Health**

응답:

| 상태 코드 | 설명 |
|---:|---|
| `200` | Successful Response |

## 재고 등록 요청 예시

```json
{
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
  "waste_reason": null,
  "weight_kg": 0.45
}
```

`days_to_expiry`, `available_qty`, `discount_price`, `freshness_score`, `disposal_candidate`는 서버에서 계산합니다.

## AWS 전송 주의사항

`POST /api/aws/sync`는 `AWS_SYNC_URL`과 `ERP_SHARED_TOKEN`이 모두 설정된 경우에만 외부 HTTPS 요청을 실행합니다. 문서나 공개 저장소에 실제 비밀키를 포함하지 마세요.
