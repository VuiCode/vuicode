#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VuiCode Generator — Generic, Stack-Agnostic, Auto-Template (BE/FE compose)

Key features
- Load backend/frontend templates dynamically from tools/templates/backend and tools/templates/frontend.
  (Each stack folder provides a single entry file named 'stack.test.yaml' plus any scaffold files).
- Compose BE+FE into content/code/{slug}; write {slug}.test.yaml that `extends` the BE/FE stack configs.
- Merge config at runtime: extends -> vars merge -> overrides -> ${VAR} resolution -> path normalization.
- Emit merged.test.yaml and call tools/run_all_tests.py; read report JSON; optional LLM customize + repair loop.
- Modes: scaffold | content | verify | all
- Flags: --dry-run (skip LLM steps), --skip-repair (no repair loop on failure)

Usage examples:
  python tools/generate_content.py --mode all --topic "Build AI Chatbot with Flask & React" --ui-path frontend
  python tools/generate_content.py --mode scaffold --topic "Spring Boot API + Vue SPA"
  python tools/generate_content.py --mode verify --slug chatbot-flask-plus-react --ui-path frontend
"""

from __future__ import annotations
import argparse, json, os, re, sys, time, shutil, subprocess, copy
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# -------------------- constants / layout --------------------
ROOT = Path(".").resolve()
CONTENT = ROOT / "content"
BLOG = CONTENT / "blog"
VIDEO = CONTENT / "video"
CODE = CONTENT / "code"
TOOLS = ROOT / "tools"
TEMPLATES_DIR_BE = TOOLS / "templates" / "backend"
TEMPLATES_DIR_FE = TOOLS / "templates" / "frontend"
ARTIFACTS = ROOT / "artifacts"

MAX_REPAIR_TRIES = 2
DEFAULT_BE_PORT = 5000
DEFAULT_FE_PORT = 5173

# -------------------- small helpers --------------------
def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def slugify(s: str) -> str:
    s = s.strip().lower().replace("+", " plus ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "project"

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def write(path: Path, data: str | bytes, binary: bool = False):
    ensure_dir(path.parent)
    mode = "wb" if binary else "w"
    with open(path, mode, encoding=None if binary else "utf-8") as f:
        f.write(data)
    print(f"wrote {path}")

def read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")

def try_load_yaml_or_json(path: Path) -> dict:
    txt = read(path)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(txt)
    except Exception:
        return json.loads(txt)

def dump_yaml(obj: dict) -> str:
    try:
        import yaml  # type: ignore
        return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)
    except Exception:
        return json.dumps(obj, indent=2, ensure_ascii=False)

def is_safe_relpath(rel: str, allowed_roots=("backend/", "frontend/")) -> bool:
    if rel.startswith("../") or rel.startswith("/") or rel.startswith("content/"):
        return False
    return any(rel.startswith(ar) for ar in allowed_roots)

def _normalize_relpath(rel: str, kind_hint: Optional[str] = None) -> Optional[str]:
    """
    Normalize incoming template paths to forward-slash, safe, and under backend/ or frontend/.
    Returns None if the path is unsafe.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None
    s = rel.strip().replace("\\", "/")
    # strip leading ./ or /
    while s.startswith("./"):
        s = s[2:]
    if s.startswith("/"):
        return None

    # If already valid, keep
    if s.startswith("backend/") or s.startswith("frontend/"):
        return s

    # Try to infer: if author gave "app.py" and this is a backend template, prefix it
    if kind_hint == "backend":
        candidate = "backend/" + s
        return candidate if is_safe_relpath(candidate) else None
    if kind_hint == "frontend":
        candidate = "frontend/" + s
        return candidate if is_safe_relpath(candidate) else None

    # Final check: reject
    return None

def norm_cmd_list(x: Any) -> List[str]:
    if isinstance(x, list) and all(isinstance(s, str) for s in x):
        return x
    raise ValueError("command must be a list[str]")

from pathlib import Path

