"""
Nomic Reality Server

The central game server that:
- Manages game state
- Triggers AI player turns
- Receives and processes PRs (rule changes)
- Collects votes and resolves proposals
- Handles self-modification via exec()
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from flask import Flask, request, jsonify
import requests

from game_state import StateManager, test_json_serializable

app = Flask(__name__)

# Paths
REPO_PATH = Path(os.environ.get("REPO_PATH", Path(__file__).parent.parent / "repo"))
RULES_PATH = REPO_PATH / "rules.md"
REALITY_CODE_PATH = REPO_PATH / "reality"
AI_CODE_PATH = REPO_PATH / "ai"

# State manager
state_manager = StateManager()


# --- API Endpoints ---

@app.get("/")
def index():
    """Health check and current state."""
    return jsonify(state_manager.get_state_summary())


@app.post("/pr")
def submit_pr():
    """
    Receive a PR submission from an AI player.
    Expected JSON: {proposer, description, branch}
    """
    data = request.json
    print(f"=== PR REQUEST ===\n{json.dumps(data, indent=2)}\n=== END REQUEST ===", flush=True)
    proposer = data.get("proposer")
    description = data.get("description")
    branch = data.get("branch")

    if not all([proposer, description, branch]):
        return jsonify({"error": "missing required fields"}), 400

    # Fetch the branch to get the diff for voters to review
    subprocess.run(["git", "fetch", "origin", branch], cwd=REPO_PATH, capture_output=True)
    diff_result = subprocess.run(
        ["git", "diff", "main", f"origin/{branch}"],
        cwd=REPO_PATH,
        capture_output=True,
        text=True
    )
    diff = diff_result.stdout

    proposal_id = state_manager.submit_proposal(proposer, description, diff, branch)
    if proposal_id:
        # Reset proposal timeout
        global proposal_start_time
        proposal_start_time = None
        # Trigger voting from other players
        trigger_voting()
        return jsonify({"status": "submitted", "proposal_id": proposal_id})
    return jsonify({"error": "invalid proposal"}), 400


@app.post("/vote/<int:proposal_id>")
def submit_vote(proposal_id):
    """
    Receive a vote from an AI player.
    Expected JSON: {voter, vote: bool}
    """
    data = request.json
    print(f"=== VOTE REQUEST for proposal {proposal_id} ===\n{json.dumps(data, indent=2)}\n=== END REQUEST ===", flush=True)
    voter = data.get("voter")
    vote = data.get("vote")

    if voter is None or vote is None:
        return jsonify({"error": "voter and vote required"}), 400

    pr = state_manager.state.pending_pr
    if not pr or pr["id"] != proposal_id:
        return jsonify({"error": "no matching pending proposal"}), 400

    if state_manager.submit_vote(voter, vote):
        print(f"Vote received: {voter} voted {'YES' if vote else 'NO'} on proposal {proposal_id}", flush=True)
        # Check if all votes are in
        if state_manager.all_votes_in():
            result = resolve_and_advance()
            print(f"Vote resolved: proposal {proposal_id} {'PASSED' if result['passed'] else 'FAILED'}", flush=True)
            return jsonify({"status": "voted", "result": result})
        return jsonify({"status": "voted", "waiting_for_votes": True})
    return jsonify({"error": "invalid vote"}), 400


@app.post("/turn-failed")
def turn_failed():
    """
    Receive notification that a player failed to make changes.
    Expected JSON: {player, reason}
    """
    data = request.json
    player = data.get("player")
    reason = data.get("reason", "unknown")
    print(f"Turn failed for {player}: {reason}", flush=True)

    # Advance to next turn
    state_manager.complete_turn()

    return jsonify({"status": "acknowledged", "next_player": state_manager.state.current_player()})


# --- Game Logic ---

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"

def save_turn_snapshot():
    """Save current game state to a timestamped snapshot file."""
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    snapshot = state_manager.get_state_summary()
    proposal_num = snapshot.get("next_proposal_number", 0)
    filename = SNAPSHOTS_DIR / f"turn_{proposal_num:04d}.json"
    with open(filename, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Saved snapshot: {filename.name}")


def trigger_current_player_turn():
    """Send HTTP request to current player to take their turn."""
    player = state_manager.state.current_player()
    if not player:
        return

    # Save snapshot at start of each turn
    save_turn_snapshot()

    try:
        response = requests.post(
            f"{player['endpoint_url']}/turn",
            json={
                "player_name": player["name"],
                "proposal_number": state_manager.state.next_proposal_number,
                "game_state": state_manager.get_state_summary()
            },
            timeout=10
        )
        print(f"Triggered turn for {player['name']}: {response.status_code}")
        # Only set phase to proposal after successful trigger
        state_manager.state.turn_phase = "proposal"
        state_manager.save()
    except Exception as e:
        print(f"Failed to trigger turn for {player['name']}: {e}")
        # Stay in waiting phase so we retry


def trigger_voting():
    """Send HTTP request to all non-proposing players to vote."""
    pr = state_manager.state.pending_pr
    if not pr:
        return

    for player in state_manager.state.players:
        if player["name"] == pr["proposer"]:
            continue  # Proposer already voted yes

        try:
            response = requests.post(
                f"{player['endpoint_url']}/vote",
                json={
                    "player_name": player["name"],
                    "proposal_id": pr["id"],
                    "proposer": pr["proposer"],
                    "description": pr["description"],
                    "branch": pr["branch"],
                    "game_state": state_manager.get_state_summary()
                },
                timeout=10
            )
            print(f"Triggered vote for {player['name']}: {response.status_code}")
        except Exception as e:
            print(f"Failed to trigger vote for {player['name']}: {e}")


def run_tests_on_branch(branch: str) -> tuple[bool, str]:
    """Run tests against a branch before merging."""
    # Checkout branch
    subprocess.run(["git", "fetch", "origin", branch], cwd=REPO_PATH, capture_output=True)
    subprocess.run(["git", "checkout", f"origin/{branch}"], cwd=REPO_PATH, capture_output=True)

    try:
        # Run the test
        result = subprocess.run(
            [sys.executable, "-c", "from game_state import test_json_serializable; test_json_serializable()"],
            cwd=REPO_PATH / "reality",
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False, result.stderr
        return True, ""
    finally:
        subprocess.run(["git", "checkout", "main"], cwd=REPO_PATH, capture_output=True)


def resolve_and_advance():
    """Resolve the vote, apply changes if passed, and advance turn."""
    # Get PR info before resolving (resolve clears pending_pr)
    pr = state_manager.state.pending_pr
    branch = pr["branch"] if pr else ""
    diff = pr["diff"] if pr else ""

    result = state_manager.resolve_vote()
    if not result:
        return None

    if result["passed"] and branch:
        # Run tests before merging
        passed, error = run_tests_on_branch(branch)
        if not passed:
            print(f"Tests failed for proposal {result['proposal_id']}: {error}")
            result["passed"] = False
            result["test_failure"] = error
            state_manager.complete_turn()
            return result

        # Merge the branch
        merge_branch(branch, result["proposal_id"])

        # Notify AIs to pull latest
        notify_ai_pull()

        # Check for self-modification
        if check_self_modification(diff):
            # Save state, advance turn first
            state_manager.complete_turn()
            # Will exec() and not return
            handle_self_modification()

    # Advance to next turn
    state_manager.complete_turn()

    return result


def merge_branch(branch: str, proposal_id: int) -> bool:
    """Merge a proposal branch into main."""
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=REPO_PATH, capture_output=True)
        subprocess.run(
            ["git", "merge", f"origin/{branch}", "-m", f"Merge proposal {proposal_id}"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True
        )
        # Push the merge to origin
        subprocess.run(["git", "push", "origin", "main"], cwd=REPO_PATH, capture_output=True)
        # Delete the proposal branch
        subprocess.run(["git", "push", "origin", "--delete", branch], cwd=REPO_PATH, capture_output=True)
        print(f"Merged branch {branch} for proposal {proposal_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to merge branch {branch}: {e}")
        return False


def notify_ai_pull():
    """Notify all AI players to pull latest code."""
    for player in state_manager.state.players:
        try:
            requests.post(f"{player['endpoint_url']}/pull", timeout=5)
        except Exception as e:
            print(f"Failed to notify {player['name']} to pull: {e}")


def check_self_modification(diff: str) -> bool:
    """Check if the diff modifies reality/* files."""
    return "reality/" in diff or "a/reality/" in diff


def handle_self_modification():
    """
    Handle self-modification by copying new code and exec()-ing.
    """
    print("Self-modification detected. Restarting...")

    # Ensure state is saved
    state_manager.save()

    # Copy ALL reality Python files to runtime location
    runtime_dir = Path(__file__).parent
    for src in REALITY_CODE_PATH.glob("*.py"):
        dst = runtime_dir / src.name
        if src != dst:
            shutil.copy(src, dst)
            print(f"Copied {src.name}")

    # Restart by exec()-ing ourselves
    os.execv(sys.executable, [sys.executable] + sys.argv)


def notify_ai_code_update():
    """Notify AI players to pull new code."""
    for player in state_manager.state.players:
        try:
            requests.post(
                f"{player['endpoint_url']}/update",
                timeout=5
            )
        except Exception as e:
            print(f"Failed to notify {player['name']} of update: {e}")


# --- Git Setup ---

def init_repo():
    """Initialize git repo if not already initialized."""
    git_dir = REPO_PATH / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=REPO_PATH, check=True)
        subprocess.run(["git", "add", "."], cwd=REPO_PATH, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit with Nomic rules"],
            cwd=REPO_PATH,
            check=True
        )
        print("Initialized git repository")


# --- Main ---

# Track when we entered proposal phase (for timeout)
proposal_start_time = None
PROPOSAL_TIMEOUT = 1200  # 20 minutes to submit a PR (2 phases x 10 min each)

def run_game_loop():
    """Main game loop - runs in background thread."""
    global proposal_start_time
    import time

    # Wait for server to start
    time.sleep(2)

    print("Game loop starting...", flush=True)
    while True:
        if state_manager.state.winner:
            print(f"Game over! Winner: {state_manager.state.winner}")
            break

        if state_manager.state.turn_phase == "waiting":
            player = state_manager.state.current_player()
            if player:
                print(f"Triggering turn for {player['name']}...")
                trigger_current_player_turn()
                if state_manager.state.turn_phase == "proposal":
                    proposal_start_time = time.time()

        # Check for proposal timeout
        if state_manager.state.turn_phase == "proposal" and proposal_start_time:
            elapsed = time.time() - proposal_start_time
            if elapsed > PROPOSAL_TIMEOUT:
                player = state_manager.state.current_player()
                if player:
                    print(f"Proposal timeout for {player['name']}, skipping turn...")
                state_manager.complete_turn()
                proposal_start_time = None

        # Poll every 5 seconds
        time.sleep(5)


if __name__ == "__main__":
    import threading

    init_repo()

    # Start game loop in background
    game_thread = threading.Thread(target=run_game_loop, daemon=True)
    game_thread.start()

    print("Starting Nomic Reality server on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)
