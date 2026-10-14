from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template

from testfails.arena import load_arena
from testfails.benchmarks import suite_manifest
from testfails.runner import load_latest


ROOT = Path(__file__).resolve().parent
app = Flask(__name__)
app.config.update(JSON_SORT_KEYS=False, MAX_CONTENT_LENGTH=64 * 1024)


def state():
    arena = load_arena(ROOT / "data" / "arena_latest.json")
    run = load_latest(ROOT / "data" / "runs")
    return arena, run


@app.after_request
def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get("/")
def index():
    arena, run = state()
    return render_template("index.html", arena=arena, run=run, suite=suite_manifest())


@app.get("/method")
def method():
    return render_template("method.html", suite=suite_manifest())


@app.get("/robot-arena")
def robot_arena():
    return render_template("robot_arena.html")


@app.get("/api/status")
def api_status():
    arena, run = state()
    return jsonify({"service": "testFAILS3", "autonomous": True, "suite": suite_manifest(), "arena": {"retrievedAt": arena.get("retrievedAt"), "source": arena.get("source"), "boards": sorted(arena.get("boards", {})), "errors": arena.get("errors", [])}, "latestRun": run})


@app.get("/api/arena")
def api_arena():
    arena, _ = state()
    return jsonify(arena)


@app.get("/api/runs/latest")
def api_latest_run():
    run = load_latest(ROOT / "data" / "runs")
    return (jsonify(run), 200) if run else (jsonify({"error": "No provider evaluation has completed yet."}), 404)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8063")), debug=False)
