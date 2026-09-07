FROM finance-bench-sandbox:latest
RUN pip install --no-cache-dir "qfbench2-common @ https://github.com/Agenthon-2026/Agenthon2026-public/archive/refs/tags/v2.3.1.tar.gz#subdirectory=common"
COPY qfbench2_track_coding/__init__.py qfbench2_track_coding/scoring.py /opt/qfbench2_track_coding/
COPY scripts/evaluate_baseline.py /opt/evaluate_baseline.py
ENV PYTHONPATH=/opt PYTHONDONTWRITEBYTECODE=1
