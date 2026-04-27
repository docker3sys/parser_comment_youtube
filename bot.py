import os
import time
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


def is_valid_channel_input(text: str) -> bool:
    text = text.strip()

    return (
        text.startswith("@")
        or text.startswith("UC")
        or "youtube.com" in text
        or "youtu.be" in text
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Отправь мне ссылку на YouTube-канал или @handle.\n\n"
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
        "2. Бот соберёт список видео.\n"
        "3. Бот соберёт комментарии.\n"
        "4. В конце пришлёт Excel-файл.\n\n"
        "Важно: если у канала много видео и комментариев, процесс может идти долго.\n\n"
        "Команда /cancel пока не останавливает уже запущенный поток парсинга, "
        "но блокировку пользователя сбрасывает."
    )

    await update.message.reply_text(text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["is_parsing"] = False

    await update.message.reply_text(
        "Ок, сбросил статус задачи. "
        "Если парсер уже запущен внутри потока, он может ещё доработать в терминале."
    )


async def parse_channel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_input = update.message.text.strip()

    if not channel_input:
        await update.message.reply_text("Отправь ссылку на канал или @handle.")
        return

    if not is_valid_channel_input(channel_input):
        await update.message.reply_text(
            "Похоже, это не ссылка на канал и не @handle.\n\n"
            "Пример:\n"
            "https://www.youtube.com/@GoogleDevelopers\n\n"
            "Или:\n"
            "@GoogleDevelopers"
        )
        return

    if context.user_data.get("is_parsing"):
        await update.message.reply_text(
            "Я уже собираю комментарии для прошлого канала. Дождись завершения."
        )
        return

    context.user_data["is_parsing"] = True

    status_message = await update.message.reply_text(
        "Начал сбор комментариев. Сейчас ищу канал..."
    )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        loop = asyncio.get_running_loop()
        last_update_time = 0

        async def edit_progress(data: dict):
            stage = data.get("stage")
            channel_title = data.get("channel_title", "")
            videos_count = data.get("videos_count", 0)
            comments_count = data.get("comments_count", 0)
            errors_count = data.get("errors_count", 0)
            current_video_index = data.get("current_video_index", 0)
            current_video_title = data.get("current_video_title", "")

            if stage == "channel_found":
                text = (
                    "Канал найден.\n\n"
                    f"Канал: {channel_title}\n"
                    "Сейчас получаю список видео..."
                )

            elif stage == "videos_loaded":
                text = (
                    "Список видео получен.\n\n"
                    f"Канал: {channel_title}\n"
                    f"Видео найдено: {videos_count}\n\n"
                    "Начинаю собирать комментарии..."
                )

            elif stage in ["video_started", "video_finished"]:
                short_title = current_video_title[:90]

                text = (
                    "Собираю комментарии...\n\n"
                    f"Канал: {channel_title}\n"
                    f"Видео: {current_video_index} / {videos_count}\n"
                    f"Комментариев собрано: {comments_count}\n"
                    f"Ошибок/отключённых комментариев: {errors_count}\n\n"
                    f"Сейчас:\n{short_title}"
                )

            elif stage == "saving_xlsx":
                text = (
                    "Сбор завершён. Сохраняю Excel-файл...\n\n"
                    f"Канал: {channel_title}\n"
                    f"Видео обработано: {videos_count}\n"
                    f"Комментариев собрано: {comments_count}\n"
                    f"Ошибок/отключённых комментариев: {errors_count}"
                )

            elif stage == "xlsx_saved":
                text = (
                    "Excel-файл готов. Готовлю отправку в Telegram...\n\n"
                    f"Канал: {channel_title}\n"
                    f"Видео обработано: {videos_count}\n"
                    f"Комментариев собрано: {comments_count}\n"
                    f"Ошибок/отключённых комментариев: {errors_count}"
                )

            else:
                return

            try:
                await status_message.edit_text(text)
            except Exception as e:
                print(f"Не смог обновить сообщение прогресса: {e}")

        def progress_callback(data: dict):
            nonlocal last_update_time

            now = time.time()
            stage = data.get("stage")

            important_stages = {
                "channel_found",
                "videos_loaded",
                "saving_xlsx",
                "xlsx_saved",
            }

            if stage not in important_stages and now - last_update_time < 3:
                return

            last_update_time = now

            asyncio.run_coroutine_threadsafe(
                edit_progress(data),
                loop,
            )

        result = await asyncio.to_thread(
            parse_channel_to_xlsx,
            channel_input,
            progress_callback,
        )

        print("Парсер вернул result:", result)

        filename = result["filename"]
        file_path = Path(filename)

        print("Путь к файлу:", file_path)
        print("Файл существует:", file_path.exists())

        if not file_path.exists():
            await status_message.edit_text("Парсер завершился, но XLSX-файл не найден.")
            return

        file_size_mb = file_path.stat().st_size / 1024 / 1024
        print(f"Размер файла: {file_size_mb:.2f} MB")

        if file_size_mb > 49:
            await status_message.edit_text(
                f"Файл получился слишком большой: {file_size_mb:.1f} MB.\n\n"
                "Telegram-бот может не отправить такой файл. "
                "Нужно будет делить XLSX на части."
            )
            return

        await status_message.edit_text(
            "Готово. Отправляю файл.\n\n"
            f"Канал: {result['channel_title']}\n"
            f"Видео найдено: {result['videos_count']}\n"
            f"Комментариев собрано: {result['comments_count']}\n"
            f"Ошибок/отключённых комментариев: {result['errors_count']}"
        )

        print("Начинаю отправку файла в Telegram...")

        with open(file_path, "rb") as document:
            await update.message.reply_document(
                document=document,
                filename=file_path.name,
                caption=(
                    f"Комментарии канала: {result['channel_title']}\n"
                    f"Видео: {result['videos_count']}\n"
                    f"Комментариев: {result['comments_count']}\n"
                    f"Ошибок/отключённых: {result['errors_count']}"
                ),
                write_timeout=300,
                read_timeout=300,
                connect_timeout=60,
                pool_timeout=60,
            )

        print("Файл успешно отправлен.")

        try:
            file_path.unlink()
            print("Файл удалён после отправки.")
        except Exception as e:
            print(f"Не смог удалить файл: {e}")

    except Exception as e:
        logging.exception("Ошибка при парсинге канала")

        try:
            await status_message.edit_text(
                "Произошла ошибка при сборе комментариев.\n\n"
                f"Ошибка:\n{e}"
            )
        except Exception:
            await update.message.reply_text(
                "Произошла ошибка при сборе комментариев.\n\n"
                f"Ошибка:\n{e}"
            )

    finally:
        context.user_data["is_parsing"] = False


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            parse_channel_handler,
        )
    )

    print("Бот запущен.", flush=True)
    app.run_polling(
        drop_pending_updates=True,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()