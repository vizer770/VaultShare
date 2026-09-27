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


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = "vaultshare-secret-key-change-later"

UPLOAD_FOLDER = "storage"
STORAGE_LIMIT = 500 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

DATABASE = "database.db"


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

    conn.close()

    storage_used = calculate_storage(
        session["user_id"]
    )

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
        storage_percent=storage_percent
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

        conn.execute("""
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

    storage_used = calculate_storage(
        session["user_id"]
    )

    return render_template(
        "my_files.html",
        files=files,
        user=user,
        storage_used=storage_used
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

    conn.close()

    if not file:
        return "File not found.", 404

    user_folder = os.path.join(
        UPLOAD_FOLDER,
        str(session["user_id"])
    )

    return send_from_directory(
        user_folder,
        file["stored_name"],
        as_attachment=True,
        download_name=file["filename"]
    )


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

    conn.commit()

    conn.close()

    update_storage(
        session["user_id"]
    )

    return redirect(request.referrer or "/dashboard")


# =========================================================
# TRASH
# =========================================================

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

@app.route("/share/<int:file_id>")
def create_share(file_id):

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

    existing = conn.execute("""
        SELECT token
        FROM shares
        WHERE file_id = ?
        AND user_id = ?
    """, (
        file_id,
        session["user_id"]
    )).fetchone()

    if existing:

        token = existing["token"]

    else:

        token = uuid.uuid4().hex

        conn.execute("""
            INSERT INTO shares (
                file_id,
                user_id,
                token
            )
            VALUES (?, ?, ?)
        """, (
            file_id,
            session["user_id"],
            token
        ))

        conn.commit()

    conn.close()

    share_url = url_for(
        "shared_file",
        token=token,
        _external=True
    )

    return render_template(
        "share.html",
        file=file,
        share_url=share_url
    )


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
    """, (token,)).fetchone()

    conn.close()

    if not result:

        return "Shared file not found.", 404

    return render_template(
        "shared_file.html",
        file=result
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
    """, (token,)).fetchone()

    conn.close()

    if not result:

        return "Shared file not found.", 404

    user_folder = os.path.join(
        UPLOAD_FOLDER,
        str(result["user_id"])
    )

    return send_from_directory(
        user_folder,
        result["stored_name"],
        as_attachment=True,
        download_name=result["filename"]
    )


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

    return render_template(
        "settings.html",
        user=user
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

if __name__ == "__main__":

    init_db()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )