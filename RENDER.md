# Render + Supabase

Текущая конфигурация — бесплатный Web Service Render с внешней PostgreSQL в Supabase. Инструкция создания базы и секретов: `SUPABASE.md`.

1. Загрузите исходники проекта в отдельный GitHub-репозиторий. Включите `advisor/postgres.sql`, `render.yaml`, `requirements.lock`, `data/courses.json`. Не включайте `.env`, SQLite, browser.secret и виртуальное окружение.
2. В Render выберите **New → Blueprint** и подключите репозиторий с `render.yaml`.
3. При создании укажите `GIGACHAT_CREDENTIALS` и `DATABASE_URL`. Render сгенерирует постоянный `BROWSER_SECRET`.
4. Проверьте план **Free**, создайте сервис и дождитесь успешной сборки. Адрес `https://<имя>.onrender.com` берите из панели сервиса.
5. Проверьте чат, запись, скачивание и восстановление истории после перезапуска.

При создании вручную: Runtime Python, Build Command `pip install -r requirements.lock`, Start Command `python app.py`. Остальные переменные скопируйте из `render.yaml`. `BROWSER_SECRET` задайте случайной постоянной строкой. `PORT` Render назначает сам.

Для уже созданного сервиса добавьте DATABASE_URL в Environment и выполните deploy: `sync: false` в Blueprint не добавляет секреты при обновлении.

Файловая система бесплатного Render временная, но история и записи находятся в Supabase. Постоянный диск Render не нужен. Подтверждение TXT хранится временно — пользователь скачивает его после записи. Бесплатный сервис засыпает после 15 минут без запросов, поэтому первое открытие может быть медленным.

Доступ к GigaChat из региона Render и реальное соединение с Supabase необходимо проверить после публикации. Локальные тесты PostgreSQL не подтверждают сетевую доступность этих провайдеров.

Документация: https://render.com/docs/free , https://render.com/docs/web-services .
