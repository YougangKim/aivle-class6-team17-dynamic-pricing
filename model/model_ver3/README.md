# Fresh Food Dynamic Discount Optimization

신선식품의 재고 상태와 판매 환경을 바탕으로 **상품별 할인율 후보를 생성하고, 예상 이익과 폐기 수준을 반복 평가하여 최종 할인 후보를 선택하는 동적 할인 최적화 프로젝트**입니다.

본 프로젝트는 점포별 최신 상태를 입력받아 **38개 상품 × 4개 유통기한 잔여 구간(총 152개 셀)**의 할인율을 계산하며, 재고가 갱신될 때마다 다시 최적화할 수 있도록 구성되어 있습니다.

## 1. 주요 기능

* 점포별 최신 재고 및 상품 상태 기반 할인 후보 생성
* LightGBM을 이용한 초기 할인 후보 생성
* B 평가 결과를 학습하는 신경망 기반 반복 최적화
* Adam optimizer를 이용한 할인율 개선
* 예상 수요, 매출, 이익, 폐기량 및 폐기율 평가
* 판별 기준을 통과한 할인 후보만 최종 실행 후보로 반환
* 이전 게시 할인율을 고려한 실시간 재계획 지원
* S01, S02, S03 점포별 독립 최적화 지원

## 2. 전체 처리 흐름

```text
최신 재고 / 점포 상태 입력
        ↓
상태 데이터 구성
        ↓
LightGBM 초기 할인 후보 생성
        ↓
B 시뮬레이션 평가
(수요 / 매출 / 이익 / 폐기 계산)
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
통과 + 수렴 조건 만족 → 최종 할인 후보 반환
미통과 / 미수렴 → 반복 또는 기존 정책 유지
```

신경망은 B 평가 결과를 바탕으로 다음 할인 후보를 제안하며, **최종 후보의 채택 여부는 실제 B 평가 결과를 기준으로 결정**합니다.

## 3. 모델 구성

### 3.1 초기 할인 후보 생성 - LightGBM

현재 재고, 가격, 상품 특성, 점포 특성, 시간 정보 등을 입력받아 각 상품의 초기 할인율을 생성합니다.

* 모델: LightGBM Regressor
* 출력: `38 × 4` 할인율 행렬
* 할인율 범위: `0.00 ~ 0.40`
* 학습 데이터: B 시뮬레이션과 반복 탐색을 통해 생성한 할인율

학습 모델:

```text
artifacts/model_a/initial_policy_lightgbm.txt
```

현재 저장된 모델의 검증 성능:

| 지표           |       결과 |
| ------------ | -------: |
| MAE          | 약 0.13%p |
| 1%p 이내 예측 비율 |  약 95.4% |
| 3%p 이내 예측 비율 |  약 99.3% |

### 3.2 반복 최적화 - 신경망

B에서 실제로 평가한 할인 후보와 평가 결과를 Replay Buffer에 저장하고, 이를 이용해 **전체 할인 행렬과 B 평가 결과의 관계를 학습하는 신경망**을 업데이트합니다.

주요 입력:

* 현재 상태 텐서
* 할인율 행렬
* 활성 재고 여부

주요 예측 대상:

* 예상 수요
* 예상 판매량
* 예상 매출
* 예상 이익
* 예상 폐기량
* 예상 폐기율

학습된 신경망:

```text
artifacts/model_a/full_policy_surrogate.pt
```

### 3.3 할인 후보 개선 - Adam

학습된 신경망을 이용해 예상 이익이 증가하는 방향으로 할인율을 조정합니다.

기본 설정:

| 항목            |  기본값 |
| ------------- | ---: |
| 최대 반복 횟수      |   30 |
| 반복당 Adam step |   10 |
| 학습률           | 0.02 |
| 수렴 확인 횟수      |    3 |
| 할인율 변화 허용치    | 0.01 |
| 최대 B 평가 횟수    |   24 |
| 최대 실행 시간      | 120초 |

## 4. 할인 제약조건

생성된 할인 후보에는 다음 제약조건을 적용합니다.

