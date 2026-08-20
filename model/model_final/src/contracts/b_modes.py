"""Shared, dependency-neutral B discriminator mode contracts."""

from __future__ import annotations


SCOPE_ALIGNED_EXPERIMENTAL = "SCOPE_ALIGNED_EXPERIMENTAL"

EXPERIMENTAL_BACKEND = "REAL_B_SIMULATION_SCOPE_ALIGNED_THRESHOLD"

EXPERIMENTAL_B_MODEL_VERSION = "delivered-code2-runtime-v1+scope-aligned-operational-v1"

SUPPORTED_DISCRIMINATOR_MODES = (SCOPE_ALIGNED_EXPERIMENTAL,)


def backend_for_mode(mode: str) -> str:
    normalized = str(mode).upper()
    if normalized == SCOPE_ALIGNED_EXPERIMENTAL:
        return EXPERIMENTAL_BACKEND
    raise ValueError(f"Unsupported discriminator_mode: {mode}")


def model_version_for_mode(mode: str) -> str:
    normalized = str(mode).upper()
    if normalized == SCOPE_ALIGNED_EXPERIMENTAL:
        return EXPERIMENTAL_B_MODEL_VERSION
    raise ValueError(f"Unsupported discriminator_mode: {mode}")


def validate_backend_version(backend: str, model_version: str) -> bool:
    return (str(backend), str(model_version)) == (
        EXPERIMENTAL_BACKEND,
        EXPERIMENTAL_B_MODEL_VERSION,
    )
