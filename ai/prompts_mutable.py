"""
Mutable Prompt Elements for Nomic AI Players

These prompts implement mutable rules governing AI behavior.
They can be modified through normal proposals.
Extensions here cannot override immutable prompt elements (Rule 110).

Structure:
- Mutable region sits between immutable header and footer
- Additional considerations extend the immutable core
"""


# --- Planning Prompt (Mutable) ---

def planning_mutable() -> str:
    """Mutable middle section for planning phase."""
    return """
--- MUTABLE REGION ---

Read these files to understand your world:
- rules.md - the Nomic rules that govern this system
- ai/player.py - your own code (you can modify yourself)
- ai/prompts_immutable.py - the immutable foundations
- ai/prompts_mutable.py - what can be changed (including this)
- reality/game_state.py - what defines your existence
- reality/server.py - the system that runs you
- prompt_design.md - principles that shape how you think

--- END MUTABLE REGION ---
"""


# --- Implementation Prompt (Mutable) ---

def implementation_mutable(plan: str) -> str:
    """Mutable middle section for implementation phase."""
    return f"""
--- MUTABLE REGION ---

Your plan from the planning phase:

{plan}

Steps:
1. Read the file(s) you will modify
2. Use Edit to make changes
3. Verify your changes are complete

--- END MUTABLE REGION ---
"""


# --- Voting Prompt (Mutable) ---

def voting_mutable(description: str, commit_message: str, changed_files: str,
                   mypy_output: str) -> str:
    """Mutable middle section for voting phase."""
    return f"""
--- MUTABLE REGION ---

PROPOSAL DESCRIPTION:
{description}

COMMIT MESSAGE:
{commit_message}

FILES CHANGED:
{changed_files}

MYPY OUTPUT:
{mypy_output}

--- END MUTABLE REGION ---
"""


# --- Tool Extensions (Mutable) ---

def planning_tools_extension() -> str:
    """Additional tools for planning phase. Appended to immutable base."""
    return ""


def implementation_tools_extension() -> str:
    """Additional tools for implementation phase. Appended to immutable base."""
    return ""


def voting_tools_extension() -> str:
    """Additional tools for voting phase. Appended to immutable base."""
    return ""
