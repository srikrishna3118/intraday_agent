import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration for the intraday RSI+volume mean-reversion agent."""

    AGENT_MODE = os.getenv("AGENT_MODE", "equity").lower().strip()

    # Angel One SmartAPI
    ANGEL_API_KEY = os.getenv("ANGEL_API_KEY")
    ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID")
    ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD")
    ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET")

    # Execution
    LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() in ("1", "true", "yes", "y")
    ALLOW_SHORT = os.getenv("ALLOW_SHORT", "true").lower() in ("1", "true", "yes", "y")
    ALLOW_LONG = os.getenv("ALLOW_LONG", "true").lower() in ("1", "true", "yes", "y")

    # Strategy selection: rsi_mr | orb | vwap_pullback | rsi_div | ...
    STRATEGY = os.getenv("STRATEGY", "rsi_mr").lower().strip()

    # F&O research strategy surface (paper-first, separate from equity STRATEGY)
    FNO_STRATEGY = os.getenv("FNO_STRATEGY", "time_based_straddle").lower().strip()
    _FNO_STRATEGIES_RAW = os.getenv(
        "FNO_STRATEGIES",
        "time_based_straddle,ema920_credit_spread,ema920_option_buy,"
        "premium_orb_short,expiry_vol_strangle",
    )
    FNO_STRATEGIES = tuple(
        part.strip().lower() for part in _FNO_STRATEGIES_RAW.split(",") if part.strip()
    ) or (FNO_STRATEGY,)
    FNO_UNDERLYING = os.getenv("FNO_UNDERLYING", "NIFTY").upper().strip()
    FNO_WEEKLY_ONLY = os.getenv("FNO_WEEKLY_ONLY", "false").lower() in (
        "1", "true", "yes", "y",
    )
    FNO_LOTS = int(os.getenv("FNO_LOTS", "1"))
    FNO_HEDGE_WING_POINTS = float(os.getenv("FNO_HEDGE_WING_POINTS", "200"))
    FNO_ENTRY_TIMES = os.getenv("FNO_ENTRY_TIMES", "09:20")
    FNO_EXIT_TIME = os.getenv("FNO_EXIT_TIME", "15:10")
    FNO_ENTRY_CUTOFF = os.getenv("FNO_ENTRY_CUTOFF", "14:30")
    FNO_LEG_STOP_LOSS_PCT = float(os.getenv("FNO_LEG_STOP_LOSS_PCT", "20"))
    FNO_COMBINED_STOP_LOSS_PCT = float(os.getenv("FNO_COMBINED_STOP_LOSS_PCT", "0"))
    FNO_MAX_MARGIN_UTILIZATION_PCT = float(os.getenv("FNO_MAX_MARGIN_UTILIZATION_PCT", "60"))
    FNO_CHECK_INTERVAL_SEC = int(os.getenv("FNO_CHECK_INTERVAL_SEC", "15"))
    FNO_CAPITAL = float(os.getenv("FNO_CAPITAL", "200000"))
    FNO_DEFINED_RISK_ONLY = os.getenv("FNO_DEFINED_RISK_ONLY", "true").lower() in (
        "1", "true", "yes", "y",
    )
    FNO_MAX_POSITIONS_PER_STRATEGY = int(os.getenv("FNO_MAX_POSITIONS_PER_STRATEGY", "1"))
    FNO_MAX_DAILY_LOSS = float(os.getenv("FNO_MAX_DAILY_LOSS", "20000"))
    FNO_BROKERAGE_PER_ORDER = float(os.getenv("FNO_BROKERAGE_PER_ORDER", "20"))
    FNO_SLIPPAGE_PCT = float(os.getenv("FNO_SLIPPAGE_PCT", "0.25"))
    FNO_OPEN_POSITIONS_PATH = os.getenv(
        "FNO_OPEN_POSITIONS_PATH",
        os.path.join(os.getenv("DATA_DIR", "data"), "fno_open_positions.json"),
    )

    # EMA 9:20 arms
    FNO_EMA_ENTRY_TIME = os.getenv("FNO_EMA_ENTRY_TIME", "09:20")
    FNO_EMA_FAST = int(os.getenv("FNO_EMA_FAST", "9"))
    FNO_EMA_SLOW = int(os.getenv("FNO_EMA_SLOW", "21"))
    FNO_BUY_PREMIUM_TARGET = float(os.getenv("FNO_BUY_PREMIUM_TARGET", "200"))
    FNO_BUY_STOP_PCT = float(os.getenv("FNO_BUY_STOP_PCT", "20"))

    # Premium-range short
    FNO_ORB_PICK_TIME = os.getenv("FNO_ORB_PICK_TIME", "09:16")
    FNO_ORB_PREMIUM_TARGET = float(os.getenv("FNO_ORB_PREMIUM_TARGET", "200"))
    FNO_ORB_RANGE_END = os.getenv("FNO_ORB_RANGE_END", "11:15")

    # Expiry-day remaining-vol strangle
    FNO_EXPIRY_ENTRY_TIME = os.getenv("FNO_EXPIRY_ENTRY_TIME", "11:00")
    FNO_EXPIRY_EXIT_TIME = os.getenv("FNO_EXPIRY_EXIT_TIME", "14:30")
    FNO_EXPIRY_TAIL_PROB = float(os.getenv("FNO_EXPIRY_TAIL_PROB", "0.10"))
    FNO_EXPIRY_MIN_DISTANCE_PCT = float(os.getenv("FNO_EXPIRY_MIN_DISTANCE_PCT", "0.4"))
    FNO_EXPIRY_STOP_PCT = float(os.getenv("FNO_EXPIRY_STOP_PCT", "50"))
    FNO_EXPIRY_MODEL_PATH = os.getenv(
        "FNO_EXPIRY_MODEL_PATH",
        os.path.join(os.getenv("DATA_DIR", "data"), "models", "fno_expiry_vol.json"),
    )

    # Daily capture / IV snapshots
    FNO_CAPTURE_ON_EXIT = os.getenv("FNO_CAPTURE_ON_EXIT", "true").lower() in (
        "1", "true", "yes", "y",
    )
    FNO_CAPTURE_STRIKE_BUFFER = float(os.getenv("FNO_CAPTURE_STRIKE_BUFFER", "400"))
    FNO_IV_SNAPSHOT_MIN = int(os.getenv("FNO_IV_SNAPSHOT_MIN", "15"))
    FNO_CANDLE_STORE_DIR = os.getenv("FNO_CANDLE_STORE_DIR", "data/candles_fno")

    # Opening range breakout (STRATEGY=orb)
    ORB_MINUTES = int(os.getenv("ORB_MINUTES", "15"))
    ORB_VOLUME_MULT = float(os.getenv("ORB_VOLUME_MULT", "1.2"))
    ORB_STOP_MODE = os.getenv("ORB_STOP_MODE", "range").lower().strip()
    ORB_USE_RSI_EXIT = os.getenv("ORB_USE_RSI_EXIT", "true").lower() in (
        "1", "true", "yes", "y",
    )
    ORB_TARGET_R_MULT = float(os.getenv("ORB_TARGET_R_MULT", "1.5"))

    # VWAP pullback (STRATEGY=vwap_pullback)
    VWAP_PULLBACK_TOUCH_PCT = float(os.getenv("VWAP_PULLBACK_TOUCH_PCT", "0.15"))
    VWAP_PULLBACK_REQUIRE_SLOPE = os.getenv(
        "VWAP_PULLBACK_REQUIRE_SLOPE", "false",
    ).lower() in ("1", "true", "yes", "y")
    VWAP_PULLBACK_SLOPE_BARS = int(os.getenv("VWAP_PULLBACK_SLOPE_BARS", "3"))

    # Position sizing & limits
    CAPITAL_PER_TRADE = float(os.getenv("CAPITAL_PER_TRADE", "25000"))
    MAX_QUANTITY = int(os.getenv("MAX_QUANTITY", "100"))
    MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "3"))

    # RSI strategy
    RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
    RSI_OVERBOUGHT = float(os.getenv("RSI_OVERBOUGHT", "80"))
    RSI_OVERSOLD = float(os.getenv("RSI_OVERSOLD", "30"))
    RSI_EXIT = float(os.getenv("RSI_EXIT", "50"))

    # Volume confirmation
    VOLUME_MA_LEN = int(os.getenv("VOLUME_MA_LEN", "20"))
    VOLUME_MA_MULT = float(os.getenv("VOLUME_MA_MULT", "1.0"))
    VOLUME_MA_MAX_MULT = float(os.getenv("VOLUME_MA_MAX_MULT", "2.0"))

    # ADX entry gate (0 = disabled; band: ADX_MR_MIN <= adx < ADX_MR_MAX)
    ADX_PERIOD = int(os.getenv("ADX_PERIOD", "14"))
    ADX_MR_MIN = float(os.getenv("ADX_MR_MIN", "0"))
    ADX_MR_MAX = float(os.getenv("ADX_MR_MAX", "0"))

    # Relative-strength mean reversion (STRATEGY=rs_mr)
    RSI_FAST_PERIOD = int(os.getenv("RSI_FAST_PERIOD", "2"))
    RSI_FAST_OVERSOLD = float(os.getenv("RSI_FAST_OVERSOLD", "15"))
    RS_MR_MIN_DAY_CHANGE = float(os.getenv("RS_MR_MIN_DAY_CHANGE", "2.0"))
    RS_MR_MAX_DAY_CHANGE = float(os.getenv("RS_MR_MAX_DAY_CHANGE", "5.0"))
    RS_MR_PULLBACK_ATR_MIN = float(os.getenv("RS_MR_PULLBACK_ATR_MIN", "0.5"))
    RS_MR_PULLBACK_ATR_MAX = float(os.getenv("RS_MR_PULLBACK_ATR_MAX", "1.0"))
    RS_MR_REQUIRE_BULLISH = os.getenv("RS_MR_REQUIRE_BULLISH", "true").lower() in (
        "1", "true", "yes", "y",
    )

    # VWAP mean reversion — fade distance from VWAP (STRATEGY=vwap_mr)
    VWAP_MR_MIN_DIST = float(os.getenv("VWAP_MR_MIN_DIST", "0.8"))
    VWAP_MR_RSI_OVERSOLD = float(os.getenv("VWAP_MR_RSI_OVERSOLD", "30"))
    VWAP_MR_USE_VWAP_TARGET = os.getenv("VWAP_MR_USE_VWAP_TARGET", "true").lower() in (
        "1", "true", "yes", "y",
    )

    # RSI divergence (STRATEGY=rsi_div) — Pine RSI Divergence Indicator port
    RSI_DIV_PERIOD = int(os.getenv("RSI_DIV_PERIOD", "9"))
    RSI_DIV_PIVOT_LEFT = int(os.getenv("RSI_DIV_PIVOT_LEFT", "1"))
    RSI_DIV_PIVOT_RIGHT = int(os.getenv("RSI_DIV_PIVOT_RIGHT", "3"))
    RSI_DIV_RANGE_LOWER = int(os.getenv("RSI_DIV_RANGE_LOWER", "5"))
    RSI_DIV_RANGE_UPPER = int(os.getenv("RSI_DIV_RANGE_UPPER", "60"))
    RSI_DIV_TP_RSI = float(os.getenv("RSI_DIV_TP_RSI", "80"))
    RSI_DIV_PLOT_BULL = os.getenv("RSI_DIV_PLOT_BULL", "true").lower() in (
        "1", "true", "yes", "y",
    )
    RSI_DIV_PLOT_HIDDEN_BULL = os.getenv("RSI_DIV_PLOT_HIDDEN_BULL", "true").lower() in (
        "1", "true", "yes", "y",
    )
    RSI_DIV_PLOT_BEAR = os.getenv("RSI_DIV_PLOT_BEAR", "true").lower() in (
        "1", "true", "yes", "y",
    )
    RSI_DIV_PLOT_HIDDEN_BEAR = os.getenv("RSI_DIV_PLOT_HIDDEN_BEAR", "false").lower() in (
        "1", "true", "yes", "y",
    )
    RSI_DIV_SL_TYPE = os.getenv("RSI_DIV_SL_TYPE", "NONE").upper().strip()
    RSI_DIV_STOP_LOSS_PCT = float(os.getenv("RSI_DIV_STOP_LOSS_PCT", "5"))
    RSI_DIV_ATR_LEN = int(os.getenv("RSI_DIV_ATR_LEN", "14"))
    RSI_DIV_ATR_MULT = float(os.getenv("RSI_DIV_ATR_MULT", "3.5"))

    # ZPayab DIY DMI confluence (STRATEGY=zp_dmi)
    ZP_DMI_DI_LEN = int(os.getenv("ZP_DMI_DI_LEN", "10"))
    ZP_DMI_ADX_LEN = int(os.getenv("ZP_DMI_ADX_LEN", "5"))
    ZP_DMI_ADX_MIN = float(os.getenv("ZP_DMI_ADX_MIN", "20"))
    ZP_RQK_H = float(os.getenv("ZP_RQK_H", "8"))
    ZP_RQK_R = float(os.getenv("ZP_RQK_R", "8"))
    ZP_RQK_X0 = int(os.getenv("ZP_RQK_X0", "25"))
    ZP_CE_LEN = int(os.getenv("ZP_CE_LEN", "22"))
    ZP_CE_MULT = float(os.getenv("ZP_CE_MULT", "3.0"))
    ZP_CE_USE_CLOSE = os.getenv("ZP_CE_USE_CLOSE", "true").lower() in (
        "1", "true", "yes", "y",
    )
    ZP_MACD_FAST = int(os.getenv("ZP_MACD_FAST", "12"))
    ZP_MACD_SLOW = int(os.getenv("ZP_MACD_SLOW", "26"))
    ZP_MACD_SIGNAL = int(os.getenv("ZP_MACD_SIGNAL", "9"))
    ZP_VOL_MA_LEN = int(os.getenv("ZP_VOL_MA_LEN", "20"))
    ZP_SIGNAL_EXPIRY = int(os.getenv("ZP_SIGNAL_EXPIRY", "3"))
    ZP_ALTERNATE_SIGNAL = os.getenv("ZP_ALTERNATE_SIGNAL", "true").lower() in (
        "1", "true", "yes", "y",
    )

    # ZPayab supply/demand S/R zones (POI group) — optional zp_dmi confirmation
    ZP_SD_FILTER_ENABLED = os.getenv("ZP_SD_FILTER_ENABLED", "false").lower() in (
        "1", "true", "yes", "y",
    )
    ZP_SD_SWING_LEN = int(os.getenv("ZP_SD_SWING_LEN", "10"))
    ZP_SD_HISTORY = int(os.getenv("ZP_SD_HISTORY", "20"))
    ZP_SD_BOX_WIDTH = float(os.getenv("ZP_SD_BOX_WIDTH", "2.5"))
    ZP_SD_ATR_LEN = int(os.getenv("ZP_SD_ATR_LEN", "50"))
    ZP_SD_TOUCH_PCT = float(os.getenv("ZP_SD_TOUCH_PCT", "0.35"))
    # at_zone: long at demand / short at supply | avoid: skip entries into opposite zone
    ZP_SD_FILTER_MODE = os.getenv("ZP_SD_FILTER_MODE", "avoid").lower().strip()

    # Zeiierman Volume SuperTrend AI (STRATEGY=vst_ai)
    VST_K = int(os.getenv("VST_K", "3"))
    VST_N = int(os.getenv("VST_N", "10"))
    VST_PRICE_LEN = int(os.getenv("VST_PRICE_LEN", "20"))
    VST_ST_LEN = int(os.getenv("VST_ST_LEN", "100"))
    VST_LEN = int(os.getenv("VST_LEN", "10"))
    VST_FACTOR = float(os.getenv("VST_FACTOR", "3.0"))
    VST_MA_SRC = os.getenv("VST_MA_SRC", "WMA").upper().strip()
    VST_AI_SIGNALS = os.getenv("VST_AI_SIGNALS", "true").lower() in (
        "1", "true", "yes", "y",
    )
    VST_ENTRY_MODE = os.getenv("VST_ENTRY_MODE", "both").lower().strip()
    VST_EXIT_ON_FLIP = os.getenv("VST_EXIT_ON_FLIP", "true").lower() in (
        "1", "true", "yes", "y",
    )

    # SBP Trend & Momentum (STRATEGY=sbp_tm) — research only
    SBP_TRADE_MODE = os.getenv("SBP_TRADE_MODE", "INTRADAY").upper().strip()
    SBP_TRAIL_ATR_MULT = float(os.getenv("SBP_TRAIL_ATR_MULT", "1.0"))
    SBP_USE_TRAIL_EXIT = os.getenv("SBP_USE_TRAIL_EXIT", "true").lower() in (
        "1", "true", "yes", "y",
    )
    SBP_MOMENTUM_MIN = float(os.getenv("SBP_MOMENTUM_MIN", "70"))

    # [Quadapt] Machine Learning Trader (STRATEGY=quadapt_ml)
    # Ports: Adaptive RQ MLMA + dual-length nonlinear envelopes + order-block context +
    #        signal quality filter.  Defaults match the Pine v6 indicator.
    # NOTE: min_bars = max(QUADAPT_WINDOW, QUADAPT_LEN1+20, …) ≈ 220.
    #       Set CANDLE_LOOKBACK=220 (or more) when using this strategy.
    # For 15-min intraday, consider LEN1=30, LEN2=14, WINDOW=60.
    QUADAPT_LEN1 = int(os.getenv("QUADAPT_LEN1", "30"))
    QUADAPT_LEN2 = int(os.getenv("QUADAPT_LEN2", "14"))
    QUADAPT_WINDOW = int(os.getenv("QUADAPT_WINDOW", "60"))
    QUADAPT_ATR_PERIOD = int(os.getenv("QUADAPT_ATR_PERIOD", "20"))
    QUADAPT_MULT = float(os.getenv("QUADAPT_MULT", "2.0"))
    QUADAPT_RQ_ALPHA = float(os.getenv("QUADAPT_RQ_ALPHA", "1.0"))
    QUADAPT_RQ_BANDWIDTH = float(os.getenv("QUADAPT_RQ_BANDWIDTH", "8.0"))
    QUADAPT_OB_VOL_LEN = int(os.getenv("QUADAPT_OB_VOL_LEN", "6"))
    QUADAPT_OB_SMOOTH_LEN = int(os.getenv("QUADAPT_OB_SMOOTH_LEN", "9"))
    QUADAPT_OB_MULT = float(os.getenv("QUADAPT_OB_MULT", "1.2"))
    QUADAPT_MIN_QUALITY = float(os.getenv("QUADAPT_MIN_QUALITY", "55.0"))
    QUADAPT_SIGNAL_MODE = os.getenv("QUADAPT_SIGNAL_MODE", "consensus").lower().strip()

    # Opening drive fade (STRATEGY=open_fade)
    OPEN_FADE_MIN_GAP = float(os.getenv("OPEN_FADE_MIN_GAP", "1.5"))
    OPEN_FADE_MIN_RSI = float(os.getenv("OPEN_FADE_MIN_RSI", "80"))
    OPEN_FADE_MIN_BODY_PCT = float(os.getenv("OPEN_FADE_MIN_BODY_PCT", "0.3"))
    OPEN_FADE_END_TIME = os.getenv("OPEN_FADE_END_TIME", "11:00")
    OPEN_FADE_VOLUME_MULT = float(os.getenv("OPEN_FADE_VOLUME_MULT", "1.2"))

    # Candles & timing
    CANDLE_INTERVAL = os.getenv("CANDLE_INTERVAL", "FIFTEEN_MINUTE")
    CANDLE_LOOKBACK = int(os.getenv("CANDLE_LOOKBACK", "100"))
    CANDLE_STORE_DIR = os.getenv("CANDLE_STORE_DIR", "data/candles")
    CANDLE_STORE_MAX_AGE_HOURS = int(os.getenv("CANDLE_STORE_MAX_AGE_HOURS", "24"))
    CANDLE_HISTORY_CHUNK_DAYS = int(os.getenv("CANDLE_HISTORY_CHUNK_DAYS", "150"))

    # Research/backtests: cache (local parquet) | angel (SmartAPI) | yahoo (~59d on 15m)
    RESEARCH_DATA_SOURCE = os.getenv("RESEARCH_DATA_SOURCE", "cache").lower().strip()
    # Parquet backend when RESEARCH_DATA_SOURCE=cache (where prefetch wrote files)
    CANDLE_CACHE_BACKEND = os.getenv("CANDLE_CACHE_BACKEND", "angel").lower().strip()
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "90"))
    SCREENER_INTERVAL_SEC = int(os.getenv("SCREENER_INTERVAL_SEC", "180"))
    SCREENER_BATCH_SIZE = int(os.getenv("SCREENER_BATCH_SIZE", "10"))
    REGIME_REFRESH_SEC = int(os.getenv("REGIME_REFRESH_SEC", "300"))
    API_RATE_LIMIT_PAUSE_SEC = int(os.getenv("API_RATE_LIMIT_PAUSE_SEC", "90"))
    API_RATE_LIMIT_PAUSE_MAX = int(os.getenv("API_RATE_LIMIT_PAUSE_MAX", "90"))
    # 0 = disabled; when >0, pause API_RECOVERY_PAUSE_SEC after this many consecutive limits
    API_RECOVERY_STREAK_THRESHOLD = int(os.getenv("API_RECOVERY_STREAK_THRESHOLD", "0"))
    API_RECOVERY_PAUSE_SEC = int(os.getenv("API_RECOVERY_PAUSE_SEC", "600"))
    SQUARE_OFF_TIME = os.getenv("SQUARE_OFF_TIME", "15:15")
    ENTRY_CUTOFF_TIME = os.getenv("ENTRY_CUTOFF_TIME", "14:00")
    # Naive candle datetimes: utc (Angel cache / research) | ist (Yahoo screener)
    CANDLE_NAIVE_TZ = os.getenv("CANDLE_NAIVE_TZ", "utc").lower().strip()
    EXCLUDED_SYMBOLS = frozenset(
        s.strip().upper()
        for s in os.getenv("EXCLUDED_SYMBOLS", "ONGC,SBIN,BAJFINANCE").split(",")
        if s.strip()
    )

    # Risk
    STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "1.5"))
    TARGET_PCT = float(os.getenv("TARGET_PCT", "2.5"))
    USE_ATR_EXITS = os.getenv("USE_ATR_EXITS", "true").lower() in ("1", "true", "yes", "y")
    ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
    ATR_STOP_MULT = float(os.getenv("ATR_STOP_MULT", "1.5"))
    ATR_TARGET_MULT = float(os.getenv("ATR_TARGET_MULT", "3.0"))
    # Exit after N completed bars if not in profit and RSI exit has not fired (0 = disabled)
    TIME_STOP_BARS = int(os.getenv("TIME_STOP_BARS", "0"))
    TRAILING_STOP_ENABLED = os.getenv("TRAILING_STOP_ENABLED", "false").lower() in (
        "1", "true", "yes", "y",
    )
    TRAILING_STOP_ATR_MULT = float(os.getenv("TRAILING_STOP_ATR_MULT", "1.0"))
    TRAILING_ACTIVATION_ATR_MULT = float(os.getenv("TRAILING_ACTIVATION_ATR_MULT", "1.0"))
    TRAILING_ACTIVATION_PCT = float(os.getenv("TRAILING_ACTIVATION_PCT", "0.5"))
    TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.8"))
    VWAP_FILTER_ENABLED = os.getenv("VWAP_FILTER_ENABLED", "true").lower() in ("1", "true", "yes", "y")
    VWAP_EXIT_ENABLED = os.getenv("VWAP_EXIT_ENABLED", "true").lower() in ("1", "true", "yes", "y")
    # MR short fade: require close above VWAP + min extension % (Sprint 5)
    VWAP_MR_FADE_SHORT = os.getenv("VWAP_MR_FADE_SHORT", "false").lower() in ("1", "true", "yes", "y")
    VWAP_MR_MIN_EXTENSION_PCT = float(os.getenv("VWAP_MR_MIN_EXTENSION_PCT", "0.3"))
    # Block entries when bar volume > mult × volume MA (0 = disabled)
    VOLUME_SURGE_BLOCK_MULT = float(os.getenv("VOLUME_SURGE_BLOCK_MULT", "0"))
    # Block shorts when RSI > N and volume/MA > M (CIPLA momentum-trap pattern; 0 = off)
    RSI_MOMENTUM_TRAP_RSI = float(os.getenv("RSI_MOMENTUM_TRAP_RSI", "0"))
    RSI_MOMENTUM_TRAP_VOLR = float(os.getenv("RSI_MOMENTUM_TRAP_VOLR", "0"))
    # Upper circuit proximity guard before short entry
    CIRCUIT_GUARD_ENABLED = os.getenv("CIRCUIT_GUARD_ENABLED", "true").lower() in (
        "1", "true", "yes", "y",
    )
    CIRCUIT_LIMIT_PCT = float(os.getenv("CIRCUIT_LIMIT_PCT", "20"))
    CIRCUIT_MIN_DISTANCE_PCT = float(os.getenv("CIRCUIT_MIN_DISTANCE_PCT", "2.0"))
    # nifty50 | nifty100 | t2 (30 liquid) | nifty200 (default) | nifty250 (legacy research)
    SCAN_UNIVERSE = os.getenv("SCAN_UNIVERSE", "nifty200").lower().strip()
    # Optional Telegram alerts
    ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").lower() in ("1", "true", "yes", "y")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    STREAM_ENABLED = os.getenv("STREAM_ENABLED", "false").lower() in ("1", "true", "yes", "y")

    # Classic pivot confluence (prior-session PP / R1–R3 / S1–S3)
    PIVOT_FILTER_ENABLED = os.getenv("PIVOT_FILTER_ENABLED", "false").lower() in (
        "1", "true", "yes", "y",
    )
    # MR fades: zone | proximity | both. Trend strategies use PP half either way.
    PIVOT_FILTER_MODE = os.getenv("PIVOT_FILTER_MODE", "proximity").lower().strip()
    PIVOT_TOUCH_PCT = float(os.getenv("PIVOT_TOUCH_PCT", "0.35"))
    REGIME_FILTER_ENABLED = os.getenv("REGIME_FILTER_ENABLED", "false").lower() in (
        "1", "true", "yes", "y",
    )
    VIX_MAX = float(os.getenv("VIX_MAX", "18"))
    NIFTY_REGIME_ENABLED = os.getenv("NIFTY_REGIME_ENABLED", "true").lower() in (
        "1", "true", "yes", "y",
    )
    NIFTY_EMA_PERIOD = int(os.getenv("NIFTY_EMA_PERIOD", "20"))

    # Anti-overtrading guards (0 = disabled)
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    MAX_TRADES_PER_SYMBOL = int(os.getenv("MAX_TRADES_PER_SYMBOL", "2"))
    SYMBOL_COOLDOWN_MIN = int(os.getenv("SYMBOL_COOLDOWN_MIN", "30"))
    LOSS_COOLDOWN_MIN = int(os.getenv("LOSS_COOLDOWN_MIN", "60"))
    MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "0"))
    MAX_DAILY_PROFIT = float(os.getenv("MAX_DAILY_PROFIT", "0"))

    # Exchange constants
    EXCHANGE_NSE = "NSE"
    PRODUCT_INTRADAY = "INTRADAY"
    ORDER_TYPE_MARKET = "MARKET"

    # Adaptive learning
    LEARNING_ENABLED = os.getenv("LEARNING_ENABLED", "false").lower() in ("1", "true", "yes", "y")
    LEARNING_MIN_TRADES = int(os.getenv("LEARNING_MIN_TRADES", "10"))
    LEARNING_SKIP_WIN_RATE = float(os.getenv("LEARNING_SKIP_WIN_RATE", "0.40"))
    LEARNING_SYMBOL_WEIGHT = float(os.getenv("LEARNING_SYMBOL_WEIGHT", "20"))
    LEARNING_LOOKBACK_DAYS = int(os.getenv("LEARNING_LOOKBACK_DAYS", "30"))

    # Paths
    DATA_DIR = os.getenv("DATA_DIR", "data")

    # Meta-label trade filter (logistic regression on journal labels)
    META_LABEL_ENABLED = os.getenv("META_LABEL_ENABLED", "false").lower() in ("1", "true", "yes", "y")
    META_LABEL_THRESHOLD = float(os.getenv("META_LABEL_THRESHOLD", "0.55"))
    META_LABEL_MODEL_PATH = os.getenv(
        "META_LABEL_MODEL_PATH",
        os.path.join(DATA_DIR, "models", "meta_label.joblib"),
    )
    INSTRUMENTS_CACHE = os.path.join(DATA_DIR, "instruments.json")
    TRADE_JOURNAL_PATH = os.path.join(DATA_DIR, "trade_journal.db")
    INSTRUMENTS_CACHE_MAX_AGE_HOURS = int(os.getenv("INSTRUMENTS_CACHE_MAX_AGE_HOURS", "24"))

    # Screener data: angel (SmartAPI getCandleData) | openchart (NSE charting API)
    SCREENER_DATA_SOURCE = os.getenv("SCREENER_DATA_SOURCE", "angel").lower().strip()
    # When openchart returns empty: none | cache | angel
    SCREENER_OPENCHART_FALLBACK = os.getenv(
        "SCREENER_OPENCHART_FALLBACK", "cache",
    ).lower().strip()

    # Screener rate limit (seconds between symbol candle requests)
    SCREENER_DELAY_SEC = float(os.getenv("SCREENER_DELAY_SEC", "1.0"))

    # Estimated Angel MIS cost per completed round-trip (0 = use formula from notional)
    ESTIMATED_COST_PER_TRADE = float(os.getenv("ESTIMATED_COST_PER_TRADE", "42"))

    # Risk-based position sizing
    # RISK_PCT > 0 enables: qty = (ACCOUNT_EQUITY * RISK_PCT%) / |entry - stop|
    # RISK_PCT = 0 (default) keeps legacy flat CAPITAL_PER_TRADE / price sizing.
    RISK_PCT = float(os.getenv("RISK_PCT", "0"))
    ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "500000"))

    # Regime-adaptive strategy switching
    # When true, Nifty ADX determines the active strategy at runtime:
    #   ADX >= REGIME_TREND_ADX_MIN  →  orb   (trend-following)
    #   ADX <= REGIME_RANGE_ADX_MAX  →  rsi_mr (mean-reversion)
    #   between                      →  no change (keep current STRATEGY)
    REGIME_ADAPTIVE = os.getenv("REGIME_ADAPTIVE", "false").lower() in ("1", "true", "yes", "y")
    REGIME_TREND_ADX_MIN = float(os.getenv("REGIME_TREND_ADX_MIN", "25"))
    REGIME_RANGE_ADX_MAX = float(os.getenv("REGIME_RANGE_ADX_MAX", "20"))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @staticmethod
    def validate():
        required = [
            "ANGEL_API_KEY",
            "ANGEL_CLIENT_ID",
            "ANGEL_PASSWORD",
            "ANGEL_TOTP_SECRET",
        ]
        missing = [name for name in required if not getattr(Config, name)]
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")
        return True
