import asyncio
import os
from dotenv import load_dotenv
from app.api.api_config import APIConfig
from app.api.imap_reader import download_media_and_process_emails
from app.database.core import setup_database, init_base_mails
from app.utils.loggs.logger_conf import logger

load_dotenv(dotenv_path="envs/elevenlabs.env")
load_dotenv(dotenv_path="envs/gpt_conf.env")
load_dotenv(dotenv_path="envs/imap.env")

X_API_KEY = os.getenv("X_API_KEY")
GPT_API_KEY = os.getenv("GPT_API_KEY")

IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
IMAP_USERNAME = os.getenv("IMAP_USERNAME")
TOKEN_VAL = os.getenv("TOKEN")

IMAP_SETTINGS = {
    "imap_server": IMAP_SERVER,
    "imap_port": 993,
    "username": IMAP_USERNAME,
    "password": IMAP_PASSWORD,
    "mailbox": "INBOX",
    "token": TOKEN_VAL
}

SMTP_SETTINGS = {
    "server": IMAP_SERVER,
    "port": 465,
    "user": IMAP_USERNAME,
    "password": IMAP_PASSWORD,
    "token": TOKEN_VAL
}


async def main():
    # 1. Инициализация API конфигурации
    api = APIConfig()

    # 2. Получение списка прокси
    actual_proxy_list = await api.get_actual_proxy_list()
    is_success = False

    # 3. Создание БД + дальнейшая обработка писем
    try:
        await setup_database()
        await init_base_mails()
    except Exception as e:
        logger.error(f"Ошибка при иницализации БД - {e}", exc_info=True)
        raise e

    for proxy in actual_proxy_list:
        try:
            logger.info(f"🔄 Пробуем подключиться через прокси: {proxy}")
            api.create_client(proxy=proxy)

            await download_media_and_process_emails(
                imap_server=IMAP_SETTINGS["imap_server"],
                imap_port=IMAP_SETTINGS["imap_port"],
                username=IMAP_SETTINGS["username"],
                password=IMAP_SETTINGS["password"],
                token=IMAP_SETTINGS["token"],
                mailbox=IMAP_SETTINGS["mailbox"],
                api_config=api,
                gpt_api_key=GPT_API_KEY,
                el_api_key=X_API_KEY,
                smtp_settings=SMTP_SETTINGS,
                max_retries=3
            )

            logger.info(f"✨ Весь почтовый пайплайн успешно отработал через прокси: {proxy}")
            is_success = True
            break

        except Exception as e:
            logger.warning(f"⚠️ Прокси {proxy} выдал ошибку в процессе пайплайна: {e}. Переключаемся...")
            continue

    if not is_success:
        logger.error("❌ Все прокси из списка были проверены, но пайплайн не смог завершиться успешно.")


if __name__ == "__main__":
    asyncio.run(main())