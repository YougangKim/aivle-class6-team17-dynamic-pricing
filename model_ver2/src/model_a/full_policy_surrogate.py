"""Attention-based full-policy neural surrogate owned and trained by Model A."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterator

import numpy as np
import torch
from torch import nn

from src.model_a.replay_buffer import RealPolicyReplayBuffer, TARGET_KEYS


class TargetScaler:
    def __init__(self): self.mean = None; self.scale = None
    @property
    def fitted(self): return self.mean is not None
    def fit(self, y):
        array = np.asarray(y, np.float32); self.mean = array.mean(0); scale = array.std(0)
        self.scale = np.where(scale < 1e-6, 1.0, scale).astype(np.float32); return self
    def transform(self, y): return (np.asarray(y, np.float32) - self.mean) / self.scale
    def inverse_tensor(self, y):
        return y * torch.as_tensor(self.scale, dtype=y.dtype, device=y.device) + torch.as_tensor(self.mean, dtype=y.dtype, device=y.device)


class FullPolicySurrogate(nn.Module):
    """All five outputs depend on the jointly encoded 152-cell policy."""

    def __init__(self, feature_dim: int, embedding_dim=32, seed=42) -> None:
        super().__init__(); torch.manual_seed(seed)
        self.feature_dim = int(feature_dim)
        self.cell_encoder = nn.Sequential(nn.Linear(feature_dim + 1, 64), nn.ReLU(), nn.Linear(64, embedding_dim), nn.ReLU())
        self.cell_attention = nn.MultiheadAttention(embedding_dim, num_heads=4, batch_first=True)
        self.head = nn.Sequential(nn.Linear(embedding_dim * 2, 64), nn.ReLU(), nn.Linear(64, len(TARGET_KEYS)))
        self.scaler = TargetScaler(); self.trained_updates = 0; self.training_metrics = {}

    @property
    def is_trained(self): return self.trained_updates > 0 and self.scaler.fitted

    def forward(self, state_tensor, policy_matrix, active_mask):
        if state_tensor.ndim != 4 or tuple(state_tensor.shape[1:3]) != (38, 4) or state_tensor.shape[-1] != self.feature_dim:
            raise ValueError(f"state_tensor must be [batch,38,4,{self.feature_dim}]")
        if policy_matrix.ndim != 3 or tuple(policy_matrix.shape[1:]) != (38, 4) or active_mask.shape != policy_matrix.shape:
            raise ValueError("policy_matrix and active_mask must be [batch,38,4]")
        batch = state_tensor.shape[0]
        state = state_tensor.reshape(batch, 152, self.feature_dim)
        policy = policy_matrix.reshape(batch, 152, 1)
        mask = active_mask.reshape(batch, 152).bool()
        # MultiheadAttention cannot consume a row whose every key is padded.
        # Pooling still uses the original mask, so this safety key contributes zero.
        attention_mask = mask.clone()
        empty_rows = ~attention_mask.any(1)
        if empty_rows.any():
            attention_mask[empty_rows, 0] = True
        embedding = self.cell_encoder(torch.cat([state, policy], -1))
        attended, _ = self.cell_attention(embedding, embedding, embedding, key_padding_mask=~attention_mask, need_weights=False)
        embedding = embedding + attended
        mask_f = mask.unsqueeze(-1).to(embedding.dtype)
        mean = (embedding * mask_f).sum(1) / mask_f.sum(1).clamp_min(1.0)
        maximum = embedding.masked_fill(~mask.unsqueeze(-1), torch.finfo(embedding.dtype).min).max(1).values
        maximum = torch.where(mask.any(1, keepdim=True), maximum, torch.zeros_like(maximum))
        return self.head(torch.cat([mean, maximum], 1))

    def predict_raw_tensor(self, state_tensor, policy_matrix, active_mask):
        if not self.is_trained: raise RuntimeError("Full-policy surrogate is not trained")
        return self.scaler.inverse_tensor(self(state_tensor, policy_matrix, active_mask))

    def train_from_replay(self, replay: RealPolicyReplayBuffer, epochs=50, learning_rate=0.003, validation_fraction=0.2, seed=42, device="cpu"):
        if not replay.can_train: return []
        states, policies, masks, targets = replay.arrays(); self.scaler.fit(targets)
        standardized = self.scaler.transform(targets); rng = np.random.default_rng(seed)
        order = rng.permutation(len(targets)); val_n = max(1, int(round(len(targets) * validation_fraction)))
        val_idx, train_idx = order[:val_n], order[val_n:]
        if not len(train_idx): train_idx = val_idx
        surrogate_optimizer = torch.optim.Adam(self.parameters(), lr=learning_rate)
        history = []; self.to(device)
        for epoch in range(1, int(epochs) + 1):
            self.train(); surrogate_optimizer.zero_grad(set_to_none=True)
            pred = self(torch.as_tensor(states[train_idx], dtype=torch.float32, device=device), torch.as_tensor(policies[train_idx], dtype=torch.float32, device=device), torch.as_tensor(masks[train_idx], dtype=torch.bool, device=device))
            target = torch.as_tensor(standardized[train_idx], dtype=torch.float32, device=device)
            per_target = nn.functional.huber_loss(pred, target, reduction="none").mean(0)
            loss = per_target.mean(); loss.backward(); nn.utils.clip_grad_norm_(self.parameters(), 5.0); surrogate_optimizer.step()
            self.eval()
            with torch.no_grad():
                val_pred = self(torch.as_tensor(states[val_idx], dtype=torch.float32, device=device), torch.as_tensor(policies[val_idx], dtype=torch.float32, device=device), torch.as_tensor(masks[val_idx], dtype=torch.bool, device=device))
                val_target = torch.as_tensor(standardized[val_idx], dtype=torch.float32, device=device)
                val_per = nn.functional.huber_loss(val_pred, val_target, reduction="none").mean(0)
            row = {"epoch": epoch, "total_train_loss": float(per_target.mean().detach()), "total_validation_loss": float(val_per.mean().detach()), "learning_rate": learning_rate, "sample_count": len(targets)}
            row.update({f"train_loss_{key}": float(value) for key, value in zip(TARGET_KEYS, per_target.detach().cpu())})
            row.update({f"validation_loss_{key}": float(value) for key, value in zip(TARGET_KEYS, val_per.detach().cpu())})
            history.append(row)
        self.trained_updates += 1; self.eval()
        with torch.no_grad():
            raw_prediction = self.scaler.inverse_tensor(self(torch.as_tensor(states, dtype=torch.float32), torch.as_tensor(policies, dtype=torch.float32), torch.as_tensor(masks, dtype=torch.bool))).cpu().numpy()
        mae = np.abs(raw_prediction - targets).mean(0); rmse = np.sqrt(np.square(raw_prediction - targets).mean(0))
        self.training_metrics = {
            "model_status": "TRAINED", "sample_count": len(targets), "real_b_sample_count": len(targets),
            "test_double_sample_count": 0, "total_train_loss": history[-1]["total_train_loss"],
            "total_validation_loss": history[-1]["total_validation_loss"],
            "target_mae": {key: float(v) for key, v in zip(TARGET_KEYS, mae)},
            "target_rmse": {key: float(v) for key, v in zip(TARGET_KEYS, rmse)},
        }
        return history

    @contextmanager
    def frozen(self) -> Iterator[None]:
        flags = [p.requires_grad for p in self.parameters()]
        try:
            for p in self.parameters(): p.requires_grad_(False)
            self.eval(); yield
        finally:
            for p, flag in zip(self.parameters(), flags): p.requires_grad_(flag)

    def save(self, artifact_dir: str | Path, feature_names):
        if not self.is_trained: raise RuntimeError("Refusing to save an untrained surrogate")
        out = Path(artifact_dir); out.mkdir(parents=True, exist_ok=True)
        torch.save({"state_dict": self.state_dict(), "feature_dim": self.feature_dim, "trained_updates": self.trained_updates}, out / "full_policy_surrogate.pt")
        np.savez(out / "surrogate_target_scaler.npz", mean=self.scaler.mean, scale=self.scaler.scale)
        (out / "surrogate_input_schema.json").write_text(json.dumps({"state_tensor": ["batch",38,4,self.feature_dim], "policy_matrix":["batch",38,4], "active_mask":["batch",38,4], "features":list(feature_names), "targets":list(TARGET_KEYS)}, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "surrogate_training_metrics.json").write_text(json.dumps(self.training_metrics, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
