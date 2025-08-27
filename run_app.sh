#!/usr/bin/env bash
# filepath: c:\Users\canng\vuicode\run_app.sh

# Set the path to Git Bash
GIT_BASH="C:\Program Files\Git\git-bash.exe"

# Start backend in a new Git Bash window
"$GIT_BASH" --cd="c:/Users/canng/vuicode/vuicode-app/backend" -c "source .venv/Scripts/activate && uvicorn app:app --reload --port 8080" &

# Start frontend in a new Git Bash window
"$GIT_BASH" --cd="c:/Users/canng/vuicode/vuicode-app/frontend" -c "python -m http.server 5500" &