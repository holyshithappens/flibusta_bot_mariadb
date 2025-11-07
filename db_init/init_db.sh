#!/bin/bash
set -e

echo "Starting custom database initialization..."

# Ждем готовности MariaDB
until mysql -h localhost -u root -p$MYSQL_ROOT_PASSWORD -e "SELECT 1"; do
  echo "Waiting for MariaDB..."
  sleep 5
done

# Создаем БД и пользователя
mysql -h localhost -u root -p$MYSQL_ROOT_PASSWORD -e "
CREATE DATABASE IF NOT EXISTS $MYSQL_DATABASE;
GRANT ALL PRIVILEGES ON $MYSQL_DATABASE.* TO '$MYSQL_USER'@'%';
FLUSH PRIVILEGES;
"

# Импортируем SQL.gz файлы в правильном порядке
for gz_file in /db_init/sql/*.sql.gz; do
    [ -f "$gz_file" ] || continue
    echo "Importing $gz_file..."
    gunzip -c "$gz_file" | mysql -h localhost -u root -p$MYSQL_ROOT_PASSWORD $MYSQL_DATABASE
done

# Выполняем конвертацию кодировки
echo "Converting charset to utf8mb4..."
mysql -h localhost -u root -p$MYSQL_ROOT_PASSWORD $MYSQL_DATABASE < /db_init/99_convert_charset.sql

echo "Database initialization completed successfully!"