import os
import re
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.utils import get_column_letter


load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3"

if not API_KEY:
    raise RuntimeError("Не найден YOUTUBE_API_KEY в .env")


def api_get(endpoint: str, params: dict) -> dict:
    """
    Универсальный GET-запрос к YouTube Data API.
    """
    params["key"] = API_KEY

    response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"Ошибка API {response.status_code}:\n{response.text}"
        )

    return response.json()


def extract_channel_ref(text: str) -> str:
    """
    Принимает:
    - @handle
    - https://www.youtube.com/@handle
    - https://www.youtube.com/channel/UC...
    - UC...
    """
    text = text.strip()

    if text.startswith("http"):
        parsed = urlparse(text)
        path = parsed.path.strip("/")

        if path.startswith("@"):
            return path

        if path.startswith("channel/"):
            return path.split("/")[1]

        if path.startswith("user/"):
            return path.split("/")[1]

        if path.startswith("c/"):
            return path.split("/")[1]

    return text


def get_channel_info(channel_ref: str) -> dict:
    """
    Получает channel_id, название канала и uploads playlist.
    """
    channel_ref = extract_channel_ref(channel_ref)

    params = {
        "part": "snippet,contentDetails",
        "maxResults": 1,
    }

    if channel_ref.startswith("@"):
        params["forHandle"] = channel_ref
    elif channel_ref.startswith("UC"):
        params["id"] = channel_ref
    else:
        # Старый username-формат.
        # Для новых каналов лучше использовать @handle или /channel/UC...
        params["forUsername"] = channel_ref

    data = api_get("channels", params)

    items = data.get("items", [])
    if not items:
        raise RuntimeError(
            "Канал не найден. Лучше вставь ссылку вида https://www.youtube.com/@handle "
            "или https://www.youtube.com/channel/UC..."
        )

    item = items[0]

    return {
        "channel_id": item["id"],
        "channel_title": item["snippet"]["title"],
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def get_all_videos_from_uploads_playlist(playlist_id: str) -> list[dict]:
    """
    Получает все видео из uploads-плейлиста канала.
    """
    videos = []
    page_token = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }

        if page_token:
            params["pageToken"] = page_token

        data = api_get("playlistItems", params)

        for item in data.get("items", []):
            snippet = item["snippet"]

            # Иногда в плейлисте могут быть удалённые/приватные видео
            resource_id = snippet.get("resourceId", {})
            video_id = resource_id.get("videoId")

            if not video_id:
                continue

            videos.append({
                "video_id": video_id,
                "video_title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
            })

        page_token = data.get("nextPageToken")

        print(f"Собрано видео: {len(videos)}")

        if not page_token:
            break

        time.sleep(0.1)

    return videos


def get_replies_for_comment(parent_comment_id: str, video: dict) -> list[dict]:
    """
    Получает все ответы на один верхнеуровневый комментарий.
    """
    replies = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "parentId": parent_comment_id,
            "maxResults": 100,
            "textFormat": "plainText",
        }

        if page_token:
            params["pageToken"] = page_token

        try:
            data = api_get("comments", params)
        except RuntimeError as e:
            print(f"Не смог получить ответы для комментария {parent_comment_id}: {e}")
            return replies

        for item in data.get("items", []):
            snippet = item["snippet"]

            replies.append({
                "video_id": video["video_id"],
                "video_title": video["video_title"],
                "video_url": video["video_url"],
                "comment_id": item["id"],
                "parent_comment_id": parent_comment_id,
                "is_reply": True,
                "author": snippet.get("authorDisplayName", ""),
                "author_channel_url": snippet.get("authorChannelUrl", ""),
                "text": snippet.get("textDisplay", ""),
                "like_count": snippet.get("likeCount", 0),
                "published_at": snippet.get("publishedAt", ""),
                "updated_at": snippet.get("updatedAt", ""),
            })

        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(0.1)

    return replies


