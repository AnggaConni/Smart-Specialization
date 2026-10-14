import importlib.util
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline" / "collect_radar.py"
SPEC = importlib.util.spec_from_file_location("s3_collect_radar", PIPELINE)
RADAR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RADAR)


class RequiredMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.external_scripts = set()
        self.html_language = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "script" and attrs.get("src"):
            self.external_scripts.add(attrs["src"])
        if tag == "html":
            self.html_language = attrs.get("lang")


class RadarHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "radar.html").read_text(encoding="utf-8")
        cls.parser = RequiredMarkup()
        cls.parser.feed(cls.html)

    def test_english_default_themes_translate_and_favicon_are_present(self):
        self.assertEqual(self.parser.html_language, "en")
        self.assertIn('href="./favicon.svg"', self.html)
        self.assertIn("color-scheme:light", self.html)
        self.assertIn("html[data-theme=dark]", self.html)
        self.assertIn('id="themeToggle"', self.html)
        self.assertIn('id="google_translate_element"', self.html)
        self.assertIn("google.translate.TranslateElement", (ROOT / "radar.js").read_text(encoding="utf-8"))

    def test_dashboard_elements_used_by_javascript_exist(self):
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        refs = set(re.findall(r'\$\("([^"]+)"\)', js))
        refs |= set(re.findall(r'getElementById\("([^"]+)"\)', js))
        self.assertFalse(refs - self.parser.ids, "Missing DOM ids: " + ", ".join(sorted(refs - self.parser.ids)))

    def test_dashboard_loads_external_script(self):
        self.assertIn("./radar.js", self.parser.external_scripts)
        self.assertIn("./data/radar-data.json", (ROOT / "radar.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
