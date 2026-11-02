import truststore
truststore.inject_into_ssl()  # trust the Windows cert store (corporate proxy TLS)

import io
import os
from datetime import timedelta
from pathlib import Path

import google.auth.transport.requests
import google.oauth2.credentials
import google.oauth2.id_token
import googleapiclient.discovery
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from googleapiclient.http import MediaIoBaseDownload
from werkzeug.utils import secure_filename

load_dotenv()

from db import get_db, init_db, now_iso
from parser import parse_itinerary_pdf

# app.py now lives in backend/; the DB, uploads/, and .env all stay at the
# project root (they're runtime/config, not source), so anchor to that.
BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {".pdf"}
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_PDF_MIME = "application/pdf"
MAX_DRIVE_PDFS = 100
MAX_DRIVE_FOLDER_DEPTH = 5
EDITABLE_FIELDS = {
    "traveler_name", "origin", "destination",
    "start_date", "end_date", "start_time", "end_time",
    "start_arrival_time", "end_departure_time", "airline", "pnr", "price",
    "booking_source", "notes",
}

app = Flask(
    __name__,
    template_folder=str(FRONTEND_DIR / "templates"),
    static_folder=str(FRONTEND_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Only mark the cookie Secure once actually served over HTTPS - browsers drop
# Secure cookies entirely over plain http://, which would break local dev.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true"

app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Add one to .env (see .env.example) - "
        "it's required to sign login session cookies."
    )
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)

# Only these Google Workspace domains may sign in. Override via env if the
# allowlist ever needs to change without a code deploy.
ALLOWED_EMAIL_DOMAINS = {
    d.strip().lower().lstrip("@")
    for d in os.environ.get(
        "ALLOWED_EMAIL_DOMAINS",
        "netcorecloud.com,netcoreunbxd.com,unbxd.com,netcore.ai",
    ).split(",")
    if d.strip()
}

# Endpoints reachable without a session - the login page itself, the
# sign-in callback, and logout. Everything else requires auth.
PUBLIC_PATHS = {"/login", "/auth/google", "/logout"}

_google_auth_request = google.auth.transport.requests.Request()

init_db()


@app.before_request
def _redirect_127_to_localhost():
    # Google OAuth treats "localhost" and "127.0.0.1" as different origins,
    # so anyone landing here via 127.0.0.1 (old bookmark, typed IP, etc.)
    # would silently fail the Drive sign-in. Force everyone onto localhost.
    if request.host.startswith("127.0.0.1"):
        return redirect(request.url.replace("127.0.0.1", "localhost", 1), code=302)


@app.before_request
def _require_login():
    if request.path.startswith("/static/") or request.path in PUBLIC_PATHS:
        return
    if session.get("user"):
        return
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not authenticated"}), 401
    return redirect(url_for("login"))


def _email_domain_allowed(email):
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in ALLOWED_EMAIL_DOMAINS


def _company_account_error():
    return "Only Netcore and Unbxd Google accounts are allowed."


def _access_token_userinfo(access_token):
    creds = google.oauth2.credentials.Credentials(token=access_token)
    service = googleapiclient.discovery.build(
        "oauth2", "v2", credentials=creds, cache_discovery=False
    )
    return service.userinfo().get().execute()


def _require_company_drive_account(access_token):
    """Drive OAuth can pick a different Google account than login. Reject it."""
    try:
        info = _access_token_userinfo(access_token)
    except Exception:
        return "Couldn't confirm which Google account is attaching from Drive. Try again."

    email = (info.get("email") or "").strip()
    if not email or not info.get("verified_email", True):
        return "Your Google account's email isn't verified."
    if not _email_domain_allowed(email):
        return _company_account_error() + " Use the same work account you signed in with."

    session_email = ((session.get("user") or {}).get("email") or "").strip().lower()
    if session_email and email.lower() != session_email:
        return (
            "Attach from Drive with the same Netcore or Unbxd account you used to sign in "
            f"({session_email}), not a personal Gmail."
        )
    return None


def row_to_dict(row):
    d = dict(row)
    d["needs_review"] = bool(d["needs_review"])
    return d


def fetch_trip(conn, trip_id):
    return conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()


