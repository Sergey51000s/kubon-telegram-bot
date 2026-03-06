import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

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

# Разрешённые серийные номера (замени на свои реальные)
ALLOWED_SERIAL_NUMBERS = ["1111111", "2222222"]  # ← ВСТАВЬ СВОИ 2 НОМЕРА

class Form(StatesGroup):
    phone = State()           # Новый: телефон в начале
    serial_number = State()   # Новый: серийный номер
    full_name = State()
    city = State()
    company = State()
    problem = State()

async def check_client_and_robot(phone: str, serial_number: str):
    """Проверка по API OKDesk: клиент + его робот + срок 2 месяцев"""
    headers = {"Content-Type": "application/json"}
    params = {"api_token": OKDESK_API_TOKEN}

    # Шаг 1: найти контакт по телефону
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params={**params, "phone": phone}) as resp:
            if resp.status != 200:
                return False, "Ошибка поиска клиента по телефону"
            contacts = await resp.json()
            if not contacts.get("contacts"):
                return False, "Клиент с таким телефоном не найден"

            contact = contacts["contacts"][0]  # берём первого
            company_id = contact.get("company_id")
            contact_id = contact.get("id")

        # Шаг 2: найти объект обслуживания по серийному номеру и компании
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params={**params, "serial_number": serial_number, "company_id": company_id}) as resp:
            if resp.status != 200:
                return False, "Ошибка поиска оборудования"
            entities = await resp.json()
            if not entities.get("maintenance_entities"):
                return False, "Робот с таким серийным номером не найден у этого клиента"

            entity = entities["maintenance_entities"][0]
            entity_id = entity.get("id")
            start_date_str = entity.get("custom_fields", {}).get("free_service_start_date")

            if not start_date_str:
                return False, "У робота не указана дата начала бесплатного обслуживания"

            # Шаг 3: проверка 2 месяцев
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                two_months_later = start_date + timedelta(days=60)
                if datetime.now() > two_months_later:
                    return True, "Платное обслуживание (прошло более 2 месяцев)", entity_id
                else:
                    return True, "Бесплатное обслуживание", entity_id
            except:
                return False, "Неверный формат даты в поле free_service_start_date"

        return False, "Неизвестная ошибка проверки"

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    print(f"Получен /start от {message.from_user.id}")
    await state.clear()
    await message.answer("Здравствуйте! Для регистрации заявки укажите ваш номер телефона (+7...):")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    print(f"Получен телефон: {phone}")
    await state.update_data(phone=phone)
    await message.answer("Укажите серийный номер вашего робота:")
    await state.set_state(Form.serial_number)

@dp.message(Form.serial_number)
async def process_serial_number(message: Message, state: FSMContext):
    serial = message.text.strip()
    print(f"Получен серийный номер: {serial}")
    data = await state.get_data()
    phone = data.get("phone")

    success, msg, entity_id = await check_client_and_robot(phone, serial)

    if not success:
        await message.answer(f"{msg}. Заявка не может быть создана.")
        await state.clear()
        return

    if "платное" in msg.lower():
        await message.answer(f"{msg}. Стоимость заявки — 5000 ₽. Продолжить? (Да/Нет)")
        await state.update_data(is_paid=True, entity_id=entity_id)
    else:
        await state.update_data(is_paid=False, entity_id=entity_id)
        await message.answer("Бесплатное обслуживание активно. Укажите ФИО:")
        await state.set_state(Form.full_name)
        return

    # Если платное — ждём ответа Да/Нет
    await state.update_data(wait_paid_confirm=True)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    print(f"Получено ФИО: {message.text}")
    await state.update_data(full_name=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

# ... остальные handlers без изменений (city → company → problem → отправка в OKDesk)

# В конце process_problem перед отправкой:
# async def process_problem(...):
#     data = await state.get_data()
#     if data.get("is_paid") and not data.get("paid_confirmed"):
#         await message.answer("Подтвердите платную заявку (Да/Нет)")
#         return
#     # дальше отправка в OKDesk с entity_id и тегом "Платное обслуживание" если нужно

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
