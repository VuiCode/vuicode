#!/usr/bin/env bash
# Clean generated and untracked files for VuiCode App

# Set the path to Git Bash
GIT_BASH="C:\Program Files\Git\git-bash.exe"

# Run git clean in a new Git Bash window
"$GIT_BASH" --cd="c:/Users/canng/vuicode" -c \
"git clean -fd vuicode-app/backend/content/code \
             vuicode-app/backend/content/blog \
             vuicode-app/backend/content/video \
             vuicode-app/backend/artifacts"

echo "Clean complete."