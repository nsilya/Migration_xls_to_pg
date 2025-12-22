import pandas as pd
import psycopg2
from psycopg2 import OperationalError, Error as Psycopg2Error
import logging
import sys
from dateutil.parser import parse
import time

# Настройка логирования
logging.basicConfig(
    filename='migration_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# Конфигурация PostgreSQL
DB_CONFIG = {
    'host': 'localhost',
    'port': '5432',
    'database': 'migration_db',
    'user': 'migrator',
    'password': 'securepass123'
}

EXCEL_FILE = 'source_data.xlsx'
SHEET_NAME = 'Sheet1'


def is_valid_date(date_str):
    """Проверяет корректность даты."""
    if pd.isna(date_str):
        return False
    try:
        parse(str(date_str))
        return True
    except (ValueError, TypeError):
        return False


def connect_db():
    """Подключается к PostgreSQL с повторными попытками."""
    for attempt in range(10):
        try:
            return psycopg2.connect(**DB_CONFIG)
        except OperationalError as e:
            logging.error(f"Не удалось подключиться к PostgreSQL (попытка {attempt + 1}): {e}")
            time.sleep(2)
    logging.critical("Превышено максимальное число попыток подключения к PostgreSQL")
    sys.exit(1)


def ensure_processed_column(df):
    """Гарантирует наличие колонки 'processed'."""
    if 'processed' not in df.columns:
        df['processed'] = False
    return df


def create_target_table(conn):
    """Создаёт таблицу в PostgreSQL, если она не существует."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migrated_data (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                birth_date DATE,
                processed_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()


def main():
    print(" Запуск RPA-бота миграции по методу Баданова и Тугой (2025)...")

    # Чтение Excel
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, dtype={'id': 'Int64'})
        df = ensure_processed_column(df)
        print(f"✅ Загружено {len(df)} строк из {EXCEL_FILE}")
    except (FileNotFoundError, ValueError) as e:
        logging.error(f"Ошибка чтения Excel: {e}")
        return

    # Подключение к БД и создание таблицы
    conn = connect_db()
    create_target_table(conn)

    total = 0
    errors = 0

    for idx, row in df.iterrows():
        if row.get('processed') is True:
            continue

        record_id = row['id']
        if pd.isna(record_id):
            logging.error("Пропущен ID (пустая строка)")
            errors += 1
            continue

        full_name = str(row.get('full_name', '')) if not pd.isna(row.get('full_name')) else ''
        birth_date_raw = row.get('birth_date')

        # Валидация данных (оценка совместимости)
        if not is_valid_date(birth_date_raw):
            logging.error(f"Некорректная дата для ID {record_id}: '{birth_date_raw}'")
            errors += 1
            continue

        # Трансформация даты
        try:
            birth_date = parse(str(birth_date_raw)).date()
        except (ValueError, TypeError):
            logging.error(f"Не удалось распарсить дату для ID {record_id}: '{birth_date_raw}'")
            errors += 1
            continue

        # Запись в промежуточное хранилище
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO migrated_data (id, full_name, birth_date) VALUES (%s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING",
                    (int(record_id), full_name, birth_date)
                )
                conn.commit()
            total += 1
            df.at[idx, 'processed'] = True
        except Psycopg2Error as e:
            logging.error(f"Ошибка PostgreSQL при записи ID {record_id}: {e}")
            errors += 1

    # Сохранение Excel с маркировкой
    df.to_excel(EXCEL_FILE, sheet_name=SHEET_NAME, index=False)
    conn.close()

    print(f"✅ Успешно обработано: {total} записей")
    if errors:
        print(f" Ошибок: {errors} — см. migration_errors.log")
    else:
        print("✅ Все записи обработаны без ошибок")


if __name__ == "__main__":
    main()