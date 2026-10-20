-- Пользователь БД только для чтения — для Superset, DBeaver, pandas (B11).
-- Запускает deploy/readonly-user.sh: psql -v ro_user=… -v ro_pass=… -v db=… -v owner=… -f этот_файл
-- Повторный запуск безопасен: роль не пересоздаётся, пароль и права обновляются.

-- 1. Роль с правом входа (создаём, если ещё нет).
SELECT 'CREATE ROLE ' || quote_ident(:'ro_user') || ' LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user') \gexec

-- 2. Пароль и «ничего, кроме чтения».
ALTER ROLE :"ro_user" WITH PASSWORD :'ro_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE :"ro_user" SET default_transaction_read_only = on;

-- 3. Доступ к базе и всем таблицам схемы public — нынешним и будущим (новые миграции).
GRANT CONNECT ON DATABASE :"db" TO :"ro_user";
GRANT USAGE ON SCHEMA public TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT SELECT ON TABLES TO :"ro_user";
