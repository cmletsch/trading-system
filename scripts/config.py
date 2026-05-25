"""
Central configuration for the trading system.
All tunable parameters live here.
"""

# ── GOOGLE SHEETS ────────────────────────────────────────────────────────────
SHEET_TOP_GAINERS   = "TOP Gainers Data"
SHEET_MDR_TRACKING  = "MDR TRACKING"
SHEET_SCAN_LOG      = "SCAN LOG"

# ── ANALYSIS PARAMS (calibrated against 5/22/2026 template, 84% match) ──────
MA_SHORT            = 20       # 2-min bars
MA_LONG             = 200      # 2-min bars
AVG_LOOKBACK        = 20       # bars for rolling body/vol averages

MIN_BODY_MULT       = 1.5      # FGE: body >= 1.5x avg body
MAX_UPPER_RATIO     = 0.5      # FGE: upper tail < 50% of body
MAX_UPPER_RATIO_BLAST = 1.5    # relaxed for very large candles (>=4x)
LARGE_BODY_MULT     = 3.0      # body >= 3x avg → mid-candle entry
VERY_LARGE_MULT     = 4.0      # body >= 4x avg → blast tail + lowest vol threshold
ENTRY_FRACTION      = 0.65     # mid-candle entry = open + 0.65 x body
MAX_ENTRY_WAIT      = 5        # bars to find entry after FGE trigger
MIN_BODY_PCT        = 0.03     # fallback when avg_body=0: body >= 3% of open
GRACE_BARS          = 2        # consecutive bars below MA20 before run ends

# Volume multipliers by session
VOL_REG             = 1.5
VOL_PM              = 0.3
VOL_AH              = 0.5
VOL_VERY_LARGE      = 0.2      # when body >= VERY_LARGE_MULT x avg

# Run thresholds
MIN_RUN_PCT         = 9.5      # minimum % gain for a valid run
APLUS_PCT           = 25.0     # A+ gain threshold
APLUS_FGE_LEGS      = 3        # A+ FGE needs this many legs
BLAST_MAX_LEGS      = 1
FGE_MIN_LEGS        = 2

# Price rounding
PENNY_THRESHOLD     = 1.0      # prices < $1 use $0.005 step; >= $1 use $0.05 step

# State/Range thresholds
NARROW_MAX          = 0.15
MEDIUM_MAX          = 0.30

# Consolidation check
CONSOL_BARS         = 5        # prior bars to check consolidation
CONSOL_FACTOR       = 2.0      # prior range must be < 2x FGE body

# ── MDR SCORING ──────────────────────────────────────────────────────────────
MDR_LOOKBACK_DAYS   = 90       # how far back to count MDR days
MDR_MIN_DAYS        = 2        # minimum top-gainer days to qualify for watchlist

MDR_SCORE_DAYS = {
    "3+": 12,
    "2":   7,
}
MDR_SCORE_ESCALATING    = 12
MDR_SCORE_PRICE_GTE     = 8    # current price >= first entry
MDR_SCORE_DAY_CHANGE    = 5    # day change > 0
MDR_SCORE_RVOL = {
    5.0: 15,
    3.0: 12,
    2.0:  8,
    1.5:  4,
}
MDR_SCORE_GAP = {
    50: 15,
    30: 12,
    20:  9,
    10:  5,
}
MDR_SCORE_PATTERNS = {
    "Breakout":     18,
    "Consolidating": 8,
    "Holding":       5,
    "Fading":      -20,
    "Pulling":     -10,
}

# News scoring (7 categories)
NEWS_SCORES = {
    "FDA/CLINICAL":      15,
    "EARNINGS":          12,
    "CONTRACT/DEAL":     10,
    "M&A":               10,
    "MANAGEMENT":         0,
    "REGULATORY/LEGAL":  -5,
    "OFFERING/DILUTION": -15,
}

# MDR tier thresholds
MDR_TIER_STRONG_REGULAR   = 55
MDR_TIER_STRONG_EXTENDED  = 70   # pre/after hours
MDR_TIER_WATCH            = 45

# Hard overrides
MDR_OVERRIDE_DAY_LOSS     = -40   # down >= 40% today → score = 0
MDR_OVERRIDE_PRICE_PCT    = 0.40  # price < 40% of first entry → score = 0

# Timeout (days since last run → weakens, then removes)
MDR_TIMEOUT = {
    (2, 3):   (14, 30),
    (4, 6):   (18, 35),
    (7, 9):   (22, 40),
    (10, 999):(28, 45),
}

# Exclusion
MDR_EXCLUDE_PRICE         = 0.50  # below $0.50 for 10+ min → removed

# ── NEWS KEYWORDS ────────────────────────────────────────────────────────────
NEWS_KEYWORDS = {
    "FDA/CLINICAL": [
        "fda", "clinical", "trial", "phase", "drug", "approval", "ind",
        "nda", "bla", "anda", "510k", "breakthrough", "orphan", "pdufa",
        "efficacy", "safety", "dosing", "cohort", "endpoint",
    ],
    "EARNINGS": [
        "earnings", "revenue", "eps", "quarterly", "guidance", "results",
        "beat", "miss", "q1", "q2", "q3", "q4", "annual", "profit",
        "loss", "income", "fiscal", "outlook", "forecast",
    ],
    "CONTRACT/DEAL": [
        "contract", "partnership", "deal", "agreement", "awarded",
        "signed", "supply", "distribution", "license", "collaboration",
        "strategic", "mou", "loi", "grant",
    ],
    "M&A": [
        "merger", "acquisition", "acquires", "buyout", "takeover",
        "tender", "bid", "purchase", "combine", "merge",
    ],
    "OFFERING/DILUTION": [
        "offering", "dilution", "reverse split", "shelf", "atm",
        "warrant", "registered direct", "private placement", "prospectus",
        "common stock", "shares sold", "priced offering",
    ],
    "REGULATORY/LEGAL": [
        "sec", "lawsuit", "settlement", "investigation", "subpoena",
        "fine", "penalty", "complaint", "litigation", "regulatory",
        "compliance", "violation", "charges",
    ],
    "MANAGEMENT": [
        "ceo", "cfo", "coo", "cto", "appointed", "resigned", "director",
        "officer", "president", "chairman", "executive", "leadership",
        "board",
    ],
}

# ── YAHOO FINANCE TOP GAINERS ─────────────────────────────────────────────────
YF_GAINERS_COUNT    = 100      # how many top gainers to pull
YF_MIN_GAIN_PCT     = 10.0     # minimum % gain to include
YF_MIN_PRICE        = 0.10     # minimum price filter
YF_MAX_PRICE        = 50.00    # maximum price filter (focus on small caps)
