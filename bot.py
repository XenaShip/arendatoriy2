import asyncio
import os
import time

import aiohttp
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import django
from django.conf import settings # Импортируем модель MESSAGE
from asgiref.sync import sync_to_async
from yandex_cloud_ml_sdk import YCloudML

load_dotenv()

# Инициализация Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from main.models import MESSAGE

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()
YANDEX_GPT_API_KEY = os.getenv("YANDEX_GPT_API_KEY")

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
            "text": f"Переформулируй объявление {} под шаблон: кол-во комнат, цена, адрес, условия, описание, контакты",
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

@sync_to_async
def save_message_to_db(text, filenames):
    return MESSAGE.objects.create(text=text, images=filenames)

def fetch_images(url):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=OutOfBlinkCors,LegacyTLS")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        logging.info("Браузер успешно запущен")
        driver.get(url)
        logging.info("Открыта страница: %s", url)

        images = []
        img_elements = driver.find_elements(By.TAG_NAME, "img")
        for img in img_elements:
            img_url = img.get_attribute("src")
            if img_url and img_url.startswith("http") and "cian" in img_url:
                images.append(img_url)
            if len(images) >= 10:
                break
        driver.quit()
        logging.info("Найдено %d изображений", len(images))
        return images
    except Exception as e:
        logging.error("Ошибка при загрузке страницы: %s", e)
        return []


async def download_images(images, text):
    async with aiohttp.ClientSession() as session:
        filenames = []
        for index, img_url in enumerate(images):
            async with session.get(img_url) as response:
                if response.status == 200:
                    filename = f"image_{index}.jpg"
                    with open(filename, "wb") as f:
                        f.write(await response.read())
                    filenames.append(filename)

    # Сохраняем в базу данных через синхронный вызов
    await save_message_to_db(text, filenames)
    return filenames



@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Привет! Отправь мне ссылку, и я скачаю 10 изображений.")


@dp.message()
async def message_handler(message: Message):
    url = message.text.strip()
    await message.answer("🔍 Ищу изображения, подождите...")

    images = fetch_images(url)
    if not images:
        await message.answer("⚠️ Не удалось найти изображения.")
        return

    filenames = await download_images(images, url)
    await message.answer("✅ Изображения успешно сохранены в базе данных!")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
