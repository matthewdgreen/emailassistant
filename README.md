# Email Triage Assistant

An LLM-assisted email triage tool that:

- Reads your **Gmail** (via OAuth) and summarizes unread messages.
- Maintains a **task list** of things you need to do or respond to.
- Learns your preferences over time via an editable **instructions file** and an interactive feedback loop.
- Lets you curate a **“known senders / VIPs”** list that influences triage.

Everything runs locally via a simple CLI.

---

## Features

### Email triage

- Connects to your **Gmail** account (read-only).
- Fetches summaries of **unread** messages (subject, sender, date, snippet).
- Two-pass LLM analysis:
  - **Pass 1**: Looks only at summaries + current tasks + known senders + instructions, decides:
    - Which messages need full text.
    - What preliminary task operations to propose.
  - **Pass 2**: Reads selected full email bodies and produces:
    - A **DailySummary** of critical emails.
    - Suggested responses (outlines and optional drafts).
    - Final task operations.
    - Updated sender profiles (importance, role, pinned, notes).

### Task management

- Stores tasks in `data/tasks.json`.
- Tasks have:
  - ID, description, status, priority, due date, source, timestamps.
- LLM can create/update/close tasks automatically from email content.
- You can manage tasks manually from the CLI:
  - Add tasks.
  - Mark tasks as done.
  - List current tasks.

### Known senders / VIPs

- Sender profiles are stored in `data/known_senders.json`:
  - `email`, `name`, `importance` (`high|normal|low`), `role`, `pinned`, etc.
- The model sees this each run and uses it to prioritize.
- CLI commands let you:
  - List known senders.
  - Set importance/role/pinned flags (e.g., mark a student or collaborator as high-importance and pinned).

### Instructions file & feedback loop

- A plain-text **instructions file** lives at `data/instructions.txt`.
- It describes your preferences:
  - What counts as “important”.
  - Which senders / topics to prioritize or de-emphasize.
  - How you like tasks and summaries structured.
- This file is injected into both prompt passes on every run.
- `--instruct` mode:
  - After a daily run, you can provide **free-form feedback** on what the assistant got wrong or could improve.
  - The LLM rewrites `instructions.txt` to better reflect your preferences.
  - Over time this tunes the behavior towards what *you* care about.

### Rescans & state

- State is stored in `data/state.json` with `last_run_at`.
- Normal runs:
  - Use `last_run_at` to fetch “new since last time”.
- `rescan-days`:
  - Rerun analysis over the last *N* days (without touching `last_run_at`), to backfill tasks or test changes.

---

## Quick Start

### 1. Clone and create a virtualenv

```bash
git clone <your-repo-url> emailassistant
cd emailassistant

python3.10 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

(You can use Python 3.11+ if you like; 3.10 works, but Google libs are moving on eventually.)

### 2. Create `.env` with your OpenAI key (and optional settings)

Copy the example:

```bash
cp .env.example .env
```

Then edit `.env` and set at least:

```env
OPENAI_API_KEY=sk-...your-key-here...

# Optional overrides (these defaults are usually fine):
# MODEL_NAME=gpt-4.1-mini
# MAX_EMAILS_PER_RUN=50
# DATA_DIR=data
# GMAIL_CREDENTIALS_PATH=credentials.json
# GMAIL_TOKEN_PATH=token.json
# INSTRUCTIONS_PATH=data/instructions.txt
```

### 3. Set up Gmail API credentials

1. Go to **Google Cloud Console** → APIs & Services.
2. Create or select a project.
3. Enable **Gmail API**.
4. Go to **APIs & Services → Credentials**:
   - Create credentials → **OAuth client ID**.
   - Application type: **Desktop app**.
   - Download the JSON.

Save that file as:

```text
emailassistant/
  credentials.json  ← here
