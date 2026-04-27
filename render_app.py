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


def run_bot():
    bot_main()


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.getenv("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )