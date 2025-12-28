"""
Nomic AI Player Program

Spawned by spawner.py to handle turns and votes.
Uses Claude Code headless (claude -p) to make decisions.
"""

import sys
import os
import json
import subprocess
import ast
import re
import requests
from pathlib import Path

from prompts_immutable import (
    planning_header, planning_footer, planning_tools,
    implementation_header, implementation_footer, implementation_tools,
    voting_header, voting_footer, voting_tools,
    wrap_with_char_count
)
from prompts_mutable import (
    planning_mutable, implementation_mutable, voting_mutable,
    planning_tools_extension, implementation_tools_extension, voting_tools_extension
)

# Configuration
REALITY_URL = os.environ.get("REALITY_URL", "http://10.128.0.3:5000")
PLAYER_DIR = Path(__file__).parent
REPO_DIR = PLAYER_DIR / "repo"


def get_rules() -> str:
    """Read current rules from local repo."""
    rules_path = REPO_DIR / "rules.md"
    if rules_path.exists():
        return rules_path.read_text()
    return ""


def get_state() -> dict:
    """Fetch current game state from Reality."""
    try:
        response = requests.get(f"{REALITY_URL}/", timeout=10)
        return response.json()
    except Exception as e:
        print(f"Failed to fetch state: {e}")
        return {}


def run_claude(prompt: str, allowed_tools: str = "Read,Edit,Bash(git:*)") -> str:
    """
    Run Claude Code headless and return the response.
    Uses stream-json format to capture and log tool usage.
    """
    print(f"=== CLAUDE PROMPT ===\n{prompt}\n=== END PROMPT ===", flush=True)
    try:
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--allowedTools", allowed_tools,
                "--permission-mode", "bypassPermissions",
                "--model", "sonnet",
                "--output-format", "stream-json",
                "--verbose"
            ],
            capture_output=True,
            text=True,
            cwd=REPO_DIR,
            timeout=600  # 10 minute timeout
        )
        if result.returncode == 0:
            # Parse stream-json output (one JSON object per line)
            result_text = ""
            tool_calls = []
            lines = result.stdout.strip().split('\n')

            # Debug: print raw output sample
            print(f"=== DEBUG: {len(lines)} lines of output ===", flush=True)
            for i, line in enumerate(lines[:3]):
                print(f"=== LINE {i}: {line[:300]} ===", flush=True)

            for line in lines:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type", "")

                    # Tool uses are nested in assistant messages
                    if msg_type == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_name = block.get("name", "unknown")
                                tool_calls.append(tool_name)
                                print(f"=== TOOL CALL: {tool_name} ===", flush=True)

                    # Capture final result
                    if msg_type == "result":
                        if msg.get("is_error"):
                            print(f"Claude error: {msg.get('result')}", flush=True)
                            return ""
                        result_text = msg.get("result", "")
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue

            print(f"=== TOOL CALLS SUMMARY: {tool_calls} ===", flush=True)
            print(f"=== CLAUDE RESPONSE ===\n{result_text}\n=== END RESPONSE ===", flush=True)
            return result_text
        else:
            print(f"Claude failed (rc={result.returncode}): {result.stdout[:500]}", flush=True)
            return ""
    except Exception as e:
        print(f"Failed to run Claude: {e}", flush=True)
        return ""


def handle_turn(player_name: str):
    """
    Handle a turn: propose a rule change.
    """
    print(f"[{player_name}] Taking turn...")

    # Get current state
    rules = get_rules()
    state = get_state()

    if not rules:
        print("Could not fetch rules, aborting turn")
        return

    proposal_number = state.get("next_proposal_number", 301)

    # Create a new branch for this proposal
    branch_name = f"proposal-{proposal_number}"
    subprocess.run(["git", "fetch", "origin"], cwd=REPO_DIR, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True)
    subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=REPO_DIR, capture_output=True)
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=REPO_DIR, capture_output=True)

    # Phase 1: Planning - read files and decide what to change
    # Compose prompt: immutable header + mutable middle + immutable footer
    planning_prompt_body = f"""{planning_header(player_name, proposal_number)}
{planning_mutable()}
{planning_footer()}"""

    planning_prompt = wrap_with_char_count(planning_prompt_body)
    planning_tools_str = planning_tools() + planning_tools_extension()

    print(f"[{player_name}] Phase 1: Planning...")
    plan = run_claude(planning_prompt, allowed_tools=planning_tools_str)

    if not plan:
        print(f"[{player_name}] Claude did not provide a plan")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    print(f"[{player_name}] Plan: {plan[:500]}...")

    # Phase 2: Implementation - make the changes
    # Compose prompt: immutable header + mutable middle + immutable footer
    implementation_prompt_body = f"""{implementation_header(player_name, proposal_number)}
{implementation_mutable(plan)}
{implementation_footer()}"""

    implementation_prompt = wrap_with_char_count(implementation_prompt_body)
    implementation_tools_str = implementation_tools() + implementation_tools_extension()

    print(f"[{player_name}] Phase 2: Implementing...")
    description = run_claude(implementation_prompt, allowed_tools=implementation_tools_str)

    if not description:
        print(f"[{player_name}] Claude did not provide a proposal")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    # Check if any changes were made
    diff_result = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )

    if not diff_result.stdout.strip():
        print(f"[{player_name}] No changes made, notifying server")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True)
        subprocess.run(["git", "branch", "-D", branch_name], cwd=REPO_DIR, capture_output=True)
        try:
            requests.post(
                f"{REALITY_URL}/turn-failed",
                json={"player": player_name, "reason": "no changes made"},
                timeout=30
            )
        except Exception as e:
            print(f"[{player_name}] Failed to notify server: {e}")
        return

    # Commit and push the branch
    subprocess.run(["git", "add", "."], cwd=REPO_DIR, check=True)

    # Extract commit message from "COMMIT: ..." line at end of response
    # (placed at end for attention mechanism optimization)
    commit_msg = None
    for line in reversed(description.strip().split('\n')):
        if line.strip().upper().startswith("COMMIT:"):
            commit_msg = line.strip()[7:].strip()[:100]
            break
    if not commit_msg:
        commit_msg = description.strip().split('\n')[0][:100]

    subprocess.run(
        ["git", "commit", "-m", f"Proposal {proposal_number}: {commit_msg}"],
        cwd=REPO_DIR,
        capture_output=True
    )

    # Delete remote branch if it exists (from previous failed attempt)
    subprocess.run(
        ["git", "push", "origin", "--delete", branch_name],
        cwd=REPO_DIR,
        capture_output=True
    )

    push_result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )

    if push_result.returncode != 0:
        print(f"[{player_name}] Failed to push: {push_result.stderr}")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True)
        return

    # Submit PR info to Reality
    print(f"[{player_name}] Submitting proposal to Reality...")
    try:
        response = requests.post(
            f"{REALITY_URL}/pr",
            json={
                "proposer": player_name,
                "description": description,
                "branch": branch_name
            },
            timeout=30
        )
        print(f"[{player_name}] PR submitted: {response.json()}")
    except Exception as e:
        print(f"[{player_name}] Failed to submit PR: {e}")

    # Switch back to main
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True)


