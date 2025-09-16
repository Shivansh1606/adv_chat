from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-for-prod'
socketio = SocketIO(app, cors_allowed_origins="*")


# ---- In-memory demo stores (replace with DB in prod) ----
advocates = [
    {"id": "adv1", "name": "Advocate A", "specialty": "Family Law", "rating": 4.7, "bio": "10 years experience in family disputes"},
    {"id": "adv2", "name": "Advocate B", "specialty": "Criminal Law", "rating": 4.5, "bio": "Expert in criminal defense"},
    {"id": "adv3", "name": "Advocate C", "specialty": "Corporate Law", "rating": 4.8, "bio": "Corporate contracts & compliance"},
]

# chat_messages maps room_id -> list of message dicts
chat_messages = {}   # { room_id: [ {id, sender, text, timestamp}, ... ] }

# meetings maps advocate_id -> list of meeting requests
meetings = {}  # { advocate_id: [ {id, client, datetime, purpose, status}, ... ] }

# Helper to create room id for advocate + client pair (or just advocate room)
def room_for_advocate(advocate_id):
    return f"room_{advocate_id}"

# Routes
@app.route("/")
def index():
    # shows list of advocates
    return render_template("index.html", advocates=advocates)

@app.route("/chat/<advocate_id>")
def chat(advocate_id):
    # client_name can be passed as query param (or ask via prompt in UI)
    client_name = request.args.get("client_name", "")
    adv = next((a for a in advocates if a["id"] == advocate_id), None)
    if not adv:
        return "Advocate not found", 404
    room = room_for_advocate(advocate_id)
    prev_msgs = chat_messages.get(room, [])
    adv_meetings = meetings.get(advocate_id, [])
    return render_template("chat.html", advocate=adv, client_name=client_name, room=room, prev_msgs=prev_msgs, adv_meetings=adv_meetings)

@app.route("/api/advocates")
def api_advocates():
    return jsonify(advocates)

@app.route("/schedule", methods=["POST"])
def schedule_meeting():
    data = request.form or request.json
    advocate_id = data.get("advocate_id")
    client_name = data.get("client_name")
    date = data.get("date")   # expected YYYY-MM-DD
    time = data.get("time")   # expected HH:MM
    purpose = data.get("purpose", "")

    if not (advocate_id and client_name and date and time):
        return jsonify({"ok": False, "error": "missing fields"}), 400

    try:
        dtstr = f"{date} {time}"
        dt = datetime.strptime(dtstr, "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"ok": False, "error": "invalid datetime format"}), 400

    meeting = {
        "id": str(uuid.uuid4()),
        "client": client_name,
        "datetime": dt.isoformat(),
        "purpose": purpose,
        "status": "requested"
    }
    meetings.setdefault(advocate_id, []).append(meeting)

    # Optionally notify the advocate room via socket that a meeting was requested
    room = room_for_advocate(advocate_id)
    socketio.emit("meeting_requested", {"advocate_id": advocate_id, "meeting": meeting}, room=room)

    return jsonify({"ok": True, "meeting": meeting})

# ---- Socket.IO events ----
@socketio.on("join")
def on_join(data):
    """
    data = { "room": "room_adv1", "user": "Client A", "role": "client" }
    """
    room = data.get("room")
    user = data.get("user", "Anonymous")
    join_room(room)
    msg = {
        "id": str(uuid.uuid4()),
        "sender": "System",
        "text": f"{user} has joined the chat.",
        "timestamp": datetime.utcnow().isoformat()
    }
    # store system message
    chat_messages.setdefault(room, []).append(msg)
    emit("user_joined", msg, room=room)

@socketio.on("leave")
def on_leave(data):
    room = data.get("room")
    user = data.get("user", "Anonymous")
    leave_room(room)
    msg = {
        "id": str(uuid.uuid4()),
        "sender": "System",
        "text": f"{user} has left the chat.",
        "timestamp": datetime.utcnow().isoformat()
    }
    chat_messages.setdefault(room, []).append(msg)
    emit("user_left", msg, room=room)

@socketio.on("send_message")
def handle_send_message(data):
    """
    data = { "room": "room_adv1", "sender": "Client A", "text": "Hello" }
    """
    room = data.get("room")
    sender = data.get("sender", "Unknown")
    text = data.get("text", "")
    if not room or not text:
        return

    msg = {
        "id": str(uuid.uuid4()),
        "sender": sender,
        "text": text,
        "timestamp": datetime.utcnow().isoformat()
    }
    chat_messages.setdefault(room, []).append(msg)
    emit("message", msg, room=room)

# Simple health check endpoint
@app.route("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    # socketio.run(app) chooses eventlet if installed
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
