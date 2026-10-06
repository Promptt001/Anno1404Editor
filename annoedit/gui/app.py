#!/usr/bin/env python3
"""annoedit.gui.app — tkinter front-end (v2 main window).

Run:  python3 -m annoedit.gui.app   (needs python3-tk)

The window is a THIN layer: every button maps onto a Session method
(annoedit/session.py), which is fully headless-testable
(tests/test_session.py). No game logic lives here.

Layout:
  top:    [Open data1.rda…] [Open live] [Open vanilla copy] |
          [Provide vanilla…] [Set live location…] [Saved exports…] [Log]
          [Restore Vanilla] [Apply & save…] [Save as export…]   archive label
  left:   roster (badges: preset / pending counts) + preset dropdown
  right:  shared DialTable (category | dial | value | vanilla | new | source,
          find box, edit bar, schema doc) — edits update rows in place
  bottom: status line + persistent-setup indicator

Persistence: the vanilla copy (data1.rda_vanilla), the live location and
the last opened archive live under ~/.anno1404gameeditor/ and are picked
up at every launch; the last archive is reopened automatically.
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .. import __version__
from ..applog import log as _log
from ..applog import startup_note, tail as log_tail
from ..session import Session, SessionError
from .. import ops
from ..plan import plan_hash
from .editor import EditorWindow
from .picker import ask_path
from .tabs import ExtrasTab, FertilityTab
from .widgets import DialTable, grab_when_mapped

# The old PICKER constant was UNUSED (only the in-app
# PathPicker + its system-dialog fallback are live) and carried the
# (pattern, description) tuples with an inverted-order comment — deleted.
# tkinter filetypes are (label, pattern): see gui/picker.py.

# banner flash period, ms — the red banners blink until dismissed
_BANNER_FLASH_MS = 600


class ExportManagerDialog(tk.Toplevel):
    """Saved data1.rda manager: list, open, rename, delete (vanilla guard).

    Rows: 'vanilla' (the stored data1.rda_vanilla copy — rename refused,
    delete via explicit confirm) + every named export data1.rda_<name>.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Saved data1.rda files — Anno1404 GameEditor")
        self.geometry("760x430")
        ttk.Label(self, text=(
            "Saved data1.rda copies — stored under ~/.anno1404gameeditor/exports.\n"
            "'vanilla' = your stored vanilla copy (data1.rda_vanilla); named\n"
            "exports appear below it (data1.rda_<export name>).")).pack(
                fill="x", padx=8, pady=(8, 4))
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "md5", "size", "saved_at", "note")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=12)
        widths = {"name": 160, "md5": 110, "size": 90, "saved_at": 150,
                  "note": 190}
        for c in cols:
            self.tree.heading(c, text={"name": "Export name",
                                       "md5": "md5 (first 12)",
                                       "size": "size",
                                       "saved_at": "saved at",
                                       "note": "note"}[c])
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Button(btns, text="Open",
                   command=self._open_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="Rename…",
                   command=self._rename).pack(side="left", padx=2)
        ttk.Button(btns, text="Delete",
                   command=self._delete).pack(side="left", padx=2)
        ttk.Button(btns, text="Refresh",
                   command=self._refresh).pack(side="left", padx=2)
        self._rows = []
        self._refresh()

    def _refresh(self):
        """Reload the saved-export list from the session's export store."""
        self.tree.delete(*self.tree.get_children())
        self._rows = []
        try:
            rows = self.app.ses.list_saved_exports()
        except Exception as e:
            messagebox.showerror("List failed", str(e), parent=self)
            rows = []
        for r in rows:
            self.tree.insert("", "end", values=(
                r["name"], (r.get("md5") or "")[:12], r.get("size", ""),
                r.get("saved_at", ""), r.get("note", "")))
            self._rows.append(r)

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._rows[self.tree.index(sel[0])]

    def _open_selected(self):
        """Open the selected saved data1.rda as the new editing baseline."""
        row = self._selected_row()
        if row is None:
            return
        try:
            path = self.app.ses.load_saved_export_path(row["name"])
        except Exception as e:
            messagebox.showerror("Open failed", str(e), parent=self)
            return
        self.destroy()
        self.app.open_archive(path)

    def _rename(self):
        """Rename a selected named export (vanilla copy refused)."""
        row = self._selected_row()
        if row is None:
            return
        if row.get("name") == "vanilla":
            messagebox.showinfo("Vanilla copy",
                                "The vanilla copy cannot be renamed.",
                                parent=self)
            return
        new = simpledialog.askstring(
            "Rename export", f"Rename {row['name']!r} to:", parent=self)
        if not new or not new.strip() or new.strip() == row["name"]:
            return
        try:
            self.app.ses.rename_saved_export(row["name"], new.strip())
        except Exception as e:
            messagebox.showerror("Rename failed", str(e), parent=self)
            return
        self._refresh()

    def _delete(self):
        """Delete a selected saved export (vanilla copy via confirm only)."""
        row = self._selected_row()
        if row is None:
            return
        if row.get("name") == "vanilla":
            if not messagebox.askyesno(
                    "Delete vanilla copy",
                    "Delete your stored vanilla copy (data1.rda_vanilla)?\n"
                    "Restore-vanilla and reset-to-vanilla will stop "
                    "working until you provide a vanilla data1.rda again.",
                    parent=self):
                return
            try:
                self.app.ses.exports_store.delete_vanilla_copy()
            except Exception as e:
                messagebox.showerror("Delete failed", str(e), parent=self)
                return
            self._refresh()
            if hasattr(self.app, "_refresh_banners"):
                self.app._refresh_banners()
            return
        if not messagebox.askyesno("Delete export",
                                   f"Delete saved export {row['name']!r}?",
                                   parent=self):
            return
        try:
            self.app.ses.delete_saved_export(row["name"])
        except Exception as e:
            messagebox.showerror("Delete failed", str(e), parent=self)
            return
        self._refresh()


