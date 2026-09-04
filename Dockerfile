FROM python:3.13-slim-bookworm AS build

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir --prefix=/install .


FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /install /usr/local

USER 10001:10001

EXPOSE 3483/tcp 3483/udp 9000/tcp

CMD ["python", "-m", "squeezebox_bootstrap", "--config", "/config/config.json"]
