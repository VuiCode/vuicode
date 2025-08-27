#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

# Optional YAML (preferred); else allow JSON-only configs
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

# ----------------------
# Helpers
# ----------------------

def load_config(path: str) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml") and yaml is not None:
        return yaml.safe_load(text)
    return json.loads(text)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def to_cmd_list(x):
    if not isinstance(x, list) or not all(isinstance(i, str) for i in x):
        raise ValueError("Command must be a list[str].")
    return x

def merge_env(base: dict, extra: dict | None):
    env = os.environ.copy()
    env.update(base or {})
    if extra:
        env.update(extra)
    return env

def write_text(path: Path, s: str):
    ensure_dir(path.parent)
    path.write_text(s, encoding="utf-8")

def tail(s: str, n: int = 1200) -> str:
    return s[-n:] if len(s) > n else s

# ----------------------
# Logging pipes to file
# ----------------------

class PipeLogger(threading.Thread):
    def __init__(self, stream, out_file: Path):
        super().__init__(daemon=True)
        self.stream = stream
        self.out_file = out_file
        ensure_dir(out_file.parent)
        self._stop = False

    def run(self):
        with self.out_file.open("ab") as f:
            try:
                for line in iter(self.stream.readline, b''):
                    if self._stop:
                        break
                    if not line:
                        break
                    f.write(line)
                    f.flush()
            except Exception:
                pass

    def stop(self):
        self._stop = True

# ----------------------
# Healthcheck
# ----------------------

def wait_http(url: str, expect: str | None, timeout_sec: int, log_file: Path, human: bool):
    import urllib.request
    import urllib.error

    start = time.time()
    tries = 0
    while time.time() - start < timeout_sec:
        tries += 1
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                body = r.read().decode("utf-8", errors="ignore")
                if (expect is None) or (expect in body):
                    write_text(log_file, f"[healthcheck] OK after {tries} tries\n")
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            write_text(log_file, f"[healthcheck] try#{tries} -> {e}\n")
        time.sleep(0.4)
    if human:
        print(f"[HC FAIL] {url} not healthy in {timeout_sec}s (expect={expect})", file=sys.stderr)
    write_text(log_file, f"[healthcheck] FAIL after {tries} tries\n")
    return False

# ----------------------
# Services
# ----------------------

def start_services(cfg: dict, artifacts_dir: Path, base_env: dict, human: bool, max_wait_override: int | None):
    services_cfg = cfg.get("services", [])
    procs = []
    svc_meta = []
    for svc in services_cfg:
        name = svc.get("name")
        cwd = svc.get("cwd")
        cmd = to_cmd_list(svc.get("start", []))
        hc = svc.get("healthcheck", {}) or {}
        url = hc.get("url")
        expect = hc.get("expect")
        timeout_sec = int(hc.get("timeout_sec", 20))
        if max_wait_override and max_wait_override > 0:
            timeout_sec = max(timeout_sec, max_wait_override)

        log_path = artifacts_dir / "logs" / f"service_{name}.log"
        if human:
            print(f"[SERVICE] starting {name}: {cmd} (cwd={cwd})", file=sys.stderr)

        t0 = time.time()
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=merge_env(base_env, None),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False
        )
        procs.append((name, proc))
        # Attach pipe loggers
        out_log = PipeLogger(proc.stdout, log_path.with_suffix(".out.log"))
        err_log = PipeLogger(proc.stderr, log_path.with_suffix(".err.log"))
        out_log.start(); err_log.start()

        healthy = False
        if url:
            healthy = wait_http(url, expect, timeout_sec, log_path, human)
        else:
            # No healthcheck -> assume OK after short grace
            time.sleep(1.0)
            healthy = True

        svc_meta.append({
            "name": name,
            "healthy": bool(healthy),
            "duration_sec": round(time.time() - t0, 2)
        })
        if not healthy:
            if human:
                print(f"[SERVICE] {name} unhealthy → stopping all", file=sys.stderr)
            stop_services(procs)
            return svc_meta, procs, False
    return svc_meta, procs, True

def stop_services(procs):
    for name, p in reversed(procs):
        try:
            p.terminate()
        except Exception:
            pass
    # small wait then kill if needed
    time.sleep(0.7)
    for name, p in reversed(procs):
        if p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

# ----------------------
# Test adapters
# ----------------------

def parse_junit(xml_path: Path, returncode: int):
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        suites = [root] if root.tag == "testsuite" else list(root)
        passed = failed = errors = skipped = 0
        duration = 0.0
        for s in suites:
            tests = int(s.attrib.get("tests", "0") or 0)
            failures = int(s.attrib.get("failures", "0") or 0)
            errs = int(s.attrib.get("errors", "0") or 0)
            sk = int(s.attrib.get("skipped", "0") or 0)
            time_s = float(s.attrib.get("time", "0") or 0)
            passed += max(tests - failures - errs - sk, 0)
            failed += failures
            errors += errs
            skipped += sk
            duration += time_s
        return {
            "type": "junit",
            "returncode": returncode,
            "summary": {
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
                "duration_sec": round(duration, 3)
            }
        }
    except Exception as e:
        return {"type": "junit", "returncode": returncode, "error": f"parse-error: {e}"}

def parse_playwright(stdout: str, returncode: int):
    try:
        data = json.loads(stdout)
        stats = data.get("stats", {})
        return {
            "type": "playwright",
            "returncode": returncode,
            "summary": {
                "passed": int(stats.get("expected", 0) or 0),
                "failed": int(stats.get("unexpected", 0) or 0),
                "skipped": int(stats.get("skipped", 0) or 0),
                "duration_sec": round((stats.get("duration", 0) or 0)/1000.0, 3)
            }
        }
    except Exception as e:
        return {"type": "playwright", "returncode": returncode, "error": f"parse-error: {e}"}

