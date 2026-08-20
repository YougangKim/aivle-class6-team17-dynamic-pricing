# Fresh Food Dynamic Discount Optimization

신선식품의 재고 상태와 판매 환경을 바탕으로 **상품별 할인율 후보를 생성하고, 예상 이익과 폐기 수준을 반복 평가하여 최종 할인 후보를 선택하는 동적 할인 최적화 프로젝트**입니다.

점포별 최신 상태를 입력받아 **38개 상품 × 4개 유통기한 잔여 구간(총 152개 셀)**의 할인율을 계산하며, 점포별로 독립적인 최적화를 수행합니다.

---

## 1. 주요 기능

- 점포별 최신 재고 및 상품 상태 기반 할인 후보 생성
- LightGBM을 이용한 초기 할인 후보 생성
- B 시뮬레이션을 통한 예상 수요·매출·이익·폐기 평가
- B 평가 결과를 학습하는 신경망 기반 반복 최적화
- Adam optimizer를 이용한 할인율 개선
- 할인율 범위, 원가, 재고 상태 등을 반영한 제약조건 적용
- 판별 기준을 통과한 할인 후보만 최종 실행 후보로 반환
- 이전 게시 할인율을 고려한 실시간 재계획 지원
- S01, S02, S03 점포별 독립 최적화 지원

---

## 2. 전체 처리 흐름

```text
최신 재고 / 점포 상태 입력
        ↓
상태 데이터 구성
        ↓
LightGBM 초기 할인 후보 생성
        ↓
B 시뮬레이션 평가
(예상 수요 / 판매량 / 매출 / 이익 / 폐기 계산)
        ↓
평가 결과 Replay Buffer 저장
        ↓
신경망 학습
        ↓
Adam 기반 할인 후보 개선
        ↓
제약조건 적용 후 B 재평가
        ↓
판별 기준 확인
        ↓
통과 후보 중 최종 후보 선택
미통과 시 기존 운영 정책 유지
```

신경망은 실제 B 평가 결과를 학습하여 다음 할인 후보를 개선하는 데 사용하며, **최종 후보의 실행 가능 여부는 실제 B 평가와 판별 결과를 기준으로 결정**합니다.

---

## 3. 모델 구성

### 3.1 초기 할인 후보 생성 - LightGBM

현재 재고, 가격, 상품 특성, 점포 특성, 시간 정보 등을 입력받아 각 상품의 초기 할인율을 생성합니다.

- 모델: LightGBM Regressor
- 출력: `38 × 4` 할인율 행렬
- 최대 할인율: 40%
- 학습 라벨: B 시뮬레이션과 좌표 단위 탐색을 통해 생성한 실행 가능한 할인율

학습된 모델 및 관련 파일:

```text
artifacts/model_a/
├─ initial_policy_lightgbm.txt
├─ initial_policy_artifact_status.json
├─ initial_policy_feature_schema.json
├─ initial_policy_mapping.json
└─ initial_policy_training_metrics.json
```

현재 저장된 LightGBM 검증 성능:

| 지표 | 결과 |
|---|---:|
| MAE | 약 0.13%p |
| 1%p 이내 예측 비율 | 약 95.4% |
| 3%p 이내 예측 비율 | 약 99.3% |

### 3.2 반복 최적화 - 신경망

B에서 실제로 평가한 할인 후보와 평가 결과를 Replay Buffer에 저장하고, 이를 이용해 **전체 할인 행렬과 B 평가 결과의 관계를 학습하는 신경망**을 업데이트합니다.

주요 입력:

- 현재 상태 텐서
- 할인율 행렬
- 활성 재고 여부

주요 예측 대상:

- 예상 수요
- 예상 판매량
- 예상 매출
- 예상 이익
- 예상 폐기량
- 예상 폐기율

신경망 모델 파일은 실행 중 충분한 B 평가 결과가 확보되어 학습이 수행되면 다음 위치에 생성됩니다.

```text
artifacts/model_a/full_policy_surrogate.pt
artifacts/model_a/surrogate_target_scaler.npz
```

### 3.3 할인 후보 개선 - Adam

학습된 신경망을 이용해 예상 이익이 증가하는 방향으로 할인율을 반복 조정합니다.

기본 설정:

| 항목 | 기본값 |
|---|---:|
| 최대 반복 횟수 | 30 |
| 반복당 Adam step | 10 |
| 할인율 학습률 | 0.02 |
| 수렴 확인 횟수 | 3 |
| 할인율 변화 허용치 | 0.01 |
| 최대 B 평가 횟수 | 24 |
| 최대 실행 시간 | 120초 |

---

## 4. 할인 제약조건

생성된 할인 후보에는 다음 제약조건을 적용합니다.

- 할인율 `0% ~ 40%` 범위 제한
- 상품별 최대 할인율 적용
- 원가 이하 판매 방지를 위한 할인 상한 적용
- 재고가 없는 셀의 할인율은 `0`
- 이전 게시 할인율이 있는 경우 해당 할인율보다 낮아지지 않도록 하한 적용 가능
- 반복 과정에서 셀별 할인율 변화폭 제한

