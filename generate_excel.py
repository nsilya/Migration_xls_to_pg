import pandas as pd
from datetime import datetime, timedelta
import random

# Генерация примеров данных
def generate_sample_data(n=100):
    names = [
        "Иванов Иван Иванович",
        "Петрова Анна Сергеевна",
        "Сидоров Дмитрий Алексеевич",
        "Кузнецова Елена Владимировна",
        "Смирнов Артём Олегович"
    ]
    data = []
    for i in range(1, n + 1):
        name = random.choice(names)
        # 90% — валидные даты, 10% — невалидные (для теста ошибок)
        if random.random() < 0.9:
            birth = datetime(1950, 1, 1) + timedelta(days=random.randint(0, 25000))
            birth_str = birth.strftime("%Y-%m-%d")
        else:
            # Невалидные даты
            invalid_dates = ["1990-02-30", "2025-13-01", "abcd", "", "31-12-2000"]
            birth_str = random.choice(invalid_dates)
        data.append({
            "id": i,
            "full_name": name,
            "birth_date": birth_str,
            "processed": False
        })
    return data

# Создание DataFrame и запись в Excel
df = pd.DataFrame(generate_sample_data(100))
df.to_excel("source_data.xlsx", index=False, sheet_name="Sheet1")
print("✅ Файл source_data.xlsx успешно создан с 100 записями (включая ошибки).")