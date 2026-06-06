# Hernandez Family Agent — Juanito

A shared AI assistant for the Hernandez family that connects Google Calendar to a Telegram group bot. Juanito speaks Venezuelan Spanish and English, manages the family calendar through natural language, sends smart proactive reminders, and keeps a living shopping list — all through Telegram.

## Features

- **Natural language calendar:** Any family member can say "Add Paola's math exam Friday at 9am" or "What do we have this week?" and Juanito reads or writes Google Calendar accordingly. Always confirms before making changes.
- **Delete and edit events:** "Move the dentist to Thursday at 4pm" or "Cancel the team call" — Juanito finds the event, confirms, and updates or removes it.
- **Recurring events:** "Add Sunday mass every week for the rest of the year" — Juanito uses RRULE format to create one recurring event instead of many.
- **Morning briefing:** Every day at 5:45am, Juanito posts today's and tomorrow's events to the family group.
- **Smart pre-event reminders:** One hour before any event, Juanito sends a context-aware reminder — sports events get warm-up tips, exams get study resources, everything gets relevant web-sourced content with links.
- **Universal event enrichment:** For any enrichable event (mass, concert, doctor visit, practice), Juanito searches Wikipedia, YouTube, USCCB, Khan Academy, and other approved sources to add genuinely useful context and links.
- **Living shopping list:** "Add milk and eggs" -> list updated. "I'm heading to Costco" -> Juanito replies with the full list. The list lives inside the next grocery calendar event.
- **Shopping price research:** Juanito can compare current prices and package value across trusted Canadian retailer websites for explicit items or the current shopping list.
- **Conflict detection:** When a new event is created, Juanito checks for time overlaps and flags pickup logistics for kids activities.
- **Slash commands:** /today, /week, /list, /help for quick access without typing a full message.
- **Bilingual:** Juanito follows whoever is writing — English gets a reply in English with Venezuelan flavour, Spanish gets full venezolano.
- **Image understanding:** Send a photo or image document in Telegram and Juanito can read invitations, schedules, flyers, and other useful details. Event details still require confirmation before being added.
- **Opportunity Scout:** Finds a small number of Ottawa-area activities that fit real family calendar openings, interests, travel limits, age ranges, and budget. Recommendations can be saved, dismissed, or added with preparation and travel buffers.

## Prerequisites

