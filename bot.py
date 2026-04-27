import os
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from commpars import parse_channel_to_xlsx


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_BOT_TOKEN в .env")


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет. Отправь мне ссылку на YouTube-канал или @handle.\n\n"
        "Пример:\n"
        "https://www.youtube.com/@GoogleDevelopers\n\n"
        "Или:\n"
        "@GoogleDevelopers\n\n"
        "Я соберу комментарии со всех доступных видео и отправлю XLSX-файл."
    )

    await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться:\n\n"
        "1. Отправь ссылку на канал или @handle.\n"
        "2. Подожди, пока бот соберёт видео и комментарии.\n"
        "3. Получи Excel-файл.\n\n"
        "Важно: если у канала очень много видео и комментариев, процесс может быть долгим."
    )

    await update.message.reply_text(text)


async def parse_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_input = update.message.text.strip()

    if not channel_input:
        await update.message.reply_text("Отправь ссылку на канал или @handle.")
        return

    if not (
        channel_input.startswith("@")
        or "youtube.com" in channel_input
        or channel_input.startswith("UC")
    ):
        await update.message.reply_text(
            "Похоже, это не ссылка на канал и не @handle.\n\n"
            "Пример:\n"
            "https://www.youtube.com/@GoogleDevelopers"
        )
        return

    if context.user_data.get("is_parsing"):
        await update.message.reply_text(
            "Я уже собираю комментарии для прошлого канала. Дождись завершения."
        )
        return

    context.user_data["is_parsing"] = True

    status_message = await update.message.reply_text(
        "Начал сбор комментариев. Это может занять время, особенно если у канала много видео."
    )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        # Запускаем обычный синхронный парсер в отдельном потоке,
        # чтобы Telegram-бот не завис полностью.
        result = await asyncio.to_thread(parse_channel_to_xlsx, channel_input)

        filename = result["filename"]
        file_path = Path(filename)

        if not file_path.exists():
            await status_message.edit_text("Парсер завершился, но XLSX-файл не найден.")
            return

        file_size_mb = file_path.stat().st_size / 1024 / 1024

        if file_size_mb > 49:
            await status_message.edit_text(
                f"Файл получился слишком большой: {file_size_mb:.1f} MB.\n"
                "Telegram-бот может не отправить такой файл. Нужно будет делить XLSX на части."
            )
            return

        await status_message.edit_text(
            "Готово. Отправляю файл.\n\n"
            f"Канал: {result['channel_title']}\n"
            f"Видео найдено: {result['videos_count']}\n"
            f"Комментариев собрано: {result['comments_count']}"
        )

        with open(file_path, "rb") as document:
            await update.message.reply_document(
                document=document,
                filename=file_path.name,
                caption=(
                    f"Комментарии канала: {result['channel_title']}\n"
                    f"Видео: {result['videos_count']}\n"
                    f"Комментариев: {result['comments_count']}"
                ),
                write_timeout=120,
                read_timeout=120,
                connect_timeout=60,
            )

    except Exception as e:
        logging.exception("Ошибка при парсинге канала")

        await status_message.edit_text(
            "Произошла ошибка при сборе комментариев.\n\n"
            f"Ошибка:\n{e}"
        )

    finally:
        context.user_data["is_parsing"] = False


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            parse_channel_handler,
        )
    )

    print("Бот запущен.")
    app.run_polling()


if __name__ == "__main__":
    main()