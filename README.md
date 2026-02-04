# Cham Lobby

A real-time lobby built with FastAPI and WebSockets. Users open the web UI, pick a name, and see who else is online. Admins can log in to view server logs in real time.

## Features
- Web UI with real-time updates.
- Duplicate name protection on the server.
- Admin login with live server logs.
- Real-time chat with system join/leave messages.
- Simple architecture to extend with new features.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://localhost:8000 in your browser.

## Admin login

Use the admin password `admin` to sign in as an administrator. Admins can see the real-time logs panel.

## Deploying the client

The client UI lives at `static/client.html`. You can give this file to users, or simply direct them to your hosted server and it will be served at `/`.

## Extending

Core logic lives in `LobbyState` and `ConnectionManager` inside `server.py`. Add new message types to the WebSocket loop when you need to expand the protocol.
