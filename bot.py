import asyncio
import logging
import os
import sys
import re
import io

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# ==================== НАСТРОЙКИ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or "твой_токен_телеграм"
AMO_SUBDOMAIN = "demon51000"
AMO_TOKEN = os.getenv("AMO_ACCESS_TOKEN") or "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6IjE0NzUzMWJlMjBhN2NkZDRiNDJjNGEzNDQwNzc5ZDY4ZDAyOWI3ZmQ2OTZiZDA3ZjhlNGIwYzM5MWQzOTU0YmJkMzFkMGI5OTBiYjdiM2FmIn0.eyJhdWQiOiJjNmVhZTYzZS00NGQyLTQzMDUtOTBhYy1iMDcwNmI4MzkxZDUiLCJqdGkiOiIxNDc1MzFiZTIwYTdjZGQ0YjQyYzRhMzQ0MDc3OWQ2OGQwMjliN2ZkNjk2YmQwN2Y4ZTRiMGMzOTFkMzk1NGJiZDMxZDBiOTkwYmI3YjNhZiIsImlhdCI6MTc3MzE1Mjg4MCwibmJmIjoxNzczMTUyODgwLCJleHAiOjE5MzA4NjcyMDAsInN1YiI6IjEzNDAxMjIyIiwiZ3JhbnRfdHlwZSI6IiIsImFjY291bnRfaWQiOjMyODU0ODY2LCJiYXNlX2RvbWFpbiI6ImFtb2NybS5ydSIsInZlcnNpb24iOjIsInNjb3BlcyI6WyJwdXNoX25vdGlmaWNhdGlvbnMiLCJmaWxlcyIsImNybSIsImZpbGVzX2RlbGV0ZSIsIm5vdGlmaWNhdGlvbnMiXSwiaGFzaF91dWlkIjoiOGFlNmExNDctYWE0Zi00MjY0LTljYmYtNTVlZjYxNjllOTFjIiwiYXBpX2RvbWFpbiI6ImFwaS1iLmFtb2NybS5ydSJ9.ps68EjCRyO1ydy6OrTfiPn0mGvbmr-0Fyls-Z4-WOfiKIpMqGnnV8toEnO5pgIvnhuat_rgM4mOmPXS9Kx_rQCF8cw3o0heoHAUgSzpp4eThhszNrpZ9E0Fte5hMiw6prJcmFgjEqmG6h8LS4Pz-S0hH9T_XK6C9siJSyz66z5K_7WMdlSN_vQ2jAKRDuanUV6ecYIi3tuXsF74OaTp3mKjxUg7GaCfl3zk1kfm9CrHiTvOAXOTHEmAQuZmM97swjZVop2NN6WzKidRB2p0JSX9PaMIepe5lKuYJaVwtKRw0bYV_KEI6eQcsrwCnoOBLb94YXnKyWjVEMgQVp1gmCQ"  # ← твой токен

AMO_PIPELINE_ID = 10684430  # твоя воронка "ТЕХОБСЛУЖИВАНИЕ"
AMO_STATUS_ID = 10684431    # ← "Заявка" (попробуй, если не туда — подправим на 10684432 или реальный)

if not TELEGRAM_TOKEN or not AMO_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

AMO_API_BASE = f"https://{AMO_SUBDOMAIN}.amocrm.ru/api/v4"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    phone = State()
    menu = State()
    serial_input = State()
    issue_description = State()
    ask_attach = State()
    wait_attach = State()


# Клавиатуры (оставь как в твоём боте)
start_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="СТАРТ", request_contact=True)]], resize_keyboard=True)
main_menu_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Обслуживание")]], resize_keyboard=True)
back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад в меню")]], resize_keyboard=True)
confirm_issue_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Создать заявку")], [KeyboardButton(text="Назад в меню")]], resize_keyboard=True)
attach_choice_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да, прикрепить фото/видео")], [KeyboardButton(text="Нет, создать заявку без файлов")]], resize_keyboard=True)
done_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Готово, отправить заявку")]], resize_keyboard=True)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r'[^0-9+]', '', raw.strip())
    if digits.startswith('8'):
        digits = '+7' + digits[1:]
    if not digits.startswith('+'):
        digits = '+7' + digits
    return digits


async def get_amo_contact_by_phone(phone: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    params = {"query": phone}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{AMO_API_BASE}/contacts", headers=headers, params=params) as resp:
            if resp.status != 200:
                logging.error(f"Amo /contacts ошибка: {resp.status} - {await resp.text()}")
                return None
            data = await resp.json()
            contacts = data.get('_embedded', {}).get('contacts', [])
            if contacts:
                return contacts[0]
            return None


async def create_amo_lead(contact_id: int, description: str, equipment_info: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": "Заявка из Telegram-бота",
        "pipeline_id": AMO_PIPELINE_ID,
        "status_id": AMO_STATUS_ID,
        "contacts": [{"id": contact_id}],
        "custom_fields_values": [
            {"field_code": "DESCRIPTION", "values": [{"value": description}]},
            {"field_code": "SERIAL_NUMBER", "values": [{"value": equipment_info}]}
        ]
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/leads", json=payload, headers=headers) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                lead_id = data['_embedded']['leads'][0]['id']
                logging.info(f"Создана сделка: {lead_id}")
                return lead_id
            else:
                text = await resp.text()
                logging.error(f"Amo создание сделки ошибка: {resp.status} - {text}")
                return None


async def upload_file_to_amo_lead(lead_id: int, file_bytes: bytes, filename: str):
    form = aiohttp.FormData()
    form.add_field("file", file_bytes, filename=filename, content_type="image/jpeg")

    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        url = f"{AMO_API_BASE}/leads/{lead_id}/files"
        async with session.post(url, data=form, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"Amo загрузка файла: {resp.status} - {text}")
            return resp.status in (200, 201)


# ... (остальные функции бота — process_phone, process_serial, create_and_finish_issue и т.д. — оставь как в твоём текущем боте)

# В create_and_finish_issue замени вызовы OkDesk на новые функции:
# lead_id = await create_amo_lead(contact_id, description, equipment_info)
# success = await upload_file_to_amo_lead(lead_id, content, filename)

async def main():
    print("KubonSupportBot запущен (aiogram 3.x + AmoCRM)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
