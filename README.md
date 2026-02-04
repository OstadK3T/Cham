# Cham Lobby

A real-time lobby built with FastAPI and WebSockets. Users open the web UI, pick a name, and see who else is online. Admins can log in to view server logs, control radio playback, and manage voice channels.

## Features
- Web UI with real-time updates.
- Duplicate name protection on the server.
- Admin login with live server logs.
- Real-time chat with system join/leave messages.
- Shared radio playlist and synced playback for the Radio channel.
- Voice chat channels with push-to-talk and microphone selection.
- End-to-end encrypted chat (shared passphrase).
- Simple architecture to extend with new features.

## Getting started (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn server:app --reload
```

## Getting started (macOS/Linux)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://localhost:8000 in your browser.

## Admin login

Use the admin password `admin` to sign in as an administrator. Admins can see the real-time logs panel and manage radio playback.

## Voice chat

Click a channel to join, press the push-to-talk button (or your key binding), and allow microphone permissions when prompted. Leaving the lobby or clicking "Leave channel" disconnects you from voice chat.

## Encryption

Set a shared passphrase in the Security panel to enable end-to-end chat encryption (messages are encrypted in the browser before being sent to the server). Voice chat uses WebRTC (DTLS-SRTP), which encrypts audio streams by default.

## Deploying the client

The client UI lives at `static/client.html`. You can give this file to users, or simply direct them to your hosted server and it will be served at `/`.

## Extending

Core logic lives in `LobbyState` and `ConnectionManager` inside `server.py`. Add new message types to the WebSocket loop when you need to expand the protocol.
