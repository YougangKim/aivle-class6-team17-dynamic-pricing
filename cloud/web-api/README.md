# FreshWatch WEB API

프론트엔드가 AWS RDS의 `P001`~`P038` 실제 재고를 조회하기 위한 읽기 전용 API입니다.
Mock ERP 데이터를 RDS에 적재하는 `cloud/erp-receiver`와 역할이 다릅니다.

## Endpoints

- `GET /health`: 애플리케이션 실행 확인
- `GET /ready`: RDS 연결 확인
- `GET /api/inventory?store_id=S01`: 최신 재고 조회
- `GET /api/summary?store_id=S01`: 대시보드용 실제 재고 집계
- `GET /api/recommendations?store_id=S01`: 모델 준비 전에는 빈 배열
- `GET /api/recommendations/skipped?store_id=S01`: 모델 준비 전에는 빈 배열

## Local run

PowerShell에서 실제 AWS 값을 환경변수에 설정합니다. DB 비밀번호는 입력하지 않습니다.

```powershell
$env:AWS_REGION="ap-northeast-2"
$env:DB_SECRET_ARN="실제 DB Secret ARN"
$env:DB_HOST="실제 RDS 엔드포인트"
$env:DB_PORT="5432"
$env:DB_NAME="aivle_db"
```

서버를 실행합니다.

```powershell
cd cloud\web-api
python -m uvicorn app.main:app --reload --port 8000
```

DB 비밀번호는 프론트나 Git에 저장하지 않고 AWS Secrets Manager에서 읽습니다.

로컬 PC가 Private RDS에 접근할 수 없다면 `/health`는 성공하고 `/ready`는 실패할 수
있습니다. 이 경우 RDS를 인터넷에 공개하지 말고 같은 VPC의 WEB EC2에 API를 배포해
`/ready`를 확인합니다.
