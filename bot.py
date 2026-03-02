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
        f"Телефон: {data.get('phone')}\n"
        f"Город: {data.get('city')}\n"
        f"Компания/ИП: {data.get('company')}\n"
        f"Проблема: {data.get('problem')}"
    )
    await message.answer(summary)
    
    print("\n" + "="*50)
    print("НОВАЯ ЗАЯВКА ОТ TELEGRAM")
    print(data)
    print("="*50 + "\n")
    
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
            "priority": "medium",
            "kind_id": 1,  # Замени на реальный, если знаешь
        }
    }
    
    print("Отправляем в OKDesk:")
    print("URL:", OKDESK_URL)
    print("JSON:", issue_data)
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http_session:
            async with http_session.post(OKDESK_URL, json=issue_data) as resp:
                response_text = await resp.text()
                print(f"Статус: {resp.status}")
                print(f"Ответ: {response_text}")
                if resp.status in (200, 201):
                    print("УСПЕХ!")
                else:
                    await message.answer(f"Ошибка OKDesk (код {resp.status}). Свяжемся вручную.")
    except Exception as e:
        print(f"Ошибка отправки: {type(e).__name__}: {str(e)}")
        await message.answer("Не удалось отправить в OKDesk. Свяжемся вручную.")
    
    await state.clear()

async def main():
    print("Бот запущен! Пиши /start в Telegram.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
