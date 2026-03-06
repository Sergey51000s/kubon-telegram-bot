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
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    os.getenv("BOT_TOKEN") or
    os.getenv("TOKEN")
)

OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные OKDesk/Telegram найдены в окружении!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    select_object = State()   # Выбор объекта обслуживания
    full_name = State()
    city = State()
    company = State()
    problem = State()

# Кнопка СТАРТ
start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def get_contact_by_username(username: str):
    """Найти контакт по Telegram username"""
    params = {"api_token": OKDESK_API_TOKEN, "telegram_username": username}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            contacts = data.get("contacts", [])
            if not contacts:
                return None
            return contacts[0]  # первый найденный контакт

async def get_objects_by_company(company_id: int):
    """Получить все объекты обслуживания компании"""
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("maintenance_entities", [])

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    username = message.from_user.username
    print(f"Получен /start или СТАРТ от @{username} ({message.from_user.id})")

    await state.clear()

    if not username:
        await message.answer("У вас не установлен username в Telegram. Пожалуйста, установите @username в настройках профиля и попробуйте снова.")
        return

    contact = await get_contact_by_username(username)

    if not contact:
        await message.answer(
            "Здравствуйте!\n\nВаше имя пользователя Telegram не найдено в нашей базе клиентов.\n"
            "Пожалуйста, обратитесь к вашему менеджеру для регистрации.",
            reply_markup=start_kb
        )
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"
    company_id = contact.get("company_id")

    if not company_id:
        await message.answer(f"Здравствуйте, {fio}!\nВаша карточка не привязана к компании. Обратитесь к менеджеру.")
        return

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer(f"Здравствуйте, {fio}!\nУ вас пока нет зарегистрированных объектов обслуживания.")
        return

    # Формируем список объектов для выбора
    object_list = "\n".join(
        f"{i+1}. {obj.get('name', 'Без названия')} (серийный № {obj.get('serial_number', 'не указан')})"
        for i, obj in enumerate(objects)
    )

    await message.answer(
        f"Здравствуйте, {fio}!\n"
        f"Пожалуйста, выберите объект, с которым возникла проблема:\n\n"
        f"{object_list}",
        reply_markup=start_kb
    )

    await state.update_data(contact=contact, objects=objects)
    await state.set_state(Form.select_object)

@dp.message(Form.select_object)
async def process_object_selection(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    objects = data.get("objects", [])

    # Пытаемся понять, какой номер выбрал пользователь
    try:
        num = int(text.split(".")[0]) - 1
        if 0 <= num < len(objects):
            selected = objects[num]
            await state.update_data(selected_object=selected)
            await message.answer("Бесплатное обслуживание активно. Укажите ФИО (если нужно обновить):")
            await state.set_state(Form.full_name)
            return
    except:
        pass

    await message.answer("Пожалуйста, выберите номер из списка (например, 1 или 2)")

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

# (остальные шаги анкеты без изменений — city, company, problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text.strip())
    data = await state.get_data()

    summary = (
        f"Спасибо, ожидайте звонок!\n\n"
        f"Ваши данные:\n"
        f"ФИО: {data.get('full_name')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Объект: {data.get('selected_object', {}).get('name', 'не выбран')}\n"
        f"Проблема: {data.get('problem')}"
    )
    await message.answer(summary)

    # Отправка заявки в OKDesk
    if OKDESK_API_TOKEN and OKDESK_SUBDOMAIN:
        issue_data = {
            "issue": {
                "title": f"Заявка из Telegram: {data.get('full_name', 'Клиент')}",
                "description": summary,
                "priority": "normal",
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}",
                    json=issue_data
                ) as resp:
                    if resp.status in (200, 201):
                        await message.answer("Заявка успешно отправлена в систему OKDesk!")
                    else:
                        text = await resp.text()
                        await message.answer(f"Ошибка при отправке заявки (код {resp.status}). Свяжемся вручную.")
        except Exception as e:
            await message.answer("Не удалось отправить заявку. Свяжемся вручную.")

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
