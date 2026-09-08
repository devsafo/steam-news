from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running and keeping alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    # Using host='0.0.0.0' makes it accessible externally, required by Render
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
