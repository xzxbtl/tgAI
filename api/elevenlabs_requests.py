from elevenlabs.client import AsyncElevenLabs
from app.api.api_config import APIConfig
from app.utils.loggs.logger_conf import logger
from app.shared_dir import DIR_TO_TEXT
from pathlib import Path


async def create_transcript(
        api: APIConfig,
        file_path: Path,
        x_api_key: str = None
):
    DIR_TO_TEXT.mkdir(parents=True, exist_ok=True)

    if not file_path or not file_path.exists() or not file_path.is_file():
        logger.warning(f"Файл для транскрибации не найден: {file_path}")
        return None

    api_client = api.client

    try:
        logger.debug("Попытка создания ElevenLabs клиента.")
        eleven_labs_client = AsyncElevenLabs(
            httpx_client=api_client,
            timeout=api.timeout,
            api_key=x_api_key
        )
        logger.info("Успешное создание клиента ElevenLabs.")

    except Exception as e:
        logger.error(f"Ошибка при создании клиента ElevenLabs. - {e}", exc_info=True)
        raise e

    try:
        logger.debug(f"Начало обработки файла: {file_path.name}.")

        with open(file_path, "rb") as audio_file:
            response = await eleven_labs_client.speech_to_text.convert(
                model_id="scribe_v2",
                language_code="ru",
                tag_audio_events=False,
                diarize=True,
                file=audio_file
            )

        dialogue_lines = []
        current_speaker = None
        current_phrase = []

        for word_info in response.words:
            spk_id = word_info.speaker_id if word_info.speaker_id else "unknown"

            if spk_id.startswith("speaker_"):
                try:
                    spk_num = int(spk_id.split("_")[1]) + 1
                    formatted_speaker = f"Спикер {spk_num}"
                except ValueError:
                    formatted_speaker = spk_id
            else:
                formatted_speaker = "Спикер 1" if spk_id == "unknown" else spk_id

            if current_speaker != formatted_speaker:
                if current_speaker is not None:
                    dialogue_lines.append(f"{current_speaker}: {''.join(current_phrase).strip()}")
                current_speaker = formatted_speaker
                current_phrase = [word_info.text]
            else:
                current_phrase.append(word_info.text)

        if current_speaker is not None:
            dialogue_lines.append(f"{current_speaker}: {''.join(current_phrase).strip()}")

        final_text = "\n".join(dialogue_lines)

        output_txt_path = DIR_TO_TEXT / f"{file_path.stem}.txt"

        with open(output_txt_path, "w", encoding="utf-8") as txt_file:
            txt_file.write(final_text)

        logger.info(f"Успешно обработан файл: {file_path.name}. Текст сохранен в {output_txt_path.name}")
        return output_txt_path

    except Exception as e:
        logger.error(
            f"Ошибка транскрибации файла {file_path.name}: {e}",
            exc_info=True
        )
        raise e

