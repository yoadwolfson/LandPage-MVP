from datetime import date, timedelta
from collections import Counter
from colorsys import rgb_to_hls
import hashlib
import logging
import os
import re
from io import BytesIO
from typing import Any
from typing import List, Dict

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

from schemas.models import ExtractedAppData, ContentStrategy
from agent.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

ALLOWED_TEMPLATE_IDS = {"default", "music", "gaming", "finance", "productivity"}

# Keywords for review quality scoring
STRONG_COMPLAINT_KEYWORDS = {
    "bug", "crash", "broken", "fails", "error",
    "terrible", "awful", "worst", "poor", "scam", "useless", "worthless",
}

MODERATE_COMPLAINT_KEYWORDS = {
    "annoying", "annoyed", "hate", "lag", "laggy",
    "glitch", "doesn't work", "not working",
}

POSITIVE_SENTIMENT_KEYWORDS = {
    "love", "loves", "amazing", "awesome", "excellent", "fantastic",
    "great", "wonderful", "perfect", "best", "recommend", "highly recommend",
    "enjoy", "enjoying", "enjoyed", "helpful", "useful",
    "simple", "easy", "intuitive", "smooth", "fast",
    "must have", "must download", "impressed", "discovering", "impressed",
    "quality", "great", "reliable", "intuitive", "clean", "works great",
}

NEGATION_WORDS = {"no ", "not ", "don't ", "didn't ", "couldn't ", "can't ", "won't ", "without "}


def _has_negation_before_word(text: str, word: str, context_length: int = 20) -> bool:
    """Check if a complaint word is negated (e.g., 'no ads', 'not slow')."""
    text_lower = text.lower()
    idx = text_lower.find(word.lower())
    if idx == -1:
        return False
    
    start = max(0, idx - context_length)
    context = text_lower[start:idx]
    return any(neg in context for neg in NEGATION_WORDS)


def _score_review_for_marketing(review_text: str) -> float:
    """
    Score a review for marketing suitability (0 = exclude, 1.0 = perfect).
    
    Scoring logic:
    - Strong complaints (crash, bug, terrible) → 0.05 (exclude)
    - Moderate complaints w/o praise → 0.25 (low)
    - Moderate complaints w/ praise → 0.55 (medium)
    - Praise-heavy reviews → 0.75-1.0 (preferred)
    - Neutral reviews → 0.4 (acceptable fallback)
    """
    text_lower = review_text.lower()
    
    # Count complaint keywords, but ignore negated ones
    strong_complaint_count = sum(
        1 for kw in STRONG_COMPLAINT_KEYWORDS 
        if kw in text_lower and not _has_negation_before_word(review_text, kw)
    )
    
    moderate_complaint_count = sum(
        1 for kw in MODERATE_COMPLAINT_KEYWORDS 
        if kw in text_lower and not _has_negation_before_word(review_text, kw)
    )
    
    praise_count = sum(1 for kw in POSITIVE_SENTIMENT_KEYWORDS if kw in text_lower)
    
    # Strong complaints = exclude
    if strong_complaint_count > 0:
        return 0.05
    
    # Multiple moderate complaints = low score
    if moderate_complaint_count > 1:
        return 0.25
    
    # One moderate complaint needs some praise
    if moderate_complaint_count == 1:
        if praise_count >= 2:
            return 0.65  # Complaint but good praise
        else:
            return 0.45  # Complaint with minimal praise
    
    # Pure praise reviews = high score
    if praise_count >= 3:
        return 0.95
    if praise_count == 2:
        return 0.80
    if praise_count == 1:
        return 0.65
    
    # Neutral reviews = acceptable
    return 0.40


