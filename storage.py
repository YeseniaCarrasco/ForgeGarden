"""Photo uploads for Plant Help questions, Garden Journal posts, and the farmstand.

Photos go to a Google Cloud Storage bucket when GCS_BUCKET is set, and to a
local folder (UPLOAD_FOLDER, default instance/uploads) otherwise. Either way
they are served through /photos/<key>, so the bucket can stay private.

Files are checked by their first bytes, not by the name or the browser's
content type, and saved under a random name.
"""
import os
import re
import uuid

from flask import Blueprint, abort, current_app, send_from_directory, Response

bp = Blueprint("photos", __name__, url_prefix="/photos")

MAX_PHOTO_BYTES = 5 * 1024 * 1024
KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(jpg|png|gif|webp)$")
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


class PhotoError(ValueError):
    """The upload isn't a photo we accept. The message is shown to the user."""


def sniff_extension(data):
    """Return jpg/png/gif/webp from the file's first bytes, or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def media_type(key):
    return MEDIA_TYPES[key.rsplit(".", 1)[1]]


def read_upload(file_storage):
    """Validate an optional uploaded file.

    Returns (bytes, extension), or None if no file was chosen.
    Raises PhotoError if the file is too big or isn't a supported image.
    """
    if file_storage is None or not file_storage.filename:
        return None
    data = file_storage.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoError("Photos must be 5 MB or smaller.")
    ext = sniff_extension(data)
    if ext is None:
        raise PhotoError("Photos must be JPEG, PNG, GIF, or WebP images.")
    return data, ext


def _bucket():
    from google.cloud import storage  # imported here so local dev doesn't need GCP credentials

    client = current_app.extensions.get("gcs_client")
    if client is None:
        client = current_app.extensions["gcs_client"] = storage.Client()
    return client.bucket(current_app.config["GCS_BUCKET"])


def _local_folder():
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    return folder


def save_photo(data, ext):
    """Store photo bytes and return the new key (e.g. '3f2a...9c.jpg')."""
    key = f"{uuid.uuid4().hex}.{ext}"
    if current_app.config.get("GCS_BUCKET"):
        _bucket().blob(key).upload_from_string(data, content_type=MEDIA_TYPES[ext])
    else:
        with open(os.path.join(_local_folder(), key), "wb") as f:
            f.write(data)
    return key


def load_photo(key):
    """Return a stored photo's bytes (used to send the photo to the Plant Doctor)."""
    if current_app.config.get("GCS_BUCKET"):
        return _bucket().blob(key).download_as_bytes()
    with open(os.path.join(_local_folder(), key), "rb") as f:
        return f.read()


def delete_photo(key):
    """Remove a stored photo. Missing files are ignored."""
    if not key or not KEY_PATTERN.match(key):
        return
    try:
        if current_app.config.get("GCS_BUCKET"):
            _bucket().blob(key).delete()
        else:
            os.remove(os.path.join(_local_folder(), key))
    except Exception:  # noqa: BLE001 - a leftover file is harmless; don't fail the request
        current_app.logger.warning("Could not delete photo %s", key, exc_info=True)


@bp.route("/<key>")
def serve(key):
    if not KEY_PATTERN.match(key):
        abort(404)
    if current_app.config.get("GCS_BUCKET"):
        from google.api_core.exceptions import NotFound

        try:
            data = _bucket().blob(key).download_as_bytes()
        except NotFound:
            abort(404)
        response = Response(data, mimetype=media_type(key))
    else:
        response = send_from_directory(_local_folder(), key, mimetype=media_type(key))
    # Keys are random and never reused, so browsers can cache photos for a long time.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
