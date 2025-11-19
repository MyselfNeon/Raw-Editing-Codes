import logging
import logging.config

# Get logging configurations
logging.config.fileConfig("logging.conf")
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

import os
import re
import time

import requests
from telegraph import Telegraph
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from utils import progress

try:
    import uvloop  # https://docs.pyrogram.org/topics/speedups#uvloop
    uvloop.install()
except ImportError:
    pass

class Bot(Client):  # pylint: disable=too-many-ancestors
    """Telegram bot client for uploading photos and creating posts on Telegra.ph."""

    def __init__(self):
        """Initializes the bot with the provided configuration."""
        super().__init__(
            "telegraph",
            bot_token=Config.BOT_TOKEN,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
        )

    async def start(self):
        """Starts the bot and prints the bot username."""
        Config.validate()
        await super().start()
        logger.info("Bot started successfully at @%s", self.me.username)
        logger.debug("Full bot info: %s", self.me)

    async def stop(self, *args, **kwargs):
        """Stops the bot and prints a stop message."""
        await super().stop(*args, **kwargs)
        logger.info("Bot session stopped gracefully.")

bot = Bot()
EMOJI_PATTERN = re.compile(r'<emoji id="\d+">')
TITLE_PATTERN = re.compile(r"title:? (.*)", re.IGNORECASE)

@bot.on_message(filters.command("start") & filters.incoming & filters.private)
async def start_handlers(_: Bot, message: Message) -> None:
    """Handles the /start command to provide a welcome message to the user."""
    logger.debug("Recieced /start command from user %s", message.from_user.first_name)
    await message.reply(
        text=(
            f"👋 **__Hello {message.from_user.mention}!__**\n\n"
            "__Welcome to **Telegraph Uploader Bot__** 🌐\n\n"
            "__With me, you can :__\n"
            "📸 **__Host Images**\nSend Me Any Photo, And I'll Immediately Upload It To **Imgbb** Or **Envs.sh**, Providing You With A Direct, Shareable Link__\n"
            "📝 **__Create Instant View Posts**\nSend me your Text, and I'll instantly convert it into a Beautifully formatted, Ad-free post on **Graph.org** (your Telegraph alternative)__\n\n"
            "📌 **__Usage__**:\n"
            "• __Send a **Photo** Get ImgBB/Envs.sh Link\n"
            "• __Send a **Text** in the following format Get Graph.org post with Link\n\n"
            "📝 **__Custom Title__**:\n"
            "```txt\n"
            "Title: {title}\n{content}\n"
            "```\n\n"
            "✅ **__Example__**:\n"
            "```txt\n"
            "Title: My First Graph.org Post\n"
            "This is the content of my first post!\n\n"
            "Here's a list of what I like:\n"
            "- Programming 💻\n"
            "- Reading 📚\n"
            "- Traveling ✈️\n"
            "- Music 🎵\n"
            "```\n\n"
            "🔗 **__About Graph.org__**:\n"
            "__Graph.org is a Minimalist Publishing tool (Alternative to Telegra.ph, which is Banned in India) that allows you to Share Beautifully formatted Posts with Text, Images, and more.__\n\n"
            "🖼️ **__About ImgBB & Envs.sh__**:\n"
            "- **__ImgBB__**\n__Permanent Image Hosting with fast Sharing Links.__\n"
            "- **__Envs.sh__**\n__Temporary Hosting (⚠️ Files may be Deleted after 30 Days).__\n\n"
            "🌟 **__Get Started Now!__** \nJust send a Photo or formatted Text message and let me handle the rest 🚀"
        ),
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👨‍💻 My Creator", url="https://t.me/MyselfNeon"
                    ),
                    InlineKeyboardButton(
                        "🛠 Source Code",
                        url="https://myselfneon.github.io/neon/",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📌 Updates", url="https://t.me/NeonFiles"
                    ),
                    InlineKeyboardButton("❤️ Support", url="https://t.me/+o1s-8MppL2syYTI9"),
                ],
            ]
        ),
        quote=True,
    )


