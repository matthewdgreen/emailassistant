# LLM-Assisted Email Triage & Task Manager

This project is a Python-based assistant that:

- Reads summaries of your unread Gmail messages (sender, time, subject, snippet),
- Maintains a persistent file of known senders and ongoing threads,
- Maintains a persistent task list derived from your email and manual tasks,
- Uses an LLM in two passes:
  1. To decide which emails need full text and propose task updates,
  2. To refine tasks, adjust sender importance, and produce a daily summary.

The daily summary includes:

- Critical emails that need attention,
- Suggested responses,
- An updated prioritized task list.

The code is structured as a small library (`email_triage/`) plus a CLI entrypoint (`main.py`).