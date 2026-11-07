from pathlib import Path
from playwright.sync_api import sync_playwright
import subprocess, sys, os, time, urllib.request, tempfile, json

ROOT = Path(__file__).resolve().parents[1]
(ROOT / "docs/screenshots").mkdir(exist_ok=True)
sandbox = tempfile.TemporaryDirectory(prefix=".browser_", dir=ROOT / "tests")
env = {**os.environ, "LINEGUARD_DB": str(Path(sandbox.name) / "feedback.sqlite3")}
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
    cwd=ROOT,
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    for _ in range(100):
        try:
            urllib.request.urlopen("http://127.0.0.1:8001/api/health", timeout=0.2)
            break
        except OSError:
            time.sleep(0.1)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8001")
        page.wait_for_function("document.querySelector('#current-score').textContent !== '—'")
        page.locator("[data-view=monitor]").click()
        page.locator("[data-view=fleet]").click()
        page.wait_for_function(
            "document.querySelector('#fleet-engine').textContent.includes('cycles remaining')"
        )
        page.screenshot(path=str(ROOT / "docs/screenshots/fleet.png"), full_page=True)
        page.locator("#guide-engine").click()
        page.locator("#forecast .inspection-action").click()
        page.locator("#task-notes").fill("<script>literal notes</script>")
        page.locator("#task-form button[type=submit]").click()
        page.locator("#task-list [data-ack]").click()
        page.locator("#task-list input[name=outcome]").fill("Inspection complete")
        page.locator('#task-list button:has-text("Complete inspection")').click()
        page.locator('#task-list h3:has-text("completed")').wait_for()
        href = page.locator("#task-list a[download]").get_attribute("href")
        assert (
            "&lt;script&gt;literal notes&lt;/script&gt;"
            in page.request.get("http://127.0.0.1:8001" + href).text()
        )
        page.reload()
        page.locator('#task-list h3:has-text("completed")').wait_for()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1600, "height": 1100})
        page.locator("[data-view=monitor]").click()
        page.screenshot(path=str(ROOT / "docs/screenshots/command-center.png"), full_page=True)
        data = json.load(urllib.request.urlopen("http://127.0.0.1:8001/api/scenario/recorded"))
        chosen = max((p for p in data["points"] if p["label"] == 1), key=lambda p: p["ratio"])[
            "index"
        ]
        page.locator("#scrubber").fill(str(chosen))
        page.locator("#scrubber").dispatch_event("input")
        page.locator("#monitor h1").click()
        page.screenshot(path=str(ROOT / "docs/screenshots/anomaly-evidence.png"), full_page=True)
        page.locator("[data-view=evidence]").click()
        page.screenshot(path=str(ROOT / "docs/screenshots/model-evidence.png"), full_page=True)
        page.locator("[data-view=forecast]").click()
        page.wait_for_function("document.querySelector('#engine-rul').textContent !== '—'")
        page.locator("#engine-select").select_option("24")
        page.wait_for_function(
            "document.querySelector('#engine-title').textContent.includes('024')"
        )
        page.locator("#rul-horizon").fill("30")
        page.locator("#rul-horizon").dispatch_event("input")
        page.locator("#forecast h1").click()
        assert "30 cycles" in page.locator("#horizon-label").inner_text()
        page.screenshot(path=str(ROOT / "docs/screenshots/forecast-lab.png"), full_page=True)
        for width in [1440, 1024, 768, 390]:
            page.set_viewport_size({"width": width, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "forecast",
                width,
            )
        page.screenshot(path=str(ROOT / "docs/screenshots/forecast-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1600, "height": 1100})
        payload = urllib.request.urlopen("http://127.0.0.1:8001/api/prognostics/sample").read()
        page.locator("#engine-file").set_input_files(
            {"name": "engine.csv", "mimeType": "text/csv", "buffer": payload}
        )
        page.wait_for_function(
            "document.querySelector('#engine-truth').textContent.includes('Unavailable')"
        )
        assert "No ground-truth" in page.locator("#toast").inner_text()

        page.locator("[data-view=monitor]").click()
        page.locator("#scenario-select").select_option("flatline")
        page.wait_for_function(
            "document.querySelector('#source-tag').textContent === 'SIMULATED INJECTION'"
        )
        flatline_index = page.evaluate(
            "state.trace.points.find(p=>p.index>=160 && p.sensor_flags.flatline.length).index"
        )
        page.locator("#scrubber").fill(str(flatline_index))
        page.locator("#scrubber").dispatch_event("input")
        assert "sensor integrity" in page.locator("#decision-brief").inner_text().lower()
        page.locator("#play-btn").click()
        page.wait_for_timeout(400)
        assert page.locator("#play-btn").inner_text().startswith("Ⅱ")
        page.locator("#play-btn").click()
        page.locator("#feedback-btn").click()
        assert page.locator("#feedback-dialog").is_visible()
        page.locator("#feedback-note").fill(
            "Automated browser verification — injected current flatline."
        )
        page.locator("#feedback-verdict").select_option("Sensor issue")
        page.locator("#feedback-form [type=submit]").click()
        page.wait_for_function("document.querySelector('#feedback-count').textContent !== '0'")
        page.locator("[data-view=feedback]").click()
        assert "Automated browser verification" in page.locator("#feedback-list").inner_text()
        page.locator("[data-view=monitor]").click()
        page.locator("#csv-file").set_input_files(str(ROOT / "data/sample_stream.csv"))
        page.wait_for_function(
            "document.querySelector('#source-tag').textContent === 'UPLOADED DATA'"
        )
        assert page.locator("#scrubber").get_attribute("max") == "119"
        assert page.locator("#scenario-select").input_value() == "uploaded"
        page.evaluate("document.querySelector('#toast').className=''")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for width in [1440, 1024, 768, 390]:
            page.set_viewport_size({"width": width, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.screenshot(path=str(ROOT / "docs/screenshots/mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1600, "height": 1100})
        page.locator("[data-view=forecast]").click()
        page.locator("#engine-select").select_option("24")
        page.wait_for_function(
            "document.querySelector('#engine-title').textContent.includes('024')"
        )
        page.locator("#engine-restart").click()
        assert page.locator("#engine-age").inner_text() == "1 cycles"
        assert "Hidden" in page.locator("#engine-truth").inner_text()
        page.locator("#forecast .truth-toggle").check()
        assert "Hidden" not in page.locator("#engine-truth").inner_text()
        page.locator("#engine-scrubber").fill("10")
        page.locator("#engine-scrubber").dispatch_event("input")
        page.locator("#forecast .inspection-action").click()
        assert "undefined" not in page.locator("#task-assessment").inner_text()
        page.locator("#task-form button[type=submit]").click()
        page.locator('#task-list h3:has-text("open")').wait_for()
        assert "Observed cycle 11" in page.locator("#task-list").inner_text()
        page.locator("#task-list form[data-cancel] input").fill("Replay test finished")
        page.locator("#task-list form[data-cancel] button").click()
        page.locator('#task-list h3:has-text("cancelled")').wait_for()
        page.locator("#task-filter").select_option("cancelled")
        assert page.locator("#task-list .task-row").count() == 1
        page.locator("#task-filter").select_option("")
        old_payload = page.request.get("http://127.0.0.1:8001/api/prognostics/engine/11").text()
        held = []
        page.route("**/api/prognostics/engine/11", lambda route: held.append(route))
        page.evaluate("void selectEngine(11);void selectEngine(12);")
        page.wait_for_function("state.engine.engine_id===12 && !state.engineLoading")
        assert held
        held[0].fulfill(status=200, content_type="application/json", body=old_payload)
        page.wait_for_timeout(150)
        assert page.evaluate("state.engine.engine_id") == 12
        page.unroute("**/api/prognostics/engine/11")
        page.route(
            "**/api/prognostics/engine/13",
            lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"detail":"Test failure"}'
            ),
        )
        page.evaluate("void selectEngine(13)")
        page.wait_for_function("!!state.engineError")
        assert "Reload" in page.locator("#engine-decision").inner_text()
        assert page.locator("#forecast .inspection-action").is_disabled()
        page.unroute("**/api/prognostics/engine/13")
        page.evaluate("void selectEngine(24)")
        page.wait_for_function("state.engine.engine_id===24 && !state.engineLoading")
        import io, pandas as pd

        unfamiliar = pd.read_csv(io.BytesIO(payload))
        unfamiliar["sensor_2"] = 9000
        page.locator("#engine-file").set_input_files(
            {
                "name": "unfamiliar.csv",
                "mimeType": "text/csv",
                "buffer": unfamiliar.to_csv(index=False).encode(),
            }
        )
        page.wait_for_function("state.engine?.domain_warnings?.length > 0 && !state.engineLoading")
        assert "Verify" in page.locator("#engine-decision").inner_text()
        page.locator("[data-view=fleet]").click()
        assert "Verify" in page.locator("#fleet-engine").inner_text()
        assert not errors, errors
        print(
            "Browser verified: replay, scenario, feedback persistence, CSV upload, desktop/mobile overflow, no JS errors."
        )
        browser.close()
finally:
    server.terminate()
    server.wait(timeout=10)
    sandbox.cleanup()
