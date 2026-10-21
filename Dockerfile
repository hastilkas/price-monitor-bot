FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # Google Chrome со всеми системными библиотеками + Xvfb для режима BROWSER_HEADLESS=false
    && patchright install --with-deps chrome \
    && apt-get update && apt-get install -y --no-install-recommends xvfb xauth fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY bot ./bot

RUN useradd --create-home botuser && mkdir -p /app/data && chown botuser /app/data
USER botuser

# С окном (BROWSER_HEADLESS=false) браузер запускается на виртуальном дисплее
CMD ["sh", "-c", "if [ \"$BROWSER_HEADLESS\" = \"false\" ]; then exec xvfb-run -a python -m bot; else exec python -m bot; fi"]
