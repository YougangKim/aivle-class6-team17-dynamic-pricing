# Model A / Model B 통합 호출 문서

```text
Model A entry point: src.model_a.run_model_a
Model B entry point: src.model_b.run_model_b
A/B orchestration example: example_pipeline.py
Full optimization pipeline: src.pipeline
```

이 폴더는 인프라팀이 Model A와 Model B를 독립적으로 호출하고 연결할 수 있도록 만든 최소 독립 실행 전달본입니다. 모든 runtime import, 데이터 및 B 원본 dependency는 이 `model_ver2` 내부 경로만 사용합니다.

현재 `artifacts/model_a/initial_policy_artifact_status.json`은 `INVALID / NOT_TRAINED`입니다. 이를 임의로 `TRAINED`로 바꾸거나 가짜 LightGBM 파일을 추가하지 않았습니다. 구조 검증 예시는 `allow_initial_policy_fallback=true`를 명시하며 그 결과를 운영 성능으로 해석하면 안 됩니다.

이 전달본의 독립 실행 범위는 현재 정책 생성·B 평가·A↔B runtime입니다. `src/model_a` 전체 소스를 보존하므로 과거 재고 복원 코드도 포함되지만, 재학습용 `receipt.csv`, `transaction.csv`, `data/derived/`는 의도적으로 제외되어 해당 오프라인 재학습 작업은 이 전달본만으로 수행하지 않습니다.

정책 한 개의 단위는 다음과 같습니다.

```text
점포 1개 × 의사결정 시각 1개 × 상품 38개 × DTE 4개
```

A는 매 호출마다 전체 `(38, 4)` 할인정책 후보 한 개만 반환하고, B는 그 전체 행렬 한 개를 한 번에 평가합니다. 상품×DTE 셀을 따로 B에 보내서 결과를 합치거나 S01/S02/S03를 456차원 정책 하나로 합치지 않습니다.

## 1. 코드 경계와 역할

| 구분 | 물리적 구현 | 역할 | 상대 모델 의존성 |
|---|---|---|---|
| Model A | `src/model_a/` | LightGBM 초기정책, B feedback Replay Buffer, Full-policy Surrogate 학습, Adam 다음 정책 생성 | `src/model_b`를 import하지 않음 |
| Model B | `src/model_b/`, `src/b_runtime/` | 전체 정책 고객 시뮬레이션, 수요·판매·매출·이익·폐기 계산, threshold 판정 | `src/model_a`를 import하지 않음 |
| 공통 계약 | `src/contracts/infrastructure_schemas.py` | A/B 입력과 출력 검증, 인프라 입력을 기존 runtime request로 변환 | A/B 구현을 import하지 않음 |
| 연결 예시 | `example_pipeline.py` | A→B→A 호출 순서만 조정 | 모델 계산식 없음 |
| 전체 운영 반복 | `src/pipeline/` | 0% baseline, A↔B 반복, 수렴, 최종 정책 선택 | 공개 경계를 조합하는 orchestration |

## 2. 대표 호출 함수

인프라에서 사용하는 대표 함수는 모델마다 하나입니다.

```python
from src.model_a import run_model_a
from src.model_b import run_model_b

a_output: dict = run_model_a(a_input: dict)
b_output: dict = run_model_b(b_input: dict)
```

정확한 signature:

```python
run_model_a(a_input: dict) -> dict
run_model_b(b_input: dict) -> dict
```

기존 저수준 함수 `generate_discount_candidate(request, previous_b_evaluation=None)`와 `evaluate_policy(request, policy)`는 기존 pipeline과 Colab 호환을 위해 유지합니다. 신규 인프라 연동에서는 위의 `run_model_a`와 `run_model_b`를 사용합니다.

## 3. Model A 입력 스키마

| 필드 | 필수 | 형식 | 설명 |
|---|---:|---|---|
| `request_id` | 예 | string | 한 A↔B 반복 session에서 바꾸지 않는 고유 ID |
| `schema_version` | 아니오 | string | 생략 시 `1.0`; 현재 `1.0`만 지원 |
| `store_id` | 예 | string | 현재 점포 ID. 운영 대상은 S01/S02/S03 |
| `current_time` | 예 | ISO-8601 string | 현재 의사결정 시각과 timezone |
| `current_state` | 예 | object 또는 cell array | 현재 점포의 상품×DTE 재고 상태 |
| `options` | 아니오 | object | 반복, 수렴, seed, 판별기 모드 설정 |
| `previous_b_evaluation` | 첫 호출 아니오, 이후 예 | object | 직전 `run_model_b()` 반환 dict 전체 |

`current_state` object는 다음 형태를 사용합니다.

