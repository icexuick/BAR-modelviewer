"""
R2 upload helper.

Reads credentials from tools/.env (or env vars) and uploads files to a
Cloudflare R2 bucket using the S3-compatible API.

Required env vars:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
  R2_BUCKET, R2_PUBLIC_URL
"""

import os
import sys
import hashlib
import mimetypes
from pathlib import Path
from typing import Iterable, Optional

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except ImportError:
    sys.stderr.write("boto3 is required. Install with: pip install -r tools/requirements.txt\n")
    raise

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


CONTENT_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".hdr": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ktx2": "image/ktx2",
    ".dds": "image/vnd.ms-dds",
    ".json": "application/json",
}


class R2Config:
    def __init__(self):
        env_path = Path(__file__).resolve().parent / ".env"
        if load_dotenv and env_path.exists():
            load_dotenv(env_path)
        self.account_id = os.environ.get("R2_ACCOUNT_ID", "").strip()
        self.access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
        self.secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.environ.get("R2_BUCKET", "").strip()
        self.public_url = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

    def is_configured(self) -> bool:
        return all([self.account_id, self.access_key, self.secret_key, self.bucket])

    def missing(self) -> list:
        out = []
        for name, val in [
            ("R2_ACCOUNT_ID", self.account_id),
            ("R2_ACCESS_KEY_ID", self.access_key),
            ("R2_SECRET_ACCESS_KEY", self.secret_key),
            ("R2_BUCKET", self.bucket),
        ]:
            if not val:
                out.append(name)
        return out


def _content_type(path: Path) -> str:
    ct = CONTENT_TYPES.get(path.suffix.lower())
    if ct:
        return ct
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _md5_hex(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class R2Client:
    def __init__(self, cfg: Optional[R2Config] = None):
        self.cfg = cfg or R2Config()
        if not self.cfg.is_configured():
            raise RuntimeError(
                f"R2 not configured — missing env vars: {', '.join(self.cfg.missing())}. "
                f"Set them in tools/.env"
            )
        endpoint = f"https://{self.cfg.account_id}.r2.cloudflarestorage.com"
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=self.cfg.access_key,
            aws_secret_access_key=self.cfg.secret_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            region_name="auto",
        )

    def _head(self, key: str) -> Optional[dict]:
        try:
            return self.s3.head_object(Bucket=self.cfg.bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def needs_upload(self, local: Path, key: str) -> bool:
        head = self._head(key)
        if head is None:
            return True
        local_md5 = _md5_hex(local)
        remote_etag = head.get("ETag", "").strip('"')
        # Multipart uploads have ETags like "<md5>-N"; for those we can't
        # cheaply compare, so re-upload only if size differs.
        if "-" in remote_etag:
            return head.get("ContentLength") != local.stat().st_size
        return remote_etag != local_md5

    def upload(self, local: Path, key: str, force: bool = False) -> bool:
        """Upload local file to R2 under `key`. Returns True if uploaded, False if skipped."""
        if not force and not self.needs_upload(local, key):
            return False
        extra = {"ContentType": _content_type(local)}
        self.s3.upload_file(str(local), self.cfg.bucket, key, ExtraArgs=extra)
        return True

    def upload_many(self, items: Iterable[tuple], force: bool = False, verbose: bool = True) -> dict:
        """Upload (local_path, key) tuples. Returns stats dict."""
        uploaded = skipped = failed = 0
        for local, key in items:
            local = Path(local)
            try:
                if self.upload(local, key, force=force):
                    uploaded += 1
                    if verbose:
                        print(f"  uploaded  {key}")
                else:
                    skipped += 1
                    if verbose:
                        print(f"  skipped   {key} (unchanged)")
            except Exception as e:
                failed += 1
                sys.stderr.write(f"  FAILED    {key}: {e}\n")
        return {"uploaded": uploaded, "skipped": skipped, "failed": failed}

    def public_url_for(self, key: str) -> str:
        return f"{self.cfg.public_url}/{key}" if self.cfg.public_url else key
