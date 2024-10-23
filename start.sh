rq worker --log-level=DEBUG &
gunicorn --bind 0.0.0.0:8080 app:app