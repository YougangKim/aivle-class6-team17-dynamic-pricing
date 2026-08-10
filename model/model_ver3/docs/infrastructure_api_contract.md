# 인프라 전달용 A/B 함수 계약

## 최종 정책 승인 응답

통합 최적화 응답은 다음 규칙을 사용한다.

- 승인: `status="SUCCESS"`, `execution_eligible=true`, `final_policy.threshold_pass=true`
- 미승인: `status="NO_THRESHOLD_PASS"`, `execution_eligible=false`, `final_policy=null`, `fallback_type="KEEP_CURRENT_POLICY"`
- 미통과 최고 후보: `diagnostic_best_candidate`에만 저장하며 실행 정책으로 전달하지 않는다.

`KEEP_CURRENT_POLICY`는 기존 운영 정책을 그대로 유지한다는 상태이며 신규 정책을 승인하는 fallback이 아니다.

Model A/B 전체를 한 번에 보는 최상위 문서는 이 전달본 루트의 `README.md`입니다. 이 문서는 validator와 세부 전달 필드를 보충합니다.

## 물리적 경계

| 구분 | 구현 경로 | 대표 함수 | 상대 모델 import |
|---|---|---|---|
| Model A | `src/model_a/` | `src.model_a.run_model_a(a_input: dict) -> dict` | B를 import하지 않음 |
| Model B | `src/model_b/` | `src.model_b.run_model_b(b_input: dict) -> dict` | A·LightGBM·Surrogate·Adam을 import하지 않음 |
| 공통 계약 | `src/contracts/infrastructure_schemas.py` | 입력/출력 validator | 모델 구현을 import하지 않음 |
| 연결 예시 | `example_pipeline.py` | `run_one_a_b_a_exchange(a_input: dict) -> dict` | 순서만 조정하며 모델 로직 없음 |

`src/model_b/discriminator.py`의 `OriginalCode2Discriminator`는 원본 Code2 legacy/reference 비교용으로 유지한다. 현재 운영 wrapper에서 사용하는 scope-aligned 판별 경로는 `src/model_b/experimental_discriminator.py`에 있으며 이름은 호환성을 위해 유지한다. 현재 기준은 `EXECUTABLE_RULE_POLICY` expected_profit 대비 +3% 이상 개선 **AND** candidate waste_rate가 executable Rule waste target 이하인 경우다. `NO_DISCOUNT_BASELINE`은 진단·Replay·비교용이고 profit threshold 기준이 아니다. `options.discriminator_mode` 값은 기존 계약대로 `ORIGINAL_CODE2` 또는 `SCOPE_ALIGNED_EXPERIMENTAL`을 유지한다.

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
