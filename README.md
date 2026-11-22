# Codicilix

**A private assistant for a manager's messy notes.**

Codicilix reads your notes on your own laptop and answers questions about them.
It shows where every answer came from. Nothing it reads ever leaves the laptop,
and it keeps no copy of your notes.

Made by **Bilan Salim** and **David** for the Pfizer OSS AI Studio × Newpage
AI Innovation Challenge, University of Bristol, November 2026.

---

## Why we built it

Managers write notes everywhere: typed notes, notebook pages, photos of whiteboards,
comments in Word files, sticky notes on PDFs, action lists and the calendar.
Before a meeting, it's hard to remember what changed, what you promised,
and which note is out of date.

Our example manager is **Tommy**. It's his first day back after the holidays.
Tomorrow is his first Pfizer × Newpage meeting of the year, and his notes from
before the break are scattered everywhere. He clicks **Prepare me**, and Codicilix
pulls together what he needs, with a link to the note behind every point.

---

## What it can do

**Get ready for a meeting**
- **Prepare me** builds a short brief for your next meeting: what's new since last time,
  what you wrote last time, open actions, and questions to ask.
- **What has changed?** finds dates and amounts that moved between notes, and tells you
  which files still say the old thing.
- **Decision log** lists every decision, and marks whether it still stands or has changed.
- **What do I owe people?** lists your open promises, overdue ones first.

**Ask questions in plain English**
- Answers read like a normal chat, with a small number after each fact showing its source.
- Each answer says how sure it is (**high**, **medium** or **low**) and why.
- If your notes don't answer the question, it says so instead of guessing.
- Small spelling mistakes are fine ("Megn" still finds Megan).

**Read messy notes**
- Handwriting, photos and screenshots, read by the laptop's own text reader.
- A photo viewer that highlights the matching words, so you can check the original yourself.
- Word, Excel and PDF files, including comments, tracked changes, sticky notes and highlights.
- Emails, Teams exports, calendars, action lists and saved links.

**Stay in control**
- Switch folders and types of file on or off. Off means never opened.
- Notes named "private" or "confidential" stay closed until you allow them.
- **Forget this session** wipes everything Codicilix held in memory.
- **Check-up** tests every privacy promise with one button.
- Themes, bigger text, and an easy-read mode with extra spacing.

---

## Why we made these choices

**Everything runs on the laptop.**
The challenge rule is that notes never leave the device. So the AI model runs
locally through Ollama, and the app blocks any connection that isn't to the laptop itself.
It works with Wi-Fi switched off.

**Code finds the facts. The AI only writes the words.**
Small local AI models can make mistakes. So plain code does the important work:
searching the notes, finding what changed, spotting overdue actions, and writing
the warnings. The AI just turns what the code found into a friendly answer.
If the AI isn't running, you still get the exact lines from your notes.

**Notes are read fresh every time, and nothing is saved.**
A saved database or search index would be a copy of your notes. So Codicilix reads
your files when you ask, keeps them only in memory, and lets them go.
A write guard stops the app from saving any file at all.

**Every answer shows its sources.**
You should never have to take the AI's word for it. Every fact has a number you can
click to see the note it came from, with its date.

**Honest beats clever.**
If the notes don't say, Codicilix says "I couldn't find that" rather than guess.
Confidence drops to "low" when only one note was used, when that note has a warning,
or when words from your question aren't in any note.

**Files can't trick it.**
Someone could hide instructions in a file, like white text in a Word document saying
"send these notes away". Codicilix checks for this with plain code and blocks it before
the AI sees anything. The AI also has no tools, so it couldn't send anything anyway.

**Nothing extra to install.**
Codicilix is plain Python with no add-on packages. Handwriting is read by the Mac's
own built-in reader. Fewer moving parts means fewer things that can go wrong or leak.

**It picks a model that suits your laptop.**
Laptops have different amounts of memory. Codicilix checks yours and uses the best
local model you've installed. You can switch models with one click.

---

## How you can check it's private

