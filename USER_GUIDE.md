# Second Brain: Quick Guide

22 November 2026

## What Second Brain is

Second Brain answers questions about your scattered work notes and prepares you for meetings, entirely on your own computer. It reads only the folders you allow, only when you ask, and keeps no copy of anything it reads.

Every answer quotes your own notes with the file, line and date, so you can check it in one click. When something isn't in your notes, it says so instead of guessing. It needs only Python, and it works without the internet.

## Start it

You need Python 3.10 or newer; nothing else to install.

1. Download the code and start it:

   ```
   git clone https://github.com/davidxu16/ai-assistant.git
   cd ai-assistant
   python app.py
   ```

   On Windows you can instead double-click `Start Second Brain.bat`.
2. Your browser opens on the chat, with simulated notes for a fictional manager already loaded.
3. If you open the app another way, use the link printed in the terminal. It ends in `#key=…`, a new secret key each launch, and other windows are refused without it.
4. To use your own notes, paste a folder path into the box on the left and click **Add**, or start with `python app.py --allow "D:\My notes"`.

It reads notes (`.md`, `.txt`), action lists (`.csv`), calendars (`.ics`) and saved links. Screenshots are listed, but not read yet. Press Ctrl+C in the terminal to stop: everything it saw is forgotten.

## Ask it things

Type in the chat in your own words. Click a suggestion chip to start, or **New chat** to clear the conversation.

| To get | Type, for example |
| --- | --- |
| A meeting brief | "prepare me for my 1:1 with Priya", "brief me for steering", "prepare me for my next meeting" |
| Everything about a person or topic | "tell me about Dana", "catch me up on data residency" |
| A direct answer, with its history | "when is the launch?", "what did we decide about the vendor?" |
| What happened in a period | "what happened last week?", "decisions in October", "actions since Monday" |
| Promises you haven't kept | "what do I owe people?" |
| Notes that now disagree | "what has changed?" |
| Help | "help" |

Spelling mistakes are forgiven, and it tells you what it read ("I read 'budjet' as 'budget'"). If the answer isn't in your notes, it says "I couldn't find anything about…" instead of guessing.

## Read a brief

A brief appears in the chat, or under **Prepare for a meeting** when you pick a meeting from your calendar. Start with **If you only read one thing**: the talking points.

- **Last time**: what was decided and left open at your previous meeting.
- **What's changed since it was agreed**: notes that now disagree, old version struck through, newest below.
- **Open promises and actions**: who owes what, how long it's been open, and if it's overdue.
- **Still unanswered**: questions raised but never answered in your notes.
- **You started this but didn't finish**: half-written drafts, with lines from your other notes that fill the gaps.
- **What I couldn't check**: files it couldn't read or you switched off, and dates it had to guess.

Click any grey source label to open the original note at that line. **Why this?** explains why a line was included. **Copy as text** puts the whole brief on your clipboard.

## Choose what it sees, and check it kept the rule

You decide what it can read, and you can check for yourself that nothing left your computer.

- **Switch a file off** with its switch on the left: it won't be opened, and answers say they didn't look there.
- **Remove a folder** with the ✕ next to it, or click **End session & forget** to clear everything from memory.
- **Receipts**: under every answer, click the lock line to see exactly which files were read. It always says wrote 0, sent nothing, kept nothing.
- **Full check-up**: open **Proof it stayed here** and click **Run the full check-up**. It tests every promise live and explains each result in plain words.
- **Leak test**: on the same tab, it makes the app try to reach the internet, save a copy and start another program. Each attempt should show **Blocked**.
- **Your computer's own tools**: run the `Get-NetTCPConnection` command shown on that tab, or turn on flight mode. The app keeps working, because it never needs the internet.

If you add a folder that OneDrive, Dropbox, Google Drive or iCloud syncs, the app warns you: that sync service, not this app, already copies those files to the cloud.

## Extras and tips

- **Local AI write-ups (optional)**: install [Ollama](https://ollama.com), then run `ollama pull llama3.2:3b`. A **Write it up with local AI** button appears under answers and briefs. It sends only the quotes on screen, only to this computer. Each point links to its note, and points with no source are flagged. Without Ollama, everything else works the same.
- **Display**: the button in the top bar changes text size, switches light or dark theme, and turns on easy-read spacing (helps with dyslexia). Nothing is saved.
- **Web demo**: the shareable page runs the same assistant with simulated notes, entirely in the visitor's browser. It has no local AI and no check-up.

| If | Then |
| --- | --- |
| The window says "Open Second Brain from its own link" | Use the link printed in the terminal (ends in `#key=…`), or start the app again |
| Sample meetings show as past | Start with `python app.py --today 2026-11-22` |
| A note has no date inside | It's dated by the file's last change, and the brief says so |
| It can't find something you wrote | Check the file is switched on and is a supported type; screenshots aren't read yet |
