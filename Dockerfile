FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[beta]' && useradd --create-home --uid 10001 persona && mkdir /backups && chown persona /backups
COPY scripts ./scripts
USER persona
EXPOSE 8770
CMD ["python", "-m", "relationship_agent.beta.app", "--host", "0.0.0.0", "--port", "8770"]