```json
{
  "source": "OPERATING_SYSTEM_CURRENT_STATE",
  "cells": [
    {
      "store_id": "S01",
      "product_id": "P001",
      "product_index": 0,
      "dte_index": 1,
      "available_qty": 12,
      "freshness_score": 0.72,
      "regular_price": 5000,
      "unit_cost": 3200,
      "visitor_count": 35,
      "previous_discount_rate": 0.10,
      "active_inventory_flag": true
    }
  ]
}
```

셀의 필수 식별값은 `product_id`, `dte_index`이고, 실제 할인 대상 판단에는 `available_qty`가 필요합니다. `product_index`를 제공하면 B mapping과 일치해야 합니다. 할인율은 20이 아니라 `0.20`처럼 비율로 전달합니다.

`current_state.cells=[]`이면 저장소의 `inventory.csv` snapshot을 읽습니다. 이는 예제·로컬 검증 경로이며 실제 운영에서는 인프라가 현재 재고 snapshot을 전달해야 합니다.

## 4. Model A 출력 스키마

| 필드 | 형식 | 설명 |
|---|---|---|
| `request_id`, `store_id` | string | 입력 식별자 |
| `policy_iteration` | integer | B 평가 한 번과 대응하는 외부 정책 반복 번호 |
| `policy_outer_iteration` | integer | `policy_iteration`과 같은 정책 반복 단위 |
| `policy_shape` | `[38, 4]` | 상품 38개 × DTE 4개 |
| `policy_matrix` | float `[38][4]` | B에 전달할 전체 할인정책 후보 한 개 |
| `policy_hash` | string | B가 같은 정책을 받았는지 확인하는 SHA-256 |
| `policy_source` | string | `LIGHTGBM`, `SURROGATE_ADAM`, warm-up 또는 명시적 fallback 출처 |
| `candidate_ready` | boolean | B가 평가할 새 후보가 존재하는지 여부 |
| `policy_long` | 152-row array | `store_id`, `product_id`, `dte`, `discount_rate` 중심의 사람이 읽는 형식 |
| `model_status` | object | InitialPolicyLightGBM, Surrogate, Adam 상태 |
| `optimization_status` | object | 수렴 횟수, 통과 정책 수, 종료 상태 |
| `warnings` | array | fallback 또는 실험 판별기 관련 경고 |

정상 후보의 `policy_matrix`는 finite, 0~0.40 범위이고 최종 실행 단위는 1%p입니다. 비활성 재고 셀은 제약 처리됩니다.

## 5. Model B 입력 스키마

B는 동일한 점포·시점·상태 context와 A 출력 전체를 받습니다.

| 필드 | 필수 | 설명 |
|---|---:|---|
| `request_id` | 예 | A와 같은 request ID |
| `schema_version` | 아니오 | A와 같은 schema version |
| `store_id` | 예 | A 출력 `store_id`와 같아야 함 |
| `current_time` | 예 | A와 같은 의사결정 시각 |
| `current_state` | 예 | A와 같은 현재 상태 snapshot |
| `options` | 아니오 | 동일 request에서 판별기 모드를 바꿀 수 없음 |
| `policy` | 예 | `run_model_a()` 반환 dict 전체 |

B validator는 `request_id`, `store_id`, `(38,4)` shape, 할인율 범위와 유한값을 확인합니다.

## 6. Model B 출력과 평가지표

| 영역 | 필드 | 의미 |
|---|---|---|
| 식별 | `request_id`, `store_id`, `policy_iteration`, `policy_hash` | 어떤 요청·정책의 평가인지 식별 |
| 평가 범위 | `evaluation_scope`, `evaluation_start`, `evaluation_end` | B가 계산한 점포 및 시간 범위 |
| KPI | `metrics.expected_demand` | 예상수요 |
| KPI | `metrics.expected_sales_qty` | 예상판매량 |
| KPI | `metrics.expected_revenue` | 예상매출 |
| KPI | `metrics.expected_profit` | 예상이익; A의 기본 목적함수 |
| KPI | `metrics.expected_waste_qty` | 예상폐기수량 |
| KPI | `metrics.expected_waste_rate` | 예상폐기율 |
| 판정 | `judgement.threshold_pass`, `threshold_passed` | B 최종 threshold 통과 여부 |
| 판정 | `judgement.reject_reason`, `reject_reason` | 미통과 사유 |
| 판정 | `profit_gap`, `revenue_gap`, `waste_gap` | 판정 기준과의 차이 |
| 추적 | `b_backend`, `b_model_version` | 실행한 B backend/version |
| 추적 | `discriminator_version`, `threshold_version` | 사용한 판별기와 threshold version |
| 추적 | `artifact_source`, `artifact_paths` | 판별 근거 artifact |

