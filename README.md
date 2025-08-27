# VuiCode App (E2E MVP)

A tiny backend + frontend that drives your generator (`tools/generate_content.py`) and runner (`tools/run_all_tests.py`).

## Layout
vuicode-app/
  backend/
    app.py
    requirements.txt
  frontend/
    index.html
    app.js
    style.css

## Run the backend
```bash
cd /path/to/your/repo    # where tools/generate_content.py exists
cd vuicode-app/backend

For first time:
  python -m venv .venv && .venv\Scripts\activate
  pip install -r requirements.txt
  or
  pip install fastapi uvicorn pydantic
Second time and so on:
  source .venv/Scripts/activate
uvicorn app:app --reload --port 8080
```

## Run the frontend
cd vuicode-app/frontend
python -m http.server 5500
--> then open  http://localhost:5500/
example: Build AI Chatbot with Flask & React

## Endpoints

- POST /api/generate → start a job (runs generator with --mode all)
- GET /api/status/{job_id} → check job status/log tails
- GET /api/preview/blog?slug=<slug>&lang=en|vi
- GET /api/preview/script?slug=<slug>
- POST /api/publish (stub)
- GET /demo/<slug>/frontend/ → serves generated demo frontend