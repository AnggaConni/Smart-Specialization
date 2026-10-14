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
        # This button is injected into the region-detail panel at runtime.
        refs.difference_update({"focusExplorerMap", "boundaryLevelSelect", "loadRegionBoundaries", "selectedAdminUnitInfo", "boundaryMetadataNote"})
        self.assertFalse(refs - self.parser.ids, "Missing DOM ids: " + ", ".join(sorted(refs - self.parser.ids)))

    def test_dashboard_loads_external_script(self):
        self.assertIn("./radar.js", self.parser.external_scripts)
        self.assertIn("./data/radar-data.json", (ROOT / "radar.js").read_text(encoding="utf-8"))

    def test_map_initializes_before_optional_carto_config(self):
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        init = js[js.index("function initialiseMap()"):js.index("function rebuildMarketFilter()")]
        self.assertIn('L.tileLayer(osmTileUrl()', init)
        self.assertIn('state.markers=L.layerGroup().addTo(state.map)', init)
        self.assertIn('state.flowLayer=L.layerGroup().addTo(state.map)', init)
        self.assertIn('loadMapConfig().then(function()', init)
        self.assertNotIn('await loadMapConfig()', init)

    def test_map_has_tile_error_fallback(self):
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("function useOsmFallback(message)", js)
        self.assertIn("CARTO key was rejected; OpenStreetMap fallback active", js)

    def test_map_supports_fullscreen_and_mouse_wheel_zoom(self):
        self.assertIn('id="mapShell"', self.html)
        self.assertIn('id="mapFullscreenToggle"', self.html)
        self.assertIn("Scroll to zoom", self.html)
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("scrollWheelZoom:true", js)
        self.assertIn("requestFullscreen()", js)
        self.assertIn('document.addEventListener("fullscreenchange",updateFullscreenButton)', js)
        self.assertIn("invalidateSize({pan:false})", js)

    def test_geoboundaries_admin_level_controls_and_fallback_are_present(self):
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("https://www.geoboundaries.org/api/current/gbOpen/", js)
        self.assertIn("function loadAdministrativeBoundaries(iso,level)", js)
        self.assertIn('id="boundaryLevelSelect"', js)
        self.assertIn("simplifiedGeometryGeoJSON", js)
        self.assertIn("Reported licence:", js)

    def test_news_policy_watch_is_connected_to_snapshot(self):
        required = {"news-section", "newsSearch", "newsSectorFilter", "newsList", "newsCount", "kpiNews"}
        self.assertTrue(required.issubset(self.parser.ids), "Missing GDELT news watch elements")
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("function renderNewsSignals()", js)
        self.assertIn("state.newsSignals=Array.isArray(payload.news_signals)", js)
        self.assertIn('$("newsSearch").addEventListener("input",renderNewsSignals)', js)

    def test_policy_support_lab_builds_and_exports_evidence_briefs(self):
        required = {
            "policy-support", "policyCountry", "policySector", "policyAudience",
            "policyHorizon", "policyQuestion", "generatePolicyBrief",
            "downloadPolicyBrief", "policyBriefStatus", "policyBriefOutput"
        }
        self.assertTrue(required.issubset(self.parser.ids), "Missing Policy Support Lab controls")
        self.assertIn('href="#policy-support"', self.html)
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("function generatePolicyBrief()", js)
        self.assertIn("function downloadPolicyBrief()", js)
        self.assertIn("Candidate options for appraisal—not recommendations", js)
        self.assertIn("official government/UN position", js)
        self.assertIn("function renderPolicyControls()", js)
        self.assertIn("markPolicyBriefStale()", js)

    def test_source_registry_does_not_repeat_note_when_it_is_already_card_body(self):
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn('escapeHtml(detail?info:"")', js)

    def test_regional_explorer_controls_and_rendering_exist(self):
        required = {
            "regional-explorer", "regionSearch", "regionGroupFilter",
            "regionEvidenceFilter", "regionExplorerList", "regionExplorerDetail",
            "regionExplorerCount"
        }
        self.assertTrue(required.issubset(self.parser.ids), "Missing regional explorer DOM IDs")
        js = (ROOT / "radar.js").read_text(encoding="utf-8")
        self.assertIn("function renderRegionExplorer()", js)
        self.assertIn("function renderRegionExplorerDetail(iso)", js)
        self.assertIn("countryTradeProducts(iso)", js)
        self.assertIn("countryTradeFlows(iso)", js)
        self.assertIn("countryResearchSignals(iso)", js)
        self.assertIn('renderRegionExplorer();renderNewsSignals();renderPolicyControls();if(state.selectedCountry', js)

    def test_regional_explorer_uses_dataset_without_fabricating_subnational_values(self):
        html = (ROOT / "radar.html").read_text(encoding="utf-8")
        self.assertIn("every country available in the current snapshot", html)
        self.assertIn("city or district-level", html.lower())
        self.assertIn("Has trade data", html)
        self.assertIn("Has economic indicators", html)


if __name__ == "__main__":
    unittest.main()
