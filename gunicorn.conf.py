import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
threads = 1
timeout = 30
accesslog = None  # request logging is done by our own middleware