def _insert_trip_row(conn, result, source_file, drive_file_id, drive_view_link, drive_managed):
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO trips
           (traveler_name, origin, destination, start_date, end_date, start_time, end_time,
            start_arrival_time, end_departure_time,
            airline, pnr, price, booking_source, status, source_format, needs_review, source_file,
            drive_file_id, drive_view_link, drive_managed, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?, '', ?, ?)""",
        (
            result["traveler_name"], result["origin"], result["destination"],
            result["start_date"], result["end_date"], result["start_time"], result["end_time"],
            result.get("start_arrival_time"), result.get("end_departure_time"),
            result["airline"], result["pnr"], result.get("price"), result.get("booking_source"),
            result["source_format"], int(result["needs_review"]), source_file,
            drive_file_id, drive_view_link, int(drive_managed), ts, ts,
        ),
    )
    conn.commit()
    return cur.lastrowid


@app.route("/")
def index():
    return render_template(
        "index.html",
        google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        google_api_key=os.environ.get("GOOGLE_PICKER_API_KEY", ""),
        google_app_id=os.environ.get("GOOGLE_APP_ID", ""),
        user=session.get("user"),
        allowed_domains=sorted(ALLOWED_EMAIL_DOMAINS),
    )


@app.route("/login")
def login():
    if session.get("user"):
        return redirect(url_for("index"))
    return render_template(
        "login.html",
        google_client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        allowed_domains=sorted(ALLOWED_EMAIL_DOMAINS),
    )


@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json(force=True) or {}
    credential = data.get("credential")
    if not credential:
        return jsonify({"error": "Missing credential"}), 400

    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
    try:
        payload = google.oauth2.id_token.verify_oauth2_token(credential, _google_auth_request, client_id)
    except ValueError:
        return jsonify({"error": "Invalid or expired sign-in token. Please try again."}), 401

    email = payload.get("email", "")
    if not email or not payload.get("email_verified"):
        return jsonify({"error": "Your Google account's email isn't verified."}), 403
    if not _email_domain_allowed(email):
        return jsonify({"error": _company_account_error() + " Sign in with a company Google account."}), 403

    session.clear()
    session.permanent = True
    session["user"] = {
        "email": email,
        "name": payload.get("name", email),
        "picture": payload.get("picture", ""),
    }
    return jsonify({"ok": True})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/trips", methods=["GET"])
def list_trips():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trips ORDER BY (start_date IS NULL), start_date, traveler_name"
    ).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


def _unique_upload_name(filename):
    """Local uploads/ is a flat folder shared by everyone, so two people
    attaching a same-named file (e.g. "ticket.pdf") can't collide."""
    safe = secure_filename(filename) or "ticket.pdf"
    stem, ext = os.path.splitext(safe)
    candidate = safe
    n = 1
    while (UPLOAD_DIR / candidate).exists():
        candidate = f"{stem}-{n}{ext}"
        n += 1
    return candidate


