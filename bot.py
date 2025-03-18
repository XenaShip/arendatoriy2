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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from django.conf import settings
from asgiref.sync import sync_to_async
import django

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

# Настройка логирования
logging.basicConfig(level=logging.INFO)


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
    """Сохранение данных в Django-модель"""
    return MESSAGE.objects.create(text=text, images=images)


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

    # Получаем текст и изображения
    text, images = fetch_page_data(url)
    if not text and not images:
        await message.answer("⚠️ Не удалось найти текст или изображения.")
        return

    # Загружаем изображения
    image_urls = await download_images(images)

    # Сохраняем в базу данных
    await save_message_to_db(text, image_urls)

    await message.answer("✅ Данные сохранены в базе!")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
