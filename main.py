import asyncio, json

import nio

# Read .env
from dotenv import dotenv_values

environ = dotenv_values(".env")


class MultiAccountBot:
    async def log(self, message: str, room_id: str = None) -> None:
        print(message)
        resp = await self.client.room_send(
            room_id=room_id or environ["LOG_ROOM"],
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message},
        )
        if isinstance(resp, nio.ErrorResponse):
            print(f"Error sending message: {resp.message}")

    def _check_config(self):
        if not environ.get("SERVER_URL"):
            raise ValueError("SERVER_URL not set in .env")
        if not environ.get("USER_ID"):
            raise ValueError("USER_ID not set in .env")
        if not environ.get("PASSWORD"):
            raise ValueError("PASSWORD not set in .env")
        if not environ.get("LOG_ROOM"):
            raise ValueError("LOG_ROOM not set in .env")

    async def _initialize_spaces(self):
        resp = await self.client.room_create(space=True, name="Admin Space")
        if isinstance(resp, nio.RoomCreateError):
            await self.log(f"Error creating room: {resp.message}")
            raise SystemExit(1)

        await self.log(f"Created space with ID {resp.room_id}")
        space_id = resp.room_id
        self.config["ADMIN_SPACE"] = space_id
        via_domain = space_id.split(":")[1]
        # create room with parent room
        initial_state = [
            {
                "type": "m.space.parent",
                "state_key": space_id,
                "content": {
                    "canonical": True,
                    "via": [via_domain],
                },
            }
        ]
        # Create control room
        room = await self.client.room_create(
            name="Control Room", initial_state=initial_state
        )
        assert room.room_id is not None
        # add to space as child room
        state_update = await self.client.room_put_state(
            space_id,
            "m.space.child",
            {
                "suggested": True,
                "via": [via_domain],
            },
            state_key=room.room_id,
        )
        assert state_update.event_id is not None
        self.config["CONTROL_ROOM"] = room.room_id
        await self.log(f"Created control room with ID {room.room_id}")

    def __init__(self) -> None:
        self._check_config()
        self.client = nio.AsyncClient(environ["SERVER_URL"], environ["USER_ID"])
        self.config: dict = json.load(open("config.json", "r", encoding="utf-8"))

    async def start(self):
        print((await self.client.login(environ["PASSWORD"])).device_id)
        if not self.config.get("ADMIN_SPACE"):
            await self.log("Creating admin space...")
            # Create spaces
            await self._initialize_spaces()

        await self.log(
            "Initialization complete", room_id=self.config.get("CONTROL_ROOM")
        )

        # Callback for messages
        self.client.add_event_callback(self.message_callback, nio.RoomMessageText)
        await self.client.sync_forever(timeout=30000)

    async def message_callback(self, room: nio.MatrixRoom, event: nio.RoomMessageText):
        if room.room_id == self.config.get("CONTROL_ROOM"):
            # switch case
            match event.body:
                case "!exit":
                    await self.log("Exiting...")
                    await self.client.close()
                    # Write config
                    json.dump(self.config, open("config.json", "w", encoding="utf-8"))
                    raise SystemExit(0)


if __name__ == "__main__":
    bot = MultiAccountBot()
    asyncio.run(bot.start())
