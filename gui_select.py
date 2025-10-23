"""Simple Tkinter GUI for selecting fantasy starters.

This module loads a team roster from config.yaml, persists selection state to
state/starters.json, and presents a togglable grid of buttons for each roster
member. The GUI is intentionally minimal and expects the config file to contain
a "team_roster" list.

Files:
- config.yaml: must contain "team_roster"
- state/starters.json: created/updated to store selected starters
"""
import json
import tkinter as tk
from pathlib import Path
import yaml
from logger import get_logger
log = get_logger(__name__)

STATE_FILE = Path("state/starters.json")
CONFIG_FILE = Path("config.yaml")

def load_roster():
    """Load the team roster from the configuration file.

    Returns:
        list[str]: The list of player names from config.yaml under "team_roster".

    Raises:
        FileNotFoundError: If CONFIG_FILE does not exist.
        KeyError: If "team_roster" is missing in the loaded config.

    """

    log.debug(f"Loading starters from {STATE_FILE}")

    cfg = yaml.safe_load(open(CONFIG_FILE, "r"))

    return cfg["team_roster"]

def load_state():
    """Load persisted selection state from disk.

    Returns:
        dict: Parsed JSON state if present, otherwise an empty dict.
    """

    if STATE_FILE.exists():
        return json.load(open(STATE_FILE, "r"))
    return {}

def save_state(state):
    """Persist the selection state to disk.

    Args:
        state (dict): State mapping to serialize (expected to contain "starters").
    """
    log.debug(f"Saving starters -> {state.get('starters', [])}")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(state, open(STATE_FILE, "w"), indent=2)

def main():
    """Launch the Tkinter UI to toggle starters and persist selections.

    Behavior:
    - Loads roster via load_roster() and previous state via load_state().
    - Displays one button per roster entry; clicking toggles selection and saves state.
    - Runs the Tk main loop until the window is closed.
    """
    roster = load_roster()
    state = load_state()
    starters = set(state.get("starters", []))

    root = tk.Tk()
    root.title("Fantasy Starters")

    tiles = []
    def toggle(name, btn):
        """Toggle a player's selection state and update the button visuals.

        Args:
            name (str): Player name to toggle.
            btn (tk.Button): Button widget to update appearance for selection.
        """
        if name in starters:
            starters.remove(name)
            btn.config(bg="gray20", fg="white")
        else:
            starters.add(name)
            btn.config(bg="green", fg="black")
        save_state({"starters": sorted(list(starters))})

    frame = tk.Frame(root, padx=12, pady=12, bg="black")
    frame.pack(fill="both", expand=True)

    for i, name in enumerate(roster):
        is_on = (name in starters)
        btn = tk.Button(frame, text=name, width=28, height=2,
                        bg=("green" if is_on else "gray20"),
                        fg=("black" if is_on else "white"),
                        relief="ridge", bd=2,
                        command=lambda n=name, b=None: None)
        btn.grid(row=i//2, column=i%2, padx=8, pady=8, sticky="ew")

        def make_cmd(b=btn, n=name):
            """Return a callable that toggles selection for the bound player/button.

            This factory captures the current button and name to avoid late-binding issues.
            """
            return lambda: toggle(n, b)
        btn.config(command=make_cmd())
        tiles.append(btn)

    root.mainloop()

if __name__ == "__main__":
    main()
