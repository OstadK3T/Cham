from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ADMIN_PASSWORD = "admin"
VOICE_CHANNELS = ["Voice 1", "Voice 2", "Voice 3", "Voice 4", "Radio Channel"]

app = FastAPI(title="Cham Real-Time Lobby")
app.mount("/static", StaticFiles(directory="static"), name="static")


@dataclass
class ClientSession:
    name: str
    role: str
    websocket: WebSocket


@dataclass
class Track:
    track_id: int
    title: str
    url: str


@dataclass
class MusicState:
    queue: List[Track] = field(default_factory=list)
    current_track_id: int | None = None
    is_playing: bool = False
    started_at: float | None = None
    position: float = 0.0

    def sync_position(self, now: float) -> float:
        if self.is_playing and self.started_at is not None:
            return max(0.0, now - self.started_at)
        return max(0.0, self.position)

    def to_payload(self, now: float) -> dict:
        return {
            "queue": [track.__dict__ for track in self.queue],
            "current_track_id": self.current_track_id,
            "is_playing": self.is_playing,
            "position": self.sync_position(now),
            "server_time": now,
        }


@dataclass
class VoiceState:
    channels: Dict[str, Set[str]] = field(
        default_factory=lambda: {channel: set() for channel in VOICE_CHANNELS}
    )
    user_channel: Dict[str, str] = field(default_factory=dict)
    talking: Dict[str, bool] = field(default_factory=dict)

    def join_channel(self, name: str, channel: str) -> None:
        self.leave_channel(name)
        self.channels[channel].add(name)
        self.user_channel[name] = channel

    def leave_channel(self, name: str) -> None:
        existing = self.user_channel.pop(name, None)
        if existing:
            self.channels[existing].discard(name)
        self.talking.pop(name, None)

    def set_talking(self, name: str, is_talking: bool) -> None:
        if name in self.user_channel:
            self.talking[name] = is_talking

    def to_payload(self) -> dict:
        return {
            "channels": {
                channel: sorted(list(users)) for channel, users in self.channels.items()
            },
            "talking": self.talking,
        }

    def same_channel(self, name: str, other: str) -> bool:
        return self.user_channel.get(name) == self.user_channel.get(other)


@dataclass
class LobbyState:
    clients: Dict[str, ClientSession] = field(default_factory=dict)
    logs: List[dict] = field(default_factory=list)
    music: MusicState = field(default_factory=MusicState)
    voice: VoiceState = field(default_factory=VoiceState)
    _track_counter: int = 0

    def list_users(self) -> List[dict]:
        return [
            {"name": session.name, "role": session.role}
            for session in sorted(self.clients.values(), key=lambda s: s.name.lower())
        ]

    def name_available(self, name: str) -> bool:
        return name not in self.clients

    def add_client(self, name: str, role: str, websocket: WebSocket) -> None:
        self.clients[name] = ClientSession(name=name, role=role, websocket=websocket)

    def remove_client(self, name: str) -> None:
        self.clients.pop(name, None)

    def add_log(self, message: str) -> None:
        entry = {"message": message, "timestamp": current_time_label()}
        self.logs.append(entry)

    def list_admins(self) -> List[ClientSession]:
        return [session for session in self.clients.values() if session.role == "admin"]

    def next_track_id(self) -> int:
        self._track_counter += 1
        return self._track_counter


class ConnectionManager:
    def __init__(self, state: LobbyState) -> None:
        self.state = state

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def broadcast_users(self) -> None:
        payload = {"type": "users", "users": self.state.list_users()}
        await self._broadcast(payload)

    async def broadcast_chat(self, payload: dict) -> None:
        await self._broadcast(payload)

    async def broadcast_logs(self) -> None:
        payload = {"type": "logs", "logs": self.state.logs}
        await self._broadcast_to_admins(payload)

    async def broadcast_music(self) -> None:
        now = time.time()
        payload = {"type": "music_state", **self.state.music.to_payload(now)}
        await self._broadcast(payload)

    async def broadcast_voice(self) -> None:
        payload = {"type": "voice_state", **self.state.voice.to_payload()}
        await self._broadcast(payload)

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        payload = {"type": "error", "message": message}
        await websocket.send_text(json.dumps(payload))

    async def send_direct(self, websocket: WebSocket, payload: dict) -> None:
        await websocket.send_text(json.dumps(payload))

    async def _broadcast(self, payload: dict) -> None:
        message = json.dumps(payload)
        for session in list(self.state.clients.values()):
            await session.websocket.send_text(message)

    async def _broadcast_to_admins(self, payload: dict) -> None:
        message = json.dumps(payload)
        for session in list(self.state.list_admins()):
            await session.websocket.send_text(message)


