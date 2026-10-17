from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    send_from_directory,
    flash,
    url_for
    
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

import sqlite3
import os
import uuid
import webbrowser
import threading
import mimetypes
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google import genai

APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP_DIR, ".env"))

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"

def get_gemini_client():
    """Create the Gemini client only when analysis is requested."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)




# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")

UPLOAD_FOLDER = os.path.join(APP_DIR, "storage")
STORAGE_LIMIT = 500 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

DATABASE = os.path.join(APP_DIR, "database.db")


def get_db():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():

    conn = get_db()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            storage_limit INTEGER DEFAULT 524288000,
            storage_used INTEGER DEFAULT 0,
            email TEXT,
            display_name TEXT
        )
    """)

    # -----------------------------------------------------
    # FILES
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            size INTEGER NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # -----------------------------------------------------
    # SHARES
    # -----------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # -----------------------------------------------------
    # ADD NEW COLUMNS TO OLD DATABASE
    # -----------------------------------------------------

    columns = [
        ("email", "TEXT"),
        ("display_name", "TEXT"),
        ("is_deleted", "INTEGER DEFAULT 0"),
        ("is_favorite", "INTEGER DEFAULT 0")
    ]

    for column_name, column_type in columns:

        try:

            conn.execute(
                f"ALTER TABLE files ADD COLUMN {column_name} {column_type}"
            )

        except sqlite3.OperationalError:

            pass

    # User columns for older databases

    user_columns = [
        ("email", "TEXT"),
        ("display_name", "TEXT")
    ]

    for column_name, column_type in user_columns:

        try:

            conn.execute(
                f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
            )

        except sqlite3.OperationalError:

            pass

    try:
        conn.execute("ALTER TABLE files ADD COLUMN last_opened_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    try:
        conn.execute("ALTER TABLE shares ADD COLUMN expires_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    conn.close()


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def current_user():

    if "user_id" not in session:
        return None

    conn = get_db()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    conn.close()

    return user


def log_activity(user_id, action, file_id=None, details=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_log (user_id, file_id, action, details) VALUES (?, ?, ?, ?)",
        (user_id, file_id, action, details)
    )
    conn.commit()
    conn.close()


def calculate_storage(user_id):

    conn = get_db()

    result = conn.execute("""
        SELECT COALESCE(SUM(size), 0) AS total
        FROM files
        WHERE user_id = ?
        AND is_deleted = 0
    """, (user_id,)).fetchone()

    conn.close()

    return result["total"]


def format_bytes(value):
    value = max(int(value or 0), 0)
    if value < 1024:
        return f"{value} B"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KB"
    if value < 1024 ** 3:
        return f"{value / (1024 ** 2):.2f} MB"
    return f"{value / (1024 ** 3):.2f} GB"


app.jinja_env.globals["format_bytes"] = format_bytes


def update_storage(user_id):

    storage_used = calculate_storage(user_id)

    conn = get_db()

    conn.execute("""
        UPDATE users
        SET storage_used = ?
        WHERE id = ?
    """, (storage_used, user_id))

    conn.commit()

    conn.close()

    return storage_used


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if "user_id" in session:
        return redirect("/dashboard")

    return redirect("/login")


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        email = request.form.get(
            "email",
            ""
        ).strip()

        display_name = request.form.get(
            "display_name",
            ""
        ).strip()

        if not username:

            return render_template(
                "register.html",
                error="Username is required."
            )

        if not password:

            return render_template(
                "register.html",
                error="Password is required."
            )

        if len(password) < 6:

            return render_template(
                "register.html",
                error="Password must contain at least 6 characters."
            )

        conn = get_db()

        existing_user = conn.execute("""
            SELECT id
            FROM users
            WHERE username = ?
        """, (username,)).fetchone()

        if existing_user:

            conn.close()

            return render_template(
                "register.html",
                error="Username already exists."
            )

        password_hash = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users (
                username,
                password_hash,
                storage_limit,
                storage_used,
                email,
                display_name
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            username,
            password_hash,
            STORAGE_LIMIT,
            0,
            email,
            display_name
        ))

        conn.commit()

        conn.close()

        return redirect("/login")

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_db()

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE username = ?
        """, (username,)).fetchone()

        conn.close()

        if not user:

            return render_template(
                "login.html",
                error="Username or password is incorrect."
            )

        if not check_password_hash(
            user["password_hash"],
            password
        ):

            return render_template(
                "login.html",
                error="Username or password is incorrect."
            )

        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect("/dashboard")

    return render_template("login.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    files = conn.execute("""
        SELECT *
        FROM files
        WHERE user_id = ?
        AND is_deleted = 0
        ORDER BY uploaded_at DESC
    """, (session["user_id"],)).fetchall()

    recent_files = conn.execute("""
        SELECT * FROM files
        WHERE user_id = ? AND is_deleted = 0 AND last_opened_at IS NOT NULL
        ORDER BY last_opened_at DESC LIMIT 5
    """, (session["user_id"],)).fetchall()

    conn.close()

    storage_used = calculate_storage(session["user_id"])
    update_storage(session["user_id"])

    storage_percent = 0

    if user["storage_limit"] > 0:

        storage_percent = (
            storage_used /
            user["storage_limit"]
        ) * 100

    storage_percent = min(
        storage_percent,
        100
    )

    return render_template(
        "dashboard.html",
        user=user,
        files=files,
        storage_used=storage_used,
        storage_percent=storage_percent,
        recent_files=recent_files,
        storage_remaining=max(int(user["storage_limit"] or 0) - int(storage_used or 0), 0)
    )


# =========================================================
# UPLOAD
# =========================================================

@app.route("/upload", methods=["POST"])
def upload_file():

    if "user_id" not in session:
        return redirect("/login")

    uploaded_files = request.files.getlist("file")

    if not uploaded_files:

        return redirect("/dashboard")

    current_storage = calculate_storage(
        session["user_id"]
    )

    user_folder = os.path.join(
        UPLOAD_FOLDER,
        str(session["user_id"])
    )

    os.makedirs(
        user_folder,
        exist_ok=True
    )

    conn = get_db()

    for file in uploaded_files:

        if not file or not file.filename:
            continue

        original_name = secure_filename(
            file.filename
        )

        if not original_name:
            continue

        file_data = file.read()

        file_size = len(file_data)

        if (
            current_storage +
            file_size
            >
            STORAGE_LIMIT
        ):

            conn.close()

            return (
                "Storage limit exceeded. "
                "Maximum storage is 500 MB."
            )

        stored_name = (
            str(uuid.uuid4())
            + "_"
            + original_name
        )

        file_path = os.path.join(
            user_folder,
            stored_name
        )

        with open(
            file_path,
            "wb"
        ) as output_file:

            output_file.write(
                file_data
            )

        cursor = conn.execute("""
            INSERT INTO files (
                user_id,
                filename,
                stored_name,
                size,
                is_deleted,
                is_favorite
            )
            VALUES (?, ?, ?, ?, 0, 0)
        """, (
            session["user_id"],
            original_name,
            stored_name,
            file_size
        ))
        conn.execute(
            "INSERT INTO activity_log (user_id, file_id, action, details) VALUES (?, ?, ?, ?)",
            (session["user_id"], cursor.lastrowid, "File uploaded", original_name)
        )
        current_storage += file_size

    conn.execute("""
        UPDATE users
        SET storage_used = ?
        WHERE id = ?
    """, (
        current_storage,
        session["user_id"]
    ))

    conn.commit()

    conn.close()

    return redirect("/dashboard")


# =========================================================
# MY FILES
# =========================================================

@app.route("/my-files")
def my_files():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    files = conn.execute("""
        SELECT *
        FROM files
        WHERE user_id = ?
        AND is_deleted = 0
        ORDER BY uploaded_at DESC
    """, (session["user_id"],)).fetchall()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (session["user_id"],)).fetchone()

    conn.close()

    storage_used = calculate_storage(session["user_id"])
    update_storage(session["user_id"])

    return render_template(
        "my_files.html",
        files=files,
        user=user,
        storage_used=storage_used,
        storage_remaining=max(int(user["storage_limit"] or 0) - int(storage_used or 0), 0)
    )

# =========================================================
# AI ANALYSIS LOADING PAGE
# =========================================================

@app.route("/ai-tools")
def ai_tools():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()
    files = conn.execute("""
        SELECT *
        FROM files
        WHERE user_id = ?
        AND is_deleted = 0
        ORDER BY uploaded_at DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    supported_extensions = {".txt", ".pdf", ".pptx"}
    file_items = []
    for file in files:
        item = dict(file)
        extension = os.path.splitext(item["filename"])[1].lower()
        item["ai_supported"] = extension in supported_extensions
        file_items.append(item)

    return render_template("ai_tools.html", files=file_items)


@app.route("/ai-analyze/<int:file_id>")
def ai_analyze_loading(file_id):

    if "user_id" not in session:
        return redirect("/login")

    return render_template(
        "ai_loading.html",
        file_id=file_id
    )


# =========================================================
# AI FILE ANALYSIS
# =========================================================

@app.route("/ai-analyze/run/<int:file_id>")
def ai_analyze(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    file = conn.execute("""
        SELECT *
        FROM files
        WHERE id = ?
        AND user_id = ?
        AND is_deleted = 0
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    conn.close()

    if not file:
        return "File not found.", 404

    filename = file["filename"]

    allowed_extensions = [".txt", ".pdf", ".pptx"]

    extension = os.path.splitext(filename)[1].lower()

    if extension not in allowed_extensions:
        return render_template(
            "ai_unavailable.html",
            filename=filename,
            reason="This file type is not supported yet.",
            detail="VaultShare can currently analyze TXT, PDF and PPTX files.",
        ), 400

    user_folder = os.path.join(
        UPLOAD_FOLDER,
        str(file["user_id"])
    )

    file_path = os.path.join(
        user_folder,
        file["stored_name"]
    )

    if not os.path.exists(file_path):
        return "Physical file not found.", 404

    # -----------------------------------------------------
    # READ TEXT FILE
    # -----------------------------------------------------

    if extension == ".txt":

        with open(
            file_path,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:

            text = f.read()

    # -----------------------------------------------------
    # READ PDF
    # -----------------------------------------------------

    elif extension == ".pdf":

        try:

            import PyPDF2

            text = ""

            with open(file_path, "rb") as f:

                reader = PyPDF2.PdfReader(f)

                for page in reader.pages:

                    page_text = page.extract_text()

                    if page_text:
                        text += page_text + "\n"

        except Exception as e:

            return f"""
            <h2>PDF Reading Error</h2>
            <p>{str(e)}</p>
            <a href="/my-files">← Back to My Files</a>
            """, 500


            # -----------------------------------------------------
    # READ POWERPOINT
    # -----------------------------------------------------

    elif extension == ".pptx":

        try:

            from pptx import Presentation

            presentation = Presentation(file_path)

            text = ""

            for slide in presentation.slides:

                for shape in slide.shapes:

                    if hasattr(shape, "text") and shape.text:

                        text += shape.text + "\n"

        except Exception as e:

            return f"""
            <h2>PowerPoint Reading Error</h2>
            <p>{str(e)}</p>
            <a href="/my-files">← Back to My Files</a>
            """, 500

    if not text.strip():
        return render_template(
            "ai_unavailable.html",
            filename=filename,
            reason="No readable text found",
            detail="This file may contain scanned pages, images, or empty text. Try a text-based PDF, TXT or PPTX file.",
        ), 400

    # -----------------------------------------------------
    # LIMIT TEXT SENT TO AI
    # -----------------------------------------------------

    text = text[:20000]

    # -----------------------------------------------------
    # ASK GEMINI
    # -----------------------------------------------------

    prompt = f"""
You are the AI assistant inside VaultShare.

Analyze the following document.

Give the answer in this exact structure:

SUMMARY:
Write a short 3-5 sentence summary.

KEY POINTS:
- Point 1
- Point 2
- Point 3
- Point 4
- Point 5

SUGGESTED CATEGORY:
Give one suitable category for this document.

DOCUMENT:
{text}
"""

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return render_template(
            "ai_error.html",
            error_title="Gemini API key is missing",
            error_message="VaultShare cannot connect to Gemini because GEMINI_API_KEY is not configured.",
            error_hint="Open your .env file, add GEMINI_API_KEY=your_key, save it, and restart VaultShare."
        ), 503

    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        ai_result = (response.text or "").strip()
        if not ai_result:
            raise RuntimeError("Gemini returned an empty response.")

    except Exception as e:
        detail = str(e).lower()
        if "api key" in detail or "unauthenticated" in detail or "permission_denied" in detail or "403" in detail:
            title = "Gemini API key was rejected"
            message = "Google did not accept the configured API key or the key does not have access to this model."
            hint = "Check GEMINI_API_KEY in your .env file, confirm the key is active in Google AI Studio, and restart the app."
        elif "429" in detail or "quota" in detail or "resource_exhausted" in detail or "rate limit" in detail:
            title = "Gemini usage limit reached"
            message = "The Gemini API quota or rate limit has been reached for this key."
            hint = "Wait and try again, or check the API quota and billing settings for your Google AI Studio project."
        elif "model" in detail and ("not found" in detail or "not supported" in detail or "404" in detail):
            title = "Gemini model is unavailable"
            message = f"The configured model ({GEMINI_MODEL}) is not available for this API key."
            hint = "Check GEMINI_MODEL in .env or remove it to use the default model configured in app.py."
        elif "timed out" in detail or "timeout" in detail or "connection" in detail or "network" in detail:
            title = "Could not reach Gemini"
            message = "VaultShare could not connect to the Gemini API. Check your internet connection and try again."
            hint = "If your connection is working, wait a moment and retry the analysis."
        else:
            title = "Document analysis failed"
            message = "Gemini could not finish analyzing this document."
            hint = "Try again with a smaller TXT, PDF, or PPTX file. If the issue continues, check the Flask terminal for the technical error."

        app.logger.exception("Gemini document analysis failed")
        return render_template(
            "ai_error.html",
            error_title=title,
            error_message=message,
            error_hint=hint
        ), 502

    return render_template(
        "ai_result.html",
        file=file,
        ai_result=ai_result
    )






# =========================================================
# DOWNLOAD
# =========================================================

@app.route("/download/<int:file_id>")
def download_file(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    file = conn.execute("""
        SELECT *
        FROM files
        WHERE id = ?
        AND user_id = ?
        AND is_deleted = 0
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    if file:
        conn.execute("UPDATE files SET last_opened_at = CURRENT_TIMESTAMP WHERE id = ?", (file_id,))
        conn.commit()
    conn.close()

    if not file:
        return "File not found.", 404

    log_activity(session["user_id"], "File downloaded", file_id, file["filename"])
    user_folder = os.path.join(UPLOAD_FOLDER, str(session["user_id"]))
    return send_from_directory(user_folder, file["stored_name"], as_attachment=True, download_name=file["filename"])


# =========================================================
# MOVE FILE TO TRASH
# =========================================================

@app.route("/delete/<int:file_id>")
def delete_file(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    file = conn.execute("""
        SELECT *
        FROM files
        WHERE id = ?
        AND user_id = ?
        AND is_deleted = 0
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    if not file:

        conn.close()

        return "File not found.", 404

    conn.execute("""
        UPDATE files
        SET is_deleted = 1
        WHERE id = ?
        AND user_id = ?
    """, (
        file_id,
        session["user_id"]
    ))

    conn.execute(
        "INSERT INTO activity_log (user_id, file_id, action, details) VALUES (?, ?, ?, ?)",
        (session["user_id"], file_id, "File moved to Trash", file["filename"])
    )
    conn.commit()
    conn.close()

    update_storage(session["user_id"])
    return redirect(request.referrer or "/dashboard")


# =========================================================
# TRASH
# =========================================================

@app.route("/preview/<int:file_id>")
def preview_file(file_id):
    if "user_id" not in session:
        return redirect("/login")
    conn = get_db()
    file = conn.execute("""
        SELECT * FROM files
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, (file_id, session["user_id"])).fetchone()
    if not file:
        conn.close()
        return "File not found.", 404

    extension = os.path.splitext(file["filename"])[1].lower()
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt"}
    if extension not in allowed:
        conn.close()
        return render_template("preview_unavailable.html", file=file), 415

    conn.execute("UPDATE files SET last_opened_at = CURRENT_TIMESTAMP WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    log_activity(session["user_id"], "File previewed", file_id, file["filename"])
    return render_template("file_preview.html", file=file, extension=extension)


@app.route("/preview-content/<int:file_id>")
def preview_content(file_id):
    if "user_id" not in session:
        return redirect("/login")
    conn = get_db()
    file = conn.execute("""
        SELECT * FROM files
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, (file_id, session["user_id"])).fetchone()
    conn.close()
    if not file:
        return "File not found.", 404
    extension = os.path.splitext(file["filename"])[1].lower()
    if extension not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt"}:
        return "Preview not supported.", 415
    user_folder = os.path.join(UPLOAD_FOLDER, str(session["user_id"]))
    return send_from_directory(user_folder, file["stored_name"], as_attachment=False, download_name=file["filename"], mimetype=mimetypes.guess_type(file["filename"])[0] or "application/octet-stream")


@app.route("/activity")
def activity_history():
    if "user_id" not in session:
        return redirect("/login")
    conn = get_db()
    rows = conn.execute("""
        SELECT activity_log.*, files.filename
        FROM activity_log
        LEFT JOIN files ON files.id = activity_log.file_id
        WHERE activity_log.user_id = ?
        ORDER BY activity_log.created_at DESC
        LIMIT 100
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("activity.html", activities=rows)


@app.route("/trash")
def trash():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    files = conn.execute("""
        SELECT *
        FROM files
        WHERE user_id = ?
        AND is_deleted = 1
        ORDER BY uploaded_at DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template(
        "trash.html",
        files=files
    )


# =========================================================
# RESTORE FROM TRASH
# =========================================================

@app.route("/restore/<int:file_id>")
def restore_file(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    conn.execute("""
        UPDATE files
        SET is_deleted = 0
        WHERE id = ?
        AND user_id = ?
    """, (
        file_id,
        session["user_id"]
    ))

    conn.commit()

    conn.close()

    update_storage(
        session["user_id"]
    )

    return redirect("/trash")


# =========================================================
# PERMANENT DELETE
# =========================================================

@app.route("/permanent-delete/<int:file_id>")
def permanent_delete(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    file = conn.execute("""
        SELECT *
        FROM files
        WHERE id = ?
        AND user_id = ?
        AND is_deleted = 1
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    if not file:

        conn.close()

        return "File not found.", 404

    user_folder = os.path.join(
        UPLOAD_FOLDER,
        str(session["user_id"])
    )

    file_path = os.path.join(
        user_folder,
        file["stored_name"]
    )

    if os.path.exists(file_path):

        os.remove(file_path)

    conn.execute("""
        DELETE FROM files
        WHERE id = ?
        AND user_id = ?
    """, (
        file_id,
        session["user_id"]
    ))

    conn.commit()

    conn.close()

    update_storage(
        session["user_id"]
    )

    return redirect("/trash")


# =========================================================
# FAVORITES
# =========================================================

@app.route("/favorites")
def favorites():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    files = conn.execute("""
        SELECT *
        FROM files
        WHERE user_id = ?
        AND is_deleted = 0
        AND is_favorite = 1
        ORDER BY uploaded_at DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template(
        "favorites.html",
        files=files
    )


# =========================================================
# TOGGLE FAVORITE
# =========================================================

@app.route("/favorite/<int:file_id>")
def toggle_favorite(file_id):

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    file = conn.execute("""
        SELECT is_favorite
        FROM files
        WHERE id = ?
        AND user_id = ?
        AND is_deleted = 0
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    if file:

        new_value = (
            0
            if file["is_favorite"]
            else 1
        )

        conn.execute("""
            UPDATE files
            SET is_favorite = ?
            WHERE id = ?
            AND user_id = ?
        """, (
            new_value,
            file_id,
            session["user_id"]
        ))

        conn.commit()

    conn.close()

    return redirect(request.referrer or "/dashboard")


# =========================================================
# CREATE SHARE
# =========================================================

@app.route("/share/<int:file_id>", methods=["GET", "POST"])
def create_share(file_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()
    file = conn.execute("""
        SELECT * FROM files
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, (file_id, session["user_id"])).fetchone()

    if not file:
        conn.close()
        return "File not found.", 404

    existing = conn.execute("""
        SELECT * FROM shares WHERE file_id = ? AND user_id = ?
    """, (file_id, session["user_id"])).fetchone()

    if request.method == "POST":
        expiry_hours = request.form.get("expiry_hours", "never")
        expires_at = None
        if expiry_hours in {"1", "24", "168", "720"}:
            expires_at = (datetime.utcnow() + timedelta(hours=int(expiry_hours))).strftime("%Y-%m-%d %H:%M:%S")

        if existing:
            conn.execute("UPDATE shares SET expires_at = ? WHERE id = ?", (expires_at, existing["id"]))
            token = existing["token"]
        else:
            token = uuid.uuid4().hex
            conn.execute("""
                INSERT INTO shares (file_id, user_id, token, expires_at)
                VALUES (?, ?, ?, ?)
            """, (file_id, session["user_id"], token, expires_at))
        conn.commit()
        log_action_conn = conn.execute(
            "INSERT INTO activity_log (user_id, file_id, action, details) VALUES (?, ?, ?, ?)",
            (session["user_id"], file_id, "Share link created/updated", file["filename"])
        )
        conn.commit()
        conn.close()
        return redirect(url_for("create_share", file_id=file_id))

    if existing and existing["expires_at"]:
        try:
            expiry_dt = datetime.fromisoformat(existing["expires_at"])
            if expiry_dt < datetime.utcnow():
                existing = None
        except (ValueError, TypeError):
            pass

    if not existing:
        token = uuid.uuid4().hex
        conn.execute("""
            INSERT INTO shares (file_id, user_id, token)
            VALUES (?, ?, ?)
        """, (file_id, session["user_id"], token))
        conn.commit()
        existing = conn.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()

    conn.close()
    share_url = url_for("shared_file", token=existing["token"], _external=True)
    return render_template("share.html", file=file, share_url=share_url, share=existing)


@app.route("/share/<int:file_id>/revoke", methods=["POST"])
def revoke_share(file_id):
    if "user_id" not in session:
        return redirect("/login")
    conn = get_db()
    file = conn.execute(
        "SELECT filename FROM files WHERE id = ? AND user_id = ?",
        (file_id, session["user_id"])
    ).fetchone()
    if file:
        conn.execute("DELETE FROM shares WHERE file_id = ? AND user_id = ?", (file_id, session["user_id"]))
        conn.commit()
        conn.close()
        log_activity(session["user_id"], "Share link revoked", file_id, file["filename"])
        flash("Share link revoked.")
        return redirect(url_for("my_files"))
    conn.close()
    return "File not found.", 404


# =========================================================
# SHARED FILES
# =========================================================

@app.route("/shared")
def shared():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    shares = conn.execute("""
        SELECT
            shares.token,
            shares.created_at,
            files.filename,
            files.id
        FROM shares
        JOIN files
        ON shares.file_id = files.id
        WHERE shares.user_id = ?
        AND files.is_deleted = 0
        ORDER BY shares.created_at DESC
    """, (
        session["user_id"],
    )).fetchall()

    conn.close()

    return render_template(
        "shared.html",
        shares=shares
    )


# =========================================================
# PUBLIC SHARED FILE
# =========================================================

@app.route("/s/<token>")
def shared_file(token):

    conn = get_db()

    result = conn.execute("""
        SELECT
            files.*,
            shares.token
        FROM shares
        JOIN files
        ON shares.file_id = files.id
        WHERE shares.token = ?
        AND files.is_deleted = 0
        AND (shares.expires_at IS NULL OR shares.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()

    conn.close()

    if not result:

        return "Shared file not found.", 404

    return render_template(
        "shared_file.html",
        file=result,
        token=token
    )


# =========================================================
# DOWNLOAD SHARED FILE
# =========================================================

@app.route("/s/<token>/download")
def download_shared_file(token):

    conn = get_db()

    result = conn.execute("""
        SELECT
            files.*,
            shares.token
        FROM shares
        JOIN files
        ON shares.file_id = files.id
        WHERE shares.token = ?
        AND files.is_deleted = 0
        AND (shares.expires_at IS NULL OR shares.expires_at > CURRENT_TIMESTAMP)
    """, (token,)).fetchone()

    conn.close()

    if not result:

        return "Shared file not found.", 404

    log_activity(result["user_id"], "Shared file downloaded", result["id"], result["filename"])
    user_folder = os.path.join(UPLOAD_FOLDER, str(result["user_id"]))
    return send_from_directory(user_folder, result["stored_name"], as_attachment=True, download_name=result["filename"])


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():

    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        display_name = request.form.get(
            "display_name",
            ""
        ).strip()

        if not username:

            user = conn.execute("""
                SELECT *
                FROM users
                WHERE id = ?
            """, (
                session["user_id"],
            )).fetchone()

            conn.close()

            return render_template(
                "profile.html",
                user=user,
                error="Username cannot be empty."
            )

        existing_user = conn.execute("""
            SELECT id
            FROM users
            WHERE username = ?
            AND id != ?
        """, (
            username,
            session["user_id"]
        )).fetchone()

        if existing_user:

            user = conn.execute("""
                SELECT *
                FROM users
                WHERE id = ?
            """, (
                session["user_id"],
            )).fetchone()

            conn.close()

            return render_template(
                "profile.html",
                user=user,
                error="Username already exists."
            )

        conn.execute("""
            UPDATE users
            SET username = ?,
                email = ?,
                display_name = ?
            WHERE id = ?
        """, (
            username,
            email,
            display_name,
            session["user_id"]
        ))

        conn.commit()

        session["username"] = username

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()

    conn.close()

    return render_template(
        "profile.html",
        user=user
    )


# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings")
def settings():

    if "user_id" not in session:
        return redirect("/login")

    user = current_user()
    storage_used = calculate_storage(session["user_id"])
    storage_limit = int(user["storage_limit"] or 0)
    storage_remaining = max(storage_limit - storage_used, 0)
    storage_percent = min((storage_used / storage_limit * 100) if storage_limit else 0, 100)

    return render_template(
        "settings.html",
        user=user,
        storage_used=storage_used,
        storage_limit=storage_limit,
        storage_remaining=storage_remaining,
        storage_percent=storage_percent
    )


# =========================================================
# SECURITY
# =========================================================

@app.route("/security", methods=["GET", "POST"])
def security():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        conn = get_db()

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE id = ?
        """, (
            session["user_id"],
        )).fetchone()

        if not check_password_hash(
            user["password_hash"],
            current_password
        ):

            conn.close()

            return render_template(
                "security.html",
                user=user,
                error="Current password is incorrect."
            )

        if len(new_password) < 6:

            conn.close()

            return render_template(
                "security.html",
                user=user,
                error="New password must contain at least 6 characters."
            )

        if new_password != confirm_password:

            conn.close()

            return render_template(
                "security.html",
                user=user,
                error="New passwords do not match."
            )

        new_hash = generate_password_hash(
            new_password
        )

        conn.execute("""
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
        """, (
            new_hash,
            session["user_id"]
        ))

        conn.commit()

        conn.close()

        return render_template(
            "security.html",
            user=user,
            success="Password changed successfully."
        )

    user = current_user()

    return render_template(
        "security.html",
        user=user
    )


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404






# =========================================================
# START APP
# =========================================================

# Initialize database when the app is imported by Gunicorn
init_db()

if __name__ == "__main__":
    url = "http://127.0.0.1:5000"

    threading.Timer(
        1.0,
        lambda: webbrowser.open(url)
    ).start()

    app.run(debug=True, use_reloader=False)





   