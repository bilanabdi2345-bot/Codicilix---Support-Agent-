# Demo video script (about 3 minutes)

**Before recording:** run `python app.py --today 2026-11-22`. Close other tabs. Zoom the browser to about 110%.
Optional: turn on flight mode / turn off Wi-Fi *before* you start. It makes the point by itself.

---

**0:00–0:20 · The problem**
> "Managers' notes are scattered: meeting notes, reminders, half-written updates, links, screenshots. And they're some of the most sensitive things in a company. So the value and the risk come from the same place. We built an assistant that helps with them without anything leaving the device, and without keeping a copy."

*Show: the app open on the chat. Point at the green "On this device" pill.*

**0:20–0:40 · You choose what it sees**
> "It only sees the folders I give it. For this demo that's simulated notes we wrote ourselves: seven weeks of a fictional manager's life."

*The simulated notes are already loaded. Point at the file list with its switches and the screenshot it says it can't read.*

**0:40–1:40 · The moment: preparing for a meeting**
*Type in the chat: "brief me for steering" (or open "Prepare for a meeting" and click "Atlas steering group").*
> "I've got steering tomorrow. In a tenth of a second it's read 14 files and built my brief."

- *Talking points:* "If I only read one thing: I promised Priya on 13 October I'd raise her tech-lead role with Helen. I've written it down four times, in four different files, and never done it. Helen's in this meeting."
- *Scroll to "What's changed".* "It connects things I never connected: the launch moved from 1 December to 15 January, but that isn't signed off yet. The budget went from £40k to £55k. And the vendor we rejected on price has since come back cheaper."
- *Click a source chip:* "Every line is a quote from my notes. Click it and the original opens at that line, read fresh and not stored."
- *Click "Why this?":* "It explains in plain English why it picked this."
- *Scroll to the draft:* "My half-written update to Helen says 'Budget: TODO'. It finds the latest figure in my own notes."
- *Scroll to "What I couldn't check":* "And it tells me where the brief stops: a whiteboard photo it can't read, which my standup note says has the rollout timeline."

**1:40–2:10 · Honest when unsure**
*Chat tab → type "When is the launch?"* → "It shows the newest answer, flags that it changed, and says it isn't final."
*Type "catch me up on data residency"* → "I can just talk to it. It pulls together four notes from four weeks and tells me it's 26 days overdue."
*Click "What's Tom's phone number?"* → "When it isn't in my notes, it says so. No guessing."
*Switch off `scratch.txt`, ask "What do I owe people?"* → "Switch a file off and it's never opened. It tells me it didn't look there."

**2:10–2:50 · Proof it stayed here**
*Proof tab.*
> "We didn't want 'trust us'. A guard inside the app runs before every file write, network connection and program launch, and nothing can switch it off once it's on."

*Click "Run the leak test".* "We make the app itself try to leak: look up a website, connect to the internet, send a web request, write a copy, start another program. All five are blocked before anything happens."
*Show a receipt under a brief:* "Every answer comes with a receipt of exactly which files were read. Zero written, zero sent, nothing kept."
*Optional: run the `Get-NetTCPConnection` line in PowerShell:* "And you can check with Windows' own tools: the only connection is to itself."

**2:50–3:00 · Close**
> "You already wrote it down. Second Brain lets it help you, without it ever leaving your hands."

---

**Submission checklist**
- [ ] Zip the `second-brain` folder (no installs needed; Python 3.10+ standard library only).
- [ ] Video file (MP4) showing the flow above.
- [ ] Email both to the address on the challenge's "Submit your work" slide, with the subject line given there, before 23:59 on Sunday 22 November 2026.
