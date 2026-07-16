FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src/ src/
RUN uv sync --frozen --no-dev
RUN useradd -u 1000 -m app
USER 1000
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "hello.main:app", "--host", "0.0.0.0", "--port", "8000"]
