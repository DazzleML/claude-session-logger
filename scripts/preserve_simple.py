#!/usr/bin/env python3
"""
Backup list→root, recursing into any directories.
Usage:  python backup_recursive.py  list.txt  <DestRoot>
"""

import hashlib, json, shutil, sys
from pathlib import Path
from datetime import datetime

BUF = 1 << 20  # 1 MiB read buffer

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        while chunk := f.read(BUF):
            h.update(chunk)
    return h.hexdigest()

def mirror_path(src: Path, dest_root: Path) -> Path:
    drive = src.drive[0].upper()          # 'C'
    rel   = src.relative_to(src.anchor)   # path\to\file.txt
    return dest_root / drive / rel

def copy_file(src: Path, dest_root: Path, log: list):
    dst = mirror_path(src, dest_root)
    dst.parent.mkdir(parents=True, exist_ok=True)

    h_src = sha256(src)
    shutil.copy2(src, dst)                # copies times & mode bits
    h_dst = sha256(dst)

    log.append({
        "source": str(src),
        "dest":   str(dst),
        "hash":   h_src,
        "status": "OK" if h_src == h_dst else "HASH_MISMATCH"
    })

def main(list_file: str, dest_root: str):
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    log = []
    for raw in Path(list_file).read_text().splitlines():
        path = Path(raw.strip().strip('"')).resolve()
        if path.is_file():
            copy_file(path, dest_root, log)
        elif path.is_dir():
            for f in path.rglob('*'):
                if f.is_file():
                    copy_file(f, dest_root, log)
        else:
            log.append({"source": str(path), "status": "NOT_FOUND"})

    log_path = dest_root / f"backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    log_path.write_text(json.dumps(log, indent=2))
    print(f"Backup finished → {log_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: backup_recursive.py list.txt <DestRoot>")
    main(sys.argv[1], sys.argv[2])
