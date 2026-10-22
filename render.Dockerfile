FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/* && groupadd --system app && useradd --system --gid app app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY database ./database
COPY scripts/render_migrate.py ./render_migrate.py
COPY index.html admin.html login.html platform.html numeric-inputs.js app.js admin.js company-settings.js catalog-cover.js ingredients-list.js ingredient-picker.js product-variants.js custody.js oimo.css mobile-ux.css minimal.css auth.js api-client.js platform.js styles.css admin.css auth.css platform.css ./public/
COPY docs/program-process-flow.html ./public/docs/program-process-flow.html
COPY docs/user-guide ./public/docs/user-guide/
COPY work-time.js ./public/
COPY offline-pos.js offline-pos-core.js pos-worker.js ./public/
COPY payroll.js ./public/
COPY offline-review.js ./public/
COPY pnl.js ./public/
COPY receipt-printing.js ./public/
COPY vendor ./public/vendor/
COPY landing.html landing.css landing.js favicon.svg ./public/
COPY billing.html billing.css billing.js platform-billing.js pos-supply-photo.js ./public/
COPY account.html account.css account.js ./public/
USER app
CMD ["sh", "-c", "exec uvicorn app.render_entry:app --host 0.0.0.0 --port ${PORT:-10000}"]
