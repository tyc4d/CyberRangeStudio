"""Budget ledger + guard. Every OpenAI call is recorded here and checked against the shared cap.

Design:
- One SQLite ledger (data/llm_ledger.db), shared by all callers in this process and persisted.
- Before a call: estimate its MAX possible cost (input est + max_output at conservative price).
  Refuse if current_spend + max_cost would exceed the hard cap.
- After a call: record actual token usage * conservative price.
- Cost is a conservative ESTIMATE, never a provider invoice.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass

from app import config


class BudgetExceeded(RuntimeError):
    pass


_LOCK = threading.Lock()
_DB = config.DATA_DIR / "llm_ledger.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB, timeout=30)
    c.execute(
        """CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, purpose TEXT, model TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            est_cost_usd REAL, cached INTEGER DEFAULT 0, agent TEXT
        )"""
    )
    return c


def _est_input_tokens(text: str) -> int:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = config.price_for(model)
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


@dataclass
class Spend:
    total: float
    calls: int


def current_spend() -> Spend:
    with _LOCK, _conn() as c:
        row = c.execute("SELECT COALESCE(SUM(est_cost_usd),0), COUNT(*) FROM ledger").fetchone()
    return Spend(total=round(row[0], 6), calls=row[1])


def check_can_spend(model: str, est_input_text: str, max_output_tokens: int,
                    tier: str = "task") -> float:
    """Raise BudgetExceeded if this call could push spend past the cap. Returns the max cost."""
    in_tok = _est_input_tokens(est_input_text)
    max_cost = estimate_cost(model, in_tok, max_output_tokens)
    spent = current_spend().total
    if tier == "batch" and spent >= config.BUDGET_STOP_BATCH_USD:
        raise BudgetExceeded(
            f"batch/research halted: spend ${spent:.2f} >= stop-batch ${config.BUDGET_STOP_BATCH_USD}"
        )
    if spent >= config.BUDGET_STOP_NEW_USD:
        raise BudgetExceeded(
            f"no new paid tasks: spend ${spent:.2f} >= stop-new ${config.BUDGET_STOP_NEW_USD}"
        )
    if spent + max_cost > config.BUDGET_HARD_CAP_USD:
        raise BudgetExceeded(
            f"would exceed hard cap: spend ${spent:.2f} + est max ${max_cost:.4f} > ${config.BUDGET_HARD_CAP_USD}"
        )
    return max_cost


def record(purpose: str, model: str, input_tokens: int, output_tokens: int,
           cached: bool = False, agent: str = "") -> float:
    cost = 0.0 if cached else estimate_cost(model, input_tokens, output_tokens)
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO ledger(ts,purpose,model,input_tokens,output_tokens,est_cost_usd,cached,agent)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), purpose, model, input_tokens, output_tokens, cost, int(cached), agent),
        )
    return cost


def summary() -> dict:
    with _LOCK, _conn() as c:
        total, calls = c.execute("SELECT COALESCE(SUM(est_cost_usd),0), COUNT(*) FROM ledger").fetchone()
        by_model = c.execute(
            "SELECT model, COUNT(*), COALESCE(SUM(est_cost_usd),0), COALESCE(SUM(input_tokens),0),"
            " COALESCE(SUM(output_tokens),0) FROM ledger GROUP BY model ORDER BY 3 DESC"
        ).fetchall()
    return {
        "est_total_usd": round(total, 4),
        "calls": calls,
        "hard_cap_usd": config.BUDGET_HARD_CAP_USD,
        "stop_new_usd": config.BUDGET_STOP_NEW_USD,
        "note": "Conservative local estimate, not a provider invoice.",
        "by_model": [
            {"model": m, "calls": n, "est_cost_usd": round(cost, 4),
             "input_tokens": it, "output_tokens": ot}
            for (m, n, cost, it, ot) in by_model
        ],
    }
