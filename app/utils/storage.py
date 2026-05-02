import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

import boto3
from botocore.client import Config
from fastapi import UploadFile


def _upload_dir() -> Path:
    disk_mount = os.getenv("RENDER_DISK_MOUNT_PATH")
    if disk_mount:
        path = Path(disk_mount) / "uploads"
    else:
        path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _upload_to_s3(filename: str, content: bytes, content_type: str | None) -> str:
    endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("R2_ENDPOINT_URL")
    bucket = os.getenv("S3_BUCKET") or os.getenv("R2_BUCKET")
    region = os.getenv("S3_REGION") or os.getenv("R2_REGION") or "auto"
    access_key = os.getenv("S3_ACCESS_KEY") or os.getenv("R2_ACCESS_KEY")
    secret_key = os.getenv("S3_SECRET_KEY") or os.getenv("R2_SECRET_KEY")
    public_base_url = os.getenv("S3_PUBLIC_BASE_URL") or os.getenv("R2_PUBLIC_BASE_URL")

    if not all([bucket, access_key, secret_key]):
        raise RuntimeError("S3 storage is enabled but missing S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    s3.put_object(
        Bucket=bucket,
        Key=filename,
        Body=content,
        ContentType=content_type or "application/octet-stream",
    )

    if public_base_url:
        return f"{public_base_url.rstrip('/')}/{filename}"
    if endpoint:
        return f"{endpoint.rstrip('/')}/{bucket}/{filename}"
    return f"https://{bucket}.s3.amazonaws.com/{filename}"


def _delete_from_s3(upload_path: str) -> bool:
    endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("R2_ENDPOINT_URL")
    bucket = os.getenv("S3_BUCKET") or os.getenv("R2_BUCKET")
    region = os.getenv("S3_REGION") or os.getenv("R2_REGION") or "auto"
    access_key = os.getenv("S3_ACCESS_KEY") or os.getenv("R2_ACCESS_KEY")
    secret_key = os.getenv("S3_SECRET_KEY") or os.getenv("R2_SECRET_KEY")
    public_base_url = os.getenv("S3_PUBLIC_BASE_URL") or os.getenv("R2_PUBLIC_BASE_URL")

    if not all([bucket, access_key, secret_key]):
        return False

    key = ""
    if public_base_url:
        prefix = public_base_url.rstrip("/") + "/"
        if upload_path.startswith(prefix):
            key = upload_path[len(prefix):]
    if not key and endpoint:
        prefix = endpoint.rstrip("/") + f"/{bucket}/"
        if upload_path.startswith(prefix):
            key = upload_path[len(prefix):]
    if not key and upload_path.startswith(f"https://{bucket}.s3.amazonaws.com/"):
        key = upload_path[len(f"https://{bucket}.s3.amazonaws.com/"):]
    if not key:
        parsed = urlparse(upload_path)
        path = unquote(parsed.path.lstrip("/"))
        if path.startswith(f"{bucket}/"):
            key = path[len(bucket) + 1:]
        else:
            key = path

    key = key.strip()
    if not key:
        return False

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    s3.delete_object(Bucket=bucket, Key=key)
    return True


def save_upload(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None

    ext = Path(upload.filename).suffix
    filename = f"{uuid4().hex}{ext}"
    content = upload.file.read()

    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    
    if backend in {"s3", "r2"}:
        return _upload_to_s3(filename, content, upload.content_type)
    
    # In production, STORAGE_BACKEND must be r2; no local storage allowed
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env in {"production", "prod"}:
        raise RuntimeError("STORAGE_BACKEND must be 'r2' in production. Local storage is disabled.")
    
    # Local storage only allowed in development
    upload_dir = _upload_dir()
    file_path = upload_dir / filename
    file_path.write_bytes(content)
    return f"/uploads/{filename}"


def delete_upload(upload_path: str | None) -> bool:
    if not upload_path:
        return False

    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    try:
        if backend in {"s3", "r2"}:
            return _delete_from_s3(upload_path)

        rel = upload_path.strip()
        if rel.startswith("/uploads/"):
            target = _upload_dir() / rel.replace("/uploads/", "", 1)
        else:
            target = Path(rel)
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False
    except Exception:
        return False
