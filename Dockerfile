FROM python:3.12-slim
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl xz-utils && rm -rf /var/lib/apt/lists/*
# YouTube extraction currently needs a supported JavaScript runtime.
RUN ARCH=$(case "$TARGETARCH" in amd64|x86_64) echo x64;; arm64|aarch64) echo arm64;; *) echo x64;; esac) \
  && curl -fsSL "https://nodejs.org/dist/latest-v22.x/node-v22.20.0-linux-${ARCH}.tar.xz" -o /tmp/node.tar.xz \
  && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
  && rm /tmp/node.tar.xz
# Use yt-dlp nightly for the newest YouTube extractor fixes.
RUN curl -fsSL https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp_linux -o /usr/local/bin/yt-dlp \
  && chmod 0755 /usr/local/bin/yt-dlp
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN mkdir -p /data/downloads
ENV PORT=8080 OUTPUT_DIR=/data/downloads
EXPOSE 8080
CMD uvicorn app:app --host 0.0.0.0 --port 8080