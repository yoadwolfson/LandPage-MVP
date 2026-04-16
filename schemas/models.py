from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ExtractedAppData(BaseModel):
    """
    Structured data extracted from Google Play app page.
    Passed to Analyzer agent for content strategy generation.
    """
    app_id: str = Field(..., description="Google Play app ID (e.g., com.example.app)")
    app_name: str = Field(..., description="App name as shown on Play Store")
    developer_name: Optional[str] = Field(default=None, description="App maker / developer name")
    short_description: str = Field(..., description="Brief one-liner description")
    full_description: str = Field(..., description="Complete detailed description")
    icon_url: str = Field(..., description="URL to app icon image")
    screenshots: List[str] = Field(default_factory=list, description="List of screenshot URLs")
    rating: Optional[float] = Field(default=None, description="Rating out of 5.0")
    installs: Optional[str] = Field(default=None, description="Number of installs (e.g., '1M+', '500K+')")
    reviews: Optional[List[dict]] = Field(
        default_factory=list,
        description="List of user reviews with rating and text"
    )
    last_updated: Optional[str] = Field(default=None, description="Last update date")
    current_version: Optional[str] = Field(default=None, description="Current app version")
    min_android_version: Optional[str] = Field(default=None, description="Min Android requirement")
    
    class Config:
        json_schema_extra = {
            "example": {
                "app_id": "com.example.app",
                "app_name": "Example App",
                "developer_name": "Example Studio",
                "short_description": "The best example app ever",
                "full_description": "This is a detailed description...",
                "icon_url": "https://example.com/icon.png",
                "screenshots": ["https://example.com/screen1.png"],
                "rating": 4.8,
                "installs": "1M+",
                "reviews": [
                    {"rating": 5, "text": "Great app!", "reviewer": "User1"},
                    {"rating": 4, "text": "Good, but needs improvement", "reviewer": "User2"}
                ],
                "last_updated": "2024-01-15",
                "current_version": "1.0.0",
                "min_android_version": "7.0"
            }
        }


class ReviewSnippet(BaseModel):
    """Selected review highlight for social proof"""
    rating: int = Field(..., description="Review rating (1-5)")
    text: str = Field(..., description="Review snippet text")
    reviewer: Optional[str] = Field(default=None, description="Reviewer name")


class ContentStrategy(BaseModel):
    """
    Content strategy determined by Analyzer agent.
    Guides the Composer agent for landing page generation.
    """
    target_audience: str = Field(..., description="Who this landing page targets")
    tone: str = Field(..., description="Tone of messaging (e.g., professional, casual, playful)")
    main_angle: str = Field(..., description="Primary value proposition angle")
    top_benefits: List[str] = Field(..., description="3-5 key benefits to highlight")
    selected_reviews: List[ReviewSnippet] = Field(
        default_factory=list,
        description="High-quality review snippets (preferred rating >= 4.5)"
    )
    faq_topics: List[str] = Field(
        default_factory=list,
        description="FAQ topics to address"
    )
    missing_data_flags: List[str] = Field(
        default_factory=list,
        description="Fields that were missing (for graceful degradation)"
    )
    style_guide: dict[str, str] = Field(
        default_factory=dict,
        description="Visual style decisions for the landing page (theme/palette/typography/direction)"
    )
    strategy_source: str = Field(
        default="fallback_rules",
        description="Source of strategy generation: openai or fallback_rules"
    )
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Why fallback was used when strategy_source=fallback_rules"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "target_audience": "Productivity-focused professionals",
                "tone": "Professional and empowering",
                "main_angle": "Save 2 hours per day with smart automation",
                "top_benefits": [
                    "Automate repetitive tasks",
                    "Sync across all devices",
                    "24/7 cloud backup"
                ],
                "selected_reviews": [
                    {"rating": 5, "text": "Changed my workflow!", "reviewer": "ProductManager123"}
                ],
                "faq_topics": ["Privacy", "Pricing", "Integration"],
                "missing_data_flags": [],
                "style_guide": {
                    "bucket": "productivity",
                    "theme": "clean-focus",
                    "palette": "light neutral with single accent",
                    "visual_direction": "clear hierarchy, concise copy, practical UI",
                    "typography": "readable sans with medium contrast headings",
                    "color_primary": "#2563EB",
                    "color_secondary": "#334155",
                    "color_background": "#F8FAFC",
                    "color_surface": "#FFFFFF",
                    "color_text": "#0F172A",
                    "color_accent": "#F59E0B"
                },
                "strategy_source": "openai",
                "fallback_reason": None
            }
        }