def handle_vote(player_name: str):
    """
    Handle a vote on a pending proposal.
    """
    print(f"[{player_name}] Voting...")

    # Get vote data from environment
    vote_data_str = os.environ.get("VOTE_DATA", "{}")
    try:
        vote_data = ast.literal_eval(vote_data_str)
    except:
        vote_data = {}

    proposal_id = vote_data.get("proposal_id")
    proposer = vote_data.get("proposer")
    description = vote_data.get("description", "")
    branch = vote_data.get("branch", "")

    if not proposal_id:
        print(f"[{player_name}] No proposal ID in vote data")
        return

    if not branch:
        print(f"[{player_name}] No branch in vote data")
        return

    # Fetch and checkout the proposal branch
    subprocess.run(["git", "fetch", "origin"], cwd=REPO_DIR, capture_output=True)
    subprocess.run(["git", "checkout", f"origin/{branch}"], cwd=REPO_DIR, capture_output=True)

    # Get commit info
    commit_result = subprocess.run(
        ["git", "log", "-1", "--format=%s%n%n%b"],
        cwd=REPO_DIR, capture_output=True, text=True
    )
    commit_message = commit_result.stdout.strip()

    # Get list of changed files
    files_result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main", "HEAD"],
        cwd=REPO_DIR, capture_output=True, text=True
    )
    changed_files = files_result.stdout.strip()

    # Run mypy to check for type errors (strict mode to catch more bugs)
    mypy_result = subprocess.run(
        ["mypy", "--ignore-missing-imports", "--check-untyped-defs", "reality/", "ai/"],
        cwd=REPO_DIR, capture_output=True, text=True
    )
    mypy_output = mypy_result.stdout.strip()

    # Build prompt for Claude to decide on vote
    # Compose prompt: immutable header + mutable middle + immutable footer
    voting_prompt_body = f"""{voting_header(player_name, proposal_id, proposer)}
{voting_mutable(description, commit_message, changed_files, mypy_output)}
{voting_footer()}"""

    voting_prompt = wrap_with_char_count(voting_prompt_body)
    voting_tools_str = voting_tools() + voting_tools_extension()

    # Run Claude to decide
    print(f"[{player_name}] Consulting Claude for vote decision...")
    response = run_claude(voting_prompt, allowed_tools=voting_tools_str)

    # Switch back to main
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True)

    if not response:
        print(f"[{player_name}] Claude did not respond, defaulting to NO")
        vote = False
    else:
        # Parse the vote - look for "I VOTE YES" or "I VOTE NO"
        # Note: Matching at the end of the response works best due to the attention
        # mechanism - the model is most likely to follow instructions that specify
        # output format at the end of the response.
        response_upper = response.upper()
        yes_pos = response_upper.rfind("I VOTE YES")
        no_pos = response_upper.rfind("I VOTE NO")
        if yes_pos > no_pos:
            vote = True
        elif no_pos > yes_pos:
            vote = False
        else:
            # Fallback: find latest standalone YES or NO
            yes_matches = list(re.finditer(r'\bYES\b', response_upper))
            no_matches = list(re.finditer(r'\bNO\b', response_upper))
            last_yes = yes_matches[-1].start() if yes_matches else -1
            last_no = no_matches[-1].start() if no_matches else -1
            vote = last_yes > last_no
        print(f"[{player_name}] Claude decided: {'YES' if vote else 'NO'}")
        print(f"[{player_name}] Reasoning: {response}")

    # Submit vote to Reality
    try:
        vote_response = requests.post(
            f"{REALITY_URL}/vote/{proposal_id}",
            json={
                "voter": player_name,
                "vote": vote
            },
            timeout=30
        )
        print(f"[{player_name}] Vote submitted: {vote_response.json()}")
    except Exception as e:
        print(f"[{player_name}] Failed to submit vote: {e}")


def main():
    if len(sys.argv) < 3:
        print("Usage: player.py <turn|vote> <player_name>")
        sys.exit(1)

    mode = sys.argv[1]
    player_name = sys.argv[2]

    if mode == "turn":
        handle_turn(player_name)
    elif mode == "vote":
        handle_vote(player_name)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
