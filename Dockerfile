FROM python:3.12-slim

WORKDIR /app

# The same user id as the other tools, as the suite's volumes expect.
RUN useradd -m -u 1000 appuser && mkdir -p /booking && chown -R appuser:appuser /app /booking

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn==23.0.0

COPY app/ ./app/

USER appuser

EXPOSE 5007

ENV PYTHONUNBUFFERED=1 \
    BOOKING_DATABASE_PATH=/booking/booking.db \
    MOCLO_DATABASE_PATH=/moclo/moclo.db \
    SUITE_DATABASE_PATH=/suite/suite.db \
    URL_PREFIX=/booking \
    TZ=Europe/Amsterdam \
    PORT=5007

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5007/booking/health')" || exit 1

# One worker with threads: SQLite's write lock (BEGIN IMMEDIATE) keeps bookings from clashing.
CMD ["gunicorn", "--bind", "0.0.0.0:5007", "--workers", "1", "--threads", "4", "app.main:app"]
