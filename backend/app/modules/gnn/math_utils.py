"""Pure Python Vector & Matrix Math Utilities for GNNs.

Enables full deterministic GNN tensor computations with ZERO external
C-extension dependencies (pure Python / standard library).
"""

from __future__ import annotations

import math
import random


def dot(v1: list[float], v2: list[float]) -> float:
    """Compute dot product of two vectors."""
    return sum(x * y for x, y in zip(v1, v2, strict=False))


def norm(v: list[float]) -> float:
    """Compute L2 Euclidean norm of a vector."""
    return math.sqrt(sum(x * x for x in v))


def normalize(v: list[float], eps: float = 1e-9) -> list[float]:
    """L2 normalize a vector to unit length."""
    n = norm(v)
    denom = max(n, eps)
    return [x / denom for x in v]


def mat_vec_mul(M: list[list[float]], v: list[float]) -> list[float]:
    """Multiply matrix M (rows x cols) by vector v (cols) -> vector (rows)."""
    return [dot(row, v) for row in M]


def vec_mat_mul(v: list[float], M: list[list[float]]) -> list[float]:
    """Multiply vector v (rows) by matrix M (rows x cols) -> vector (cols).

    Equivalent to v^T M.
    """
    cols = len(M[0]) if M else 0
    res = [0.0] * cols
    for j in range(cols):
        res[j] = sum(v[i] * M[i][j] for i in range(len(v)))
    return res


def mat_mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """Multiply matrix A (rA x cA) by matrix B (cA x cB) -> matrix (rA x cB)."""
    rA = len(A)
    cA = len(A[0]) if rA > 0 else 0
    cB = len(B[0]) if B else 0

    res = [[0.0] * cB for _ in range(rA)]
    for i in range(rA):
        for j in range(cB):
            res[i][j] = sum(A[i][k] * B[k][j] for k in range(cA))
    return res


def softmax(logits: list[float]) -> list[float]:
    """Compute numerically stable softmax over a list of logits."""
    if not logits:
        return []
    max_l = max(logits)
    exp_l = [math.exp(x - max_l) for x in logits]
    sum_exp = sum(exp_l)
    denom = max(sum_exp, 1e-9)
    return [e / denom for e in exp_l]


def leaky_relu(x: float, alpha: float = 0.2) -> float:
    """Compute LeakyReLU activation."""
    return x if x > 0 else x * alpha


def elu(x: float) -> float:
    """Compute ELU activation."""
    return x if x > 0 else (math.exp(x) - 1.0)


def layer_norm(v: list[float], eps: float = 1e-6) -> list[float]:
    """Apply layer normalization to a feature vector (zero mean, unit variance)."""
    n = len(v)
    if n == 0:
        return []
    mean = sum(v) / n
    variance = sum((x - mean) ** 2 for x in v) / n
    std = math.sqrt(variance + eps)
    return [(x - mean) / std for x in v]


def random_matrix(
    rows: int,
    cols: int,
    seed: int = 42,
    std: float = 0.1,
) -> list[list[float]]:
    """Generate a deterministic pseudo-random weight matrix (Xavier-like initialization)."""
    rng = random.Random(seed)  # noqa: S311 - deterministic weight init, not crypto
    return [[rng.gauss(0.0, std) for _ in range(cols)] for _ in range(rows)]


def random_vector(
    dim: int,
    seed: int = 42,
    std: float = 0.1,
) -> list[float]:
    """Generate a deterministic pseudo-random vector."""
    rng = random.Random(seed)  # noqa: S311 - deterministic weight init, not crypto
    return [rng.gauss(0.0, std) for _ in range(dim)]
