import sys
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database.config import settings
from app.database.models import Base, Logs, Mails
from app.utils.loggs.logger_conf import logger

if sys.platform.startswith('win') and os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async_engine = create_async_engine(settings.DataBase_URL_psycopg, echo=False, pool_size=20, max_overflow=50)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

BASE_MAILS = [
    "ogtonyworking@gmail.com",
    "xzxbtl@gmail.com",
    "medvedev_a@unas.ru"
]


async def setup_database():
    async with async_engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all)
            return True
        except Exception as e:
            logger.error(f"Database creation failed: {e}", exc_info=True)
    return logger.info("Base Table Created")


async def init_base_mails():
    """Инициализация базы данных базовыми адресами при старте приложения"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            for mail in BASE_MAILS:
                exists = await session.execute(select(Mails).where(Mails.mail == mail))
                if not exists.scalar_one_or_none():
                    session.add(Mails(mail=mail))
    logger.info("Базовые адреса успешно проверены/добавлены в БД.")


async def take_all_mails() -> list[str]:
    """Быстро открывает соединение, забирает разрешенные email и закрывает его"""
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Mails.mail))
        mails = res.scalars().all()

        if mails:
            return list(mails)
        else:
            logger.error("No mails found")
            return []


async def add_log(mail: str, action: str, date: datetime):
    """Изолированная быстрая запись лога. Сессия живет ровно долю секунды"""
    async with AsyncSessionLocal() as session:
        try:
            new_log = Logs(
                mail=mail,
                action=action,
                date=date
            )
            session.add(new_log)
            await session.commit()  # Сохраняем и закрываем соединение
        except Exception as e:
            logger.error(f"Database insertion failed: {e}", exc_info=True)
            await session.rollback()


@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
