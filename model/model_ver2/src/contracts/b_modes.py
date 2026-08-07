"""Shared, dependency-neutral B discriminator mode contracts."""

from __future__ import annotations


ORIGINAL_CODE2 = "ORIGINAL_CODE2"
SCOPE_ALIGNED_EXPERIMENTAL = "SCOPE_ALIGNED_EXPERIMENTAL"

REAL_B_BACKEND = "REAL_B"
EXPERIMENTAL_BACKEND = "REAL_B_SIMULATION_SCOPE_ALIGNED_THRESHOLD"

REAL_B_MODEL_VERSION = "delivered-code2-runtime-v1"
EXPERIMENTAL_B_MODEL_VERSION = "delivered-code2-runtime-v1+scope-abs-margin-threshold-exp-v2"

SUPPORTED_DISCRIMINATOR_MODES = (ORIGINAL_CODE2, SCOPE_ALIGNED_EXPERIMENTAL)


def backend_for_mode(mode: str) -> str:
    normalized = str(mode).upper()
    if normalized == ORIGINAL_CODE2:
        return REAL_B_BACKEND
    if normalized == SCOPE_ALIGNED_EXPERIMENTAL:
        return EXPERIMENTAL_BACKEND
    raise ValueError(f"Unsupported discriminator_mode: {mode}")


def model_version_for_mode(mode: str) -> str:
    normalized = str(mode).upper()
    if normalized == ORIGINAL_CODE2:
        return REAL_B_MODEL_VERSION
    if normalized == SCOPE_ALIGNED_EXPERIMENTAL:
        return EXPERIMENTAL_B_MODEL_VERSION
    raise ValueError(f"Unsupported discriminator_mode: {mode}")


def validate_backend_version(backend: str, model_version: str) -> bool:
    return (str(backend), str(model_version)) in {
        (REAL_B_BACKEND, REAL_B_MODEL_VERSION),
        (EXPERIMENTAL_BACKEND, EXPERIMENTAL_B_MODEL_VERSION),
    }
