#!/usr/bin/env python3
"""Scrape GitHub trending repositories."""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict

GITHUB_TRENDING_URL = "https://github.com/trending"


def fetch_trending(language: str = "", since: str = "daily") -> List[Dict]:
    """Fetch trending GitHub repositories."""
    params = {"since": since}
    if language:
        params["spoken_language_code"] = language

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    response = requests.get(GITHUB_TRENDING_URL, params=params, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    repos = []

    for idx, article in enumerate(soup.find_all("article", class_="Box-row"), 1):
        try:
            link = article.find("h2", class_="h3").find("a")
            repo_name = link.get_text(strip=True)
            repo_url = "https://github.com" + link["href"]

            desc_elem = article.find("p", class_="col-9")
            description = desc_elem.get_text(strip=True) if desc_elem else None

            lang_elem = article.find("span", itemprop="programmingLanguage")
            language = lang_elem.get_text(strip=True) if lang_elem else None

            stars_elem = article.find("span", class_="d-inline-block float-sm-right")
            stars = None
            if stars_elem:
                stars_text = stars_elem.get_text(strip=True)
                stars = int(stars_text.replace(",", ""))

            repos.append({
                "repo_name": repo_name,
                "url": repo_url,
                "description": description,
                "language": language,
                "stars": stars,
                "rank": idx,
            })
        except Exception as e:
            print(f"Error parsing repo: {e}")
            continue

    return repos


if __name__ == "__main__":
    repos = fetch_trending(since="daily")
    print(f"Collected {len(repos)} trending repos")
    for repo in repos[:5]:
        print(f"  {repo['rank']}. {repo['repo_name']} ({repo['stars']} stars)")
