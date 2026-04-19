# Hernandez Family Agent — Juanito

A shared AI assistant for the Hernandez family that connects Google Calendar to a Telegram group bot. Juanito speaks Venezuelan Spanish and English, manages the family calendar through natural language, sends smart proactive reminders, and keeps a living shopping list — all through Telegram.

## Features

- **Natural language calendar:** Any family member can say "Add Paola's math exam Friday at 9am" or "What do we have this week?" and Juanito reads or writes Google Calendar accordingly. Always confirms before making changes.
- **Delete and edit events:** "Move the dentist to Thursday at 4pm" or "Cancel the team call" — Juanito finds the event, confirms, and updates or removes it.
- **Recurring events:** "Add Sunday mass every week for the rest of the year" — Juanito uses RRULE format to create one recurring event instead of many.
- **Morning briefing:** Every day at 5:45am, Juanito posts today's and tomorrow's events to the family group.
- **Smart pre-event reminders:** One hour before any event, Juanito sends a context-aware reminder — sports events get warm-up tips, exams get study resources, everything gets relevant web-sourced content with links.
- **Universal event enrichment:** For any enrichable event (mass, concert, doctor visit, practice), Juanito searches Wikipedia, YouTube, USCCB, Khan Academy, and other approved sources to add genuinely useful context and links.
- **Living shopping list:** "Add milk and eggs" → list updated. "I'm heading to Costco" → Juanito replies with the full list. The list lives inside the next grocery calendar event.
- **Conflict detection:** When a new event is created, Juanito checks for time overlaps and flags pickup logistics for kids' activities.
- **Slash commands:** `/today`, `/week`, `/list`, `/help` for quick access without typing a full message.
- **Bilingual:** Juanito follows whoever is writing — English gets a reply in English with Venezuelan flavour, Spanish gets full venezolano.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) package manager
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An OpenAI API key (gpt-4o)
- A Google Cloud project with the Calendar API enabled

## Setup

Clone the repo:

```bash
git clone https://github.com/your-username/family-planner.git
cd family-planner
```

Install dependencies:

```bash
uv sync
```

Configure environment variables:

```bash
cp .env.example .env
```

Then open `.env` and fill in your values:

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather → /newbot |
| `OPENAI_API_KEY` | Yes | From platform.openai.com |
| `GOOGLE_CALENDAR_ID` | Yes | From Google Calendar settings → Integrate calendar |
| `GOOGLE_CREDENTIALS_FILE` | Yes | Path to your OAuth client JSON — default: `credentials.json` |
| `FAMILY_CHAT_ID` | Yes | Telegram group chat ID — use @userinfobot to find it |
| `DARWIN_USER_ID` | Yes | Darwin's Telegram user ID |
| `WIFE_USER_ID` | Yes | Wife's Telegram user ID |
| `PAOLA_USER_ID` | Yes | Paola's Telegram user ID |
| `TIMEZONE` | Yes | e.g. `America/Toronto` |

## Google Calendar setup

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a project
2. Enable the **Google Calendar API**
3. Create **OAuth 2.0 credentials** (Desktop app type)
4. Download `credentials.json` and place it in the project root
5. First run will open a browser for OAuth consent — token saved to `token.json` automatically
6. Set `GOOGLE_CALENDAR_ID` in `.env` (find it in Google Calendar → Settings → Integrate calendar)

## Telegram bot setup

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token to `.env`
2. Create a Telegram group, add the bot, and make it an admin
3. Send a message to the group, then fetch `https://api.telegram.org/bot<TOKEN>/getUpdates` to get `FAMILY_CHAT_ID`
4. Get each family member's user ID from [@userinfobot](https://t.me/userinfobot)

Register slash commands with @BotFather so they appear in Telegram's menu:

```
/setcommands → select your bot → paste:
today - Today's schedule
week - This week at a glance
list - Current shopping list
help - What I can do
```

## Run

```bash
uv run main.py
```

The bot starts polling and the scheduler activates. All three family members can interact immediately via the Telegram group. Logs are written to `logs/family-agent.log` (daily rotation, 7 days retained).

To manually trigger the morning briefing or pre-event reminder for testing:

```bash
uv run scripts/test_briefing.py
uv run scripts/test_reminder.py
```

## Project structure

```
family-planner/
├── main.py                      # Entry point — starts bot + scheduler
├── .env                         # Secrets — never commit
├── .env.example                 # Template for secrets
├── credentials.json             # Google OAuth client secret — never commit
├── token.json                   # Google OAuth token (auto-generated) — never commit
│
├── agent/
│   ├── brain.py                 # OpenAI gpt-4o agentic loop — Juanito's reasoning
│   ├── tools.py                 # Tool definitions and handlers (calendar, shopping list)
│   └── enrichment.py           # Universal event enrichment via OpenAI web search
│
├── bot/
│   ├── handlers.py              # Telegram message handler — routes to agent brain
│   └── commands.py              # /today, /week, /list, /help handlers
│
├── gcal/
│   ├── auth.py                  # OAuth 2.0 flow, saves token.json
│   └── client.py                # get_events, create_event, delete_event, update_event, etc.
│
├── scheduler/
│   └── jobs.py                  # Morning briefing (5:45am) + pre-event check (every 30 min)
│
├── storage/
│   ├── memory.py                # In-memory conversation history per Telegram user
│   └── shopping_list.py         # Reads/writes [agent] block in grocery calendar event
│
├── config/
│   └── rules.yaml               # Event type keywords, reminder timing, pickup flags
│
├── scripts/
│   ├── test_calendar.py         # Manual test for Google Calendar auth and read
│   ├── test_briefing.py         # Manually trigger morning briefing
│   └── test_reminder.py         # Manually trigger pre-event reminder check
│
└── logs/
    └── family-agent.log         # Daily rotating log (auto-created)
```
