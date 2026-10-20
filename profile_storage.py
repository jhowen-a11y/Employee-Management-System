import os
from pathlib import Path
from urllib.parse import quote

from flask import current_app, url_for
from supabase import create_client


DEFAULT_PROFILE_BUCKET = "employee-profiles"


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
    if not path:
        return None

    legacy_url = _legacy_local_picture_url(path)
    if legacy_url:
        return legacy_url

    if not _is_safe_storage_path(path):
        raise ProfileStorageError("The stored profile picture path is invalid.")

    project_url = os.getenv("SUPABASE_URL")
    if not project_url:
        raise ProfileStorageError("SUPABASE_URL is not configured.")

    bucket = quote(_profile_bucket_name(), safe="")
    object_path = quote(path, safe="")
    return (
        f"{project_url.rstrip('/')}/storage/v1/object/public/"
        f"{bucket}/{object_path}"
    )


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
