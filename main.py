import asyncio, json, time

import nio

# Read .env
from dotenv import dotenv_values

environ = dotenv_values(".env")


class MultiAccountBot:
    async def log(self, message: str, room_id: str = None) -> None:
        # GMT +8 time in YYYY-MM-DD HH:MM:SS format
        message = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] {message}"
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

        # Move log room to space and rename it to "Log Room"
        await self.client.room_put_state(
            space_id,
            "m.space.child",
            {
                "suggested": True,
                "via": [via_domain],
            },
            state_key=environ["LOG_ROOM"],
        )
        await self.client.room_put_state(
            environ["LOG_ROOM"],
            "m.room.name",
            {"name": "Log Room"},
        )

    def __init__(self) -> None:
        self._check_config()
        self.client = nio.AsyncClient(environ["SERVER_URL"], environ["USER_ID"])
        try:
            self.config: dict = json.load(open("config.json", "r", encoding="utf-8"))
        except FileNotFoundError:
            self.config = {}
        self.begin_process: bool = False

    async def start(self):
        print((await self.client.login(environ["PASSWORD"])).device_id)
        if not self.config.get("ADMIN_SPACE"):
            await self.log("Creating admin space...")
            # Create spaces
            await self._initialize_spaces()
        if environ.get("CONTROLLER"):
            # Invite controller to admin space
            await self.client.room_invite(
                self.config.get("ADMIN_SPACE"), environ["CONTROLLER"]
            )

        # Send timestamp
        self.timestamp = int(time.time() * 1000)
        await self.client.room_send(
            environ["LOG_ROOM"],
            "m.room.message",
            {"msgtype": "m.text", "body": f"Timestamp: {self.timestamp}"},
        )
        # Callback for messages
        self.client.add_event_callback(self.message_callback, nio.RoomMessageText)
        await self.client.sync_forever(timeout=30000)

    async def message_callback(
        self, current_room: nio.MatrixRoom, event: nio.RoomMessageText
    ):
        body = event.body
        if event.server_timestamp < self.config.get("LAST_TIMESTAMP", 0):
            return
        if (
            body.startswith("Timestamp:")
            and len(body.split(" ")) == 2
            and current_room.room_id == environ["LOG_ROOM"]
        ):
            try:
                timestamp = int(body.split(" ")[1])
            except ValueError:
                return
            if timestamp == self.timestamp:
                self.config["LAST_TIMESTAMP"] = event.server_timestamp
                self.begin_process = True
                await self.log("Timestamp verified, starting process...")
            return
        if not self.begin_process:
            return

        if current_room.room_id == self.config.get(
            "CONTROL_ROOM"
        ) and event.body.startswith("!"):
            if body == "!ping":
                await self.log("Pong!", room_id=current_room.room_id)
            if body == "!exit":
                await self.log("Exiting...", room_id=current_room.room_id)
                await self.log("--- END OF BOT LOG ---")
                await self.client.close()
                # Write config
                self.config["LAST_TIMESTAMP"] = event.server_timestamp
                json.dump(self.config, open("config.json", "w", encoding="utf-8"))
                raise SystemExit(0)
            # If starts with !crawl
            if body.startswith("!crawl"):
                args = body.split(" ")
                if len(args) != 3:
                    await self.log(
                        "Invalid arguments. Expected: !crawl <room_id> <num_messages>",
                        room_id=current_room.room_id,
                    )
                    return
                room_id = args[1]
                num_messages = int(args[2])
                if room_id not in (await self.client.joined_rooms()).rooms:
                    await self.log("Not in room", room_id=current_room.room_id)
                    return
                await self.log(
                    f"Crawling {num_messages} messages from {room_id}",
                    room_id=current_room.room_id,
                )
                messages = await self.client.room_messages(
                    room_id, start="", limit=num_messages
                )
                if isinstance(messages, nio.RoomMessagesError):
                    await self.log(
                        f"Error getting messages: {messages.message}",
                        room_id=current_room.room_id,
                    )
                    return
                for message in messages.chunk:
                    # Check if message is a subtype of RoomMessage
                    if str(type(message)).startswith(
                        "<class 'nio.events.room_events.RoomMessage"
                    ):
                        await self.client.room_send(
                            environ["LOG_ROOM"],
                            message_type="m.room.message",
                            content=message.source["content"],
                        )
                return
            else:
                await self.log(
                    "Invalid command. Available commands: !ping, !exit, !crawl",
                    room_id=current_room.room_id,
                )


if __name__ == "__main__":
    bot = MultiAccountBot()
    asyncio.run(bot.start())