def _validate_openai_reviews(reviews: List[Dict]) -> List[Dict]:
    """
    STRICT validation: hard reject obvious complaint patterns.
    
    AUTO-REJECT (no exceptions):
    - "popup" or "pop-up" keyword → UX frustration complaint
    - "annoying" or "annoyed" keyword → indicates frustration
    - "deleted" keyword → data loss concern
    - 2+ technical complaint keywords → multiple issues
    
    Philosophy: Better to show 1 excellent review than 3 reviews with complaints.
    """
    logger.info(f"=== VALIDATION STARTED: {len(reviews)} reviews ===")
    if not reviews:
        logger.info("No reviews to validate")
        return []
    
    validated = []
    for rev in reviews:
        # Handle both dict and object types
        if hasattr(rev, "model_dump"):
            rev_dict = rev.model_dump()
        else:
            rev_dict = rev if isinstance(rev, dict) else {}
        
        text_raw = rev_dict.get("text", "")
        if not text_raw:
            continue
            
        text_lower = str(text_raw).lower()
        reviewer_name = rev_dict.get("reviewer", "Unknown")
        
        # ===== HARD REJECTS =====
        # Any "popup" keyword = auto-reject
        if "popup" in text_lower or "pop-up" in text_lower:
            logger.warning(f"REJECTED '{reviewer_name}': contains 'popup' keyword (UX complaint)")
            continue
        
        # Any "annoying" keyword = auto-reject  
        if "annoying" in text_lower or "annoyed" in text_lower:
            logger.warning(f"REJECTED '{reviewer_name}': contains 'annoying' keyword (frustration)")
            continue
        
        # Data loss = auto-reject
        if "deleted" in text_lower:
            logger.warning(f"REJECTED '{reviewer_name}': contains 'deleted' keyword (data loss)")
            continue
        
        # Multiple technical issues
        tech_issues = ["crash", "broken", "bug", "error", "fail", "lag"]
        issue_count = sum(1 for issue in tech_issues if issue in text_lower)
        if issue_count >= 2:
            logger.warning(f"REJECTED '{reviewer_name}': {issue_count} technical issues")
            continue
        
        # Single issue with NO positive sentiment = reject
        if issue_count >= 1:
            positive_count = sum(1 for kw in POSITIVE_SENTIMENT_KEYWORDS if kw in text_lower)
            if positive_count == 0:
                logger.warning(f"REJECTED '{reviewer_name}': technical issue with no praise")
                continue
        
        # Otherwise: KEEP (it passed all hard filters)
        logger.debug(f"APPROVED '{reviewer_name}': passed all validation checks")
        validated.append(rev)
    
    logger.info(f"Review validation: filtered {len(reviews)} → {len(validated)}")
    return validated


def _select_marketing_reviews(reviews: List[Dict]) -> List[Dict]:
    """
    Select best 3 reviews for marketing based on:
    1. Marketing content quality (sentiment analysis)
    2. Rating (high ratings preferred)
    3. Recency (newer reviews preferred)
    
    CRITICAL: Apply same strict filtering as OpenAI validation -
    NO reviews with "popup", "annoying", or "deleted" keywords.
    
    Only includes reviews with marketing score > 0.50 threshold.
    Falls back to score > 0.35 if fewer than 3 high-quality reviews available.
    """
    if not reviews or len(reviews) < 1:
        return []
    
    from datetime import datetime
    
    # Pre-filter: Remove absolute deal-breakers
    filtered_reviews = []
    for rev in reviews:
        text = rev.get("text", "")
        text_lower = str(text).lower()
        
        # Hard filters - same as validation
        if "popup" in text_lower or "annoying" in text_lower or "deleted" in text_lower:
            logger.debug(f"Pre-filter removed review: complaint keyword found")
            continue
        
        filtered_reviews.append(rev)
    
    if not filtered_reviews:
        logger.warning("All reviews filtered by strict criteria - returning empty list")
        return []
    
    # Score remaining reviews
    scored_reviews = []
    for rev in filtered_reviews:
        text = rev.get("text", "")
        marketing_score = _score_review_for_marketing(text)
        
        # Parse date for sorting (handle various formats)
        date_obj = None
        date_str = rev.get("date", "")
        if date_str:
            try:
                date_obj = datetime.fromisoformat(date_str)
            except (ValueError, TypeError):
                date_obj = datetime.min
        else:
            date_obj = datetime.min
        
        scored_reviews.append({
            **rev,
            "_marketing_score": marketing_score,
            "_date_obj": date_obj,
        })
    
    # Primary sort: marketing score (high first), rating (high first), date (newest first)
    scored_reviews.sort(
        key=lambda x: (
            x["_marketing_score"],
            x.get("rating", 0),
            x["_date_obj"]
        ),
        reverse=True,
    )
    
    # Try to get 3 high-quality reviews (score > 0.50)
    best_reviews = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in scored_reviews
        if r["_marketing_score"] > 0.50
    ][:3]
    
    # If not enough, lower threshold more aggressively to 0.35
    if len(best_reviews) < 3:
        best_reviews = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in scored_reviews
            if r["_marketing_score"] > 0.35
        ][:3]
    
    return best_reviews



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
        "hero_layout": "split",
        "card_layout": "carousel",
        "typography_density": "spacious",
        "content_emphasis": "visual",
        "visual_intensity": "high",
        "section_order": "visual-first",
        "tone_variant": "energetic",
        "trust_level": "medium",
        "motion_hint": "pulsed",
        "palette_source": "category_fallback",
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
        "hero_layout": "full-width",
        "card_layout": "grid",
        "typography_density": "spacious",
        "content_emphasis": "visual",
        "visual_intensity": "high",
        "section_order": "visual-first",
        "tone_variant": "bold",
        "trust_level": "low",
        "motion_hint": "aggressive",
        "palette_source": "category_fallback",
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
        "hero_layout": "split",
        "card_layout": "grid",
        "typography_density": "normal",
        "content_emphasis": "reviews",
        "visual_intensity": "medium",
        "section_order": "proof-first",
        "tone_variant": "precise",
        "trust_level": "high",
        "motion_hint": "subtle",
        "palette_source": "category_fallback",
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
        "hero_layout": "full-width",
        "card_layout": "list",
        "typography_density": "compact",
        "content_emphasis": "text",
        "visual_intensity": "low",
        "section_order": "benefit-first",
        "tone_variant": "practical",
        "trust_level": "medium",
        "motion_hint": "minimal",
        "palette_source": "category_fallback",
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
        "hero_layout": "full-width",
        "card_layout": "grid",
        "typography_density": "normal",
        "content_emphasis": "text",
        "visual_intensity": "medium",
        "section_order": "benefit-first",
        "tone_variant": "balanced",
        "trust_level": "medium",
        "motion_hint": "minimal",
        "palette_source": "category_fallback",
    },
}