* 할인율 `0% ~ 40%` 범위 제한
* 상품별 최대 할인율 적용
* 원가 이하 판매 방지를 위한 할인 상한 적용
* 재고가 없는 셀의 할인율은 `0`
* 이전 게시 할인율보다 낮아지지 않도록 하한 적용 가능
* 반복 1회당 할인율 변화폭 제한

## 5. B 평가 및 판별

B 영역에서는 전달받은 할인 후보를 기준으로 판매 결과를 시뮬레이션하고 다음 지표를 계산합니다.

* `expected_demand`
* `expected_sales_qty`
* `expected_revenue`
* `expected_profit`
* `expected_waste_qty`
* `waste_rate`

평가 후 판별기에서 후보의 실행 가능 여부를 확인합니다.

```text
후보 이익이 기준 할인안 대비 요구 수준 이상 개선
AND
후보 폐기율이 허용 폐기 기준 이하
```

판별 기준을 통과한 후보만 `final_policy`로 반환되며, 통과 후보가 없으면 기존 운영 정책을 유지합니다.

## 6. 프로젝트 구조

```text
model_ver3/
├─ artifacts/
│  ├─ b_runtime/
│  │  ├─ dte_index_mapping.json
│  │  ├─ product_index_mapping.json
│  │  ├─ no_discount_policy.npy
│  │  ├─ rule_policy.npy
│  │  └─ runtime_manifest.json
│  └─ model_a/
│     ├─ initial_policy_lightgbm.txt
│     ├─ initial_policy_training_metrics.json
│     ├─ initial_policy_feature_schema.json
│     ├─ initial_policy_mapping.json
│     ├─ full_policy_surrogate.pt
│     ├─ surrogate_input_schema.json
│     ├─ surrogate_target_scaler.npz
│     └─ model_metadata.json
│
├─ data/
│  ├─ calendar.csv
│  ├─ inventory.csv
│  ├─ product.csv
│  ├─ store.csv
│  ├─ store_calendar.csv
│  ├─ store_visitor_profile.csv
│  └─ sample_infrastructure_input.json
│
├─ docs/
│  ├─ infrastructure_api_contract.md
│  └─ rolling_replanning.md
│
├─ external/
│  └─ b_original/
│     ├─ code2_package/
│     └─ nb1_results/
│
├─ scripts/
│  ├─ bootstrap_labels_coordinate_ascent.py
│  └─ train_initial_policy_lightgbm.py
│
├─ src/
│  ├─ b_runtime/
│  ├─ contracts/
│  ├─ model_a/
│  ├─ model_b/
│  └─ pipeline/
│
├─ tests/
│  └─ test_rolling_replanning.py
│
├─ example_pipeline.py
├─ requirements.txt
└─ README.md
```

### 주요 디렉터리

| 경로                    | 설명                           |
| --------------------- | ---------------------------- |
| `src/model_a`         | 초기 할인 후보 생성, 신경망 학습, 반복 최적화  |
| `src/model_b`         | 할인 후보 시뮬레이션 평가 및 판별          |
| `src/b_runtime`       | B 실행에 필요한 데이터 로딩 및 평가 로직     |
| `src/pipeline`        | A-B 반복 실행 및 점포별 운영 흐름        |
| `src/contracts`       | 입출력 스키마, 매핑 및 직렬화            |
| `artifacts/model_a`   | 학습된 LightGBM 및 신경망 파일        |
| `artifacts/b_runtime` | B 실행용 매핑 및 기준 정책 파일          |
| `data`                | 프로젝트 입력 데이터                  |
| `scripts`             | 학습 데이터 생성 및 LightGBM 학습 스크립트 |

## 7. 사용 데이터

| 파일                          | 주요 용도                   |
| --------------------------- | ----------------------- |
| `inventory.csv`             | 상품별 재고, 판매 상태 및 할인 정보   |
| `product.csv`               | 상품 가격, 원가, 유통기한 및 상품 특성 |
| `store.csv`                 | 점포별 기본 특성               |
| `calendar.csv`              | 날짜, 요일, 휴일 등 달력 정보      |
| `store_calendar.csv`        | 점포별 일자 운영 정보            |
| `store_visitor_profile.csv` | 점포별 방문 관련 특성            |

