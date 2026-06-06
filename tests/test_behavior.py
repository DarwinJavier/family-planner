import json
import unittest
import httpx
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from openai import RateLimitError

from agent import brain
from scheduler.jobs import _build_reminder, _time_until


class ReminderTimingTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("America/Toronto")
        self.now = datetime(2026, 6, 6, 12, 0, tzinfo=self.tz)

    def test_time_until_reports_more_than_one_hour_accurately(self):
        self.assertEqual(_time_until(self.now + timedelta(minutes=74), self.now), "1 h 14 min")

    def test_reminder_uses_calculated_countdown(self):
        message = _build_reminder(
            "Basketball practice",
            "sports",
            self.now + timedelta(minutes=74),
            now=self.now,
        )
        self.assertIn("empieza en 1 h 14 min", message)
        self.assertNotIn("menos de una hora", message)


class ConfirmationTests(unittest.TestCase):
    def tearDown(self):
        brain._pending_writes.clear()

    def test_affirmative_executes_pending_write(self):
        user_id = 123
        pending_input = {
            "title": "Dentist",
            "start_datetime": "2026-06-08T15:00:00",
            "end_datetime": "2026-06-08T16:00:00",
        }
        brain._set_pending_write(user_id, "create_calendar_event", pending_input)

        with patch("agent.brain.handle_tool_call", return_value="Event created: Dentist") as tool:
            reply, history = brain.process_message("yes", [], user_id=user_id)

        tool.assert_called_once_with("create_calendar_event", pending_input)
        self.assertEqual(reply, "Event created: Dentist")
        self.assertNotIn(user_id, brain._pending_writes)
        self.assertEqual(history[-1]["content"], "Event created: Dentist")

    def test_common_affirmative_phrases_execute_without_asking_again(self):
        pending_input = {
            "title": "Dentist",
            "start_datetime": "2026-06-08T15:00:00",
            "end_datetime": "2026-06-08T16:00:00",
        }

        for user_id, confirmation in enumerate(
            [
                "yes please",
                "yes, please create it",
                "looks good",
                "go ahead and add it",
                "sí, por favor",
                "dale, agrégalo",
            ],
            start=1000,
        ):
            with self.subTest(confirmation=confirmation):
                brain._set_pending_write(user_id, "create_calendar_event", pending_input)
                with (
                    patch("agent.brain.handle_tool_call", return_value="Event created: Dentist") as tool,
                    patch("agent.brain.OpenAI") as openai,
                ):
                    reply, _ = brain.process_message(confirmation, [], user_id=user_id)

                tool.assert_called_once_with("create_calendar_event", pending_input)
                openai.assert_not_called()
                self.assertEqual(reply, "Event created: Dentist")
                self.assertNotIn(user_id, brain._pending_writes)

    def test_affirmative_with_requested_change_does_not_execute_pending_write(self):
        user_id = 2000
        brain._set_pending_write(
            user_id,
            "create_calendar_event",
            {
                "title": "Dentist",
                "start_datetime": "2026-06-08T15:00:00",
                "end_datetime": "2026-06-08T16:00:00",
            },
        )
        response_message = SimpleNamespace(role="assistant", content="Okay, changing it to 4 PM.", tool_calls=None)
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=response_message, finish_reason="stop")]
                    )
                )
            )
        )

        with patch("agent.brain.OpenAI", return_value=client), patch("agent.brain.handle_tool_call") as tool:
            brain.process_message("yes, but change it to 4 PM", [], user_id=user_id)

        tool.assert_not_called()

    def test_quota_exhaustion_returns_actionable_reply(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(429, request=request)
        error = RateLimitError(
            "Quota exhausted",
            response=response,
            body={"code": "insufficient_quota"},
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(error))
            )
        )

        with patch("agent.brain.OpenAI", return_value=client):
            reply, history = brain.process_message("hello", [], user_id=3000)

        self.assertIn("credits are exhausted", reply)
        self.assertIn("increase the OpenAI API limit", reply)
        self.assertEqual(history[-1]["content"], reply)

    def test_write_tool_is_held_until_confirmation(self):
        user_id = 789
        pending_input = {
            "title": "Dentist",
            "start_datetime": "2026-06-08T15:00:00",
            "end_datetime": "2026-06-08T16:00:00",
        }
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="create_calendar_event", arguments=json.dumps(pending_input)),
        )
        tool_message = SimpleNamespace(role="assistant", content=None, tool_calls=[tool_call])
        confirmation_message = SimpleNamespace(
            role="assistant",
            content="Should I add Dentist on Monday at 3:00 PM?",
            tool_calls=None,
        )
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(message=tool_message, finish_reason="tool_calls")]),
            SimpleNamespace(choices=[SimpleNamespace(message=confirmation_message, finish_reason="stop")]),
        ]
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: responses.pop(0))
            )
        )

        with patch("agent.brain.OpenAI", return_value=client), patch("agent.brain.handle_tool_call") as tool:
            reply, _ = brain.process_message("Schedule a dentist appointment Monday at 3", [], user_id=user_id)

        tool.assert_not_called()
        self.assertIn("Should I add", reply)
        self.assertEqual(brain._get_pending_write(user_id), ("create_calendar_event", pending_input))

    def test_negative_cancels_pending_write(self):
        user_id = 456
        brain._set_pending_write(user_id, "delete_calendar_event", {"event_id": "abc", "title": "Dentist"})

        reply, _ = brain.process_message("no", [], user_id=user_id)

        self.assertIn("won't change", reply)
        self.assertNotIn(user_id, brain._pending_writes)

    def test_pending_write_expires(self):
        user_id = 654
        brain._pending_writes[user_id] = ("create_calendar_event", {"title": "Old request"}, 0)

        with patch("agent.brain.time.monotonic", return_value=brain.PENDING_WRITE_TTL_SECONDS + 1):
            self.assertIsNone(brain._get_pending_write(user_id))

        self.assertNotIn(user_id, brain._pending_writes)

    def test_multimodal_history_does_not_store_image_data(self):
        content = [
            {"type": "text", "text": "Read this invitation"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,very-large-data"}},
        ]

        history = brain._chat_only_history([{"role": "user", "content": content}])

        self.assertEqual(history, [{"role": "user", "content": "[Image sent] Read this invitation"}])
        self.assertNotIn("base64", history[0]["content"])


if __name__ == "__main__":
    unittest.main()
