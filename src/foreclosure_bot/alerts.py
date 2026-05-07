import smtplib
import time
from email.message import EmailMessage
from .dedupe import Store


class AlertSender:
    THROTTLE_SECS = 3600

    def __init__(self, *, store: Store, host: str, port: int,
                 user: str, password: str, to: str):
        self.store = store
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.to = to

    def notify(self, *, stage: str, message: str, traceback: str) -> None:
        if self._throttled(stage):
            return
        msg = EmailMessage()
        msg["Subject"] = f"[foreclosure-bot] error in {stage}"
        msg["From"] = self.user
        msg["To"] = self.to
        msg.set_content(f"Stage: {stage}\n\n{message}\n\n{traceback}")
        with smtplib.SMTP(self.host, self.port) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.sendmail(self.user, [self.to], msg.as_string())
        self.store.set_state(self._key(stage), str(int(time.time())))

    def _throttled(self, stage: str) -> bool:
        last = self.store.get_state(self._key(stage))
        if last is None:
            return False
        return (time.time() - int(last)) < self.THROTTLE_SECS

    @staticmethod
    def _key(stage: str) -> str:
        return f"alert_last_sent::{stage}"
