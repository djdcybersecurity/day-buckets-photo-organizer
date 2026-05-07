#!/usr/bin/env python3
# daybuckets.py - CLI utility for SDI-4233 DayBuckets
# Stdlib only.

from __future__ import annotations
import argparse
import json
import os
import sys
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone
import urllib.parse
import urllib.request
import time

try:
    from zoneinfo import ZoneInfo  # optional
except Exception:
    ZoneInfo = None


# ------------- helpers -------
def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dirs(project: Path) -> None:
    (project / "incoming").mkdir(parents=True, exist_ok=True)
    (project / "logs").mkdir(parents=True, exist_ok=True)


def log_line(project: Path, msg: str) -> None:
    ensure_dirs(project)
    log_file = project / "logs" / "daybuckets.log"
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{iso_now()} {msg}\n")


def echo(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg)


def resolve_project(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


# ----- fetch helpers -----
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def api_get(params: dict, retries: int = 3, timeout: int = 20) -> dict:
    """Call MediaWiki API (GET) with User-Agent and retries."""
    qs = urllib.parse.urlencode(params)
    url = f"{COMMONS_API}?{qs}"
    headers = {"User-Agent": "DayBucketsBot/1.0 (student project)"}
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise


def commons_iter_files_by_category(category: str, limit: int):
    """Yield file pages from a Commons category with imageinfo + extmetadata."""
    fetched = 0
    cont = None
    while fetched < limit:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "categorymembers",
            "gcmtitle": f"Category:{category}",
            "gcmnamespace": "6",
            "gcmtype": "file",
            "gcmlimit": min(50, limit - fetched),
            "prop": "imageinfo",
            "iiprop": "url|timestamp|extmetadata|size",
        }
        if cont:
            params["gcmcontinue"] = cont

        obj = api_get(params)
        pages = (obj.get("query") or {}).get("pages") or []
        for page in pages:
            if fetched >= limit:
                break
            ii = (page.get("imageinfo") or [])
            if not ii:
                continue
            info = ii[0]
            yield {
                "pageid": page.get("pageid"),
                "title": page.get("title"),
                "imageinfo": info,
            }
            fetched += 1

        cont = (obj.get("continue") or {}).get("gcmcontinue")
        if not cont:
            break


def parse_datetime_original(value: str | None) -> datetime | None:
    if not value:
        return None
    candidates = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    if value.endswith("Z"):
        try:
            dt = datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def parse_upload_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except Exception:
        return None


def file_safe_name_from_title(title: str) -> str:
    name = title.split(":", 1)[-1].strip() if ":" in title else title
    return name.replace("/", "_").replace("\\", "_")


def write_sidecar_json(sidecar: Path, payload: dict, dry_run: bool, verbose: bool, project: Path):
    if dry_run:
        echo(f"[dry-run] would write sidecar: {sidecar}", verbose)
        log_line(project, f"FETCH sidecar (dry-run): {sidecar.name}")
        return
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log_line(project, f"FETCH sidecar wrote: {sidecar.name}")


def set_file_mtime(path: Path, dt: datetime, dry_run: bool, verbose: bool, project: Path):
    ts = dt.timestamp()
    if dry_run:
        echo(f"[dry-run] would set mtime {dt.isoformat()} on {path.name}", verbose)
        log_line(project, f"FETCH mtime (dry-run): {path.name} -> {dt.isoformat()}")
        return
    os.utime(path, (ts, ts))
    log_line(project, f"FETCH mtime set: {path.name} -> {dt.isoformat()}")


def download_file(url: str, dest: Path, dry_run: bool, verbose: bool, project: Path) -> bool:
    if dry_run:
        echo(f"[dry-run] would download {url} -> {dest}", verbose)
        log_line(project, f"FETCH download (dry-run): {dest.name}")
        return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "DayBucketsBot/1.0 (student project)")
        print(f"DEBUG: downloading {url} -> {dest}")  # 🔎 Debug
        with urllib.request.urlopen(req) as resp, dest.open("wb") as out:
            shutil.copyfileobj(resp, out)
        log_line(project, f"FETCH downloaded: {dest.name}")
        return True
    except Exception as e:
        log_line(project, f"FETCH download ERROR for {dest.name}: {e!r}")
        print(f"DEBUG ERROR: failed to download {url} -> {dest}, error={e!r}")
        return False


