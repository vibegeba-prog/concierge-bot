#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИИ-Консьерж УК "Мир" для VK
--------------------------
Автоматические посты в группу ВКонтакте:
  • Утро (9:00) — пн, ср, пт: погода + доброе пожелание
  • Вечер (20:00) — вт, чт: закат + пожелание

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
from datetime import datetime, timedelta
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
CITY_PREP = "Санкт-Петербурге"

DISTRICT       = "Васильевский остров"
DISTRICT_PREP  = "Васильевском острове"
DISTRICT_DAT   = "Васильевскому острову"
DISTRICT_GEN   = "Васильевского острова"

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

    if group_input.isdigit():
        _vk_group_numeric_id = int(group_input)
        return _vk_group_numeric_id

    short_name = group_input.strip()
    short_name = re.sub(r'^https?://(m\.)?vk\.com/', '', short_name)
    short_name = re.sub(r'^vk\.com/', '', short_name)
    short_name = re.sub(r'^(public|club|event)', '', short_name)

    if short_name.isdigit():
        _vk_group_numeric_id = int(short_name)
        return _vk_group_numeric_id

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
# 4. ЗАКАТ (с московским временем)
# ============================================================

def get_sunset():
    """Получает время заката в СПб (по московскому времени)."""
    url = (
        f"https://api.sunrise-sunset.org/json"
        f"?lat=59.9343&lng=30.3351&formatted=0"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()["results"]
        sunset_utc = datetime.fromisoformat(data["sunset"].replace("Z", "+00:00"))
        sunset_msk = sunset_utc + timedelta(hours=3)
        return sunset_msk.strftime("%H:%M")
    except Exception as e:
        print(f"[ERROR] Не удалось получить закат: {e}")
        return None


def sunset_already_passed(sunset_time: str) -> bool:
    """Проверяет, село ли солнце раньше текущего времени (по МСК)."""
    try:
        sunset_h, sunset_m = map(int, sunset_time.split(":"))
        now_msk = datetime.utcnow() + timedelta(hours=3)
        sunset_dt = now_msk.replace(hour=sunset_h, minute=sunset_m, second=0, microsecond=0)
        return now_msk > sunset_dt
    except Exception:
        return False


# ============================================================
# 5. УТРЕННИЕ ПОСТЫ — без повторов, живой язык
# ============================================================

def generate_morning_post(weather: dict) -> str:
    """Генерирует утренний пост для ЖК Мурино."""
    temp = weather["temp"]
    feels = weather["feels_like"]
    desc = weather["description"]
    wind = weather["wind_speed"]
    emoji = weather_to_emoji(desc)

    templates = []

    if "дождь" in desc or "ливень" in desc or "гроза" in desc:
        templates = [
            f"{emoji} За окнами {DISTRICT} — дождь, +{temp}° (по ощущениям +{feels}°). Не забудьте зонт и закройте форточки перед уходом. Проходите аккуратно — лужи есть, но убираем. Хорошего дня!",
            f"{emoji} Утро на {DISTRICT_PREP} начинается с дождя, +{temp}°. Если ещё дома — захватите непромокаемую обувь. Мы на месте, следим за состоянием дворов. Берегите себя!",
        ]
    elif "снег" in desc or "снегопад" in desc:
        templates = [
            f"{emoji} Снегопад в {CITY_PREP}, +{temp}°. Дворники уже убирают подъезды и тротуары. На дорогах скользко — не спешите. Тёплого дня!",
            f"{emoji} Снежное утро на {DISTRICT_PREP}, +{temp}°. Уборка снега и посыпка песком в полном разгаре. Выходите в удобной обуви. Доброго дня!",
        ]
    elif temp >= 25:
        templates = [
            f"{emoji} Жара на {DISTRICT_PREP}: +{temp}°! Проветрите квартиру утром, пока не начался зной. Пейте больше воды и не забывайте про пожилых соседей. Лёгкого дня!",
            f"{emoji} +{temp}° — лето в разгаре. Идеальный день для вечерней прогулки по набережной, а пока — тень и прохлада. Бодрого дня!",
        ]
    elif temp >= 18:
        templates = [
            f"{emoji} +{temp}° — погода, ради которой стоит проснуться пораньше. Ветер {wind} м/с, на {DISTRICT_PREP} сейчас особенно свежо. Прекрасного дня!",
            f"{emoji} Прекрасное утро в {CITY_PREP}: +{temp}°. Окна на запад открывайте сейчас — до обеда будет прохладно и тихо. Удачного дня!",
        ]
    elif temp >= 10:
        templates = [
            f"{emoji} Прохладно, +{temp}°, {desc}. Ветер {wind} м/с — наденьте кофту. Ничего, скоро лето. Приятного дня!",
            f"{emoji} +{temp}° на {DISTRICT_PREP}. Свежо, как после дождя. Чашка кофе — и вперёд. Бодрого дня!",
        ]
    elif temp >= 0:
        templates = [
            f"{emoji} Холодное утро на {DISTRICT_PREP}: +{temp}°. Не забудьте шапку — ветер {wind} м/с. Подъезды тёплые, лифты работают. Счастливого дня!",
            f"{emoji} +{temp}° — пора доставать пальто. Тёплый кофе, любимый шарф — и вперёд. Продуктивного дня!",
        ]
    else:
        templates = [
            f"{emoji} Морозное утро, {temp}°. Проверьте, закрыты ли окна, и одевайтесь потеплее. Берегите себя!",
            f"{emoji} {temp}° — настоящий мороз. Тёплый чай и хорошее настроение — лучшая защита от холода. Согревающего дня!",
        ]

    post = random.choice(templates)
    post = post + "\n\n" + "#УКМир #ЖКХ #СанктПетербург #ВасильевскийОстров #погода"
    return post


# ============================================================
# 6. ВЕЧЕРНИЕ ПОСТЫ — без повторов
# ============================================================

def generate_evening_post(sunset_time: str | None) -> str:
    """Генерирует вечерний пост."""

    if sunset_time and sunset_already_passed(sunset_time):
        templates = [
            f"🌙 Вечер на {DISTRICT_PREP}. День прошёл — отлично. Завтра встретимся в 9:00. Сладких снов!",
            f"🌃 {DISTRICT} засыпает. Если вы ещё на работе — скорее домой, тут тепло и уютно. До завтра!",
            f"🌆 Вечер в {CITY_PREP}. Окна горят тёплым светом — приятно смотреть с улицы. Отдохните хорошо.",
            f"⭐ Небо над Невой уже тёмное. Время чая, книги или любимого сериала. Завтра новый день. Спокойной ночи!",
            f"🌙 {DISTRICT_PREP} тихий и спокойный. Желаем вам тёплого пледа и сладких снов. До встречи утром!",
        ]
        post = random.choice(templates)
        post = post + "\n\n" + "#УКМир #ЖКХ #СанктПетербург #ВасильевскийОстров #вечер"
        return post

    if sunset_time:
        templates = [
            f"Добрый вечер, {DISTRICT}! 🌅 Сегодняшний закат будет в {sunset_time}. Если окна на запад — откройте на 10 минут, это того стоит. Спокойной ночи и тёплых снов!",
            f"Вечер на {DISTRICT_PREP}… 🌇 Закат сегодня в {sunset_time}. После рабочего дня — минутка тишины у окна. Завтра будет новый день, а мы уже будем на месте. Доброй ночи!",
            f"Спокойной ночи, {DISTRICT}! 🌙 Сегодня закат в {sunset_time}. Петербургские вечера особенно красивы в это время года. Отдохните хорошо — завтра встретимся снова!",
            f"Вечерний привет с {DISTRICT_GEN}! 🌆 Закат сегодня в {sunset_time}. Прогуляйтесь по набережной — свежий воздух и красивый вид — лучшее завершение дня. До завтра!",
            f"Добрый вечер! 🌠 Сегодня закат в {sunset_time}. Если вы ещё на работе — не пропустите: небо над Невой сейчас особенное. Сладких снов, {DISTRICT}!",
        ]
    else:
        templates = [
            f"🌙 Вечер на {DISTRICT_PREP}. День прошёл — отлично. Завтра встретимся в 9:00. Сладких снов!",
            f"🌃 {DISTRICT} засыпает. Если вы ещё на работе — скорее домой, тут тепло и уютно. До завтра!",
            f"🌆 Вечер в {CITY_PREP}. Окна горят тёплым светом — приятно смотреть с улицы. Отдохните хорошо.",
        ]

    post = random.choice(templates)
    post = post + "\n\n" + "#УКМир #ЖКХ #СанктПетербург #ВасильевскийОстров #вечер"
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

    if not VK_ACCESS_TOKEN:
        print("[FATAL] Задайте VK_ACCESS_TOKEN!")
        sys.exit(1)
    if not VK_GROUP_ID:
        print("[FATAL] Задайте VK_GROUP_ID!")
        sys.exit(1)

    today = datetime.now()
    weekday = today.weekday()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Режим: {args.mode}")

    if args.mode == "morning":
        if weekday not in (0, 2, 4):
            days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
            print(f"[INFO] Сегодня {days[weekday]} — утренний пост пропускаем.")
            return

        if OPENWEATHER_KEY:
            weather = get_weather()
            if weather:
                text = generate_morning_post(weather)
            else:
                text = "Доброе утро, " + DISTRICT + "! ☀️ Желаем хорошего дня и отличного настроения. Мы уже на месте и следим за порядком во дворах.\n\n#УКМир #ЖКХ #СанктПетербург"
        else:
            print("[WARN] Нет ключа OpenWeather — пост без погоды")
            text = "Доброе утро, " + DISTRICT + "! ☀️ Желаем хорошего дня и отличного настроения. Мы уже на месте и следим за порядком во дворах.\n\n#УКМир #ЖКХ #СанктПетербург"

        success = post_to_vk(text, VK_ACCESS_TOKEN, VK_GROUP_ID)
        log_post("morning", text, success)
        return

    if args.mode == "evening":
        if weekday not in (1, 3):
            days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
            print(f"[INFO] Сегодня {days[weekday]} — вечерний пост пропускаем.")
            return

        sunset = get_sunset()
        if sunset:
            print(f"[INFO] Закат сегодня в {sunset} (МСК)")
            if sunset_already_passed(sunset):
                print("[INFO] Солнце уже село — пост без времени заката")
            else:
                print("[INFO] Солнце ещё не село — пишем с временем заката")

        text = generate_evening_post(sunset)
        success = post_to_vk(text, VK_ACCESS_TOKEN, VK_GROUP_ID)
        log_post("evening", text, success)
        return


if __name__ == "__main__":
    main()
