FROM finance-bench-sandbox:latest
COPY baselines/iterative/__init__.py baselines/iterative/agent.py baselines/iterative/prompts.py /opt/baselines/iterative/
ENV PYTHONPATH=/opt PYTHONDONTWRITEBYTECODE=1
LABEL qfbench2.interface_version="2.0"
ENTRYPOINT ["python", "-m", "baselines.iterative.agent"]
CMD ["solve", "--task-dir", "/input", "--out", "/app/output"]
