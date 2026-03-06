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
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    select_object = State()
    problem = State()

start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def get_company_by_user_id(user_id: int):
    """Поиск компании по custom field telegram_user_id"""
    params = {"api_token": OKDESK_API_TOKEN}
    custom_filter = f"custom_fields[telegram_user_id]={user_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/companies?{custom_filter}", params=params) as resp:
            if resp.status != 200:
                print(f"Ошибка API companies: {resp.status} - {await resp.text()}")
                return None
            data = await resp.json()
            companies = data.get("companies", [])
            if not companies:
                return None
            return companies[0]

async def get_contact_by_company(company_id: int):
    """Найти контакт по компании (берём первый)"""
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            contacts = data.get("contacts", [])
            if not contacts:
                return None
            return contacts[0]

async def get_objects_by_company(company_id: int):
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            if resp.status != 200:
                print(f"Ошибка API objects: {resp.status}")
                return []
            data = await resp.json()
            return data.get("maintenance_entities", [])

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "без username"
    print(f"СТАРТ от @{username} (ID: {user_id})")

    await state.clear()
    await message.answer("Пожалуйста, подождите...", reply_markup=start_kb)

    company = await get_company_by_user_id(user_id)

    if not company:
        await message.answer(
            f"Здравствуйте!\n\n"
            f"Ваш Telegram ID ({user_id}) не найден в базе компаний.\n"
            "Обратитесь к менеджеру для регистрации.",
            reply_markup=start_kb
        )
        return

    fio = "клиент"  # Если ФИО в компании нет — можно оставить так
    # Если хочешь ФИО из контакта — добавим поиск ниже

    contact = await get_contact_by_company(company.get("id"))
    if contact:
        fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"

    company_id = company.get("id")

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer(f"Здравствуйте, {fio}!\nУ вас нет объектов обслуживания.", reply_markup=start_kb)
        return

    object_list = "\n".join(
        f"{i+1}. {obj.get('name', 'Без названия')} (№ {obj.get('serial_number', 'не указан')})"
        for i, obj in enumerate(objects)
    )

    await message.answer(
        f"Здравствуйте, {fio}!\n\n"
        f"Выберите объект с проблемой:\n\n"
        f"{object_list}\n\n"
        "Напишите номер (1, 2, 3...)",
        reply_markup=start_kb
    )

    await state.update_data(company=company, objects=objects)
    await state.set_state(Form.select_object)

@dp.message(Form.select_object)
async def process_object_selection(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        num = int(text) - 1
        data = await state.get_data()
        objects = data.get("objects", [])
        if 0 <= num < len(objects):
            selected = objects[num]
            await state.update_data(selected_object=selected)
            await message.answer(
                f"Вы выбрали: {selected.get('name', 'Без названия')} (№ {selected.get('serial_number', 'не указан')})\n\n"
                "Опишите проблему:"
            )
            await state.set_state(Form.problem)
            return
    except:
        pass

    await message.answer("Введите номер из списка (1, 2, 3...)")

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    problem = message.text.strip()
    data = await state.get_data()

    fio = "клиент"  # или из контакта, если нужно
    obj_name = data.get("selected_object", {}).get("name", "не выбран")

    summary = (
        f"Спасибо! Ожидайте звонок.\n\n"
        f"Объект: {obj_name}\n"
        f"Проблема: {problem}"
    )
    await message.answer(summary, reply_markup=start_kb)

    # Отправка заявки в OKDesk (можно добавить)

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
