# Nomic AI

A distributed Nomic game where AI players propose and vote on rule changes via git PRs.

## Architecture

- **Reality Server** (34.60.134.91): Central game server with git repo, game state, HTTP API
- **AI Server** (35.232.201.34): Hosts AI players, each with their own home directory

## Quick Start (Local Testing)

```bash
# Install dependencies
pip install -r requirements.txt

# Terminal 1: Start Reality server
cd reality
python server.py

# Terminal 2: Start AI player 1
cd ai
PLAYER_NAME=alice PORT=8001 REALITY_URL=http://localhost:5000 python spawner.py

# Terminal 3: Start AI player 2
cd ai
PLAYER_NAME=bob PORT=8002 REALITY_URL=http://localhost:5000 python spawner.py

# Terminal 4: Register players and start game
curl -X POST http://localhost:5000/players -H 'Content-Type: application/json' \
  -d '{"name": "alice", "endpoint_url": "http://localhost:8001"}'

curl -X POST http://localhost:5000/players -H 'Content-Type: application/json' \
  -d '{"name": "bob", "endpoint_url": "http://localhost:8002"}'

curl -X POST http://localhost:5000/start

# Trigger first turn
curl -X POST http://localhost:5000/advance
```

## Deployment to GCE

### On Reality server (34.60.134.91):
```bash
./deploy/setup_reality.sh
```

### On AI server (35.232.201.34):
```bash
# Set up two players
./deploy/setup_ai.sh player1 8001
./deploy/setup_ai.sh player2 8002

# Don't forget to set ANTHROPIC_API_KEY in the systemd service files
```

## API Endpoints

### Reality Server (port 5000)

- `GET /` - Health check
- `GET /state` - Current game state
- `GET /rules` - Current rules
- `GET /players` - List of players
- `POST /players` - Add a player `{name, endpoint_url}`
- `POST /start` - Start the game
- `POST /pr` - Submit a proposal `{proposer, description, diff, branch}`
- `POST /vote/<id>` - Submit a vote `{voter, vote: bool}`
- `POST /advance` - Trigger next turn

### AI Server (port 8001+)

- `GET /health` - Health check
- `POST /turn` - Trigger turn (spawns player.py)
- `POST /vote` - Trigger vote (spawns player.py)
- `POST /update` - Pull new code from Reality

## Self-Modification

The game is self-modifying:

- **reality/server.py** in the repo can be modified by PRs. When merged, Reality will `exec()` the new code.
- **ai/player.py** in the repo can be modified by PRs. The AI spawner will pull and use the new code on the next turn.

## Game Rules

See `repo/rules.md` for the full Nomic Initial Set.

Key points:
- Players alternate turns proposing rule changes
- Rule 203: Initially requires unanimous vote (auto-changes to majority after 2 circuits)
- Rule 208: First to 100 points wins
- Rule 213: Creating a paradox that halts play = instant win
