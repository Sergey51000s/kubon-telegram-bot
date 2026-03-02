import asyncio
import logging
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
TOKEN = "8502841955:AAHLUFUVIHEzn6kgpDLrODedWjZMCn25Tok"

OKDESK_SUBDOMAIN = "kubon2026"
OKDESK_API_TOKEN = "a74b294d798762a6c2fba2bea27e63e6486a471a"
OKDESK_URL = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    full_name = State()
    phone     = State()
    city      = State()
    company   = State()
    problem   = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте, я — технический специалист компании Kubon.\n"
        "Пожалуйста, заполните анкету и мы с вами свяжемся.\n\n"
        "ФИО:"
    )
    await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await message.answer("Номер телефона:")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

@dp.message(Form.city)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await message.answer("Компания/ИП:")
    await state.set_state(Form.company)

@dp.message(Form.company)
async def process_company(message: Message, state: FSMContext):
    await state.update_data(company=message.text.strip())
    await message.answer("Краткое описание проблемы (если возможно):")
    await state.set_state(Form.problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text.strip())
    
    data = await state.get_data()
    
    summary = (
        "Спасибо, ожидайте звонок!\n\n"
        f"Ваши данные:\n"
        f"ФИО: {data.get('full_name')}\n"
        f"Телефон: {data.get('phone')}\n"import asyncio
import logging
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
from dotenv import load_dotenv
import os

# Загружаем переменные из .env файла
load_dotenv()

# Токены и настройки из .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not all([TELEGRAM_TOKEN, OKDESK_API_TOKEN, OKDESK_SUBDOMAIN]):
    print("ОШИБКА: Не все переменные найдены в .env!")
    print("Проверьте наличие TELEGRAM_TOKEN, OKDESK_API_TOKEN, OKDESK_SUBDOMAIN")
    sys.exit(1)

OKDESK_URL = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}"

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Состояния анкеты
class Form(StatesGroup):
    full_name = State()
    phone     = State()
    city      = State()
    company   = State()
    problem   = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте, я — технический специалист компании Kubon.\n"
        "Пожалуйста, заполните анкету и мы с вами свяжемся.\n\n"
        "ФИО:"
    )
    await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await message.answer("Номер телефона:")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

@dp.message(Form.city)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await message.answer("Компания/ИП:")
    await state.set_state(Form.company)

@dp.message(Form.company)
async def process_company(message: Message, state: FSMContext):
    await state.update_data(company=message.text.strip())
    await message.answer("Краткое описание проблемы (если возможно):")
    await state.set_state(Form.problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text.strip())
    
    data = await state.get_data()
    
    # Сообщение пользователю
    summary = (
        "Спасибо, ожидайте звонок!\n\n"
        f"Ваши данные:\n"
        f"ФИО: {data.get('full_name')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Город: {data.get('city')}\n"
        f"Компания/ИП: {data.get('company')}\n"
        f"Проблема: {data.get('problem')}"
    )
    await message.answer(summary)
    
    # Отладка в консоль
    print("\n" + "="*60)
    print("НОВАЯ ЗАЯВКА ОТ TELEGRAM")
    print("Время:", datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'))
    print(data)
    print("="*60 + "\n")
    
    # Данные для OKDesk
    issue_data = {
        "issue": {
            "title": f"Заявка из Telegram: {data.get('full_name', 'Клиент')}",
            "description": (
                f"ФИО: {data.get('full_name')}\n"
                f"Телефон: {data.get('phone')}\n"
                f"Город: {data.get('city')}\n"
                f"Компания/ИП: {data.get('company')}\n"
                f"Описание проблемы: {data.get('problem')}\n\n"
                f"Источник: Telegram-бот Kubon\n"
                f"Дата: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            ),
            "priority": "medium",   # low / medium / high
            "kind_id": 1,           # ← если знаешь реальный ID типа обращения — замени
        }
    }
    
    print("Отправляем в OKDesk:")
    print("URL:", OKDESK_URL)
    print("JSON:", issue_data)
    print("-"*80)
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http_session:
            async with http_session.post(OKDESK_URL, json=issue_data) as resp:
                response_text = await resp.text()
                print(f"Статус ответа OKDesk: {resp.status}")
                print(f"Ответ сервера: {response_text}")
                print("-"*80)
                
                if resp.status in (200, 201):
                    print("УСПЕХ! Заявка создана в OKDesk")
                else:
                    await message.answer(f"Ошибка OKDesk (код {resp.status}). Свяжемся вручную.")
    
    except aiohttp.ClientConnectorError as conn_err:
        print(f"Ошибка подключения к OKDesk: {conn_err}")
        await message.answer("Не удалось подключиться к системе OKDesk. Свяжемся вручную.")
    
    except Exception as e:
        print(f"Критическая ошибка при отправке: {type(e).__name__}: {str(e)}")
        await message.answer("Произошла ошибка при отправке заявки. Свяжемся вручную.")
    
    await state.clear()

async def main():
    print("Бот запущен! Пиши /start в Telegram для теста.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
if __name__ == "__main__":
    asyncio.run(main())