def _ingest_pdf_bytes(conn, filename, file_bytes):
    """Parse a ticket PDF and store it the same way as Attach from device."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Only PDF files are supported")
    result = parse_itinerary_pdf(io.BytesIO(file_bytes), filename=filename)
    stored_name = _unique_upload_name(filename)
    (UPLOAD_DIR / stored_name).write_bytes(file_bytes)
    try:
        new_id = _insert_trip_row(
            conn, result, stored_name,
            None, url_for("serve_upload", filename=stored_name), drive_managed=0,
        )
    except Exception:
        (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
        raise
    return fetch_trip(conn, new_id)


def _drive_file_get(service, file_id, fields):
    return service.files().get(
        fileId=file_id, fields=fields, supportsAllDrives=True,
    ).execute()


def _list_pdfs_in_drive_folder(service, folder_id, depth=0):
    """All PDFs in a Drive folder (and nested folders), capped for safety."""
    pdfs = []
    if depth > MAX_DRIVE_FOLDER_DEPTH:
        return pdfs
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while len(pdfs) < MAX_DRIVE_PDFS:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, mimeType, webViewLink)",
            pageSize=100,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in resp.get("files") or []:
            mime = item.get("mimeType") or ""
            name = item.get("name") or item.get("id")
            if mime == DRIVE_FOLDER_MIME:
                pdfs.extend(_list_pdfs_in_drive_folder(service, item["id"], depth + 1))
            elif mime == DRIVE_PDF_MIME or name.lower().endswith(".pdf"):
                pdfs.append(item)
            if len(pdfs) >= MAX_DRIVE_PDFS:
                return pdfs[:MAX_DRIVE_PDFS]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return pdfs[:MAX_DRIVE_PDFS]


def _collect_drive_pdfs(service, picked_ids):
    """Expand picked Drive files/folders into a PDF list, like a device folder."""
    pdfs, errors = [], []
    seen = set()
    for file_id in picked_ids:
        try:
            meta = _drive_file_get(service, file_id, "id, name, mimeType, webViewLink")
        except Exception as e:
            errors.append({"filename": file_id, "error": f"Couldn't read file info from Drive: {e}"})
            continue
        name = meta.get("name", file_id)
        mime = meta.get("mimeType") or ""
        if mime == DRIVE_FOLDER_MIME:
            try:
                nested = _list_pdfs_in_drive_folder(service, file_id)
            except Exception as e:
                errors.append({"filename": name, "error": f"Couldn't list tickets in this folder: {e}"})
                continue
            if not nested:
                errors.append({"filename": name, "error": "This folder has no PDF tickets"})
                continue
            for item in nested:
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                pdfs.append(item)
            continue
        if mime != DRIVE_PDF_MIME and not name.lower().endswith(".pdf"):
            errors.append({"filename": name, "error": "Only PDF files or folders of PDFs are supported"})
            continue
        if file_id not in seen:
            seen.add(file_id)
            pdfs.append(meta)
        if len(pdfs) >= MAX_DRIVE_PDFS:
            break
    return pdfs[:MAX_DRIVE_PDFS], errors


def _download_drive_bytes(service, file_id):
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(
        buf, service.files().get_media(fileId=file_id, supportsAllDrives=True),
    )
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


@app.route("/api/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    created, errors = [], []
    conn = get_db()
    for f in files:
        if not f.filename:
            continue
        try:
            row = _ingest_pdf_bytes(conn, f.filename, f.read())
        except Exception as e:
            conn.rollback()
            errors.append({"filename": f.filename, "error": str(e)})
            continue
        created.append(row_to_dict(row))

    conn.close()
    return jsonify({"created": created, "errors": errors})


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/attach-from-drive", methods=["POST"])
def attach_from_drive():
    data = request.get_json(force=True) or {}
    access_token = data.get("access_token")
    file_ids = data.get("file_ids") or []
    if not access_token:
        return jsonify({"error": "access_token is required"}), 400
    if not file_ids:
        return jsonify({"error": "file_ids is required"}), 400

    drive_account_error = _require_company_drive_account(access_token)
    if drive_account_error:
        return jsonify({"error": drive_account_error}), 403

    creds = google.oauth2.credentials.Credentials(token=access_token)
    service = googleapiclient.discovery.build("drive", "v3", credentials=creds, cache_discovery=False)

    pdfs, errors = _collect_drive_pdfs(service, file_ids)
    created = []
    conn = get_db()
    for meta in pdfs:
        name = meta.get("name", meta.get("id"))
        if Path(name).suffix.lower() not in ALLOWED_EXT:
            name = f"{name}.pdf"
        try:
            file_bytes = _download_drive_bytes(service, meta["id"])
        except Exception as e:
            errors.append({"filename": name, "error": f"Couldn't download file from Drive: {e}"})
            continue
        try:
            row = _ingest_pdf_bytes(conn, name, file_bytes)
        except Exception as e:
            conn.rollback()
            errors.append({"filename": name, "error": str(e)})
            continue
        created.append(row_to_dict(row))

    conn.close()
    return jsonify({"created": created, "errors": errors})


@app.route("/api/trips/<int:trip_id>", methods=["PUT"])
def update_trip(trip_id):
    data = request.get_json(force=True) or {}
    fields = {k: v for k, v in data.items() if k in EDITABLE_FIELDS}
    if not fields:
        return jsonify({"error": "No editable fields provided"}), 400

    conn = get_db()
    if not fetch_trip(conn, trip_id):
        conn.close()
        abort(404)

    fields["needs_review"] = 0
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [now_iso(), trip_id]
    conn.execute(f"UPDATE trips SET {set_clause}, updated_at = ? WHERE id = ?", values)
    conn.commit()
    row = fetch_trip(conn, trip_id)
    conn.close()
    return jsonify(row_to_dict(row))


@app.route("/api/trips/<int:trip_id>/status", methods=["POST"])
def set_status(trip_id):
    data = request.get_json(force=True) or {}
    status = data.get("status")
    leg = data.get("leg")  # None = whole trip, or "outbound" / "return"
    if status not in {"confirmed", "cancelled"}:
        return jsonify({"error": "status must be 'confirmed' or 'cancelled'"}), 400
    if leg not in (None, "outbound", "return"):
        return jsonify({"error": "leg must be 'outbound', 'return', or omitted"}), 400

    conn = get_db()
    row = fetch_trip(conn, trip_id)
    if not row:
        conn.close()
        abort(404)

    ts = now_iso()
    if leg is None:
        conn.execute(
            "UPDATE trips SET status = ?, outbound_status = ?, return_status = ?, updated_at = ? WHERE id = ?",
            (status, status, status, ts, trip_id),
        )
    else:
        leg_col = "outbound_status" if leg == "outbound" else "return_status"
        other_status = row["return_status"] if leg == "outbound" else row["outbound_status"]
        overall = "cancelled" if (status == "cancelled" and other_status == "cancelled") else "confirmed"
        conn.execute(
            f"UPDATE trips SET {leg_col} = ?, status = ?, updated_at = ? WHERE id = ?",
            (status, overall, ts, trip_id),
        )
    conn.commit()
    row = fetch_trip(conn, trip_id)
    conn.close()
    return jsonify(row_to_dict(row))


@app.route("/api/trips/<int:trip_id>/delete-leg", methods=["POST"])
def delete_leg(trip_id):
    """Permanently discard one leg of a round trip, collapsing the record
    down to a one-way trip for whichever leg is kept. Unlike /status
    (cancel/restore), this is destructive - the discarded leg's own
    date/time/route data is gone, not just flagged.
    """
    data = request.get_json(force=True) or {}
    leg = data.get("leg")
    if leg not in ("outbound", "return"):
        return jsonify({"error": "leg must be 'outbound' or 'return'"}), 400

    conn = get_db()
    row = fetch_trip(conn, trip_id)
    if not row:
        conn.close()
        abort(404)
    if row["start_date"] == row["end_date"]:
        conn.close()
        return jsonify({"error": "This trip only has one leg"}), 400

    pnr_parts = [p.strip() for p in row["pnr"].split("/")] if row["pnr"] else []

    if leg == "outbound":
        # Keep only the return leg: it becomes the trip's sole (one-way) leg.
        new_origin, new_destination = row["destination"], row["origin"]
        new_date = row["end_date"]
        new_start_time, new_end_time = row["end_departure_time"], row["end_time"]
        new_status = row["return_status"]
        new_pnr = pnr_parts[1] if len(pnr_parts) > 1 else (pnr_parts[0] if pnr_parts else None)
    else:
        new_origin, new_destination = row["origin"], row["destination"]
        new_date = row["start_date"]
        new_start_time, new_end_time = row["start_time"], row["start_arrival_time"]
        new_status = row["outbound_status"]
        new_pnr = pnr_parts[0] if pnr_parts else None

    conn.execute(
        """UPDATE trips SET
               origin = ?, destination = ?, start_date = ?, end_date = ?,
               start_time = ?, end_time = ?, start_arrival_time = NULL, end_departure_time = NULL,
               pnr = ?, status = ?, outbound_status = ?, return_status = ?, updated_at = ?
           WHERE id = ?""",
        (
            new_origin, new_destination, new_date, new_date,
            new_start_time, new_end_time,
            new_pnr, new_status, new_status, new_status, now_iso(),
            trip_id,
        ),
    )
    conn.commit()
    row = fetch_trip(conn, trip_id)
    conn.close()
    return jsonify(row_to_dict(row))


def _remove_stored_file(row):
    """Delete a trip's PDF only if this app owns the copy in uploads/.

    Device attach and Drive attach both store a local copy (no drive_file_id).
    Original files in the user's Google Drive are never deleted.
    """
    if not row["drive_file_id"] and row["source_file"]:
        (UPLOAD_DIR / row["source_file"]).unlink(missing_ok=True)


@app.route("/api/trips/<int:trip_id>", methods=["DELETE"])
def delete_trip(trip_id):
    conn = get_db()
    row = fetch_trip(conn, trip_id)
    if not row:
        conn.close()
        abort(404)
    conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    conn.commit()
    conn.close()
    _remove_stored_file(row)
    return jsonify({"deleted": trip_id})


@app.route("/api/trips", methods=["DELETE"])
def clear_all_trips():
    conn = get_db()
    rows = conn.execute("SELECT drive_file_id, drive_managed, source_file FROM trips").fetchall()
    conn.execute("DELETE FROM trips")
    conn.commit()
    conn.close()
    for row in rows:
        _remove_stored_file(row)
    return jsonify({"deleted": len(rows)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