## 8. 설치

저장소 루트에서 다음 명령을 실행합니다.

```bash
pip install -r requirements.txt
```

주요 라이브러리:

* NumPy
* Pandas
* scikit-learn
* LightGBM
* PyTorch
* PyArrow
* PyTest

테스트 실행:

```bash
python -m pytest tests -q
```

## 9. 실행 방법

### 9.1 A → B → A 연결 예제

인프라 형식의 샘플 입력:

```text
data/sample_infrastructure_input.json
```

실행:

```bash
python example_pipeline.py
```

실행 흐름:

```text
Model A 할인 후보 생성
        ↓
Model B 평가
        ↓
B 평가 결과 전달
        ↓
Model A 다음 할인 후보 생성
```

### 9.2 점포 1개 최적화

운영 환경에서는 `optimize_discount_policy(...)`를 사용합니다.

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

### 9.3 전체 점포 실행

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

3개 점포를 하나의 문제로 합치지 않고 **점포별 152셀 최적화를 각각 수행한 뒤 결과를 통합**합니다.

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
model_metadata
warnings
```

판별 기준을 통과한 경우:

```text
status = SUCCESS
execution_eligible = true
```

통과한 최종 할인 후보는 `final_policy`에 저장됩니다.

통과 후보가 없는 경우:

```text
status = NO_THRESHOLD_PASS
execution_eligible = false
```

이 경우 새 할인 후보를 게시하지 않고 기존 정책을 유지합니다.

## 11. 결과 저장

기본 실행 결과는 다음 경로에 저장됩니다.

```text
outputs/runtime/
```

주요 생성 파일:

```text
discount_result.json
optimization_history.csv
policy_cell_history.parquet
surrogate_training_history.csv
run.log
```

점포 단위 실행 결과:

```text
outputs/runtime/stores/{store_id}/discount_result.json
```

## 12. 실시간 재계획

재고 및 판매 상태가 변경되면 최신 상태를 기준으로 할인율을 다시 계산할 수 있습니다.

`rolling_enabled=True`로 실행하면 이전에 게시된 할인율을 고려하여 새 할인 후보를 생성합니다.

```python
result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-12-31T18:10:00+09:00",
    current_state={"cells": []},
    rolling_enabled=True,
)
```

실시간 재계획에서는 이전 ESL 할인율을 하한으로 적용하여 이미 적용된 할인율이 다시 낮아지는 것을 방지합니다.

## 13. 학습 스크립트

### 초기 학습용 할인율 생성

```bash
python scripts/bootstrap_labels_coordinate_ascent.py
```

B 평가 결과를 이용해 LightGBM 학습에 사용할 초기 할인율 데이터를 생성합니다.

### LightGBM 학습

```bash
python scripts/train_initial_policy_lightgbm.py
```

학습된 모델과 관련 메타데이터는 `artifacts/model_a/`에 저장됩니다.

## 14. 주요 실행 진입점

| 함수                                 | 용도                       |
| ---------------------------------- | ------------------------ |
| `optimize_discount_policy(...)`    | 점포 1개 운영 최적화             |
| `optimize_all_store_policies(...)` | S01~S03 전체 점포 최적화        |
| `run_discount_optimization(...)`   | 내부 schema 1.0 기반 A-B 최적화 |
| `run_model_a(...)`                 | A 단독 할인 후보 생성            |
| `run_model_b(...)`                 | B 단독 할인 후보 평가            |

인프라 연동 시에는 일반적으로 `optimize_discount_policy(...)`를 사용합니다.

`run_discount_optimization(...)`은 이미 내부 schema `1.0` 형식으로 변환된 요청을 직접 처리할 때 사용하며, `data/sample_infrastructure_input.json`을 그대로 전달하지 않습니다.

## 15. 참고 문서

세부 인프라 연동 규격과 실시간 재계획 방식은 다음 문서를 참고합니다.

```text
docs/infrastructure_api_contract.md
docs/rolling_replanning.md
```
