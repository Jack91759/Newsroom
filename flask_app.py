import hashlib
import csv
import io
import os
import math
import sqlite3
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, jsonify, Response
)

app = Flask(__name__)
app.secret_key = "change-this-to-a-random-secret-key-in-production"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "newsroom.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def record_site_visit():
    """Logs unique daily visitors and total pageviews privately via daily salted hash."""
    today = datetime.now().strftime("%Y-%m-%d")
    raw_id = f"{request.remote_addr}:{request.headers.get('User-Agent', '')}:{today}"
    visitor_hash = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:24]

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM site_traffic WHERE visit_date = ? AND visitor_hash = ?",
            (today, visitor_hash)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE site_traffic SET page_views = page_views + 1 WHERE id = ?",
                (existing["id"],)
            )
        else:
            conn.execute(
                "INSERT INTO site_traffic (visit_date, visitor_hash, page_views) VALUES (?, ?, 1)",
                (today, visitor_hash)
            )

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def calculate_read_time(text):
    words = len(text.split())
    return max(1, math.ceil(words / 200))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def enrich_article_stats(row):
    """Converts a SQLite Row into a dict with calculated read-depth percentages."""
    d = dict(row)
    views = d.get("views", 0) or 0
    r25 = d.get("read_25", 0) or 0
    r50 = d.get("read_50", 0) or 0
    r75 = d.get("read_75", 0) or 0
    r100 = d.get("read_100", 0) or 0

    if views > 0:
        d["pct_25"] = min(100, round((r25 / views) * 100))
        d["pct_50"] = min(100, round((r50 / views) * 100))
        d["pct_75"] = min(100, round((r75 / views) * 100))
        d["pct_100"] = min(100, round((r100 / views) * 100))
        # Weighted average of how far readers get through the story
        d["avg_read_pct"] = min(100, round(((r25 + r50 + r75 + r100) / (4 * views)) * 100))
    else:
        d["pct_25"] = d["pct_50"] = d["pct_75"] = d["pct_100"] = d["avg_read_pct"] = 0

    return d


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'writer'
            );

            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                publish_date TEXT NOT NULL,
                is_current INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                tldr TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                is_lead INTEGER DEFAULT 0,
                read_minutes INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL,
                views INTEGER DEFAULT 0,
                read_25 INTEGER DEFAULT 0,
                read_50 INTEGER DEFAULT 0,
                read_75 INTEGER DEFAULT 0,
                read_100 INTEGER DEFAULT 0,
                FOREIGN KEY (issue_id) REFERENCES issues (id),
                FOREIGN KEY (author_id) REFERENCES users (id)
            );

            CREATE TABLE IF NOT EXISTS sponsors (
                slot_key TEXT PRIMARY KEY,
                slot_label TEXT NOT NULL,
                sponsor_name TEXT DEFAULT '',
                target_url TEXT DEFAULT '',
                image_filename TEXT DEFAULT ''
            );
        """)

        # Seed default Admin user (admin / admin123)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
                ("admin", "Chief Editor", generate_password_hash("admin123"), "admin")
            )

        # Seed Sponsor Slots
        for key, label in [
            ("top_banner", "Top Leaderboard Banner (728x90 / Wide)"),
            ("sidebar_box", "Sidebar Square Sponsor (300x250)"),
            ("mid_feed", "Mid-Edition Feature Sponsor")
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO sponsors (slot_key, slot_label) VALUES (?, ?)",
                (key, label)
            )

        # Seed Initial Issue & Sample Articles with baseline demo metrics
        if conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 0:
            cur = conn.execute(
                "INSERT INTO issues (issue_number, title, publish_date, is_current) VALUES (?, ?, ?, 1)",
                (1, "The Inaugural Edition: Tech, Local Policy & Community", datetime.now().strftime("%B %d, %Y"))
            )
            issue_id = cur.lastrowid
            admin_id = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]

            sample_articles = [
                (
                    issue_id, "COVER STORY",
                    "How Independent Local Newsrooms Are Rebuilding Community Trust",
                    admin_id, "Chief Editor",
                    "• Curated weekly editions reduce news fatigue and boost full-article completion.\n• Direct reader mailbags turn passive subscribers into active contributors.\n• Transparent local sponsorship keeps journalism free without intrusive popups.",
                    "In an era dominated by algorithmic feeds and breaking-news alerts, weekly publications are experiencing a quiet renaissance. Readers increasingly prefer a single, thoughtful package delivered once a week over an endless stream of fragmented updates.\n\nBy slowing down the publishing cycle, editors can verify sources thoroughly, provide historical context, and connect dots across multiple weeks of local developments.\n\nOur goal with this weekly edition is simple: respect your time, verify every claim, and give our community a clear window into the stories that actually matter.",
                    "published", 1, 3, datetime.now().strftime("%Y-%m-%d %H:%M"),
                    142, 128, 110, 94, 81
                ),
                (
                    issue_id, "TECHNOLOGY",
                    "Open-Source Infrastructure Is Powering the Next Wave of Local Makers",
                    admin_id, "Chief Editor",
                    "• Affordable microcontrollers and self-hosted tools lower prototyping costs.\n• Community-maintained libraries speed up hardware and software iteration.\n• Local schools and clubs are adopting industry-grade open toolchains.",
                    "Walk into almost any modern workshop or student robotics lab and you will see open-source software and modular hardware doing the heavy lifting.\n\nInstead of relying on expensive proprietary licenses, small teams are combining Python backends, lightweight SQLite databases, and self-hosted services to build resilient tools tailored to their exact needs.",
                    "published", 0, 2, datetime.now().strftime("%Y-%m-%d %H:%M"),
                    98, 86, 74, 65, 59
                ),
                (
                    issue_id, "ANALYSIS",
                    "Upcoming Draft: Q4 Infrastructure & County Budget Breakdown",
                    admin_id, "Chief Editor",
                    "• Draft notes currently under editorial review.",
                    "This draft article is saved in the newsroom system and will remain invisible to public readers until an editor switches its status to Published.",
                    "draft", 0, 1, datetime.now().strftime("%Y-%m-%d %H:%M"),
                    0, 0, 0, 0, 0
                )
            ]

            conn.executemany("""
                INSERT INTO articles
                (issue_id, category, title, author_id, author_name, tldr, body, status, is_lead, read_minutes, updated_at,
                 views, read_25, read_50, read_75, read_100)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_articles)


