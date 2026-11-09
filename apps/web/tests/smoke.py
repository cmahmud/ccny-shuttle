"""Offline, no-dependency smoke checks for the alpha site."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
REQUIRED_IDS = ["main", "top-status", "source-banner", "destination-select", "map", "stops", "refreshed-label", "banner-title", "banner-detail"]


class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.append(d["id"])
        if tag == "script" and "src" in d:
            self.links.append(d["src"])


class WebSmokeTests(unittest.TestCase):
    def test_html_ids_and_script(self):
        parser = IDs()
        parser.feed((WEB / "index.html").read_text())
        for identifier in REQUIRED_IDS:
            self.assertIn(identifier, parser.ids)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertIn("/app.js", parser.links)

    def test_local_assets_exist(self):
        for asset in ["index.html", "app.js", "alpha-v2.css", "favicon.svg", "icon.svg", "service-worker.js", "manifest.webmanifest"]:
            with self.subTest(asset=asset):
                self.assertTrue((WEB / asset).is_file())

    def test_no_synthetic_eta(self):
        page = (WEB / "index.html").read_text()
        self.assertIn("ETA unavailable", page)
        self.assertIn("Not enough live data yet", page)
        self.assertNotIn("3 min away", page)

    def test_api_url_is_relative(self):
        script = (WEB / "app.js").read_text()
        self.assertIn('const API_ENDPOINT = "/api/v1/vehicles"', script)
        self.assertNotIn("api.syndrid.com", script)
        self.assertIn('vehicle.locationKind !== "confirmed"', script)

    def test_sw_never_caches_gps(self):
        sw = (WEB / "service-worker.js").read_text()
        self.assertIn('url.pathname.startsWith("/api/")', sw)

    def test_destination_choices_exist(self):
        page = (WEB / "index.html").read_text()
        for choice in ["nac", "marshak", "shepard", "steinman", "spitzer"]:
            self.assertIn('value="' + choice + '"', page)

if __name__ == "__main__":
    unittest.main()
