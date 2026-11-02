"""Background jobs (v1.4.5) for long downloads.

A Streamlit script run is stopped whenever the page reruns, and the browser reruns the page when its websocket reconnects (a laptop
waking from sleep, a slow mobile link, a tab throttled in the background). A 10-minute basin composite running inside the script was
therefore lost on any reconnect. A Job runs the work in its own thread, kept in st.session_state, so it survives reruns and reconnects
of the same session; the page only polls its progress.
"""
import threading
import time
import traceback


class Job:
    def __init__(self, name, fn, *args, **kwargs):
        self.name = name
        self.progress, self.message = 0.0, "Starting…"
        self.result, self.error, self.detail = None, None, None
        self.started, self.finished = time.time(), None
        self.consumed = False                # set once the page has registered the result
        self._thread = threading.Thread(target=self._run, args=(fn, args, kwargs), name=f"job-{name}", daemon=True)
        self._thread.start()

    def _report(self, frac, msg=""):
        self.progress, self.message = max(0.0, min(float(frac), 1.0)), str(msg)

    def _run(self, fn, args, kwargs):
        try:
            self.result = fn(*args, progress=self._report, **kwargs)
            self._report(1.0, "Done")
        except Exception as e:  # noqa: BLE001 - surfaced to the user by the page
            self.error, self.detail = f"{type(e).__name__}: {e}", traceback.format_exc(limit=4)
        finally:
            self.finished = time.time()

    @property
    def running(self):
        return self.finished is None

    @property
    def elapsed(self):
        return (self.finished or time.time()) - self.started

    def wait(self, timeout=None):
        self._thread.join(timeout)
        return not self.running
