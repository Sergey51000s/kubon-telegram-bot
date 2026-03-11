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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AMO_SUBDOMAIN = os.getenv("AMO_SUBDOMAIN") or "demon51000"
AMO_TOKEN = os.getenv("AMO_ACCESS_TOKEN")

AMO_PIPELINE_ID = 10684430
AMO_STATUS_ID = 10684431  # Заявка — подправь после теста

if not TELEGRAM_TOKEN or not AMO_TOKEN:
    print("ОШИБКА: TELEGRAM_TOKEN или AMO_ACCESS_TOKEN не найдены!")
    sys.exit(1)

AMO_API_BASE = f"https://{AMO_SUBDOMAIN}.amocrm.ru/api/v4"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Registration(StatesGroup):
    fio = State()
    inn = State()
    phone = State()
    filial_name = State()
    filial_city = State()
    filial_street = State()
    filial_building = State()

class Form(StatesGroup):
    menu = State()
    serial_input = State()
    issue_description = State()
    ask_attach = State()
    wait_attach = State()


# Клавиатуры
start_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="СТАРТ", request_contact=True)]], resize_keyboard=True)
main_menu_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Обслуживание")]], resize_keyboard=True)
back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True)
attach_choice_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="Да, прикрепить фото/видео")],
    [KeyboardButton(text="Нет, создать заявку без файлов")]
], resize_keyboard=True)
done_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Готово, отправить заявку")]], resize_keyboard=True)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r'[^0-9+]', '', raw.strip())
    if digits.startswith('8'):
        digits = '+7' + digits[1:]
    if not digits.startswith('+'):
        digits = '+7' + digits
    return digits


async def get_amo_contact_by_telegram_id(telegram_id: int):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{AMO_API_BASE}/contacts", headers=headers) as resp:
            if resp.status != 200:
                logging.error(f"[get_contact] Ошибка /contacts: {resp.status} - {await resp.text()}")
                return None
            data = await resp.json()
            contacts = data.get('_embedded', {}).get('contacts', [])
            for contact in contacts:
                async with session.get(f"{AMO_API_BASE}/contacts/{contact['id']}/notes", headers=headers) as note_resp:
                    if note_resp.status == 200:
                        note_data = await note_resp.json()
                        notes = note_data.get('_embedded', {}).get('notes', [])
                        for note in notes:
                            text = note.get('params', {}).get('text', '')
                            if f"Telegram ID: {telegram_id}" in text:
                                logging.info(f"[get_contact] Найден контакт {contact['id']}")
                                return contact
    logging.info(f"[get_contact] Контакт с Telegram ID {telegram_id} не найден")
    return None


async def create_amo_contact(fio: str, inn: str, phone: str, telegram_id: int, filial_name: str, filial_city: str, filial_street: str, filial_building: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": fio
        # Убрали custom_fields_values, чтобы избежать 403 на базовом тарифе
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/contacts", json=payload, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"[create_contact] Ответ: {resp.status} - {text}")
            if resp.status in (200, 201):
                data = await resp.json()
                contact_id = data['_embedded']['contacts'][0]['id']
                # Все данные в заметку (note)
                note_text = f"Telegram ID: {telegram_id}\nИНН: {inn}\nТелефон: {phone}\nФилиал: {filial_name}\nГород: {filial_city}\nУлица: {filial_street}\nЗдание: {filial_building}"
                await add_note_to_contact(contact_id, note_text)
                logging.info(f"[create_contact] Контакт {contact_id} создан")
                return contact_id
            return None


async def add_note_to_contact(contact_id: int, text: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "note_type": "common",
        "params": {"text": text}
    }]

    async with aiohttp.ClientSession() as session:
        url = f"{AMO_API_BASE}/contacts/{contact_id}/notes"
        async with session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"[add_note] {resp.status} - {text}")


