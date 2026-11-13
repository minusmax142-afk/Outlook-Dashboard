# Outlook Dashboard

A local web dashboard for your work mailbox: read, send, reply, forward, search and filter mail, and turn requests in emails into **tasks**.

- **Always connected, whichever Outlook you use.** It connects directly to your mail server over IMAP/SMTP (for Indigo Heights: `mail.indigoheights.com`, hosted at HostNext). Classic Outlook, New Outlook and phones all read the same server mailbox, so anything you do here shows up everywhere, and no Outlook app needs to be open.
- Free and open source: Python, Flask, IMAPClient, keyring, and Tailwind CSS via CDN. No paid services, no cloud, no Azure.
- Runs only on your PC at **http://127.0.0.1:5000**.

> **Build status:** done so far: sign-in, all folders, inbox, reading pane, compose (send / reply / reply all / forward / drafts / attachments), folders (create / rename / delete / move emails), organize tools (sort, group, colour categories, bulk actions), tasks and the overview page. All seven build steps are complete.

---

## Quick start

1. Install **Python 3.11+** from https://www.python.org/downloads/windows/ and tick **"Add python.exe to PATH"**.
2. Double-click **`setup.bat`** **once**. It installs what's needed and:
   - adds an **Outlook Dashboard** icon to your desktop and Start menu,
   - makes the dashboard **start by itself, hidden, every time you sign in to Windows** (no black window),
   - opens the dashboard in your browser.
3. Sign in with your **email address and email password**, the same ones Outlook uses. The server settings fill in automatically (`mail.<your domain>`, IMAP 993 / SMTP 465, SSL).

After that you never need a `.bat` file again: just open **http://127.0.0.1:5000**, or click the desktop icon (it also starts the dashboard if it isn't running). You stay signed in until you click **Sign out** in the sidebar.

- **Stop it**: Task Manager → *Details* → end `pythonw.exe` (or sign out of Windows).
- **Turn off starting at sign-in**: Task Manager → *Startup apps* → disable *Outlook Dashboard (background)*, or run `.venv\Scripts\python.exe launcher.pyw --uninstall` to remove the icons and the auto-start.
- **If something goes wrong**: see `%LOCALAPPDATA%\OutlookDashboard\dashboard.log` (error types only, never email content).

### Your password
- It is checked against the mail server (both incoming and outgoing) before anything is saved.
- It is stored **only in Windows Credential Manager** (encrypted by Windows for your account). You can see it there as *"OutlookDashboard (IMAP)"*.
- It is never written to a file, never shown in the browser, and never logged.
- If you change your email password, the dashboard asks you to sign in again.

### Sign-in problems
| Message | What to do |
|---|---|
| *The email address or password was not accepted* | Check the password (try it in Outlook or webmail). Too many failed attempts can temporarily block your IP at the mail server. |
| *Couldn't reach mail.…* | Check your internet/VPN, or open **Server settings** and correct the server name. |
| *Security certificate couldn't be verified* | The server name doesn't match the certificate. Use the exact name your Outlook account uses. |
| *Outgoing (SMTP) server rejected the password* | Check the SMTP server/port under **Server settings** (465 = SSL, 587 = STARTTLS). |

---

## Features

### Overview (the start page)
- **Cards**: unread in Inbox, received today, sent this week, flagged, open tasks (with overdue count) and drafts. Click a card to open that list.
- **Chart**: emails received (Inbox) and sent per day for the last 7 days. Hover a day for exact numbers, or open *Show as table*. Needs internet once to load Chart.js; without it the table still works.
- **Upcoming tasks** (next 5 by due date) and **Recent unread** (5 newest unread in the Inbox; click one to open it).
- Refreshes every 60 seconds while open.

### Summary (all mail + task mail)
Pick a period (today, 3, 7, 14 or 30 days) for the Inbox.
- **All mail**: received, unread, replied, need a reply, with attachments and number of senders; **top senders**; emails **by type** (Request, Meeting, Finance, Update, Notification, Info); and **every email in one line**: a short summary taken from the email's own text (greetings, quoted history and signatures are skipped; forwards are summarised from the forwarded email). Filter by Unread, Need a reply or Requests. Click an email to open it.
- **Task mail**: emails that ask you to do something: how many, how many are waiting for your decision, added as tasks, due this week and overdue. Each email shows its summary, the requests found (with deadline and the sentence it came from) and its status: *Waiting for you*, *Task added*, *Task done* or *Dismissed*. Add or dismiss right there.
- The number next to **Summary** in the sidebar is how many task emails are waiting for you.
- Summaries and types use simple rules on this PC: no AI service, nothing leaves your computer.

