#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИИ-Консьерж УК "Мир" для VK
--------------------------
Автоматические посты в группу ВКонтакте:
  • Утро (9:00) — каждый будний день: погода + доброе пожелание
  • Вечер (20:00) — понедельник, среда, пятница: закат + спокойной ночи

Запуск:
  python concierge.py --mode morning
  python concierge.py --mode evening

Переменные окружения:
  VK_ACCESS_TOKEN — токен сообщества VK
  VK_GROUP_ID     — ID или короткое имя группы
  OPENWEATHER_KEY — ключ OpenWeatherMap
"""

import os
import sys
import json
import random
import argparse
import re
from datetime import datetime
from pathlib import Path

import requests

# ============================================================
# 1. НАСТРОЙКИ
# ============================================================

VK_ACCESS_TOKEN = os.environ.get("VK_ACCESS_TOKEN", "")
VK_GROUP_ID     = os.environ.get("VK_GROUP_ID", "")
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "")

CITY_NAME = "Saint Petersburg"
CITY_RU   = "Санкт-Петербург"
DISTRICT  = "Васильевский остров"

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FILE = DATA_DIR / "posts_log.jsonl"

# ============================================================
# 2. VK API: ОПРЕДЕЛЕНИЕ ЧИСЛОВОГО ID ГРУППЫ
# ============================================================

_vk_group_numeric_id = None

def resolve_group_id(token: str, group_input: str) -> int:
    """
    Превращает любой формат ID группы в числовой:
      - public102907155 → 102907155
      - club12345 → 12345
      - uc_mir → резолв через API
      - 12345 → 12345
      - https://vk.com/ucmir → ucmir → резолв через API
    """
    global _vk_group_numeric_id
    if _vk_group_numeric_id is not None:
        return _vk_group_numeric_id

    # Если уже чистое число
    if group_input.isdigit():
        _vk_group_numeric_id = int(group_input)
        return _vk_group_numeric_id

    # Извлекаем короткое имя из разных форматов
    short_name = group_input.strip()

    # Убираем https://vk.com/ или vk.com/
    short_name = re.sub(r'^https?://(m\.)?vk\.com/', '', short_name)
    short_name = re.sub(r'^vk\.com/', '', short_name)

    # Убираем public / club / event префиксы
    short_name = re.sub(r'^(public|club|event)', '', short_name)

    # Если после очистки остались только цифры
    if short_name.isdigit():
        _vk_group_numeric_id = int(short_name)
        return _vk_group_numeric_id

    # Иначе — резолвим через API
    url = "https://api.vk.com/method/groups.getById"
    params = {
        "group_id": short_name,
        "access_token": token,
        "v": "5.199",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            print(f"[ERROR] Не удалось определить ID группы: {data['error']}")
            sys.exit(1)
        gid = data["response"]["groups"][0]["id"]
        _vk_group_numeric_id = gid
        print(f"[OK] Группа '{short_name}' → ID: {gid}")
        return gid
    except Exception as e:
        print(f"[ERROR] Ошибка при определении ID группы: {e}")
        sys.exit(1)


# ============================================================
# 3. ПОГОДА
# ============================================================

def get_weather():
    """Получает текущую погоду в СПб через OpenWeatherMap."""
    url = (
        f"https://api.openweathermap.org/data/2.5/weather"
        f"?q={CITY_NAME}&appid={OPENWEATHER_KEY}&units=metric&lang=ru"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            "temp": round(data["main"]["temp"]),
            "feels_like": round(data["main"]["feels_like"]),
            "description": data["weather"][0]["description"],
            "wind_speed": round(data["wind"]["speed"]),
            "humidity": data["main"]["humidity"],
            "pressure": data["main"]["pressure"],
            "icon": data["weather"][0]["icon"],
        }
    except Exception as e:
        print(f"[ERROR] Не удалось получить погоду: {e}")
        return None


def weather_to_emoji(desc: str) -> str:
    """Превращает описание погоды в эмодзи."""
    desc = desc.lower()
    mapping = {
        "ясно": "☀️", "солнечно": "☀️", "clear": "☀️",
        "облачно": "☁️", "пасмурно": "☁️", "clouds": "☁️",
        "дождь": "🌧️", "ливень": "🌧️", "rain": "🌧️",
        "гроза": "⛈️", "thunderstorm": "⛈️",
        "снег": "❄️", "снегопад": "❄️", "snow": "❄️",
        "туман": "🌫️", "mist": "🌫️", "fog": "🌫️",
        "малооблачно": "🌤️", "переменная облачность": "⛅",
    }
    for key, emoji in mapping.items():
        if key in desc:
            return emoji
    return "🌡️"


# ============================================================
# 4. ЗАКАТ
# ============================================================

def get_sunset():
    """Получает время заката в СПб."""
    url = (
        f"https://api.sunrise-sunset.org/json"
        f"?lat=59.9343&lng=30.3351&formatted=0"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()["results"]
        sunset_utc = datetime.fromisoformat(data["sunset"].replace("Z", "+00:00"))
        sunset_local = sunset_utc.astimezone()
        return sunset_local.strftime("%H:%M")
    except Exception as e:
        print(f"[ERROR] Не удалось получить закат: {e}")
        return None


# ============================================================
# 5. ГЕНЕРАТОР УТРЕННИХ ПОСТОВ
# ============================================================

def generate_morning_post(weather: dict) -> str:
    """Генерирует утренний пост на основе погоды."""
    temp = weather["temp"]
    feels = weather["feels_like"]
    desc = weather["description"]
    wind = weather["wind_speed"]
    emoji = weather_to_emoji(desc)

    templates = []

    if "дождь" in desc or "ливень" in desc or "гроза" in desc:
        templates = [
            f"Доброе утро, {DISTRICT}! {emoji} Сегодня дождливо, +{temp}° (ощущается как +{feels}°). Не забудьте зонт и закройте форточки перед уходом. Наши дворники следят за лужами — проходите аккуратно. Хорошего дня!",
            f"Утро на {DISTRICT} начинается с дождя {emoji} +{temp}°. Если вы ещё дома — захватите непромокаемую обувь. Мы уже на месте и следим за состоянием дворов. Берегите себя!",
        ]
    elif "снег" in desc or "снегопад" in desc:
        templates = [
            f"Доброе утро! {emoji} Сегодня снег, +{temp}°. Наши дворники уже убирают подъезды и тротуары. Будьте осторожны на дорогах — скользко. Тёплого вам дня!",
            f"Снежное утро на {DISTRICT} {emoji} +{temp}°. Мы в режиме повышенной готовности: уборка снега, посыпка песком. Выходите из дома в удобной обуви. Доброго дня!",
        ]
    elif temp >= 25:
        templates = [
            f"Доброе утро! {emoji} Сегодня жарко — +{temp}°! Отличный день, чтобы проветрить квартиру утром, пока не началась дневная жара. Пейте больше воды и не забывайте про пожилых соседей. Хорошего дня!",
            f"Жаркое утро на {DISTRICT} {emoji} +{temp}°. Если у вас есть балкон — откройте его на проветривание сейчас, до полудня. Берегите себя от перегрева!",
        ]
    elif temp >= 18:
        templates = [
            f"Доброе утро, {DISTRICT}! {emoji} Сегодня +{temp}° — идеальная погода для прогулки по набережной. Ветер {wind} м/с, лёгкий. Хорошего дня и хорошего настроения!",
            f"Прекрасное утро! {emoji} +{temp}° — такая погода, ради которой стоит проснуться пораньше. Прогуляйтесь по {DISTRICT} перед работой. Удачного дня!",
        ]
    elif temp >= 10:
        templates = [
            f"Доброе утро! {emoji} Сегодня +{temp}°, {desc}. Прохладно, но комфортно. Наденьте что-то тёплое — ветер {wind} м/с. Хорошего дня!",
            f"Утро на {DISTRICT} {emoji} +{temp}°. Прохладно, но свежо. Отличная погода для утренней прогулки с чашкой кофе. Бодрого дня!",
        ]
    elif temp >= 0:
        templates = [
            f"Доброе утро! {emoji} Сегодня +{temp}° — прохладно. Не забудьте тёплую куртку, ветер {wind} м/с. Мы следим за состоянием подъездов — чтобы было сухо и чисто. Хорошего дня!",
            f"Прохладное утро на {DISTRICT} {emoji} +{temp}°. Тёплый кофе, тёплая куртка — и вперёд. Мы уже на месте, проверяем состояние дворов. Удачи!",
        ]
    else:
        templates = [
            f"Доброе утро! {emoji} Сегодня морозно — {temp}°. Проверьте, закрыты ли окна, и не забудьте перчатки. Наши дворники работают в усиленном режиме. Берегите себя!",
            f"Морозное утро на {DISTRICT} {emoji} {temp}°. Тёплый чай, шарф и хорошее настроение — лучшая защита от холода. Мы следим за чистотой и безопасностью. Доброго дня!",
        ]

    post = random.choice(templates)
    post += "\n\n#УКМир #ЖКХ #СанктПетербург #ВасильевскийОстров #погода"
    return post


# ============================================================
# 6. ГЕНЕРАТОР ВЕЧЕРНИХ ПОСТОВ
# ============================================================

def generate_evening_post(sunset_time: str) -> str:
    """Генерирует вечерний пост."""
    templates = [
        f"Добрый вечер, {DISTRICT}! 🌅 Сегодняшний закат будет в {sunset_time}. Если у вас окна на запад — откройте на 10 минут, это того стоит. Спокойной ночи и тёплых снов!",
        f"Вечер на {DISTRICT}… 🌇 Закат сегодня в {sunset_time}. После рабочего дня — минутка тишины у окна. Завтра будет новый день, а мы уже будем на месте. Доброй ночи!",
        f"Спокойной ночи, {DISTRICT}! 🌙 Сегодня закат в {sunset_time}. Петербургские вечера особенно красивы в это время года. Отдохните хорошо — завтра встретимся снова!",
        f"Вечерний привет с {DISTRICT}! 🌆 Закат сегодня в {sunset_time}. Прогуляйтесь по набережной — свежий воздух и красивый вид — лучшее завершение дня. Спокойной ночи!",
        f"Добрый вечер! 🌠 Сегодня закат в {sunset_time}. Если вы ещё на работе — не пропустите: небо над Невой сейчас особенное. Спокойной ночи, {DISTRICT}!",
    ]
    post = random.choice(templates)
    post += "\n\n#УКМир #ЖКХ #СанктПетербург #ВасильевскийОстров #вечер"
    return post


# ============================================================
# 7. VK API
# ============================================================

def post_to_vk(text: str, token: str, group_input: str) -> bool:
    """Публикует пост на стену группы VK."""
    gid = resolve_group_id(token, group_input)

    url = "https://api.vk.com/method/wall.post"
    payload = {
        "owner_id": f"-{gid}",
        "from_group": 1,
        "message": text,
        "access_token": token,
        "v": "5.199",
    }
    try:
        r = requests.post(url, data=payload, timeout=20)
        r.raise_for_status()
        result = r.json()
        if "error" in result:
            print(f"[ERROR] VK API ошибка: {result['error']}")
            return False
        post_id = result["response"]["post_id"]
        print(f"[OK] Пост опубликован: https://vk.com/wall-{gid}_{post_id}")
        return True
    except Exception as e:
        print(f"[ERROR] Не удалось опубликовать: {e}")
        return False


# ============================================================
# 8. ЛОГИРОВАНИЕ
# ============================================================

def log_post(mode: str, text: str, success: bool):
    """Записывает информацию о посте в лог."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "text_preview": text[:120],
        "success": success,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================
