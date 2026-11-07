import os

from supabase import create_client


class SupabaseStorageConfigurationError(RuntimeError):
    pass


def create_supabase_client():
    project_url = os.getenv("SUPABASE_URL")
    secret_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
    )
    if not project_url:
        raise SupabaseStorageConfigurationError("SUPABASE_URL is not configured.")
    if not secret_key:
        raise SupabaseStorageConfigurationError(
            "Set SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY."
        )
    try:
        return create_client(project_url, secret_key)
    except Exception as error:
        raise SupabaseStorageConfigurationError(
            "Could not connect to Supabase Storage."
        ) from error


def storage_bucket(bucket_name):
    if not bucket_name or "/" in bucket_name or "\\" in bucket_name:
        raise SupabaseStorageConfigurationError("The Supabase bucket name is invalid.")
    return create_supabase_client().storage.from_(bucket_name)