# --- Auth Decorators ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access the newsroom.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Administrator privileges required.", "error")
            return redirect(url_for("admin_dashboard"))
        return f(*args, **kwargs)
    return decorated


# --- Public Reader Routes ---
@app.route("/")
def index():
    search_query = request.args.get("q", "").strip()
    category_filter = request.args.get("category", "").strip()

    with get_db() as conn:
        issue = conn.execute(
            "SELECT * FROM issues WHERE is_current = 1 ORDER BY issue_number DESC LIMIT 1"
        ).fetchone()

        query = "SELECT * FROM articles WHERE issue_id = ? AND status = 'published'"
        params = [issue["id"]]

        if search_query:
            query += " AND (title LIKE ? OR body LIKE ? OR tldr LIKE ? OR author_name LIKE ?)"
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        if category_filter:
            query += " AND category = ?"
            params.append(category_filter)

        query += " ORDER BY is_lead DESC, id ASC"
        articles = conn.execute(query, params).fetchall()

        all_categories = conn.execute(
            "SELECT DISTINCT category FROM articles WHERE issue_id = ? AND status = 'published'",
            (issue["id"],)
        ).fetchall()

        sponsors_rows = conn.execute("SELECT * FROM sponsors").fetchall()
        sponsors = {row["slot_key"]: dict(row) for row in sponsors_rows}

        total_minutes = sum(a["read_minutes"] for a in articles)

    return render_template(
        "index.html",
        issue=issue,
        articles=articles,
        categories=[c["category"] for c in all_categories],
        sponsors=sponsors,
        total_minutes=total_minutes,
        search_query=search_query,
        category_filter=category_filter
    )


# --- Lightweight Reader Telemetry Endpoint ---
@app.route("/api/track", methods=["POST"])
def track_article_event():
    data = request.get_json(silent=True) or {}
    article_id = data.get("article_id")
    milestone = data.get("milestone")

    valid_columns = {
        "view": "views",
        "25": "read_25",
        "50": "read_50",
        "75": "read_75",
        "100": "read_100"
    }

    col = valid_columns.get(str(milestone))
    if not article_id or not col:
        return jsonify({"ok": False}), 400

    with get_db() as conn:
        conn.execute(
            f"UPDATE articles SET {col} = COALESCE({col}, 0) + 1 WHERE id = ? AND status = 'published'",
            (article_id,)
        )

    return jsonify({"ok": True})


