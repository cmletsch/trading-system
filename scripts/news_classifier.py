"""
News fetcher and classifier.
Fetches recent headlines for a ticker via yfinance and classifies
into one of 7 categories using keyword matching.
"""

import os
import requests
from datetime import date, timedelta
from config import NEWS_KEYWORDS, NEWS_SCORES

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")


def fetch_news(ticker: str) -> list[dict]:
    """Fetch recent news headlines via FMP."""
    if not FINNHUB_KEY:
        return []
    try:
        from fmp_client import fetch_news_fmp
        return fetch_news_fmp(ticker)
    except Exception:
        return []


def classify_news(headlines: list[dict]) -> tuple[str, str]:
    """
    Classify news into one of 7 categories.
    Returns (category, top_headline).
    Category is the highest-scoring match, or '' if no match.
    """
    if not headlines:
        return "", ""

    # Score each category against all headlines
    cat_scores = {cat: 0 for cat in NEWS_KEYWORDS}
    for item in headlines:
        text = item["text"]
        for cat, keywords in NEWS_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    cat_scores[cat] += 1

    # Pick the category with most keyword hits
    best_cat = max(cat_scores, key=cat_scores.get)
    if cat_scores[best_cat] == 0:
        return "", headlines[0]["title"] if headlines else ""

    top_headline = headlines[0]["title"] if headlines else ""
    return best_cat, top_headline


def get_news_score(category: str) -> int:
    """Return the MDR score for a given news category."""
    return NEWS_SCORES.get(category, 0)


def analyze_ticker_news(ticker: str) -> dict:
    """
    Full pipeline: fetch + classify news for a ticker.
    Returns dict with category, headline, and MDR score.
    """
    headlines = fetch_news(ticker)
    category, headline = classify_news(headlines)
    score = get_news_score(category)
    return {
        "news":       headline,
        "news_type":  category,
        "news_score": score,
    }
