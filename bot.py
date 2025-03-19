import asyncio
import os
import aiohttp
import logging
import time
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from telegram import InputMediaPhoto
from webdriver_manager.chrome import ChromeDriverManager
from django.conf import settings
from asgiref.sync import sync_to_async
import django
from yandex_cloud_ml_sdk import YCloudML
from aiogram.types import InputMediaPhoto
import undetected_chromedriver as uc
import time
import aiogram.utils.markdown as md
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# Настроим Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

# Импортируем модель MESSAGE
from main.models import MESSAGE

# Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
# Настройка логирования
logging.basicConfig(level=logging.INFO)


def process_text_with_gpt(text):
    """Отправка текста в Yandex GPT и получение измененного текста"""
    sdk = YCloudML(
        folder_id=os.getenv("FOLDER_ID"),
        auth=os.getenv("AUTH"),
    )

    model = sdk.models.completions("yandexgpt")

    # Variant 1: wait for the operation to complete using 5-second sleep periods

    messages_1 = [
        {
            "role": "system",
            "text": "Переформулируй объявление под шаблон: кол-во комнат, цена, адрес, условия, описание",
        },
        {
            "role": "user",
            "text": text,
        },
    ]
    operation = model.configure(temperature=0.3).run_deferred(messages_1)

    status = operation.get_status()
    while status.is_running:
        time.sleep(5)
        status = operation.get_status()

    result = operation.get_result()
    return result.text


async def send_images_with_text(bot, chat_id, text, images):
    """Отправляет изображения в Telegram, первое с текстом, остальные без."""
    media_group = []
    for index, img_url in enumerate(images):
        if index == 0:
            media_group.append(InputMediaPhoto(media=img_url, caption=text))  # Первое изображение с текстом
        else:
            media_group.append(InputMediaPhoto(media=img_url))

    if media_group:
        await bot.send_media_group(chat_id=chat_id, media=media_group)


from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def escape_md_v2(text):
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in special_chars else char for char in text)

def fetch_page_data(url):
    """Функция загружает страницу, извлекает текст и ссылки на изображения"""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Без графического интерфейса
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")
    options.add_argument("--disable-site-isolation-trials")

    # Устанавливаем "человеческий" User-Agent
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    logging.info(f"Открываю страницу: {url}")
    driver.get(url)

    # Ждем загрузки страницы
    time.sleep(10)

    # Прокручиваем страницу вниз (если контент загружается при прокрутке)
    for _ in range(5):
        ActionChains(driver).send_keys(Keys.END).perform()
        time.sleep(1)

    # 1️⃣ Извлекаем весь текст со страницы
    full_text = driver.execute_script("return document.body.innerText")

    # 2️⃣ Извлекаем самый длинный текстовый блок
    text_blocks = [el.text for el in driver.find_elements(By.TAG_NAME, "div") if el.text.strip()]
    longest_text = max(text_blocks, key=len, default="")  # Берем самый длинный

    # Если полный текст слишком короткий, берем текст из div
    page_text = longest_text if len(longest_text) > 100 else full_text

    # 3️⃣ Извлекаем изображения
    images = []
    for img in driver.find_elements(By.TAG_NAME, "img"):
        img_url = img.get_attribute("src")
        if img_url and img_url.startswith("http"):
            images.append(img_url)
        if len(images) >= 10:
            break

    driver.quit()
    logging.info(f"Текст страницы (200 символов): {page_text[:200]}...")
    logging.info(f"Найдено {len(images)} изображений")
    return page_text, images



@sync_to_async
def save_message_to_db(text, images):
    """Сохранение объявления в БД."""
    return MESSAGE.objects.create(text=text, images=images)



async def fetch_message_from_db():
    """Получение последнего сообщения из базы"""
    return await sync_to_async(lambda: MESSAGE.objects.last())()

async def download_images(images):
    """Загружает изображения и сохраняет ссылки в БД"""
    async with aiohttp.ClientSession() as session:
        filenames = []
        for index, img_url in enumerate(images):
            async with session.get(img_url) as response:
                if response.status == 200:
                    filenames.append(img_url)  # Сохраняем ссылки вместо файлов
        return filenames


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Привет! Отправь мне ссылку, и я сохраню текст и изображения.")


@dp.message()
async def message_handler(message: Message):
    url = message.text.strip()
    await message.answer("🔍 Обрабатываю страницу, подождите...")

    # Получаем текст, изображения и телефон
    text, images= fetch_page_data(url)

    if not text and not images:
        await message.answer("⚠️ Не удалось найти данные на странице.")
        return

    # Загружаем изображения
    image_urls = await download_images(images)

    # Сохраняем в базу
    await save_message_to_db(text, image_urls)

    # Обновляем текст через GPT
    new_text = await asyncio.to_thread(process_text_with_gpt, text)
    print(new_text)
    # Отправляем сообщение в канал
    media_group = [InputMediaPhoto(media=img_url) for img_url in image_urls[1:]]  # Пропускаем первое изображение

    if media_group:
        caption = f"{escape_md_v2(new_text)}\n📞 [Контакты]({escape_md_v2(url)})"
        media_group[0].caption = caption
        media_group[0].parse_mode = "MarkdownV2"
        await bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media_group)
    else:
        text = f"{escape_md_v2(new_text)}\n📞 [Контакты]({escape_md_v2(url)})"
        await bot.send_message(TELEGRAM_CHANNEL_ID, text, parse_mode="MarkdownV2")

    await message.answer("✅ Данные сохранены и отправлены!")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)



async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
