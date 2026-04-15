import logging
from datetime import datetime, timedelta
from typing import Dict
from urllib.parse import urlparse, parse_qs
from google_play_scraper import app as gp_app
from google_play_scraper import reviews as gp_reviews
from google_play_scraper import Sort
from schemas.models import ExtractedAppData

logger = logging.getLogger(__name__)


class PlayStoreExtractor:
    """Extracts app metadata from Google Play Store."""

    def __init__(self):
        self.review_window_days = 180
        self.max_reviews = 8

    def extract_app_id_from_url(self, url: str) -> str:
        """Extract app ID from Google Play URL."""
        if "id=" not in url:
            raise ValueError(f"No app ID found in URL: {url}")
        parsed = urlparse(url)
        return parse_qs(parsed.query)["id"][0]

    def _extract_via_google_play_scraper(self, app_id: str) -> Dict:
        data = gp_app(app_id, lang="en", country="us")

        cutoff = datetime.utcnow() - timedelta(days=self.review_window_days)

        # Pull a larger set and keep only strong + recent reviews.
        raw_reviews, _ = gp_reviews(
            app_id,
            lang="en",
            country="us",
            sort=Sort.RATING,
            count=100,
        )

        filtered_reviews = []
        for r in raw_reviews:
            score = int(r.get("score", 0) or 0)
            text = (r.get("content") or "").strip()
            review_at = r.get("at")

            if score < 4 or not text:
                continue

            # Keep only reviews from the last 6 months.
            if not isinstance(review_at, datetime):
                continue
            if review_at < cutoff:
                continue

            filtered_reviews.append(
                {
                    "rating": score,
                    "text": text[:350],
                    "reviewer": (r.get("userName") or "Anonymous").strip(),
                    "_at": review_at,
                }
            )

        # Highest stars first, then newest first.
        filtered_reviews.sort(
            key=lambda x: (
                x.get("rating", 0),
                x.get("_at") if isinstance(x.get("_at"), datetime) else datetime.min,
            ),
            reverse=True,
        )

        good_reviews = [
            {
                "rating": r["rating"],
                "text": r["text"],
                "reviewer": r["reviewer"],
                "date": r["_at"].date().isoformat() if isinstance(r.get("_at"), datetime) else None,
            }
            for r in filtered_reviews[: self.max_reviews]
        ]

        updated = data.get("updated")
        updated_str = str(updated) if updated is not None else None

        installs_value = data.get("realInstalls")
        if installs_value is None:
            installs_value = data.get("installs")
        installs_str = str(installs_value) if installs_value is not None else None

        return {
            "app_id": app_id,
            "app_name": data.get("title") or "Unknown",
            "short_description": data.get("summary") or "No description available",
            "full_description": data.get("description") or data.get("summary") or "No description available",
            "icon_url": data.get("icon") or "",
            "screenshots": (data.get("screenshots") or [])[:8],
            "rating": round(float(data.get("score")), 2) if data.get("score") is not None else None,
            "installs": installs_str,
            "reviews": good_reviews,
            "last_updated": updated_str,
            "current_version": data.get("version"),
            "min_android_version": None,
        }

    def extract(self, google_play_url: str) -> ExtractedAppData:
        """Extract app data from URL."""
        app_id = self.extract_app_id_from_url(google_play_url)
        logger.info(f"App ID: {app_id}")

        # Single extractor path per requested simplification.
        data = self._extract_via_google_play_scraper(app_id)
        
        app_data = ExtractedAppData(**data)
        logger.info(f"Extracted: {app_data.app_name}")
        return app_data


def extract_app_data(google_play_url: str) -> ExtractedAppData:
    """Extract app data from URL."""
    extractor = PlayStoreExtractor()
    return extractor.extract(google_play_url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_url = "https://play.google.com/store/apps/details?id=com.spotify.music"
    try:
        result = extract_app_data(test_url)
        print(result.model_dump_json(indent=2))
    except Exception as e:
        print(f"Error: {e}")
