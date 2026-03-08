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

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
OKDESK_API_TOKEN = "80ce0681fc84a44a7ca11450b24587b9fa367fa8"
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN") or "teken2027"

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    phone = State()
    select_object = State()
    problem = State()

start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def get_contact_by_phone(phone: str):
    params = {"api_token": OKDESK_API_TOKEN, "phone": phone}
    async with aiohttp.ClientSession() as session:
        logging.info(f"Запрос по телефону: {phone}")
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            logging.info(f"Статус: {resp.status}")
            text = await resp.text()
            logging.info(f"Сырой ответ API: {text}")

            if resp.status != 200:
                return None

            try:
                data = await resp.json()

                # Вариант 1: массив contacts
                contacts = data.get("contacts", [])

                # Вариант 2: одиночный объект (если нет ключа contacts)
                if not contacts and isinstance(data, dict) and "id" in data:
                    contacts = [data]

                logging.info(f"Найдено контактов после фикса: {len(contacts)}")

                if not contacts:
                    return None

                return contacts[0]  # берём первый контакт

            except Exception as e:
                logging.error(f"Ошибка парсинга JSON: {e}")
                return None

async def get_objects_by_company(company_id: int):
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        logging.info(f"Запрос объектов компании {company_id}")
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            logging.info(f"Статус: {resp.status}")
            if resp.status != 200:
                logging.error(await resp.text())
                return []
            data = await resp.json()
            objects = data.get("maintenance_entities", [])
            logging.info(f"Найдено объектов: {len(objects)}")
            return objects

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    logging.info(f"СТАРТ от {message.from_user.id}")
    await state.clear()
    await message.answer("Здравствуйте! Укажите ваш номер телефона (+7...):", reply_markup=start_kb)
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    logging.info(f"Телефон введён: {phone}")
    await state.update_data(phone=phone)

    contact = await get_contact_by_phone(phone)

    if not contact:
        await message.answer("Клиент с таким телефоном не найден. Обратитесь к менеджеру.", reply_markup=start_kb)
        await state.clear()
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"
    company_id = contact.get("company_id")

    if not company_id:
        await message.answer(f"Здравствуйте, {fio}!\nКарточка не привязана к компании.", reply_markup=start_kb)
        await state.clear()
        return

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer(f"Здравствуйте, {fio}!\nУ вас нет объектов обслуживания.", reply_markup=start_kb)
        await state.clear()
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

    await state.update_data(contact=contact, objects=objects)
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
    except ValueError:
        pass

    await message.answer("Введите номер из списка (1, 2, 3...)")

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    problem = message.text.strip()
    data = await state.get_data()

    fio = data.get("contact", {}).get("first_name", "клиент")
    obj_name = data.get("selected_object", {}).get("name", "не выбран")

    summary = (
        f"Спасибо, {fio}! Ожидайте звонок.\n\n"
        f"Объект: {obj_name}\n"
        f"Проблема: {problem}"
    )
    await message.answer(summary, reply_markup=start_kb)

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