# ---------- subcommands ----------
def cmd_fetch(args: argparse.Namespace) -> int:
    project = resolve_project(args.dest)
    incoming = project / "incoming"
    ensure_dirs(project)

    cat = args.category
    limit = args.limit
    prefer = args.set_mtime_from

    log_line(project, f"FETCH start category='{cat}' limit={limit} prefer={prefer} dry_run={args.dry_run} verbose={args.verbose}")
    echo(f"Fetching up to {limit} files from Commons category '{cat}' (prefer mtime from {prefer})", args.verbose)

    count_ok = 0
    count_skip = 0
    for item in commons_iter_files_by_category(cat, limit):
        pageid = item.get("pageid")
        title = item.get("title") or "File:unknown"
        info = item.get("imageinfo") or {}
        url = info.get("url")
        upload_ts = info.get("timestamp")
        extmd = (info.get("extmetadata") or {})

        if not url:
            log_line(project, f"FETCH skip pageid={pageid} title='{title}': missing download URL")
            echo(f"SKIP (no URL): {title}", args.verbose)
            count_skip += 1
            continue

        name = file_safe_name_from_title(title)
        dest_path = incoming / name
        sidecar_path = incoming / f"{name}.meta.json"

        def md_val(key: str) -> str | None:
            v = extmd.get(key)
            if isinstance(v, dict):
                return v.get("value")
            return v

        meta_DateTimeOriginal = md_val("DateTimeOriginal")
        meta_LicenseShortName = md_val("LicenseShortName")
        meta_Artist = md_val("Artist")

        dt_meta = parse_datetime_original(meta_DateTimeOriginal) if meta_DateTimeOriginal else None
        dt_upload = parse_upload_timestamp(upload_ts) if upload_ts else None

        chosen_dt = None
        if prefer == "meta" and dt_meta:
            chosen_dt = dt_meta
        elif dt_upload:
            chosen_dt = dt_upload
        elif dt_meta:
            chosen_dt = dt_meta

        sidecar_payload = {
            "title": title,
            "pageid": pageid,
            "original_url": url,
            "upload_timestamp": dt_upload.isoformat() if dt_upload else upload_ts,
            "extmetadata": {
                "DateTimeOriginal": meta_DateTimeOriginal,
                "LicenseShortName": meta_LicenseShortName,
                "Artist": meta_Artist,
            },
        }

        ok = download_file(url, dest_path, args.dry_run, args.verbose, project)
        if not ok:
            count_skip += 1
            continue

        write_sidecar_json(sidecar_path, sidecar_payload, args.dry_run, args.verbose, project)

        if chosen_dt:
            set_file_mtime(dest_path, chosen_dt, args.dry_run, args.verbose, project)
        else:
            log_line(project, f"FETCH note: no usable timestamp for {dest_path.name}; leaving OS mtime")

        echo(f"OK: {name}", args.verbose)
        count_ok += 1

        if not args.dry_run:
            time.sleep(0.2)

    log_line(project, f"FETCH end ok={count_ok} skipped={count_skip}")
    echo(f"Done. ok={count_ok}, skipped={count_skip}", True)
    return 0


def iter_source_files(src: Path, pattern: str, ignore_hidden: bool):
    """Yield (status, Path) for each file in src matching pattern."""
    for f in src.glob(pattern):
        try:
            if ignore_hidden and f.name.startswith("."):
                yield ("skip_hidden", f)
                continue
            if f.is_symlink():
                yield ("skip_hidden", f)
                continue
            if f.is_file():
                yield ("ok", f)
        except Exception:
            continue


def cmd_organize(args: argparse.Namespace) -> int:
    project = resolve_project(args.dest)
    src = Path(args.src).expanduser().resolve() if args.src else project / "incoming"
    buckets_root = project / "buckets"
    ensure_dirs(project)

    log_line(
        project,
        f"ORGANIZE start src='{src}' mode={args.mode} pattern='{args.pattern}' "
        f"ignore_hidden={args.ignore_hidden} tz='{args.tz}' "
        f"dry_run={args.dry_run} verbose={args.verbose}"
    )

    if not src.exists():
        echo(f"Source directory does not exist: {src}", True)
        log_line(project, f"ORGANIZE ERROR: missing src {src}")
        return 1

    moved = 0
    skipped_hidden = 0
    collisions = 0
    errors = 0

    for status, f in iter_source_files(src, args.pattern, args.ignore_hidden):
        if status == "skip_hidden":
            skipped_hidden += 1
            log_line(project, f"ORGANIZE skip hidden/symlink: {f}")
            continue

        planned = plan_dest_path(buckets_root, f, args.tz)
        dest = planned
        if dest.exists():
            dest = with_collision_suffix(dest)
            collisions += 1

        ok = copy_or_move(f, dest, args.mode, args.dry_run, project, args.verbose)
        if ok:
            moved += 1
        else:
            errors += 1

    log_line(
        project,
        f"ORGANIZE end moved={moved} skipped_hidden={skipped_hidden} "
        f"collisions={collisions} errors={errors}"
    )
    echo(
        f"Done. moved={moved}, skipped_hidden={skipped_hidden}, "
        f"collisions={collisions}, errors={errors}",
        True
    )
    return 0 if errors == 0 else 2

def plan_dest_path(buckets_root: Path, f: Path, tz: str) -> Path:
    """Decide destination path inside buckets/YYYY/MM/DD based on file mtime."""
    try:
        st = f.stat()
        dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        if ZoneInfo and tz:
            try:
                dt = dt.astimezone(ZoneInfo(tz))
            except Exception:
                pass
    except Exception:
        # fallback: use now
        dt = datetime.now(timezone.utc)

    return buckets_root / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}" / f.name


