"""
Apply CORS policy from tools/r2_cors.json to the R2 bucket.

Usage:
  python tools/set_r2_cors.py          # show current + apply from r2_cors.json
  python tools/set_r2_cors.py --show   # only print the current policy
"""

import argparse
import json
import sys
from pathlib import Path

from r2_upload import R2Client

CORS_FILE = Path(__file__).resolve().parent / "r2_cors.json"


def _get_current(client):
    try:
        resp = client.s3.get_bucket_cors(Bucket=client.cfg.bucket)
        return resp.get("CORSRules", [])
    except Exception as e:
        if "NoSuchCORSConfiguration" in str(e) or "NoSuchCorsConfiguration" in str(e):
            return []
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="only show current CORS, do not apply")
    args = ap.parse_args()

    client = R2Client()
    print(f"Bucket: {client.cfg.bucket}\n")

    current = _get_current(client)
    print("Current CORS policy:")
    print(json.dumps(current, indent=2) if current else "  (none)")
    print()

    if args.show:
        return

    if not CORS_FILE.exists():
        sys.stderr.write(f"Missing {CORS_FILE}\n")
        sys.exit(1)

    rules = json.loads(CORS_FILE.read_text())
    client.s3.put_bucket_cors(
        Bucket=client.cfg.bucket,
        CORSConfiguration={"CORSRules": rules},
    )
    print(f"Applied CORS policy from {CORS_FILE.name}")
    print(json.dumps(rules, indent=2))


if __name__ == "__main__":
    main()
