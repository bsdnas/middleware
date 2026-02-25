#!/usr/bin/env python3
"""
Update OpenZFS ports under nas_ports to a new version and GitHub tag.

Usage:
    tools/update_openzfs_ports.py <version> <github_tag>
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


GH_ACCOUNT = "dravanet"
GH_PROJECT = "openzfs-zfs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update OpenZFS port Makefiles and distinfo files."
    )
    parser.add_argument("version", help="Port version, e.g. 2.3.6")
    parser.add_argument("github_tag", help="GitHub tag/commit, e.g. 20fa09b5...")
    return parser.parse_args()


def normalize_github_tag(github_tag: str) -> str:
    # If this looks like a raw commit SHA (7-40 hex chars), store the
    # abbreviated 10-char form used in port metadata.
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", github_tag):
        return github_tag[:10]
    return github_tag


def replace_line(text: str, key: str, value: str, path: Path) -> str:
    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}=\t{value}"
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Expected exactly one '{key}=' line in {path}, found {count}")
    return updated


def update_makefile(path: Path, version: str, github_tag: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_line(text, "PORTVERSION", version, path)
    text = replace_line(text, "GH_TAGNAME", github_tag, path)
    path.write_text(text, encoding="utf-8")


def download_and_hash(version: str, github_tag: str) -> tuple[str, int, str]:
    distfile = f"{GH_ACCOUNT}-{GH_PROJECT}-v{version}-{github_tag}_GH0.tar.gz"
    url = f"https://codeload.github.com/{GH_ACCOUNT}/{GH_PROJECT}/tar.gz/{github_tag}?dummy=/{distfile}"

    hasher = hashlib.sha256()
    size = 0

    with tempfile.NamedTemporaryFile(prefix="openzfs-distfile-", suffix=".tar.gz") as tmp:
        try:
            with urllib.request.urlopen(url) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
        except urllib.error.URLError as err:
            raise RuntimeError(f"Failed to download {url}: {err}") from err

    return hasher.hexdigest(), size, distfile


def update_distinfo(path: Path, distfile: str, sha256: str, size: int) -> None:
    body = (
        f"TIMESTAMP = {int(time.time())}\n"
        f"SHA256 ({distfile}) = {sha256}\n"
        f"SIZE ({distfile}) = {size}\n"
    )
    path.write_text(body, encoding="utf-8")


def main() -> int:
    args = parse_args()
    version = args.version
    github_tag = normalize_github_tag(args.github_tag)

    repo_root = Path(__file__).resolve().parent.parent
    port_dirs = [
        repo_root / "nas_ports/filesystems/openzfs",
        repo_root / "nas_ports/filesystems/openzfs-kmod",
    ]

    for port_dir in port_dirs:
        makefile = port_dir / "Makefile"
        if not makefile.exists():
            raise RuntimeError(f"Missing file: {makefile}")
        update_makefile(makefile, version, github_tag)

    sha256, size, distfile = download_and_hash(version, github_tag)

    for port_dir in port_dirs:
        distinfo = port_dir / "distinfo"
        if not distinfo.exists():
            raise RuntimeError(f"Missing file: {distinfo}")
        update_distinfo(distinfo, distfile, sha256, size)

    print(f"Updated OpenZFS ports to version {version}")
    print(f"GitHub tag: {github_tag}")
    print(f"Distfile: {distfile}")
    print(f"SHA256: {sha256}")
    print(f"SIZE: {size}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(1)