class ReviewChangesDialog(tk.Toplevel):
    """Pending-changes review window: line-by-line table, then a save choice.

    Every pending change is one row: character | dial | old value -> new
    value (+ section), so the user approves exactly what will be
    written. The bottom row offers the two save targets:
      * 'Save to live'     -> apply over the game's live archive (flash)
      * 'Save as export…' -> build into the exports store under a name
    'Cancel' closes without building anything.
    """

    def __init__(self, parent, app, on_save=None, allow_live=True,
                 base=None):
        super().__init__(parent)
        self.app = app
        self.on_save = on_save          # callback(action, export_name)
        self.result = None              # 'live' | ('export', name) | None
        self._allow_live = allow_live
        self.title("Review changes — Anno1404 GameEditor")
        self.geometry("860x560")
        self.transient(parent)
        # Base = the project the save will write (the live project for
        # save-to-live; None = the opened archive). _rebind(target)
        # recomputes the rows for the save target the user actually
        # picks: "Save as export" builds from the opened archive, so it
        # must show rows computed against that, not against live.
        self._base = base
        rows, totals = app.ses.pending_change_rows(base)
        self._rows = rows
        self._totals = totals
        summary = (f"{totals['dials']} AI dial edits, "
                   f"{totals['relations']} relations edits, "
                   f"{totals['extras']} extras edits, "
                   f"{totals['fertility']} fertility edits — pending")
        ttk.Label(self, text="Pending changes — review before saving",
                 font=("DejaVu Sans", 11, "bold")).pack(
                     fill="x", padx=8, pady=(8, 0))
        # summary as a stored label so _rebind can update the counts the
        # user approves when the save target switches the base
        self.summary_lbl = ttk.Label(self, text=summary)
        self.summary_lbl.pack(fill="x", padx=8, pady=(0, 4))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("section", "character", "dial", "old", "new")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=18)
        widths = {"section": 90, "character": 150, "dial": 260,
                  "old": 130, "new": 110}
        for c in cols:
            self.tree.heading(c, text={
                "section": "Section", "character": "Character / asset",
                "dial": "Dial", "old": "Old value",
                "new": "New value"}[c])
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        for r in rows:
            self.tree.insert("", "end", values=(
                r["section"], r["character"], r["dial"],
                "" if r["old"] is None else str(r["old"]),
                str(r["new"])))

        note = ttk.Label(self, justify="left", text=(
            "Only the AI profile files (and assets.xml / randommapgenerator.xml\n"
            "when extras / fertility edits are pending) inside data1.rda\n"
            "change; everything else stays byte-identical. Test on a NEW\n"
            "endless game — old saves may have baked-in AI values."))
        note.pack(fill="x", padx=8, pady=(2, 4))
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        live = self.app.ses.default_target()
        self.live_btn = ttk.Button(btns, text="Save to live",
                                   command=self._save_live,
                                   state="normal" if (allow_live and live)
                                   else "disabled")
        self.live_btn.pack(side="left")
        ttk.Button(btns, text="Save as export…",
                   command=self._save_export).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel",
                   command=self.destroy).pack(side="right")
        ttk.Label(btns, justify="left", text=(
            f"writes to: {App._compact_path(live, 60)}" if live else
            "live game location NOT set — use 'Set live location…' first")
                  ).pack(side="right", padx=8)
        self._live_lbl = live
        # initial focus on nothing so Enter does not fire a save button
        self.bind("<Escape>", lambda _e: self.destroy())
        grab_when_mapped(self)       # modal: one review at a time

    def _rows_for_target(self, target):
        """(rows, totals) for the base the given save target will write.

        'live' replays the pending edits onto the LIVE file — rows come
        from the live base (the base this dialog was built with).
        'export' builds from the OPENED archive — rows come from the
        opened project, so the no-op rule-row drops match exactly what
        the export build drops against the opened entries. The displayed
        list must always match the base of the build the approval
        dispatches; otherwise the user approves one list and a
        different one is written.
        """
        if target == "export":
            return self.app.ses.pending_change_rows(self.app.ses.proj)
        return self.app.ses.pending_change_rows(
            getattr(self, "_base", None))

    def _rebind(self, target):
        """Recompute + redisplay the rows for the chosen save target."""
        rows, totals = self._rows_for_target(target)
        self._rows = rows
        self._totals = totals
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", values=(
                r["section"], r["character"], r["dial"],
                "" if r["old"] is None else str(r["old"]),
                str(r["new"])))
        self.summary_lbl.config(text=(
            f"{totals['dials']} AI dial edits, "
            f"{totals['relations']} relations edits, "
            f"{totals['extras']} extras edits, "
            f"{totals['fertility']} fertility edits — "
            + ("saving over the LIVE file" if target == "live"
               else "building from the OPENED archive")))

    def _save_live(self):
        """Approve: apply the pending changes over the live archive."""
        self._rebind("live")
        if self.on_save:
            self.on_save("live", None)
        self.result = "live"
        self.destroy()

    def _save_export(self):
        """Approve: build into the exports store under a chosen name."""
        # An export builds from the OPENED archive, not the live file:
        # re-display those rows before anything is approved. A cancelled
        # prompt or a refused overwrite restores the live-based rows.
        self._rebind("export")
        name = simpledialog.askstring(
            "Export name",
            "Name this export (letters/digits/-/_/.):", parent=self)
        if not name or not name.strip():
            self._rebind("live")
            return
        try:
            from ..exports import slug_export_name
            safe = slug_export_name(name.strip())
        except Exception as e:
            messagebox.showerror("Invalid export name", str(e), parent=self)
            self._rebind("live")
            return
        # Confirm before overwriting an existing export (names come from
        # the store's own metadata).
        existing = {e.get("name") for e in
                    (self.app.ses.list_saved_exports() or [])}
        if safe in existing and not messagebox.askyesno(
                "Overwrite export?",
                f"An export named {safe!r} already exists.\n"
                "Overwrite it with the new build?", parent=self):
            self._rebind("live")
            return
        if self.on_save:
            self.on_save("export", safe)
        self.result = ("export", safe)
        self.destroy()




