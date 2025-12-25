"""
Disk-based game state management for Nomic Reality server.
All state is persisted to state.json after every mutation.
"""

import json
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"
CONFIG_FILE = Path(__file__).parent / "config.json"



@dataclass
class Player:
    name: str
    endpoint_url: str
    score: int = 0


@dataclass
class PendingPR:
    id: int
    proposer: str
    description: str
    diff: str
    branch: str
    votes: dict = field(default_factory=dict)  # player_name -> bool


@dataclass
class HistoryEntry:
    turn_number: int
    proposer: str
    proposal_id: int
    description: str
    votes: dict
    passed: bool
    points_awarded: int


@dataclass
class GameState:
    players: list
    current_turn_index: int = 0
    next_proposal_number: int = 301
    pending_pr: Optional[dict] = None
    history: list = field(default_factory=list)
    game_started: bool = False
    winner: Optional[str] = None
    turn_phase: str = "waiting"  # waiting, proposal, voting, completed
    circuits_completed: int = 0  # Rule 203: after 2 circuits, majority voting enabled

    def current_player(self) -> Optional[dict]:
        """Return the player whose turn it is."""
        if not self.players:
            return None
        return self.players[self.current_turn_index]

    def get_player(self, name: str) -> Optional[dict]:
        """Get a player by name."""
        for p in self.players:
            if p["name"] == name:
                return p
        return None

    def advance_turn(self):
        """Move to the next player's turn."""
        self.current_turn_index = (self.current_turn_index + 1) % len(self.players)
        # Track circuit completion (Rule 203)
        if self.current_turn_index == 0:
            self.circuits_completed += 1
        self.turn_phase = "waiting"
        self.pending_pr = None

    def roll_die(self) -> int:
        """Roll a six-sided die."""
        return random.randint(1, 6)

    def calculate_points(self, proposal_number: int, favorable_votes: int, total_votes: int) -> int:
        """
        Calculate points for a successful proposal.
        Points = (proposal_number - 291) * (favorable_votes / total_votes), rounded.
        """
        if total_votes == 0:
            return 0
        base = proposal_number - 291
        fraction = favorable_votes / total_votes
        return round(base * fraction)

    def check_winner(self) -> Optional[str]:
        """Check if any player has won (100+ points)."""
        for p in self.players:
            if p["score"] >= 100:
                self.winner = p["name"]
                return p["name"]
        return None


class StateManager:
    """Manages game state with automatic disk persistence."""

    def __init__(self, state_file: Path = STATE_FILE, config_file: Path = CONFIG_FILE):
        self.state_file = state_file
        self.config_file = config_file
        self.state = self._load()

    def _load_config(self) -> list:
        """Load players from config file."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file required: {self.config_file}")
        with open(self.config_file, "r") as f:
            config = json.load(f)
            return config["players"]

    def _load(self) -> GameState:
        """Load state from disk, or create initial state with configured players."""
        if self.state_file.exists():
            with open(self.state_file, "r") as f:
                data = json.load(f)
                return GameState(**data)
        # Initialize with configured players
        players = self._load_config()
        return GameState(players=players, game_started=True)

    def save(self):
        """Persist current state to disk."""
        with open(self.state_file, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    def submit_proposal(self, proposer: str, description: str, diff: str, branch: str) -> Optional[int]:
        """
        Submit a new proposal (PR) for voting.
        Returns the proposal number, or None if invalid.
        """
        current = self.state.current_player()
        if not current or current["name"] != proposer:
            return None
        if self.state.turn_phase != "proposal":
            return None

        proposal_id = self.state.next_proposal_number
        self.state.next_proposal_number += 1

        self.state.pending_pr = {
            "id": proposal_id,
            "proposer": proposer,
            "description": description,
            "diff": diff,
            "branch": branch,
            "votes": {proposer: True}  # Proposer votes yes automatically
        }
        self.state.turn_phase = "voting"
        self.save()
        return proposal_id

    def submit_vote(self, voter: str, vote: bool) -> bool:
        """Submit a vote on the pending PR."""
        if not self.state.pending_pr:
            return False
        if self.state.turn_phase != "voting":
            return False
        if not self.state.get_player(voter):
            return False

        self.state.pending_pr["votes"][voter] = vote
        self.save()
        return True

    def all_votes_in(self) -> bool:
        """Check if all players have voted."""
        if not self.state.pending_pr:
            return False
        votes = self.state.pending_pr["votes"]
        return all(p["name"] in votes for p in self.state.players)

    def resolve_vote(self) -> Optional[dict]:
        """
        Resolve the pending vote and return the result.
        Returns: {passed: bool, points: int, votes: dict}
        """
        if not self.state.pending_pr or not self.all_votes_in():
            return None

        pr = self.state.pending_pr
        votes = pr["votes"]
        favorable = sum(1 for v in votes.values() if v)
        total = len(votes)

        # Rule 203: Unanimity for first 2 circuits, then majority
        if self.state.circuits_completed >= 2:
            passed = favorable > total / 2  # Simple majority
        else:
            passed = all(votes.values())  # Unanimity required

        proposer = self.state.get_player(pr["proposer"])
        points = 0

        if proposer is None:
            return None

        if passed:
            points = self.state.calculate_points(pr["id"], favorable, total)
            proposer["score"] += points

            # Rule 204: NO voters get 10 points on non-unanimous wins
            if not all(votes.values()):
                for player_name, voted_yes in votes.items():
                    if not voted_yes:
                        player = self.state.get_player(player_name)
                        if player:
                            player["score"] += 10
        else:
            # Rule 206: Proposer loses 10 points on defeat
            proposer["score"] -= 10

        # Record in history
        self.state.history.append({
            "turn_number": len(self.state.history) + 1,
            "proposer": pr["proposer"],
            "proposal_id": pr["id"],
            "description": pr["description"],
            "votes": votes.copy(),
            "passed": passed,
            "points_awarded": points if passed else -10
        })

        result = {
            "passed": passed,
            "points": points if passed else -10,
            "votes": votes,
            "proposal_id": pr["id"],
            "branch": pr["branch"] if passed else None
        }

        # Check for winner
        winner = self.state.check_winner()
        if winner:
            result["winner"] = winner

        self.state.turn_phase = "completed"
        self.save()
        return result

    def complete_turn(self):
        """Complete the current turn and advance to the next player."""
        self.state.advance_turn()
        self.save()

    def get_state_summary(self) -> dict:
        """Return a summary of the current game state for API responses."""
        return {
            "players": self.state.players,
            "current_player": self.state.current_player(),
            "turn_phase": self.state.turn_phase,
            "next_proposal_number": self.state.next_proposal_number,
            "pending_pr": self.state.pending_pr,
            "game_started": self.state.game_started,
            "winner": self.state.winner,
            "history_length": len(self.state.history),
            "circuits_completed": self.state.circuits_completed,
            "majority_voting": self.state.circuits_completed >= 2
        }

    def reset(self):
        """Reset the game to initial state (for testing)."""
        self.state = GameState(players=[])
        self.save()
