import pandas as pd
import psycopg2
from psycopg2 import OperationalError, Error as Psycopg2Error
from psycopg2.extras import execute_values
import logging
import sys
from dateutil.parser import parse
from datetime import datetime, date
import time
import uuid
import os
import json

# =============== НАСТРОЙКИ ===============
EXCEL_FILE = 'source_data.xlsx'
SHEET_NAME = 'Sheet1'
STATE_FILE = 'migration_state.json'
DB_CONFIG = {
    'host': 'localhost',
    'port': '5433',
    'database': 'migration_db',
    'user': 'migrator',
    'password': 'securepass123'
}

# =============== ЛОГИРОВАНИЕ ===============
logging.basicConfig(
    filename='migration.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - run_id=%(run_id)s - %(message)s',
    encoding='utf-8'
)


class RunIdFilter(logging.Filter):
    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id

    def filter(self, record):
        record.run_id = self.run_id
        return True


# =============== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===============
def parse_and_validate_date(date_str):
    """
    Пытается распарсить дату и валидирует её.
    Возвращает валидный date или None если дата некорректна.
    """
    if pd.isna(date_str):
        return None

    # Преобразуем в строку для обработки
    date_str_clean = str(date_str).strip()

    # Пропускаем пустые строки
    if not date_str_clean:
        return None

    try:
        # Пробуем распарсить
        parsed_date = parse(date_str_clean, dayfirst=True, yearfirst=True)
        date_obj = parsed_date.date()

        # Дополнительная валидация
        # 1. Проверка на реалистичные годы
        if date_obj.year < 1900 or date_obj.year > datetime.now().year + 1:
            return None

        # 2. Проверка на корректность даты (особенно для февраля 29)
        try:
            # Пробуем создать date объект снова для проверки
            date(date_obj.year, date_obj.month, date_obj.day)
        except ValueError:
            return None

        return date_obj
    except (ValueError, TypeError, OverflowError) as e:
        # Ловим все возможные ошибки парсинга
        return None


def validate_full_name(name_str):
    """Валидирует ФИО."""
    if pd.isna(name_str):
        return ''

    name = str(name_str).strip()
    # Базовая проверка: не должно быть пустым или состоять только из пробелов
    if not name:
        return ''

    # Убираем лишние пробелы
    return ' '.join(name.split())


def connect_db(max_attempts=10, delay=2):
    """Подключается к PostgreSQL с повторными попытками."""
    for attempt in range(max_attempts):
        try:
            return psycopg2.connect(**DB_CONFIG)
        except OperationalError as e:
            logging.error(f"Не удалось подключиться к PostgreSQL (попытка {attempt + 1}): {e}")
            time.sleep(delay)
    logging.critical("Превышено максимальное число попыток подключения к PostgreSQL")
    sys.exit(1)


def load_or_create_state():
    """Загружает состояние обработки из файла или создаёт пустое."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Ошибка чтения файла состояния: {e}. Создаём новый.")
    return set()


def save_state(processed_ids):
    """Сохраняет множество обработанных ID."""
    try:
        # Конвертируем numpy.int64 в обычный int
        ids_list = [int(id_val) for id_val in processed_ids]
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(ids_list, f)
    except IOError as e:
        logging.error(f"Ошибка сохранения состояния: {e}")


def create_target_table(conn):
    """Создаёт целевую таблицу, если не существует."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migrated_data (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                birth_date DATE NOT NULL, -- <-- ТЕПЕРЬ NOT NULL
                processed_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT valid_date_range CHECK (
                    birth_date >= '1900-01-01' AND birth_date <= CURRENT_DATE + INTERVAL '1 year'
                )
            )
        """)
        conn.commit()


# =============== ОСНОВНАЯ ЛОГИКА ===============
def main():
    # Генерируем уникальный ID запуска для трассировки
    run_id = str(uuid.uuid4())[:8]
    logging.getLogger().addFilter(RunIdFilter(run_id))
    logging.info("=== ЗАПУСК МИГРАЦИИ ===")

    print(f" Запуск миграции (run_id={run_id})...")

    # 1. Загрузка и предварительная валидация данных
    try:
        df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, dtype={'id': 'Int64'})
        logging.info(f"Загружено {len(df)} строк из {EXCEL_FILE}")
        print(f"✅ Загружено {len(df)} строк")
    except (FileNotFoundError, ValueError, Exception) as e:
        logging.critical(f"Ошибка чтения Excel: {e}")
        print(f"❌ Ошибка чтения файла Excel: {e}")
        return

    # 2. Дедупликация по ID
    initial_count = len(df)
    df = df.drop_duplicates(subset=['id'], keep='first')
    if len(df) < initial_count:
        logging.info(f"Удалено {initial_count - len(df)} дублей по id")
        print(f" Удалено {initial_count - len(df)} дублей")

    # 3. Загрузка состояния
    processed_ids = load_or_create_state()
    logging.info(f"Уже обработано: {len(processed_ids)} записей")

    # 4. Фильтрация уже обработанных строк
    df_new = df[~df['id'].isin(processed_ids)].copy()
    logging.info(f"Новых строк для обработки: {len(df_new)}")

    if df_new.empty:
        print("✅ Нет новых строк для обработки.")
        return

    # 5. Пакетная валидация данных в Pandas
    df_new['full_name_valid'] = df_new['full_name'].apply(validate_full_name)
    df_new['birth_date_parsed'] = df_new['birth_date'].apply(parse_and_validate_date)

    # Фильтрация по валидным строкам
    df_valid = df_new[
        (df_new['full_name_valid'] != '') &
        (df_new['birth_date_parsed'].notna())
    ].copy()

    # Подсчёт ошибок
    invalid_count = len(df_new) - len(df_valid)
    logging.info(f"Отфильтровано {invalid_count} невалидных строк")

    if df_valid.empty:
        print(f"❌ Нет валидных строк для вставки после фильтрации.")
        return

    # 6. Подготовка данных для вставки
    records_to_insert = [
        (int(row['id']), row['full_name_valid'], row['birth_date_parsed'])
        for _, row in df_valid.iterrows()
    ]

    # 7. Подключение к БД
    conn = connect_db()
    create_target_table(conn)

    # 8. Пакетная вставка
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO migrated_data (id, full_name, birth_date)
                VALUES %s
                ON CONFLICT (id) DO NOTHING
                """,
                records_to_insert,
                template=None,
                page_size=100  # Пакеты по 100 строк
            )
            inserted_count = cur.rowcount
        conn.commit()
        logging.info(f"Вставлено {inserted_count} записей")
    except Psycopg2Error as e:
        logging.error(f"Ошибка вставки в БД: {e}")
        print(f"❌ Ошибка вставки: {e}")
        conn.rollback()
        conn.close()
        return

    # 9. Обновление состояния
    new_processed_ids = set(df_valid['id'].values)
    processed_ids.update(new_processed_ids)
    save_state(processed_ids)

    conn.close()

    # 10. Отчёт
    logging.info(f"Миграция завершена: вставлено={inserted_count}, ошибок={invalid_count}")
    print(f"\n{'=' * 50}")
    print(f"ОТЧЁТ О МИГРАЦИИ (run_id={run_id})")
    print(f"{'=' * 50}")
    print(f"✅ Успешно вставлено: {inserted_count} записей")
    print(f"❌ Ошибок (невалидные): {invalid_count}")
    print(f"📊 Всего строк в Excel: {len(df)}")


if __name__ == "__main__":
    main()