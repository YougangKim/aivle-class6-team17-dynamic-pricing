CREATE TABLE IF NOT EXISTS pricing_ops.pricing_recommendation (
    request_id text PRIMARY KEY,
    store_id text NOT NULL,
    result_json jsonb NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'))
);

GRANT SELECT, INSERT, UPDATE ON pricing_ops.pricing_recommendation TO aivle_service;
