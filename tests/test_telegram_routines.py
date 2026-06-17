import importlib.util
import json

import pytest

import telegram_routines


def test_telegram_routines_module_exists() -> None:
    assert importlib.util.find_spec("telegram_routines") is not None


class FakeStore:
    def stats(self) -> dict:
        return {
            "total": 7,
            "by_status": {
                "new": 3,
                "enriched": 2,
                "manual_review": 1,
                "not_relevant": 1,
            },
        }

    def coverage_by_segment(self) -> dict:
        return {
            "medical-imaging": {"new": 2, "enriched": 1},
            "speech-and-audio": {"manual_review": 1},
        }

    def list_hot_leads(self, limit: int = 5) -> list[dict]:
        hot_rows = [
            {
                "name": "Alpha <Vision>",
                "domain": "alpha.ai",
                "status": "relevant",
                "icp_segment": "medical-imaging",
            },
            {
                "name": "Beta Audio",
                "domain": "beta.example",
                "status": "sources_gathered",
                "icp_segment": "speech-and-audio",
            },
        ]
        return hot_rows[:limit]

    def list_stale_review_queue(self, days: int = 14, limit: int = 10) -> list[dict]:
        stale_rows = [
            {
                "name": "Needs Review",
                "domain": "needs-review.ai",
                "status": "manual_review",
                "last_verified": "2026-05-01",
            }
        ]
        return stale_rows[:limit]


def test_daily_digest_formats_counts_and_segment_coverage() -> None:
    result = telegram_routines.run_routine(
        "daily_digest",
        store=FakeStore(),
        dry_run=True,
    )

    assert result.name == "daily_digest"
    assert result.sent is False
    assert "Daily digest" in result.message
    assert "Total companies: <b>7</b>" in result.message
    assert "new: 3" in result.message
    assert "medical-imaging" in result.message
    assert result.payload["stats"]["total"] == 7


def test_hot_leads_escapes_html_and_respects_limit() -> None:
    result = telegram_routines.run_routine(
        "hot_leads",
        store=FakeStore(),
        dry_run=True,
        limit=1,
    )

    assert "Alpha &lt;Vision&gt;" in result.message
    assert "Beta Audio" not in result.message
    assert "Score:" not in result.message
    assert "relevant" in result.message


def test_stale_review_uses_requested_day_window() -> None:
    result = telegram_routines.run_routine(
        "stale_review",
        store=FakeStore(),
        dry_run=True,
        days=30,
    )

    assert "30d" in result.message
    assert "Needs Review" in result.message
    assert "Score:" not in result.message
    assert "manual_review" in result.message
    assert result.payload["days"] == 30


def test_run_routine_sends_when_not_dry_run() -> None:
    sent_messages: list[str] = []

    result = telegram_routines.run_routine(
        "daily_digest",
        store=FakeStore(),
        send_message=sent_messages.append,
    )

    assert result.sent is True
    assert sent_messages == [result.message]


def test_unknown_routine_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown Telegram routine"):
        telegram_routines.run_routine("unknown", store=FakeStore(), dry_run=True)


def test_main_dry_run_prints_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(telegram_routines, "_default_store", lambda: FakeStore())

    exit_code = telegram_routines.main(["daily_digest", "--dry-run"])

    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "daily_digest"
    assert out["sent"] is False
    assert out["payload"]["stats"]["total"] == 7
