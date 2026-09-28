import os

from prometheus_client import multiprocess

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
threads = 1
timeout = 30
accesslog = None


def child_exit(server, worker):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(worker.pid)
