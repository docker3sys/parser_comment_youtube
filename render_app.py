import os
import threading

import uvicorn
from fastapi import FastAPI

from bot import main as bot_main


app = FastAPI()


@app.get("/")
def home():
    return {
        "ok": True,
        "service": "youtube-comments-telegram-bot",
    }


def run_web_server():
    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )


if __name__ == "__main__":
    print("Запускаю web server для Render...", flush=True)

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True,
    )
    web_thread.start()

    print("Запускаю Telegram-бота...", flush=True)

    bot_main()