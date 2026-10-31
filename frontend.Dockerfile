FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html admin.html login.html platform.html numeric-inputs.js app.js admin.js company-settings.js catalog-cover.js catalog-units.js ingredients-list.js ingredient-picker.js recipe-variants.js product-variants.js custody.js oimo.css mobile-ux.css ui-theme.css minimal.css auth.js api-client.js password-visibility.js platform.js styles.css admin.css auth.css platform.css /usr/share/nginx/html/
COPY tests /usr/share/nginx/html/tests
COPY work-time.js /usr/share/nginx/html/
COPY offline-pos.js offline-pos-core.js pos-worker.js pos-pwa.js pos.webmanifest /usr/share/nginx/html/
COPY payroll.js /usr/share/nginx/html/
COPY offline-review.js /usr/share/nginx/html/
COPY pnl.js /usr/share/nginx/html/
COPY receipt-printing.js /usr/share/nginx/html/
COPY vendor /usr/share/nginx/html/vendor/
COPY landing.html landing.css landing.js favicon.svg oimo-logo.png oimo-mark.svg brand.css /usr/share/nginx/html/
COPY billing.html billing.css billing.js platform-billing.js pos-supply-photo.js /usr/share/nginx/html/
COPY account.html account.css account.js /usr/share/nginx/html/
COPY docs/program-process-flow.html /usr/share/nginx/html/docs/program-process-flow.html
COPY docs/user-guide /usr/share/nginx/html/docs/user-guide/

EXPOSE 80
