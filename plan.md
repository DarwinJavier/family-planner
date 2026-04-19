# Javier Family Agent — Build Plan

A phased execution plan for building the family Telegram bot + Google Calendar agent. Each phase is self-contained and testable before moving to the next.

---

## Status overview

| Phase | Status |
|---|---|
| Phase 1 — Foundation | ✅ Complete |
| Phase 2 — Proactive notifications | ✅ Complete |
| Phase 3 — Web enrichment | ✅ Complete |
| Phase 4 — Smart features | ✅ Complete |
| Phase 5 — Polish & go live | ✅ Complete (deployment pending) |

**Added outside original plan:**
- Delete calendar events (`delete_calendar_event` tool)
- Edit/update calendar events (`update_calendar_event` tool)
- RRULE support for recurring events
- Universal event enrichment (not just sports/exam — any enrichable event)
- Prompt injection defences in enrichment pipeline

**Pending (one-off tasks):**
- Fill `WIFE_USER_ID` and `PAOLA_USER_ID` in `.env`
- Register slash commands with @BotFather (see Step 5.2)
- Railway deployment (do after one week of local testing — see Step 5.3)

---

## Before you start

- [x] Telegram bot token — from @BotFather
- [x] OpenAI API key — `OPENAI_API_KEY` in `.env`
- [x] Google Cloud project with Calendar API enabled + `credentials.json`
- [x] `GOOGLE_CALENDAR_ID` set in `.env`
- [x] `FAMILY_CHAT_ID` and `DARWIN_USER_ID` set in `.env`
- [ ] `WIFE_USER_ID` and `PAOLA_USER_ID` — get from @userinfobot on Telegram

---

## Phase 1 — Foundation ✅

**Goal:** All three family members can talk to the bot and it reads/writes Google Calendar.

### Step 1.1 — Project scaffold ✅
- `uv` project with all dependencies
- Folder structure: `agent/`, `gcal/`, `bot/`, `scheduler/`, `storage/`, `config/`, `scripts/`, `logs/`
- `.env`, `.env.example`, `.gitignore`

### Step 1.2 — Telegram bot shell ✅
- `bot/handlers.py` — message handler with access control (FAMILY_CHAT_ID only)
- `main.py` — entry point, starts bot + scheduler

### Step 1.3 — Google Calendar connection ✅
- `gcal/auth.py` — OAuth 2.0 flow, saves `token.json`
- `gcal/client.py` — `get_events()`, `create_event()`, `delete_event()`, `update_event()`, `get_overlapping_events()`, `get_next_grocery_event()`

### Step 1.4 — Agent brain ✅
- `agent/brain.py` — OpenAI gpt-4o agentic loop
- Juanito personality: Venezuelan, bilingual, follows message language
- System prompt injects current datetime to prevent date hallucination
- `finish_reason=length` guard prevents corrupt conversation history

### Step 1.5 — Connect bot to agent ✅
- Per-user in-memory conversation history (`storage/memory.py`, MAX_TURNS=20)
- Typing indicator while agent processes
- Friendly error fallback — raw errors never reach the chat

---

## Phase 2 — Proactive notifications ✅

**Goal:** Bot pushes information to the family without anyone asking.

### Step 2.1 — Scheduler setup ✅
- `scheduler/jobs.py` — python-telegram-bot built-in JobQueue (no separate APScheduler thread)

### Step 2.2 — Morning briefing ✅
- Fires daily at **5:45am**
- Today's + tomorrow's events, Juanito-formatted
- Posted to `FAMILY_CHAT_ID`

### Step 2.3 — Pre-event reminders ✅
- Runs every 30 minutes
- Fires for events starting in 60–90 min window
- Event type detected from `config/rules.yaml` keywords
- `_reminded_events` set prevents duplicate reminders per session

---

## Phase 3 — Web enrichment ✅

**Goal:** Reminders include real, web-sourced content.

### Step 3.1 — Enrichment module ✅
- `agent/enrichment.py` — single universal `enrich_event(title, description)` function
- Uses OpenAI Responses API with `web_search_preview` tool
- Works for any enrichable event — not limited to sports/exam
- Examples: Mass → liturgical readings + vestment color; sports → warm-up drill video; exam → Khan Academy link
- Returns empty string for logistical events (pickups, calls, meetings)

### Step 3.2 — Prompt injection defences ✅
- Input sanitization: strips control characters, caps at 300 chars
- Input pattern detection: rejects known injection phrases before API call
- Structural isolation: event data wrapped in XML tags, labelled as untrusted
- Approved domain allowlist: Wikipedia, YouTube, Spotify, Vatican, USCCB, BBC, Mayo Clinic, Khan Academy, etc.
- Output validation: model response scanned for injection patterns before sending to Telegram

---