PALETTE_VARIANTS: Dict[str, List[Dict[str, str]]] = {
    "music": [
        {"color_primary": "#1DB954", "color_secondary": "#0B1320", "color_background": "#070A0F", "color_surface": "#111827", "color_text": "#F3F4F6", "color_accent": "#8B5CF6"},
        {"color_primary": "#22C55E", "color_secondary": "#0A1020", "color_background": "#050816", "color_surface": "#111A2F", "color_text": "#EAF2FF", "color_accent": "#F43F5E"},
        {"color_primary": "#14B8A6", "color_secondary": "#111827", "color_background": "#060C14", "color_surface": "#172133", "color_text": "#ECFEFF", "color_accent": "#A78BFA"},
    ],
    "gaming": [
        {"color_primary": "#22D3EE", "color_secondary": "#0F172A", "color_background": "#030712", "color_surface": "#111827", "color_text": "#E5E7EB", "color_accent": "#A855F7"},
        {"color_primary": "#38BDF8", "color_secondary": "#0B1024", "color_background": "#04050F", "color_surface": "#151A2F", "color_text": "#EEF2FF", "color_accent": "#F97316"},
        {"color_primary": "#06B6D4", "color_secondary": "#111827", "color_background": "#020617", "color_surface": "#0F1B2D", "color_text": "#E2E8F0", "color_accent": "#EC4899"},
    ],
    "finance": [
        {"color_primary": "#0EA5E9", "color_secondary": "#1E293B", "color_background": "#F8FAFC", "color_surface": "#FFFFFF", "color_text": "#0F172A", "color_accent": "#10B981"},
        {"color_primary": "#2563EB", "color_secondary": "#1F2937", "color_background": "#F7FAFF", "color_surface": "#FFFFFF", "color_text": "#111827", "color_accent": "#14B8A6"},
        {"color_primary": "#0284C7", "color_secondary": "#273449", "color_background": "#F4F8FB", "color_surface": "#FFFFFF", "color_text": "#0F172A", "color_accent": "#16A34A"},
    ],
    "productivity": [
        {"color_primary": "#2563EB", "color_secondary": "#334155", "color_background": "#F8FAFC", "color_surface": "#FFFFFF", "color_text": "#0F172A", "color_accent": "#F59E0B"},
        {"color_primary": "#4F46E5", "color_secondary": "#374151", "color_background": "#F9FAFB", "color_surface": "#FFFFFF", "color_text": "#111827", "color_accent": "#06B6D4"},
        {"color_primary": "#0EA5E9", "color_secondary": "#334155", "color_background": "#F6FAFF", "color_surface": "#FFFFFF", "color_text": "#0B1220", "color_accent": "#F97316"},
    ],
    "default": [
        {"color_primary": "#4F46E5", "color_secondary": "#1F2937", "color_background": "#F9FAFB", "color_surface": "#FFFFFF", "color_text": "#111827", "color_accent": "#06B6D4"},
        {"color_primary": "#2563EB", "color_secondary": "#334155", "color_background": "#F8FAFC", "color_surface": "#FFFFFF", "color_text": "#0F172A", "color_accent": "#14B8A6"},
        {"color_primary": "#0EA5E9", "color_secondary": "#1E293B", "color_background": "#F4F8FB", "color_surface": "#FFFFFF", "color_text": "#0F172A", "color_accent": "#8B5CF6"},
    ],
}


