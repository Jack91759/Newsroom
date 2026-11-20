# Newsroom — Curated Weekly News CMS & Reader Platform

A self-hosted, full-stack weekly publication platform built with **Python (Flask)**, **SQLite**, and vanilla **HTML/CSS/JavaScript**. Designed around a cohesive, magazine-style "Weekly Edition" format rather than an endless daily feed, complete with a multi-user newsroom dashboard, live split-screen article editor, scroll-depth analytics, sponsor slot management, and an integrated mailing list.

---

## Key Features

### Public Reader Experience (`/`)
* **Curated Weekly Edition Layout:** Displays the active issue with total edition read time, sticky table of contents, and smooth section jumping.
* **TL;DR Executive Summaries:** Dedicated 3-bullet summary callout boxes at the top of articles for quick skimming.
* **Reader Controls:** Includes a live reading progress bar, **Focus Mode** (hides sidebars for distraction-free reading), **Dark/Light Theme** toggle, and dynamic font-size adjusters (`A-` / `A+`).
* **Search & Section Filtering:** Instant keyword search across headlines, body copy, TL;DRs, and authors, paired with category filter pills.
* **Auto-Hiding Sponsor Slots:** Top leaderboard, sidebar square, and mid-feed sponsor placements automatically render when an image is uploaded and stay completely hidden when empty.
* **Newsletter Subscription & Reader Pulse:** Sidebar and end-of-issue email signup forms plus an interactive weekly reader poll.

### Newsroom & Editorial Command Center (`/admin`)
* **Role-Based Authentication:** Session-based login separating **Admins** (full control over staff, sponsors, edition headers, and analytics) from **Writers** (drafting, editing, and personal telemetry).
* **Live Split-Screen Article Studio:** Real-time preview pane that updates formatting, word count, and estimated reading time (`200 WPM`) as you type.
* **Automatic Author Attribution:** Automatically assigns newly created articles to the logged-in writer's display name.
* **Draft & Publish Workflow:** Save stories privately as `Draft` before publishing them to the live issue, toggle publication status in one click, or pin a story as the **Lead Cover Story**.
* **Staff & Credential Management:** Admins can add writers, edit usernames/screen names/roles, reset passwords, and safely delete accounts (reassigning existing articles automatically). Writers can also update their own profile credentials.

### Audience & Read-Depth Analytics (`/admin/stats`)
* **Privacy-Friendly Website Traffic:** Tracks unique daily visitors and total pageviews using a daily salted SHA-256 hash without storing raw IP addresses.
* **Scroll Completion Telemetry:** Uses the browser's `IntersectionObserver` API to measure exact article engagement (`Views`, `25%`, `50%`, `75%`, and `100%` completion funnels) shown on both the Admin Analytics page and each writer's personal dashboard.
* **Mailing List Manager:** View active subscribers, copy all addresses to the clipboard in one click, or export the list as a `.csv` file.

---

## Project Structure

```text
weekly-news/
├── app.py                  # Flask backend, SQLite initialization, auth, API & routes
├── newsroom.db             # Auto-generated SQLite database (created on first run)
├── static/
│   └── uploads/            # Uploaded sponsor banner images
└── templates/
    ├── index.html          # Main public weekly edition & reader interface
    ├── login.html          # Staff authentication screen
    ├── admin.html          # Live split-screen editor, article manager & staff controls
    └── stats.html          # Site traffic, read-depth funnels & subscriber manager
