import base64
import imaplib
import shutil
import smtplib
import email
import uuid
import asyncio
import re
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from email.message import EmailMessage
from email.policy import default
from pathlib import Path
from zoneinfo import ZoneInfo
from app.api.elevenlabs_requests import create_transcript
from app.api.gpt_report import create_reformated_gpt_report
from app.database.core import take_all_mails, add_log
from app.utils.loggs.logger_conf import logger
from app.shared_dir import DIR_TO_MEDIA, DIR_TO_REFORMATED_TEXT as DIR_READY_TO_UPLOAD, DIR_TO_TEXT, \
    DIR_TO_REFORMATED_TEXT
from app.api.api_config import APIConfig

MEDIA_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
}
CLOUD_PATTERNS = {
    "google": re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)([-_a-zA-Z0-9]+)"),
    "yandex": re.compile(r"disk\.yandex\.ru/d/([-_a-zA-Z0-9]+)"),
    "mailru": re.compile(r"cloud\.mail\.ru/public/([-a-zA-Z0-9]+)/([-a-zA-Z0-9]+)")
}


async def download_from_cloud(full_body: str, api_client) -> Path | None:
    """Определяет сервис и скачивает файл по ссылке."""

    # 1. Google Drive (уже есть логика с download_warning)
    match_google = CLOUD_PATTERNS["google"].search(full_body)
    if match_google:
        file_id = match_google.group(1)
        save_path = DIR_TO_MEDIA / f"{uuid.uuid4().hex}.mp3"
        if await download_from_google_drive(file_id, api_client, save_path):
            return save_path

    # 2. Яндекс.Диск (требует Public API)
    match_yandex = CLOUD_PATTERNS["yandex"].search(full_body)
    if match_yandex:
        public_key = match_yandex.group(1)
        api_url = f"https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key={public_key}"
        resp = await api_client.get(api_url)
        if resp.status_code == 200:
            direct_link = resp.json().get("href")
            save_path = DIR_TO_MEDIA / f"{uuid.uuid4().hex}.mp3"
            file_resp = await api_client.get(direct_link)
            with open(save_path, "wb") as f:
                f.write(file_resp.content)
            return save_path

    return None


def _build_xoauth2_string(username: str, access_token: str) -> str:
    auth_string = f"user={username}\1auth=Bearer {access_token}\1\1"
    return base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _imap_authenticate(
        mail: imaplib.IMAP4,
        username: str,
        password: str | None = None,
        token: str | None = None,
) -> None:
    if password and not token:
        mail.login(username, password)
        return

    if token:
        try:
            xoauth2_b64 = _build_xoauth2_string(username, token)
            mail.authenticate("XOAUTH2", lambda _: xoauth2_b64)
            return
        except imaplib.IMAP4.error as e:
            if "Unsupported authentication mechanism" in str(e) and password:
                logger.warning("⚠️ Сервер не поддерживает токен (XOAUTH2). Пробуем авторизацию по паролю...")
                mail.login(username, password)
                return
            else:
                raise e
    raise ValueError("Для IMAP-аутентификации нужен password или token")


def _send_email_reply_sync(smtp_settings: dict, to_address: str, custom_subject: str, report_file_path: Path):
    msg = EmailMessage()

    cleaned_subject = str(custom_subject).replace('\n', ' ').replace('\r', ' ').strip()
    cleaned_subject = " ".join(cleaned_subject.split())

    if len(cleaned_subject) > 150:
        cleaned_subject = cleaned_subject[:147] + "..."

    msg['Subject'] = f"Отчет GPT: {cleaned_subject}"

    msg['From'] = smtp_settings['user']
    msg['To'] = to_address
    msg.set_content(
        f"Здравствуйте!\n\n"
        f"Во вложении ваш обработанный транскрипт и краткий аналитический отчет GPT на тему:\n"
        f"«{cleaned_subject}»."
    )

    with open(report_file_path, 'rb') as f:
        file_data = f.read()
        file_name = report_file_path.name

    msg.add_attachment(file_data, maintype='text', subtype='plain', filename=file_name)

    with smtplib.SMTP_SSL(smtp_settings['server'], smtp_settings['port'], timeout=15) as server:
        server.login(smtp_settings['user'], smtp_settings['password'])
        server.send_message(msg)