flat KPI alias도 반환하지만 A의 기존 내부 계약은 `metrics`와 `judgement`를 사용합니다. A는 threshold를 자체 판정하지 않고 B가 반환한 판정을 저장하고 사용합니다.

## 7. A→B 전달값과 B→A 반환값

### A→B

```python
b_input = {
    "request_id": a_input["request_id"],
    "schema_version": a_input.get("schema_version", "1.0"),
    "store_id": a_input["store_id"],
    "current_time": a_input["current_time"],
    "current_state": a_input["current_state"],
    "options": a_input.get("options", {}),
    "policy": a_output,
}
```

핵심 전달값은 점포 context, 현재 상태, 전체 `(38,4)` 정책 한 개입니다.

### B→A

```python
next_a_input = dict(a_input)
next_a_input["previous_b_evaluation"] = b_output
```

B 출력 dict를 수정하거나 KPI 이름을 변환하지 않습니다. A가 request ID, store ID, iteration, policy hash, B backend/version을 다시 검증합니다.

## 8. A↔B 반복 흐름

```text
해당 점포 전체 0% 정책
→ B 1회 평가
→ baseline_metrics 저장

현재 점포 상태
→ A InitialPolicyLightGBM 첫 (38,4) 후보 1개
→ B 전체 정책 시뮬레이션 및 판정
→ B 결과를 A Replay Buffer에 저장
→ 충분한 실제 B 결과가 있으면 Full-policy Surrogate 학습
→ Adam으로 활성 정책 셀 갱신
→ A가 다음 전체 (38,4) 후보 1개 반환
→ B가 다음 전체 정책 1개 평가
→ 통과 상태에서 정책·실제 B 이익이 3회 연속 수렴할 때까지 반복
→ 전체 실제 B 통과 후보 중 expected_profit 최고 정책 선택
```

단순 `example_pipeline.py`는 함수 교환을 짧게 보여주기 위해 A→B→A 한 번만 수행합니다. 0% baseline부터 종료조건까지 전체 반복하려면 `src.pipeline.optimize_discount_policy()` 또는 `run_discount_optimization()`을 사용합니다.

## 9. 판별기 선택

| 설정값 | 구현 파일 | 현재 용도 |
|---|---|---|
| `ORIGINAL_CODE2` | `src/model_b/discriminator.py` | B팀 전달 Code2 원본 판별 재현 |
| `SCOPE_ALIGNED_EXPERIMENTAL` | `src/model_b/experimental_discriminator.py` | 현재 점포·현재시각~마감 범위 개발 검증 |

현재 점포별 `optimize_discount_policy()`와 예제 인프라 입력은 `SCOPE_ALIGNED_EXPERIMENTAL`을 명시합니다. 이 판별기는 공식 판별기를 덮어쓰지 않으며 B팀 공식 운영 승인을 의미하지 않습니다. rebuilt, uncalibrated 또는 Mock 판별기로 자동 fallback하지 않습니다.

## 10. `example_pipeline.py` 실행

Windows PowerShell:

```powershell
Set-Location 'C:\path\to\model_ver2'
.\.venv\Scripts\Activate.ps1
python example_pipeline.py
```

또는 가상환경 Python을 직접 사용합니다.

```powershell
.\.venv\Scripts\python.exe example_pipeline.py
```

입력 예시는 `data/sample_infrastructure_input.json`입니다. 현재 유효한 InitialPolicyLightGBM artifact가 없기 때문에 이 예시는 `allow_initial_policy_fallback=true`를 명시한 함수 연결 검증이며 운영 성능 결과가 아닙니다.

예상되는 요약 출력 항목:

```text
request_id
first_policy_source
first_policy_shape
b_backend
b_expected_profit
next_policy_source
```

전체 점포 운영 호출 예:

```python
from src.pipeline import optimize_discount_policy

result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-12-31T18:00:00+09:00",
    current_state={"source": "OPERATING_SYSTEM_CURRENT_STATE", "cells": current_cells},
    options={"discriminator_mode": "SCOPE_ALIGNED_EXPERIMENTAL"},
)
```

## 11. 관련 파일

- 실행 예시: `example_pipeline.py`
- 인프라 예제 입력: `data/sample_infrastructure_input.json`
- Python schema validator: `src/contracts/infrastructure_schemas.py`
- 세부 API 계약: `docs/infrastructure_api_contract.md`
- 점포별 운영 설명: `docs/store_scoped_optimization.md`

현재 A/B별로 별도 README가 필요한 정도의 추가 독립 내용은 없으므로 `src/model_a/README.md`나 `src/model_b/README.md`를 만들지 않았습니다. 모든 공통 호출 정보는 이 문서에서 확인할 수 있습니다.
