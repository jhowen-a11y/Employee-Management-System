import hashlib
import os
import threading
import time
import uuid
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

from flask import current_app, g, has_request_context, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from services.supabase_storage import (
    SupabaseStorageConfigurationError,
    storage_bucket,
)


DEFAULT_PROFILE_BUCKET = "employee-profiles"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024
SIGNED_URL_CACHE_SECONDS = 3300
SIGNED_URL_CACHE_LIMIT = 1024
_signed_url_cache = OrderedDict()
_signed_url_cache_lock = threading.Lock()


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

    user_scope = _signed_url_cache_scope()
    paths_to_sign = []
    project_url = os.getenv("SUPABASE_URL", "")
    bucket_name = _profile_bucket_name()
    storage_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
    )
    storage_key_id = (
        hashlib.sha256(storage_key.encode()).digest()
        if storage_key
        else None
    )
    cache_scope = user_scope if storage_key_id else None
    for path in remote_paths:
        cache_key = cache_scope + (
            project_url,
            bucket_name,
            storage_key_id,
            path,
        ) if cache_scope else None
        signed_url = _get_cached_signed_url(cache_key) if cache_key else None
        if signed_url:
            urls[path] = signed_url
        else:
            paths_to_sign.append(path)

    if not paths_to_sign:
        cached_urls.update(urls)
        g.profile_picture_urls = cached_urls
        return urls

    signing_started = time.perf_counter()
    try:
        signed_urls = _storage_bucket().create_signed_urls(
            paths_to_sign,
            expires_in=3600,
        )
    except ProfileStorageError:
        raise
    except Exception as error:
        raise ProfileStorageError(
            "Supabase Storage could not create profile picture URLs."
        ) from error
    finally:
        g.profile_picture_signing_ms = (
            getattr(g, "profile_picture_signing_ms", 0.0)
            + (time.perf_counter() - signing_started) * 1000
        )

    if len(signed_urls) != len(paths_to_sign):
        raise ProfileStorageError(
            "Supabase Storage returned incomplete profile picture URLs."
        )

    for path, signed_url in zip(paths_to_sign, signed_urls):
        url = signed_url.get("signedURL") or signed_url.get("signedUrl")
        if signed_url.get("error") or not url:
            raise ProfileStorageError(
                "Supabase Storage could not create a profile picture URL."
            )
        urls[path] = url
        if cache_scope:
            _store_cached_signed_url(
                cache_scope + (
                    project_url,
                    bucket_name,
                    storage_key_id,
                    path,
                ),
                url,
            )

    cached_urls.update(urls)
    g.profile_picture_urls = cached_urls
    return urls


def _signed_url_cache_scope():
    if not has_request_context() or not current_user.is_authenticated:
        return None
    return current_user.get_id(), current_user.role


def _get_cached_signed_url(cache_key):
    now = time.monotonic()
    with _signed_url_cache_lock:
        cached = _signed_url_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, signed_url = cached
        if expires_at <= now:
            del _signed_url_cache[cache_key]
            return None
        _signed_url_cache.move_to_end(cache_key)
        return signed_url


def _store_cached_signed_url(cache_key, signed_url):
    with _signed_url_cache_lock:
        _signed_url_cache[cache_key] = (
            time.monotonic() + SIGNED_URL_CACHE_SECONDS,
            signed_url,
        )
        _signed_url_cache.move_to_end(cache_key)
        while len(_signed_url_cache) > SIGNED_URL_CACHE_LIMIT:
            _signed_url_cache.popitem(last=False)


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
    try:
        return storage_bucket(_profile_bucket_name())
    except SupabaseStorageConfigurationError as error:
        raise ProfileStorageError(str(error)) from error
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