async def create_amo_lead(contact_id: int, description: str, serial: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": f"Заявка по роботу {serial}",
        "pipeline_id": AMO_PIPELINE_ID,
        "status_id": AMO_STATUS_ID,
        "contacts": [{"id": contact_id}],
        "description": f"{description}\nСерийный номер: {serial}"
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/leads", json=payload, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"[create_lead] Ответ: {resp.status} - {text}")
            if resp.status in (200, 201):
                data = await resp.json()
                lead_id = data['_embedded']['leads'][0]['id']
                return lead_id
            return None


async def upload_file_to_amo_lead(lead_id: int, file_bytes: bytes, filename: str):
    form = aiohttp.FormData()
    form.add_field("file", file_bytes, filename=filename, content_type="image/jpeg")

    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        url = f"{AMO_API_BASE}/leads/{lead_id}/files"
        async with session.post(url, data=form, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"[upload_file] {resp.status} - {text}")
            return resp.status in (200, 201)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    telegram_id = message.from_user.id
    contact = await get_amo_contact_by_telegram_id(telegram_id)
    if contact:
        fio = contact.get('name', 'Клиент')
        await message.answer(f"Здравствуйте, <b>{fio}</b>!\n\nЧто делаем?", reply_markup=main_menu_kb)
        await state.update_data(contact=contact)
        await state.set_state(Form.menu)
    else:
        await message.answer("Здравствуйте! Давайте зарегистрируемся.")
        await message.answer("Введите ФИО:", reply_markup=back_kb)
        await state.set_state(Registration.fio)


@dp.message(Registration.fio, F.text == "Назад")
async def reg_fio_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Начнём заново?", reply_markup=start_kb)
    await state.clear()


@dp.message(Registration.fio)
async def reg_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Введите ИНН (10 или 12 цифр):", reply_markup=back_kb)
    await state.set_state(Registration.inn)


@dp.message(Registration.inn, F.text == "Назад")
async def reg_inn_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите ФИО заново:", reply_markup=back_kb)
    await state.set_state(Registration.fio)


@dp.message(Registration.inn)
async def reg_inn(message: Message, state: FSMContext):
    inn = message.text.strip()
    if len(inn) not in (10, 12) or not inn.isdigit():
        await message.answer("ИНН должен состоять из 10 или 12 цифр. Попробуйте ещё раз:", reply_markup=back_kb)
        return
    await state.update_data(inn=inn)
    await message.answer("Введите номер телефона:", reply_markup=back_kb)
    await state.set_state(Registration.phone)


@dp.message(Registration.phone, F.text == "Назад")
async def reg_phone_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите ИНН заново:", reply_markup=back_kb)
    await state.set_state(Registration.inn)


@dp.message(Registration.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    await state.update_data(phone=phone)
    await message.answer("Введите название филиала:", reply_markup=back_kb)
    await state.set_state(Registration.filial_name)


@dp.message(Registration.filial_name, F.text == "Назад")
async def reg_filial_name_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите номер телефона заново:", reply_markup=back_kb)
    await state.set_state(Registration.phone)


@dp.message(Registration.filial_name)
async def reg_filial_name(message: Message, state: FSMContext):
    await state.update_data(filial_name=message.text)
    await message.answer("Введите город филиала:", reply_markup=back_kb)
    await state.set_state(Registration.filial_city)


@dp.message(Registration.filial_city, F.text == "Назад")
async def reg_filial_city_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите название филиала заново:", reply_markup=back_kb)
    await state.set_state(Registration.filial_name)


@dp.message(Registration.filial_city)
async def reg_filial_city(message: Message, state: FSMContext):
    await state.update_data(filial_city=message.text)
    await message.answer("Введите улицу филиала:", reply_markup=back_kb)
    await state.set_state(Registration.filial_street)


@dp.message(Registration.filial_street, F.text == "Назад")
async def reg_filial_street_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите город заново:", reply_markup=back_kb)
    await state.set_state(Registration.filial_city)


@dp.message(Registration.filial_street)
async def reg_filial_street(message: Message, state: FSMContext):
    await state.update_data(filial_street=message.text)
    await message.answer("Введите номер здания филиала:", reply_markup=back_kb)
    await state.set_state(Registration.filial_building)


@dp.message(Registration.filial_building, F.text == "Назад")
async def reg_filial_building_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите улицу заново:", reply_markup=back_kb)
    await state.set_state(Registration.filial_street)


@dp.message(Registration.filial_building)
async def reg_filial_building(message: Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = message.from_user.id
    contact_id = await create_amo_contact(
        data['fio'], data['inn'], data['phone'], telegram_id,
        data['filial_name'], data['filial_city'], data['filial_street'], message.text
    )
    if contact_id:
        # Изменённое сообщение
        await message.answer("Данные на модерации, ваша тех поддержка будет активированна в течении 2х часов", reply_markup=main_menu_kb)
        await state.update_data(contact={"id": contact_id})
        await state.set_state(Form.menu)
    else:
        await message.answer("Ошибка регистрации. Попробуйте позже /start")


@dp.message(Form.menu, F.text == "Обслуживание")
async def process_service(message: Message, state: FSMContext):
    await message.answer("Введите серийный номер вашего робота:", reply_markup=back_kb)
    await state.set_state(Form.serial_input)


@dp.message(Form.serial_input, F.text == "Назад")
async def serial_back(message: Message, state: FSMContext):
    await message.answer("Вернулись в меню", reply_markup=main_menu_kb)
    await state.set_state(Form.menu)


@dp.message(Form.serial_input)
async def process_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        await message.answer("Серийный номер не может быть пустым. Введите заново:", reply_markup=back_kb)
        return
    await state.update_data(serial_number=serial)
    await message.answer("Опишите проблему (минимум 5 символов):", reply_markup=back_kb)
    await state.set_state(Form.issue_description)


@dp.message(Form.issue_description, F.text == "Назад")
async def description_back(message: Message, state: FSMContext):
    await message.answer("Вернулись назад. Введите серийный номер заново:", reply_markup=back_kb)
    await state.set_state(Form.serial_input)


@dp.message(Form.issue_description)
async def process_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if len(desc) < 5:
        await message.answer("Описание слишком короткое. Минимум 5 символов:", reply_markup=back_kb)
        return
    await state.update_data(issue_description=desc)
    await message.answer("Прикрепить фото/видео?", reply_markup=attach_choice_kb)
    await state.set_state(Form.ask_attach)


@dp.message(Form.ask_attach, F.text == "Да, прикрепить фото/видео")
async def ask_attach_yes(message: Message, state: FSMContext):
    await message.answer("Прикрепите фото/видео (можно несколько), затем нажмите «Готово»:", reply_markup=done_kb)
    await state.set_state(Form.wait_attach)


@dp.message(Form.ask_attach, F.text == "Нет, создать заявку без файлов")
async def ask_attach_no(message: Message, state: FSMContext):
    await process_finish(message, state)


@dp.message(Form.wait_attach, F.photo | F.document | F.video | F.text == "Готово, отправить заявку")
async def process_wait_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])
    if message.photo:
        attachments.append(message.photo[-1].file_id)
        await message.answer("Фото добавлено. Можно ещё или «Готово»:", reply_markup=done_kb)
    elif message.document:
        attachments.append(message.document.file_id)
        await message.answer("Документ добавлен. Можно ещё или «Готово»:", reply_markup=done_kb)
    elif message.video:
        attachments.append(message.video.file_id)
        await message.answer("Видео добавлено. Можно ещё или «Готово»:", reply_markup=done_kb)
    elif message.text == "Готово, отправить заявку":
        await process_finish(message, state)
    await state.update_data(attachments=attachments)


async def process_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    contact = data.get("contact")
    if not contact or "id" not in contact:
        await message.answer("Ошибка: контакт не найден. Начните заново /start")
        return

    contact_id = contact["id"]
    serial = data.get("serial_number", "не указан")
    description = data.get("issue_description", "без описания")
    attachments = data.get("attachments", [])

    lead_id = await create_amo_lead(contact_id, description, serial)
    if not lead_id:
        await message.answer("Не удалось создать заявку. Попробуйте позже.")
        return

    uploaded = 0
    for file_id in attachments:
        try:
            file = await bot.get_file(file_id)
            bytes_io = io.BytesIO()
            await bot.download_file(file.file_path, bytes_io)
            bytes_io.seek(0)
            filename = f"attach_{uploaded + 1}.jpg" if file.photo else "attach_file"
            success = await upload_file_to_amo_lead(lead_id, bytes_io.read(), filename)
            if success:
                uploaded += 1
        except Exception as e:
            logging.error(f"Ошибка загрузки файла {file_id}: {e}")

    await message.answer(
        f"Заявка создана!\n"
        f"Сделка №{lead_id}\n"
        f"Прикреплено файлов: {uploaded}",
        reply_markup=main_menu_kb
    )
    await state.clear()
    await state.set_state(Form.menu)


@dp.message(F.text == "Назад в меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.menu)
    await message.answer("Вернулись в главное меню", reply_markup=main_menu_kb)


# ────────────────────────────────────────────────
# ТЕСТОВЫЙ ХЭНДЛЕР ДЛЯ ПРОВЕРКИ amoCRM API
# Напиши боту команду /test_amo
# ────────────────────────────────────────────────
@dp.message(F.text == "/test_amo")
async def test_amo(message: Message):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    url = f"{AMO_API_BASE}/account"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                short_text = text[:800] + "..." if len(text) > 800 else text
                await message.answer(
                    f"<b>Тест amoCRM API</b>\n\n"
                    f"URL: {url}\n"
                    f"Статус: {resp.status}\n\n"
                    f"Ответ (первые 800 символов):\n<pre>{short_text}</pre>",
                    parse_mode="HTML"
                )
                logging.info(f"[test_amo] {resp.status} - {text}")
    except Exception as e:
        await message.answer(f"Ошибка при запросе: {str(e)}")
        logging.error(f"[test_amo] Exception: {str(e)}")


async def main():
    print("KubonSupportBot запущен (aiogram 3.x + AmoCRM)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
