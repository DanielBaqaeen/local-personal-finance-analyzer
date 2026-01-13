import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
APP_DIR = SRC / "subsentry" / "app"
PAGES_DIR = APP_DIR / "pages"


if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pages = []

home_path = APP_DIR / "Home.py"
if home_path.exists():
    pages.append(
        st.Page(str(home_path.relative_to(ROOT)), title="Home", default=True)
    )


if PAGES_DIR.exists():
    for p in sorted(PAGES_DIR.glob("*.py")):
        stem = p.stem
        title = stem.split("_", 1)[1].replace("_", " ") if "_" in stem else stem.replace("_", " ")
        pages.append(st.Page(str(p.relative_to(ROOT)), title=title))

nav = st.navigation(pages)
nav.run()
