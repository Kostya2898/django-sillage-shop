release: python manage.py migrate --noinput
web: gunicorn shop_project.wsgi:application --bind 0.0.0.0:$PORT --workers ${GUNICORN_WORKERS:-3} --access-logfile - --error-logfile -