---

## 5. B 평가 및 판별

B 영역에서는 전달받은 전체 할인 후보를 기준으로 판매 결과를 시뮬레이션하고 다음 지표를 계산합니다.

- `expected_demand`
- `expected_sales_qty`
- `expected_revenue`
- `expected_profit`
- `expected_waste_qty`
- `expected_waste_rate`

후보는 다음 조건을 모두 만족해야 실행 가능한 최종 후보로 인정됩니다.

```text
후보 예상이익 ≥ 기준 할인안 예상이익 + 3% × |기준 할인안 예상이익|
AND
후보 폐기율 ≤ 기준 할인안의 허용 폐기율
```

판별 기준을 통과한 후보가 있으면 `final_policy`로 반환하며, 통과 후보가 없으면 `NO_THRESHOLD_PASS` 상태로 종료하고 기존 운영 정책을 유지합니다.

---

## 6. 프로젝트 구조

최종 소스코드 기준 구조는 다음과 같습니다.

```text
model_final/
├─ artifacts/
│  ├─ b_runtime/
│  │  ├─ dte_index_mapping.json
│  │  ├─ params_customer_sim.json
│  │  ├─ params_discriminator.json
│  │  ├─ product_index_mapping.json
│  │  └─ sim_arrays.npz
│  │
│  └─ model_a/
│     ├─ initial_policy_artifact_status.json
│     ├─ initial_policy_feature_schema.json
│     ├─ initial_policy_lightgbm.txt
│     ├─ initial_policy_mapping.json
│     └─ initial_policy_training_metrics.json
│
├─ scripts/
│  ├─ bootstrap_labels_coordinate_ascent.py
│  └─ train_initial_policy_lightgbm.py
│
├─ src/
│  ├─ b_runtime/
│  │  ├─ artifact_loader.py
│  │  ├─ customer_simulator.py
│  │  ├─ discriminator.py
│  │  ├─ inventory_engine.py
│  │  └─ schemas.py
│  │
│  ├─ contracts/
│  │  ├─ b_modes.py
│  │  ├─ data_paths.py
│  │  ├─ discounts.py
│  │  ├─ executable_rule.py
│  │  ├─ infrastructure_schemas.py
│  │  ├─ mappings.py
│  │  ├─ schemas.py
│  │  ├─ serialization.py
│  │  └─ store_schedule.py
│  │
│  ├─ model_a/
│  │  ├─ api.py
│  │  ├─ candidate_generator.py
│  │  ├─ constraints.py
│  │  ├─ convergence.py
│  │  ├─ full_policy_surrogate.py
│  │  ├─ initial_policy_lightgbm.py
│  │  ├─ policy_optimizer.py
│  │  ├─ replay_buffer.py
│  │  ├─ service.py
│  │  └─ state_builder.py
│  │
│  ├─ model_b/
│  │  ├─ api.py
│  │  ├─ evaluator.py
│  │  ├─ experimental_discriminator.py
│  │  ├─ metrics_calculator.py
│  │  └─ service.py
│  │
│  └─ pipeline/
│     ├─ discount_optimization_pipeline.py
│     ├─ rolling_constraints.py
│     ├─ rolling_planner.py
│     └─ store_policy_service.py
│
├─ requirements.txt
└─ README.md
```

### 주요 디렉터리

| 경로 | 설명 |
|---|---|
| `src/model_a` | 초기 할인 후보 생성, 신경망 학습, Adam 기반 반복 최적화 |
| `src/model_b` | 할인 후보 시뮬레이션 평가 및 판별 |
| `src/b_runtime` | B 실행용 artifact 및 데이터 로딩, 고객·재고 시뮬레이션 |
| `src/pipeline` | A-B 반복 실행, 점포별 최적화, 실시간 재계획 |
| `src/contracts` | 입출력 스키마, 할인율 정규화, 매핑 및 직렬화 |
| `artifacts/model_a` | 초기 LightGBM 모델 및 학습 메타데이터 |
| `artifacts/b_runtime` | B 실행에 필요한 파라미터, 배열 및 인덱스 매핑 |
| `scripts` | LightGBM 학습용 라벨 생성 및 모델 학습 스크립트 |

---

## 7. 사용 데이터

데이터셋은 소스코드와 분리하여 관리합니다. 실행 시 다음 CSV 파일이 필요합니다.

```text
calendar.csv
inventory.csv
product.csv
store.csv
store_calendar.csv
store_visitor_profile.csv
```

기본적으로 프로젝트 루트의 `data/` 폴더를 참조하며, 데이터가 다른 위치에 있는 경우 환경변수 `MODEL_VER3_DATA_DIR`로 경로를 지정할 수 있습니다.

예시:

```bash
export MODEL_VER3_DATA_DIR=/path/to/data
```

Windows Git Bash 예시:

```bash
export MODEL_VER3_DATA_DIR="C:/path/to/data"
```

---

## 8. 설치

프로젝트 폴더에서 다음 명령을 실행합니다.

```bash
pip install -r requirements.txt
```

주요 라이브러리:

- NumPy
- Pandas
- scikit-learn
- PyTorch
- LightGBM