### Mail
- **Inbox** with sender, subject, preview, date and unread marker. 50 at a time with **Load more**. Auto-refreshes every 60 seconds.
- **Search** by sender or subject. **Filters**: Unread, Flagged, Attachments, date range.
- **Reading pane**: the email is shown in a locked-down (sandboxed) frame. Pictures from the internet are blocked until you click **Show pictures**, because they can track when you open an email.
- **Attachments** download; images inside emails display.
- **Mark read/unread, Flag/Unflag, Delete** (moves to Trash / Deleted Items). These are saved on the server, so Outlook sees them too.

### Folders
- The sidebar lists **all your mailbox folders** (Inbox, Drafts, Sent Items, Archive, Junk, Deleted Items and your own folders, with subfolders indented), with unread counts. Click one to open it. Sent Items and Drafts show who each email is **to**.
- **New folder**: the **+** next to *Folders*. **Rename / New subfolder / Delete**: the **⋯** button on a folder (or right-click it). Inbox and the special folders can't be renamed or deleted.
- Deleting a folder moves its emails to **Deleted Items** first, so nothing is lost. Folders with subfolders must be emptied of subfolders first.
- **Move emails**: **Move** in the reading pane, or tick several emails (Shift+click ticks a range) and use **Move to…**, or **drag** emails onto a folder in the sidebar.
- Deleting an email that is already in Deleted Items removes it permanently (you're asked first).
- **Drafts**: open a draft and click **Edit draft** to continue it.
- All of this is done on the mail server, so Outlook and your phone show the same folders.

### Organize ("align")
- **Sort**: newest or oldest first, sender (A–Z), subject (A–Z), or largest first. Sorting is done by the mail server, so it covers the whole folder, not just the emails loaded so far.
- **Group**: by sender, by conversation (same subject without Re:/Fw:), or by date (Today, Yesterday, Earlier this week, ...). Click a group heading to collapse it, or tick its box to select the whole group. Your sort and group choice is remembered.
- **Colour categories** (like Outlook's): *Categorize* on an open email or on ticked emails. Six are ready to use (Urgent, Follow up, Waiting, Done, FYI, Personal). Add, rename, recolour or delete them under *Manage categories…*. Filter the list by category with the **Category** menu.
  - Categories are saved **on the mail server** with each email (as IMAP keywords), so they stay when you move an email. Category names and colours are kept on this PC (`categories.json`).
  - Outlook itself doesn't show IMAP keywords, so categories are visible in the dashboard only.
- **Bulk actions** on ticked emails: Read, Unread, Flag, Unflag, Categorize, Move, Delete. Shift+click ticks a range; the box at the top ticks everything loaded.

### Compose
- **New mail** (button, or press **N**), **Reply**, **Reply all**, **Forward** (keeps the original attachments; you can remove any).
- Replies keep the conversation threaded (`In-Reply-To` / `References`) and mark the original as answered.
- **Sent mail** goes through your SMTP server and a copy is saved to your **Sent** folder, as Outlook does.
- **Save draft** saves to your server's **Drafts** folder, so Outlook sees it. Saving again replaces the previous draft.
- Use full email addresses (`name@company.com`). Up to 25 MB of attachments. **Ctrl+Enter** sends.
- Your Outlook signature isn't added automatically.

### Tasks
- **Found in your emails**: scans recent mail (3–30 days) for requests and deadlines, such as *"kindly share the report by Thursday"*, *"could you review… before 15 Nov"*, or *"Action required: …"*. Each suggestion shows the sentence it came from, a suggested title and a due date.
  - **Add task** (edit first if you like) or **Dismiss**. Added or dismissed suggestions aren't shown again.
  - Newsletters, no-reply senders, out-of-office replies and quoted conversation history are ignored.
  - Dates understood include *by Friday*, *tomorrow*, *EOD*, *end of month*, *within 3 days*, *15 Nov*, *November 15th*, *15/11/2026* (day first), and *2026-11-15*.
- **Add task** on any open email creates a task linked to it; **Open email** on a task jumps back.
- **My tasks**: tick to complete, add your own, and overdue / due-soon dates are highlighted.
- Tasks are kept in the **dashboard's own task list** on this PC (`tasks.db`). IMAP mail servers have no task store, and New Outlook / To Do tasks need a Microsoft 365 account.
- Task detection is simple rules running on your PC. No AI service is used and nothing leaves your machine.

### Write for me

- Click **Write for me** (or press **W**) and type a short note, e.g.
  *hold salary of abdul rehman store manager, send to qasim* or *ask accounts to send the stock report by friday, cc hr*.
- The dashboard writes a professional email: greeting, polite wording, subject line, your name, and spelling/shorthand fixes.
  It understands salary hold / release / deduction, meetings, report requests, reminders, approvals and rejections,
  explanations and warnings, follow-ups, thanks, "inform … that …" and general instructions.
- People are found from the names and addresses in your Inbox and Sent mail. If a name is unclear or unknown, you pick the
  person (or type their address) once; the dashboard remembers it (`contacts.json`).
- The finished email opens in the normal mail window so you can **check and edit it before clicking Send**. Nothing is sent automatically.
- **Your signature** (name, job title, company, phone) is set once in the Write for me window (`signature.json`).
- **Make professional** in the New mail window rewrites what you typed: formal wording, grammar and spelling fixes,
  a proper greeting, opening and closing, and your signature. **Undo rewrite** puts your text back.
- **Any language**: notes in Roman Urdu, Roman Hindi, Urdu, Hindi or any other language are translated to English
  first, then written up as a professional email. This uses Google's free translation services (no key, no cost):
  only the non-English lines are sent to Google; English lines never leave your PC. Needs an internet connection.
- Writing the email itself uses templates and rules on your PC (no AI service).

---

## Privacy and security

- The server listens **only on 127.0.0.1**. Requests addressed to other hostnames are rejected, and data-changing requests must come from the dashboard page itself.
- All connections to the mail server are encrypted (SSL/TLS) with certificate checking.
- **Email content is never printed or written to disk.** Logs contain only error types. A few recently opened emails are kept in memory (not on disk) so attachments open quickly.
- Files in `%LOCALAPPDATA%\OutlookDashboard\`:
  - `account.json`: email address, display name, server names and ports (**no password**)
  - `tasks.db`: your task list (titles, due dates, linked email ids)
  - `categories.json`: your category names and colours
  - `task_suggestions.json`: keys of suggestions you added or dismissed (email id plus a short hash; no email text)

## Backup mode: classic Outlook

If the mail server can't be reached directly (for example, a firewall), the dashboard can use the classic Outlook desktop app instead. Copy `settings.example.json` to `settings.json`, change `"imap"` to `"outlook"`, keep classic Outlook open, and start the dashboard again.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask routes (pages + `/api/...`) |
| `imap_service.py` | Mail server backend (IMAP/SMTP): mail, compose, task-finder input |
| `imap_account.py` | Sign-in: checks the password, saves it to Windows Credential Manager |
| `tasks_store.py` | Local task list (SQLite) |
| `categories.py` | Colour categories (names/colours; assignments are IMAP keywords) |
| `writer.py` | "Write for me": short note -> professional email (templates, no AI) |
| `translate.py` | Roman Urdu / Hindi / any language -> English before writing (free Google services) |
| `contacts.py` | People you email (from mail headers) and remembered names, for Write for me |
| `summarizer.py` | One-line email summaries and email types (rules, no AI) |
| `task_finder.py` | Rules that find requests and deadlines in emails |
| `outlook_service.py` | Backup backend: classic Outlook via COM |
| `config.py` / `settings.example.json` | Settings (backend) |
| `errors.py` | Error types shared by the backends |
| `templates/index.html`, `static/app.js`, `static/style.css` | The web page |
| `setup.bat` | One-time setup: installs requirements, icons and auto-start |
| `launcher.pyw` | Runs the dashboard in the background (no window); `--install` / `--uninstall` icons and auto-start |