def upload_file(file_path):
    """
    Uploads file to ImgBB (if API key is set).
    Falls back to envs.sh if ImgBB fails or API key missing.
    """
    imgbb_key = getattr(Config, "IMGBB_API_KEY", None)
    logger.debug("Attempting to upload file: %s", file_path)

    # 1. Try ImgBB first (if key exists)
    if imgbb_key:
        logger.debug("ImgBB API key found. Uploading to ImgBB...")
        try:
            with open(file_path, "rb") as f:
                files = {"image": f}
                response = requests.post(
                    "https://api.imgbb.com/1/upload",
                    params={"key": imgbb_key},
                    files=files,
                    timeout=15,
                )

            if response.ok:
                data = response.json()["data"]
                return {
                    "provider": "imgbb",
                    "url": data["url"],
                    "delete_url": data.get("delete_url"),
                }
            else:
                logger.warning("ImgBB upload failed: %s", response.text)

        except Exception as e:
            logger.error("Error uploading to ImgBB: %s", e, exc_info=True)

    # 2. Fallback: use envs.sh
    logger.debug("Falling back to envs.sh upload...")
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = requests.post("https://envs.sh", files=files, timeout=15)

        if response.ok:
            url = response.text.strip()
            logger.info("File uploaded to envs.sh: %s", url)
            return {"provider": "envs.sh", "url": url}
        else:
            logger.error("envs.sh upload failed: %s", response.text)

    except Exception as e:
        logger.critical("All upload methods failed: %s", e, exc_info=True)

@bot.on_message(filters.photo & filters.incoming & filters.private)
async def photo_handler(_: Bot, message: Message) -> None:
    """Handles incoming photo messages by uploading them to cloud providers."""

    try:
        logger.debug("Received photo from user_id=%s", message.from_user.id)
        msg = await message.reply_text("Processing....⏳", quote=True)

        location = f"./{message.from_user.id}{time.time()}/"
        start_time = time.time()
        logger.debug("Downloading photo to %s", location)

        file = await message.download(
            location, progress=progress, progress_args=(msg, start_time)
        )
        logger.info("Photo downloaded: %s", file)

        await msg.edit(
            "📥 **Download Complete!**\n\n"
            "☁️ Now uploading your file to the **cloud provider**..."
        )

        media_data = upload_file(file)
        if not media_data:
            logger.warning("Upload failed for file: %s", file)
            await msg.edit(
                "⚠️ Oops! We couldn’t upload your media file.\nPlease try again in a while."
            )
            return

        else:
            buttons = [[InlineKeyboardButton("🌐 View Image", url=media_data["url"])]]

            text = (
                f"[\u200B]({media_data['url']})✅ **Upload Successful!**\n\n"
                f"🖼️ [Click here to view the image]({media_data['url']})\n\n"
                f"📡 **Provider:** `{media_data['provider']}`\n\n"
                f"🔗 **Direct Link:** `{media_data['url']}`\n\n"
            )

            if media_data["provider"].lower() == "envs.sh":
                text += (
                    "\n⚠️ **Note:**\n\nFiles uploaded to **Envs.sh** may be automatically deleted "
                    "after **30 days**. This is **not** a permanent storage option.\n\n"
                )

            if media_data.get("delete_url"):
                buttons.append(
                    [
                        InlineKeyboardButton(
                            "🗑️ Delete Image", url=media_data["delete_url"]
                        )
                    ]
                )

            await msg.edit(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=False,
            )

    except FileNotFoundError:
        pass
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(e)
        await msg.edit(f"**Error:**\n{e}")
    finally:
        if os.path.exists(file):
            os.remove(file)
            os.rmdir(location)

@bot.on_message(filters.text & filters.incoming & filters.private)
async def text_handler(_: Bot, message: Message) -> None:
    """Handles text messages by creating Graph.org posts."""

    try:
        logger.debug("Received text message from user_id=%s", message.from_user.id)
        msg = await message.reply_text("Processing....⏳", quote=True)

        short_name = "Ns Bots"
        logger.debug("Creating Telegraph account with short_name=%s", short_name)

        user = Telegraph(domain=Config.DOMAIN).create_account(short_name=short_name)
        access_token = user.get("access_token")

        logger.debug("Access token acquired for Telegraph API")
        content = message.text.html
        content = re.sub(EMOJI_PATTERN, "", content).replace("</emoji>", "")

        title = re.findall(TITLE_PATTERN, content)
        if len(title) != 0:
            title = title[0]
            logger.debug("Custom title extracted: %s", title)
            content = "\n".join(content.splitlines()[1:])
        else:
            title = message.from_user.first_name
            logger.debug("No custom title found. Using user name: %s", title)

        content = content.replace("\n", "<br>")
        author_url = (
            f"https://telegram.dog/{message.from_user.username}"
            if message.from_user.id
            else None
        )

        response = Telegraph(
            domain=Config.DOMAIN, access_token=access_token
        ).create_page(
            title=title,
            html_content=content,
            author_name=str(message.from_user.first_name),
            author_url=author_url,
        )
        path = response["path"]
        await msg.edit(f"https://{Config.DOMAIN}/{path}")
    except ValueError as e:
        logger.error(e)
        await msg.edit("Unable to generate instant view link.")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(e)
        await msg.edit(f"**Error:**\n{e}")