def _hex_to_rgb_tuple(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _normalize_hex(color: str | None, fallback: str) -> str:
    value = (color or "").strip()
    if not re.match(r"^#[0-9a-fA-F]{6}$", value):
        return fallback
    return value.upper()


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(color: str) -> float:
    r, g, b = _hex_to_rgb(color)
    rl = _srgb_to_linear(r / 255.0)
    gl = _srgb_to_linear(g / 255.0)
    bl = _srgb_to_linear(b / 255.0)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def _contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a)
    lb = _relative_luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _mix_hex(a: str, b: str, ratio_a: float) -> str:
    ratio_a = max(0.0, min(1.0, ratio_a))
    ratio_b = 1.0 - ratio_a
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    r = round(ar * ratio_a + br * ratio_b)
    g = round(ag * ratio_a + bg * ratio_b)
    b2 = round(ab * ratio_a + bb * ratio_b)
    return f"#{r:02X}{g:02X}{b2:02X}"


def _rgb_saturation(rgb: tuple[int, int, int]) -> float:
    r, g, b = [channel / 255.0 for channel in rgb]
    _, _, saturation = rgb_to_hls(r, g, b)
    return saturation


def _rgb_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return _relative_luminance(_rgb_to_hex((r, g, b)))


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _bucket_rgb(rgb: tuple[int, int, int], step: int = 32) -> tuple[int, int, int]:
    return tuple(min(255, max(0, round(channel / step) * step)) for channel in rgb)


def _text_color_for_background(background: str, surface: str) -> str:
    light = "#F8FAFC"
    dark = "#0F172A"
    light_score = min(_contrast_ratio(light, background), _contrast_ratio(light, surface))
    dark_score = min(_contrast_ratio(dark, background), _contrast_ratio(dark, surface))
    return light if light_score >= dark_score else dark


def _sample_icon_colors(icon_url: str) -> List[tuple[tuple[int, int, int], int]]:
    if not icon_url:
        return []

    try:
        import requests
        from PIL import Image
    except Exception:
        return []

    try:
        response = requests.get(icon_url, timeout=10)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail((96, 96))
    except Exception:
        return []

    counts: Counter[tuple[int, int, int]] = Counter()
    for red, green, blue, alpha in image.getdata():
        if alpha < 32:
            continue
        counts[_bucket_rgb((red, green, blue))] += 1

    return counts.most_common(20)


def _derive_logo_palette(extracted_data: ExtractedAppData, base_style: Dict[str, str]) -> Dict[str, str]:
    sampled_colors = _sample_icon_colors(extracted_data.icon_url)
    if not sampled_colors:
        return dict(base_style)

    ranked = [rgb for rgb, _count in sampled_colors]
    primary = ranked[0]
    for candidate in ranked[1:5]:
        if _rgb_saturation(candidate) >= 0.22 and _rgb_distance(candidate, primary) >= 48:
            primary = candidate
            break

    accent = None
    for candidate in ranked[1:8]:
        if _rgb_distance(candidate, primary) >= 70:
            accent = candidate
            break
    if accent is None and len(ranked) > 1:
        accent = ranked[1]

    if accent is None:
        accent = _bucket_rgb(tuple(min(255, max(0, channel + 56)) for channel in primary))

    primary_luminance = _rgb_luminance(primary)
    dark_theme = primary_luminance < 0.55 or extracted_data.app_id.startswith("com.spotify")

    if dark_theme:
        background = _mix_hex(_rgb_to_hex(primary), "#000000", 0.16)
        surface = _mix_hex(_rgb_to_hex(primary), "#111827", 0.22)
        secondary = _mix_hex(_rgb_to_hex(primary), "#0B1320", 0.30)
    else:
        background = _mix_hex(_rgb_to_hex(primary), "#FFFFFF", 0.92)
        surface = _mix_hex(_rgb_to_hex(primary), "#FFFFFF", 0.98)
        secondary = _mix_hex(_rgb_to_hex(primary), "#334155", 0.76)

    primary_hex = _rgb_to_hex(primary)
    accent_hex = _rgb_to_hex(accent)
    text_hex = _text_color_for_background(background, surface)

    derived_style = dict(base_style)
    derived_style.update({
        "color_primary": primary_hex,
        "color_secondary": secondary,
        "color_background": background,
        "color_surface": surface,
        "color_text": text_hex,
        "color_accent": accent_hex,
        "palette": f"logo-derived from {primary_hex} and {accent_hex}",
        "palette_source": "brand_logo",
    })
    return derived_style