# 9. ГЛАВНАЯ ЛОГИКА
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="ИИ-Консьерж УК Мир")
    parser.add_argument("--mode", choices=["morning", "evening"], required=True,
                        help="Режим: morning (9:00) или evening (20:00)")
    args = parser.parse_args()

    # Проверка настроек
    if not VK_ACCESS_TOKEN:
        print("[FATAL] Задайте VK_ACCESS_TOKEN!")
        sys.exit(1)
    if not VK_GROUP_ID:
        print("[FATAL] Задайте VK_GROUP_ID!")
        sys.exit(1)

    today = datetime.now()
    weekday = today.weekday()  # 0=пн, 1=вт, ..., 6=вс
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Режим: {args.mode}")

    # --- УТРО ---
    if args.mode == "morning":
        if OPENWEATHER_KEY:
            weather = get_weather()
            if weather:
                text = generate_morning_post(weather)
            else:
                text = f"Доброе утро, {DISTRICT}! ☀️ Желаем хорошего дня и отличного настроения. Мы уже на месте и следим за порядком во дворах.\n\n#УКМир #ЖКХ #СанктПетербург"
        else:
            print("[WARN] Нет ключа OpenWeather — пост без погоды")
            text = f"Доброе утро, {DISTRICT}! ☀️ Желаем хорошего дня и отличного настроения. Мы уже на месте и следим за порядком во дворах.\n\n#УКМир #ЖКХ #СанктПетербург"

        success = post_to_vk(text, VK_ACCESS_TOKEN, VK_GROUP_ID)
        log_post("morning", text, success)
        return

    # --- ВЕЧЕР ---
    if args.mode == "evening":
        # Постим только в пн (0), ср (2), пт (4)
        if weekday not in (0, 2, 4):
            print(f"[INFO] Сегодня {'ПНВТСРЧТПТВС'[weekday*2:weekday*2+2]} — вечерний пост пропускаем.")
            return

        sunset = get_sunset()
        if sunset:
            text = generate_evening_post(sunset)
        else:
            text = f"Добрый вечер, {DISTRICT}! 🌙 Желаем спокойной ночи и тёплых снов. Завтра встретимся снова!\n\n#УКМир #ЖКХ #СанктПетербург #вечер"

        success = post_to_vk(text, VK_ACCESS_TOKEN, VK_GROUP_ID)
        log_post("evening", text, success)
        return


if __name__ == "__main__":
    main()
