import json
from datetime import datetime
from pathlib import Path
from app.api.api_config import APIConfig
from app.shared_dir import DIR_TO_REFORMATED_TEXT
from openai import AsyncOpenAI
from app.utils.loggs.logger_conf import logger

SYSTEM_PROMPT = """
You are a professional business analyst and data summarizer. 
Your task is to generate a comprehensive, structured report based on the provided dialogue.

You MUST respond with a strict, valid JSON object containing exactly two keys: "subject_summary" and "report".

1. "subject_summary": A very short, concise sentence in Russian (5-7 words max) describing the core topic of the meeting/dialogue. This will be used as an email subject line. Examples: "Обсуждение дизайна мобильного приложения", "Правки по договору поставок", "Интервью с кандидатом на вакансию". Do not use generic phrases like "Краткий отчет" or "Итоги созвона".
2. "report": The full analytical report in Russian structured exactly as follows:
   1. **Краткое резюме**: A concise 2-3 sentence overview of the dialogue's main topic and final outcome.
   2. **Ключевые темы обсуждения**: A bulleted list of the core topics discussed.
   3. **Принятые решения и план действий**: Clear list of agreed-upon conclusions.
   4. **Общие выводы**: A brief closing summary.

CRITICAL GUIDELINES:
- Your response must be parsed as JSON. Do not include Markdown blocks like ```json ... ``` around your raw JSON output.
- If you receive additional instructions under "# User Instruction" (e.g., specific words to add, formatting, greetings), you MUST strictly execute them inside the "report" field.
- Be objective, precise, and concise.
- Do not invent any facts not mentioned in the text.
"""


async def create_reformated_gpt_report(
        api: APIConfig,
        file_path: Path = None,
        prompt: str = None,
        gpt_api_key: str = None,
        email_date: str = datetime.now().strftime("%Y-%m-%d"),
) -> tuple[Path, str]:
    openai_client = None
    api_client = api.client
    DIR_TO_REFORMATED_TEXT.mkdir(parents=True, exist_ok=True)

    try:
        logger.debug("Попытка создания клиента GPT.")
        openai_client = AsyncOpenAI(
            api_key=gpt_api_key,
            http_client=api_client
        )
        logger.info("Успешное создание GPT клиента.")

    except Exception as e:
        logger.error(f"Ошибка при создании GPT клиента - {e}.", exc_info=True)
        raise e

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            document_text = file.read()

        system_prompt = f"# SYSTEM PROMPT\n{SYSTEM_PROMPT}"

        user_content = ""
        if prompt:
            user_content += f"# User Instruction: {prompt}\n\n"
        user_content += f"# Document Text:\n{document_text}"

        response = await openai_client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"}
        )
        raw_json = response.choices[0].message.content
        data = json.loads(raw_json)

        subject_summary = data.get("subject_summary", "Аналитический отчет").strip()
        if isinstance(subject_summary, str):
            subject_summary = subject_summary.strip()
        else:
            subject_summary = str(subject_summary)

        report_data = data.get("report", "")
        if isinstance(report_data, dict):
            lines = []
            for key, value in report_data.items():
                lines.append(f"## {key}")
                if isinstance(value, list):
                    for item in value:
                        lines.append(f"- {item}")
                else:
                    lines.append(str(value))
                lines.append("")
            reformatted_text = "\n".join(lines).strip()
        else:
            reformatted_text = str(report_data).strip()

        output_file_path = DIR_TO_REFORMATED_TEXT / f"reformated_{file_path.stem}_{email_date}.txt"

        with open(output_file_path, "w", encoding="utf-8") as output_file:
            output_file.write(reformatted_text)

        logger.info(f"Отформатированный отчет успешно сохранен в: {output_file_path}.")
        return output_file_path, subject_summary

    except Exception as e:
        logger.error(f"Ошибка при чтении и генерации отчета GPT - {e}.", exc_info=True)
        raise e