def _enforce_style_contrast(style: dict[str, str], fallback_style: dict[str, str]) -> dict[str, str]:
    bg = _normalize_hex(style.get("color_background"), fallback_style["color_background"])
    surface = _normalize_hex(style.get("color_surface"), fallback_style["color_surface"])
    text = _normalize_hex(style.get("color_text"), fallback_style["color_text"])

    # Ensure text is readable on both background and surface.
    min_text_contrast = min(_contrast_ratio(text, bg), _contrast_ratio(text, surface))
    if min_text_contrast < 4.5:
        light_text = "#F8FAFC"
        dark_text = "#0F172A"
        light_score = min(_contrast_ratio(light_text, bg), _contrast_ratio(light_text, surface))
        dark_score = min(_contrast_ratio(dark_text, bg), _contrast_ratio(dark_text, surface))
        text = light_text if light_score >= dark_score else dark_text

    # Ensure cards do not blend with page background.
    if _contrast_ratio(surface, bg) < 1.25:
        if _relative_luminance(bg) < 0.5:
            surface = _mix_hex(bg, "#FFFFFF", 0.78)
        else:
            surface = _mix_hex(bg, "#000000", 0.90)

    style["color_background"] = bg
    style["color_surface"] = surface
    style["color_text"] = text
    return style


def _normalize_text(*parts: str) -> str:
    return " ".join((p or "") for p in parts).lower().strip()


