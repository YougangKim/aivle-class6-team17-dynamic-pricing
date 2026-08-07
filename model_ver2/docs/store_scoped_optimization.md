# 점포별 할인정책 최적화

## 운영 단위

한 번의 최적화는 `점포 1개 × 의사결정 시각 1개 × 상품 38개 × DTE 4개`다. S01/S02/S03는 서로 다른 request, A session, B session, Replay Buffer, 상태 tensor로 실행하며 456셀을 한 모델 입력으로 합치지 않는다.

```python
from src.pipeline import optimize_discount_policy

result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-12-31T18:00:00+09:00",
    current_state={"source": "OPERATING_SYSTEM_CURRENT_STATE", "cells": [...]},
)
```

3개 점포 집계는 독립 단일점포 함수를 세 번 호출한다.

```python
from src.pipeline import optimize_all_store_policies

result = optimize_all_store_policies(
    current_time="2025-12-31T18:00:00+09:00",
    current_states={"S01": state_1, "S02": state_2, "S03": state_3},
)
```

## 점포별 실행 순서

1. 전체 0% `(38,4)` 정책을 실제 B로 평가한다.
2. 결과를 `baseline`에 저장하고 Replay Buffer에는 `iteration=0`, `policy_source=NO_DISCOUNT_BASELINE`으로 한 번 저장한다.
3. 학습된 InitialPolicyLightGBM의 `(38,4)` 출력을 iteration 1 후보로 실제 B에 전달한다.
4. 실제 B 결과로 Full-policy Surrogate와 Adam 반복을 수행한다.
5. 통과 정책의 3회 연속 수렴을 확인하고 통과 pool의 실제 B 이익 최고 정책을 선택한다.

0% baseline은 초기정책, warm-up 후보, passed-policy pool에 넣지 않는다. 정상 운영은 `LIGHTGBM/TRAINED`가 필요하다. 현재 artifact는 통과 라벨 부족으로 `NOT_TRAINED`이므로 명시적 fallback 없는 운영 호출은 실패한다.

## B 평가 범위

운영 함수는 `SCOPE_ALIGNED_EXPERIMENTAL` B 판별기를 명시한다. A가 threshold를 계산하지 않는다. A와 B 모두 `data/store_calendar.csv`의 해당 점포·날짜 행을 사용하며 B가 `현재 시각~close_hour-1`을 전체 정책으로 평가하고 판정한다.

## 2026-08-07 실제 검증

명시적 구조검증 fallback으로 2025-12-31 18시를 실행했다.

| 점포 | B 범위 | baseline 이익 | 최종 후보 이익 | B 평가 | 통과 |
|---|---|---:|---:|---:|---:|
| S01 | 18:00~22:59 | -95,561.76 | -126,317.57 | 6 | 0 |
| S02 | 18:00~21:59 | 56,753.96 | 41,892.49 | 6 | 0 |
| S03 | 18:00~22:59 | -21,316.35 | -52,381.52 | 6 | 0 |

각 점포 152행, 합계 456행을 저장했다. 동일 상품·DTE 중 33개 셀에서 점포별 최종 할인율이 달랐다. 이 실행은 `CURRENT_POLICY` fallback 구조검증이며 LightGBM 운영 성능이 아니다.

결과: `outputs/runtime/three_store_validation/store_discount_policy_long.csv`
