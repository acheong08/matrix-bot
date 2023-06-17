import asyncio, json

import nio

# Read .env
from dotenv import dotenv_values

environ = dotenv_values(".env")


class Logger:
    def __init__(self, client: nio.AsyncClient) -> None:
        self.client = client
        self.room_id = environ["LOG_ROOM"]

    async def log(self, message: str) -> None:
        await self.client.room_send(
            room_id=self.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": message},
        )


class MultiAccountBot:
    def _check_config(self):
        if not environ.get("SERVER_URL"):
            raise ValueError("SERVER_URL not set in .env")
        if not environ.get("USER_ID"):
            raise ValueError("USER_ID not set in .env")
        if not environ.get("PASSWORD"):
            raise ValueError("PASSWORD not set in .env")
        if not environ.get("LOG_ROOM"):
            raise ValueError("LOG_ROOM not set in .env")

    def __init__(self) -> None:
        self._check_config()
        self.client = nio.AsyncClient(environ["SERVER_URL"], environ["USER_ID"])
        self.config: dict = json.load(open("config.json", "r", encoding="utf-8"))
        self.logger = Logger(self.client)

    async def create_room(self, name: str, space_id: str):
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
        room = await self.client.room_create(
            visibility=nio.RoomVisibility.private,
            name=name,
            federate=False,
            initial_state=initial_state,
        )
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
        return room

    async def _initialize_spaces(self):
        resp = await self.client.room_create(space=True, name="Admin Space")
        if isinstance(resp, nio.RoomCreateError):
            await self.logger.log(f"Error creating room: {resp.message}")
            raise SystemExit(1)

        await self.logger.log(f"Created space with ID {resp.room_id}")
        self.config["ADMIN_SPACE"] = resp.room_id

        # Create rooms within space
        for room in ["Control Room", "Log Room", "Bot Room"]:
            resp = await self.create_room(room, resp.room_id)
            await self.logger.log(f"Created room with ID {resp.room_id}")
            self.config[room.upper().replace(" ", "_")] = resp.room_id
        environ["LOG_ROOM"] = self.config["LOG_ROOM"]

    async def start(self):
        await self.client.login(environ["PASSWORD"])
        #  Check config for admin space
        if not self.config.get("ADMIN_SPACE"):
            # Create spaces
            await self._initialize_spaces()
            # Write config
            json.dump(self.config, open("config.json", "w", encoding="utf-8"))

        await self.client.close()


if __name__ == "__main__":
    bot = MultiAccountBot()
    asyncio.run(bot.start())
