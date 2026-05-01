import os
from pathlib import Path
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
