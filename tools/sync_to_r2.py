"""
Sync local assets (glb/, tex/, hdr/) to Cloudflare R2.

Examples:
  # Upload everything new/changed
  python tools/sync_to_r2.py --all

  # Just one folder
  python tools/sync_to_r2.py --glb
  python tools/sync_to_r2.py --tex
  python tools/sync_to_r2.py --hdr

  # One unit
  python tools/sync_to_r2.py --unit corjugg

  # Force re-upload even if remote matches
  python tools/sync_to_r2.py --all --force
"""

import argparse
import sys
from pathlib import Path

from r2_upload import R2Client


REPO_ROOT = Path(__file__).resolve().parent.parent

FOLDERS = {
    "glb": REPO_ROOT / "glb",
    "tex": REPO_ROOT / "tex",
    "hdr": REPO_ROOT / "hdr",
}


def _iter_folder(folder: Path, prefix: str):
    """Yield (local_path, r2_key) for every file in folder (recursive)."""
    if not folder.exists():
        return
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        rel = p.relative_to(folder).as_posix()
        yield p, f"{prefix}/{rel}"


def main():
    ap = argparse.ArgumentParser(description="Sync assets to Cloudflare R2")
    ap.add_argument("--all", action="store_true", help="Sync glb/, tex/, hdr/")
    ap.add_argument("--glb", action="store_true", help="Sync glb/")
    ap.add_argument("--tex", action="store_true", help="Sync tex/")
    ap.add_argument("--hdr", action="store_true", help="Sync hdr/")
    ap.add_argument("--unit", help="Sync a single GLB by unit name (without .glb)")
    ap.add_argument("--force", action="store_true", help="Re-upload even if remote matches")
    ap.add_argument("--quiet", action="store_true", help="Less output")
    args = ap.parse_args()

    if not (args.all or args.glb or args.tex or args.hdr or args.unit):
        ap.error("specify at least one of --all / --glb / --tex / --hdr / --unit")

    client = R2Client()
    if not args.quiet:
        print(f"R2 bucket: {client.cfg.bucket}")
        print(f"Public:    {client.cfg.public_url}")
        print()

    items = []
    if args.unit:
        glb_path = FOLDERS["glb"] / f"{args.unit}.glb"
        if not glb_path.exists():
            sys.stderr.write(f"GLB not found: {glb_path}\n")
            sys.exit(1)
        items.append((glb_path, f"glb/{args.unit}.glb"))

    if args.all or args.glb:
        items.extend(_iter_folder(FOLDERS["glb"], "glb"))
    if args.all or args.tex:
        items.extend(_iter_folder(FOLDERS["tex"], "tex"))
    if args.all or args.hdr:
        items.extend(_iter_folder(FOLDERS["hdr"], "hdr"))

    if not items:
        print("Nothing to sync.")
        return

    if not args.quiet:
        print(f"Checking {len(items)} files...")

    stats = client.upload_many(items, force=args.force, verbose=not args.quiet)
    print()
    print(f"Done — uploaded: {stats['uploaded']}, skipped: {stats['skipped']}, failed: {stats['failed']}")
    if stats["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