def _stable_variant_index(source: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.md5(source.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def _infer_palette_hint(extracted_data: ExtractedAppData) -> str:
    text = _normalize_text(
        extracted_data.app_name,
        extracted_data.short_description,
        extracted_data.full_description,
        " ".join((extracted_data.screenshots or [])[:3]),
    )
    if re.search(r"music|podcast|audio|playlist|artist", text):
        return "vibrant"
    if re.search(r"bank|wallet|money|loan|finance|pay", text):
        return "confidence"
    if re.search(r"game|battle|arcade|rpg|level", text):
        return "neon"
    if re.search(r"task|note|calendar|workflow|productivity", text):
        return "minimal"
    return "balanced"


def _derive_vibe_fingerprint(extracted_data: ExtractedAppData, style_bucket: str) -> Dict[str, str]:
    text = _normalize_text(extracted_data.app_name, extracted_data.short_description, extracted_data.full_description)
    if style_bucket == "finance":
        brand_tone = "trust-first"
        visual_bias = "proof-first"
    elif style_bucket in {"music", "gaming"}:
        brand_tone = "energetic"
        visual_bias = "media-first"
    elif style_bucket == "productivity":
        brand_tone = "practical"
        visual_bias = "text-first"
    else:
        brand_tone = "balanced"
        visual_bias = "text-first"

    if re.search(r"premium|pro|studio|plus", text):
        ui_mood = "premium"
    elif re.search(r"simple|minimal|easy|quick", text):
        ui_mood = "clean"
    elif re.search(r"battle|arcade|playlist|mix|discover", text):
        ui_mood = "immersive"
    else:
        ui_mood = "clean"

    if style_bucket in {"music", "gaming"}:
        content_energy = "high"
    elif style_bucket == "finance":
        content_energy = "medium"
    elif style_bucket == "productivity":
        content_energy = "low"
    else:
        content_energy = "medium"

    palette_hint = _infer_palette_hint(extracted_data)
    return {
        "brand_tone": brand_tone,
        "content_energy": content_energy,
        "visual_bias": visual_bias,
        "ui_mood": ui_mood,
        "palette_hint": palette_hint,
    }


def _format_fingerprint(vibe: Dict[str, str]) -> str:
    return ";".join([
        f"tone={vibe['brand_tone']}",
        f"energy={vibe['content_energy']}",
        f"bias={vibe['visual_bias']}",
        f"mood={vibe['ui_mood']}",
        f"palette={vibe['palette_hint']}",
    ])


def _apply_app_style_variation(style_bucket: str, extracted_data: ExtractedAppData, base_style: Dict[str, str], vibe: Dict[str, str]) -> Dict[str, str]:
    style = _derive_logo_palette(extracted_data, base_style)

    if style.get("palette_source") != "brand_logo":
        variants = PALETTE_VARIANTS.get(style_bucket, PALETTE_VARIANTS["default"])
        source = f"{extracted_data.app_id}:{extracted_data.app_name}:{vibe['palette_hint']}"
        selected = variants[_stable_variant_index(source, len(variants))]
        style.update(selected)
        style["palette_source"] = "category_fallback"

    style["visual_intensity"] = vibe["content_energy"]
    style["tone_variant"] = vibe["brand_tone"]
    style["motion_hint"] = "pulsed" if vibe["content_energy"] == "high" else ("subtle" if vibe["content_energy"] == "medium" else "minimal")
    style["section_order"] = "visual-first" if vibe["visual_bias"] == "media-first" else ("proof-first" if vibe["visual_bias"] == "proof-first" else "benefit-first")
    style["trust_level"] = "high" if style_bucket == "finance" else ("medium" if style_bucket in {"productivity", "default"} else "low")
    return style


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
    reviews = extracted_data.reviews or []
    cutoff_date = date.today() - timedelta(days=183)

    eligible_reviews = []
    for review in reviews:
        rating = int(review.get("rating", 0) or 0)
        text = str(review.get("text", "")).strip()
        if rating < 5 or not text:
            continue

        raw_date = str(review.get("date") or "").strip()
        if not raw_date:
            continue

        try:
            review_date = date.fromisoformat(raw_date)
        except ValueError:
            continue

        if review_date < cutoff_date:
            continue

        eligible_reviews.append({
            "rating": rating,
            "text": text,
            "reviewer": str(review.get("reviewer", "Anonymous")).strip(),
            "date": review_date,
        })

    if len(eligible_reviews) < 3:
        return []

    sorted_reviews = sorted(
        eligible_reviews,
        key=lambda r: (
            int(r.get("rating", 0) or 0),
            r.get("date") or date.min,
        ),
        reverse=True,
    )
    max_reviews = 3
    return [
        {
            "rating": int(r.get("rating", 0) or 0),
            "text": str(r.get("text", "")).strip(),
            "reviewer": str(r.get("reviewer", "Anonymous")).strip(),
        }
        for r in sorted_reviews
        if int(r.get("rating", 0) or 0) >= 5 and str(r.get("text", "")).strip()
    ][:max_reviews]


def _policy_reviews(extracted_data: ExtractedAppData) -> List[dict]:
    """Return the authoritative review set used by the strategy.

    We only promote review proof when there are at least 3 qualifying recent
    5-star reviews. Otherwise the page should not show review proof at all.
    """
    return _choose_reviews(extracted_data)


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


def _build_rules_strategy(extracted_data: ExtractedAppData) -> ContentStrategy:
    style_bucket = _detect_style_bucket(extracted_data)
    style_profile = STYLE_PROFILES.get(style_bucket, STYLE_PROFILES["default"])
    vibe = _derive_vibe_fingerprint(extracted_data, style_bucket)
    app_style_profile = _apply_app_style_variation(style_bucket, extracted_data, style_profile, vibe)

    benefits = _extract_benefits(extracted_data)
    selected_reviews = _policy_reviews(extracted_data)

    include_rating = extracted_data.rating is not None and extracted_data.rating >= 4.5
    main_angle = _build_main_angle(extracted_data, benefits, include_rating)

    missing_data_flags: List[str] = []
    if extracted_data.rating is None:
        missing_data_flags.append("rating_missing")
    elif extracted_data.rating < 4.5:
        missing_data_flags.append("rating_not_promoted_below_4_5")

    # For low-rated apps, avoid review-based social proof and focus on other value angles.
    if extracted_data.rating is None or extracted_data.rating < 4.2:
        selected_reviews = []
        missing_data_flags.append("reviews_hidden_for_low_rating")

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
            **app_style_profile,
        },
    )


