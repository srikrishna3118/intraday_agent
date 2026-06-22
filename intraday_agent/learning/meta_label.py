"""Logistic meta-label filter: skip low-expectancy trades after ranker."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from intraday_agent.config import Config
from intraday_agent.learning.costs import apply_costs
from intraday_agent.learning.entry_features import build_entry_features, features_from_json
from intraday_agent.learning.journal import TradeJournal, TradeRecord
from intraday_agent.learning.metrics import summarize_trades
from intraday_agent.market_regime import MarketRegime
from intraday_agent.strategy import BaseStrategy, ScreenResult

logger = logging.getLogger(__name__)

NUMERIC_FEATURES = [
    "rsi",
    "volume_ratio",
    "adx",
    "atr_pct",
    "vix",
    "nifty_close",
    "nifty_ema",
    "minutes_from_open",
    "entry_hour",
    "day_of_week",
    "side_is_short",
    "symbol_code",
]

DEFAULT_MODEL_PATH = os.path.join(Config.DATA_DIR, "models", "meta_label.joblib")


def _side_is_short(side: str) -> float:
    return 1.0 if side.upper() == "SHORT" else 0.0


def _symbol_vocab(symbols: list[str]) -> dict[str, int]:
    uniq = sorted({s.upper() for s in symbols if s})
    return {sym: idx for idx, sym in enumerate(uniq)}


def _symbol_code(symbol: str | None, vocab: dict[str, int]) -> float:
    if not symbol:
        return -1.0
    return float(vocab.get(symbol.upper(), -1))


def trade_row_to_features(row: dict[str, Any], vocab: dict[str, int]) -> dict[str, float]:
    """Merge journal row + entry_features JSON into model feature dict."""
    feats = features_from_json(row.get("entry_features"))
    symbol = (feats.get("symbol") or row.get("symbol") or "").upper()
    side = (feats.get("side") or row.get("side") or "LONG").upper()
    return {
        "rsi": float(feats.get("rsi") if feats.get("rsi") is not None else row.get("entry_rsi") or 0),
        "volume_ratio": float(
            feats.get("volume_ratio")
            if feats.get("volume_ratio") is not None
            else row.get("volume_ratio") or 0
        ),
        "adx": float(feats["adx"]) if feats.get("adx") is not None else np.nan,
        "atr_pct": float(feats["atr_pct"]) if feats.get("atr_pct") is not None else np.nan,
        "vix": float(feats["vix"]) if feats.get("vix") is not None else np.nan,
        "nifty_close": float(feats["nifty_close"]) if feats.get("nifty_close") is not None else np.nan,
        "nifty_ema": float(feats["nifty_ema"]) if feats.get("nifty_ema") is not None else np.nan,
        "minutes_from_open": float(
            feats.get("minutes_from_open") if feats.get("minutes_from_open") is not None else np.nan
        ),
        "entry_hour": float(
            feats.get("entry_hour") if feats.get("entry_hour") is not None else row.get("entry_hour") or 0
        ),
        "day_of_week": float(
            feats.get("day_of_week") if feats.get("day_of_week") is not None else row.get("day_of_week") or 0
        ),
        "side_is_short": _side_is_short(side),
        "symbol_code": _symbol_code(symbol, vocab),
    }


def features_dict_to_vector(features: dict[str, Any], vocab: dict[str, int]) -> np.ndarray:
    side = (features.get("side") or "LONG").upper()
    row = {
        "rsi": features.get("rsi", 0),
        "volume_ratio": features.get("volume_ratio", 0),
        "adx": features.get("adx"),
        "atr_pct": features.get("atr_pct"),
        "vix": features.get("vix"),
        "nifty_close": features.get("nifty_close"),
        "nifty_ema": features.get("nifty_ema"),
        "minutes_from_open": features.get("minutes_from_open"),
        "entry_hour": features.get("entry_hour"),
        "day_of_week": features.get("day_of_week"),
        "side_is_short": _side_is_short(side),
        "symbol_code": _symbol_code(features.get("symbol"), vocab),
    }
    return np.array([[float(row.get(k, np.nan)) for k in NUMERIC_FEATURES]], dtype=float)


def build_dataset(
    journal: TradeJournal | None = None,
    *,
    source_filter: str | list[str] | None = None,
    min_trades: int = 0,
) -> pd.DataFrame:
    """Journal rows with numeric features and binary label (net profitable)."""
    journal = journal or TradeJournal()
    rows = journal.fetch_trades()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if source_filter:
        sources = {
            s.strip()
            for s in (source_filter if isinstance(source_filter, list) else source_filter.split(","))
            if s.strip()
        }
        df = df[df["source"].isin(sources)]

    if df.empty:
        return df

    df = apply_costs(df)
    df["label"] = (df["net_pnl_amount"] > 0).astype(int)
    vocab = _symbol_vocab(df["symbol"].astype(str).tolist())
    feat_rows = [trade_row_to_features(r, vocab) for r in df.to_dict("records")]
    feat_df = pd.DataFrame(feat_rows)[NUMERIC_FEATURES]
    overlap = [c for c in NUMERIC_FEATURES if c in df.columns]
    base = df.drop(columns=overlap, errors="ignore").reset_index(drop=True)
    out = pd.concat([base, feat_df], axis=1)
    out.attrs["symbol_vocab"] = vocab

    if min_trades and len(out) < min_trades:
        logger.warning("Dataset has %d rows (< min_trades=%d)", len(out), min_trades)
    return out


def train_meta_model(
    df: pd.DataFrame,
    *,
    C: float = 0.1,
    random_state: int = 42,
) -> tuple[Pipeline, dict[str, Any]]:
    """Train regularized logistic regression on feature matrix."""
    if df.empty or "label" not in df.columns:
        raise ValueError("Empty dataset or missing labels")

    vocab = df.attrs.get("symbol_vocab") or _symbol_vocab(df["symbol"].astype(str).tolist())
    x = df[NUMERIC_FEATURES].astype(float)
    y = df["label"].astype(int)
    if y.nunique() < 2:
        raise ValueError("Need both winning and losing trades to train meta-label model")

    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=0.0)),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=C, max_iter=1000, random_state=random_state)),
    ])
    pipeline.fit(x, y)
    meta = {
        "feature_names": NUMERIC_FEATURES,
        "symbol_vocab": vocab,
        "C": C,
        "train_samples": len(df),
        "positive_rate": round(float(y.mean()), 4),
        "trained_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return pipeline, meta


def save_meta_model(
    path: str,
    pipeline: Pipeline,
    meta: dict[str, Any],
) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"pipeline": pipeline, "meta": meta}
    joblib.dump(payload, path)
    logger.info("Saved meta-label model → %s (%d samples)", path, meta.get("train_samples", 0))
    return path


def load_meta_model(path: str | None = None) -> tuple[Pipeline | None, dict[str, Any]]:
    path = path or Config.META_LABEL_MODEL_PATH
    if not path or not os.path.isfile(path):
        return None, {}
    payload = joblib.load(path)
    if isinstance(payload, dict) and "pipeline" in payload:
        return payload["pipeline"], payload.get("meta", {})
    return payload, {}


def predict_proba_from_row(pipeline: Pipeline, row_feats: dict[str, float]) -> float:
    x = np.array([[float(row_feats.get(k, np.nan)) for k in NUMERIC_FEATURES]], dtype=float)
    proba = pipeline.predict_proba(x)[0]
    classes = list(getattr(pipeline.named_steps["clf"], "classes_", [0, 1]))
    pos_idx = classes.index(1) if 1 in classes else -1
    return float(proba[pos_idx])


def predict_proba(
    pipeline: Pipeline,
    features: dict[str, Any],
    vocab: dict[str, int],
) -> float:
    x = features_dict_to_vector(features, vocab)
    proba = pipeline.predict_proba(x)[0]
    classes = list(getattr(pipeline.named_steps["clf"], "classes_", [0, 1]))
    pos_idx = classes.index(1) if 1 in classes else -1
    return float(proba[pos_idx])


def _trade_records_from_pnls(pnls: list[float]) -> list[TradeRecord]:
    now = datetime.now()
    return [
        TradeRecord(
            symbol="X",
            side="SHORT",
            entry_rsi=50,
            volume_ratio=1,
            entry_time=now,
            exit_time=now,
            exit_reason="wf",
            pnl_pct=0,
            pnl_amount=p,
            source="wf",
        )
        for p in pnls
    ]


def _parse_exit_dt(value: str) -> datetime | pd.Timestamp:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return pd.NaT
    if getattr(dt, "tzinfo", None) is not None:
        return dt.tz_convert("Asia/Kolkata").tz_localize(None)
    return dt


def walk_forward_evaluate(
    df: pd.DataFrame,
    *,
    n_splits: int = 4,
    C: float = 0.1,
) -> dict[str, Any]:
    """Time-ordered walk-forward on journal exit times."""
    if df.empty:
        return {"error": "empty dataset", "pass": False}

    work = df.copy()
    work["exit_dt"] = work["exit_time"].astype(str).apply(_parse_exit_dt)
    work = work.dropna(subset=["exit_dt"]).sort_values("exit_dt").reset_index(drop=True)
    if len(work) < 20:
        return {"error": f"need >=20 trades, have {len(work)}", "pass": False}

    n_splits = max(2, min(n_splits, max(2, len(work) // 15)))
    fold_size = len(work) // (n_splits + 1)
    min_fold = 5 if len(work) < 80 else 10
    if fold_size < min_fold:
        n_splits = max(2, len(work) // (min_fold * 2))
        fold_size = len(work) // (n_splits + 1)
    if fold_size < min_fold:
        return {"error": "insufficient rows per fold", "pass": False}

    oos_probs: list[float] = []
    oos_pnls: list[float] = []
    folds: list[dict[str, Any]] = []

    for fold in range(n_splits):
        train_end = fold_size * (fold + 1)
        test_end = min(len(work), train_end + fold_size)
        train_df = work.iloc[:train_end].copy()
        test_df = work.iloc[train_end:test_end].copy()
        if len(train_df) < 10 or len(test_df) < 3:
            continue
        if train_df["label"].nunique() < 2:
            continue

        train_df.attrs["symbol_vocab"] = _symbol_vocab(train_df["symbol"].astype(str).tolist())
        pipeline, _ = train_meta_model(train_df, C=C)
        vocab = train_df.attrs["symbol_vocab"]
        probs = []
        for _, row in test_df.iterrows():
            feats = trade_row_to_features(row.to_dict(), vocab)
            probs.append(predict_proba_from_row(pipeline, feats))
        oos_probs.extend(probs)
        oos_pnls.extend(test_df["net_pnl_amount"].astype(float).tolist())
        folds.append({"fold": fold, "train": len(train_df), "test": len(test_df)})

    if not oos_probs:
        return {"error": "no valid folds", "pass": False}

    threshold = Config.META_LABEL_THRESHOLD
    kept = [i for i, p in enumerate(oos_probs) if p >= threshold]
    baseline_trades = len(oos_probs)
    kept_trades = len(kept)
    keep_ratio = kept_trades / baseline_trades if baseline_trades else 0.0

    filtered_pnl = sum(oos_pnls[i] for i in kept) if kept else 0.0
    baseline_pnl = sum(oos_pnls)
    all_stats = summarize_trades(_trade_records_from_pnls(oos_pnls))
    filt_stats = (
        summarize_trades(_trade_records_from_pnls([oos_pnls[i] for i in kept]))
        if kept
        else {"sharpe": 0.0, "net_pnl_rs": 0.0, "trades": 0}
    )

    return {
        "folds": folds,
        "baseline_trades": baseline_trades,
        "filtered_trades": kept_trades,
        "keep_ratio": round(keep_ratio, 3),
        "baseline_net_pnl_rs": round(baseline_pnl, 0),
        "filtered_net_pnl_rs": round(filtered_pnl, 0),
        "baseline_sharpe": all_stats.get("sharpe", 0),
        "filtered_sharpe": filt_stats.get("sharpe", 0),
        "threshold": threshold,
        "pass_keep_ratio": keep_ratio >= 0.30,
        "pass_sharpe": filt_stats.get("sharpe", 0) > all_stats.get("sharpe", 0),
        "pass": (
            keep_ratio >= 0.30
            and filt_stats.get("sharpe", 0) > all_stats.get("sharpe", 0)
            and filtered_pnl >= baseline_pnl * 0.9
        ),
    }


class MetaLabelFilter:
    """Optional gate: P(profitable) >= threshold after ranker."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        threshold: float | None = None,
        model_path: str | None = None,
    ) -> None:
        self.enabled = Config.META_LABEL_ENABLED if enabled is None else enabled
        self.threshold = threshold if threshold is not None else Config.META_LABEL_THRESHOLD
        self.model_path = model_path or Config.META_LABEL_MODEL_PATH
        self._pipeline: Pipeline | None = None
        self._vocab: dict[str, int] = {}
        if self.enabled:
            self._load()

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def _load(self) -> None:
        pipeline, meta = load_meta_model(self.model_path)
        if pipeline is None:
            logger.warning("Meta-label enabled but model missing: %s", self.model_path)
            self.enabled = False
            return
        self._pipeline = pipeline
        self._vocab = meta.get("symbol_vocab", {})
        logger.info(
            "Meta-label model loaded (%d train samples, threshold=%.2f)",
            meta.get("train_samples", 0),
            self.threshold,
        )

    def should_take(
        self,
        side: str,
        result: ScreenResult,
        strategy: BaseStrategy,
        slice_df,
        regime: MarketRegime | None,
        bar_dt: datetime,
    ) -> tuple[bool, float | None]:
        if not self.enabled or self._pipeline is None:
            return True, None

        features = build_entry_features(side, result, strategy, slice_df, regime, bar_dt)
        prob = predict_proba(self._pipeline, features, self._vocab)
        return prob >= self.threshold, prob

    def should_take_from_features(self, features: dict[str, Any]) -> tuple[bool, float | None]:
        if not self.enabled or self._pipeline is None:
            return True, None
        prob = predict_proba(self._pipeline, features, self._vocab)
        return prob >= self.threshold, prob