def hydrate_files_from_stack_dir(tpl: dict) -> dict:
    """
    Merge textual files found next to this template (…/<stack>/backend/**, frontend/**)
    into tpl['files'] if they aren't already listed. Also defaults editable_files if missing.
    """
    base = Path(tpl.get("__path", "")).parent
    if not base.exists():
        return tpl

    existing = dict(tpl.get("files") or {})
    discovered = {}

    for sub in ("backend", "frontend"):
        root = base / sub
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # skip binaries
            rel = f"{sub}/{p.relative_to(root).as_posix()}"
            discovered[rel] = text

    # MERGE: do not overwrite anything the YAML already specified
    for k, v in discovered.items():
        existing.setdefault(k, v)

    if existing:
        tpl["files"] = existing
        if not tpl.get("editable_files"):
            tpl["editable_files"] = [
                k for k in existing if k.endswith((".py", ".js", ".ts", ".tsx", ".html", ".css"))
            ][:30]
    return tpl


# -------------------- OpenAI (LLM) --------------------
def gen_openai(system: str, prompt: str, model: str = "gpt-4o-mini", temperature: float = 0.2) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return json.dumps({"__error__": "OPENAI_API_KEY not set", "__prompt_head__": prompt[:300]})
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return r.choices[0].message.content
    except Exception as e:
        return json.dumps({"__error__": f"GEN_ERROR: {e}", "__prompt_head__": prompt[:300]})

# -------------------- Template registry --------------------
def scan_templates(dirpath: Path) -> Dict[str, dict]:
    """
    Scan stacks in a directory. Each stack lives in a subfolder:
      tools/templates/backend/<stack>/
        - stack.test.yaml (required entry)
        - ... (scaffold files under backend/)
    The registry key will be the folder name; we attach '__path' to stack.test.yaml.
    """
    reg: Dict[str, dict] = {}
    if not dirpath.exists():
        return reg
    for stack_dir in dirpath.iterdir():
        if not stack_dir.is_dir():
            continue
        entry = stack_dir / "stack.test.yaml"
        if not entry.exists():
            continue
        try:
            d = try_load_yaml_or_json(entry)
            if isinstance(d, dict):
                # use folder name as template "name"
                d.setdefault("name", stack_dir.name)
                d["__path"] = str(entry)
                reg[stack_dir.name] = d
        except Exception:
            pass
    return reg

def best_match_by_topic(reg: Dict[str, dict], topic: str) -> Optional[str]:
    t = (topic or "").lower()
    best, score = None, 0
    for name, tpl in reg.items():
        kws = [k.lower() for k in tpl.get("detect", []) if isinstance(k, str)]
        sc = sum(1 for k in kws if k in t) if kws else 0
        if sc > score:
            best, score = name, sc
    return best

def validate_template(kind: str, tpl: dict):
    # Minimal fields expected inside stack.test.yaml
    if not isinstance(tpl, dict):
        raise ValueError(f"{kind} template must be a dict")
    for key in ("services", "tests"):
        if key not in tpl or not isinstance(tpl[key], list):
            raise ValueError(f"{kind} template missing/invalid '{key}' list")
    # services basic checks
    for svc in tpl.get("services", []):
        if not all(k in svc for k in ("name","cwd","start")):
            raise ValueError(f"{kind} service missing fields: {svc}")
        norm_cmd_list(svc["start"])
    # tests basic checks
    for t in tpl.get("tests", []):
        if not all(k in t for k in ("name","type","cwd","cmd")):
            raise ValueError(f"{kind} test missing fields: {t}")
        norm_cmd_list(t["cmd"])

def save_template(kind: str, name: str, tpl: dict) -> Path:
    base = TEMPLATES_DIR_BE if kind == "backend" else TEMPLATES_DIR_FE
    ensure_dir(base / name)
    p = base / name / "stack.test.yaml"
    write(p, dump_yaml(tpl))
    tpl["__path"] = str(p)
    return p

