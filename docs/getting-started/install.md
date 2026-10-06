# Install

## Requirements

- *Anno 1404 History Edition* (Steam, GOG, retail — any source)
- Python **3.10 or newer**
- The GUI needs **tkinter** (usually already installed; see below if not)
- No other dependencies — the whole tool is Python standard library

### tkinter check / install

Open a terminal and run:

```bash
python3 -c "import tkinter; print('tkinter OK')"
```

If that fails:

- **Debian / Ubuntu / SteamOS**: `sudo apt install python3-tk`
- **Arch**: `sudo pacman -S tk`
- **Windows**: the standard installer from [python.org](https://python.org)
  includes tkinter — just re-run "Modify" and tick *Tcl/tk* if you deselected it.
- **macOS**: `brew install python-tk` (for Homebrew Python)

## Get the tool

Download the release zip (`annoedit-<version>.zip`) and unpack it
anywhere. Optionally install it so `annoedit` and `annoedit-gui` are on
your PATH:

```bash
cd annoedit-<version>
python3 -m pip install .
```

## Find your data1.rda

The tool edits exactly one game file: `addon/data1.rda`.

Default locations (adjust `<user>` to your Windows login):

| Store | Path |
|---|---|
| Steam (Windows) | `C:\Program Files (x86)\Steam\steamapps\common\Anno 1404 - History Edition\addon\data1.rda` |
| Steam (Linux/Proton) | `~/.local/share/Steam/steamapps/common/Anno 1404 - History Edition/addon/data1.rda` |
| GOG Galaxy | `C:\GOG Games\Anno 1404 - History Edition\addon\data1.rda` |

Tip: in Steam, right-click the game → *Manage → Browse local files* to open
the game folder directly; `data1.rda` is inside the `addon` subfolder.

## The 5-minute sanity check

1. Start the tool:

   ```bash
   python3 -m annoedit.gui.app
   ```

2. Click the red **Provide vanilla…** banner and pick an unmodified
   `addon/data1.rda` (if your game is unmodded, that is simply your game's
   file). Then click the orange **Set live location…** banner and pick the
   `addon/data1.rda` your game loads.
3. Click **Open live data1.rda** (or **Open vanilla copy**). The window
   fills with the roster of AI characters. **That's it, everything works.**

(Prefer to stay in the terminal? `python3 -m annoedit.cli list
<path-to-data1.rda>` prints the same roster.)

Next: [The 5-minute walkthrough](walkthrough.md)
