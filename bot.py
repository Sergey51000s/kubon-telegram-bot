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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

import aiohttp
import os

# Токены из окружения Bothost
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    os.getenv("BOT_TOKEN") or
    os.getenv("TOKEN")
)

OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_TOKEN не найден!")
    sys.exit(1)

OKDESK_URL = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}" if OKDESK_SUBDOMAIN and OKDESK_API_TOKEN else None

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    full_name = State()
    phone = State()
    city = State()
    company = State()
    problem = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    print("Получен /start от", message.from_user.id)
    await state.clear()
    await message.answer(
        "Здравствуйте, я — технический специалист компании Kubon.\n"
        "Пожалуйста, заполните анкету и мы с вами свяжемся.\n\n"
        "ФИО:"
    )
    await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    print("Получено ФИО:", message.text)
    await state.update_data(full_name=message.text.strip())
    await message.answer("Номер телефона:")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    print("Получен телефон:", message.text)
    await state.update_data(phone=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

@dp.message(Form.city)
async def process_city(message: Message, state: FSMContext):
    print("Получен город:", message.text)
    await state.update_data(city=message.text.strip())
    await message.answer("Компания/ИП:")
    await state.set_state(Form.company)

@dp.message(Form.company)
async def process_company(message: Message, state: FSMContext):
    print("Получена компания:", message.text)
    await state.update_data(company=message.text.strip())
    await message.answer("Краткое описание проблемы (если возможно):")
    await state.set_state(Form.problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    print("Получено описание:", message.text)
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

    if OKDESK_URL:
        issue_data = {
            "issue": {
                "title": f"Заявка из Telegram: {data.get('full_name', 'Клиент')}",
                "description": (
                    f"ФИО: {data.get('full_name')}\n"
                    f"Телефон: {data.get('phone')}\n"
                    f"Город: {data.get('city')}\n"
                    f"Компания/ИП: {data.get('company')}\n"
                    f"Описание проблемы: {data.get('problem')}\n\n"
                    f"Источник: Telegram-бот Kubon"
                ),
                "priority": "medium",
                "kind_id": 1,
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OKDESK_URL, json=issue_data) as resp:
                    print(f"OKDesk статус: {resp.status}")
        except Exception as e:
            print(f"Ошибка OKDesk: {e}")

    await state.clear()

async def on_startup(bot: Bot):
    # Устанавливаем webhook при запуске
    webhook_path = f"/webhook/{TELEGRAM_TOKEN[-10:]}"  # уникальный путь
    webhook_url = f"https://{os.getenv('BOTHOST_DOMAIN', 'your-domain.bothost.ru')}{webhook_path}"
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(webhook_url)
    print(f"Webhook установлен на: {webhook_url}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook(drop_pending_updates=True)
    print("Webhook удалён")

def main():
    print("Бот запущен! Используем webhook.")
    app = web.Application()
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_handler.register(app, path=f"/webhook/{TELEGRAM_TOKEN[-10:]}")
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", 3000)))

if __name__ == "__main__":
    main()
