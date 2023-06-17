import asyncio, json

from nio import AsyncClient, MatrixRoom, RoomMessageText

# Read .env
from dotenv import dotenv_values
config = dotenv_values(".env")


class MultiAccountBot():
    def __init__(self) -> None:
        self.client = AsyncClient(config["SERVER_URL"], config["USER_ID"])
        self.config = json.load(open("config.json", "r", encoding="utf-8"))
        
    async def message_callback(room: MatrixRoom, event: RoomMessageText) -> None:
        print(
            f"Message received in room {room.display_name}\n"
            f"{room.user_name(event.sender)} | {event.body}"
        )


    async def start(self):
        print(await self.client.login(config["PASSWORD"]))
        self.client.add_event_callback(self.message_callback, RoomMessageText)
        print(await self.client.room_send(
            # Watch out! If you join an old room you'll see lots of old messages
            room_id="!jUPYMj5UfXPZcYdm:matrix.duti.me",
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": "Hello world!"},
        ))
        await self.client.sync_forever(timeout=30000)  # milliseconds


if __name__ == "__main__":
    bot = MultiAccountBot()
    asyncio.run(bot.start())