"""
Minimal HTTP server that spawns player.py for each request.
~10 lines of actual logic.
"""

import subprocess
import sys
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# Get player name and port from environment
PLAYER_NAME = os.environ.get("PLAYER_NAME", "player1")
PLAYER_DIR = os.path.dirname(os.path.abspath(__file__))


@app.post("/turn")
def turn():
    """Spawn player.py to handle a turn."""
    data = request.get_json()
    subprocess.Popen(
        [sys.executable, "player.py", "turn", PLAYER_NAME],
        cwd=PLAYER_DIR,
        env={**os.environ, "TURN_DATA": str(data)}
    )
    return jsonify({"status": "spawned"})


@app.post("/vote")
def vote():
    """Spawn player.py to handle a vote."""
    data = request.get_json()
    subprocess.Popen(
        [sys.executable, "player.py", "vote", PLAYER_NAME],
        cwd=PLAYER_DIR,
        env={**os.environ, "VOTE_DATA": str(data)}
    )
    return jsonify({"status": "spawned"})


@app.post("/pull")
def pull():
    """Pull latest from origin."""
    repo_dir = os.path.join(PLAYER_DIR, "repo")
    subprocess.run(["git", "fetch", "origin"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_dir, capture_output=True)
    # Copy player.py from repo if it was updated
    src = os.path.join(repo_dir, "ai", "player.py")
    dst = os.path.join(PLAYER_DIR, "player.py")
    if os.path.exists(src):
        import shutil
        shutil.copy(src, dst)
    return jsonify({"status": "pulled"})


@app.post("/update")
def update():
    """Alias for /pull (backwards compat)."""
    return pull()


@app.get("/health")
def health():
    """Health check."""
    return jsonify({"status": "ok", "player": PLAYER_NAME})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    print(f"AI spawner for {PLAYER_NAME} starting on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
