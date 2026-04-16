import logging
import re
from typing import List
from schemas.models import ExtractedAppData, ContentStrategy, LandingPageContent
from agent.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


ICON_BY_BUCKET = {
    "music": ["AUDIO", "DISCOVER", "SPEED", "GLOBAL", "LIBRARY"],
    "gaming": ["PLAY", "BOOST", "WIN", "ACTION", "PRO"],
    "finance": ["GROWTH", "SECURE", "PAY", "TRUST", "INSIGHT"],
    "productivity": ["FOCUS", "FAST", "ORGANIZE", "MOBILE", "TEAM"],
    "default": ["VALUE", "FAST", "TRUST", "MOBILE", "QUALITY"],
}


def _bucket(strategy: ContentStrategy) -> str:
    return (strategy.style_guide or {}).get("bucket", "default")


def _smart_headline(extracted_data: ExtractedAppData, strategy: ContentStrategy) -> str:
    bucket = _bucket(strategy)
    app_name = extracted_data.app_name
    if bucket == "music":
        return f"Feel Every Beat with {app_name}"
    if bucket == "gaming":
        return f"Level Up Faster with {app_name}"
    if bucket == "finance":
        return f"Make Smarter Money Moves with {app_name}"
    if bucket == "productivity":
        return f"Get More Done with {app_name}"
    return f"Discover {app_name}"


def _smart_subheadline(extracted_data: ExtractedAppData, strategy: ContentStrategy) -> str:
    base = (extracted_data.short_description or "").strip()
    angle = (strategy.main_angle or "").strip()
    if base:
        angle = base
    if len(angle) > 180:
        angle = angle[:177].rstrip() + "..."
    if angle:
        return angle
    return extracted_data.short_description or "Built for a better mobile experience."


def _hero_subheadline(extracted_data: ExtractedAppData, strategy: ContentStrategy) -> str:
    lead = _smart_headline(extracted_data, strategy).strip()
    detail = _smart_subheadline(extracted_data, strategy).strip()

    if lead and detail:
        return f"{lead}. {detail}"
    if detail:
        return detail
    if lead:
        return lead
    return extracted_data.short_description or "Built for a better mobile experience."


