import os
import uuid
from io import BytesIO
from pathlib import Path

from flask import current_app, g, url_for
from supabase import create_client
from werkzeug.utils import secure_filename


DEFAULT_PROFILE_BUCKET = "employee-profiles"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024


class ProfileStorageError(RuntimeError):
    pass


def _profile_bucket_name():
    return os.getenv("SUPABASE_PROFILE_BUCKET", DEFAULT_PROFILE_BUCKET)


def _is_safe_storage_path(path):
    return bool(path) and "/" not in path and "\\" not in path and path not in {
        ".",
        "..",
    }


def _legacy_local_picture_url(path):
    if not _is_safe_storage_path(path):
        return None

    local_path = (
        Path(current_app.root_path)
        / "static"
        / "uploads"
        / "profiles"
        / path
    )
    if local_path.is_file():
        return url_for("static", filename=f"uploads/profiles/{path}")
    return None


def profile_picture_url(path):
    return profile_picture_urls([path]).get(path) if path else None


def profile_picture_urls(paths):
    cached_urls = getattr(g, "profile_picture_urls", {})
    urls = {}
    remote_paths = []

    for path in dict.fromkeys(path for path in paths if path):
        if path in cached_urls:
            urls[path] = cached_urls[path]
            continue

        legacy_url = _legacy_local_picture_url(path)
        if legacy_url:
            urls[path] = legacy_url
        elif _is_safe_storage_path(path):
            remote_paths.append(path)
        else:
            raise ProfileStorageError("The stored profile picture path is invalid.")

    if not remote_paths:
        cached_urls.update(urls)
        g.profile_picture_urls = cached_urls
        return urls

    try:
        signed_urls = _storage_bucket().create_signed_urls(
            remote_paths,
            expires_in=3600,
        )
    except ProfileStorageError:
        raise
    except Exception as error:
        raise ProfileStorageError(
            "Supabase Storage could not create profile picture URLs."
        ) from error

    for path, signed_url in zip(remote_paths, signed_urls):
        url = signed_url.get("signedURL") or signed_url.get("signedUrl")
        if signed_url.get("error") or not url:
            raise ProfileStorageError(
                "Supabase Storage could not create a profile picture URL."
            )
        urls[path] = url

    if len(signed_urls) != len(remote_paths):
        raise ProfileStorageError(
            "Supabase Storage returned incomplete profile picture URLs."
        )

    cached_urls.update(urls)
    g.profile_picture_urls = cached_urls
    return urls


def save_profile_picture(file, employee_id):
    """Validate and upload a profile picture; return its storage key and error."""
    if not file or not file.filename:
        return None, None

    original_filename = secure_filename(file.filename)
    if not original_filename or "." not in original_filename:
        return None, "Choose a valid image file."

    extension = original_filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "Upload a PNG, JPG, JPEG, or WEBP image."

    image_data = file.read(MAX_IMAGE_SIZE + 1)
    file.seek(0)

    if not image_data:
        return None, "The selected image is empty."
    if len(image_data) > MAX_IMAGE_SIZE:
        return None, "The image must be 5 MB or smaller."

    try:
        from PIL import Image

        with Image.open(BytesIO(image_data)) as image:
            image_format = image.format
            image.verify()
    except Exception:
        return None, "The uploaded file is not a valid image."

    image_details = {
        "PNG": ("png", "image/png"),
        "JPEG": ("jpg", "image/jpeg"),
        "WEBP": ("webp", "image/webp"),
    }
    if image_format not in image_details:
        return None, "The uploaded file is not a supported image."

    extension, content_type = image_details[image_format]
    filename = f"employee_{employee_id}_{uuid.uuid4().hex}.{extension}"
    try:
        upload_profile_picture(filename, image_data, content_type)
    except ProfileStorageError:
        current_app.logger.exception(
            "Could not upload employee profile picture to Supabase Storage."
        )
        return None, (
            "The profile picture could not be uploaded. Check the storage "
            "configuration and try again."
        )

    return filename, None


def _storage_bucket():
    project_url = os.getenv("SUPABASE_URL")
    secret_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
    )
    if not project_url:
        raise ProfileStorageError("SUPABASE_URL is not configured.")
    if not secret_key:
        raise ProfileStorageError(
            "Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY."
        )

    try:
        return create_client(project_url, secret_key).storage.from_(
            _profile_bucket_name()
        )
    except Exception as error:
        raise ProfileStorageError(
            "Could not connect to Supabase Storage."
        ) from error


def upload_profile_picture(path, image_data, content_type):
    try:
        _storage_bucket().upload(
            path,
            image_data,
            {
                "content-type": content_type,
                "upsert": "false",
            },
        )
    except ProfileStorageError:
        raise
    except Exception as error:
        raise ProfileStorageError(
            "Supabase Storage could not upload the profile picture."
        ) from error


def delete_profile_picture(path):
    if not path or _legacy_local_picture_url(path):
        return

    if not _is_safe_storage_path(path):
        raise ProfileStorageError("The stored profile picture path is invalid.")

    try:
        _storage_bucket().remove([path])
    except ProfileStorageError:
        raise
    except Exception as error:
        raise ProfileStorageError(
            "Supabase Storage could not delete the profile picture."
        ) from error