def parse_raw(stdout: str, stderr: str, returncode: int):
    return {
        "type": "raw",
        "returncode": returncode,
        "summary": {
            "stdout_tail": tail(stdout, 800),
            "stderr_tail": tail(stderr, 800),
        }
    }

# ----------------------
# Run a single test
# ----------------------

def run_one_test(tcfg: dict, artifacts_dir: Path, base_env: dict, human: bool):
    name = tcfg.get("name")
    ttype = (tcfg.get("type") or "raw").lower()
    cwd = tcfg.get("cwd")
    cmd = to_cmd_list(tcfg.get("cmd", []))
    install = tcfg.get("install", [])
    timeout_sec = int(tcfg.get("timeout_sec", 0) or 0)
    retries = int(tcfg.get("retries", 0) or 0)

    # Install phase (optional)
    if install:
        install_log = artifacts_dir / "logs" / f"test_{name}_install.log"
        for icmd in install:
            icmd = to_cmd_list(icmd)
            if human:
                print(f"[TEST] install {name}: {icmd}", file=sys.stderr)
            pr = subprocess.run(
                icmd, cwd=cwd, env=merge_env(base_env, None),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False
            )
            write_text(install_log, pr.stdout + "\n---\n" + pr.stderr)
            if pr.returncode != 0:
                return {
                    "name": name, "type": ttype, "returncode": pr.returncode,
                    "error": "install-failed", "summary": {"install_cmd": icmd}
                }

    # Actual test execution with retries
    attempt = 0
    last_result = None
    while True:
        attempt += 1
        if human:
            print(f"[TEST] run {name} (attempt {attempt})", file=sys.stderr)
        t0 = time.time()
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=merge_env(base_env, None),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_sec if timeout_sec > 0 else None)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                rc = 124  # timeout code
            else:
                rc = proc.returncode
        except FileNotFoundError as e:
            stdout, stderr, rc = "", str(e), 127
        except Exception as e:
            stdout, stderr, rc = "", str(e), 1

        # Save logs
        tlog = artifacts_dir / "logs" / f"test_{name}.log"
        write_text(tlog, stdout + "\n--- STDERR ---\n" + stderr)

        # Parse by adapter
        if ttype == "junit":
            junit_xml = tcfg.get("junit_xml")
            if junit_xml:
                result = parse_junit(Path(junit_xml), rc)
            else:
                result = parse_raw(stdout, stderr, rc)
        elif ttype == "playwright":
            result = parse_playwright(stdout, rc)
        else:
            result = parse_raw(stdout, stderr, rc)

        # Attach meta
        result["name"] = name
        result.setdefault("summary", {})
        result["summary"]["duration_sec"] = result["summary"].get("duration_sec", round(time.time()-t0, 3))

        last_result = result

        if rc == 0:
            return result
        if attempt > retries:
            return result
        if human:
            print(f"[TEST] {name} failed (rc={rc}), retrying ({attempt-1}/{retries})", file=sys.stderr)
        time.sleep(0.6)

# ----------------------
# Main
# ----------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to {slug}.test.yaml or .json")
    ap.add_argument("--artifacts", help="Override artifacts_dir")
    ap.add_argument("--human", action="store_true", help="Print human-friendly summary to stderr")
    ap.add_argument("--max-service-wait", type=int, default=0, help="Override min healthcheck wait (sec)")
    ap.add_argument("--env", nargs="*", default=[], help="Extra KEY=VALUE pairs")
    args = ap.parse_args()

    cfg = load_config(args.config)
    project = cfg.get("project") or "project"
    artifacts_dir = Path(args.artifacts or cfg.get("artifacts_dir") or f"artifacts/{project}")
    ensure_dir(artifacts_dir / "logs")

    # Merge env
    cfg_env = cfg.get("env", {}) or {}
    extra_env = {}
    for kv in args.env:
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra_env[k] = v
    base_env = merge_env(cfg_env, extra_env)

    # Start services
    services_meta, procs, ok_services = start_services(
        cfg, artifacts_dir, base_env, args.human, args.max_service_wait
    )

    results = []
    overall_passed = False

    try:
        if ok_services:
            # Run tests (sequential)
            tests_cfg = cfg.get("tests", []) or []
            all_ok = True
            for tcfg in tests_cfg:
                res = run_one_test(tcfg, artifacts_dir, base_env, args.human)
                results.append(res)
                if res.get("returncode", 1) != 0:
                    all_ok = False
            overall_passed = all_ok
        else:
            # Services unhealthy → mark overall failed
            overall_passed = False
    finally:
        stop_services(procs)

    report = {
        "timestamp": now_iso(),
        "project": project,
        "overall_passed": bool(overall_passed),
        "services": services_meta,
        "results": results
    }

    # Write to configured report path if present
    report_path = cfg.get("report")
    if report_path:
        try:
            write_text(Path(report_path), json.dumps(report, indent=2, ensure_ascii=False))
        except Exception:
            pass

    # Print JSON to stdout (for generator to parse)
    sys.stdout.write(json.dumps(report, ensure_ascii=False))
    sys.stdout.flush()

    # Optional human summary
    if args.human:
        ok_txt = "PASS" if overall_passed else "FAIL"
        print(f"[SUMMARY] project={project} result={ok_txt}", file=sys.stderr)
        for r in results:
            name = r.get("name")
            rc = r.get("returncode")
            typ = r.get("type")
            print(f"  - {name}: type={typ} rc={rc}", file=sys.stderr)

    # Exit with correct code
    sys.exit(0 if overall_passed else 1)

if __name__ == "__main__":
    main()
