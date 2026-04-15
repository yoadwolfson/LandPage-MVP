import logging
import re
from datetime import datetime
from typing import List, Dict
from schemas.models import ExtractedAppData, ContentStrategy
from agent.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


STYLE_PROFILES: Dict[str, Dict[str, str]] = {
    "music": {
        "theme": "immersive",
        "palette": "high-contrast dark with vibrant accent",
        "visual_direction": "bold hero, large artwork, energetic sections",
        "template_id": "music",
        "template_objective": "Drive emotional engagement and quick install intent through immersive visual rhythm.",
        "typography": "modern geometric sans",
        "color_primary": "#1DB954",
        "color_secondary": "#0B1320",
        "color_background": "#070A0F",
        "color_surface": "#111827",
        "color_text": "#F3F4F6",
        "color_accent": "#8B5CF6",
    },
    "gaming": {
        "theme": "dynamic",
        "palette": "neon accent over deep background",
        "visual_direction": "high energy, gamified badges, strong motion",
        "template_id": "gaming",
        "template_objective": "Maximize excitement and urgency with progression-driven sections and action-first CTA.",
        "typography": "display headline + readable body sans",
        "color_primary": "#22D3EE",
        "color_secondary": "#0F172A",
        "color_background": "#030712",
        "color_surface": "#111827",
        "color_text": "#E5E7EB",
        "color_accent": "#A855F7",
    },
    "finance": {
        "theme": "trust-first",
        "palette": "clean neutral with confidence green/blue",
        "visual_direction": "structured cards, proof-forward layout",
        "template_id": "finance",
        "template_objective": "Build trust quickly with credibility cues, clarity, and proof-led messaging.",
        "typography": "professional sans",
        "color_primary": "#0EA5E9",
        "color_secondary": "#1E293B",
        "color_background": "#F8FAFC",
        "color_surface": "#FFFFFF",
        "color_text": "#0F172A",
        "color_accent": "#10B981",
    },
    "productivity": {
        "theme": "clean-focus",
        "palette": "light neutral with single accent",
        "visual_direction": "clear hierarchy, concise copy, practical UI",
        "template_id": "productivity",
        "template_objective": "Show practical value fast using clean hierarchy and no-noise benefit communication.",
        "typography": "readable sans with medium contrast headings",
        "color_primary": "#2563EB",
        "color_secondary": "#334155",
        "color_background": "#F8FAFC",
        "color_surface": "#FFFFFF",
        "color_text": "#0F172A",
        "color_accent": "#F59E0B",
    },
    "default": {
        "theme": "balanced",
        "palette": "clean modern neutral",
        "visual_direction": "benefit-first layout with strong CTA",
        "template_id": "default",
        "template_objective": "Provide a balanced app landing with broad compatibility and clear install path.",
        "typography": "modern sans",
        "color_primary": "#4F46E5",
        "color_secondary": "#1F2937",
        "color_background": "#F9FAFB",
        "color_surface": "#FFFFFF",
        "color_text": "#111827",
        "color_accent": "#06B6D4",
    },
}


def _normalize_text(*parts: str) -> str:
    return " ".join((p or "") for p in parts).lower().strip()


def _detect_style_bucket(extracted_data: ExtractedAppData) -> str:
    text = _normalize_text(
        extracted_data.app_name,
        extracted_data.short_description,
        extracted_data.full_description,
    )

    def has_term(pattern: str) -> bool:
        return re.search(pattern, text) is not None

    def score_terms(patterns: list[tuple[str, int]]) -> int:
        score = 0
        for pattern, weight in patterns:
            if has_term(pattern):
                score += weight
        return score

    music_score = score_terms([
        (r"\bmusic\b", 2),
        (r"\bpodcast\b", 2),
        (r"\baudio\b", 1),
        (r"\bplaylist\b", 1),
        (r"\bartist\b", 1),
    ])
    gaming_score = score_terms([
        (r"\bgame\b", 2),
        (r"\bgames\b", 2),
        (r"\bbattle\b", 1),
        (r"\blevel\b", 1),
        (r"\brpg\b", 1),
        (r"\barcade\b", 1),
    ])
    finance_score = score_terms([
        (r"\bbank\b", 3),
        (r"\bbanking\b", 3),
        (r"\bfinance\b", 3),
        (r"\bwallet\b", 3),
        (r"\binvest\b", 3),
        (r"\binvesting\b", 3),
        (r"\btrading\b", 3),
        (r"\bloan\b", 3),
        (r"\bmoney\b", 1),
        (r"\bbudget\b", 1),
        (r"\bbills?\b", 1),
        (r"\bspend\w*\b", 1),
        (r"\bpayment\b", 1),
        (r"\bpay\b", 1),
        (r"\bcash\b", 1),
        (r"\bcredit\b", 1),
        (r"\baccount\b", 1),
        (r"\btransfer\b", 1),
    ])
    productivity_score = score_terms([
        (r"\btask\b", 2),
        (r"\bnote\b", 1),
        (r"\bcalendar\b", 1),
        (r"\bworkflow\b", 2),
        (r"\bproductivity\b", 2),
        (r"\borganize\b", 1),
    ])

    if finance_score >= 3 and finance_score >= gaming_score + 1 and finance_score >= music_score:
        return "finance"
    if music_score >= 2 and music_score > finance_score and music_score > gaming_score:
        return "music"
    if gaming_score >= 2 and gaming_score > finance_score and gaming_score >= music_score:
        return "gaming"
    if productivity_score >= 2 and productivity_score > finance_score and productivity_score > gaming_score:
        return "productivity"
    return "default"


