"""SageMaker inference entry points for Model A only."""

import json

from src.model_a import run_model_a


def model_fn(model_dir):
    # Artifacts are loaded by the existing Model A implementation from this package.
    return run_model_a


def input_fn(request_body, content_type):
    if content_type != "application/json":
        raise ValueError(f"Unsupported content type: {content_type}")
    value = json.loads(request_body)
    if not isinstance(value, dict):
        raise ValueError("Model A input must be a JSON object")
    return value


def predict_fn(input_data, model):
    return model(input_data)


def output_fn(prediction, accept):
    if accept not in ("application/json", "*/*"):
        raise ValueError(f"Unsupported accept type: {accept}")
    return json.dumps(prediction, ensure_ascii=False), "application/json"
