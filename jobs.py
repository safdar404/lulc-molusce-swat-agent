"""Background jobs (v1.4.5) for long downloads.

A Streamlit script run is stopped whenever the page reruns, and the browser reruns the page when its websocket reconnects (a laptop
waking from sleep, a slow mobile link, a tab throttled in the background). A 10-minute basin composite running inside the script was
therefore lost on any reconnect. A Job runs the work in its own thread, kept in st.session_state, so it survives reruns and reconnects
of the same session; the page only polls its progress.
"""
import threading
import time
import traceback
import uuid


class Job:
    def __init__(self, name, fn, *args, **kwargs):
        self.name = name
        self.id = uuid.uuid4().hex[:16]      # unguessable; put in the page URL so a reloaded page can pick the job up again
        self.meta = {}
        self.progress, self.message = 0.0, "Starting…"
        self.result, self.error, self.detail = None, None, None
        self.started, self.finished = time.time(), None
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


class Registry:
    """Server-wide job table so a job outlives the browser session that started it (a page reload opens a NEW Streamlit session).
    Finished jobs are dropped after `keep_s` seconds; at most `max_jobs` are kept."""

    def __init__(self, keep_s=3600, max_jobs=20):
        self.jobs, self.keep_s, self.max_jobs = {}, keep_s, max_jobs
        self._lock = threading.Lock()

    def add(self, job):
        with self._lock:
            now = time.time()
            for k in [k for k, j in self.jobs.items() if j.finished and now - j.finished > self.keep_s]:
                del self.jobs[k]
            while len(self.jobs) >= self.max_jobs:
                done = [k for k, j in self.jobs.items() if j.finished] or list(self.jobs)
                del self.jobs[done[0]]
            self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id) if job_id else None