class BenefitCard(BaseModel):
    """Single benefit/feature card for landing page"""
    title: str = Field(..., description="Benefit title")
    description: str = Field(..., description="Benefit description (1-2 sentences)")
    icon_emoji: Optional[str] = Field(default="✨", description="Emoji or icon representation")


class FAQItem(BaseModel):
    """Single FAQ entry"""
    question: str = Field(..., description="FAQ question")
    answer: str = Field(..., description="FAQ answer (clear and concise)")


class LandingPageContent(BaseModel):
    """
    Final landing page content ready for rendering.
    Generated by Composer agent, ready for Jinja2 template.
    """
    hero_headline: str = Field(..., description="Main headline (short, punchy)")
    hero_subheadline: str = Field(..., description="Subheadline (supporting text)")
    hero_image_url: str = Field(..., description="Hero image (usually app icon or screenshot)")
    
    benefits: List[BenefitCard] = Field(..., description="3-5 benefit cards")
    
    social_proof_headline: str = Field(
        default="Loved by users",
        description="Social proof section headline"
    )
    social_proof_rating: Optional[float] = Field(default=None, description="App rating")
    social_proof_installs: Optional[str] = Field(default=None, description="Number of installs")
    social_proof_reviews: List[ReviewSnippet] = Field(
        default_factory=list,
        description="Selected review quotes"
    )
    
    screenshots: List[str] = Field(
        default_factory=list,
        description="Screenshot URLs for gallery"
    )
    
    faq_items: List[FAQItem] = Field(
        default_factory=list,
        description="FAQ section items"
    )
    
    cta_text: str = Field(default="Install on Google Play", description="Main CTA button text")
    cta_url: str = Field(..., description="CTA target URL (Google Play)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "hero_headline": "Automate Your Workflow",
                "hero_subheadline": "Save 2 hours every day with intelligent task automation",
                "hero_image_url": "https://example.com/app-icon.png",
                "benefits": [
                    {
                        "title": "100% Automation",
                        "description": "Set it once, run forever",
                        "icon_emoji": "⚡"
                    }
                ],
                "social_proof_rating": 4.8,
                "social_proof_installs": "1M+",
                "cta_url": "https://play.google.com/store/apps/details?id=com.example"
            }
        }


class PipelineOutput(BaseModel):
    """
    Complete output from the entire pipeline.
    Includes all intermediate results and final HTML.
    """
    run_id: str = Field(..., description="Unique run identifier")
    timestamp: str = Field(..., description="Run timestamp")
    google_play_url: str = Field(..., description="Input Google Play URL")
    
    extracted_data: ExtractedAppData = Field(..., description="Extracted app data")
    strategy: ContentStrategy = Field(..., description="Content strategy")
    landing_content: LandingPageContent = Field(..., description="Final landing page content")
    
    html_file: str = Field(..., description="Path to generated HTML file")
    artifacts_folder: str = Field(..., description="Path to artifacts folder with JSONs")
    
    status: str = Field(default="success", description="Pipeline status (success/partial/error)")
    error_message: Optional[str] = Field(default=None, description="Error details if any")
    
    class Config:
        json_schema_extra = {
            "example": {
                "run_id": "run_20240115_143052",
                "timestamp": "2024-01-15T14:30:52",
                "google_play_url": "https://play.google.com/store/apps/details?id=com.example",
                "status": "success"
            }
        }
