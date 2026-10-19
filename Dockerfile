FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY server/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/requirements.lock
COPY server/ /app/server/
COPY dist/ /app/dist/
COPY docs/ /app/docs/
COPY tools/ /app/tools/
COPY .dockerignore .env.example Dockerfile LICENSE README.md docker-compose.yml .gitignore /app/
WORKDIR /app/server
RUN python manage.py collectstatic --noinput
RUN python package_source.py
EXPOSE 8000
USER 65534:65534
CMD ["sh", "-c", "python manage.py check_deployment && python manage.py migrate --noinput && python manage.py seed_roles && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${APP_WORKERS:-1} --timeout 60"]
