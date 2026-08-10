# Fresh Food Dynamic Discount Optimization

- `src/model_a`: initial policy, replay buffer, full-policy surrogate, and Adam optimization
- `src/model_b`: REAL B policy evaluation and discriminator adapter
- `src/pipeline`: A-B orchestration and rolling replanning
- `src/contracts`: A/B schemas, mappings, and serialization
- `run_discount_optimization(...)`: low-level A-B integration function

## Setup

```powershell
pip install -r requirements.txt
python -m pytest tests -q
```

## Run entry points

### Infrastructure A/B exchange example

`data/sample_infrastructure_input.json` is an infrastructure envelope using
`store_id`, `current_time`, and `current_state`. Run the one-step A -> B -> A
example with:

```powershell
python example_pipeline.py
```

### Full optimization for one store

Use `src.pipeline.optimize_discount_policy(...)` for ordinary store operation.
It converts the infrastructure-style arguments into the internal runtime
request schema.

```python
from src.pipeline import optimize_discount_policy

result = optimize_discount_policy(
    store_id="S01",
    current_time="2025-10-05T12:00:00+09:00",
    current_state={"source": "PROJECT_DATA_SNAPSHOT", "cells": []},
)
```

### Low-level integration function

`run_discount_optimization(...)` accepts only an already converted internal
schema-version `1.0` runtime request containing `decision` and `state`.
Do not pass `data/sample_infrastructure_input.json` directly to this function:
that file uses the infrastructure envelope, not the internal runtime schema.

`data/` and `artifacts/` contain the files required by the current REAL B and
trained LightGBM/Surrogate runtime. Generated results are written under
`outputs/`, which is not a Git-tracked package input.

## Included documentation

- `docs/infrastructure_api_contract.md`: A/B and infrastructure contract
- `docs/rolling_replanning.md`: ESL lower bound and rolling ledger
