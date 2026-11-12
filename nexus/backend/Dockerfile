FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md /holding/
COPY src /holding/src
RUN pip install --no-cache-dir /holding
COPY nexus/backend /app
RUN pip install --no-cache-dir ".[postgres]"
ENV NEXUS_HOST=0.0.0.0
EXPOSE 8000
CMD ["nexus-api"]
