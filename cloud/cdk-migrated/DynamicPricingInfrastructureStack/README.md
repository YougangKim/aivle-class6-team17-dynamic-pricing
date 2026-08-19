# Dynamic Pricing Infrastructure Stack

AWS CloudFormation IaC Generator가 추출한 인프라를 Python AWS CDK 형식으로 옮긴 프로젝트입니다. 이 프로젝트에는 **배포용 마이그레이션 Stack**과 **AWS PDK 시각화 전용 Stack**이 함께 있습니다.

> 주의: 이 프로젝트는 마이그레이션 검증 경고를 포함합니다. 경고를 검토·수정하기 전에는 `cdk deploy`, `cdk import`, `cdk destroy`를 실행하지 마세요.

상위 폴더 전체 역할은 [Cloud README](../../README.md)를 참고하세요.

## 구성

```text
DynamicPricingInfrastructureStack/
├── app.py                                      # 배포용 CDK App 진입점
├── cdk.json                                    # CDK Toolkit 실행 설정
├── migrate.json                                # CDK Migrate 메타데이터
├── requirements*.txt                           # Python/CDK/PDK 의존성
├── dynamic_pricing_infrastructure_stack/
│   ├── dynamic_pricing_infrastructure_stack_stack.py  # 마이그레이션 배포용 Stack
│   └── reference_architecture_stack.py                # PDK 시각화 전용 Stack
├── reference_app.py                             # 기본 참조 다이어그램 진입점
├── step_functions_reference_app.py              # Step Functions 포함 다이어그램 진입점
├── render_reference_diagram.py                  # 기본 SVG 후처리
├── render_step_functions_diagram.py             # 유향·무향 SVG 후처리
├── architecture/                                # 최종 SVG/DOT와 AWS 아이콘
├── cdk.out*/                                   # synth/PDK 중간 산출물
└── tests/                                       # CDK 단위 테스트
```

## 배포용 CDK와 시각화용 CDK

| 구분 | 관련 파일 | 역할 |
|---|---|---|
| 배포용 CDK | `app.py`, `dynamic_pricing_infrastructure_stack_stack.py` | IaC Generator 변환 결과를 CloudFormation으로 합성 |
| 기본 시각화 | `reference_app.py`, `reference_architecture_stack.py` | CDK 토큰과 명시적 dependency로 관계를 복원해 PDK 그래프 생성 |
| Step Functions 시각화 | `step_functions_reference_app.py` | Scheduler → Step Functions → Lambda 흐름을 포함한 별도 그래프 생성 |
| SVG 후처리 | `render_*.py` | 직각선, 실선, 화살표 방향, 서비스 아이콘을 최종 SVG에 적용 |

`reference_architecture_stack.py`에는 그림 관계 표현용 placeholder와 명시적 dependency가 있으므로 배포용 Stack으로 사용하면 안 됩니다.

## 로컬 준비

Windows PowerShell 예시입니다.

```powershell
cd cloud\cdk-migrated\DynamicPricingInfrastructureStack
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`.venv/`, `__pycache__/`, `cdk.out/`은 로컬 산출물이며 Git에 올리지 않습니다.

## 안전한 CDK 명령

```powershell
# 현재 App에 등록된 Stack 목록
cdk ls

# CloudFormation 템플릿만 생성 — AWS 리소스 변경 없음
cdk synth

# 현재 배포 상태와 코드 차이 확인 — AWS 리소스 변경 없음
cdk diff
```

다음 명령은 AWS 계정 리소스를 만들거나 바꾸거나 삭제할 수 있습니다.

```powershell
# 검증 경고 해결 전 실행 금지
cdk deploy
cdk import
cdk destroy
```

## PDK 다이어그램 생성

```powershell
# 기본 참조 다이어그램
python reference_app.py
python render_reference_diagram.py

# Step Functions 포함 다이어그램
python step_functions_reference_app.py
python render_step_functions_diagram.py
```

출력은 `architecture/`에 생성됩니다. 무향 SVG는 `dynamic-pricing-step-functions-undirected.svg`, 방향 정보를 포함하는 SVG는 `dynamic-pricing-step-functions-directed.svg`입니다.

## 마이그레이션 경고 요약

IaC Generator는 읽을 수 없는 쓰기 전용 속성이나 CDK에서 아직 지원하지 않는 속성을 완전하게 변환하지 못할 수 있습니다. 상세 원본 경고는 CDK Migrate 실행 결과와 `migrate.json`을 기준으로 확인합니다.

| 리소스 영역 | 확인할 항목 |
|---|---|
| Auto Scaling Group | `SkipZonalShiftValidation` 변환 지원 여부 |
| S3 버킷 | 수명 주기, 버전 관리, 메타데이터 테이블, ACL, 복제 관련 속성 |
| RDS / Neptune | `aivle-rds`의 PostgreSQL/RDS 정의와 잘못 추론된 Neptune 중복 여부 |
| Lambda | Code 저장 방식, SnapStart, Published Version 관련 변환 속성 |
| Secrets Manager | Secret 값과 생성 규칙은 읽을 수 없는 속성일 수 있으므로 코드·Git에 저장 금지 |
| EC2 / VPC / Subnet | 하드코딩된 AMI, 네트워크 인터페이스 및 서브넷 비지원 속성 |
| Load Balancer | 서브넷 및 용량 예약 안정화 설정 |
| IAM User / KMS | 로그인 프로필, KMS 삭제 대기·회전 정책 등 민감·비지원 속성 |

특히 다음은 배포 전 반드시 사람이 확인해야 합니다.

- `aivle-rds`는 PostgreSQL RDS로 확인해야 하며, 생성기가 중복 추론한 Neptune 리소스는 배포 대상에서 제외해야 합니다.
- 로드 밸런서 서브넷과 보안 그룹 연결이 실제 VPC 구성과 일치하는지 확인합니다.
- RDS 비밀번호, AWS Access Key, Secret Access Key, Secret 값은 코드·YAML·Git 이력에 포함하면 안 됩니다.
- 쓰기 전용 값은 AWS Secrets Manager, SSM Parameter Store 또는 배포 시 전달되는 안전한 환경변수로 제공합니다.

## 테스트

```powershell
python -m pytest tests -q
```

## 관련 문서

- [상위 Cloud 구조 문서](../../README.md)
- [PDK 다이어그램 문서](./architecture/README.md)
- [IaC Generator 출력](../../iac-export/)