def _extract_benefits(extracted_data: ExtractedAppData) -> List[str]:
    raw = extracted_data.full_description or extracted_data.short_description or ""
    candidates = re.split(r"[\n\r•\-;]+", raw)
    cleaned: List[str] = []
    seen = set()
    for item in candidates:
        s = re.sub(r"\s+", " ", item).strip(" .")
        if len(s) < 24:
            continue
        lower = s.lower()
        if lower in seen:
            continue
        seen.add(lower)
        cleaned.append(s)
        if len(cleaned) >= 5:
            break

    if len(cleaned) >= 3:
        return cleaned[:5]

    fallback = [
        "Fast and intuitive mobile experience",
        "Large content and feature coverage",
        "Reliable day-to-day usability",
    ]
    return cleaned + fallback[: max(0, 3 - len(cleaned))]


def _choose_reviews(extracted_data: ExtractedAppData) -> List[dict]:
    # Reviews are already filtered upstream for recent high-quality content.
    reviews = extracted_data.reviews or []
    sorted_reviews = sorted(
        reviews,
        key=lambda r: (
            int(r.get("rating", 0) or 0),
            r.get("date") or "",
        ),
        reverse=True,
    )
    return [
        {
            "rating": int(r.get("rating", 0) or 0),
            "text": str(r.get("text", "")).strip(),
            "reviewer": str(r.get("reviewer", "Anonymous")).strip(),
        }
        for r in sorted_reviews
        if int(r.get("rating", 0) or 0) >= 4 and str(r.get("text", "")).strip()
    ][:3]


def _build_main_angle(extracted_data: ExtractedAppData, benefits: List[str], include_rating: bool) -> str:
    base = benefits[0] if benefits else f"A better way to use {extracted_data.app_name}"
    if include_rating and extracted_data.rating is not None:
        return f"{base}. Rated {extracted_data.rating:.2f}/5 by users."
    return base


def _faq_topics_for_app(extracted_data: ExtractedAppData) -> List[str]:
    style_bucket = _detect_style_bucket(extracted_data)
    if style_bucket == "music":
        return ["Offline listening", "Audio quality", "Playlists and recommendations"]
    if style_bucket == "gaming":
        return ["Device performance", "Progress sync", "In-app purchases"]
    if style_bucket == "finance":
        return ["Security and privacy", "Fees and pricing", "Account management"]
    if style_bucket == "productivity":
        return ["Cross-device sync", "Notifications", "Collaboration"]
    return ["How it works", "Privacy", "Compatibility"]


def analyze_content_strategy(extracted_data: ExtractedAppData) -> ContentStrategy:
    """
    Analyzer Agent: Determines content strategy based on extracted data.
    
    TODO: Implement OpenAI API call here.
    Prompt should:
    1. Analyze app description and reviews
    2. Identify target audience
    3. Extract top 3-5 benefits
    4. Select high-quality reviews (rating >= 4.5)
    5. Determine FAQ topics
    
    Args:
        extracted_data: Raw app data from Extractor
        
    Returns:
        ContentStrategy with messaging direction
    """
    
    # Prompt is loaded now so LLM integration can use a stable contract.
    prompt_text = load_prompt("analyzer")
    logger.info("Analyzer prompt loaded (%d chars)", len(prompt_text))

    style_bucket = _detect_style_bucket(extracted_data)
    style_profile = STYLE_PROFILES.get(style_bucket, STYLE_PROFILES["default"])

    benefits = _extract_benefits(extracted_data)
    selected_reviews = _choose_reviews(extracted_data)

    include_rating = extracted_data.rating is not None and extracted_data.rating >= 4.5
    main_angle = _build_main_angle(extracted_data, benefits, include_rating)

    missing_data_flags: List[str] = []
    if extracted_data.rating is None:
        missing_data_flags.append("rating_missing")
    elif extracted_data.rating < 4.5:
        missing_data_flags.append("rating_not_promoted_below_4_5")
    if not selected_reviews:
        missing_data_flags.append("no_good_recent_reviews")
    if not extracted_data.installs:
        missing_data_flags.append("installs_missing")

    # If we have review proof, signal this in messaging focus.
    if selected_reviews and "review_proof_enabled" not in missing_data_flags:
        missing_data_flags.append("review_proof_enabled")

    tone = {
        "music": "Energetic and expressive",
        "gaming": "Bold and high-energy",
        "finance": "Trustworthy and precise",
        "productivity": "Clear and practical",
        "default": "Modern and benefit-led",
    }.get(style_bucket, "Modern and benefit-led")

    audience = {
        "music": "Music and podcast listeners",
        "gaming": "Mobile gamers seeking immersive play",
        "finance": "Users managing money and financial decisions",
        "productivity": "Users who want to organize work and tasks",
        "default": "Mobile users looking for a better app experience",
    }.get(style_bucket, "Mobile users looking for a better app experience")

    return ContentStrategy(
        target_audience=audience,
        tone=tone,
        main_angle=main_angle,
        top_benefits=benefits[:5],
        selected_reviews=selected_reviews,
        faq_topics=_faq_topics_for_app(extracted_data),
        missing_data_flags=missing_data_flags,
        style_guide={
            "bucket": style_bucket,
            **style_profile,
        },
    )
