FROM python:3.12-slim

WORKDIR /app
COPY src/ ./src/
COPY data/ ./data/
COPY run.py ./

ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python3", "run.py", "8000"]