def get_comments_for_video(video: dict) -> list[dict]:
    """
    Получает все комментарии конкретного видео:
    - верхнеуровневые комментарии
    - ответы на них
    """
    comments = []
    page_token = None

    while True:
        params = {
            "part": "snippet",
            "videoId": video["video_id"],
            "maxResults": 100,
            "order": "time",
            "textFormat": "plainText",
        }

        if page_token:
            params["pageToken"] = page_token

        try:
            data = api_get("commentThreads", params)
        except RuntimeError as e:
            error_text = str(e)

            if "commentsDisabled" in error_text:
                print(f"Комментарии отключены: {video['video_title']}")
                return comments

            print(f"Ошибка при получении комментариев к видео {video['video_id']}: {e}")
            return comments

        for item in data.get("items", []):
            thread_snippet = item["snippet"]
            top_comment = thread_snippet["topLevelComment"]
            top_snippet = top_comment["snippet"]

            top_comment_id = top_comment["id"]

            comments.append({
                "video_id": video["video_id"],
                "video_title": video["video_title"],
                "video_url": video["video_url"],
                "comment_id": top_comment_id,
                "parent_comment_id": "",
                "is_reply": False,
                "author": top_snippet.get("authorDisplayName", ""),
                "author_channel_url": top_snippet.get("authorChannelUrl", ""),
                "text": top_snippet.get("textDisplay", ""),
                "like_count": top_snippet.get("likeCount", 0),
                "published_at": top_snippet.get("publishedAt", ""),
                "updated_at": top_snippet.get("updatedAt", ""),
            })

            total_reply_count = thread_snippet.get("totalReplyCount", 0)

            if total_reply_count > 0:
                replies = get_replies_for_comment(top_comment_id, video)
                comments.extend(replies)

        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(0.1)

    return comments


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip()
    return name[:100] or "youtube_comments"


def save_to_xlsx(rows: list[dict], filename: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "comments"

    headers = [
        "video_id",
        "video_title",
        "video_url",
        "comment_id",
        "parent_comment_id",
        "is_reply",
        "author",
        "author_channel_url",
        "text",
        "like_count",
        "published_at",
        "updated_at",
    ]

    ws.append(headers)

    for row in rows:
        ws.append([row.get(header, "") for header in headers])

    # Автоширина колонок
    for column_cells in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column_cells[0].column)

        for cell in column_cells:
            value = str(cell.value) if cell.value is not None else ""
            max_length = max(max_length, len(value))

        ws.column_dimensions[column_letter].width = min(max_length + 2, 70)

    # Чтобы текст комментариев переносился визуально
    for row in ws.iter_rows(min_row=2):
        row[8].alignment = row[8].alignment.copy(wrap_text=True)

    wb.save(filename)


def main():
    channel_input = input("Вставь @handle, ссылку на канал или channel_id: ").strip()

    channel_info = get_channel_info(channel_input)

    print(f"Канал: {channel_info['channel_title']}")
    print(f"Channel ID: {channel_info['channel_id']}")
    print(f"Uploads playlist: {channel_info['uploads_playlist_id']}")

    videos = get_all_videos_from_uploads_playlist(
        channel_info["uploads_playlist_id"]
    )

    print(f"Всего видео найдено: {len(videos)}")

    all_comments = []

    for index, video in enumerate(videos, start=1):
        print(f"\n[{index}/{len(videos)}] {video['video_title']}")
        video_comments = get_comments_for_video(video)
        all_comments.extend(video_comments)

        print(
            f"Комментарии у видео: {len(video_comments)} | "
            f"Всего собрано: {len(all_comments)}"
        )

    filename = safe_filename(channel_info["channel_title"]) + "_comments.xlsx"
    save_to_xlsx(all_comments, filename)

    print(f"\nГотово. Файл сохранён: {filename}")
    print(f"Всего строк с комментариями: {len(all_comments)}")


if __name__ == "__main__":
    main()