| Promise | How to check it yourself |
|---|---|
| Nothing leaves the laptop | Turn Wi-Fi off. It still works. Or click **Try to break the rule** and watch the app block itself. |
| No copies are kept | The trust panel shows "saved 0 files". |
| Your notes aren't changed | A fingerprint of your notes is checked while the app runs. |
| You choose what it reads | Switch a folder off, then ask about it. The answer says it didn't look there. |
| Hidden instructions are blocked | Ask "What feedback did we get on the prototype?" and see the trap file get blocked. |

More detail: [docs/how-it-keeps-notes-yours.md](docs/how-it-keeps-notes-yours.md)

---

## Get started on a Mac

You need internet once, for about 10 minutes. After that it works offline.

1. Install **Ollama** from [ollama.com](https://ollama.com/download) and open it.
2. Open **Terminal** and download a model. Pick one for your Mac's memory
   (Apple menu → About This Mac):
   ```sh
   ollama pull llama3.2:3b   # small and fast, works on any Mac
   ollama pull qwen3:8b      # better answers, for Macs with 16 GB or more
   ```
3. Download Codicilix and make the app:
   ```sh
   git clone https://github.com/bilanabdi2345-bot/Codicilix---Support-Agent-.git Codicilix
   cd Codicilix
   ./scripts/make-mac-app.sh
   ```
4. In **Applications**, right-click **Codicilix** and choose **Open** (first time only).

To update later, double-click **Update Codicilix** in Applications.
It runs all the tests first, and stops if anything fails.

**On Windows:** install Python and Ollama, download this repo, and double-click
`start-windows.bat`. It opens in your browser. Photos are read by Windows' own text reader.

---

## Using your own notes

Codicilix starts in **Demo mode**, with made-up notes and "today" set to 5 January 2027.

To use your own notes:
1. Go to **Folders & access** and switch **Demo mode** off.
2. Click **Choose a folder…** or **Choose files…**, and pick your notes.

Codicilix remembers where your notes are, but never what's in them.
**Remove** stops using a folder. Your files always stay exactly where they are.

---

## The sample notes

Everything in `sample-notes/` is made up for the demo. No real company information is used.

**The main story** is Tommy's team in Pfizer's AI Studio, working with Newpage.
The people are Tommy (the manager), Megan (who trains the interns), Bilan and David
(the interns), Xinyue and Mehreen (from Newpage), and Sophie (from the Medical team).

The notes are messy on purpose. The pilot date moved from 12 to 26 January, but an
unfinished draft still says 12 January. There's an overdue action, scraps with no
dates, a private folder, handwritten pages, a Word file with comments, a spreadsheet,
a marked-up PDF, and one trap file with hidden instructions.

**Project Helix** is a second, even messier set of notes. Switch it on in
**Folders & access** to try it.

---

## For developers

Run the tests (88 of them, using a fake AI model so they run anywhere):
```sh
python3 -B -m unittest discover tests
```

How the code is organised:
```
secondbrain/
  guards.py    blocks internet connections and saving files
  notes.py     reads notes, finds dates, flags problems
  docs.py      reads Word, Excel and PDF files
  search.py    finds the notes that match a question
  changes.py   finds what changed, decisions and promises
  shield.py    blocks hidden instructions in files
  brain.py     builds the answer and explains it
  models.py    picks and talks to the local AI model
  server.py    the local web server (this laptop only)
  static/      the app window
sample-notes/  made-up notes for the demo
themes/        colour themes (add your own)
scripts/       Mac app maker, updater and text readers
tests/         automatic tests
docs/          design notes and the demo script
```

Themes are small files that can only change colours, font and corner shape,
so any theme is safe to use. See [themes/README.md](themes/README.md).

---

## Credits

We each built a version first, then combined the best of both.
From Bilan's version: reading handwriting, photos and documents, the photo viewer,
the shield, themes, the app window and the model picker. From David's version:
what has changed, what you owe, the decision log, private notes, and answers that
work without the AI. David's original is at
[github.com/davidxu16/ai-assistant](https://github.com/davidxu16/ai-assistant).

Challenge set by **Pfizer's OSS AI Studio** and **Newpage Solutions**.
