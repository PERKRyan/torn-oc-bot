import time

class APILimiter:
    def __init__(self, max_calls_per_minute=80):
        self.max_calls = max_calls_per_minute
        self.call_times = []

    def allow(self):
        now = time.time()
        # Remove calls older than 60s
        self.call_times = [t for t in self.call_times if now - t < 60]

        if len(self.call_times) < self.max_calls:
            self.call_times.append(now)
            return True
        return False
