from unittest.mock import MagicMock, patch

from foreclosure_bot.alerts import AlertSender


def test_send_calls_smtp(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="boom", traceback="tb")
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("u", "p")
        smtp.sendmail.assert_called_once()


def test_throttle_blocks_second_within_hour(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="m", traceback="t")
        sender.notify(stage="court", message="m", traceback="t")
        assert smtp.sendmail.call_count == 1


def test_throttle_independent_per_stage(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="m", traceback="t")
        sender.notify(stage="gis", message="m", traceback="t")
        assert smtp.sendmail.call_count == 2