- Python 3.11+
- uv package manager (https://docs.astral.sh/uv/)
- A Telegram bot token from @BotFather
- An OpenAI API key (gpt-4o)
- A Google Cloud project with the Calendar API enabled

## Setup

Clone the repo:

    git clone https://github.com/DarwinJavier/family-planner.git
    cd family-planner

Install dependencies:

    uv sync

Configure environment variables:

    cp .env.example .env

Then open .env and fill in your values:

| Variable | Required | Description |
|---|---|---|
| TELEGRAM_BOT_TOKEN | Yes | From @BotFather -> /newbot |
| OPENAI_API_KEY | Yes | From platform.openai.com |
| GOOGLE_CALENDAR_ID | Yes | From Google Calendar settings -> Integrate calendar |
| GOOGLE_CREDENTIALS_FILE | Yes | Path to your OAuth client JSON — default: credentials.json |
| FAMILY_CHAT_ID | Yes | Telegram group chat ID — use @userinfobot to find it |
| DARWIN_USER_ID | Yes | Darwin's Telegram user ID |
| WIFE_USER_ID | Yes | Wife's Telegram user ID |
| PAOLA_USER_ID | Yes | Paola's Telegram user ID |
| TIMEZONE | Yes | e.g. America/Toronto |

## Google Calendar setup

1. Go to Google Cloud Console and create a project
2. Enable the Google Calendar API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download credentials.json and place it in the project root
5. First run will open a browser for OAuth consent — token saved to token.json automatically
6. Set GOOGLE_CALENDAR_ID in .env (find it in Google Calendar -> Settings -> Integrate calendar)

## Telegram bot setup

1. Message @BotFather -> /newbot -> copy the token to .env
2. Create a Telegram group, add the bot, and make it an admin
3. Send a message to the group, then fetch https://api.telegram.org/bot<TOKEN>/getUpdates to get FAMILY_CHAT_ID
4. Get each family member's user ID from @userinfobot

Register slash commands with @BotFather so they appear in Telegram's menu:

    /setcommands -> select your bot -> paste:
    today - Today's schedule
    week - This week at a glance
    list - Current shopping list
    prices - Compare shopping-list prices
    scout - Local activities that fit our calendar
    scout_preferences - Opportunity Scout preferences
    help - What I can do

## Run

    uv run main.py

The bot starts polling and the scheduler activates. All three family members can interact immediately via the Telegram group. Logs are written to logs/family-agent.log (daily rotation, 7 days retained).

To manually trigger the morning briefing or pre-event reminder for testing:

    uv run scripts/test_briefing.py
    uv run scripts/test_reminder.py

## Opportunity Scout

Run `/scout` to receive up to five ranked local activity recommendations. Scout reads the next 14 days of the shared calendar, excludes configured protected/recovery periods, and only recommends activities that fit after preparation and round-trip travel.

Commands:

    /scout
    /scout_add RECOMMENDATION_ID
    /scout_save RECOMMENDATION_ID
    /scout_dismiss RECOMMENDATION_ID
    /scout_more RECOMMENDATION_ID
    /scout_preferences
    /scout_interest family|older_child|younger_child INTEREST
    /scout_hide CATEGORY

Calendar adds always require confirmation. The created calendar block includes preparation and travel time, the official source URL, estimated cost, and relevant family members. Scout checks for conflicts before asking for confirmation and avoids recommending titles already on the calendar.

Configuration lives in `config/opportunity_scout.yaml`. Editable preferences and feedback are written to ignored local files:

    data/opportunity_preferences.json
    data/opportunity_state.json

Opportunity Scout uses a configured public web-search adapter plus a validated mock Ottawa fallback in `opportunity/sources.py`. The public adapter can use Ottawa Is Not Boring as an editorial discovery lead, validates structured results, and asks for official-page verification. Mock-event details remain examples and explicitly warn the family to verify them. No new environment variables or database migrations are required. Future providers should implement the `EventSource` protocol and use a permitted API or public feed.

Discovery-source policy lives in `config/opportunity_sources.yaml`. Ottawa Is Not Boring is enabled as an editorial discovery lead. Community Facebook groups are intentionally disabled for automated access: Juanito must not scrape or bypass login, and community posts should be verified against official event pages before recommendation.

Use `/prices` to compare the current shopping list, or `/prices ITEM` for an explicit item. Price research:

- Prioritizes retailers named in the request, such as `/prices milk at Walmart`.
- Chooses likely sources by product type: grocery, electronics, hardware, office, home, or automotive.
- Searches each item separately for more specific results.
- Rejects homepages, search pages, category pages, invalid prices, and retailer/domain mismatches.
- Runs a second web-search pass to verify the product link and price claim.
- Shows only verified or clearly labeled uncertain offers.

Official product pages are preferred. Specific current Flipp offers may be used as labeled flyer evidence, and specific Instacart listings may be used only as uncertain delivery pricing. Results include the exact product/variant, package size/unit value when available, and label sale, membership, marketplace, or delivery-only pricing. Diagnostics explain when weak candidates were filtered out. Results are cached locally in ignored `data/shopping_price_cache.json`; prices should still be checked before purchase because retailers can change them quickly.

Run all automated tests:

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

## Deploy to Railway

Juanito should run as one always-on Railway service. Do not run multiple replicas, because Telegram polling and scheduled reminders can duplicate messages.

1. Push the repo to a private GitHub repository.
2. In Railway, create a new project from that GitHub repo.
3. Railway will use `railway.toml` and start the bot with:

       uv run main.py

4. Add these Railway variables:

   | Variable | Description |
   |---|---|
   | TELEGRAM_BOT_TOKEN | Bot token from @BotFather |
   | OPENAI_API_KEY | OpenAI API key |
   | ANTHROPIC_API_KEY | Anthropic API key, if enrichment still uses it |
   | GOOGLE_CALENDAR_ID | Family calendar ID |
   | GOOGLE_CREDENTIALS_JSON | Full contents of local credentials.json |
   | GOOGLE_TOKEN_JSON | Full contents of local token.json |
   | FAMILY_CHAT_ID | Telegram family group chat ID |
   | DARWIN_USER_ID | Darwin's Telegram user ID |
   | WIFE_USER_ID | Wife's Telegram user ID |
   | PAOLA_USER_ID | Paola's Telegram user ID |
   | TIMEZONE | Example: America/Toronto |

5. Set replicas to 1.
6. Deploy, then check Railway logs for `Bot is running. Press Ctrl+C to stop.`
7. Send `/today` in the Telegram group to confirm Juanito can read Google Calendar.

Keep `.env`, `credentials.json`, and `token.json` out of GitHub. They are listed in `.gitignore`; Railway should receive their values only as variables.

## Project structure

    family-planner/
    |-- main.py                      # Entry point — starts bot + scheduler
    |-- .env                         # Secrets — never commit
    |-- .env.example                 # Template for secrets
    |-- credentials.json             # Google OAuth client secret — never commit
    |-- token.json                   # Google OAuth token (auto-generated) — never commit
    |
    |-- agent/
    |   |-- brain.py                 # OpenAI gpt-4o agentic loop — Juanito's reasoning
    |   |-- tools.py                 # Tool definitions and handlers (calendar, shopping list)
    |   `-- enrichment.py           # Universal event enrichment via OpenAI web search
    |
    |-- bot/
    |   |-- handlers.py              # Telegram message handler — routes to agent brain
    |   `-- commands.py              # /today, /week, /list, /help handlers
    |
    |-- gcal/
    |   |-- auth.py                  # OAuth 2.0 flow, saves token.json
    |   `-- client.py                # get_events, create_event, delete_event, update_event, etc.
    |
    |-- scheduler/
    |   `-- jobs.py                  # Morning briefing (5:45am) + pre-event check (every 30 min)
    |
    |-- storage/
    |   |-- memory.py                # In-memory conversation history per Telegram user
    |   `-- shopping_list.py         # Reads/writes [agent] block in grocery calendar event
    |
    |-- opportunity/
    |   |-- models.py                # Validated external activity and recommendation models
    |   |-- sources.py               # EventSource adapter protocol + Phase 1 mock source
    |   |-- preferences.py           # Editable preferences and feedback persistence
    |   `-- service.py               # Free windows, scoring, discovery, and calendar proposals
    |
    |-- config/
    |   |-- rules.yaml               # Event type keywords, reminder timing, pickup flags
    |   `-- opportunity_scout.yaml   # Availability rules and transparent scoring weights
    |
    |-- scripts/
    |   |-- test_calendar.py         # Manual test for Google Calendar auth and read
    |   |-- test_briefing.py         # Manually trigger morning briefing
    |   `-- test_reminder.py         # Manually trigger pre-event reminder check
    |
    `-- logs/
        `-- family-agent.log         # Daily rotating log (auto-created)
