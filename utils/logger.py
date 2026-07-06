import os
import sys
import datetime


class _Tee:
    """Write to several streams at once (console + logfile), flushing eagerly
    so the log is complete even if the run crashes."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def setup_logging(logdir='./logs'):
    """Tee stdout/stderr to a timestamped file under logdir so every run of the
    script produces its own log. Returns the log file path."""
    os.makedirs(logdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    logpath = os.path.join(logdir, f'run_{stamp}.log')
    logfile = open(logpath, 'a', encoding='utf-8')
    sys.stdout = _Tee(sys.__stdout__, logfile)
    sys.stderr = _Tee(sys.__stderr__, logfile)
    return logpath