lobby_state = LobbyState()
manager = ConnectionManager(lobby_state)


def current_time_label() -> str:
    return datetime.now().strftime("%I:%M%p").lstrip("0")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/client.html")


def create_track(title: str, url: str) -> Track:
    return Track(track_id=lobby_state.next_track_id(), title=title, url=url)


def get_target_session(name: str) -> ClientSession | None:
    return lobby_state.clients.get(name)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    name: str | None = None
    role: str | None = None
    try:
        join_text = await websocket.receive_text()
        join_payload = json.loads(join_text)
        if join_payload.get("type") != "join":
            await manager.send_error(websocket, "Expected join message first.")
            return
        proposed_name = str(join_payload.get("name", "")).strip()
        proposed_role = str(join_payload.get("role", "user")).strip().lower()
        if not proposed_name:
            await manager.send_error(websocket, "Name cannot be empty.")
            return
        if proposed_role not in {"user", "admin"}:
            await manager.send_error(websocket, "Role must be user or admin.")
            return
        if proposed_role == "admin":
            password = str(join_payload.get("password", "")).strip()
            if password != ADMIN_PASSWORD:
                await manager.send_error(websocket, "Invalid admin password.")
                return
        if not lobby_state.name_available(proposed_name):
            await manager.send_error(websocket, "Name already taken. Choose another.")
            return

        name = proposed_name
        role = proposed_role
        lobby_state.add_client(name, role, websocket)
        lobby_state.add_log(f"{name} connected as {role}.")
        await manager.send_direct(
            websocket,
            {
                "type": "join_ack",
                "success": True,
                "role": role,
                "users": lobby_state.list_users(),
                "logs": lobby_state.logs,
                **lobby_state.music.to_payload(time.time()),
                **lobby_state.voice.to_payload(),
            },
        )
        await manager.broadcast_users()
        await manager.broadcast_logs()
        await manager.broadcast_music()
        await manager.broadcast_voice()
        await manager.broadcast_chat(
            {
                "type": "chat",
                "name": "System",
                "role": "system",
                "message": f"{name} joined as {role}.",
                "timestamp": current_time_label(),
            }
        )

        while True:
            message_text = await websocket.receive_text()
            payload = json.loads(message_text)
            message_type = payload.get("type")
            if message_type == "chat":
                is_encrypted = bool(payload.get("encrypted", False))
                reply_to = str(payload.get("reply_to", "")).strip() or None
                if is_encrypted:
                    ciphertext = str(payload.get("ciphertext", "")).strip()
                    iv = str(payload.get("iv", "")).strip()
                    if not ciphertext or not iv:
                        continue
                    await manager.broadcast_chat(
                        {
                            "type": "chat",
                            "name": name,
                            "role": role,
                            "encrypted": True,
                            "ciphertext": ciphertext,
                            "iv": iv,
                            "reply_to": reply_to,
                            "timestamp": current_time_label(),
                        }
                    )
                else:
                    text = str(payload.get("message", "")).strip()
                    if not text:
                        continue
                    await manager.broadcast_chat(
                        {
                            "type": "chat",
                            "name": name,
                            "role": role,
                            "message": text,
                            "reply_to": reply_to,
                            "timestamp": current_time_label(),
                        }
                    )
                continue
            if message_type == "voice_join":
                channel = str(payload.get("channel", "")).strip()
                if channel in VOICE_CHANNELS:
                    lobby_state.voice.join_channel(name, channel)
                    lobby_state.add_log(f"{name} joined {channel}.")
                    await manager.broadcast_voice()
                    await manager.broadcast_logs()
                continue
            if message_type == "voice_leave":
                lobby_state.voice.leave_channel(name)
                lobby_state.add_log(f"{name} left voice channels.")
                await manager.broadcast_voice()
                await manager.broadcast_logs()
                continue
            if message_type == "voice_talking":
                is_talking = bool(payload.get("is_talking", False))
                lobby_state.voice.set_talking(name, is_talking)
                await manager.broadcast_voice()
                continue
            if message_type in {"voice_offer", "voice_answer", "voice_ice"}:
                target_name = str(payload.get("target", "")).strip()
                if target_name and target_name != name:
                    if lobby_state.voice.same_channel(name, target_name):
                        target_session = get_target_session(target_name)
                        if target_session:
                            forward = {
                                "type": message_type,
                                "from": name,
                                "data": payload.get("data"),
                            }
                            await manager.send_direct(target_session.websocket, forward)
                continue
            if role != "admin":
                continue
            if message_type == "music_add":
                url = str(payload.get("url", "")).strip()
                title = str(payload.get("title", "")).strip() or "Untitled track"
                if not url:
                    continue
                track = create_track(title, url)
                lobby_state.music.queue.append(track)
                lobby_state.add_log(f"{name} added track: {title}.")
                if lobby_state.music.current_track_id is None:
                    lobby_state.music.current_track_id = track.track_id
                await manager.broadcast_music()
                await manager.broadcast_logs()
                continue
            if message_type == "music_delete":
                track_id = int(payload.get("track_id", 0))
                lobby_state.music.queue = [
                    track for track in lobby_state.music.queue if track.track_id != track_id
                ]
                if lobby_state.music.current_track_id == track_id:
                    lobby_state.music.current_track_id = (
                        lobby_state.music.queue[0].track_id
                        if lobby_state.music.queue
                        else None
                    )
                    lobby_state.music.is_playing = False
                    lobby_state.music.position = 0.0
                    lobby_state.music.started_at = None
                lobby_state.add_log(f"{name} removed a track from the playlist.")
                await manager.broadcast_music()
                await manager.broadcast_logs()
                continue
            if message_type == "music_select":
                track_id = int(payload.get("track_id", 0))
                if any(track.track_id == track_id for track in lobby_state.music.queue):
                    lobby_state.music.current_track_id = track_id
                    lobby_state.music.is_playing = False
                    lobby_state.music.position = 0.0
                    lobby_state.music.started_at = None
                    lobby_state.add_log(f"{name} selected a new track.")
                    await manager.broadcast_music()
                    await manager.broadcast_logs()
                continue
            if message_type == "music_play":
                if lobby_state.music.current_track_id is None or lobby_state.music.is_playing:
                    continue
                now = time.time()
                lobby_state.music.is_playing = True
                lobby_state.music.started_at = now - lobby_state.music.position
                lobby_state.add_log(f"{name} started playback.")
                await manager.broadcast_music()
                await manager.broadcast_logs()
                continue
            if message_type == "music_pause":
                if not lobby_state.music.is_playing:
                    continue
                now = time.time()
                lobby_state.music.position = lobby_state.music.sync_position(now)
                lobby_state.music.is_playing = False
                lobby_state.music.started_at = None
                lobby_state.add_log(f"{name} paused playback.")
                await manager.broadcast_music()
                await manager.broadcast_logs()
                continue
            if message_type == "music_seek":
                now = time.time()
                new_position = float(payload.get("position", 0.0))
                lobby_state.music.position = max(0.0, new_position)
                if lobby_state.music.is_playing:
                    lobby_state.music.started_at = now - lobby_state.music.position
                lobby_state.add_log(f"{name} scrubbed the timeline.")
                await manager.broadcast_music()
                await manager.broadcast_logs()
    except WebSocketDisconnect:
        pass
    finally:
        if name:
            lobby_state.remove_client(name)
            lobby_state.voice.leave_channel(name)
            lobby_state.add_log(f"{name} disconnected.")
            await manager.broadcast_users()
            await manager.broadcast_voice()
            await manager.broadcast_logs()
            await manager.broadcast_chat(
                {
                    "type": "chat",
                    "name": "System",
                    "role": "system",
                    "message": f"{name} left the lobby.",
                    "timestamp": current_time_label(),
                }
            )
