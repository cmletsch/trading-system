"""
news_classifier.py — News fetching and classification via FMP.
7 categories: CATALYST, OFFERING/DILUTION, PARTNERSHIP, EARNINGS,
              SEC/LEGAL, ANALYST, GENERAL
"""
from config import NEWS_KEYWORDS, NEWS_SCORES


def fetch_news(ticker: str) -> list[dict]:
    """Fetch recent news headlines via FMP."""
    try:
        from fmp_client import fetch_news_fmp
        return fetch_news_fmp(ticker)
    except Exception:
        return []


def classify_news(headlines: list[dict]) -> tuple[str, str]:
    """
    Classify a list of headlines into a news category.
    Returns (headline_str, category_str).
    """
    if not headlines:
        return "", ""

    combined = " ".join(h.get("text", "") for h in headlines).lower()
    best_cat   = ""
    best_score = 0

    for cat, keywords in NEWS_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > best_score:
            best_score = score
            best_cat   = cat

    top_headline = headlines[0].get("title", "") if headlines else ""
    return top_headline, best_cat


def analyze_ticker_news(ticker: str) -> dict:
    """Fetch and classify news for a ticker. Returns dict with news/news_type/news_score."""
    headlines = fetch_news(ticker)
    headline, category = classify_news(headlines)
    score = NEWS_SCORES.get(category, 0)
    return {
        "news":       headline,
        "news_type":  category,
        "news_score": score,
    }
