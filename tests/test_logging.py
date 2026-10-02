import logging

from utils.logging import HealthCheckFilter


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:5000", "GET", path, "1.1", 200),
        exc_info=None,
    )


class TestHealthCheckFilter:
    def test_drops_health_requests(self):
        assert HealthCheckFilter().filter(_access_record("/health")) is False

    def test_keeps_other_requests(self):
        assert HealthCheckFilter().filter(_access_record("/webhook")) is True
