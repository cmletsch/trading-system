"""
finnhub_client.py — Candle data via yfinance (free, Yahoo Finance)
Used for nightly EOD candle analysis in GitHub Actions.
If yfinance is blocked, swap fetch_candles_polygon_2min to use FMP Premium.
"""
import time
import pandas as pd
import pytz
from datetime import date

ET       = pytz.timezone("America/New_York")
POLY_DELAY = 1.0   # 1 second between calls — gentle on Yahoo


def fetch_candles_polygon_2min(ticker: str, target_date: date) -> pd.DataFrame:
    """
    Fetch 1-min candles via yfinance, resample to 2-min, add MAs.
    Named 'polygon_2min' so run_analysis.py needs no changes.
    """
    try:
        import yfinance as yf

        date_str = target_date.strftime("%Y-%m-%d")

        # yfinance 1-min data: available for last 7 days only
        tk   = yf.Ticker(ticker)
        df_1 = tk.history(
            start=date_str,
            end=date_str,
            interval="1m",
            prepost=True,       # include pre/post market
            auto_adjust=True,
        )

        if df_1 is None or df_1.empty:
            return pd.DataFrame()

        # Normalise columns
        df_1 = df_1.rename(columns={
            "Open": "Open", "High": "High", "Low": "Low",
            "Close": "Close", "Volume": "Volume"
        })[["Open", "High", "Low", "Close", "Volume"]]

        # Ensure ET timezone
        if df_1.index.tzinfo is None:
            df_1.index = df_1.index.tz_localize("UTC").tz_convert(ET)
        else:
            df_1.index = df_1.index.tz_convert(ET)

        # Filter to target date only
        df_1 = df_1[df_1.index.date == target_date]
        if df_1.empty:
            return pd.DataFrame()

        # Resample to 2-min
        df_2 = df_1.resample("2min").agg({
            "Open": "first", "High": "max",
            "Low":  "min",   "Close": "last",
            "Volume": "sum",
        }).dropna(subset=["Open"])

        if len(df_2) < 5:
            return pd.DataFrame()

        df_2["MA20"]  = df_2["Close"].rolling(20).mean()
        df_2["MA200"] = df_2["Close"].rolling(200).mean()
        return df_2

    except Exception as e:
        print(f" [YF_ERR:{str(e)[:50]}]", end="")
        return pd.DataFrame()