# --- Authentication Routes ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["display_name"] = user["display_name"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['display_name']}!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# --- Writer & Editor Workspace (/admin) ---
@app.route("/admin")
@login_required
def admin_dashboard():
    edit_id = request.args.get("edit", type=int)

    with get_db() as conn:
        issue = conn.execute(
            "SELECT * FROM issues WHERE is_current = 1 ORDER BY issue_number DESC LIMIT 1"
        ).fetchone()

        raw_articles = conn.execute(
            "SELECT * FROM articles WHERE issue_id = ? ORDER BY status ASC, is_lead DESC, id DESC",
            (issue["id"],)
        ).fetchall()
        articles = [enrich_article_stats(a) for a in raw_articles]

        # Personal stats for the currently logged-in writer
        my_articles = [a for a in articles if a["author_id"] == session["user_id"]]
        my_views = sum(a["views"] for a in my_articles)
        my_published = [a for a in my_articles if a["status"] == "published"]
        my_avg_read = (
            round(sum(a["avg_read_pct"] for a in my_published) / len(my_published))
            if my_published else 0
        )
        my_completion_rate = (
            round(sum(a["pct_100"] for a in my_published) / len(my_published))
            if my_published else 0
        )

        edit_article = None
        if edit_id:
            edit_article = conn.execute("SELECT * FROM articles WHERE id = ?", (edit_id,)).fetchone()

        users = conn.execute("SELECT id, username, display_name, role FROM users ORDER BY id ASC").fetchall()
        sponsors = conn.execute("SELECT * FROM sponsors").fetchall()

    return render_template(
        "admin.html",
        issue=issue,
        articles=articles,
        my_articles=my_articles,
        my_views=my_views,
        my_avg_read=my_avg_read,
        my_completion_rate=my_completion_rate,
        edit_article=edit_article,
        users=users,
        sponsors=sponsors
    )


# --- Admin Full Analytics Page (/admin/stats) ---
@app.route("/admin/stats")
@login_required
@admin_required
def admin_stats():
    with get_db() as conn:
        issue = conn.execute(
            "SELECT * FROM issues WHERE is_current = 1 ORDER BY issue_number DESC LIMIT 1"
        ).fetchone()

        raw_articles = conn.execute(
            "SELECT * FROM articles WHERE issue_id = ? ORDER BY views DESC, id ASC",
            (issue["id"],)
        ).fetchall()
        articles = [enrich_article_stats(a) for a in raw_articles]
        published_articles = [a for a in articles if a["status"] == "published"]

        total_views = sum(a["views"] for a in published_articles)
        total_completions = sum(a["read_100"] for a in published_articles)
        avg_read_depth = (
            round(sum(a["avg_read_pct"] for a in published_articles) / len(published_articles))
            if published_articles else 0
        )
        avg_finish_rate = (
            round(sum(a["pct_100"] for a in published_articles) / len(published_articles))
            if published_articles else 0
        )

        # Group performance by writer
        users = conn.execute("SELECT id, username, display_name, role FROM users").fetchall()
        writer_leaderboard = []
        for u in users:
            w_arts = [a for a in published_articles if a["author_id"] == u["id"]]
            w_views = sum(a["views"] for a in w_arts)
            w_avg_depth = round(sum(a["avg_read_pct"] for a in w_arts) / len(w_arts)) if w_arts else 0
            w_finish = round(sum(a["pct_100"] for a in w_arts) / len(w_arts)) if w_arts else 0
            writer_leaderboard.append({
                "display_name": u["display_name"],
                "username": u["username"],
                "role": u["role"],
                "story_count": len(w_arts),
                "total_views": w_views,
                "avg_read_pct": w_avg_depth,
                "finish_rate": w_finish
            })

        writer_leaderboard.sort(key=lambda x: x["total_views"], reverse=True)
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Site-wide visitor metrics
        unique_visitors_total = conn.execute("SELECT COUNT(*) FROM site_traffic").fetchone()[0]
        total_site_pageviews = conn.execute(
            "SELECT COALESCE(SUM(page_views), 0) FROM site_traffic"
        ).fetchone()[0]
        unique_visitors_today = conn.execute(
            "SELECT COUNT(*) FROM site_traffic WHERE visit_date = ?", (today_str,)
        ).fetchone()[0]

        # Last 7 days daily visitor breakdown
        daily_traffic = conn.execute("""
            SELECT visit_date,
                   COUNT(*) AS unique_people,
                   SUM(page_views) AS page_views
            FROM site_traffic
            GROUP BY visit_date
            ORDER BY visit_date DESC
            LIMIT 7
        """).fetchall()

        # Email list data
        subscribers = conn.execute(
            "SELECT * FROM subscribers ORDER BY id DESC"
        ).fetchall()
        active_sub_count = sum(1 for s in subscribers if s["status"] == "active")
    return render_template(
        "stats.html",
        issue=issue,
        articles=published_articles,
        total_views=total_views,
        total_completions=total_completions,
        avg_read_depth=avg_read_depth,
        avg_finish_rate=avg_finish_rate,
        writer_leaderboard=writer_leaderboard,
        unique_visitors_total=unique_visitors_total,
        total_site_pageviews=total_site_pageviews,
        unique_visitors_today=unique_visitors_today,
        daily_traffic=daily_traffic,
        subscribers=subscribers,
        active_sub_count=active_sub_count
    )


