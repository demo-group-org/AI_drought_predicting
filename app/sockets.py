"""
Real-time direct-message chat between two farmers, used from the Community
page instead of a mailto email link. One room per pair of users
(Message.room_name), persisted to the database so history survives a
refresh/reconnect.
"""
from datetime import datetime
from flask_login import current_user
from flask_socketio import join_room, emit

from app import socketio, db
from app.models import Message, User


@socketio.on("join")
def handle_join(data):
    if not current_user.is_authenticated:
        return
    other_user_id = data.get("other_user_id")
    if not other_user_id:
        return
    room = Message.room_name(current_user.id, other_user_id)
    join_room(room)


@socketio.on("send_message")
def handle_send_message(data):
    if not current_user.is_authenticated:
        return

    recipient_id = data.get("recipient_id")
    body = (data.get("body") or "").strip()
    if not recipient_id or not body:
        return

    recipient = db.session.get(User, int(recipient_id))
    if recipient is None:
        return

    message = Message(sender_id=current_user.id, recipient_id=recipient.id, body=body)
    db.session.add(message)
    db.session.commit()

    room = Message.room_name(current_user.id, recipient.id)
    emit("receive_message", {
        "sender_id": current_user.id,
        "sender_name": f"{current_user.name} {current_user.surname}",
        "body": body,
        "created_at": message.created_at.strftime("%H:%M"),
    }, room=room)
