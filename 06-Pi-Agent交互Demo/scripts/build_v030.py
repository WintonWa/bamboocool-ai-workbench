#!/usr/bin/env python3
import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from v030.pipeline import build_dataset


if __name__ == "__main__":
    print(json.dumps(build_dataset(), ensure_ascii=False, indent=2))