@app.route("/admin/article/save", methods=["POST"])
@login_required
def save_article():
    article_id = request.form.get("article_id", type=int)
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "REPORT").strip().upper()
    tldr = request.form.get("tldr", "").strip()
    body = request.form.get("body", "").strip()
    status = request.form.get("status", "draft")
    is_lead = 1 if request.form.get("is_lead") == "on" else 0

    if not title or not body:
        flash("Headline and article body are required.", "error")
        return redirect(url_for("admin_dashboard"))

    read_minutes = calculate_read_time(body)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    author_id = session["user_id"]
    author_name = session["display_name"]

    with get_db() as conn:
        issue = conn.execute(
            "SELECT id FROM issues WHERE is_current = 1 ORDER BY issue_number DESC LIMIT 1"
        ).fetchone()

        if is_lead:
            conn.execute("UPDATE articles SET is_lead = 0 WHERE issue_id = ?", (issue["id"],))

        if article_id:
            conn.execute("""
                UPDATE articles
                SET category = ?, title = ?, tldr = ?, body = ?, status = ?,
                    is_lead = ?, read_minutes = ?, updated_at = ?
                WHERE id = ?
            """, (category, title, tldr, body, status, is_lead, read_minutes, now_str, article_id))
            flash(f"Article updated ({status.upper()}) — {read_minutes} min read.", "success")
        else:
            conn.execute("""
                INSERT INTO articles
                (issue_id, category, title, author_id, author_name, tldr, body, status, is_lead, read_minutes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (issue["id"], category, title, author_id, author_name, tldr, body, status, is_lead, read_minutes, now_str))
            flash(f"Article saved as {status.upper()} under {author_name}!", "success")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/article/toggle-status/<int:article_id>", methods=["POST"])
@login_required
def toggle_article_status(article_id):
    with get_db() as conn:
        art = conn.execute("SELECT status FROM articles WHERE id = ?", (article_id,)).fetchone()
        if art:
            new_status = "published" if art["status"] == "draft" else "draft"
            conn.execute("UPDATE articles SET status = ? WHERE id = ?", (new_status, article_id))
            flash(f"Article status changed to {new_status.upper()}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/article/delete/<int:article_id>", methods=["POST"])
@login_required
def delete_article(article_id):
    with get_db() as conn:
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    flash("Article permanently deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/issue/update", methods=["POST"])
@login_required
@admin_required
def update_issue():
    issue_number = request.form.get("issue_number", type=int)
    title = request.form.get("title", "").strip()
    publish_date = request.form.get("publish_date", "").strip()

    if issue_number and title:
        with get_db() as conn:
            conn.execute(
                "UPDATE issues SET issue_number = ?, title = ?, publish_date = ? WHERE is_current = 1",
                (issue_number, title, publish_date)
            )
        flash("Current Weekly Edition header updated!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/add", methods=["POST"])
@login_required
@admin_required
def add_writer():
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "writer")

    if not username or not display_name or not password:
        flash("All writer fields are required.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
                (username, display_name, generate_password_hash(password), role)
            )
        flash(f"Added {display_name} (@{username}) as {role}.", "success")
    except sqlite3.IntegrityError:
        flash("That username is already taken.", "error")

    return redirect(url_for("admin_dashboard"))

@app.route("/admin/users/edit/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def edit_user(user_id):
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "writer")
    new_password = request.form.get("password", "")

    if not username or not display_name:
        flash("Username and screen name are required.", "error")
        return redirect(url_for("admin_dashboard"))

    with get_db() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            flash("User not found.", "error")
            return redirect(url_for("admin_dashboard"))

        # Prevent demoting the last remaining admin
        if target["role"] == "admin" and role != "admin":
            admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admin_count <= 1:
                flash("Cannot demote the last remaining administrator.", "error")
                return redirect(url_for("admin_dashboard"))

        try:
            if new_password.strip():
                conn.execute(
                    """UPDATE users
                       SET username = ?, display_name = ?, role = ?, password_hash = ?
                       WHERE id = ?""",
                    (username, display_name, role, generate_password_hash(new_password), user_id)
                )
            else:
                conn.execute(
                    """UPDATE users
                       SET username = ?, display_name = ?, role = ?
                       WHERE id = ?""",
                    (username, display_name, role, user_id)
                )

            # Sync updated screen name across all articles written by this user
            conn.execute(
                "UPDATE articles SET author_name = ? WHERE author_id = ?",
                (display_name, user_id)
            )

            # If admin edited their own account, refresh active session values
            if user_id == session["user_id"]:
                session["username"] = username
                session["display_name"] = display_name
                session["role"] = role

            flash(f"Updated account for {display_name} (@{username}).", "success")
        except sqlite3.IntegrityError:
            flash("That username is already in use by another staff member.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot delete your own currently logged-in account.", "error")
        return redirect(url_for("admin_dashboard"))

    with get_db() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            flash("User not found.", "error")
            return redirect(url_for("admin_dashboard"))

        if target["role"] == "admin":
            admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admin_count <= 1:
                flash("Cannot delete the last remaining administrator.", "error")
                return redirect(url_for("admin_dashboard"))

        # Reassign any articles owned by the deleted user to the current admin so stories aren't orphaned
        conn.execute(
            "UPDATE articles SET author_id = ? WHERE author_id = ?",
            (session["user_id"], user_id)
        )
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    flash(f"Deleted user @{target['username']} ({target['display_name']}).", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/account/update", methods=["POST"])
@login_required
def update_own_account():
    """Allows any logged-in writer or admin to edit their own screen name, username, or password."""
    user_id = session["user_id"]
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    new_password = request.form.get("password", "")

    if not username or not display_name:
        flash("Screen name and username cannot be empty.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        with get_db() as conn:
            if new_password.strip():
                conn.execute(
                    "UPDATE users SET username = ?, display_name = ?, password_hash = ? WHERE id = ?",
                    (username, display_name, generate_password_hash(new_password), user_id)
                )
            else:
                conn.execute(
                    "UPDATE users SET username = ?, display_name = ? WHERE id = ?",
                    (username, display_name, user_id)
                )

            conn.execute(
                "UPDATE articles SET author_name = ? WHERE author_id = ?",
                (display_name, user_id)
            )

        session["username"] = username
        session["display_name"] = display_name
        flash("Your profile and credentials have been updated!", "success")
    except sqlite3.IntegrityError:
        flash("That username is already taken.", "error")

    return redirect(url_for("admin_dashboard"))

@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("index") + "#subscribe-box")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO subscribers (email, subscribed_at, status) VALUES (?, ?, 'active')",
                (email, now_str)
            )
        flash("You're subscribed! You'll receive the next Weekly Edition in your inbox.", "success")
    except sqlite3.IntegrityError:
        flash("That email is already on our weekly mailing list.", "success")

    return redirect(url_for("index") + "#subscribe-box")


@app.route("/admin/subscribers/export")
@login_required
@admin_required
def export_subscribers():
    """Downloads active email subscribers as a CSV file for any email sender."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT email, subscribed_at, status FROM subscribers WHERE status = 'active' ORDER BY id DESC"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Subscribed At", "Status"])
    for r in rows:
        writer.writerow([r["email"], r["subscribed_at"], r["status"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=weekly_dispatch_subscribers.csv"}
    )


@app.route("/admin/subscribers/delete/<int:sub_id>", methods=["POST"])
@login_required
@admin_required
def delete_subscriber(sub_id):
    with get_db() as conn:
        conn.execute("DELETE FROM subscribers WHERE id = ?", (sub_id,))
    flash("Subscriber removed from mailing list.", "success")
    return redirect(url_for("admin_stats"))


@app.route("/admin/sponsors/update", methods=["POST"])
@login_required
@admin_required
def update_sponsor():
    slot_key = request.form.get("slot_key")
    sponsor_name = request.form.get("sponsor_name", "").strip()
    target_url = request.form.get("target_url", "").strip()
    clear_image = request.form.get("clear_image") == "1"

    with get_db() as conn:
        existing = conn.execute("SELECT image_filename FROM sponsors WHERE slot_key = ?", (slot_key,)).fetchone()
        filename = existing["image_filename"] if existing else ""

        if clear_image:
            if filename:
                old_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = ""

        file = request.files.get("sponsor_image")
        if file and file.filename != "":
            if allowed_file(file.filename):
                safe_name = secure_filename(f"{slot_key}_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], safe_name))
                filename = safe_name
            else:
                flash("Invalid image format. Use PNG, JPG, GIF, or WEBP.", "error")
                return redirect(url_for("admin_dashboard"))

        conn.execute(
            "UPDATE sponsors SET sponsor_name = ?, target_url = ?, image_filename = ? WHERE slot_key = ?",
            (sponsor_name, target_url, filename, slot_key)
        )

    flash("Sponsor slot updated!", "success")
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)