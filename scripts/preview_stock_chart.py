#!/usr/bin/env python3
"""Run the dashboard and its stock chart API on the local machine."""
import argparse
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8878)
    args = parser.parse_args()
    php = shutil.which("php")
    if not php:
        parser.error("PHP with the cURL extension is required for chart previews")
    os.chdir(ROOT)
    address = f"127.0.0.1:{args.port}"
    print(f"Local: http://{address}/chart/", flush=True)
    os.execv(php, [php, "-S", address, "scripts/preview-stock-router.php"])