```

Or set `GMAIL_CREDENTIALS_PATH` in `.env` to wherever you put it.

5. On **OAuth consent screen**:
   - Set the app type to **External**.
   - Set it to **Testing** mode.
   - Add your Gmail address as a **test user**.

### 4. First run: create data files and do Gmail OAuth

Run any command that touches storage, e.g.:

```bash
python main.py show-tasks
```

This will:

- Create `data/` if it doesn’t exist.
- Create:
  - `data/known_senders.json`
  - `data/tasks.json`
  - `data/state.json`
  - `data/instructions.txt` (with default instructions)

Now trigger Gmail OAuth by running:

```bash
python main.py run-daily
```

On the first call, a browser window will open:

- Google will show an “unverified app” warning.
- Click **Advanced** → “Go to <your app name> (unsafe)” (since this is your own app).
- Approve the requested Gmail scopes.

A `token.json` will be created next to `credentials.json` and used for future runs.

If the LLM key is set correctly, you should now get a first **daily summary** and updated JSON files in `data/`.

---

## Data Files

All under `data/` by default:

- `known_senders.json`  
  Sender profiles: importance, role, pinned, notes, last_seen_at.

- `tasks.json`  
  Task list: IDs, descriptions, status (`open|in_progress|done`), priority, due dates, etc.

- `state.json`  
  State for scheduling: currently just `last_run_at` (UTC timestamp).

- `instructions.txt`  
  Human-readable instructions/preferences for the triage model.  
  You can edit this manually or refine it via `--instruct`.

- `daily_summary.md`  
  The most recent daily summary in Markdown (rewritten each run).

You can customize paths via `.env` (see `Config` in `email_triage/config.py`).

---

## CLI Commands

Commands are all under `main.py`:

```bash
python main.py <command> [options]
```

### 1. `run-daily`

Run the daily analysis over unseen emails since the last run (or last 24h on first run):

```bash
python main.py run-daily
```

Does:

- Loads state, known senders, tasks, instructions.
- Fetches unread summaries since `last_run_at`.
- Runs two-pass LLM triage.
- Applies task operations and sender updates.
- Updates `state.last_run_at`.
- Writes `data/daily_summary.md`.
- Prints the summary to stdout.

#### `--instruct` (interactive instructions refinement)

```bash
python main.py run-daily --instruct
```

After the usual run, you’ll be prompted:

- Type free-form feedback about what the assistant did well/poorly.
- End with an empty line.
- The tool sends:
  - your feedback, and
  - the current `instructions.txt`

  to the LLM to generate improved instructions.

If successful, `data/instructions.txt` is overwritten with an updated version tuned to your feedback.

---

### 2. `show-tasks`

List all current tasks in a table:

```bash
python main.py show-tasks
```

Shows:

- Task ID  
- Status (`open / in_progress / done`)  
- Priority (1–10; higher = more important)  
- Due date (if any)  
- Description  

---

### 3. `add-task`

Add a manual task:

```bash
python main.py add-task "Review NSF proposal" --priority 9 --due 2025-12-15 --source manual
```

Options:

- `description` (positional) – required.  
- `-p, --priority` – integer 1–10 (default: 5).  
- `--due` – optional due date in `YYYY-MM-DD`.  
- `--source` – string label (default: `manual`); LLM uses `"email"` for its own tasks.

A unique task ID (e.g., `task-0001`) is assigned automatically.

---

### 4. `complete-task`

Mark a task as done:

```bash
python main.py complete-task task-0001
```

This sets its status to `done` and updates its timestamp.

---

### 5. `rescan-days`

Re-run analysis over the past **N days**, ignoring `last_run_at`:

```bash
# Default: past 3 days
python main.py rescan-days

# Past 7 days
python main.py rescan-days --days 7
```

Behavior:

- Computes `since = now - N days`.
- Runs the full two-pass analysis over unread emails since that time.
- Applies task & sender updates.
- Writes a summary to `data/daily_summary.md`.
- **Does not** update `state.last_run_at`.  
  (So your regular `run-daily` still uses the true last run time.)

Useful when:

- You change instructions and want to rebuild tasks based on the last few days.
- You want to test the pipeline on an explicit window.

---

### 6. `list-senders`

List known senders and their metadata:

```bash
python main.py list-senders
```

Shows:

- Email
- Name
- Importance (`high|normal|low`)
- Role (`student|collaborator|admin|family|notification|other`)
- Pinned? (`yes/no`)
- Last seen timestamp

Senders are sorted so pinned + high-importance ones appear first.

---

### 7. `set-sender`

Create or update a sender profile (e.g., mark someone as VIP):

```bash
python main.py set-sender alice@example.com   --name "Alice Student"   --importance high   --role student   --pin
```

Options:

- `email` (positional) – required.
- `--name` – human-readable name.
- `--importance` – one of `high`, `normal`, `low`.
- `--role` – one of:
  - `student`
  - `collaborator`
  - `admin`
  - `family`
  - `notification`
  - `other`
- `--pin` – mark as pinned (VIP).
- `--unpin` – unpin.

The LLM sees these profiles and can treat pinned/high-importance senders as higher priority.

---

## Implementation Notes

- All core logic lives under `email_triage/`:
  - `analysis_engine.py` – orchestration of Gmail → LLM → state updates.
  - `gmail_client.py` – Gmail API integration (read-only).
  - `llm_client.py` – thin wrapper around OpenAI’s chat completions endpoint.
  - `prompts.py` – prompt construction for:
    - pass 1,
    - pass 2,
    - instructions refinement.
  - `models.py` – Pydantic models for tasks, senders, summaries, etc.
  - `storage.py` – JSON and text file loading/saving.
  - `cli.py` – argument parsing and command dispatch.
  - `daily_runner.py` – render `DailySummary` to Markdown text.

- It’s designed so you can:
  - Swap out the backend model by changing `MODEL_NAME`.
  - Point at a different OpenAI-compatible endpoint by editing `llm_client.py`.
  - Customize behavior by editing `instructions.txt` and/or `prompts.py`.
