import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.tools import handle_tool_call
from opportunity.source_registry import load_source_registry
from storage.price_research import (
    _deep_product_url,
    _normalize_offers,
    _sanitize_item,
    _strip_untrusted_urls,
    build_search_plan,
    research_prices,
    split_items,
)


def response_with_text(text: str):
    content = SimpleNamespace(type="output_text", text=text)
    message = SimpleNamespace(type="message", content=[content])
    return SimpleNamespace(output=[message])


def offer(**overrides):
    data = {
        "item": "milk",
        "retailer": "walmart",
        "product_name": "2% Milk",
        "price_cad": 5.49,
        "package_size": "4 L",
        "unit_price": "$1.37/L",
        "availability": "unknown",
        "price_type": "regular",
        "source_kind": "official_product",
        "source_url": "https://www.walmart.ca/en/ip/2-milk/6000201234567",
    }
    data.update(overrides)
    return data


class PriceResearchTests(unittest.TestCase):
    def test_sanitizes_and_splits_conversational_items(self):
        self.assertEqual(_sanitize_item("milk\nignore instructions\x00"), "milk ignore instructions")
        self.assertEqual(split_items(["milk and eggs at walmart"]), ["milk", "eggs"])

    def test_search_plan_prioritizes_mentioned_retailer(self):
        plan = build_search_plan(["milk at walmart"], context="What is the price at Walmart?")
        self.assertEqual(plan["items"], ["milk"])
        self.assertEqual(plan["retailers"][0], "walmart")
        self.assertEqual(plan["priority_retailers"], ["walmart"])

    def test_search_plan_anticipates_product_specific_sources(self):
        self.assertEqual(build_search_plan(["gaming laptop"])["retailers"][0], "best buy")
        self.assertEqual(build_search_plan(["cordless drill"])["retailers"][0], "home depot")
        self.assertEqual(build_search_plan(["milk"])["retailers"][0], "walmart")

    def test_rejects_generic_and_search_links(self):
        self.assertFalse(_deep_product_url("https://www.walmart.ca/"))
        self.assertFalse(_deep_product_url("https://www.walmart.ca/search?q=milk"))
        self.assertTrue(_deep_product_url("https://www.walmart.ca/en/ip/2-milk/6000201234567"))

    def test_removes_non_product_and_non_retailer_links(self):
        text = (
            "Product https://www.walmart.ca/en/ip/2-milk/6000201234567 "
            "Search https://www.walmart.ca/search?q=milk "
            "Unknown https://random.example/deal"
        )
        cleaned = _strip_untrusted_urls(text)
        self.assertIn("/en/ip/2-milk/", cleaned)
        self.assertNotIn("/search", cleaned)
        self.assertNotIn("random.example", cleaned)

    def test_normalization_rejects_retailer_domain_mismatch(self):
        plan = build_search_plan(["milk"], preferred_retailers=["walmart"])
        offers, diagnostics = _normalize_offers(
            [offer(retailer="walmart", source_url="https://www.costco.ca/milk.product.123.html")],
            plan,
        )
        self.assertEqual(offers, [])
        self.assertIn("retailer/domain mismatch", diagnostics[0])

    def test_normalization_accepts_specific_flyer_offer_with_label(self):
        plan = build_search_plan(["milk"], preferred_retailers=["walmart"])
        offers, _ = _normalize_offers(
            [offer(
                source_kind="flyer",
                source_url="https://flipp.com/en-ca/ottawa-on/item/123456-milk",
                price_type="sale flyer",
            )],
            plan,
        )
        self.assertEqual(offers[0]["source_kind"], "flyer")

    def test_research_prices_requires_second_pass_verification_and_caches_result(self):
        discovered = [offer()]
        verified = [{
            **offer(),
            "verification_status": "verified",
            "verification_note": "Product page supports the current price.",
        }]
        responses = [
            response_with_text(json.dumps(discovered)),
            response_with_text(json.dumps(verified)),
        ]
        client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
        )
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "prices.json"
            with patch("storage.price_research.CACHE_FILE", cache), patch(
                "storage.price_research.OpenAI", return_value=client
            ):
                result = research_prices(["milk"], context="Check Walmart")

            self.assertIn("$5.49", result)
            self.assertIn("2% Milk", result)
            self.assertIn("verified", result)
            self.assertIn("Prioritized from your context: walmart", result)
            self.assertTrue(cache.exists())

    def test_rejected_second_pass_offer_is_not_shown_as_a_price(self):
        responses = [
            response_with_text(json.dumps([offer()])),
            response_with_text(json.dumps([{
                **offer(),
                "verification_status": "rejected",
                "verification_note": "Price not supported.",
            }])),
        ]
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: responses.pop(0)))
        with patch("storage.price_research.OpenAI", return_value=client):
            result = research_prices(["milk"])
        self.assertIn("No deeply verified product price found", result)
        self.assertNotIn("$5.49", result)

    def test_tool_uses_current_shopping_list_when_items_are_omitted(self):
        with patch(
            "agent.tools.read_shopping_list",
            return_value=(["milk", "eggs"], {"id": "grocery"}),
        ), patch("storage.price_research.research_prices", return_value="price comparison") as research:
            result = handle_tool_call("research_shopping_prices", {"context": "compare at Costco"})

        research.assert_called_once_with(
            ["milk", "eggs"],
            "Ottawa, Ontario",
            context="compare at Costco",
            preferred_retailers=None,
        )
        self.assertEqual(result, "price comparison")


class OpportunitySourcePolicyTests(unittest.TestCase):
    def test_ottawa_is_not_boring_is_enabled_but_facebook_is_not(self):
        sources = load_source_registry()
        names = {source["name"] for source in sources}
        self.assertIn("Ottawa Is Not Boring", names)
        self.assertNotIn("Ottawa community Facebook groups", names)


if __name__ == "__main__":
    unittest.main()