# -------------------- Auto-template generation --------------------
AUTO_TEMPLATE_CONTRACT = dedent("""
Contract for auto-generated stacks (STRICT YAML in stack.test.yaml semantics):

- Create a minimal but runnable stack for KIND = backend or frontend.
- For backend:
  * Provide an HTTP API on a fixed port (default 5000 if unsure).
  * Endpoints: GET /api/ping -> reply contains "pong"; POST /api/echo; POST /api/chat {"message"} -> {"reply"}.
  * Enable CORS so FE at :5173 can call.
  * Provide at least one test that outputs JUnit XML to a known path (e.g., backend/pytest_report.xml).
- For frontend:
  * Provide a minimal UI that calls window.API_BASE + "/api/ping" and "/api/chat".
  * Default dev server port 5173 (or set FE_PORT var).
  * Provide at least one Playwright test that outputs JUnit XML (e.g., frontend/test-results/results.xml).
- services[]: each has name, cwd (backend/ or frontend subdir), start (list[str]), and healthcheck with url, expect(optional), timeout_sec.
- tests[]: each has name, type="junit", cwd, cmd (list[str]), junit_xml path; optional install (list[list[str]]).
- Include 'vars' with reasonable defaults: BE_PORT/BE_API_BASE or FE_PORT/FE_BASE_URL.
- Output STRICT YAML for stack.test.yaml (no markdown fences).
""")

def autogen_template(kind: str, topic: str) -> dict:
    system = "You are a senior scaffolder. Output STRICT YAML suitable for stack.test.yaml only."
    role = "backend" if kind == "backend" else "frontend"
    prompt = f"""Topic: {topic}
KIND: {role}

{AUTO_TEMPLATE_CONTRACT}
Return ONLY the YAML content for stack.test.yaml (no extra text).
"""
    raw = gen_openai(system, prompt)
    try:
        import yaml
        tpl = yaml.safe_load(raw)
        if not isinstance(tpl, dict):
            raise ValueError("YAML not a mapping")
        validate_template(kind, tpl)
        return tpl
    except Exception as e:
        raise RuntimeError(f"Auto-template generation failed ({kind}): {e}\nRAW head:\n{raw[:400]}")

# -------------------- Resolve templates (by name or detect or autogen) --------------------
def load_or_autogen_template(kind: str, topic: str, name: Optional[str]) -> dict:
    root = TEMPLATES_DIR_BE if kind == "backend" else TEMPLATES_DIR_FE
    reg  = scan_templates(root)

    chosen = name or best_match_by_topic(reg, topic or "")
    if chosen and chosen in reg:
        tpl = reg[chosen]

        # attach path (in case scan_templates didn't)
        if "__path" not in tpl:
            tpl["__path"] = str(root / chosen / "stack.test.yaml")

        # 🔹 HYDRATE FIRST so files + editable_files are present
        tpl = hydrate_files_from_stack_dir(tpl)

        # validate AFTER hydration
        validate_template(kind, tpl)

        print(f"Using existing {kind} stack: {chosen}")
        return tpl

    print(f"No {kind} stack matched; auto-generating from topic…")
    tpl = autogen_template(kind, topic or "generic project")

    # derive a name for the new stack
    base_name = (name or role_from_topic(topic) or f"{kind}-auto").lower()
    base_name = re.sub(r"[^a-z0-9\-]+", "-", base_name).strip("-") or f"{kind}-auto"

    # save the raw autogen first
    save_template(kind, base_name, tpl)

    print(f"New {kind} stack saved: {base_name}/stack.test.yaml")

    # re-scan to load normalized dict, then hydrate + validate
    reg = scan_templates(root)
    tpl = reg[base_name]
    if "__path" not in tpl:
        tpl["__path"] = str(root / base_name / "stack.test.yaml")

    # 🔹 HYDRATE FIRST here too
    tpl = hydrate_files_from_stack_dir(tpl)

    # validate AFTER hydration
    validate_template(kind, tpl)

    return tpl


def role_from_topic(topic: str) -> str:
    t = (topic or "").lower()
    if "flask" in t: return "flask"
    if "fastapi" in t: return "fastapi"
    if "spring" in t: return "spring"
    if "express" in t: return "express"
    if "react" in t: return "react"
    if "vue" in t: return "vue"
    if "svelte" in t: return "svelte"
    return "generic"

# -------------------- Merge/resolve utils for test configs --------------------
_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

def deep_merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = deep_merge(out.get(k), v)
        return out
    return copy.deepcopy(b)

def merge_named_list(base_list, override_map=None, add_list=None):
    base_list = base_list or []
    idx = {item.get("name"): i for i, item in enumerate(base_list) if isinstance(item, dict) and "name" in item}
    out = [copy.deepcopy(x) for x in base_list]
    for name, patch in (override_map or {}).items():
        if name in idx:
            i = idx[name]
            out[i] = deep_merge(out[i], patch)
    for item in (add_list or []):
        out.append(copy.deepcopy(item))
    return [x for x in out if not x.get("disabled")]

