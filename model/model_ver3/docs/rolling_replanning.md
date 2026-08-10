# Rolling replanning

`run_rolling_replan()` and `optimize_discount_policy(..., rolling_enabled=True)`
implement store-scoped receding-horizon rolling replanning. At each decision
timestamp they use the newest inventory state to evaluate the remaining
store-to-close performance, then re-optimize the one currently executable
`38 x 4` product-by-DTE policy.

They do **not** optimize or publish an entire hourly discount time series in
advance.

The flow is:

```text
current state
-> latest earlier published policy from the store timestamp ledger
-> A optimization with the prior policy as a projection lower bound
-> FINAL_RELEASE executable constraints and 1%p rounding
-> actual B evaluate_policy() on that exact matrix
-> executable-Rule discriminator
-> publish only when threshold_pass=True
-> full ISO-8601 timestamp ledger record
```

`previous_discount_rate` is optional and accepts either a rate (`0.30`) or a
percentage (`30`). It may be one rate or a `[38, 4]` matrix. The schema
normalizes it once; the ledger's previous published matrix is authoritative
after the first successful publication.

For every active cell, A's optimizer projection enforces the executable form
of:

```text
previous published discount <= optimized discount <= current policy_caps
```

Inactive cells remain zero. If a previous published rate exceeds a newly
calculated cap, the rolling request is rejected and recorded as a safe hold;
it never silently lowers the previous discount or posts an infeasible policy.

The JSON ledger is stored under `outputs/runtime/rolling_policy_ledger.json`
by default. Its keys are `store_id` and the complete decision timestamp, so
`13:00`, `13:10`, and `13:20` are distinct records. Calling the same store and
timestamp again returns the recorded result idempotently.
