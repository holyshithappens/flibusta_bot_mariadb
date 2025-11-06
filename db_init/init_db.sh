#!/bin/bash
# db_init/init_database.sh
set -e

until mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} -e "SELECT 1"; do
  sleep 5
done

mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} -e "CREATE DATABASE IF NOT EXISTS ${MYSQL_DATABASE};"
mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} -e "GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '${MYSQL_USER}'@'%'; FLUSH PRIVILEGES;"

#mkdir -p /docker-entrypoint-initdb.d/sql

# Импорт SQL файлов
for sql_file in /docker-entrypoint-initdb.d/sql/*.sql; do
    [ -f "$sql_file" ] || continue
    echo "Importing $sql_file..."
    mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} ${MYSQL_DATABASE} < "$sql_file"
done

# Импорт сжатых SQL файлов
for gz_file in /docker-entrypoint-initdb.d/sql/*.sql.gz; do
    [ -f "$gz_file" ] || continue
    echo "Importing $gz_file..."
    gunzip -c "$gz_file" | mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} ${MYSQL_DATABASE}
done

# Конвертация кодировки
CONVERSION_SCRIPT="/docker-entrypoint-initdb.d/sql/00_convert_charset.sql"
[ -f "$CONVERSION_SCRIPT" ] && mysql -h localhost -u root -p${MYSQL_ROOT_PASSWORD} ${MYSQL_DATABASE} < "$CONVERSION_SCRIPT"

echo "Database initialization completed!"