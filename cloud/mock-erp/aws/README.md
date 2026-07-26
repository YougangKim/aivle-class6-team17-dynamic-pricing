# 기존 Mock ERP의 AWS RDS 연동

이 폴더는 상위 `mock-erp`가 전송하는 재고 배치를 그대로 수신합니다.

```text
mock-erp /api/aws/sync
  -> API Gateway HTTP API POST /demo/erp/sync
  -> Lambda
  -> RDS PostgreSQL inventory 테이블
```

## 생성되는 AWS 자원

- 서울 리전 VPC와 프라이빗 서브넷 2개
- Single-AZ RDS PostgreSQL `db.t4g.micro`, gp3 20GB
- Python Lambda
- API Gateway HTTP API
- Lambda와 RDS 전용 보안 그룹

NAT Gateway, 로드 밸런서, RDS Proxy는 생성하지 않습니다. RDS는 외부에
공개되지 않으며 Lambda 보안 그룹에서 들어오는 5432 연결만 허용합니다.

## 사전 준비

1. AWS CLI v2를 설치합니다.
2. AWS SAM CLI를 설치합니다.
3. `aws configure`에서 서울 리전과 배포용 IAM 자격증명을 설정합니다.
4. 현재 IAM 사용자에게 CloudFormation, VPC, RDS, Lambda, API Gateway,
   IAM 역할 생성 권한이 있는지 확인합니다.

## 배포

`mock-erp` 폴더에서 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\aws\deploy.ps1
```

스크립트는 AWS 계정과 실행 주체를 먼저 표시하고, `DEPLOY` 확인을 받은
후에만 비용이 발생하는 RDS를 생성합니다. 비밀번호와 공유 토큰은
PowerShell 입력창에서 묻습니다.

## 로컬 Mock ERP 연결

배포 결과의 `SyncUrl`과 배포 때 입력한 공유 토큰을 현재 PowerShell 창에
설정합니다.

```powershell
$env:AWS_SYNC_URL="https://...execute-api.ap-northeast-2.amazonaws.com/demo/erp/sync"
$env:ERP_SHARED_TOKEN="배포할-때-입력한-공유-토큰"
.\run.ps1
```

브라우저에서 `http://127.0.0.1:8010`을 열고 AWS 전송을 실행하거나 다음
명령을 사용합니다.

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8010/api/aws/sync?limit=3"
```

성공 응답에는 `batch_id`와 `saved_count`가 포함됩니다. 같은
`inventory_id`를 다시 보내면 새 행을 중복 생성하지 않고 기존 행을
업데이트합니다.

## 비용 중지

데모가 끝나면 스택을 삭제해야 RDS 실행 비용이 중단됩니다.

```powershell
sam delete --stack-name fresh-food-mock-erp --region ap-northeast-2
```

템플릿은 데모 비용을 남기지 않기 위해 RDS 삭제 시 최종 스냅샷을
보존하지 않도록 설계되어 있습니다. 필요한 데이터는 삭제 전에 별도로
내보내야 합니다.
