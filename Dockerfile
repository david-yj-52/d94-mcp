FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd -m -u 10001 d94
WORKDIR /app
COPY pyproject.toml ./
COPY d94_mcp ./d94_mcp
RUN pip install --no-cache-dir .
USER d94
EXPOSE 8095
# workers=1 고정: workflow job 저장소가 프로세스 메모리에 있다
CMD ["uvicorn", "d94_mcp.server:app", "--host", "0.0.0.0", "--port", "8095", "--workers", "1"]
