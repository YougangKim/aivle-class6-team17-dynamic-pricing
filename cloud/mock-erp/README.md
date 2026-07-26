# 신선식품 Mock ERP

외부 ERP가 AWS에 일부 데이터를 전송하는 과정을 구현하기 위한 로컬 프로그램입니다. 재고 스키마를 SQLite에 저장하고, FastAPI를 통해 조회·입력·수정·삭제하며, 향후 API Gateway로 전송할 JSON을 미리 확인할 수 있습니다.
이 폴더를 실행하는 것만으로는 AWS 서비스나 비용이 발생하지 않습니다. AWS 전송 주소와 비밀키를 직접 설정하기 전까지 `/api/aws/sync`도 안전하게 비활성화됩니다.

## 포함된 기능

- 브라우저 재고 대시보드
- 로트별 재고 입력 및 조회
- SQLite 자동 생성과 샘플 데이터 3건
- 재고 상태·수량·날짜 검증
- AWS 전송 JSON 미리보기
- 선택적 HTTPS POST 전송 기능
- Swagger API 문서
- 자동 테스트

## 자동 계산 필드

다음 값은 입력하지 않아도 서버에서 계산합니다.

| 필드 | 계산 방식 |
|---|---|
| `days_to_expiry` | 소비기한 - 기준일자 |
| `available_qty` | 현재 재고 - 예약수량 |
| `discount_price` | 정상 판매가 × (100 - 할인율) / 100 |
| `freshness_score` | 미입력 시 전체 보관기간 대비 잔여기간 비율, 0~100 |
| `disposal_candidate` | 미입력 시 소비기한이 지났거나 상태가 `DISPOSAL`이면 `Y` |

## 실행 방법

Windows PowerShell에서 저장된 폴더로 이동합니다.

예시:
```powershell
cd "C:\Users\User\Documents\빅프로젝트_AI 신선식품 다이나믹 프라이싱\mock-erp"
.\run.ps1
```

처음 실행할 때만 Python 패키지를 설치하므로 시간이 조금 걸릴 수 있습니다. 실행 후 다음 주소를 엽니다.

- 대시보드: http://127.0.0.1:8010
- API 문서: http://127.0.0.1:8010/docs
- 상태 확인: http://127.0.0.1:8010/health
- AWS 데이터 미리보기: http://127.0.0.1:8010/api/aws/payload-preview

종료할 때는 PowerShell 창에서 `Ctrl+C`를 누릅니다.

## 주요 API

| 방식 | 주소 | 용도 |
|---|---|---|
| GET | `/api/inventory` | 재고 목록과 필터 조회 |
| GET | `/api/inventory/{inventory_id}` | 재고 한 건 조회 |
| POST | `/api/inventory` | 재고 생성 |
| PUT | `/api/inventory/{inventory_id}` | 재고 수정 |
| DELETE | `/api/inventory/{inventory_id}` | 재고 삭제 |
| GET | `/api/aws/payload-preview` | AWS 전송 JSON 확인 |
| POST | `/api/aws/sync` | 설정된 AWS HTTPS API로 전송 |

필터 예시:

```text
GET /api/inventory?store_id=STORE001
GET /api/inventory?product_id=PROD001
GET /api/inventory?inventory_status=DISPOSAL
GET /api/inventory?disposal_candidate=Y
```

## 테스트

서버를 종료한 상태에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 폴더 구성

```text
mock-erp/
├─ app/main.py            API, 검증, SQLite 처리
├─ static/                브라우저 대시보드
├─ sample/                JSON·CSV 예시
├─ tests/test_api.py      자동 테스트
├─ data/                  실행 시 DB 생성
├─ requirements.txt
└─ run.ps1
```

## 재고 등록·수정 시 AWS 자동 전송

다음 환경변수를 설정하고 Mock ERP를 실행하면 `POST /api/inventory` 또는
`PUT /api/inventory/{inventory_id}` 성공 직후 해당 재고가 AWS로 자동
전송됩니다.

```powershell
$env:AWS_SYNC_URL="https://...execute-api.ap-northeast-2.amazonaws.com/demo/erp/sync"
$env:ERP_SHARED_TOKEN="Lambda에 설정한 공유 토큰"
$env:AWS_AUTO_SYNC="true"
.\run.ps1
```

처리 순서는 다음과 같습니다.

1. 재고를 로컬 SQLite에 저장합니다.
2. 저장된 재고 1건을 API Gateway로 전송합니다.
3. 성공하면 `aws_sync_status`가 `SYNCED`로 변경됩니다.
4. 실패하면 로컬 데이터는 유지되고 `aws_sync_status`가 `FAILED`가 됩니다.
5. `POST /api/aws/sync`를 호출하면 실패·대기 건을 다시 전송합니다.

`AWS_AUTO_SYNC=false`로 설정하면 자동 전송만 중지할 수 있습니다.
