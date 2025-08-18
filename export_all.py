#!/usr/bin/env python3
import os

ROOT = "change-clothes"
EXTS = {".py", ".json", ".txt", ".html", ".js", ".css"}
OUT = "all_code.txt"

with open(OUT, "w", encoding="utf-8") as fout:
    for base, _, files in os.walk(ROOT):
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1]
            if ext in EXTS:
                path = os.path.join(base, fn)
                fout.write(f"\n===== {path} =====\n")
                with open(path, "r", encoding="utf-8") as fin:
                    fout.write(fin.read())

