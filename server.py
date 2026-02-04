from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ADMIN_PASSWORD = "admin"

app = FastAPI(title="Cham Real-Time Lobby")
app.mount("/static", StaticFiles(directory="static"), name="static")


@dataclass
class ClientSession:
    name: str
    role: str
    websocket: WebSocket


@dataclass
class LobbyState:
    clients: Dict[str, ClientSession] = field(default_factory=dict)
    logs: List[dict] = field(default_factory=list)

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

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        payload = {"type": "error", "message": message}
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
        await websocket.send_text(
            json.dumps(
                {
                    "type": "join_ack",
                    "success": True,
                    "role": role,
                    "users": lobby_state.list_users(),
                    "logs": lobby_state.logs,
                }
            )
        )
        await manager.broadcast_users()
        await manager.broadcast_logs()
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
            if payload.get("type") == "chat":
                text = str(payload.get("message", "")).strip()
                if not text:
                    continue
                await manager.broadcast_chat(
                    {
                        "type": "chat",
                        "name": name,
                        "role": role,
                        "message": text,
                        "timestamp": current_time_label(),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        if name:
            lobby_state.remove_client(name)
            lobby_state.add_log(f"{name} disconnected.")
            await manager.broadcast_users()
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