---

## 9. 실행 방법

### 9.1 점포 1개 최적화

운영 환경에서는 `optimize_discount_policy(...)`를 사용할 수 있습니다.

```python
from src.pipeline import optimize_discount_policy

result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-12-31T18:00:00+09:00",
    current_state={
        "source": "OPERATING_SYSTEM_CURRENT_STATE",
        "cells": []
    },
)
```

지원 점포:

```text
S01
S02
S03
```

각 점포는 독립적으로 `38 × 4 = 152개` 할인 셀을 최적화합니다.

### 9.2 전체 점포 실행

```python
from src.pipeline import optimize_all_store_policies

result = optimize_all_store_policies(
    current_time="2025-12-31T18:00:00+09:00",
    current_states={
        "S01": {"cells": []},
        "S02": {"cells": []},
        "S03": {"cells": []},
    },
)
```

3개 점포를 하나의 456셀 문제로 합치지 않고, **점포별 152셀 최적화를 각각 수행한 뒤 결과를 통합**합니다.

### 9.3 내부 Schema 1.0 요청 실행

이미 내부 요청 형식으로 구성된 데이터는 `run_discount_optimization(...)`으로 직접 실행할 수 있습니다.

```python
from src.pipeline import run_discount_optimization

result = run_discount_optimization(request)
```

요청에는 다음 기본 정보가 필요합니다.

```text
request_id
decision.store_id
decision.date
decision.hour
decision.decision_timestamp
schema_version = "1.0"
```

---

## 10. 주요 출력

최적화 결과에는 다음 정보가 포함됩니다.

```text
status
execution_eligible
baseline
initial_policy
final_policy
diagnostic_best_candidate
evaluation
optimization
training
comparison_to_no_discount
artifacts
model_metadata
warnings
```

판별 기준을 통과한 경우:

```text
status = SUCCESS
execution_eligible = true
```

통과한 할인 후보는 `final_policy`에 저장됩니다.

통과 후보가 없는 경우:

```text
status = NO_THRESHOLD_PASS
execution_eligible = false
```

이 경우 `final_policy`는 실행 후보로 사용되지 않으며 기존 운영 정책을 유지합니다.

---

## 11. 실행 결과 저장

기본 실행 결과는 `outputs/runtime/` 아래에 저장됩니다.

주요 생성 파일:

```text
discount_result.json
optimization_history.csv
policy_cell_history.csv
surrogate_training_history.csv
run.log
```

Replay Buffer는 요청별로 다음 경로에 저장됩니다.

```text
artifacts/replay_buffer/{request_id}/
```

점포 단위 실행 결과:

```text
outputs/runtime/stores/{store_id}/discount_result.json
```

전체 점포 실행 시에는 실행 시각별 폴더에 점포별 결과와 통합 결과가 저장됩니다.

---

## 12. 실시간 재계획

재고 및 판매 상태가 변경되면 최신 상태를 기준으로 할인율을 다시 계산할 수 있습니다.

`rolling_enabled=True`로 실행하면 이전 게시 할인율을 반영하여 새 할인 후보를 생성합니다.

```python
result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-12-31T18:10:00+09:00",
    current_state={"cells": []},
    rolling_enabled=True,
)
```

이전 게시 할인율이 전달되면 실행 가능한 범위 안에서 하한으로 적용하여, 이미 게시된 할인율이 다시 낮아지지 않도록 처리합니다.

---

## 13. 학습 스크립트

### LightGBM 학습용 할인율 생성

```bash
python scripts/bootstrap_labels_coordinate_ascent.py
```

B 평가와 좌표 단위 탐색을 이용해 LightGBM 학습에 사용할 할인율 데이터를 생성합니다.

학습/검증 기간:

```text
Train      : 2025-01-01 ~ 2025-09-30
Validation : 2025-10-01 ~ 2025-11-15
Test       : 2025-11-16 ~ 2025-12-31
```

Test 기간은 학습 및 튜닝에 사용하지 않습니다.

### LightGBM 학습

```bash
python scripts/train_initial_policy_lightgbm.py
```

학습된 모델과 관련 메타데이터는 `artifacts/model_a/`에 저장됩니다.

---

## 14. 주요 실행 진입점

| 함수 | 용도 |
|---|---|
| `optimize_discount_policy(...)` | 점포 1개 운영 최적화 |
| `optimize_all_store_policies(...)` | S01~S03 전체 점포 독립 최적화 후 통합 |
| `run_discount_optimization(...)` | Schema 1.0 기반 A-B 반복 최적화 |
| `run_rolling_replan(...)` | 이전 게시 할인율을 반영한 실시간 재계획 |
| `run_model_a(...)` | A 영역 단독 할인 후보 생성 |
| `run_model_b(...)` | B 영역 단독 할인 후보 평가 |

---

## 15. 참고

본 저장소의 소스코드와 데이터셋은 분리되어 있습니다. 실행 전 필요한 CSV 데이터 경로를 확인해야 하며, B 실행에 필요한 파라미터 및 시뮬레이션 artifact는 `artifacts/b_runtime/`에 포함되어 있습니다.
