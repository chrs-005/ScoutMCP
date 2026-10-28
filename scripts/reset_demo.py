"""Reset data/ to the demo roster and starting ledger (run before recording the screencast)."""

import shutil
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

for name in ("members.json", "ledger.json"):
    shutil.copyfile(DATA / "seed" / name, DATA / name)
    print(f"reset data/{name}")
