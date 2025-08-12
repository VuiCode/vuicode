# VuiCode AI Content Pipeline

This repo hosts blog content, video scripts, code demos, and templates for VuiCode.

## Structure
```
vuicode/
  content/
    blog/           # markdown posts EN/VN
    video/          # scripts, captions, thumbnails
    code/           # demo source, tests
  templates/
    intro.mp4       # intro (you already created)
    outro.mp4       # outro (you already created)
    yt_description.md
    medium_frontmatter.yaml
  tools/            # AI & build scripts
  .env.example
  README.md
```

## Quick Start
1. Copy `.env.example` to `.env` and fill keys.
2. Create and activate a Python venv.
3. Install deps:
   ```bash
   pip install openai python-dotenv elevenlabs pyyaml markdownify moviepy
   ```
4. Generate content (blogs EN/VN + video script):
   ```bash
   python tools/generate_content.py
   ```
5. (Optional) Create voice audio from script:
   ```bash
   python tools/make_audio.py
   ```

## Notes
- Replace `templates/intro.mp4` & `templates/outro.mp4` later if you update animations.
- Keep text/logo inside YouTube's "safe area" when adding overlays.