class App(tk.Tk):
    """Main tkinter window: thin GUI layer over the headless Session."""

    def __init__(self, auto_open=True):
        super().__init__()
        self.title(f"Anno1404 GameEditor — {__version__}")
        self.geometry("1180x760")
        self.minsize(900, 560)
        self.ses = Session()
        self._banner_flash_on = True
        self._editors = {}          # guid -> open EditorWindow
        self._cur_guid = None       # character shown in the dial table
        self._busy_flag = False
        self._busy_label = ""
        self._build_widgets()
        self._refresh_banners()
        self._refresh_state()
        self._set_status(self._startup_text())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if auto_open:
            # let the window paint first, then reopen the last archive
            self.after(120, self._startup_open)

    # ------------------------------------------------------------- startup

    def _startup_text(self):
        """Status line at launch: what is already stored (persistent)."""
        bits = []
        if self.ses.exports_store.has_vanilla_copy():
            bits.append("vanilla copy on file")
        else:
            bits.append("no vanilla copy yet — click 'Provide vanilla…'")
        live = self.ses.live_path()
        bits.append(f"live game file: {self._compact_path(live)}" if live
                    else "live game location not set")
        # Surface skipped preset files (a malformed file is logged and
        # reported here instead of blocking startup).
        if getattr(self.ses, "preset_load_errors", None):
            bits.append(f"{len(self.ses.preset_load_errors)} preset file(s) "
                        "skipped — see annoedit.log")
        return "ready — " + " · ".join(bits)

    def _startup_target(self):
        """The archive to reopen at launch: last opened, else live."""
        last = self.ses.settings.get("last_opened")
        if last and os.path.isfile(last):
            return last
        return self.ses.live_path()

    def _startup_open(self):
        if self.ses.proj is not None:
            return
        path = self._startup_target()
        if path:
            self.open_archive(path, background=True, quiet=True)

    def on_close(self):
        """Window close: refuse while busy warn about unsaved pending
        edits, release the lock."""
        if self._busy_flag:
            messagebox.showinfo(
                "Busy",
                "A background job is still running (build/restore).\n"
                "Wait for it to finish before closing.")
            return
        if self._has_pending() and not messagebox.askyesno(
                "Quit", f"You have {self._pending_summary()} that are not "
                "saved yet.\nQuit anyway and discard them?"):
            return
        try:
            self.ses.close()
        finally:
            self.destroy()

    def destroy(self):
        """Cancel the banner timer first (no 'invalid command' noise)."""
        if getattr(self, "_flash_after", None):
            try:
                self.after_cancel(self._flash_after)
            except tk.TclError:
                pass
            self._flash_after = None
        super().destroy()

    # ------------------------------------------------------------- banners

    def _refresh_banners(self):
        """Show/hide the two setup banners based on session state.

        Banner 1 (red, flashing): no stored vanilla copy yet — the
        user must provide the pristine vanilla data1.rda.
        Banner 2 (orange): live archive location not set — Flash and
        Restore need to know where the game's addon/data1.rda lives.
        """
        need_vanilla = not self.ses.exports_store.has_vanilla_copy()
        need_live = self.ses.live_path() is None
        if need_vanilla:
            if self.vanilla_banner is None:
                self.vanilla_banner = self._make_banner(
                    "⚠ PROVIDE THE VANILLA data1.rda — click here (a pristine, "
                    "unmodded copy is stored once and kept between launches)",
                    on_color="#b00020", off_color="#7a0016",
                    action=self.provide_vanilla)
        elif self.vanilla_banner is not None:
            self.vanilla_banner.destroy()
            self.vanilla_banner = None
        if need_live:
            if self.live_banner is None:
                self.live_banner = self._make_banner(
                    "⚠ SET THE GAME'S LIVE data1.rda LOCATION — click here "
                    "(where the game reads addon/data1.rda; 'Save to live' "
                    "and 'Restore Vanilla' write there)",
                    on_color="#e07000", off_color="#8a4400",
                    action=self.set_live_location)
        elif self.live_banner is not None:
            self.live_banner.destroy()
            self.live_banner = None
        self._refresh_state()

    def _make_banner(self, text, on_color, off_color, action):
        """Create a flashing warning banner; click triggers action."""
        lbl = tk.Label(self, text=text, bg=on_color, fg="white", anchor="w",
                       padx=8, pady=4, font=("TkDefaultFont", 10, "bold"),
                       cursor="hand2")
        lbl.pack(fill="x", padx=4, pady=2, before=self.open_btn.master)
        lbl._flash_on_color = on_color
        lbl._flash_off_color = off_color
        lbl._banner_action = action
        lbl.bind("<Button-1>", lambda _e: action())
        if lbl not in self._flashables:
            self._flashables.append(lbl)
        self._ensure_flash_timer()
        return lbl

    def _ensure_flash_timer(self):
        """Exactly one flash timer loop, started on first banner."""
        if not getattr(self, "_flash_timer_on", False):
            self._flash_timer_on = True
            self._flash_after = self.after(_BANNER_FLASH_MS, self._tick_flash)

    def _tick_flash(self):
        """Toggle all visible flashing banners between bright and dark."""
        self._banner_flash_on = not self._banner_flash_on
        alive = []
        for lbl in list(self._flashables):
            try:
                if lbl.winfo_exists():
                    lbl.config(bg=lbl._flash_on_color if self._banner_flash_on
                               else lbl._flash_off_color)
                    alive.append(lbl)
            except tk.TclError:
                pass
        self._flashables = alive
        if self._flashables:
            self._flash_after = self.after(_BANNER_FLASH_MS, self._tick_flash)
        else:
            self._flash_timer_on = False

    def _refresh_state(self):
        """Right side of the status bar: persistent setup at a glance."""
        if not hasattr(self, "state_lbl"):
            return
        van = "✓" if self.ses.exports_store.has_vanilla_copy() else "✗"
        live = "✓" if self.ses.live_path() else "✗"
        self.state_lbl.config(text=f"vanilla copy {van}   live location {live}")
        self._update_buttons()

    def provide_vanilla(self):
        """Banner action: pick the pristine vanilla data1.rda (persisted)."""
        path = ask_path(self, title="Provide your VANILLA addon/data1.rda "
                                    "(pristine, unmodded)",
                        suffixes=(".rda",), settings=self.ses.settings)
        if not path:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            info = self.ses.provide_vanilla(path)
        except SessionError as e:
            messagebox.showerror("Provide vanilla failed", str(e))
            return
        finally:
            self.config(cursor="")
        vclass = getattr(self.ses, "_vanilla_class", None)
        vtxt = {"verified": " — VERIFIED vanilla build (matches the known-vanilla hash table)",
                "modded": " — WARNING: this copy does NOT match the known vanilla hashes (a modded or patched build?)",
                "partial": " — UNKNOWN build (known members missing; cannot verify)"}.get(vclass, "")
        self._set_status(f"vanilla copy stored as data1.rda_vanilla "
                         f"(md5 {info['md5'][:12]}…) — kept between launches; "
                         "the Vanilla column and reset-to-vanilla now use it" + vtxt)
        if vclass == "modded":
            messagebox.showwarning(
                "Provided copy is not verified vanilla",
                "The file you provided parses as a data1.rda archive, but its "
                "members do NOT match the known vanilla hash table.\n\n"
                "If this is a modded copy, the 'Vanilla' reference column and "
                "restores will use MODDED values while claiming vanilla.\n\n"
                "Provide the pristine file from a fresh game install or "
                "Steam's 'verify game files' instead.")
        self._refresh_banners()
        self._refresh_roster()
        self._show_profile(self._current_profile(), keep_view=True)
        if self.ses.proj is None and messagebox.askyesno(
                "Open now?", "Open the vanilla copy as your editing "
                "baseline now?\n(Recommended: edits are then always "
                "'vanilla + your changes'.)"):
            self.open_archive(self.ses.exports_store.vanilla_path)

    def set_live_location(self):
        """Banner action: set where the game's live data1.rda lives (persisted)."""
        path = ask_path(self, title="Select your game's LIVE addon/data1.rda",
                        suffixes=(".rda",), settings=self.ses.settings)
        if not path:
            return
        try:
            p = self.ses.set_live_path(path)
        except SessionError as e:
            messagebox.showerror("Set live location failed", str(e))
            return
        self._set_status(f"live game location set: {p} — 'Save to live' "
                         "writes there, 'Restore Vanilla' restores there")
        self._refresh_banners()
        if self.ses.proj is None and messagebox.askyesno(
                "Open now?", f"Open {p} as the editing baseline now?"):
            self.open_archive(p)

    # ---------------------------------------------------------------- UI

    def _build_widgets(self):
        self.vanilla_banner = None
        self.live_banner = None
        self._flashables = []
        # Toolbar = two fixed rows so the save buttons can never be
        # pushed off-screen by a long archive path:
        #   row 1: archive actions (open / open live / vanilla / exports / log)
        #   row 2: save actions (Restore / Apply & save / Save as export) +
        #          the archive label, kept COMPACT (file name + md5; the
        #          full path is only a hover tooltip).
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=6, pady=(4, 0))
        self.open_btn = ttk.Button(actions, text="Open data1.rda…",
                                   command=self.open_archive)
        self.open_btn.pack(side="left")
        self.open_live_btn = ttk.Button(actions, text="Open live data1.rda",
                                        command=self.open_live_archive)
        self.open_live_btn.pack(side="left", padx=4)
        self.open_vanilla_btn = ttk.Button(actions, text="Open vanilla copy",
                                           command=self.open_vanilla_copy)
        self.open_vanilla_btn.pack(side="left", padx=4)
        ttk.Separator(actions, orient="vertical").pack(side="left", fill="y",
                                                       padx=6)
        self.provide_btn = ttk.Button(actions, text="Provide vanilla…",
                                      command=self.provide_vanilla)
        self.provide_btn.pack(side="left", padx=4)
        self.live_btn = ttk.Button(actions, text="Set live location…",
                                   command=self.set_live_location)
        self.live_btn.pack(side="left", padx=4)
        self.exports_btn = ttk.Button(actions, text="Saved exports…",
                                      command=self.open_export_manager)
        self.exports_btn.pack(side="left", padx=4)
        self.log_btn = ttk.Button(actions, text="View log…",
                                  command=self.view_log)
        self.log_btn.pack(side="left", padx=4)

        save = ttk.Frame(self)
        save.pack(fill="x", padx=6, pady=(4, 4))
        self.restore_btn = ttk.Button(save, text="Restore Vanilla",
                                      command=self.restore_vanilla,
                                      state="disabled")
        self.restore_btn.pack(side="left")
        self.flash_btn = ttk.Button(save, text="Apply & save…",
                                    command=self.flash, state="disabled")
        self.flash_btn.pack(side="left", padx=4)
        self.export_btn = ttk.Button(save, text="Save as export…",
                                     command=self.export, state="disabled")
        self.export_btn.pack(side="left")
        self.path_lbl = ttk.Label(save, text="no archive loaded",
                                  anchor="e", justify="right")
        self.path_lbl.pack(side="right", fill="x", expand=True, padx=8)
        self._archive_full_path = None
        self._path_tip = None
        self.path_lbl.bind("<Enter>", self._show_path_tip)
        self.path_lbl.bind("<Leave>", self._hide_path_tip)

        # status bar packed BEFORE the notebook so it can never be squeezed
        # off the bottom of a small window
        statusbar = ttk.Frame(self)
        statusbar.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        self.status = ttk.Label(statusbar, text="", anchor="w",
                                justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        self.state_lbl = ttk.Label(statusbar, text="", anchor="e",
                                   foreground="#555")
        self.state_lbl.pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=2)
        main = ttk.Frame(nb)            # tab 1: AI profiles
        nb.add(main, text="AI profiles")
        self.xtab = ExtrasTab(nb, self)   # tab 2: EXTRAS (global dials)
        nb.add(self.xtab, text="EXTRAS (global dials)")
        self.ftab = FertilityTab(nb, self)  # tab 3: island fertility
        nb.add(self.ftab, text="FERTILITY (island crops)")
        self.notebook = nb

        left = ttk.Frame(main)
        left.pack(side="left", fill="y", padx=6, pady=4)
        ttk.Label(left, text="Characters (double-click = editor window)"
                  ).pack(anchor="w")
        rf = ttk.Frame(left)
        rf.pack(fill="both", expand=True)
        self.roster = tk.Listbox(rf, width=44, exportselection=False,
                                 activestyle="none")
        rsb = ttk.Scrollbar(rf, orient="vertical", command=self.roster.yview)
        self.roster.configure(yscrollcommand=rsb.set)
        self.roster.pack(side="left", fill="both", expand=True)
        rsb.pack(side="left", fill="y")
        self.roster.bind("<<ListboxSelect>>", self.on_select_char)
        self.roster.bind("<Double-1>", self.on_open_editor)
        self.roster.bind("<Return>", self.on_open_editor)
        pmid = ttk.Frame(left)
        pmid.pack(fill="x", pady=(8, 2))
        ttk.Label(pmid, text="Preset:").pack(side="left")
        self.preset_var = tk.StringVar(value="")
        self.preset_box = ttk.Combobox(pmid, textvariable=self.preset_var,
                                       state="disabled", width=18)
        self.preset_box.pack(side="left", padx=4)
        self.preset_box.bind("<<ComboboxSelected>>", self.on_preset)
        self.preset_note = ttk.Label(left, text="", foreground="#555")
        self.preset_note.pack(fill="x")
        ttk.Label(left, justify="left", foreground="#444", text=(
            "Vanilla   = back to the stored vanilla values\n"
            "Hardened = every key dial at the hardest\n"
            "            vanilla value (never easier)\n"
            "Personas = The Admiral / Spider / Conqueror\n"
            "            (playtested, per character)\n"
            "Custom   = keep your own edits")).pack(fill="x", pady=(6, 0))

        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True, padx=6, pady=4)
        self.char_lbl = ttk.Label(right, text="Open an archive, then pick a "
                                              "character on the left",
                                  font=("TkDefaultFont", 11, "bold"))
        self.char_lbl.pack(anchor="w", pady=(0, 4))
        # Column order: value | vanilla | new side by
        # side; 'source' (edit vs schema default) at the END.
        self.dials = DialTable(right, self.ses, show_category=True,
                               on_change=self.notify_changed,
                               on_status=self._set_status)
        self.dials.pack(fill="both", expand=True)
        self.tree = self.dials.tree
        self.doc = self.dials.doc

    def _show_path_tip(self, _ev=None):
        """Hover tooltip: the full archive path + backup state (compact row)."""
        if not self._archive_full_path:
            return
        self._hide_path_tip()
        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        x = self.path_lbl.winfo_rootx()
        y = self.path_lbl.winfo_rooty() + self.path_lbl.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self._archive_full_path, bg="#ffffe0",
                 relief="solid", borderwidth=1, padx=6, pady=2,
                 justify="left").pack()
        self._path_tip = tip

    def _hide_path_tip(self, _ev=None):
        if self._path_tip is not None:
            try:
                self._path_tip.destroy()
            except tk.TclError:
                pass
            self._path_tip = None

    @staticmethod
    def _compact_path(path, limit=44):
        """Compact an archive path for the toolbar row (middle-ellipsis)."""
        path = path.replace(os.sep, "/")
        if len(path) <= limit:
            return path
        keep = (limit - 1) // 2
        return path[:keep] + "…" + path[-keep:]

    def _set_status(self, text):
        self.status.config(text=text)

    # ------------------------------------------------------------ state

    def _has_pending(self):
        s = self.ses
        return bool(any(s.changes.values()) or s.extras or s.fert or s.rels)

    def _pending_summary(self):
        # Count the real changes the build would make against the opened
        # archive. A Vanilla click queues every key in scope; the no-op
        # rows among them are not changes and are not counted.
        c = self.ses.pending_counts()
        parts = []
        if c["dials"]:
            parts.append(f"{c['dials']} dial edits")
        if c["relations"]:
            parts.append(f"{c['relations']} relations changes")
        if c["extras"]:
            parts.append(f"{c['extras']} extras edits")
        if c["fertility"]:
            parts.append(f"{c['fertility']} fertility edits")
        return ", ".join(parts) or "no pending edits"

    def _update_buttons(self):
        """Enable/disable toolbar buttons from the current state."""
        if not hasattr(self, "restore_btn"):
            return
        busy = self._busy_flag
        opened = self.ses.proj is not None

        def st(flag):
            return "normal" if (flag and not busy) else "disabled"

        self.open_btn.config(state=st(True))
        self.open_live_btn.config(state=st(self.ses.live_path() is not None))
        self.open_vanilla_btn.config(
            state=st(self.ses.exports_store.has_vanilla_copy()))
        self.provide_btn.config(state=st(True))
        self.live_btn.config(state=st(True))
        self.flash_btn.config(state=st(opened))
        self.export_btn.config(state=st(opened))
        self.restore_btn.config(state=st(
            self.ses.has_restore_source() and
            (self.ses.live_path() is not None or opened)))
        # The exports manager can open an archive, which must never race
        # an in-flight background save. Disable it while busy, like every
        # other entry point.
        if hasattr(self, "exports_btn"):
            self.exports_btn.config(state=st(True))
        if self._cur_guid is not None and opened:
            self.preset_box.config(state="disabled" if busy else "readonly")

    def _busy(self, flag):
        """Disable the toolbar while a background job runs (and re-enable)."""
        self._busy_flag = bool(flag)
        if not flag:
            self._busy_label = ""
        self.config(cursor="watch" if flag else "")
        self._update_buttons()

    def _run_bg(self, label, work, done, fail_title):
        """Run work() in a thread; done(result) / error box on the Tk loop.

        The busy state is always cleared afterwards, on success and on
        failure.

        Single-flight: while a background job runs, a second _run_bg
        refuses instead of racing the first (e.g. an open must never
        interleave with a 30-60 s save whose callback would then swap
        the session back to the old archive).
        """
        if self._busy_flag:
            messagebox.showinfo(
                "Busy",
                f"A background job is still running ({self._busy_label}).\n"
                "Wait for it to finish before starting another one.")
            return
        self._busy(True)
        self._busy_label = str(label)
        self._set_status(label)
        q = queue.Queue()

        def runner():
            # No tkinter calls in here: Tk is not thread-safe. The result
            # goes through the queue and is picked up on the Tk loop.
            # BaseException is caught so a SystemExit/KeyboardInterrupt in
            # the worker cannot leave the UI stuck in the busy state; the
            # Tk side re-raises those after clearing it.
            try:
                q.put((True, work()))
            except BaseException as e:  # noqa: BLE001 — surfaced to the user
                q.put((False, e))

        def poll():
            try:
                ok, res = q.get_nowait()
            except queue.Empty:
                self.after(50, poll)
                return
            if ok:
                self._bg_done(done, res)
            else:
                self._bg_failed(fail_title, res)

        threading.Thread(target=runner, daemon=True).start()
        self.after(50, poll)

    def _bg_done(self, done, res):
        self._busy(False)
        # An exception inside a done-callback (apply_flash_result,
        # apply_restore_result, view refreshes) goes to the same failure
        # box as a worker error, not to a Tk traceback on stderr.
        try:
            done(res)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:          # noqa: BLE001 — surfaced to the user
            import traceback
            self._sync_closed()
            self._set_status("background completion failed: %s" % (e,))
            messagebox.showerror(
                "Background task failed",
                "The task finished but updating the window failed:\n\n"
                f"{e}\n\n{traceback.format_exc()[-1500:]}")

    def _bg_failed(self, title, err):
        self._busy(False)
        self._sync_closed()
        self._set_status(f"{title.lower()}: {err}")
        messagebox.showerror(title, str(err))

    def _sync_closed(self):
        """A failed open leaves the session closed: clear stale views."""
        if self.ses.proj is not None:
            return
        self._cur_guid = None
        self.roster.delete(0, "end")
        self.dials.clear()
        self.preset_var.set("")
        self.preset_box.config(values=[], state="disabled")
        self.preset_note.config(text="")
        self.char_lbl.config(text="Open an archive, then pick a character "
                                  "on the left")
        self.path_lbl.config(text="no archive loaded")
        self._archive_full_path = None
        self._update_buttons()

    # ---------------------------------------------------------------- open

    def open_archive(self, path=None, background=False, quiet=False):
        """Open data1.rda (in-app picker if no path) and refresh all tabs.

        Opening a different archive drops pending edits — confirm first.
        background=True parses in a worker thread (window stays live).
        """
        if path is None:
            path = ask_path(self, title="Select a data1.rda to edit",
                            suffixes=(".rda",), settings=self.ses.settings)
        if not path:
            return
        if self._has_pending() and not messagebox.askyesno(
                "Discard pending edits?",
                f"Opening another archive discards {self._pending_summary()}."
                "\nContinue?"):
            return
        self._close_editors()
        if background:
            # The worker runs the PURE
            # ops.load_archive on frozen inputs — no Session attribute is
            # touched off the Tk thread; install_open (the commit) runs
            # in the done callback, here on the Tk loop.
            same = (self.ses.proj is not None and self.ses.source_path
                    and os.path.normcase(self.ses.source_path)
                    == os.path.normcase(path))
            self._run_bg(f"opening {os.path.basename(path)}…",
                         lambda: ops.load_archive(
                             path, self.ses.store, self.ses.exports_store,
                             self.ses.settings, same,
                             cached_baseline=self.ses.vanilla_baseline,
                             cached_stamp=getattr(self.ses,
                                                  "_vanilla_stamp", None)),
                         lambda loaded: self._opened(
                             path, self.ses.install_open(loaded)),
                         "Open failed")
            return
        self.config(cursor="watch")
        self._set_status(f"opening {os.path.basename(path)}…")
        self.update_idletasks()
        try:
            info = self.ses.open(path)
        except Exception as e:
            _log("open_failed", path=path, error=str(e)[:120])
            self._sync_closed()
            if not quiet:
                messagebox.showerror("Open failed", str(e))
            self._set_status(f"open failed: {e}")
            return
        finally:
            self.config(cursor="")
        self._opened(path, info)

    def _opened(self, path, info):
        """UI refresh after a successful open."""
        # Compact label (file name + md5 + counts); full path + backup
        # state only in the hover tooltip — keeps the save buttons on
        # screen at any window width.
        kind = self._archive_kind(path)
        self._archive_full_path = (
            f"{path}\n{info['files']} files, {info['profiles']} AI profiles, "
            f"md5 {info['source_md5']}\n{info['backup']}")
        self.path_lbl.config(
            text=f"editing: {kind} — {info['profiles']} profiles, "
                 f"md5 {info['source_md5'][:12]}…")
        self._cur_guid = None
        self.dials.clear()
        self.preset_var.set("")
        self.preset_box.config(values=[], state="disabled")
        self.preset_note.config(text="")
        self.char_lbl.config(text="Pick a character on the left")
        self._refresh_roster()
        self.xtab.reload_catalog()
        self.ftab.reload_catalog()
        self._refresh_banners()
        self._set_status(f"opened {kind} — pick a character; select a dial "
                         "and type a new value (Enter to queue)")

    def _archive_kind(self, path):
        """Friendly name of what is open (live / vanilla copy / export)."""
        ap = os.path.normcase(os.path.abspath(path))
        live = self.ses.live_path()
        if live and ap == os.path.normcase(os.path.abspath(live)):
            return "live game file"
        if ap == os.path.normcase(os.path.abspath(
                self.ses.exports_store.vanilla_path)):
            return "vanilla copy"
        base = os.path.basename(path)
        if base.startswith(self.ses.exports_store.PREFIX):
            return f"export '{base[len(self.ses.exports_store.PREFIX):]}'"
        return base

    def open_live_archive(self):
        """Open the game's live data1.rda (from the persisted live path)."""
        live = self.ses.live_path()
        if live is None:
            if not messagebox.askyesno(
                    "No live location set",
                    "The game's live addon/data1.rda location is not "
                    "set yet.\nChoose it now?"):
                return
            self.set_live_location()
            return
        self.open_archive(live)

    def open_vanilla_copy(self):
        """Open the stored data1.rda_vanilla as the editing baseline."""
        if not self.ses.exports_store.has_vanilla_copy():
            self.provide_vanilla()
            return
        self.open_archive(self.ses.exports_store.vanilla_path)

    # ---------------------------------------------------------------- roster

    def _roster_label(self, q):
        # Honest per-character counts from the change plan (a Vanilla
        # click queues every key in scope; only the REAL changes count).
        hc = self.ses.pending_counts()["_by_guid"].get(q.guid, {})
        n = hc.get("dials", 0)
        nrel = hc.get("rels", 0)
        mode = self.ses.modes.get(q.guid)
        parts = []
        if mode and mode not in ("custom", "vanilla"):
            parts.append(mode)
        if n:
            parts.append(f"{n} pending")
        if nrel:
            parts.append(f"{nrel} rel")
        badge = f"  ● {', '.join(parts)}" if parts else ""
        return f"{q.name}  [{q.template} {q.guid}]{badge}"

    def _refresh_roster(self, guids=None):
        """Rewrite roster labels in place, keeping the selection and the
        scroll position (rebuilding the listbox would lose both and
        blank the dial table)."""
        roster = self.ses.roster
        if self.roster.size() != len(roster):
            top = self.roster.yview()[0]
            self.roster.delete(0, "end")
            for q in roster:
                self.roster.insert("end", self._roster_label(q))
            self.roster.yview_moveto(top)
        else:
            for i, q in enumerate(roster):
                if guids is not None and q.guid not in guids:
                    continue
                label = self._roster_label(q)
                if self.roster.get(i) != label:
                    self.roster.delete(i)
                    self.roster.insert(i, label)
        # restore the visible selection to the shown character
        self.roster.selection_clear(0, "end")
        if self._cur_guid is not None:
            for i, q in enumerate(roster):
                if q.guid == self._cur_guid:
                    self.roster.selection_set(i)
                    self.roster.activate(i)
                    break

    def _current_profile(self):
        if self._cur_guid is None or not self.ses.proj:
            return None
        return self.ses.proj.by_guid.get(self._cur_guid)

    def _sel_profile(self):
        """The character currently shown (listbox selection as fallback)."""
        p = self._current_profile()
        if p is not None:
            return p
        sel = self.roster.curselection()
        if not sel or not self.ses.proj:
            return None
        return self.ses.roster[sel[0]]

    # ---------------------------------------------------------------- dials

    def on_select_char(self, _ev=None):
        """Roster selection handler: show the newly selected character."""
        sel = self.roster.curselection()
        if not sel or not self.ses.proj:
            return             # selection cleared: keep showing the current one
        p = self.ses.roster[sel[0]]
        if p.guid == self._cur_guid:
            return
        self._cur_guid = p.guid
        self._show_profile(p, keep_view=False)

    def _show_profile(self, p, keep_view=True):
        """Point the dial table + preset box at character p."""
        if p is None:
            return
        self.char_lbl.config(text=f"{p.name}   ({p.template} · GUID {p.guid})")
        if keep_view:
            self.dials.load(p, None)
        else:
            self.dials.profile = None      # force a fresh view (top, no sel)
            self.dials.load(p, None)
        self._refresh_preset_box(p)

    def _preset_values(self, p):
        vals = ["Vanilla", "Hardened"]
        vals += self.ses.personas_for(p)
        vals.append("Custom")
        return vals

    def _mode_label(self, p):
        # The combobox may DISPLAY 'Unchanged' (a
        # status label), and on_preset maps an unknown combobox string
        # back to the mode via set_mode — see on_preset.
        # 'Unchanged' when the profile has no
        # pending edits (the opened archive may be MODDED — no pending
        # edits does not mean vanilla); 'Vanilla' is reserved for the
        # explicit vanilla MODE
        mode = self.ses.modes.get(p.guid)
        if mode is None:
            return "Unchanged" if not self.ses.changes.get(p.guid) \
                else "Custom"
        if mode == "hardened_rel":
            return "Hardened (relative)"
        if mode == "vanilla_no_ref":
            return "Cleared (no vanilla reference)"
        return mode.capitalize() if mode in ("vanilla", "hardened", "custom") \
            else mode

    def _refresh_preset_box(self, p):
        self.preset_box.config(values=self._preset_values(p),
                               state="disabled" if self._busy_flag
                               else "readonly")
        self.preset_var.set(self._mode_label(p))
        self.preset_box.selection_clear()
        n = len(self.ses.changes.get(p.guid, {}))
        nrel = sum(len(v) for v in self.ses.rels.get(p.guid, {}).values())
        note = f"{n} pending dial edits" if n else "no pending edits"
        if nrel:
            note += f", {nrel} relations"
        mode = self.ses.modes.get(p.guid)
        if mode in self.ses.personas or mode == "hardened":
            preset = self.ses.persona_dials(p, mode) if mode in self.ses.personas \
                else None
            if preset is not None and self.ses.changes.get(p.guid) != preset:
                note += " (preset + your tweaks)"
        self.preset_note.config(text=note)

    def on_preset(self, _ev=None):
        """Preset combo handler: apply the chosen mode/persona via the Session."""
        p = self._sel_profile()
        if p is None:
            return
        mode = self.preset_var.get()
        # 'Unchanged' (no pending edits) is a display state, never a
        # set_mode target.
        if mode == "Unchanged":
            return
        # 'Cleared (no vanilla reference)' is a display state (the
        # vanilla click had no reference to revert to), never a
        # set_mode target
        if mode == "Cleared (no vanilla reference)":
            return
        key = mode.lower() if mode.lower() in ("vanilla", "hardened", "custom") \
            else mode
        self.preset_box.selection_clear()
        self.roster.focus_set()      # keyboard focus back to the roster
        prev = self.ses.modes.get(p.guid)
        if key == prev and key != "vanilla":
            return
        pend = self.ses.changes.get(p.guid, {})
        if key != "custom" and pend and prev in (None, "custom") and \
                not messagebox.askyesno(
                    "Replace your edits?",
                    f"{p.name} has {len(pend)} hand-made pending edits.\n"
                    f"Applying '{mode}' replaces them. Continue?"):
            self.preset_var.set(self._mode_label(p))
            return
        try:
            self.ses.set_mode(p, key)
        except Exception as e:
            messagebox.showerror("Preset failed", str(e))
            self.preset_var.set(self._mode_label(p))
            return
        self.notify_changed(p, None)
        n = len(self.ses.changes.get(p.guid, {}))
        self._set_status(f"{p.name}: preset {mode} — {n} dial edits pending")

    def notify_changed(self, profile, paths=None):
        """Something changed for profile (paths None = many): sync all views.

        Called by the main dial table, every editor window and the preset
        box, so the roster badges, the dial table and open editors always
        agree — without rebuilding anything that loses the user's place.
        """
        guid = profile.guid
        self._refresh_roster(guids={guid})
        if guid == self._cur_guid:
            self.dials.refresh_paths(paths)
            p = self._current_profile()
            if p is not None:
                self._refresh_preset_box(p)
        ed = self._editors.get(guid)
        if ed is not None:
            try:
                if ed.winfo_exists():
                    ed.refresh(paths)
            except tk.TclError:
                self._editors.pop(guid, None)

    # kept for compatibility with older callers

    def _after_tab_change(self):
        """EXTRAS/FERTILITY tab pending-change hook (status summary)."""
        self._set_status(f"pending: {self._pending_summary()}")

    def _refresh_dials(self):
        """Refresh the dial table for the shown character (view kept)."""
        p = self._current_profile()
        if p is None:
            self.dials.clear()
            return
        self.dials.refresh_paths()
        self._refresh_preset_box(p)

    def on_open_editor(self, _ev=None):
        """Roster double-click handler: open (or raise) the editor window."""
        sel = self.roster.curselection()
        if not sel or not self.ses.proj:
            return
        p = self.ses.roster[sel[0]]
        ed = self._editors.get(p.guid)
        if ed is not None:
            try:
                if ed.winfo_exists():
                    ed.deiconify()
                    ed.lift()
                    ed.focus_set()
                    return
            except tk.TclError:
                pass
        try:
            ed = EditorWindow(self, self.ses, p, on_change=self.notify_changed)
        except Exception as e:
            messagebox.showerror("Editor failed", str(e))
            return
        self._editors[p.guid] = ed
        ed.bind("<Destroy>", lambda ev, g=p.guid, w=ed:
                self._editors.pop(g, None) if ev.widget is w else None,
                add="+")

    def _close_editors(self):
        for ed in list(self._editors.values()):
            try:
                ed.destroy()
            except tk.TclError:
                pass
        self._editors.clear()

    def _refresh_all_views(self):
        """After open/flash/restore: every view re-reads the session."""
        self._refresh_roster()
        p = self._current_profile()
        if p is None:
            self._cur_guid = None
            self.dials.clear()
        else:
            self.dials.refresh_paths()
            self._refresh_preset_box(p)
        for ed in list(self._editors.values()):
            try:
                ed.refresh()
            except tk.TclError:
                pass
        if self.ses.proj is not None:
            self.xtab.reload_catalog()
            self.ftab.reload_catalog()

    # ------------------------------------------------------- restore / flash

    def restore_vanilla(self):
        """Copy the stored vanilla over the live game file after confirm."""
        target = self.ses.default_target()
        if target is None:
            messagebox.showinfo(
                "Set live location first",
                "Tell the editor where the game's live addon/data1.rda is "
                "('Set live location…'), then restore.")
            return
        src = self.ses.restore_source_label() or "?"
        in_place = self.ses.source_path is not None and \
            os.path.normcase(target) == os.path.normcase(self.ses.source_path)
        msg = (f"Overwrite\n{target}\nwith the stored vanilla archive?\n\n"
               f"Source: {src}\n\n"
               "Surgical restore: only the editor's own 4 files inside "
               "data1.rda are restored; other mods or game patches in "
               "the live file are KEPT. A snapshot of the current file "
               "is kept first.")
        if in_place and self._has_pending():
            msg += (f"\n\nThat file is open: {self._pending_summary()} will "
                    "be discarded (edits you make while the restore runs "
                    "are kept as pending).")
        if not messagebox.askyesno("Restore vanilla", msg):
            return

        def done(md5):
            self._refresh_all_views()
            self._set_status(f"restored vanilla ({md5[:12]}…) over "
                             f"{self._compact_path(target, 60)}")

        # Pure worker + Tk-thread commit: the worker never touches the
        # Session; apply_restore_result updates the pending state.
        src_path = self.ses.source_path
        # Freeze the pending state on the Tk thread. The in-place restore
        # clears only records equal to this snapshot, so edits queued or
        # re-edited during the restore survive.
        cs_snap = self.ses.cs.snapshot()

        def commit(res):
            done(self.ses.apply_restore_result(res))
            # A surgical restore that degraded to FULL
            # because the live file could not be read back — surface it
            # (untracked members, other mods, may be gone).
            if getattr(res, "degraded_to_full", None):
                messagebox.showwarning(
                    "Restore degraded to full",
                    "Restored vanilla over the live file.\n\n"
                    "WARNING: " + str(res.degraded_to_full) + ".\n\n"
                    "A FULL restore was performed instead of the surgical "
                    "one. If other mods had added members to the file, "
                    "they may be gone — check your pre-restore snapshot "
                    "in the backups store.")
            if getattr(res, "unmodelled", ()):
                messagebox.showwarning(
                    "Restored over another mod's edits",
                    "Restored vanilla over the live file.\n\n"
                    "WARNING: these of the editor's own 4 files carried "
                    "other changes the editor does not model (another "
                    "mod may have edited them), and restore replaced "
                    "them with vanilla:\n  "
                    + "\n  ".join(res.unmodelled)
                    + "\n\nIf you did not expect that, check your "
                    "pre-restore snapshot in the backups store.")

        self._run_bg("restoring vanilla…",
                     lambda: ops.restore_build(
                         self.ses._write_lock, self.ses.store,
                         self.ses.exports_store, target, False, src_path,
                         cs=cs_snap),
                     commit,
                     "Restore failed")

    def _run_build(self, action, export_name):
        """Background build dispatcher: action 'live' flashes, 'export' saves.

        Shared backend for the review dialog's two save choices.
        """
        if not self.ses.proj:
            return
        if action == "live":
            if not self._has_pending():
                messagebox.showinfo("Nothing to apply",
                                    "No pending changes — nothing to build.")
                return
            target = self.ses.default_target()
            if target is None:
                messagebox.showinfo(
                    "Set live location first",
                    "Set the game's live addon/data1.rda location first.")
                return
            # Freeze the pending state on the Tk thread before the worker
            # runs: edits queued during the build are not included, and
            # the subtractive clear afterwards keeps them pending.
            snap = self.ses.cs.snapshot()
            # The worker runs the pure ops.flash_build on frozen inputs;
            # apply_flash_result (subtractive clear + reload) runs in
            # _flash_done on the Tk loop. No Session attribute is touched
            # off-thread. source_md5 is frozen here too, so an in-place
            # commit can refuse if the file changed on disk since it was
            # opened.
            entries = self.ses.proj.entries
            source_path = self.ses.source_path
            src_md5 = self.ses.source_md5
            in_place = (os.path.normcase(target)
                        == os.path.normcase(source_path))
            # The PLAN half of the consent anchor —
            # frozen with the snapshot on the Tk thread. The build
            # recomputes the plan against the SAME base and REFUSES on
            # a hash mismatch: what the user approved in the review
            # is by construction what the build writes (the file half
            # is expected_md5 below).
            build_roster = list(self.ses.roster)
            # The plan is computed against the SAME base the build
            # writes: the LIVE project for not-in-place saves (the
            # rebase replays onto live), the OPENED project for
            # in-place saves (target == opened).
            plan_base = (getattr(getattr(self, "_drift_res", None),
                                 "live", None)
                         if not in_place else self.ses.proj)
            eplan = plan_hash(self.ses.change_plan(plan_base)[0])
            self._run_bg(f"saving to {self._compact_path(target, 50)}… "
                         "(packing the archive can take 30–60 s)",
                         lambda: ops.flash_build(
                             self.ses._write_lock, self.ses.store, entries,
                             source_path,
                             lambda tmp, cs, base, **kw: ops.build_from_snapshot(
                                 base, source_path, cs, tmp, **kw),
                             snap, target, in_place,
                             # The consent anchor — the FILE half
                             # (expected_md5) + the PLAN half
                             # (expected_plan): the md5 of the live blob
                             # the drift/review approved + the hash of
                             # the exact plan the review displayed.
                             # NOT-in-place saves refuse in
                             # commit_archive when live changed between
                             # the review and the save; the build refuses
                             # when the recomputed plan hash differs (the
                             # base changed between review and build).
                             expected_md5=(src_md5 if in_place else
                                           getattr(getattr(
                                               self, "_drift_res", None),
                                               "live_md5", None)),
                             roster=build_roster, expected_plan=eplan,
                             exports_store=self.ses.exports_store),
                         self._flash_done,
                         "Save failed")
        elif action == "export":
            # Build through the export store's own entry point; the GUI
            # never constructs paths inside the (protected) exports store.
            def done(rep):
                name = rep.get("export_name", export_name)
                self._set_status(
                    f"exported {name!r}: {rep['dial_edits']} dial "
                    f"edits, md5 {rep['md5'][:12]}… → data1.rda_{name}")

            # Pure worker + Tk-thread path
            # the export build runs on frozen inputs (the mutator
            # export_named stays for the CLI/tests); a build is a pure
            # op, committing nothing, so no commit callback is needed.
            entries = self.ses.proj.entries
            source_path = self.ses.source_path
            snap = self.ses.cs.snapshot()
            store = self.ses.exports_store
            lock = self.ses._write_lock
            # The PLAN half of the consent anchor: the review's
            # _rebind('export') displayed the plan against the OPENED
            # archive — the build recomputes it against the same base
            # and refuses on a mismatch.
            build_roster = list(self.ses.roster)
            # The plan is computed against the OPENED archive — the
            # base the export build writes (the review's _rebind('export')
            # showed exactly these rows).
            eplan = plan_hash(self.ses.change_plan(self.ses.proj)[0])
            self._run_bg(f"exporting as data1.rda_{export_name}…",
                         lambda: ops.export_named_build(
                             lock, store, entries, source_path,
                             snap, export_name, roster=build_roster,
                             expected_plan=eplan),
                         done, "Export failed")

    def _review_and_save(self):
        """Open the review dialog; dispatch the chosen save action."""
        if not self.ses.proj:
            return
        # Queue the write ledger's cleared keys as revert records before
        # the rows are computed: an edit the user saved earlier and then
        # cleared is reverted by the next save. They are ordinary pending
        # rows: shown in the review, counted in the badges, clearable.
        # Insert-shaped writes cannot be auto-reverted (no delete-leaf
        # operation) and are only reported.
        tgt = self.ses.default_target()
        if tgt:
            try:
                n_rev, unrev = self.ses.apply_ledger_reverts(tgt)
            except Exception:
                n_rev, unrev = 0, []
            if n_rev:
                self._set_status(
                    f"queued {n_rev} revert(s) of edits you cleared "
                    "earlier — they show in the review and save with it")
            if unrev:
                self._set_status(
                    "cannot auto-revert " + ", ".join(unrev)
                    + " (added leaves) — use Restore snapshot instead")
        allow_live = self._has_pending()
        if not allow_live and not messagebox.askyesno(
                "No pending changes",
                "No pending changes — open the review window anyway\n"
                "to save an identical copy as a named export?"):
            return
        # .3 + warn when the LIVE
        # target carries earlier edits this session's baseline doesn't
        # know about — saving would revert them silently. the drift
        # check now covers all four surfaces (dials, relations, extras,
        # fertility) and never counts pending edits as drift. the
        # live archive load runs OFF the Tk thread via _run_bg; the dialog
        # opens in the done callback, on the Tk loop.
        # A fresh review invalidates the previous
        # consent anchor — a stale stash would bind the save to a live
        # version the user never saw.
        self._drift_res = None
        def drift_done(drift):
            # Drift fails CLOSED — a corrupt/locked live file raises
            # DriftUnavailable in the worker, which _run_bg surfaces as
            # "Drift check failed" (the save flow stops and the user
            # is told, instead of silently continuing with no warning).
            # Stash the drift result — its live/live_md5
            # are the CONSENT ANCHOR for the save (the review approved THIS
            # version of the live file; _run_build('live') passes
            # expected_md5=drift.live_md5 for not-in-place saves so the
            # commit refuses when live changed between review and save),
            # and ReviewChangesDialog passes drift.live as the base for
            # the rows ('old' = what the edit ACTUALLY replaces
            # no-op rule rows drop).
            self._drift_res = drift
            if drift:
                n_dial, n_rel, n_extra, n_fert, n_chars, foreign = drift
                # Saving replays your edits onto the live file. Only real
                # conflicts (a live value your pending edit would
                # overwrite) are lost; every other live difference is kept.
                parts = []
                examples = []
                blocking = []
                if n_dial:
                    parts.append(f"{n_dial} dial values")
                    examples += list(getattr(drift, "dial_keys", ()))
                if n_rel:
                    parts.append(f"{n_rel} relations lists")
                    examples += list(getattr(drift, "rel_keys", ()))
                if n_extra:
                    # EXTRAS conflicts are blocking: the replay guard
                    # refuses these edits at build time, so offering
                    # "Continue anyway?" would be a dead end. Dials and
                    # relations overwrite after consent; EXTRAS conflicts
                    # are resolved by opening the live file instead.
                    blocking.append(f"{n_extra} extras leaves")
                    examples += list(getattr(drift, "extra_keys", ()))
                if n_fert:
                    parts.append(f"{n_fert} fertility rates")
                    examples += list(getattr(drift, "fert_keys", ()))
                if blocking:
                    # live_path is a method; call it.
                    live_path = (self.ses.live_path() or
                                 self.ses.default_target() or
                                 "(the live file)")
                    msg = ("Some EXTRAS values in the LIVE file differ "
                           "from what you opened AND from your pending "
                           "edits — saving would overwrite a live "
                           "value the replay guard cannot verify (its "
                           "old-value record was made against the OPENED "
                           f"file).\n\nTo keep those live changes, open "
                           f"the LIVE file instead:\n  {live_path}\n\n"
                           f"Blocked: {' + '.join(blocking)}.\n")
                    if examples:
                        msg += ("\nFor example:\n  "
                                + "\n  ".join(examples[:8]))
                    messagebox.showwarning(
                            "EXTRAS conflicts must be resolved first", msg)
                    return
                # The conflict preamble makes sense
                # only when there ARE conflicts (parts non-empty) — a
                # kept-only or unmodelled-only result gets its own
                # message below instead of a confusing empty preamble.
                if parts:
                    msg = ("Some live values differ from what you opened "
                           "AND from your pending edits — saving will "
                           "OVERWRITE those live values "
                           f"({' + '.join(parts)} across {n_chars} "
                           "characters).\n\n"
                           "Everything else in the live file (other changes "
                           "you are not editing) is KEPT.\nContinue anyway?")
                    if examples:
                        msg += ("\n\nFor example:\n  "
                                + "\n  ".join(examples[:8]))
                    if not messagebox.askyesno(
                            "Live file has other changes", msg):
                        return
                else:
                    msg = ("The live file differs from what you opened, "
                           "but NONE of your pending edits overwrite a "
                           "live value.")
                kept = []
                if getattr(drift, "kept_dials", 0):
                    kept.append(f"{drift.kept_dials} dial values")
                if getattr(drift, "kept_relations", 0):
                    kept.append(f"{drift.kept_relations} relations lists")
                if getattr(drift, "kept_extras", 0):
                    kept.append(f"{drift.kept_extras} extras leaves")
                if getattr(drift, "kept_fert", 0):
                    kept.append(f"{drift.kept_fert} fertility rates")
                # Mine, now cleared (from the write ledger): edits this
                # tool wrote earlier that the user has since cleared. The
                # save reverts them to the values they replaced; the
                # review shows those rows.
                cleared = []
                if getattr(drift, "mine_cleared_dials", 0):
                    cleared.append(
                        f"{drift.mine_cleared_dials} dial values")
                if getattr(drift, "mine_cleared_relations", 0):
                    cleared.append(
                        f"{drift.mine_cleared_relations} relations lists")
                if getattr(drift, "mine_cleared_extras", 0):
                    cleared.append(
                        f"{drift.mine_cleared_extras} extras leaves")
                if getattr(drift, "mine_cleared_fert", 0):
                    cleared.append(
                        f"{drift.mine_cleared_fert} fertility rates")
                if cleared:
                    msg += ("\nThe live file carries "
                            f"{', '.join(cleared)} YOU saved earlier and "
                            "then cleared — this save REVERTS them to "
                            "their earlier values (shown in the review).")
                if kept:
                    msg += (f"\n\nThe live file also carries earlier "
                            f"changes you are NOT editing ({', '.join(kept)}) "
                            "— those are KEPT when you save.")
                if getattr(drift, "unmodelled", ()):
                    msg += ("\n\nWARNING: the live copies of some of the "
                            "editor's own 4 files differ in ways this "
                            "editor does not model (another mod may have "
                            "edited them): "
                            + ", ".join(drift.unmodelled)
                            + ". Saving KEEPS those differences (your edit is "
                            "replayed on top of the live text) — but review "
                            "them if you did not expect that.")
                if foreign:
                    msg += (f"\n\nThe live file also carries {foreign} "
                            "other file(s) this editor does not track "
                            "(another mod / a game patch) — those are "
                            "KEPT (saving only replaces the editor's own "
                            "files in your live data1.rda).")
                if parts:
                    return   # the conflict askyesno already ran above
                if not messagebox.askyesno(
                        "Live file has other changes", msg):
                    return
            # The review rows come from the BASE the
            # save will actually write — the LIVE project from the stashed
            # drift result (fallback: the opened project; CLI-equivalent
            # dry-run shape when drift never ran).
            base = getattr(getattr(self, "_drift_res", None), "live", None)
            if base is None:
                base = self.ses.proj
            dlg = ReviewChangesDialog(self, self, on_save=self._run_build,
                                      allow_live=allow_live, base=base)
            return dlg

        # Inputs are frozen here on the Tk thread; the pure
        # ops.drift_check runs in the worker, so the worker never reads
        # state this thread may be editing.
        frozen = self.ses.freeze_drift_inputs()
        if frozen is None:
            drift_done(None)
            return
        self._run_bg("checking the live file for earlier changes…",
                     lambda: ops.drift_check(*frozen, store=self.ses.store),
                     drift_done, "Drift check failed")

    def flash(self):
        """Review all pending changes, then save (live or export) in background."""
        self._review_and_save()

    def export(self):
        """Review all pending changes, then save as a named export."""
        self._review_and_save()

    def _flash_done(self, res):
        # Stale-result guard: the save was dispatched with a frozen
        # source_path; if the user opened a DIFFERENT archive while the
        # build ran (single-flight should have prevented it, but a
        # reload/open can land between dispatch and done), applying the
        # flash result would swap proj back to the OLD archive. Ignore
        # the reload; the file on disk WAS written, only the in-memory
        # refresh is dropped (the user re-opens to see it).
        if res.source_path is not None and self.ses.proj is not None and \
                os.path.normcase(res.source_path) != os.path.normcase(
                    self.ses.source_path):
            self._set_status(
                f"saved {res.report['flashed']} — a different archive "
                "was opened meanwhile; reopen it to see the result")
            messagebox.showinfo(
                "Saved",
                f"Wrote {res.report['flashed']}\n"
                "(a different archive was opened while the save ran — "
                "the window still shows the archive you opened last; "
                "reopen the saved file to see the result)")
            return
        # The Tk-thread commit — subtractive clear of the
        # flashed snapshot, in-place reload (apply_flash_result).
        rep = self.ses.apply_flash_result(res)
        self._refresh_all_views()
        where = rep["flashed"]
        self._set_status(f"saved to {self._compact_path(where, 60)} — "
                         f"{rep['dial_edits']} dial edits, md5 "
                         f"{rep['md5'][:12]}…")
        extra = ("" if rep.get("in_place") else
                 "\nYour edits stay pending here, so you can keep tweaking "
                 "and save again.")
        messagebox.showinfo(
            "Saved",
            f"Wrote {where}\n"
            f"{rep['dial_edits']} dial edits · "
            f"{rep.get('relations_edits', 0)} relations · "
            f"{rep.get('extras_edits', 0)} extras · "
            f"{rep.get('fert_edits', 0)} fertility\n"
            f"md5: {rep['md5']}\n"
            "Round-trip verified.\n" +
            ("A pre-save snapshot of the previous file was kept.\n"
             if rep.get("snapshot_written") else
             "No new snapshot was needed (the previous file is already "
             "preserved in the editor's backups).\n") +
            "\nStart a NEW endless game to see the changes." + extra)

    def open_export_manager(self):
        """Open the saved data1.rda manager dialog."""
        try:
            ExportManagerDialog(self, self)
        except Exception as e:
            messagebox.showerror("Export manager failed", str(e))

    def view_log(self):
        """Show the last 60 log lines in a scrollable read-only window."""
        from ..applog import log_path
        win = tk.Toplevel(self)
        win.title("Anno1404 GameEditor — activity log")
        win.geometry("820x420")
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=6, pady=6)
        txt = tk.Text(body, wrap="none", state="disabled")
        ys = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        ttk.Label(win, text=f"log file: {log_path()}", anchor="w").pack(
            fill="x", padx=6)
        lines = log_tail(60)
        txt.config(state="normal")
        txt.insert("1.0", "\n".join(lines) or "(no log entries yet)")
        txt.config(state="disabled")
        txt.see("end")


def main():
    """Entry point: python3 -m annoedit.gui.app"""
    startup_note()
    App().mainloop()


if __name__ == "__main__":
    main()
