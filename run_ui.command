#!/bin/bash
# Double-click (or run) to start the site2rss UI on http://localhost:8501
cd "$(dirname "$0")" || exit 1
git pull --rebase --autostash -q 2>/dev/null || true
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements-ui.txt
# Skip Streamlit's first-run email prompt
mkdir -p ~/.streamlit
[ -f ~/.streamlit/credentials.toml ] || printf '[general]\nemail = ""\n' > ~/.streamlit/credentials.toml
exec .venv/bin/streamlit run ui/app.py --server.port 8501
