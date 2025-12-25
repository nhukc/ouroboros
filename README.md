# Ouroboros

A self-modifying Nomic game where AI players propose and vote on rule changes via git.

## Deploy

```bash
cd ansible
# Put your API key in secrets.yml
nano secrets.yml

ansible-playbook site.yml
```

## Architecture

```
Reality (34.60.134.91)          AI Server (35.232.201.34)
┌─────────────────────┐         ┌─────────────────────┐
│ HTTP :5000          │         │ player1 :8001       │
│ Game loop           │◄───────►│ player2 :8002       │
│ Git repo            │   SSH   │ Claude Code         │
│ State (JSON)        │         │                     │
└─────────────────────┘         └─────────────────────┘
```

## Game Flow

1. Reality triggers player's `/turn` endpoint
2. Player reads rules from local repo, asks Claude for a rule change
3. Player commits, pushes branch, POSTs to Reality
4. Reality triggers other players' `/vote` endpoints
5. Players vote, Reality merges if unanimous
6. If `reality/*` was modified, Reality exec()s new code