def with_collision_suffix(path: Path) -> Path:
    """If file already exists, add numeric suffix before extension."""
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    new_path = parent / f"{stem}_{i}{suffix}"
    while new_path.exists():
        i += 1
        new_path = parent / f"{stem}_{i}{suffix}"
    return new_path


def copy_or_move(src: Path, dest: Path, mode: str, dry_run: bool, project: Path, verbose: bool) -> bool:
    """Copy or move file depending on mode."""
    try:
        if dry_run:
            echo(f"[dry-run] {mode} {src} -> {dest}", verbose)
            log_line(project, f"ORGANIZE {mode} (dry-run): {src.name} -> {dest}")
            return True

        dest.parent.mkdir(parents=True, exist_ok=True)
        if mode == "move":
            shutil.move(str(src), str(dest))
            log_line(project, f"ORGANIZE moved: {src.name} -> {dest}")
        else:
            shutil.copy2(str(src), str(dest))
            log_line(project, f"ORGANIZE copied: {src.name} -> {dest}")

        echo(f"{mode.upper()} OK: {src} -> {dest}", verbose)
        return True
    except Exception as e:
        log_line(project, f"ORGANIZE ERROR {src.name}: {e!r}")
        echo(f"ERROR: {src} -> {dest} ({e})", True)
        return False


def cmd_report(args: argparse.Namespace) -> int:
    project = resolve_project(args.dest)
    ensure_dirs(project)
    out_md = Path(args.out) if args.out else project / "report.md"
    manifest_path = project / "manifest.json"
    buckets_root = project / "buckets"

    log_line(project, f"REPORT start out='{out_md}' tz='{args.tz}' verbose={args.verbose}")

    if args.dry_run:
        echo(f"[dry-run] would scan '{buckets_root}' and write '{out_md}' + '{manifest_path}'", args.verbose)
        return 0

    report_lines = ["# DayBuckets Report", ""]
    manifest = {"buckets": {}}

    if not buckets_root.exists():
        report_lines.append("_No buckets found._")
    else:
        for bucket_dir in sorted(buckets_root.rglob("*")):
            if bucket_dir.is_dir():
                files = list(bucket_dir.glob("*"))
                if not files:
                    continue
                rel_dir = bucket_dir.relative_to(buckets_root)
                report_lines.append(f"### {rel_dir}")
                manifest["buckets"][str(rel_dir)] = []
                for f in sorted(files):
                    report_lines.append(f"- {f.name}")
                    manifest["buckets"][str(rel_dir)].append(f.name)
                report_lines.append("")

    # Write markdown report
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(report_lines), encoding="utf-8")

    # Write JSON manifest
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    echo(f"Wrote {out_md} and {manifest_path}", True)
    log_line(project, f"REPORT wrote detailed report and manifest: {out_md.name}, {manifest_path.name}")
    return 0



# ---------- argparse ----------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daybuckets",
        description="Fetch Commons images, bucket by day, and report. (SDI-4233)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, allow_dry_run: bool = False):
        p.add_argument("--verbose", action="store_true", help="Print actions to stdout.")
        if allow_dry_run:
            p.add_argument("--dry-run", action="store_true", help="Show what would happen without writing files.")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Download images + sidecar metadata from a Commons category.")
    p_fetch.add_argument("--category", required=True, help='Commons category name WITHOUT the "Category:" prefix.')
    p_fetch.add_argument("--dest", required=True, help="Project directory (e.g., ./project).")
    p_fetch.add_argument("--limit", type=int, default=25, help="Max files to fetch.")
    p_fetch.add_argument("--set-mtime-from", choices=["meta", "upload"], default="meta",
                         help="Set file mtime from DateTimeOriginal (meta) if available, else from upload time.")
    add_common(p_fetch, allow_dry_run=True)
    p_fetch.set_defaults(func=cmd_fetch)

    # organize
    p_org = subparsers.add_parser("organize", help="Bucket files by mtime into YYYY/MM/DD folders.")
    p_org.add_argument("--dest", required=True, help="Project directory (e.g., ./project).")
    p_org.add_argument("--src", default=None, help="Source dir (default: project/incoming)")
    p_org.add_argument("--mode", choices=["copy", "move"], default="copy", help="Copy (preserve) or move files.")
    p_org.add_argument("--pattern", default="*", help='Glob pattern for files to include (default "*").')
    p_org.add_argument("--ignore-hidden", action="store_true", default=True, help="Skip hidden files and symlinks.")
    p_org.add_argument("--tz", default="America/Chicago", help="Timezone for bucketing/reporting (optional).")
    add_common(p_org, allow_dry_run=True)
    p_org.set_defaults(func=cmd_organize)

    # report
    p_rep = subparsers.add_parser("report", help="Generate report.md and manifest.json from buckets.")
    p_rep.add_argument("--dest", required=True, help="Project directory (e.g., ./project).")
    p_rep.add_argument("--out", default=None, help="Path for report.md (default: PROJECT/report.md).")
    p_rep.add_argument("--tz", default="America/Chicago", help="Timezone for date display (optional).")
    add_common(p_rep, allow_dry_run=True)
    p_rep.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
