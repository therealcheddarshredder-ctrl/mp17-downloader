FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg ca-certificates \
  && python3 -m venv /opt/venv \
  && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
  && pip install --no-cache-dir --pre "yt-dlp[default]" \
  && python -c "import yt_dlp, yt_dlp_ejs; print(yt_dlp.version.__version__)"

COPY app.py .

RUN mkdir -p /data/downloads

ENV PORT=8080 OUTPUT_DIR=/data/downloads

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port $PORT"]
