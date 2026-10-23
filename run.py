from dotenv import load_dotenv
load_dotenv()  # reads DATABASE_URL, SECRET_KEY etc. from a local .env file

from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    # socketio.run (not app.run) -- this is what makes the real-time
    # community chat work. Same host/port/debug behaviour as before.
    socketio.run(app, debug=True, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