def _enforce_strategy_policy(strategy: ContentStrategy, extracted_data: ExtractedAppData) -> ContentStrategy:
    style_bucket = _detect_style_bucket(extracted_data)
    style_profile = STYLE_PROFILES.get(style_bucket, STYLE_PROFILES["default"])
    vibe = _derive_vibe_fingerprint(extracted_data, style_bucket)
    app_style_profile = _apply_app_style_variation(style_bucket, extracted_data, style_profile, vibe)

    style = dict(strategy.style_guide or {})
    requested_template = str(style.get("template_id", style_profile["template_id"]))
    if requested_template not in ALLOWED_TEMPLATE_IDS:
        requested_template = style_profile["template_id"]

    merged_style = {
        "bucket": style_bucket,
        **app_style_profile,
        **style,
        "template_id": requested_template,
    }
    for key in ("color_primary", "color_secondary", "color_background", "color_surface", "color_text", "color_accent", "palette", "palette_source"):
        if key in app_style_profile:
            merged_style[key] = app_style_profile[key]
    merged_style = _enforce_style_contrast(merged_style, app_style_profile)

    # Enforce normalized style contract for template behavior.
    merged_style["visual_intensity"] = str(merged_style.get("visual_intensity", vibe["content_energy"]))
    merged_style["section_order"] = str(merged_style.get("section_order", "benefit-first"))
    merged_style["tone_variant"] = str(merged_style.get("tone_variant", vibe["brand_tone"]))
    merged_style["trust_level"] = str(merged_style.get("trust_level", "medium"))
    merged_style["motion_hint"] = str(merged_style.get("motion_hint", "minimal"))
    merged_style["palette_source"] = str(merged_style.get("palette_source", "brand_logo"))

    missing_data_flags = list(strategy.missing_data_flags or [])

    # Preserve analyzer-selected reviews (OpenAI + validation/fallback),
    # then enforce hard complaint filters again as a safety net.
    selected_reviews = list(strategy.selected_reviews or [])
    if not selected_reviews:
        selected_reviews = _policy_reviews(extracted_data)
    selected_reviews = _validate_openai_reviews(selected_reviews)

    if extracted_data.rating is None:
        if "rating_missing" not in missing_data_flags:
            missing_data_flags.append("rating_missing")
    elif extracted_data.rating < 4.5:
        if "rating_not_promoted_below_4_5" not in missing_data_flags:
            missing_data_flags.append("rating_not_promoted_below_4_5")

    if extracted_data.rating is None or extracted_data.rating < 4.2:
        selected_reviews = []
        if "reviews_hidden_for_low_rating" not in missing_data_flags:
            missing_data_flags.append("reviews_hidden_for_low_rating")

    if not selected_reviews and "no_good_recent_reviews" not in missing_data_flags:
        missing_data_flags.append("no_good_recent_reviews")

    if not extracted_data.installs and "installs_missing" not in missing_data_flags:
        missing_data_flags.append("installs_missing")

    if selected_reviews and "review_proof_enabled" not in missing_data_flags:
        missing_data_flags.append("review_proof_enabled")

    top_benefits = [b.strip() for b in (strategy.top_benefits or []) if b and b.strip()]
    if len(top_benefits) < 3:
        top_benefits = _extract_benefits(extracted_data)[:5]

    faq_topics = [q.strip() for q in (strategy.faq_topics or []) if q and q.strip()]
    if not faq_topics:
        faq_topics = _faq_topics_for_app(extracted_data)

    target_audience = (strategy.target_audience or "").strip()
    if not target_audience:
        target_audience = {
            "music": "Music and podcast listeners",
            "gaming": "Mobile gamers seeking immersive play",
            "finance": "Users managing money and financial decisions",
            "productivity": "Users who want to organize work and tasks",
            "default": "Mobile users looking for a better app experience",
        }.get(style_bucket, "Mobile users looking for a better app experience")

    tone = (strategy.tone or "").strip() or {
        "music": "Energetic and expressive",
        "gaming": "Bold and high-energy",
        "finance": "Trustworthy and precise",
        "productivity": "Clear and practical",
        "default": "Modern and benefit-led",
    }.get(style_bucket, "Modern and benefit-led")

    main_angle = (strategy.main_angle or "").strip() or _build_main_angle(
        extracted_data,
        top_benefits,
        include_rating=bool(extracted_data.rating is not None and extracted_data.rating >= 4.5),
    )

    return ContentStrategy(
        target_audience=target_audience,
        tone=tone,
        main_angle=main_angle,
        top_benefits=top_benefits[:5],
        selected_reviews=selected_reviews[:3],
        faq_topics=faq_topics[:4],
        missing_data_flags=missing_data_flags,
        style_guide=merged_style,
        strategy_source=strategy.strategy_source,
        fallback_reason=strategy.fallback_reason,
    )