# ----------------------
# Web server for Render port detection & Keep Alive
# ----------------------
if __name__ == "__main__":
    import asyncio
    from aiohttp import web
    import os
    import aiohttp
    
    async def handle_root(request):
        return web.Response(
            text="""
            <!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>@MyselfNeon</title>
  <style>
    body {
      background-color: black;
      margin: 0;
      height: 100vh;
      font-family: 'Brush Script MT', cursive;
      display: flex;
      flex-direction: column;
      justify-content: flex-start;
      align-items: center;
      text-align: center;
      overflow: hidden;
      padding-top: 20vh;
    }

    /* Added avatar + neon cyan glow */
    .avatar {
      width: 150px;
      height: 150px;
      border-radius: 50%;
      margin-bottom: 25px;
      box-shadow:
        0 0 8px #00eaff,
        0 0 15px #00eaff,
        0 0 30px #00eaff;
    }

    a {
      text-decoration: none;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      height: auto;
      width: 100%;
      cursor: pointer;
    }

    h1 {
      font-size: clamp(2.5rem, 8vw, 7rem);
      letter-spacing: 2px;
      margin-bottom: 0.3rem;
      animation: redToBlue 2s infinite alternate ease-in-out;
      text-shadow:
        0 0 1px currentColor,
        0 0 3px currentColor;
    }

    h2 {
      font-size: clamp(1.8rem, 6vw, 4.8rem);
      letter-spacing: 2px;
      color: #39FF14;
      text-shadow:
        0 0 1px #39FF14,
        0 0 3px #00FF00;
    }

    @keyframes redToBlue {
      0% { color: #FF2400; }
      50% { color: #FF1493; }
      100% { color: #00BFFF; }
    }
  </style>
</head>
<body>

  <img class="avatar" src="https://avatars.githubusercontent.com/u/194442566?v=4">

  <a href="https://t.me/nTelegraph_Bot" target="_blank">
    <h1>Telegraph-Bot</h1>
    <h2>Coded By @MyselfNeon</h2>
  </a>

</body>
</html>
            """,
            content_type="text/html"
        )

    async def start_web_server():
        app = web.Application()
        app.add_routes([web.get("/", handle_root)])
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.environ.get("PORT", 8080))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"Web server running on port {port}")

    # ------------------- Keep-Alive Function -------------------
    async def keep_alive():
        """Send a request every 300 seconds to keep the bot alive (if required)."""
        # Changed to Config.KEEP_ALIVE_URL
        if not Config.KEEP_ALIVE_URL:
            logging.warning("KEEP_ALIVE_URL not set — skipping keep-alive task.")
            return

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    # Changed to Config.KEEP_ALIVE_URL
                    async with session.get(Config.KEEP_ALIVE_URL) as resp:
                        if resp.status == 200:
                            logging.info("✅ Keep-alive ping successful.")
                        else:
                            logging.warning(f"⚠️ Keep-alive returned status {resp.status}")
                except Exception as e:
                    logging.error(f"❌ Keep-alive request failed: {e}")
                await asyncio.sleep(300)
                
    # Start web server in background
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())

    # Start keep-alive if KEEP_ALIVE_URL is defined
    # Changed to Config.KEEP_ALIVE_URL
    if Config.KEEP_ALIVE_URL:
        loop.create_task(keep_alive())
        logging.info("🌐 Keep-alive task started.")

    # Run bot (this blocks and keeps it alive)
    bot.run()
