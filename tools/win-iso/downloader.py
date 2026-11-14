#!/usr/bin/env python3
"""Download an ISO from a user-resolved, official Microsoft HTTPS URL.

The source page may require a browser, registration, or Microsoft-issued signed URL.
This tool deliberately does not scrape undocumented endpoints or bypass access gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog.json")
DEFAULT_DESTINATION = Path("/home/tyc4d/cr-images")
ALLOWED_HOSTS = ("microsoft.com", "windows.com")
CHUNK_SIZE = 1024 * 1024


def catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def list_releases() -> list[dict[str, Any]]:
    return catalog()["releases"]


def _check_official_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not any(host == d or host.endswith("." + d) for d in ALLOWED_HOSTS):
        raise ValueError("URL 必須是 HTTPS 的 Microsoft 官方網域 (microsoft.com/windows.com)")


def _request(url: str, headers: dict[str, str]) -> urllib.request.Response:
    _check_official_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "CyberRange-WinMedia/1.0", **headers})
    response = urllib.request.urlopen(request, timeout=60)
    _check_official_url(response.geturl())
    return response


def download_iso(
    release_id: str,
    official_url: str,
    *,
    destination: Path = DEFAULT_DESTINATION,
    filename: str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Resume download from an official Microsoft URL and calculate/verify SHA-256.

    `expected_sha256` should be copied from Microsoft's published hash table. Without
    it, the computed digest is recorded but cannot independently establish authenticity.
    """
    releases = {item["id"]: item for item in list_releases()}
    if release_id not in releases:
        raise ValueError(f"未知 release id: {release_id}")
    _check_official_url(official_url)
    if expected_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 必須為 64 位十六進位 SHA-256")
    parsed_name = Path(urllib.parse.unquote(urllib.parse.urlparse(official_url).path)).name
    filename = filename or parsed_name or f"{release_id}.iso"
    if Path(filename).name != filename or not filename.lower().endswith(".iso"):
        raise ValueError("filename 必須是單層 .iso 檔名")

    destination.mkdir(parents=True, exist_ok=True)
    final_path = destination / filename
    part_path = destination / (filename + ".part")
    offset = part_path.stat().st_size if part_path.exists() else 0
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        response = _request(official_url, headers)
    except urllib.error.HTTPError as exc:
        if offset and exc.code == 416:
            part_path.unlink(missing_ok=True)
            return download_iso(release_id, official_url, destination=destination, filename=filename,
                                expected_sha256=expected_sha256)
        raise

    status = getattr(response, "status", response.getcode())
    if offset and status != 206:
        # Server ignored Range; restart safely rather than append a full response.
        offset = 0
    content_range = response.headers.get("Content-Range")
    if offset and (not content_range or not content_range.startswith(f"bytes {offset}-")):
        response.close()
        raise ValueError("伺服器回傳的 Content-Range 不符；保留 .part 供檢查")
    total = None
    if content_range and "/" in content_range:
        try:
            total = int(content_range.rsplit("/", 1)[1])
        except ValueError:
            pass
    if total is None:
        length = response.headers.get("Content-Length")
        total = offset + int(length) if length and length.isdigit() else None

    mode = "ab" if offset else "wb"
    bytes_done = offset
    try:
        with response, part_path.open(mode) as out:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                bytes_done += len(chunk)
                percent = f"{bytes_done * 100 / total:.1f}%" if total else "size unknown"
                print(f"\r{bytes_done:,} bytes ({percent})", end="", file=sys.stderr, flush=True)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        print(file=sys.stderr)
        raise
    print(file=sys.stderr)

    if total is not None and bytes_done != total:
        raise IOError(f"下載長度不符：收到 {bytes_done} / {total} bytes；可再次執行續傳")
    digest = hashlib.sha256()
    with part_path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    sha256 = digest.hexdigest()
    if expected_sha256 and sha256.lower() != expected_sha256.lower():
        raise ValueError(f"SHA-256 不符：計算值 {sha256}；檔案保留在 {part_path}")
    part_path.replace(final_path)
    return {
        "release_id": release_id,
        "path": str(final_path),
        "bytes": bytes_done,
        "sha256": sha256,
        "sha256_verified_against_microsoft": bool(expected_sha256),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出已整理的官方來源版本")
    get = sub.add_parser("download", help="下載 ISO；先從 Microsoft 頁面取得當次有效 URL")
    get.add_argument("release_id")
    get.add_argument("--url", required=True, help="從 Microsoft 官方頁面取得的 HTTPS ISO URL")
    get.add_argument("--sha256", help="Microsoft 發布的 SHA-256；提供後才會做來源雜湊比對")
    get.add_argument("--filename")
    get.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps(list_releases(), ensure_ascii=False, indent=2))
        return 0
    result = download_iso(args.release_id, args.url, destination=args.destination,
                          filename=args.filename, expected_sha256=args.sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