def _analyze_with_openai(
    extracted_data: ExtractedAppData,
    prompt_text: str,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> ContentStrategy:
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")

    api_key = (
        os.getenv("OPENAI_API_KEY", "").strip()
        or os.getenv("GITHUB_PAT", "").strip()
        or os.getenv("GITHUB_TOKEN", "").strip()
    )
    if not api_key:
        raise RuntimeError("No API key is set (OPENAI_API_KEY/GITHUB_PAT/GITHUB_TOKEN)")

    model = model_name or os.getenv("ANALYZER_OPENAI_MODEL", "gpt-4o-mini")
    base_url = (
        os.getenv("OPENAI_BASE_URL", "").strip()
        or os.getenv("GITHUB_MODELS_BASE_URL", "").strip()
    )

    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    payload: dict[str, Any] = extracted_data.model_dump()
    user_input = (
        "Use the provided app data to generate ContentStrategy JSON only. "
        "No markdown and no extra text.\n\n"
        f"extracted_data:\n{payload}"
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            request_kwargs = {
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": user_input},
                ],
                "temperature": 0.2,
            }
            if max_output_tokens is not None:
                request_kwargs["max_tokens"] = max_output_tokens

            response = client.chat.completions.create(**request_kwargs)
            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("OpenAI returned empty analyzer output")
            parsed = ContentStrategy.model_validate_json(content)
            return parsed
        except Exception as e:
            last_error = e
            logger.warning("OpenAI analyzer attempt %d failed: %s", attempt + 1, e)

    raise RuntimeError(f"OpenAI analyzer failed after retries: {last_error}")


def analyze_content_strategy(
    extracted_data: ExtractedAppData,
    use_openai: bool | None = None,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> ContentStrategy:
    """Build content strategy with OpenAI-first flow and deterministic fallback."""
    prompt_text = load_prompt("analyzer")
    logger.info("Analyzer prompt loaded (%d chars)", len(prompt_text))

    if use_openai is None:
        use_openai = os.getenv("ANALYZER_USE_OPENAI", "1").strip().lower() not in {"0", "false", "no", "off"}

    if use_openai:
        try:
            strategy = _analyze_with_openai(
                extracted_data,
                prompt_text,
                model_name=model_name,
                max_output_tokens=max_output_tokens,
            )
            strategy = strategy.model_copy(update={
                "strategy_source": "openai",
                "fallback_reason": None,
            })
            # Validate OpenAI's review selection to filter out hidden complaints
            if strategy.selected_reviews:
                validated_reviews = _validate_openai_reviews(strategy.selected_reviews)
                strategy = strategy.model_copy(update={"selected_reviews": validated_reviews})
                # If validation filtered everything, use fallback
                if not validated_reviews:
                    logger.info("OpenAI reviews filtered by validation, applying keyword-based fallback")
                    best_reviews = _select_marketing_reviews(extracted_data.reviews)
                    strategy = strategy.model_copy(update={"selected_reviews": best_reviews})
            else:
                # OpenAI didn't select any, apply keyword fallback
                logger.info("OpenAI didn't select reviews, applying keyword-based fallback")
                best_reviews = _select_marketing_reviews(extracted_data.reviews)
                strategy = strategy.model_copy(update={"selected_reviews": best_reviews})
            return _enforce_strategy_policy(strategy, extracted_data)
        except Exception as e:
            logger.warning("Analyzer OpenAI path failed, using rules fallback: %s", e)
            fallback = _build_rules_strategy(extracted_data)
            fallback = fallback.model_copy(update={
                "strategy_source": "fallback_rules",
                "fallback_reason": str(e),
            })
            # Apply keyword-based review selection to fallback
            best_reviews = _select_marketing_reviews(extracted_data.reviews)
            fallback = fallback.model_copy(update={"selected_reviews": best_reviews})
            return _enforce_strategy_policy(fallback, extracted_data)

    # OpenAI disabled - use rules-based fallback
    fallback = _build_rules_strategy(extracted_data)
    fallback = fallback.model_copy(update={
        "strategy_source": "fallback_rules",
        "fallback_reason": "openai_disabled",
    })
    # Apply keyword-based review selection
    best_reviews = _select_marketing_reviews(extracted_data.reviews)
    fallback = fallback.model_copy(update={"selected_reviews": best_reviews})
    return _enforce_strategy_policy(fallback, extracted_data)
