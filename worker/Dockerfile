# Worker: тот же код, что в api/, плюс PrusaSlicer CLI и OpenSCAD CLI. Запускает фоновые задачи arq.
# Сборка идёт из корня репо: docker build -f worker/Dockerfile .
# bookworm закреплён: в trixie нет libwebkit2gtk-4.0 (нужен AppImage PrusaSlicer 2.8).
FROM python:3.12-slim-bookworm

ARG PRUSA_SLICER_URL=https://github.com/prusa3d/PrusaSlicer/releases/download/version_2.8.1/PrusaSlicer-2.8.1+linux-x64-GTK3-202409181354.AppImage

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Библиотеки, которые нужны AppImage PrusaSlicer даже в режиме командной строки,
# плюс OpenSCAD из репозитория Debian для параметрических редакторов (B21) и шрифты
# для text() в будущих редакторах с надписями (B24).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
        libgtk-3-0 libglu1-mesa libgl1 libegl1 libwebkit2gtk-4.0-37 libdbus-1-3 \
        openscad fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && openscad --version

# Качаем AppImage и распаковываем (FUSE в контейнере нет, поэтому --appimage-extract).
RUN curl -fsSL -o /tmp/prusa.AppImage "$PRUSA_SLICER_URL" \
    && chmod +x /tmp/prusa.AppImage \
    && cd /opt && /tmp/prusa.AppImage --appimage-extract >/dev/null \
    && mv /opt/squashfs-root /opt/prusaslicer \
    && rm /tmp/prusa.AppImage \
    && /opt/prusaslicer/AppRun --help >/dev/null

ENV PRUSA_SLICER_BIN=/opt/prusaslicer/AppRun

COPY api/pyproject.toml ./
COPY api/app ./app
RUN pip install --no-cache-dir .

# profiles/ и editors/ монтируются из корня репо (см. docker-compose: ./profiles:/srv/profiles,
# ./editors:/srv/editors). OPENSCAD_BIN по умолчанию «openscad» — он в PATH.

CMD ["arq", "app.worker.WorkerSettings"]
