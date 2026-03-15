# Project: Nutrition Feedback Assistant

## Overview
A web application for a nutrition coach working with 30+ clients weekly.
Clients fill a daily Google Form (7 days/week). The coach uploads the weekly
CSV export and the app generates personalized feedback in Romanian for each client.

## Tech Stack
- Python 3.12
- FastAPI (single file: main.py)
- Claude API (Anthropic) — loaded from .env as CLAUDE_API_KEY
- pandas (CSV parsing)
- python-dotenv
- CORS middleware enabled (needed for frontend)
- Storage: data/storage.json (client history across weeks)

## CSV Structure
One row per day per client. Columns:
- Timestamp, Name+Surname, Email
- Breakfast (what they ate)
- How they felt before breakfast
- How they felt after breakfast
- Lunch (what they ate)
- How they felt before lunch
- How they felt after lunch
- Dinner (what they ate)
- How they felt before dinner
- How they felt after dinner
- Snack (what they ate, optional)
- How they felt before snack
- How they felt after snack
- Intestinal transit (yes/no + description)
- Exercise/movement today (yes/no + description)
- Mindful eating (yes/no)

## API Endpoints
- GET /health
- POST /upload-csv — upload weekly CSV, parse and store by client
- GET /clients — list all clients found in uploaded data
- POST /feedback/{email} — generate weekly feedback for one client
- GET /history/{email} — get past feedbacks for a client

## Feedback Rules (CRITICAL — always follow these)
Always write feedback in Romanian. Tone: warm, encouraging, professional.

1. BREAKFAST: At least 80% savory (no large carbs/sugar/high-GI). 
   90% protein-rich (clients are women 37-60yo, many exercise regularly).

2. VEGETABLES: Present in at least 80% of all meals.

3. MEAL STRUCTURE: 3 main meals/day, ~4 hour intervals.
   Snacks only if interval >4h, maximum 4 days out of 7.

4. EXERCISE: Mention 8,000+ steps or other movement daily.
   If not mentioned, encourage consistent movement.

5. BOWEL TRANSIT: Daily ideally, minimum every 2 days.

6. FAT: Main meals should not be too high in fat (for weight loss).
   All meals should contain a good protein source.

7. FIBER: Total 20-30g fiber per day across all meals.

8. EMOTIONAL EATING: If occasional — normalize it warmly.
   If daily — gently ask what might be happening emotionally.

9. PLANT-BASED/FASTING: Many clients eat plant-based during fasting
   periods. Acknowledge lower protein, suggest plant-based protein sources.

10. MINDFUL EATING: If present — congratulate warmly.
    If absent — briefly mention its importance.

11. HISTORY: Always compare to previous weeks when available.
    Reference progress explicitly ("față de săptămâna trecută...").

12. CONGRATULATE genuine progress and good habits specifically.
    Never be generic. Always reference actual foods and days.

## Coding Rules
- Type hints on all functions
- try/except on every endpoint
- Never hardcode API key
- Ask before creating new files
- Single main.py
- CORS enabled for all origins