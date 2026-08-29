FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY data/knowledge/ ./data/knowledge/
COPY data/illustrations/ ./data/illustrations/
COPY run.py ./

ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python3", "run.py", "8000"]
