import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from opportunity.models import ExternalEvent, FreeWindow
from opportunity.preferences import DEFAULT_PREFERENCES
from opportunity.service import (
    build_calendar_proposal,
    detect_free_windows,
    discover_recommendations,
    dismiss_recommendation,
    recommend_more_like,
    save_recommendation,
    score_activity,
)
from opportunity.sources import ConfiguredWebLeadSource, search_sources


TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 6, 6, 8, 0, tzinfo=TZ)


def event(title, start, end, members=None):
    item = {
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if members:
        item["extendedProperties"] = {"private": {"family_members": ",".join(members)}}
    return item


def activity(**overrides):
    raw = {
        "id": "activity-1",
        "title": "Youth Debate Workshop",
        "description": "A practical debate session.",
        "source": "Test source",
        "source_url": "https://ottawa.ca/events",
        "venue": "Community Centre",
        "address": "Ottawa, ON",
        "start": datetime(2026, 6, 6, 14, 0, tzinfo=TZ),
        "end": datetime(2026, 6, 6, 16, 0, tzinfo=TZ),
        "categories": ["debate", "leadership"],
        "min_age": 12,
        "max_age": 17,
        "indoor_outdoor": "indoor",
        "admission_cost": 20,
        "parking_cost": 5,
        "incidental_cost": 5,
        "travel_minutes": 20,
        "relevant_members": ["older_child"],
        "confidence": 0.8,
        "registration_required": True,
        "registration_deadline": datetime(2026, 6, 6, 13, 0, tzinfo=TZ),
    }
    raw.update(overrides)
    return ExternalEvent.from_dict(raw)


def config(**availability_overrides):
    availability = {
        "day_start": "09:00",
        "day_end": "20:00",
        "minimum_useful_minutes": 90,
        "preparation_minutes": 20,
        "default_travel_minutes": 20,
        "maximum_commitments_per_day": 3,
        "protected_periods": [],
    }
    availability.update(availability_overrides)
    return {"availability": availability}


class FreeWindowTests(unittest.TestCase):
    def test_overlapping_events_are_merged_with_travel_buffers(self):
        events = [
            event("One", datetime(2026, 6, 6, 11, 0, tzinfo=TZ), datetime(2026, 6, 6, 12, 0, tzinfo=TZ)),
            event("Two", datetime(2026, 6, 6, 11, 30, tzinfo=TZ), datetime(2026, 6, 6, 13, 0, tzinfo=TZ)),
        ]
        windows = detect_free_windows(events, NOW, datetime(2026, 6, 6, 20, 0, tzinfo=TZ), config())

        self.assertEqual(windows[0].end, datetime(2026, 6, 6, 10, 40, tzinfo=TZ))
        self.assertEqual(windows[1].start, datetime(2026, 6, 6, 13, 20, tzinfo=TZ))

    def test_protected_time_is_not_available(self):
        cfg = config(protected_periods=[{"weekdays": [5], "start": "12:00", "end": "14:00"}])
        windows = detect_free_windows([], NOW, datetime(2026, 6, 6, 20, 0, tzinfo=TZ), cfg)

        self.assertTrue(all(not (window.start < datetime(2026, 6, 6, 14, 0, tzinfo=TZ) and window.end > datetime(2026, 6, 6, 12, 0, tzinfo=TZ)) for window in windows))

    def test_maximum_commitments_protects_the_day(self):
        events = [
            event(str(index), datetime(2026, 6, 6, 9 + index, 0, tzinfo=TZ), datetime(2026, 6, 6, 10 + index, 0, tzinfo=TZ))
            for index in range(3)
        ]
        windows = detect_free_windows(events, NOW, datetime(2026, 6, 6, 20, 0, tzinfo=TZ), config())
        self.assertEqual(windows, [])

    def test_individual_availability_ignores_other_child_event(self):
        events = [
            event(
                "Younger child class",
                datetime(2026, 6, 6, 12, 0, tzinfo=TZ),
                datetime(2026, 6, 6, 15, 0, tzinfo=TZ),
                members=["younger_child"],
            )
        ]
        family_windows = detect_free_windows(events, NOW, datetime(2026, 6, 6, 20, 0, tzinfo=TZ), config())
        older_windows = detect_free_windows(
            events,
            NOW,
            datetime(2026, 6, 6, 20, 0, tzinfo=TZ),
            config(),
            required_members=("older_child",),
        )
        self.assertGreater(older_windows[0].duration_minutes, family_windows[0].duration_minutes)
        self.assertEqual(older_windows[0].kind, "individual")


class ModelAndScoringTests(unittest.TestCase):
    def setUp(self):
        self.window = FreeWindow(
            datetime(2026, 6, 6, 9, 0, tzinfo=TZ),
            datetime(2026, 6, 6, 19, 0, tzinfo=TZ),
        )
        self.scoring_config = {
            "availability": {"preparation_minutes": 20},
            "scoring": {
                "calendar_fit": 35,
                "interest_match": 22,
                "age_suitability": 12,
                "travel": 10,
                "cost": 8,
                "confidence": 8,
                "novelty": 5,
            },
        }

    def test_external_event_validation_and_registration_deadline(self):
        item = activity()
        self.assertTrue(item.registration_required)
        self.assertEqual(item.registration_deadline.hour, 13)
        with self.assertRaises(ValueError):
            activity(source_url="http://unsafe.example/event")

    def test_score_explains_match(self):
        recommendation = score_activity(activity(), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW)
        self.assertIsNotNone(recommendation)
        self.assertIn("matches debate, leadership", recommendation.explanation)

    def test_age_budget_and_distance_filters(self):
        self.assertIsNone(score_activity(activity(min_age=5, max_age=10), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW))
        self.assertIsNone(score_activity(activity(admission_cost=500), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW))
        self.assertIsNone(score_activity(activity(travel_minutes=90), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW))
        self.assertIsNone(score_activity(activity(availability_status="cancelled"), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW))
        self.assertIsNone(score_activity(activity(registration_deadline=NOW - timedelta(minutes=1)), self.window, DEFAULT_PREFERENCES, {"feedback": {}}, self.scoring_config, now=NOW))

    def test_feedback_blocks_dismissed_activity(self):
        state = {"feedback": {"activity-1": {"value": "dismissed", "categories": ["debate"]}}}
        self.assertIsNone(score_activity(activity(), self.window, DEFAULT_PREFERENCES, state, self.scoring_config, now=NOW))


class ProviderAndWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.preferences_file = Path(self.temp.name) / "preferences.json"
        self.state_file = Path(self.temp.name) / "state.json"
        self.patches = [
            patch("opportunity.preferences.PREFERENCES_FILE", self.preferences_file),
            patch("opportunity.preferences.STATE_FILE", self.state_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_provider_failure_does_not_break_search(self):
        class BrokenSource:
            name = "Broken"

            def search_events(self, start, end):
                raise RuntimeError("offline")

        activities, warnings = search_sources([BrokenSource()], NOW, NOW + timedelta(days=1))
        self.assertEqual(activities, [])
        self.assertIn("temporarily unavailable", warnings[0])

    def test_configured_web_source_validates_structured_results(self):
        raw = {
            "id": "real-1",
            "title": "Ottawa Family Event",
            "description": "A verified event.",
            "source": "Ottawa Is Not Boring",
            "source_url": "https://ottawaisnotboring.com/event",
            "venue": "Ottawa",
            "address": "Ottawa, ON",
            "start": "2026-06-06T14:00:00-04:00",
            "end": "2026-06-06T16:00:00-04:00",
            "categories": ["family"],
            "min_age": 5,
            "max_age": 99,
            "indoor_outdoor": "indoor",
            "registration_required": False,
            "registration_deadline": None,
            "availability_status": "available",
            "admission_cost": 0,
            "parking_cost": 0,
            "incidental_cost": 0,
            "travel_minutes": 20,
            "relevant_members": ["family"],
            "weather_sensitive": False,
            "confidence": 0.6,
            "last_verified_at": "2026-06-06T08:00:00-04:00",
        }
        response = type("Response", (), {
            "output": [
                type("Message", (), {
                    "type": "message",
                    "content": [type("Content", (), {"type": "output_text", "text": __import__("json").dumps([raw])})()],
                })()
            ]
        })()
        client = type("Client", (), {
            "responses": type("Responses", (), {"create": lambda self, **kwargs: response})()
        })()

        with patch("opportunity.sources.OpenAI", return_value=client):
            results = ConfiguredWebLeadSource().search_events(NOW, NOW + timedelta(days=1))

        self.assertEqual(results[0].source, "Ottawa Is Not Boring")

    def test_discovery_avoids_duplicate_calendar_title_and_limits_results(self):
        class Source:
            name = "Test"

            def search_events(self, start, end):
                return [
                    activity(id="duplicate", title="Already Planned"),
                    activity(id="new-one", title="New Debate Option"),
                ]

        existing = [
            event("Already Planned", datetime(2026, 6, 6, 9, 0, tzinfo=TZ), datetime(2026, 6, 6, 10, 0, tzinfo=TZ))
        ]
        recommendations, _ = discover_recommendations(NOW, existing, [Source()], limit=1)
        self.assertEqual([item.activity.id for item in recommendations], ["new-one"])

    def test_calendar_proposal_includes_preparation_travel_and_conflict_warning(self):
        class Source:
            name = "Test"

            def search_events(self, start, end):
                return [activity()]

        recommendations, _ = discover_recommendations(NOW, [], [Source()])
        with patch("opportunity.service.get_overlapping_events", return_value=[{"summary": "Existing plan"}]):
            proposal, conflicts = build_calendar_proposal(recommendations[0].activity.id)

        self.assertEqual(datetime.fromisoformat(proposal["start_datetime"]), activity().start - timedelta(minutes=40))
        self.assertEqual(datetime.fromisoformat(proposal["end_datetime"]), activity().end + timedelta(minutes=20))
        self.assertEqual(conflicts, ["Existing plan"])
        self.assertIn("Official source:", proposal["description"])

    def test_save_dismiss_and_more_like_feedback_are_persisted(self):
        class Source:
            name = "Test"

            def search_events(self, start, end):
                return [activity()]

        recommendations, _ = discover_recommendations(NOW, [], [Source()])
        activity_id = recommendations[0].activity.id
        self.assertIsNotNone(save_recommendation(activity_id))
        self.assertIsNotNone(recommend_more_like(activity_id))
        self.assertIsNotNone(dismiss_recommendation(activity_id, "too_far"))

        from opportunity.preferences import load_state
        self.assertEqual(load_state()["feedback"][activity_id]["value"], "too_far")


if __name__ == "__main__":
    unittest.main()