def resolve_vars(obj, vars_map):
    if isinstance(obj, dict):
        return {k: resolve_vars(v, vars_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_vars(x, vars_map) for x in obj]
    if isinstance(obj, str):
        def repl(m):
            key = m.group(1)
            return str(vars_map.get(key, os.environ.get(key, m.group(0))))
        return _VAR_RE.sub(repl, obj)
    return obj

def _expand_project_paths(merged: dict, slug: str) -> dict:
    """Normalize cwd/junit_xml into content/code/{slug}/..."""
    def expand_cwd(cwd: str) -> str:
        cwd = (cwd or "").replace("\\", "/")
        while cwd.startswith("./"):
            cwd = cwd[2:]
        if cwd == "backend" or cwd.startswith("backend/"):
            return f"content/code/{slug}/{cwd}"
        if cwd == "frontend" or cwd.startswith("frontend/"):
            return f"content/code/{slug}/{cwd}"
        if not is_safe_relpath((cwd + ("/" if not cwd.endswith("/") else ""))):
            raise ValueError(f"Illegal test/service cwd: {cwd}")
        return f"content/code/{slug}/{cwd}"

    merged = copy.deepcopy(merged)
    for svc in merged.get("services", []):
        if "cwd" in svc:
            svc["cwd"] = expand_cwd(svc["cwd"])
    for t in merged.get("tests", []):
        if "cwd" in t:
            t["cwd"] = expand_cwd(t["cwd"])
        if t.get("type") == "junit" and t.get("junit_xml"):
            j = t["junit_xml"].replace("\\", "/")
            if not str(j).startswith("content/"):
                t["junit_xml"] = f"content/code/{slug}/{j}"
        if "install" in t and isinstance(t["install"], list):
            t["install"] = [list(map(str, cmd)) for cmd in t["install"]]
        if "cmd" in t:
            t["cmd"] = [str(x) for x in t["cmd"]]
    return merged

def load_and_compose_test_config(project_yaml_path: Path, slug: str) -> dict:
    """Read {slug}.test.yaml with 'extends' (list), 'vars', 'overrides'; merge + resolve ${VAR} + expand paths."""
    import yaml
    proj_cfg = yaml.safe_load(project_yaml_path.read_text(encoding="utf-8"))
    base_files = proj_cfg.get("extends", [])
    if isinstance(base_files, (str, Path)):
        base_files = [base_files]

    # 1) merge base stacks sequentially
    merged = {"version": 1, "project": proj_cfg.get("project", slug)}
    for bf in base_files:
        bf = Path(bf)
        base = yaml.safe_load(bf.read_text(encoding="utf-8"))
        merged = deep_merge(merged, base)

    # 2) combine vars (base.vars <- proj.vars)
    base_vars = merged.get("vars", {}) or {}
    proj_vars = proj_cfg.get("vars", {}) or {}
    vars_combined = {**base_vars, **proj_vars, "__PROJECT__": slug, "SLUG": slug}

    # 3) apply overrides by name
    ov = proj_cfg.get("overrides", {}) or {}
    merged = deep_merge(merged, {k: v for k, v in ov.items() if k not in ("services", "tests", "add_tests")})
    merged["services"] = merge_named_list(merged.get("services", []), ov.get("services"), None)
    merged["tests"]    = merge_named_list(merged.get("tests", []),    ov.get("tests"),    ov.get("add_tests"))

    # 4) resolve ${VAR}
    merged = resolve_vars(merged, vars_combined)

    # 5) normalize paths
    merged = _expand_project_paths(merged, slug)

    # 6) defaults for artifacts/report
    merged.setdefault("report", f"artifacts/{slug}/test_report.json")
    merged.setdefault("artifacts_dir", f"artifacts/{slug}")

    return merged

# -------------------- Compose BE+FE into project --------------------
def compose_stack(slug: str, title: str, be_tpl: dict, fe_tpl: dict) -> Tuple[Tuple[str, ...], str]:
    
    def write_files(tpl: dict, kind_hint: str):
        files = tpl.get("files", {}) or {}
        wrote = 0
        skipped = 0
        for rel, content in files.items():
            norm = _normalize_relpath(rel, kind_hint=kind_hint)
            if not norm or not is_safe_relpath(norm):
                skipped += 1
                continue
            write(proj / norm, content if isinstance(content, str) else str(content))
            wrote += 1
        print(f"[compose] wrote {wrote} file(s) from {kind_hint} template, skipped {skipped}.")
        
        
    """
    Create project content/code/{slug} by writing files from stacks and
    generating a {slug}.test.yaml that *extends* both stack configs.
    Merge is done later when running tests.
    """
    proj = CODE / slug
    ensure_dir(proj)
    

    # 1) Write files from backend and frontend templates, normalizing paths
    write_files(be_tpl, kind_hint="backend")
    write_files(fe_tpl, kind_hint="frontend")

    # 2) Create {slug}.test.yaml with extends
    be_entry = be_tpl.get("__path")
    fe_entry = fe_tpl.get("__path")
    if not be_entry or not fe_entry:
        raise RuntimeError("Stack template missing '__path' to stack.test.yaml")

    cfg_dict = {
        "project": slug,
        "extends": [be_entry, fe_entry],
        "vars": {
            "__PROJECT__": slug,
            "SLUG": slug,
            "BE_PORT": str(DEFAULT_BE_PORT),
            "BE_API_BASE": f"http://localhost:{DEFAULT_BE_PORT}",
            "FE_PORT": str(DEFAULT_FE_PORT),
            "FE_BASE_URL": f"http://localhost:{DEFAULT_FE_PORT}",
        },
        "overrides": {
            # Optional per-project overrides (cwd/junit_xml will be normalized later anyway)
        }
    }
    cfg_path = f"content/code/{slug}/{slug}.test.yaml"
    write(Path(cfg_path), dump_yaml(cfg_dict))

    # 3) Editable whitelist comes from each stack’s manifest (optional). If stacks provide it inline, combine here.
    editable = tuple(sorted(set(
        list(be_tpl.get("editable_files", [])) + list(fe_tpl.get("editable_files", []))
    )))
    return editable, cfg_path

# -------------------- Blog/script skeleton & snippets --------------------
def scaffold_snippets_generic(slug: str):
    snip_dir = BLOG / slug / "snippets"
    write(snip_dir / "backend_main.txt", "# snippet placeholder: backend main logic will be extracted later\n")
    write(snip_dir / "frontend_main.txt", "# snippet placeholder: frontend main logic will be extracted later\n")
    

def fill_snippets_from_code(slug: str):
    base = CODE / slug
    snip = BLOG / slug / "snippets"
    ensure_dir(snip)
    be = next((p for p in ["backend/app.py","backend/main.py"] if (base / p).exists()), None)
    fe = next((p for p in ["frontend/app.js","frontend/index.html","frontend/src/main.jsx"] if (base / p).exists()), None)
    if be:
        write(snip / "backend_main.txt", read(base / be))
    if fe:
        write(snip / "frontend_main.txt", read(base / fe))


def scaffold_blog_and_script(topic: str, slug: str):
    blog_dir = BLOG / slug
    video_dir = VIDEO / slug
    ensure_dir(blog_dir); ensure_dir(video_dir)

    meta = {
        "title_en": topic,
        "title_vi": f"Cách xây {topic}",
        "tags": ["vuicode", "tutorial", "simple-code", "clear-results"],
        "created": now_iso(),
    }
    write(blog_dir / "meta.yaml", dump_yaml(meta))

    post_en = f"""# Clear Result (Demo first)
A minimal demo using an API + a simple frontend.

- Backend serves /api/ping, /api/echo, /api/chat
- Frontend calls window.API_BASE (set by the generator)
- Typical dev ports: backend :5000, frontend :5173

## Backend (main snippet)
{{{{snippet:backend_main.txt}}}} 

## Frontend (main snippet)
{{{{snippet:frontend_main.txt}}}}

## How to run
```bash
cd content/code/{slug}
# see project README or stack README
"""
    write(blog_dir / "post.en.md", post_en)

    post_vi = f"""# Kết quả rõ ràng (xem demo trước)
Demo tối giản: API + frontend.

Backend: /api/ping, /api/echo, /api/chat
Frontend gọi window.API_BASE (được cấu hình sẵn)
Cổng thường dùng: backend :5000, frontend :5173

Backend (snippet chính)
{{{{snippet:backend_main.txt}}}}

Frontend (snippet chính)
{{{{snippet:frontend_main.txt}}}}

Cách chạy
cd content/code/{slug}
# tham khảo README của dự án/stack để chạy backend & frontend
"""
    write(blog_dir / "post.vi.md", post_vi)

    script_md = f"""# Video Script — {topic}
Intro (5s)

Title

Clear Result demo

Simple code

Architecture

Backend details

Frontend details

Run fullstack

Outro (5s)
"""
    write(video_dir / "script.md", script_md)

# -------------------- LLM customize-in-place --------------------
def llm_customize_in_place(slug: str, topic: str, allowed_rel: Tuple[str, ...]) -> bool:
    base_dir = CODE / slug
    ctx = {}
    for rel in allowed_rel:
        p = base_dir / rel
        if p.exists():
            try:
                ctx[rel] = read(p)
            except Exception:
                pass

    system = (
        "You are a careful software engineer. Output ONLY a strict JSON object mapping relative file paths "
        "to FULL updated contents. Modify ONLY allowed files. Keep structure/ports/commands intact."
    )
    allowed_list = "\n".join(f"- {r}" for r in allowed_rel)
    prompt = f"""
Topic: {topic}

Project root: content/code/{slug}
Allowed files (relative) you MAY modify:
{allowed_list}

Current contents (JSON):
{json.dumps(ctx)[:45000]}

Requirements:

Implement the topic idea with minimal, focused changes.

Preserve ports and start commands already defined by stacks.

Return ONLY JSON mapping relative paths to full file contents.
"""
    raw = gen_openai(system, prompt)
    try:
        start = raw.find("{"); end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            print("LLM customize output not JSON-like. Head:\n", raw[:300])
            return False
        data = json.loads(raw[start:end+1])
    except Exception as e:
        print("Failed to parse LLM customize JSON:", e, "\nRaw head:\n", raw[:300]); return False

    changed = 0
    for rel, content in data.items():
        if rel not in allowed_rel:
            print(f"Skip non-allowed file from LLM: {rel}")
            continue
        write(base_dir / rel, content); changed += 1

    print(f"LLM customize applied to {changed} file(s).")
    return changed > 0

# -------------------- Runner & repair loop --------------------
def run_tests_with_config(slug: str) -> tuple[bool, dict]:
    # 1) compose merged config
    proj_cfg_path = CODE / slug / f"{slug}.test.yaml"
    merged = load_and_compose_test_config(proj_cfg_path, slug)

    # 2) write merged.test.yaml
    merged_path = CODE / slug / "merged.test.yaml"
    write(merged_path, dump_yaml(merged))
    print(f"wrote merged config → {merged_path}")

    # 3) run runner
    cmd = [sys.executable, str(TOOLS / "run_all_tests.py"), "--config", str(merged_path)]
    print("Running tests:", " ".join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True)

    # 4) read report from file
    report_path = Path(merged["report"])
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as e:
            data = {"error": f"cannot read report: {e}", "stderr": (proc.stderr or "")[:1200]}
    else:
        # fallback: parse stdout if runner printed JSON (not typical)
        try:
            data = json.loads(proc.stdout or "{}")
        except Exception as e:
            data = {"error": f"no report file & stdout parse failed: {e}", "stderr": (proc.stderr or "")[:1200]}

    ok = bool(data.get("overall_passed"))
    return ok, data

def infer_failure_target(report: dict) -> str:
    targets = set()
    for r in report.get("results", []):
        t = (r.get("type") or r.get("tool") or "").lower()
        rc = r.get("returncode", 1)
        nm = (r.get("name","").lower())
        if rc != 0:
            if "junit" in t or "pytest" in t or "backend" in nm:
                targets.add("backend")
            if "playwright" in t or "ui" in nm or "frontend" in nm:
                targets.add("frontend")
    if not targets: return "both"
    if len(targets) == 1: return list(targets)[0]
    return "both"

def brief_fail(report: dict) -> str:
    parts = [f"overall_passed={report.get('overall_passed')}"]
    for r in report.get("results", []):
        parts.append(f"- {r.get('name')} type={r.get('type')} rc={r.get('returncode')} summary={r.get('summary')} err={r.get('error')}")
    return "\n".join(parts)

def llm_repair_once(slug: str, topic: str, allowed_rel: Tuple[str, ...], target: str) -> bool:
    base_dir = CODE / slug
    if target == "backend":
        subset = tuple([r for r in allowed_rel if r.startswith("backend/")])
    elif target == "frontend":
        subset = tuple([r for r in allowed_rel if r.startswith("frontend/")])
    else:
        subset = allowed_rel
    ctx = {}
    for rel in subset:
        p = base_dir / rel
        if p.exists():
            try:
                ctx[rel] = read(p)
            except Exception:
                pass
    system = (
        "You are a fixer bot. Output ONLY a strict JSON object mapping relative file paths to FULL corrected contents. "
        "Modify ONLY files listed. Keep structure/ports/commands the same. Aim to make tests pass."
    )
    prompt = f"""
Topic: {topic}
Project: content/code/{slug}

Allowed files to modify (relative):
{json.dumps(list(subset))}

Current contents (JSON):
{json.dumps(ctx)[:45000]}

Fix minimal issues likely causing tests to fail. Return JSON only.
"""
    raw = gen_openai(system, prompt)
    try:
        start = raw.find("{"); end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            print("LLM repair output not JSON-like. Head:\n", raw[:300]); return False
        data = json.loads(raw[start:end+1])
    except Exception as e:
        print("Failed to parse LLM repair JSON:", e, "\nRaw head:\n", raw[:300]); return False

    changed = 0
    for rel, content in data.items():
        if rel not in subset:
            print(f"Skip non-allowed file from LLM repair: {rel}"); continue
        write(base_dir / rel, content); changed += 1
    print(f"LLM repair applied to {changed} file(s) on target={target}.")
    return changed > 0

def repair_loop_if_needed(slug: str, topic: str, allowed_rel: Tuple[str, ...]) -> bool:
    ok, report = run_tests_with_config(slug)
    if ok:
        print("Tests passed on first run."); return True
    tries = 0
    while not ok and tries < MAX_REPAIR_TRIES:
        tries += 1
        target = infer_failure_target(report)
        print(f"Tests failed → repair attempt #{tries} (target={target})")
        changed = llm_repair_once(slug, topic, allowed_rel, target)
        if not changed:
            print("No changes produced by repair.")
            break
        ok, report = run_tests_with_config(slug)
    if ok:
        print(f"Tests passed after {tries} repair attempt(s).")
    else:
        print("Tests still failing.\n" + brief_fail(report))
    return ok

# -------------------- Content generation (blog/script) --------------------
def generate_content(topic: str, slug: str):
    blog_dir = BLOG / slug
    video_dir = VIDEO / slug
    ensure_dir(blog_dir); ensure_dir(video_dir)

    md_en = gen_openai(
        "You are VuiCode Writer. Write a clear, beginner-friendly tech blog with headings, code blocks, and a 'Clear Result' section first. Keep tech terms in English.",
        f"Write a markdown blog post (800-1200 words) about {topic}. Keep {{snippet:...}} placeholders intact. Do not translate technical terms."
    )
    md_vi = gen_openai(
        "Bạn là VuiCode Writer. Viết blog tiếng Việt dễ hiểu, có tiêu đề phụ, code block, phần 'Kết quả rõ ràng' ở đầu. Giữ nguyên thuật ngữ kỹ thuật bằng tiếng Anh.",
        f"Viết bài blog markdown (800–1200 chữ) về {topic}. GIỮ nguyên placeholder {{snippet:...}}."
    )
    write(blog_dir / "post.en.md", md_en)
    write(blog_dir / "post.vi.md", md_vi)

    script = gen_openai(
        "You are VuiCode Video Scriptwriter. Create a 5-min script aligned to VuiCode structure. Keep snippet placeholders intact.",
        f"Create a YouTube script for {topic} following: 1 intro(5s), 2 title, 3 clear result demo, 4 simple code, 5 architecture, 6 backend details, 7 frontend details, 8 run fullstack, 9 outro(5s). Include {{snippet:...}} where appropriate."
    )
    write(video_dir / "script.md", script)
    print(f"Generated content: {blog_dir/'post.en.md'}, {blog_dir/'post.vi.md'}, {video_dir/'script.md'}")

# -------------------- Verify & copy UI --------------------
def run_verify_and_maybe_copy(ui_path: Path, slug: str) -> bool:
    ok, _ = run_tests_with_config(slug)
    if not ok:
        print("Tests failed — not copying demo UI."); return False
    src_frontend = CODE / slug / "frontend"
    ensure_dir(ui_path)
    if ui_path.exists():
        # clean folder
        for entry in ui_path.iterdir():
            if entry.is_file(): entry.unlink()
            else: shutil.rmtree(entry)
    shutil.copytree(src_frontend, ui_path, dirs_exist_ok=True)
    print(f"Copied demo UI to {ui_path}")
    return True

# -------------------- Router (name or detect or autogen) --------------------
def route_template(kind: str, topic: str, name: Optional[str]) -> dict:
    return load_or_autogen_template(kind, topic, name)

# -------------------- CLI --------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["scaffold", "content", "verify", "all"])
    ap.add_argument("--topic", help="Topic title, e.g., 'Build AI Chatbot with Flask & React'")
    ap.add_argument("--slug", help="Explicit slug, e.g., 'chatbot-flask-plus-react'")
    ap.add_argument("--backend-template", help="Backend stack folder name (optional)")
    ap.add_argument("--frontend-template", help="Frontend stack folder name (optional)")
    ap.add_argument("--ui-path", default="frontend", help="Destination path to copy verified FE")
    ap.add_argument("--dry-run", action="store_true", help="Only scaffold + run tests, skip LLM customization and repair loop")
    ap.add_argument("--skip-repair", action="store_true", help="Skip repair loop on test failures")
    args = ap.parse_args()

    # directories
    for d in (CONTENT, BLOG, VIDEO, CODE, TOOLS, TEMPLATES_DIR_BE, TEMPLATES_DIR_FE, ARTIFACTS):
        ensure_dir(d)

    # derive slug
    if args.slug:
        slug = args.slug
    elif args.topic:
        slug = slugify(args.topic)
    else:
        if args.mode in ("scaffold", "content", "all"):
            ap.error("--topic or --slug is required for this mode"); return
        slug = "project"

    # Resolve stacks (by name or detect; auto-template if missing)
    if args.mode in ("scaffold", "all", "content", "verify"):
        topic_for_detection = args.topic or slug
        be_tpl = route_template("backend", topic_for_detection, args.backend_template)
        fe_tpl = route_template("frontend", topic_for_detection, args.frontend_template)

    # ---- Modes ----
    if args.mode in ("scaffold", "all"):
        title = args.topic or slug
        editable, _cfg = compose_stack(slug, title, be_tpl, fe_tpl)
        scaffold_snippets_generic(slug)
        fill_snippets_from_code(slug)

        # Run initial tests after scaffold
        print("Running initial tests after scaffold…")
        tests_ok, _ = run_tests_with_config(slug)
        if tests_ok:
            print("Initial tests passed.")
        else:
            print("Initial tests failed.")

        # --dry-run: stop here (no LLM customize/repair)
        if args.dry_run:
            print("[INFO] Dry-run: Skipping LLM customization & repair loop.")
            if args.mode != "all":
                print("Done.")
                return

        # If failed and not --skip-repair, try repair loop
        if not tests_ok and not args.skip_repair:
            print("[INFO] Entering repair loop…")
            repair_loop_if_needed(slug, title, editable)

        # If passed or after repair, optionally customize
        if args.mode == "all":
            llm_customize_in_place(slug, title, editable)
            tests_ok2, _ = run_tests_with_config(slug)
            if not tests_ok2 and not args.skip_repair:
                print("[INFO] Post-customize tests failed; entering repair loop…")
                repair_loop_if_needed(slug, title, editable)

    if args.mode == "content":
        topic = args.topic or slug
        generate_content(topic, slug)

    if args.mode == "verify":
        ui_dest = Path(args.ui_path)
        ok = run_verify_and_maybe_copy(ui_dest, slug)
        if not ok: sys.exit(1)

    if args.mode == "all":
        topic = args.topic or slug
        generate_content(topic, slug)
        ui_dest = Path(args.ui_path)
        run_verify_and_maybe_copy(ui_dest, slug)

    print(" Done.")
    
if __name__ == "__main__":
    main()