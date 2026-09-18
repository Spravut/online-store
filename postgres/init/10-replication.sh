#!/bin/sh
# Подготовка Primary к streaming replication (лабораторная №4).
#
# Скрипт выполняется автоматически при ПЕРВОМ старте контейнера с пустым
# томом. На уже развёрнутой базе те же действия делаются вручную:
#   CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '...';
#   echo 'host replication replicator all scram-sha-256' >> pg_hba.conf
#   SELECT pg_reload_conf();
set -e

REPLICATION_USER="${REPLICATION_USER:-replicator}"
REPLICATION_PASSWORD="${REPLICATION_PASSWORD:-replpass}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
    CREATE ROLE ${REPLICATION_USER} WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
EOSQL

# По умолчанию pg_hba разрешает репликацию только с localhost — реплика живёт
# в соседнем контейнере, поэтому правило нужно расширить.
echo "host replication ${REPLICATION_USER} all scram-sha-256" >> "$PGDATA/pg_hba.conf"

echo "Primary подготовлен к репликации: роль ${REPLICATION_USER} создана"
