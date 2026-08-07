# 인프라 전달용 A/B 함수 계약

Model A/B 전체를 한 번에 보는 최상위 문서는 이 전달본 루트의 `README.md`입니다. 이 문서는 validator와 세부 전달 필드를 보충합니다.

## 물리적 경계

| 구분 | 구현 경로 | 대표 함수 | 상대 모델 import |
|---|---|---|---|
| Model A | `src/model_a/` | `src.model_a.run_model_a(a_input: dict) -> dict` | B를 import하지 않음 |
| Model B | `src/model_b/` | `src.model_b.run_model_b(b_input: dict) -> dict` | A·LightGBM·Surrogate·Adam을 import하지 않음 |
| 공통 계약 | `src/contracts/infrastructure_schemas.py` | 입력/출력 validator | 모델 구현을 import하지 않음 |
| 연결 예시 | `example_pipeline.py` | `run_one_a_b_a_exchange(a_input: dict) -> dict` | 순서만 조정하며 모델 로직 없음 |

`src/model_b/discriminator.py`에는 B팀이 전달한 Code2 원본과 원본 결과를 검증해 읽는 `OriginalCode2Discriminator`만 둔다. 현재 개발 검증용 `ScopeAlignedExperimentalDiscriminator`는 `src/model_b/experimental_discriminator.py`에 따로 둔다. 두 모드는 `options.discriminator_mode`의 `ORIGINAL_CODE2` 또는 `SCOPE_ALIGNED_EXPERIMENTAL`로 선택한다. 현재 점포·현재시각~마감 최적화 wrapper는 명시적으로 실험 판별기를 사용한다.

## A 입력

```json
{
  "request_id": "unique-request-id",
  "schema_version": "1.0",
  "store_id": "S01",
  "current_time": "2025-12-31T18:00:00+09:00",
  "current_state": {"source": "OPERATING_SYSTEM_CURRENT_STATE", "cells": []},
  "options": {"discriminator_mode": "SCOPE_ALIGNED_EXPERIMENTAL"},
  "previous_b_evaluation": null
}
```

첫 호출에서는 `previous_b_evaluation`을 생략한다. 다음 호출부터는 직전 `run_model_b` 반환 dict를 아무 수정 없이 넣는다. `current_state.cells`가 비어 있으면 현재 저장소 snapshot을 읽는 명시적 데모/로컬 경로이며 운영 입력은 아니다.

## A 출력 / B의 policy 입력

핵심 필드는 `request_id`, `store_id`, `policy_iteration`, `policy_shape=[38,4]`, `policy_matrix`, `policy_source`, `candidate_ready`, `model_status`, `optimization_status`, `warnings`다. 사람이 읽는 `policy_long`은 항상 152행이며 각 행에 `store_id`, `product_id`, `product_index`, `dte`, `dte_bucket`, `dte_index`, `available_qty`, `active_inventory_flag`, `discount_rate`를 둔다.

B에는 A 출력 전체를 `policy` 필드로 넣는다. B validator는 request/store 일치, `(38,4)` shape, 유한한 0~0.40 할인율을 확인한다.

## B 입력

```python
b_input = {
    "request_id": a_input["request_id"],
    "store_id": a_input["store_id"],
    "current_time": a_input["current_time"],
    "current_state": a_input["current_state"],
    "options": a_input["options"],
    "policy": a_output,
}
```

## B 출력 / A의 다음 feedback 입력

| 영역 | 필드 |
|---|---|
| 식별 | `request_id`, `store_id`, `policy_iteration`, `policy_hash`, `policy_shape` |
| KPI | `metrics.expected_demand`, `expected_sales_qty`, `expected_revenue`, `expected_profit`, `expected_waste_qty`, `expected_waste_rate`, `expected_waste_cost`(계산 가능 시) |
| 판정 | `judgement.threshold_pass`, `threshold_passed`, `reject_reason`, `profit_gap`, `revenue_gap`, `waste_gap` |
| 판별기 추적 | `discriminator_version`, `threshold_version`, `artifact_source`, `artifact_paths`, `threshold_scope` |
| 평가 범위 | `evaluation_scope`, `evaluation_start`, `evaluation_end`, `active_cell_count`, `b_backend`, `b_model_version` |

B 출력에는 인프라 편의를 위한 KPI/판정 flat alias도 있지만 A는 기존 호환성을 위해 `metrics`와 `judgement`를 사용한다. B 출력 dict는 `previous_b_evaluation`으로 바로 전달 가능하다.

## 직접 호출 예시

```python
from src.model_a import run_model_a
from src.model_b import run_model_b

a_output = run_model_a(a_input)
b_output = run_model_b({
    "request_id": a_input["request_id"],
    "store_id": a_input["store_id"],
    "current_time": a_input["current_time"],
    "current_state": a_input["current_state"],
    "options": a_input.get("options", {}),
    "policy": a_output,
})

next_a_input = dict(a_input)
next_a_input["previous_b_evaluation"] = b_output
next_a_output = run_model_a(next_a_input)
```

전체 baseline·반복·최종 후보 선택은 기존 `src.pipeline.run_discount_optimization`과 점포별 `src.pipeline.optimize_discount_policy`가 담당한다. 이 오케스트레이터는 두 모델의 계산식을 복사하지 않는다.
