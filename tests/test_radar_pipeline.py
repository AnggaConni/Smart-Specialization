import importlib.util
import unittest
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline" / "collect_radar.py"
SPEC = importlib.util.spec_from_file_location("s3_collect_radar", PIPELINE)
RADAR = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RADAR)


class RadarTransformTests(unittest.TestCase):
    def test_normalise_doi(self):
        self.assertEqual(RADAR.normalise_doi("https://doi.org/10.1000/ABC"), "10.1000/abc")

    def test_gdelt_date_parser_accepts_seendate(self):
        self.assertEqual(RADAR.gdelt_date("20261014T102030Z"), "2026-10-14")

    def test_gdelt_url_key_normalizes_host_and_fragment(self):
        self.assertEqual(
            RADAR.gdelt_url_key("HTTPS://Example.COM/story/?utm_source=test#section"),
            "https://example.com/story/?utm_source=test",
        )
        self.assertEqual(RADAR.gdelt_url_key("javascript:alert(1)"), "")

    def test_crossref_skips_implausible_future_publication_date(self):
        item = {
            "published": {"date-parts": [[2121, 10, 1]]},
            "created": {"date-parts": [[2025, 2, 12]]},
        }
        self.assertEqual(RADAR.publication_date_from_crossref(item), "2025-02-12")

    def test_openalex_skips_implausible_future_publication_year(self):
        work = {
            "title": "A study of regional innovation",
            "publication_date": "2121-10-01",
            "publication_year": 2121,
            "doi": "https://doi.org/10.1000/future",
            "primary_location": {"landing_page_url": "https://example.org/study", "source": {"display_name": "Example Journal"}},
        }
        topic = {"sector": "Regional Innovation", "query": "regional innovation"}
        record = RADAR.openalex_record(work, topic)
        self.assertIsNotNone(record)
        self.assertIsNone(record["publication_date"])
        self.assertIsNone(record["year"])

    def test_reconstruct_abstract(self):
        abstract = {"smart": [0], "regions": [1], "innovate": [2]}
        self.assertEqual(RADAR.reconstruct_abstract(abstract), "smart regions innovate")

    def test_merge_deduplicates_crossref_and_openalex_by_doi(self):
        base = {
            "title": "Regional innovation",
            "doi": "https://doi.org/10.1000/test",
            "url": "https://doi.org/10.1000/test",
            "publication_date": "2025-01-01",
            "year": 2025,
            "venue": "",
            "publisher": "",
            "authors": [],
            "abstract": "",
            "cited_by_count": 2,
            "data_sources": ["OpenAlex"],
            "source_urls": ["https://openalex.org/"],
            "sectors": ["Regional Innovation"],
            "queries": ["regional innovation"],
            "author_country_iso2": [],
            "record_type": "research",
        }
        second = {**base, "data_sources": ["Crossref"], "source_urls": ["https://crossref.org/"], "abstract": "A summary."}
        merged = RADAR.merge_signals([base, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["data_sources"]), {"OpenAlex", "Crossref"})
        self.assertEqual(merged[0]["abstract"], "A summary.")

    def test_trade_product_builder_computes_yoy(self):
        raw = {
            ("IDN", 2022): [{"cmdCode": "854231", "cmdDesc": "Example chips", "classificationCode": "H6", "primaryValue": 100}],
            ("IDN", 2023): [{"cmdCode": "854231", "cmdDesc": "Example chips", "classificationCode": "H6", "primaryValue": 150}],
        }
        items = RADAR.build_trade_products(raw, {"IDN": "Indonesia"})
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["yoy_growth_pct"], 50.0)
        self.assertEqual(items[0]["market_iso3"], "IDN")

    def test_flow_transform_filters_world_and_self_partner(self):
        rows = [
            {"partnerCode": "702", "partnerISO": "SGP", "cmdCode": "854231", "period": 2024, "primaryValue": 500},
            {"partnerCode": "0", "partnerISO": "W00", "cmdCode": "854231", "period": 2024, "primaryValue": 900},
            {"partnerCode": "360", "partnerISO": "IDN", "cmdCode": "854231", "period": 2024, "primaryValue": 100},
        ]
        flows = RADAR.build_trade_flows(rows, "IDN", "Indonesia", 2024, {"702": "SGP", "360": "IDN"})
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0]["supplier_iso3"], "SGP")
        self.assertEqual(flows[0]["buyer_iso3"], "IDN")


if __name__ == "__main__":
    unittest.main()
