import app as application


def test_dashboard_and_apis_render_without_provider_run(monkeypatch, tmp_path):
    arena = {"retrievedAt": "2026-10-13T00:00:00Z", "source": "https://example.test", "boards": {"text": {"publishDate": "2026-10-12", "config": "text_style_control", "rows": [{"rank": 1, "model_name": "model-a", "organization": "org", "rating": 1500.0}]}}, "errors": []}
    monkeypatch.setattr(application, "state", lambda: (arena, None))
    monkeypatch.setattr(application, "load_latest", lambda path: None)
    client = application.app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b"No provider evaluation has been fabricated" in page.data
    assert b"Arena leaderboards" in page.data
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/runs/latest").status_code == 404
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]


def test_robot_arena_is_real_self_contained_simulation():
    client = application.app.test_client()
    page = client.get("/robot-arena")
    assert page.status_code == 200
    assert b"Evolutionary robot laboratory" in page.data
    assert b"robot-arena.js" in page.data
    assert client.get("/static/vendor/three/three.module.min.js").status_code == 200


def test_dashboard_never_mixes_a_historical_run_with_the_current_suite(monkeypatch):
    arena = {"retrievedAt": "2026-10-13T00:00:00Z", "source": "https://example.test", "boards": {}, "errors": []}
    old_run = {"runId": "old", "suite": {"sha256": "0" * 64}, "models": [{"model": "old-model", "results": []}]}
    monkeypatch.setattr(application, "state", lambda: (arena, old_run))
    client = application.app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b"stored run belongs to an earlier suite" in page.data
    assert b"old-model" not in page.data
