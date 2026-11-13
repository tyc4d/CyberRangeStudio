"""Central config. Reads from environment; never hardcodes secrets."""
from __future__ import annotations

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = API_DIR.parent.parent
DATA_DIR = Path(os.getenv("CR_DATA_DIR", API_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- OpenAI / budget ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Hard shared budget across ALL agents and experiments (USD).
BUDGET_HARD_CAP_USD = float(os.getenv("CR_BUDGET_HARD_CAP_USD", "50"))
BUDGET_STOP_NEW_USD = float(os.getenv("CR_BUDGET_STOP_NEW_USD", "45"))   # no new paid tasks past here
BUDGET_STOP_BATCH_USD = float(os.getenv("CR_BUDGET_STOP_BATCH_USD", "40"))  # no batch/research past here

# Conservative prices (USD per 1M tokens, input/output). Deliberately >= real list prices
# so the guard trips EARLY rather than late. Local estimate != provider invoice.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.30, 1.20),
    "gpt-4.1-mini": (0.80, 3.20),
    "gpt-4.1": (3.00, 12.00),
    "gpt-5-nano": (0.20, 1.60),
    "gpt-5-mini": (0.60, 4.00),
    "gpt-5": (2.50, 20.00),
    "gpt-5.1": (3.00, 15.00),
    "gpt-5.2": (3.00, 15.00),
}
# Unknown model => very high price so the guard is conservative.
DEFAULT_PRICE = (10.0, 40.0)

# Task-tier default models.
MODEL_CHEAP = os.getenv("CR_MODEL_CHEAP", "gpt-4.1-mini")   # parsing, formatting, small tasks
MODEL_STRONG = os.getenv("CR_MODEL_STRONG", "gpt-5.1")       # hard attack-behavior analysis

# Call limits
MAX_OUTPUT_TOKENS = int(os.getenv("CR_MAX_OUTPUT_TOKENS", "4000"))
MAX_RETRIES = int(os.getenv("CR_MAX_RETRIES", "2"))
MAX_CONCURRENCY = int(os.getenv("CR_MAX_CONCURRENCY", "3"))


def price_for(model: str) -> tuple[float, float]:
    for key, price in MODEL_PRICES.items():
        if model == key or model.startswith(key + "-"):
            return price
    return DEFAULT_PRICE
