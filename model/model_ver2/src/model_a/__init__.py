"""Model A: initial LightGBM policy, neural surrogate, replay, and Adam optimization."""

from .initial_policy_lightgbm import InitialPolicyLightGBM, LightGBMNotTrainedError
from .api import run_model_a
from .candidate_generator import generate_discount_candidate
from .service import optimize_policy_with_surrogate, propose_initial_policy
from .state_builder import RuntimePolicyState, RuntimeStateBuilder

__all__ = ["InitialPolicyLightGBM", "LightGBMNotTrainedError", "RuntimePolicyState", "RuntimeStateBuilder", "generate_discount_candidate", "optimize_policy_with_surrogate", "propose_initial_policy", "run_model_a"]
