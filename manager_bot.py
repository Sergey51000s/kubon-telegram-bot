import asyncio
import logging
import os
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# === Настройки ===
TELEGRAM_TOKEN = "8773186067:AAFEtMtaKtkTTGH6HLNmWEzdXHlFKYh4g3g"  # Твой токен менеджера
OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN") or "beb8b36c5dad4163d92be7e8cec186e3acd20d56"
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN") or "teken2026"

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class ManagerForm(StatesGroup):
    fio = State()
    phone = State()
    telegram_username = State()
    telegram_user_id = State()
    robot_name = State()
    serial_number = State()
    start_date = State()

@dp.message(CommandStart())
async def manager_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Здравствуйте, менеджер! Укажите ФИО клиента:")
    await state.set_state(ManagerForm.fio)

@dp.message(ManagerForm.fio)
async def process_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text.strip())
    await message.answer("Телефон клиента (+7...):")
    await state.set_state(ManagerForm.phone)

@dp.message(ManagerForm.phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await message.answer("Telegram username клиента (без @):")
    await state.set_state(ManagerForm.telegram_username)

@dp.message(ManagerForm.telegram_username)
async def process_username(message: Message, state: FSMContext):
    await state.update_data(telegram_username=message.text.strip())
    await message.answer("Telegram User ID клиента (число):")
    await state.set_state(ManagerForm.telegram_user_id)

@dp.message(ManagerForm.telegram_user_id)
async def process_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await state.update_data(telegram_user_id=user_id)
        await message.answer("Название робота (например Робот №1):")
        await state.set_state(ManagerForm.robot_name)
    except ValueError:
        await message.answer("Введите число (User ID).")

@dp.message(ManagerForm.robot_name)
async def process_robot_name(message: Message, state: FSMContext):
    await state.update_data(robot_name=message.text.strip())
    await message.answer("Серийный номер робота:")
    await state.set_state(ManagerForm.serial_number)

@dp.message(ManagerForm.serial_number)
async def process_serial_number(message: Message, state: FSMContext):
    await state.update_data(serial_number=message.text.strip())
    await message.answer("Дата начала бесплатного обслуживания (YYYY-MM-DD):")
    await state.set_state(ManagerForm.start_date)

@dp.message(ManagerForm.start_date)
async def process_start_date(message: Message, state: FSMContext):
    data = await state.get_data()
    start_date = message.text.strip()

    # 1. Создаём контакт
    contact_data = {
        "contact": {
            "first_name": data['fio'].split()[0],
            "last_name": ' '.join(data['fio'].split()[1:]) if len(data['fio'].split()) > 1 else "",
            "phone": data['phone'],
            "telegram_username": data['telegram_username'],
            "custom_fields": {
                "telegram_user_id": data['telegram_user_id']
            }
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OKDESK_API_BASE}/contacts",
            json=contact_data,
            params={"api_token": OKDESK_API_TOKEN}
        ) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                await message.answer(f"Ошибка создания контакта: {resp.status} - {text}")
                await state.clear()
                return
            contact_response = await resp.json()
            contact_id = contact_response.get("id")
            logging.info(f"Создан контакт ID: {contact_id}")

    # 2. Создаём объект обслуживания
    entity_data = {
        "maintenance_entity": {
            "name": data['robot_name'],
            "serial_number": data['serial_number'],
            "custom_fields": {
                "free_service_start_date": start_date
            },
            "contact_id": contact_id
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{OKDESK_API_BASE}/maintenance_entities",
            json=entity_data,
            params={"api_token": OKDESK_API_TOKEN}
        ) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                await message.answer(f"Ошибка создания робота: {resp.status} - {text}")
            else:
                await message.answer("Клиент и робот успешно зарегистрированы в OKDesk!")

    await state.clear()

async def main():
    print("Менеджерский бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
