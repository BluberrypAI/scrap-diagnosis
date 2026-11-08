# waste-diagnosis 엔진 이미지(포트 8030).
# 운영 필수 환경변수: APP_ENV=prod, ENGINE_SERVICE_TOKEN, DATABASE_URL, DB_CREATE_ALL=false
# DB 스키마는 컨테이너를 띄우기 전에 `alembic upgrade head`로 만든다.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv

# 의존성을 먼저 설치해 레이어 캐시를 쓴다
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY data ./data

ENV PATH="/srv/.venv/bin:$PATH" APP_ENV=prod
EXPOSE 8030
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030"]
