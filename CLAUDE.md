# Javier Family Agent

A shared AI assistant for the Javier family (Darwin, wife, and Paola) that connects Google Calendar to a Telegram group bot. The agent proactively notifies the family, answers questions, manages a shared shopping list, and enriches calendar events with useful context (study tips, warm-up routines, store info).

---

## Project goals

- All three family members can interact with the agent equally via Telegram
- Native iOS push notifications via Telegram (no extra app setup beyond Telegram)
- Google Calendar is the single source of truth — the agent reads and writes to it
- Agent enriches events automatically (exam prep, sports tips, shopping lists)
- MVP runs locally on Darwin's ASUS VivoBook; future deployment on Railway

---

## Stack

| Layer | Tool |
|---|---|
| Language | Python (managed with uv) |
| Agent brain | OpenAI API — gpt-4o (OPENAI_API_KEY) |
| Calendar | Google Calendar API (OAuth 2.0) |
| Family interface | Telegram Bot API (python-telegram-bot) |
| Notifications | Telegram push (native, no extra setup) |
| Scheduler | APScheduler (runs inside the bot process locally) |
| Web enrichment | Anthropic web search tool |
| Hosting (future) | Railway (Hobby plan ~$5 USD/month) |

---

## Project structure

```
family-agent/
├── CLAUDE.md
├── plan.md
├── README.md
├── .env                             # secrets — never commit
├── .env.example                     # template for secrets
├── .gitignore
├── pyproject.toml                   # uv project config
├── main.py                          # entry point — starts bot + scheduler
│
├── bot/
│   ├── __init__.py
│   ├── handlers.py                  # Telegram message handlers
│   └── commands.py                  # /today, /week, /list, /help
│
├── agent/
│   ├── __init__.py
│   ├── brain.py                     # Anthropic API calls — main reasoning loop
│   ├── tools.py                     # tool definitions (calendar, list, enrichment)
│   └── enrichment.py               # web search for exam prep, sports tips
│
├── gcal/
│   ├── __init__.py
│   ├── auth.py                      # OAuth 2.0 flow, saves token.json
│   └── client.py                    # get_events(), create_event(), check_conflicts()
│
├── scheduler/
│   ├── __init__.py
│   └── jobs.py                      # morning briefing + pre-event reminder jobs
│
├── storage/
│   ├── __init__.py
│   └── memory.py                    # in-memory conversation history per user
│
├── config/
│   └── rules.yaml                   # event types, keywords, reminder timing, behaviour rules
│
├── data/
│   ├── preferences.json             # per-user language and notification preferences
│   └── .gitkeep
│
├── scripts/
│   └── test_calendar.py             # manual test script for calendar auth
│
├── logs/
│   └── .gitkeep
│
└── credentials.json                 # Google OAuth client secret — never commit
```

---

## Environment variables

```
# .env.example

# Telegram
TELEGRAM_BOT_TOKEN=

# Anthropic
ANTHROPIC_API_KEY=

# Google Calendar
GOOGLE_CALENDAR_ID=
GOOGLE_CREDENTIALS_FILE=credentials.json   # OAuth client secret from Google Cloud

# Family Telegram user IDs (for access control)
FAMILY_CHAT_ID=        # the group chat ID
DARWIN_USER_ID=
WIFE_USER_ID=
PAOLA_USER_ID=

# Scheduler timezone
TIMEZONE=America/Toronto
```

---

## Core features — MVP scope

### 1. Natural language calendar interaction
Any family member can send a message like:
- *"Add Paola's math exam Friday at 9am"*
- *"What does our week look like?"*
- *"When is my dentist appointment?"*

The agent interprets the message, calls the Google Calendar API, and replies in the group.

### 2. Proactive morning briefing
Every day at 7:00am the bot posts a digest to the family group:
- Today's events for each family member
- Tomorrow's events as a heads-up
- Any flagged conflicts

### 3. Pre-event smart reminders
1 hour before a calendar event the bot sends a context-aware message:
- Basketball / sports → warm-up tips, hydration reminder
- Exam / test → subject summary, 3–5 practice questions (via web search)
- Grocery run → current shopping list

Event type is detected from keywords in the event title/description.

### 4. Living shopping list
- Any family member says *"Add milk and eggs to the list"* → agent updates the list
- Darwin says *"I'm going to Costco"* → bot replies with the full current list
- List is stored in the `[agent]` block of the next grocery calendar event's description
- If no grocery event exists, agent prompts: *"Should I add a Costco trip to the calendar first?"*

### 5. Conflict detection
When a new event is added, the agent checks for overlaps and flags logistics gaps:
- *"Darwin is travelling Friday but Paola has basketball at 5pm — who's on pickup?"*

---

## Storage model

Three distinct layers — each type of data belongs in exactly one place:

**1. Google Calendar event description — event-specific data**
Stored in a structured `[agent]` block at the bottom of the event description. Human-readable content sits above it; the agent reads and writes only its own block.

```
Paola's basketball game vs St. Thomas

📍 Carleton Place Arena
🕔 4:00pm warmup, 5:00pm tip-off

---
[agent]
type: sports
sport: basketball
pickup_needed: true
[/agent]
```