async def download_from_google_drive(file_id: str, api_client, save_path: Path) -> bool:
    """Асинхронно скачивает файл с Google Диска, обходя страницу предупреждения о большом размере (вирусах)."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        # 1. Делаем первый запрос. Google может вернуть файл сразу или страницу-предупреждение.
        response = await api_client.get(url, follow_redirects=True)

        # 2. Ищем cookie 'download_warning', который Google выдает большим файлам
        confirm_token = None
        for cookie in response.cookies.jar:
            if cookie.name.startswith("download_warning"):
                confirm_token = cookie.value
                break

        # 3. Если нашли токен, делаем второй запрос с подтверждением
        if confirm_token:
            url = f"https://drive.google.com/uc?export=download&confirm={confirm_token}&id={file_id}"
            response = await api_client.get(url, follow_redirects=True)

        # 4. Сохраняем файл стримингом (чтобы не забить оперативную память тяжелым аудио)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
            return True
        else:
            logger.warning(f"Google Drive вернул ошибку: {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"Ошибка при скачивании с Google Диска: {e}")
        return False


async def process_single_email(
        mail: imaplib.IMAP4,
        uid: str,
        api_config: APIConfig,
        gpt_api_key: str,
        el_api_key: str,
        smtp_settings: dict,
        subject: str,
        sender_email: str
) -> bool:
    logger.info(f"📌 Скачиваем тело письма UID={uid} от {sender_email}")
    st, full_data = mail.fetch(uid, "(RFC822)")
    if st != "OK" or not full_data:
        logger.warning(f"Не удалось получить тело письма UID={uid}")
        return False

    raw_body = None
    for part in full_data:
        if isinstance(part, tuple):
            raw_body = part[1]
            break

    if not isinstance(raw_body, bytes):
        return False

    msg = email.message_from_bytes(raw_body, policy=default)

    email_date = None
    email_date_str = msg.get("Date")
    if email_date_str:
        email_date = parsedate_to_datetime(email_date_str).strftime("%Y-%m-%d")

    # === ПЕРЕМЕННЫЕ ДЛЯ ТРЕКИНГА И ОЧИСТКИ ===
    downloaded_files = []
    file_stems = []
    is_success = False
    gpt_report_path = None

    try:
        DIR_TO_MEDIA.mkdir(parents=True, exist_ok=True)
        email_text_parts = []

        # Ищем вложения и текст
        for part in msg.walk():
            content_type = part.get_content_type()
            disp = part.get("Content-Disposition", "") or ""

            if content_type in ["text/plain", "text/html"] and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True)
                if payload:
                    email_text_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))

            if "attachment" in disp.lower():
                filename = part.get_filename()
                filename = _decode_mime_header(filename) if filename else ""
                if filename:
                    ext = Path(filename).suffix.lower()
                    if ext in MEDIA_EXTENSIONS:
                        # Генерируем корень имени файла
                        file_stem = uuid.uuid4().hex
                        unique_filename = f"{file_stem}{ext}"
                        filepath = DIR_TO_MEDIA / unique_filename

                        payload = part.get_payload(decode=True)
                        if payload:
                            with open(filepath, "wb") as f:
                                f.write(payload)
                            downloaded_files.append(filepath)
                            file_stems.append(file_stem)
                            logger.info(f"📦 Найдено вложение: {filename} -> {unique_filename}")

        full_email_body = "\n".join(email_text_parts)

        # Проверка на ссылку Google Drive
        if not downloaded_files:
            cloud_file = await download_from_cloud(full_email_body, api_config.client)
            if cloud_file:
                downloaded_files.append(cloud_file)
                file_stems.append(cloud_file.stem)

        if is_success:
            DIR_READY_TO_UPLOAD.mkdir(exist_ok=True)
            final_path = DIR_READY_TO_UPLOAD / gpt_report_path.name
            shutil.move(str(gpt_report_path), str(final_path))
            is_success = True

        target_media = downloaded_files[0]
        user_instruction = f"Тема письма: {subject}\nТекст письма:\n{full_email_body.strip()}"

        # 1. Транскрибация ElevenLabs (сохранит в DIR_TO_TEXT / {stem}.txt)
        logger.info(f"🎙️ UID={uid}: Старт транскрибации...")
        transcript_path = await create_transcript(api=api_config, file_path=target_media, x_api_key=el_api_key)
        if not transcript_path:
            raise ValueError("ElevenLabs вернул пустой путь.")

        # 2. Генерация отчета GPT (сохранит в DIR_TO_REFORMATED_TEXT / reformated_{stem}.txt)
        logger.info(f"🤖 UID={uid}: Старт генерации отчета через GPT...")
        gpt_report_path, gpt_subject = await create_reformated_gpt_report(
            api=api_config,
            file_path=transcript_path,
            prompt=user_instruction,
            gpt_api_key=gpt_api_key,
            email_date=email_date
        )

        # 3. Отправка ответа
        logger.info(f"📧 UID={uid}: Отправка ответа на {sender_email} с темой: {gpt_subject}...")
        await asyncio.to_thread(
            _send_email_reply_sync, smtp_settings, sender_email, gpt_subject, gpt_report_path
        )
        # 4. Успешное перемещение
        DIR_READY_TO_UPLOAD.mkdir(parents=True, exist_ok=True)
        final_save_path = DIR_READY_TO_UPLOAD / gpt_report_path.name
        shutil.move(str(gpt_report_path), str(final_save_path))
        logger.info(f"📁 Финальный отчет отправлен и сохранен в: {final_save_path}")
        return True

    except Exception as e:
        logger.error(f"💥 Ошибка в пайплайне для письма UID={uid}: {e}", exc_info=True)
        return False

    finally:
        logger.debug(f"🧹 Запуск очистки временных файлов для UID={uid}...")
        for f in downloaded_files:
            if f.exists(): f.unlink()

        for stem in file_stems:
            t_path = DIR_TO_TEXT / f"{stem}.txt"
            if t_path.exists(): t_path.unlink()

            g_path = DIR_TO_REFORMATED_TEXT / f"reformated_{stem}.txt"
            if g_path.exists(): g_path.unlink()


async def download_media_and_process_emails(
        imap_server: str,
        username: str,
        api_config: APIConfig,
        gpt_api_key: str,
        el_api_key: str,
        smtp_settings: dict,
        password: str | None = None,
        token: str | None = None,
        imap_port: int = 993,
        mailbox: str = "INBOX",
        tz_name: str = "Europe/Moscow",
        date_now: datetime | None = None,
        max_retries: int = 3
):
    if date_now is None:
        date_now = datetime.now(ZoneInfo(tz_name))

    logger.info("🚀 Старт загрузки медиа-писем и генерации отчетов")

    daily_date = date_now.date()
    weekly_date_from = daily_date - timedelta(days=7)
    since_str = weekly_date_from.strftime("%d-%b-%Y")

    logger.info(f"🔎 Ищем непрочитанные письма за период с: {weekly_date_from.strftime('%d.%m.%Y')}")

    if imap_port == 993:
        mail = imaplib.IMAP4_SSL(imap_server, imap_port, timeout=60)
    else:
        mail = imaplib.IMAP4(imap_server, imap_port, timeout=60)
        mail.starttls()

    try:
        allowed_mails = await take_all_mails()
        logger.info("🔌 Подключение к IMAP серверу")
        logger.info("🔐 Аутентификация в IMAP")
        _imap_authenticate(mail=mail, username=username, password=password, token=token)

        logger.info(f"📬 Выбор папки: {mailbox}")
        status, _ = mail.select(mailbox)
        if status != "OK":
            raise RuntimeError(f'Не удалось открыть mailbox "{mailbox}"')

        search_criterion = f'(UNSEEN SINCE "{since_str}")'
        status, data = mail.search(None, search_criterion)
        uids = data[0].split() if status == "OK" and data and data[0] else []

        logger.info(f"📨 Найдено непрочитанных писем: {len(uids)}")

        if not uids:
            logger.info("ℹ️ Нет новых писем для обработки.")
            return

        for raw_uid in reversed(uids):
            uid = raw_uid.decode(errors="ignore")
            logger.info(f"🔄 🆔 Начало обработки письма UID={uid}")

            st, msg_data = mail.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE FROM)])")
            if st != "OK" or not msg_data:
                continue

            raw_hdr = None
            for part in msg_data:
                if isinstance(part, tuple):
                    raw_hdr = part[1]
                    break

            if not isinstance(raw_hdr, bytes):
                continue

            hdr = email.message_from_bytes(raw_hdr, policy=default)
            subj = _decode_mime_header(hdr.get("Subject", "Без темы"))
            raw_date = hdr.get("Date", "")
            _, sender_email = parseaddr(hdr.get("From", ""))

            if not sender_email:
                continue

            if sender_email not in allowed_mails:
                continue

            success = False
            for attempt in range(1, max_retries + 1):
                try:
                    success = await process_single_email(
                        mail=mail,
                        uid=uid,
                        api_config=api_config,
                        gpt_api_key=gpt_api_key,
                        el_api_key=el_api_key,
                        smtp_settings=smtp_settings,
                        subject=subj,
                        sender_email=sender_email
                    )
                    if success:
                        break
                except Exception as ex:
                    logger.error(f"UID={uid}: Исключение на попытке {attempt}/{max_retries} — {ex}")

                if not success and attempt < max_retries:
                    await asyncio.sleep(5)

            if success:
                try:
                    mail.copy(uid, 'Trash')
                    mail.store(uid, '+FLAGS', '\\Deleted')
                    mail.expunge()
                    await add_log(
                        mail=sender_email,
                        action=f"Успешные ответ на генерацию: UID={uid}",
                        date=date_now
                    )
                    logger.info(f"🧹 Письмо UID={uid} успешно обработано и удалено из {mailbox}.")
                except Exception as delete_err:
                    logger.error(f"❌ Ошибка удаления письма UID={uid}: {delete_err}")
            else:
                try:
                    mail.store(uid, '-FLAGS', '\\Seen')
                    logger.error(f"❌ Письмо UID={uid} НЕ обработано. Статус 'Непрочитано' восстановлен.")
                    await add_log(
                        mail=sender_email,
                        action=f"Ошибка при попытке обработки письма с UID={uid}",
                        date=date_now
                    )
                except Exception as flag_err:
                    logger.error(f"❌ Ошибка: {flag_err}")
                    await add_log(
                        mail=sender_email,
                        action=f"Стороняя ошибка: {str(flag_err)[:64] + '...'}",
                        date=date_now
                    )

    except Exception as e:
        logger.error(f"💥 Критическая ошибка при обработке писем: {e}", exc_info=True)
        raise
    finally:
        logger.info("🔌 Закрытие IMAP-соединения")
        try:
            mail.logout()
        except:
            pass
