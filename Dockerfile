# Insight by Milton, web version. The host (Render) builds this from the top of the repository.
# Steps for putting it online are in web/README.md.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Libraries first, so a change to the code doesn't download them all again.
COPY web/requirements.txt web/requirements.txt
RUN pip install -r web/requirements.txt

# Only what the server uses: the shared data module, the web folder, the logo and the icon.
COPY insight_core.py icon.ico ./
COPY assets/logo.png assets/logo-dark.png assets/
COPY web web

# Run as an ordinary user. yfinance keeps its own small cookie file in this user's home folder.
RUN useradd --create-home insight
USER insight

# Render tells the server which port to use through PORT (10000 unless changed).
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
