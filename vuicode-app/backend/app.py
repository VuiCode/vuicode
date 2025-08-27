import os
import json
import time
import uuid
import shutil
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# -------- Paths & Settings --------
ROOT = Path(".").resolve()
# ROOT = Path(__file__).parent.parent.resolve()
TOOLS_DIR = ROOT / "tools"
CONTENT_DIR = ROOT / "content"
CODE_DIR = CONTENT_DIR / "code"
ARTIFACTS = ROOT / "artifacts"
JOBS_DIR = ARTIFACTS / "jobs"
FRONTEND_DEMOS_MOUNT = ROOT / "content" / "code"  # we'll serve /demo/{slug}/frontend from here

print(f"ROOT: {ROOT}")
print(f"TOOLS_DIR: {TOOLS_DIR}")
print(f"CONTENT_DIR: {CONTENT_DIR}")
print(f"CODE_DIR: {CODE_DIR}")
print(f"ARTIFACTS: {ARTIFACTS}")
print(f"JOBS_DIR: {JOBS_DIR}")
print(f"FRONTEND_DEMOS_MOUNT: {FRONTEND_DEMOS_MOUNT}")

for d in (ARTIFACTS, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)
  

# -------- App --------
app = FastAPI(title="VuiCode Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static for previews of generated frontend demos
# e.g., GET /demo/chatbot-flask-plus-react/frontend/index.html
app.mount("/demo", StaticFiles(directory=str(FRONTEND_DEMOS_MOUNT), html=True), name="demo")

# -------- In-memory job state --------
JOBS: Dict[str, Dict[str, Any]] = {}

def _save_job(job_id: str):
    path = JOBS_DIR / f"{job_id}.json"
    path.write_text(json.dumps(JOBS[job_id], indent=2, ensure_ascii=False), encoding="utf-8")

def _update_job(job_id: str, **kw):
    JOBS[job_id].update(kw)
    _save_job(job_id)

# -------- Models --------
class GenerateRequest(BaseModel):
    topic: str
    slug: str                         # required now
    backend_template: str             # required now
    frontend_template: str            # required now
    dry_run: bool = False
    skip_repair: bool = False
    mode: str = "all"  # scaffold | content | verify | all

class PublishRequest(BaseModel):
    slug: str

# -------- Helpers --------
def _slugify(s: str) -> str:
    import re
    s = s.strip().lower().replace("+", " plus ")
    # allow letters, digits, hyphen, underscore
    s = re.sub(r"[^a-z0-9\-_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "project"

def _list_templates(kind: str) -> List[str]:
    # kind in {"backend","frontend"}
    base = TOOLS_DIR / "templates" / kind
    names = []
    if base.exists():
        for p in base.glob("*.yaml"):
            try:
                # read name field
                import yaml  # type: ignore
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("name"):
                    names.append(str(data.get("name")))
            except Exception:
                pass
    return sorted(set(names))

# -------- Job runner thread --------
def _run_generate(job_id: str):
    job = JOBS[job_id]
    topic = job["topic"]
    slug = job["slug"]
    args = job["args"]
    _update_job(job_id, status="running", started_at=time.time())

    cmd = [os.getenv("PYTHON_BIN", "python"), str(TOOLS_DIR / "generate_content.py")]
    cmd += ["--mode", args.get("mode","all")]
    cmd += ["--topic", topic]
    cmd += ["--slug", slug]
    if args.get("backend_template"):
        cmd += ["--backend-template", args["backend_template"]]
    if args.get("frontend_template"):
        cmd += ["--frontend-template", args["frontend_template"]]
    # Always point ui-path to content/ui/{slug} for preview (or configurable later)
    ui_dest = f"content/ui/{slug}"
    cmd += ["--ui-path", ui_dest]
    if args.get("dry_run"):
        cmd += ["--dry-run"]
    if args.get("skip_repair"):
        cmd += ["--skip-repair"]

    JOBS[job_id]["command"] = cmd
    _save_job(job_id)
    
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
        stdout, stderr = proc.stdout, proc.stderr
        JOBS[job_id]["stdout_tail"] = (stdout or "")[-2000:]
        JOBS[job_id]["stderr_tail"] = (stderr or "")[-2000:]
        JOBS[job_id]["returncode"] = proc.returncode
        if proc.returncode == 0:
            _update_job(job_id, status="succeeded", finished_at=time.time())
        else:
            _update_job(job_id, status="failed", finished_at=time.time())
    except Exception as e:
        JOBS[job_id]["stderr_tail"] = str(e)
        _update_job(job_id, status="error", finished_at=time.time())

# -------- API --------
@app.get("/api/templates")
def list_templates():
    return {
        "backend": _list_templates("backend"),
        "frontend": _list_templates("frontend"),
    }


@app.post("/api/generate")
def generate(req: GenerateRequest, bg: BackgroundTasks):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    slug_raw = (req.slug or "").strip()
    if not slug_raw:
        raise HTTPException(status_code=400, detail="slug (project name) is required")

    slug = _slugify(slug_raw)

    be_tpl = (req.backend_template or "").strip()
    fe_tpl = (req.frontend_template or "").strip()
    if not be_tpl:
        raise HTTPException(status_code=400, detail="backend_template is required")
    if not fe_tpl:
        raise HTTPException(status_code=400, detail="frontend_template is required")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "id": job_id,
        "status": "queued",
        "topic": topic,
        "slug": slug,
        "created_at": time.time(),
        "args": {
            "topic": topic,
            "slug": slug,
            "backend_template": be_tpl,
            "frontend_template": fe_tpl,
            "dry_run": req.dry_run,
            "skip_repair": req.skip_repair,
            "mode": req.mode,
        },
    }
    _save_job(job_id)
    bg.add_task(_run_generate, job_id)
    return {"job_id": job_id, "slug": slug}

@app.get("/api/status/{job_id}")
def status(job_id: str):
    if job_id not in JOBS:
        p = JOBS_DIR / f"{job_id}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        raise HTTPException(status_code=404, detail="job not found")
    return JOBS[job_id]

@app.get("/api/preview/blog")
def preview_blog(slug: str, lang: str = Query("en")):
    p = CONTENT_DIR / "blog" / slug / (f"post.{lang}.md")
    if not p.exists():
        raise HTTPException(status_code=404, detail="blog not found")
    return {"slug": slug, "lang": lang, "markdown": p.read_text(encoding="utf-8")}

@app.get("/api/preview/script")
def preview_script(slug: str):
    p = (CONTENT_DIR / "video" / slug / "script.md")
    if not p.exists():
        raise HTTPException(status_code=404, detail="script not found")
    return {"slug": slug, "script": p.read_text(encoding="utf-8")}

class PublishResult(BaseModel):
    slug: str
    medium_status: str = "stubbed"
    youtube_status: str = "stubbed"

@app.post("/api/publish", response_model=PublishResult)
def publish(req: PublishRequest):
    # Stub for now. Later: call your real publisher scripts.
    # We mark as stubbed and return links (if you want, compute expected URLs).
    return PublishResult(slug=req.slug)

# Health endpoint
@app.get("/api/health")
def health():
    return {"ok": True, "pong": "pong"}