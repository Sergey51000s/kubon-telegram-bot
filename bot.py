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

class Form(StatesGroup):
    phone = State()           # Телефон в начале
    serial_number = State()   # Серийный номер
    full_name = State()
    city = State()
    company = State()
    problem = State()

async def get_company_id_by_phone(phone: str):
    """Найти company_id по телефону контакта"""
    params = {"api_token": OKDESK_API_TOKEN, "phone": phone}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            contacts = data.get("contacts", [])
            if not contacts:
                return None
            return contacts[0].get("company_id")

async def get_robot_by_serial(company_id: int, serial_number: str):
    """Найти объект обслуживания по серийному номеру и компании"""
    params = {"api_token": OKDESK_API_TOKEN, "serial_number": serial_number, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            entities = data.get("maintenance_entities", [])
            if not entities:
                return None
            return entities[0]  # возвращаем первый найденный объект

async def check_client_and_robot(phone: str, serial_number: str):
    """Полная проверка: клиент + робот + срок 2 месяцев"""
    company_id = await get_company_id_by_phone(phone)
    if not company_id:
        return False, "Клиент с таким телефоном не найден", None

    robot = await get_robot_by_serial(company_id, serial_number)
    if not robot:
        return False, "Робот с таким серийным номером не найден у этого клиента", None

    entity_id = robot.get("id")
    custom_fields = robot.get("custom_fields", {})
    start_date_str = custom_fields.get("free_service_start_date")

    if not start_date_str:
        return False, "У робота не указана дата начала бесплатного обслуживания", entity_id

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        two_months_later = start_date + timedelta(days=60)
        if datetime.now() > two_months_later:
            return True, "Платное обслуживание (прошло более 2 месяцев)", entity_id
        else:
            return True, "Бесплатное обслуживание", entity_id
    except Exception as e:
        return False, f"Неверный формат даты в поле free_service_start_date: {e}", entity_id

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

    await state.update_data(entity_id=entity_id)

    if "платное" in msg.lower():
        await message.answer(f"{msg}. Стоимость заявки — 5000 ₽. Продолжить? (Да/Нет)")
        await state.update_data(is_paid=True, paid_confirmed=False)
    else:
        await state.update_data(is_paid=False)
        await message.answer("Бесплатное обслуживание активно. Укажите ФИО:")
        await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    print(f"Получено ФИО: {message.text}")
    await state.update_data(full_name=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

# (остальные handlers без изменений — city, company, problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    print(f"Получено описание проблемы: {message.text}")
    await state.update_data(problem=message.text.strip())
    data = await state.get_data()

    summary = (
        "Спасибо, ожидайте звонок!\n\n"
        f"Ваши данные:\n"
        f"ФИО: {data.get('full_name')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Серийный номер: {data.get('serial_number')}\n"
        f"Город: {data.get('city')}\n"
        f"Компания/ИП: {data.get('company')}\n"
        f"Проблема: {data.get('problem')}"
    )
    await message.answer(summary)

    # Отправка в OKDesk
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
                        print("Заявка создана успешно!")
                        await message.answer("Заявка успешно отправлена в систему OKDesk!")
                    else:
                        text = await resp.text()
                        print(f"Ошибка OKDesk: {resp.status} - {text}")
                        await message.answer("Ошибка при отправке заявки. Свяжемся вручную.")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
            await message.answer("Не удалось отправить заявку. Свяжемся вручную.")
    else:
        await message.answer("OKDesk не настроен — данные получены.")

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
