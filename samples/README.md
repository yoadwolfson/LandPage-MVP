# Sample Data Files

These files show the exact JSON format that each agent should produce. Use these as reference when implementing agents.

## 1. extracted_app_data.json
**Produced by**: Extractor Agent  
**Input**: Google Play URL  
**Output format**: `ExtractedAppData` Pydantic model

This is the raw, extracted data from a Google Play page. The Extractor agent should:
- Scrape the Play Store page using Playwright/BeautifulSoup
- Extract all fields shown in this file
- Use Optional fields with None as default if data is unavailable
- Include at least 2-3 review snippets if available
- Validate that required fields (app_id, app_name, etc.) are always present

## 2. content_strategy.json
**Produced by**: Analyzer Agent  
**Input**: `ExtractedAppData`  
**Output format**: `ContentStrategy` Pydantic model

This is the strategy document that guides content creation. The Analyzer agent should:
- Read the extracted data
- Use LLM to determine target audience and tone
- Identify top 3-5 benefits from the description
- Select only high-quality reviews (rating >= 4.5)
- Generate FAQ topics based on the description
- Output strategy that is clear and actionable for the Composer

## 3. landing_page_content.json
**Produced by**: Composer Agent  
**Input**: `ExtractedAppData` + `ContentStrategy`  
**Output format**: `LandingPageContent` Pydantic model

This is the final content, ready for HTML rendering. The Composer agent should:
- Use the strategy to guide messaging
- Extract data from ExtractedAppData to populate fields
- Create persuasive hero headline and subheadline (max 60 chars each)
- Generate 4 benefit cards with emoji icons
- Include social proof section with rating and reviews
- List 3 FAQ items with Q&A
- Set CTA button text and Google Play URL
- Ensure all text is clear, concise, and formatted for a landing page

---

## Data Flow
```
Google Play URL
        ↓
   [Extractor Agent]
        ↓
  extracted_app_data.json
        ↓
   [Analyzer Agent]
        ↓
  content_strategy.json
        ↓
   [Composer Agent]
        ↓
  landing_page_content.json
        ↓
   [Jinja2 Template]
        ↓
    index.html
```

## Validation Rules

1. **ExtractedAppData**: 
   - Required: app_id, app_name, short_description, full_description, icon_url
   - Optional: rating, installs, reviews, screenshots

2. **ContentStrategy**:
   - Required: target_audience, tone, main_angle, top_benefits
   - Select reviews with rating >= 4.5
   - Flag missing data in `missing_data_flags`

3. **LandingPageContent**:
   - Required: hero_headline, hero_subheadline, benefits (minimum 3), cta_url
   - All text fields should be human-readable and grammatically correct
   - Benefits should have emoji icons for visual appeal

---

## Testing

To test each agent independently:

1. **Test Extractor**: Run with a real Google Play URL, verify extracted_app_data matches this schema
2. **Test Analyzer**: Pass extracted_app_data.json, verify output matches content_strategy schema
3. **Test Composer**: Pass both JSONs, verify output matches landing_page_content schema