What lives here: event type tag, sport/subject name, pickup flag, shopping list for grocery events, any event-specific notes.

**2. `data/` folder — family-wide persistent state**
JSON files for state that spans across events and sessions.

```
data/
└── preferences.json     # per-user language preference, notification settings
```

What lives here: user preferences, anything that applies across all interactions.

**3. `config/rules.yaml` — agent behaviour config**
Static configuration that defines how the agent behaves. Edited by Darwin, not by the agent at runtime.

```yaml
event_types:
  sports:
    keywords: [basketball, soccer, practice, training, game, match]
    reminder_hours_before: 1
    enrichment: sports_tips
  exam:
    keywords: [exam, test, quiz, midterm, final]
    reminder_hours_before: 12
    enrichment: exam_prep
  grocery:
    keywords: [costco, grocery, supermarket, walmart, metro]
    reminder_hours_before: 0

notifications:
  morning_briefing_time: "07:00"
  timezone: America/Toronto

behaviour:
  confirm_before_write: true
  enrichment: always
  language_default: en
```

What lives here: keyword mappings, reminder timing, agent behaviour switches.

**4. In-memory — conversation history**
Stored in a Python dict keyed by Telegram user ID. Resets when the bot restarts. Sufficient for MVP since conversations are short and context doesn't need to survive restarts.

---

## Key decisions

| Decision | Choice | Reason |
|---|---|---|
| Google auth | OAuth 2.0 (browser flow) | Simpler setup for MVP, no service account needed |
| Conversation memory | In-memory dict | Resets on restart — fine for short family conversations |
| Shopping list storage | Calendar event `[agent]` block | Keeps all event data in one place, visible in Google Calendar |
| Web enrichment | Always on for sports and exam events | Better family experience, no manual triggering needed |
| Confirm before writes | Always | Prevents accidental calendar changes, builds family trust in the bot |

---



- Always respond in the same language the family member used (English or Spanish)
- Keep responses concise — this is a family chat, not an essay
- For calendar writes, always confirm before creating: *"Got it — should I add Paola's exam on Friday May 2 at 9am?"*
- For enrichment content (study tips, warm-up routines), keep it practical and brief — 3–5 bullet points max
- Never expose raw API errors to the family chat — log them and reply with a friendly fallback
- Paola is a minor — keep all content age-appropriate

---

## Google Calendar setup

1. Go to Google Cloud Console → create a project
2. Enable the Google Calendar API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `credentials.json` and place it in the project root
5. First run will open a browser for OAuth consent — token saved to `token.json`
6. Share the existing family Google Calendar with the service account or use the OAuth user's calendar
7. Set `GOOGLE_CALENDAR_ID` in `.env` (find it in Google Calendar settings → Integrate calendar)

---

## Telegram bot setup

1. Message @BotFather on Telegram → `/newbot`
2. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`
3. Create a Telegram group, add the bot, and make it an admin
4. Send a message to the group, then call `https://api.telegram.org/bot<TOKEN>/getUpdates` to get the `FAMILY_CHAT_ID`
5. Set each family member's Telegram user ID in `.env` (use @userinfobot to find IDs)

---

## Running locally (MVP)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project and install dependencies
uv init family-agent
cd family-agent
uv add anthropic python-telegram-bot google-auth google-auth-oauthlib \
        google-api-python-client apscheduler python-dotenv

# Copy and fill in secrets
cp .env.example .env

# First run — triggers Google OAuth in browser
uv run main.py
```

The bot will stay running in the terminal. All three family members can interact with it via the Telegram group immediately.

---

## Build phases

### Phase 1 — Foundation (start here)
- [ ] Telegram bot receives and replies to messages
- [ ] Google Calendar read: agent can answer "what's on today?"
- [ ] Google Calendar write: agent can create events from natural language
- [ ] All three family members verified in the group

### Phase 2 — Proactive notifications
- [ ] Morning briefing cron job (7am daily)
- [ ] Pre-event reminder cron job (1 hour before)
- [ ] Event type detection (sports, exam, grocery)

### Phase 3 — Enrichment
- [ ] Web search for exam subject summaries
- [ ] Web search for sport-specific warm-up tips
- [ ] Store hours lookup for grocery events

### Phase 4 — Smart features
- [ ] Living shopping list (add/view/clear)
- [ ] Conflict detection on new event creation
- [ ] Weekly Sunday summary

---

## Future: deploy to Railway

When the family is happy with the MVP:
1. Push repo to GitHub (ensure `.env` is in `.gitignore`)
2. Create Railway project → connect GitHub repo
3. Add all `.env` variables in Railway's environment settings
4. Railway auto-detects Python and deploys
5. Bot runs 24/7 — no laptop needed

Estimated cost: ~$5 USD/month (Hobby plan, well within included credits for this workload).

---

## What not to build (MVP constraints)

- No web app or dashboard — Telegram is the interface
- No database — calendar event descriptions + JSON preferences file is enough
- No multi-calendar support — one shared family calendar only
- No voice transcription — text input only for now
- No Railway deployment until Phase 1–2 are stable locally
- No persistent conversation memory — in-memory only, resets on restart