def _clean_text(value: str) -> str:
    text = (value or "").replace("\n", " ").replace("\r", " ")
    text = text.replace("â€¢", " ").replace("â€™", "'").replace("â€“", "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _benefit_title(text: str) -> str:
    normalized = _clean_text(text)
    if normalized.upper().startswith("WHY "):
        return "Why Users Choose It"

    low = normalized.lower()
    keyword_titles = [
        ("offline", "Offline Access"),
        ("podcast", "Podcast Variety"),
        ("playlist", "Smarter Playlists"),
        ("discover", "Easy Discovery"),
        ("quality", "Great Audio Quality"),
        ("sync", "Cross-Device Continuity"),
        ("user-friendly", "User-Friendly Interface"),
        ("secure", "Secure Experience"),
        ("privacy", "Privacy Control"),
        ("budget", "Budget Control"),
        ("transfer", "Fast Transfers"),
    ]
    for key, title in keyword_titles:
        if key in low:
            return title

    # Convert common sentence starters into clean topic labels.
    if low.startswith("access to"):
        if "wide" in low:
            return "Wide Access"
        if "quick" in low or "fast" in low:
            return "Quick Access"
        return "Easy Access"

    if low.startswith("user-friendly interface"):
        return "User-Friendly Interface"

    # Prefer a clause before connectors so headings stay concise and natural.
    primary_clause = re.split(r"\b(for|with|to|that|which)\b|[\.:;,-]", normalized, maxsplit=1)[0].strip()
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']+", primary_clause) if len(w) > 2]

    stopwords = {
        "the", "and", "for", "with", "that", "this", "your", "you", "from", "into", "over", "under",
        "while", "where", "when", "have", "has", "had", "are", "was", "were", "will", "can", "all",
    }
    filtered = [w for w in words if w.lower() not in stopwords]

    if filtered:
        if filtered[0].lower() == "access" and len(filtered) > 1:
            # "Access ..." reads better as "... Access".
            return f"{filtered[1].capitalize()} Access"[:60]
        title = " ".join(filtered[:3])
        return title.title()[:60]

    words = normalized.split(" ")
    if not words:
        return "Key Benefit"
    title = " ".join(words[:4]).strip(" ,.;:-")
    return title[:60]


def _benefit_description(text: str) -> str:
    normalized = _clean_text(text)
    # Remove heading-like lines that are not useful marketing copy.
    if normalized.isupper() and len(normalized.split()) <= 8:
        return "Built to deliver a smooth and enjoyable mobile experience every day."

    normalized = re.sub(r"^why\s+[^?]*\??", "", normalized, flags=re.IGNORECASE).strip()
    if not normalized:
        return "Built to deliver a smooth and enjoyable mobile experience every day."

    if len(normalized) > 160:
        normalized = normalized[:157].rstrip() + "..."
    return normalized


def _humanize_installs(installs: str | None) -> str | None:
    if not installs:
        return installs
    raw = str(installs).strip()
    if not raw.isdigit():
        return raw
    value = int(raw)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return raw


def _compose_benefits(strategy: ContentStrategy) -> List[dict]:
    bucket = _bucket(strategy)
    icons = ICON_BY_BUCKET.get(bucket, ICON_BY_BUCKET["default"])

    cards = []
    for i, benefit in enumerate((strategy.top_benefits or [])[:5]):
        title = _benefit_title(benefit)
        description = _benefit_description(benefit)
        cards.append(
            {
                "title": title,
                "description": description,
                "icon_emoji": icons[i % len(icons)],
            }
        )

    # Ensure at least 3 cards.
    while len(cards) < 3:
        i = len(cards)
        cards.append(
            {
                "title": f"Core Value {i+1}",
                "description": "Designed to deliver a smooth, reliable experience for daily use.",
                "icon_emoji": icons[i % len(icons)],
            }
        )
    return cards


def _faq_answer(topic: str, extracted_data: ExtractedAppData, strategy: ContentStrategy) -> str:
    bucket = _bucket(strategy)
    t = topic.lower()

    if "offline" in t:
        return "You can install the app and use its supported features on your device immediately. Check in-app settings for offline options."
    if "audio" in t:
        return "The app is optimized for high-quality playback and smooth streaming, with settings you can tune based on your connection."
    if "privacy" in t or "security" in t:
        return "Your account and usage settings are managed inside the app. Review permissions and privacy settings during onboarding for best control."
    if "sync" in t:
        return "The app is built for modern mobile usage and typically keeps your experience consistent across sessions and devices."
    if "compat" in t or "device" in t:
        return "It supports a broad range of Android devices; compatibility details are available on the Google Play listing."

    if bucket == "music":
        return "The experience is designed around fast discovery, smooth listening, and personalized recommendations."
    if bucket == "gaming":
        return "The app focuses on responsive gameplay, clear progression, and an immersive mobile experience."
    if bucket == "finance":
        return "The product emphasizes clarity, control, and safe account management for everyday decisions."
    if bucket == "productivity":
        return "The workflow is optimized to reduce friction so you can complete tasks quickly and consistently."
    return "The app is designed for a reliable, user-friendly experience from first install."


def _clean_reviews(reviews: List[dict]) -> List[dict]:
    """Clean reviews for display - minimal filtering, trust OpenAI analysis."""
    
    cleaned = []
    for r in reviews:
        if hasattr(r, "model_dump"):
            r = r.model_dump()
        
        text_raw = str(r.get("text", ""))
        text = _clean_text(text_raw)
        
        if len(text) > 220:
            text = text[:217].rstrip() + "..."
        if not text:
            continue
        
        cleaned.append(
            {
                "rating": int(r.get("rating", 0) or 0),
                "text": text,
                "reviewer": _clean_text(str(r.get("reviewer", "Anonymous"))) or "Anonymous",
            }
        )
    return cleaned


def generate_landing_content(
    extracted_data: ExtractedAppData, strategy: ContentStrategy
) -> LandingPageContent:
    """
    Composer Agent: Generates final landing page content.
    
    TODO: Implement OpenAI API call here.
    Prompt should:
    1. Create compelling hero headline/subheadline
    2. Generate benefit cards with descriptions
    3. Compile social proof section
    4. Create FAQ answers
    5. Format all content for HTML rendering
    
    Args:
        extracted_data: Raw app data from Extractor
        strategy: Content strategy from Analyzer
        
    Returns:
        LandingPageContent ready for HTML rendering
    """
    
    # Prompt is loaded now so LLM integration can use a stable contract.
    prompt_text = load_prompt("composer")
    logger.info("Composer prompt loaded (%d chars)", len(prompt_text))

    include_rating = extracted_data.rating is not None and "rating_not_promoted_below_4_5" not in (strategy.missing_data_flags or [])
    max_reviews = 5 if extracted_data.rating and extracted_data.rating >= 4.0 else 3
    reviews = _clean_reviews((strategy.selected_reviews or [])[:max_reviews])
    installs = _humanize_installs(extracted_data.installs)

    social_headline = "Loved by users"
    if include_rating and extracted_data.rating is not None:
            social_headline = f"Rated {extracted_data.rating:.2f}/5 by users"
    elif installs:
            social_headline = f"Trusted by {installs} installs"

    faq_items = [
    {
            "question": topic,
            "answer": _faq_answer(topic, extracted_data, strategy),
    }
    for topic in (strategy.faq_topics or [])[:4]
    ]

    if not faq_items:
        faq_items = [
            {
                "question": "How do I get started?",
                "answer": "Install from Google Play and complete the in-app onboarding to start using the key features in minutes.",
            }
        ]

    cta_text = "Install on Google Play"
    if _bucket(strategy) == "music":
        cta_text = "Install and Start Listening"
    elif _bucket(strategy) == "gaming":
        cta_text = "Install and Play Now"
    elif _bucket(strategy) == "finance":
        cta_text = "Install and Take Control"
    elif _bucket(strategy) == "productivity":
        cta_text = "Install and Get More Done"

    return LandingPageContent(
        hero_headline=(extracted_data.app_name or "").strip() or _smart_headline(extracted_data, strategy),
        hero_subheadline=_hero_subheadline(extracted_data, strategy),
        hero_image_url=extracted_data.icon_url or (extracted_data.screenshots[0] if extracted_data.screenshots else ""),
        benefits=_compose_benefits(strategy),
        social_proof_headline=social_headline,
        social_proof_rating=round(extracted_data.rating, 2) if include_rating and extracted_data.rating is not None else None,
        social_proof_installs=installs,
        social_proof_reviews=reviews,
        screenshots=(extracted_data.screenshots or [])[:8],
        faq_items=faq_items,
        cta_text=cta_text,
        cta_url=f"https://play.google.com/store/apps/details?id={extracted_data.app_id}",
    )