## Phase 4 — Smart features ✅

**Goal:** Shopping list management, conflict detection, delete/edit events.

### Step 4.1 — Shopping list ✅
- `manage_shopping_list` tool: `view`, `add`, `clear` actions
- List stored in `[agent]` block inside next grocery calendar event description
- `storage/shopping_list.py` — reads/writes the block without touching human-written notes
- Duplicate detection (case-insensitive)
- If no grocery event exists → Juanito prompts to create one

### Step 4.2 — Conflict detection ✅
- Runs automatically after every `create_calendar_event` call
- Fetches overlapping events in the same time window
- Pickup flag triggered if new or overlapping event contains pickup keywords
- Keywords configurable in `config/rules.yaml` under `pickup_required`

### Step 4.3 — Delete & edit events ✅ (added outside plan)
- `delete_calendar_event` tool — always confirms before deleting
- `update_calendar_event` tool — partial update via Google Calendar PATCH (only changed fields sent)
- `read_calendar` now includes `[id:...]` in each event line so agent can reference events by ID

---

## Phase 5 — Polish and go live ✅

### Step 5.1 — Error handling and logging ✅
- All API calls wrapped in try/except throughout codebase
- Friendly fallback messages — no raw errors in Telegram
- Daily rotating log file: `logs/family-agent.log` (7 days retained)

### Step 5.2 — /commands ✅
- `/today` — today's schedule
- `/week` — next 7 days grouped by day
- `/list` — current shopping list
- `/help` — what Juanito can do, bilingual

**Manual step — register with @BotFather:**
Send `/setcommands` to @BotFather, select your bot, paste:
```
today - Today's schedule
week - This week at a glance
list - Current shopping list
help - What I can do
```

### Step 5.3 — Railway deployment ⬜ (after one week of local testing)

**Plan:**
1. Push repo to GitHub — verify `.env`, `token.json`, `credentials.json` are in `.gitignore`
2. Create Railway project → connect GitHub repo
3. Add all `.env` variables in Railway dashboard
4. Handle Google OAuth for production:
   - **Option A (recommended):** run OAuth locally, upload `token.json` as a Railway secret
   - Option B: switch to Google Service Account (no browser flow, more setup)
5. Add `Procfile`: `worker: uv run main.py`
6. Verify bot stays online after closing the laptop

Cost: ~$5 USD/month on Hobby plan.

---

## Testing checklist — one week local test

### Core features
- [ ] All 3 family members can chat with Juanito in the group
- [ ] `WIFE_USER_ID` and `PAOLA_USER_ID` filled in `.env`
- [ ] Calendar read: "What's on today/this week?" works
- [ ] Calendar write: add event → Juanito confirms → appears in Google Calendar
- [ ] Recurring events work (e.g. weekly misa with RRULE)
- [ ] Edit event: "Move dentist to Friday at 4pm" works
- [ ] Delete event: "Remove the dentist appointment" works
- [ ] Bulk event creation: list of events added in one message

### Proactive
- [ ] Morning briefing fires at 5:45am with correct events
- [ ] Pre-event reminder fires ~1 hour before sports/exam events
- [ ] Enrichment content appears in reminders (check quality)
- [ ] No duplicate reminders for the same event

### Shopping list
- [ ] Any family member can add items: "Add milk and eggs"
- [ ] Darwin can request the list: "I'm heading to Costco"
- [ ] Clear works with confirmation

### Smart features
- [ ] Conflict flag appears when overlapping events are created
- [ ] Pickup warning appears for kids' activity conflicts

### Commands
- [ ] `/today`, `/week`, `/list`, `/help` all work
- [ ] Commands appear in Telegram's command menu (after BotFather setup)

### Language
- [ ] English messages → English reply with Venezuelan flavour
- [ ] Spanish messages → full venezolano

---

## Key decisions — confirmed

| Decision | Choice | Reason |
|---|---|---|
| Agent brain | OpenAI gpt-4o | Switched from Anthropic mid-build; single provider for all LLM calls |
| Web enrichment | OpenAI Responses API + `web_search_preview` | Same provider, no extra dependency |
| Google auth | OAuth 2.0 (browser flow) | Simpler MVP setup; token.json cached after first run |
| Conversation memory | In-memory dict (MAX_TURNS=20) | Resets on restart — fine for short family chats |
| Shopping list storage | Calendar event `[agent]` block | All event data in one place, visible in Google Calendar |
| Enrichment scope | Universal — any enrichable event | Model decides; not limited to sports/exam categories |
| Confirm before writes | Always | Prevents accidental changes, builds family trust |
| Language handling | System prompt (message-by-message) | gpt-4o handles this reliably; no preferences file needed |
| Deployment | Railway Hobby ~$5/mo | After one week local test; Fly.io as free alternative |
