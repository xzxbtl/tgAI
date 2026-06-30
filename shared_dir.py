from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DIR_TO_MEDIA = BASE_DIR / "media"
DIR_TO_TEXT = BASE_DIR / "transcription_text"          # Промежуточные транскрипты
DIR_TO_REFORMATED_TEXT = BASE_DIR / "reformatted_gpt"  # Промежуточные отчеты GPT
DIR_READY_TO_UPLOAD = BASE_DIR / "ready_to_upload"     # ФИНАЛЬНЫЕ отчеты (ОТДЕЛЬНО)


def create_media_dir():
    if not DIR_TO_MEDIA.exists():
        DIR_TO_MEDIA.mkdir()


def create_text_dir():
    if not DIR_TO_TEXT.exists():
        DIR_TO_TEXT.mkdir()


def create_reformated_text_dir():
    if not DIR_TO_REFORMATED_TEXT.exists():
        DIR_TO_REFORMATED_TEXT.mkdir()