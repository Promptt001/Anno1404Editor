#!/usr/bin/env python3
"""annoedit.gui.editor — per-character editor window.

A Toplevel opened by double-clicking a roster entry in the main window.
Thin layer: all state changes go through the shared Session (and thus its
pending-changes dict), so this window is disposable — closing it never
loses edits. The main window and every open editor stay in sync through
the on_change callback (App.notify_changed) and refresh().

Layout:
  left:   category list (Build / Military / ShipFight / ... with dial
          counts and pending badges)
  right:  the shared DialTable (value | vanilla | new | source, find box,
          edit bar, schema doc)
  bottom: Save / Load preset, Relations…, Reset to vanilla
"""
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..session import SessionError
from ..changeset import ChangeSetError
from .widgets import DialTable, grab_when_mapped



class EditorWindow(tk.Toplevel):
    """Per-character editor window: category list plus inline dial editing."""

    def __init__(self, parent, ses, profile, on_change=None):
        super().__init__(parent)
        self.ses = ses
        self.profile = profile
        self.on_change = on_change   # callback(profile, paths) -> main window
        self._cat_sel = None         # None = ALL
        self.title(f"Editor — {profile.name} ({profile.template} {profile.guid})")
        self.geometry("1040x660")
        self.minsize(760, 460)
        self._build_widgets()
        self.refresh()
        self.bind("<Escape>", lambda _e: self.destroy())

    # ---------------------------------------------------------------- UI

    def _build_widgets(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(top, text=f"{self.profile.name}",
                  font=("TkDefaultFont", 12, "bold")).pack(side="left")
        ttk.Label(top, text=f"  {self.profile.template} · GUID "
                            f"{self.profile.guid}").pack(side="left")
        self.badge = ttk.Label(top, text="")
        self.badge.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=6)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", pady=4)
        ttk.Label(left, text="Categories").pack(anchor="w")
        # A plain Listbox: selecting never re-triggers itself (a Treeview
        # that re-selects inside its own select handler fires
        # <<TreeviewSelect>> again and loops).
        self.cat = tk.Listbox(left, width=26, exportselection=False,
                              activestyle="none")
        self.cat.pack(fill="y", expand=True)
        self.cat.bind("<<ListboxSelect>>", self._on_cat)
        self._cat_keys = []

        self.table = DialTable(body, self.ses, show_category=False,
                               on_change=self._table_changed,
                               on_status=self._status)
        self.table.pack(side="left", fill="both", expand=True, padx=(8, 0),
                        pady=4)
        self.tree = self.table.tree       # compat (tests / callers)
        self.doc = self.table.doc

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=8, pady=4)
        ttk.Button(bottom, text="Save preset…",
                   command=self.save_preset).pack(side="left")
        ttk.Button(bottom, text="Load preset…",
                   command=self.load_preset).pack(side="left", padx=4)
        ttk.Button(bottom, text="Relations…",
                   command=self.edit_relations).pack(side="left", padx=4)
        ttk.Button(bottom, text="Reset to vanilla",
                   command=self.clear_pending).pack(side="right")
        self.status = ttk.Label(self, text="", anchor="w")
        self.status.pack(fill="x", padx=8, pady=(0, 4))

    # ---------------------------------------------------------------- data

    def _status(self, text):
        self.status.config(text=text)

    def _dial_paths(self):
        # The category counts must match the
        # table's rows — the table unions the SCHEMA paths too
        # (ses.proj.defaults, per-category via defaults_by_cat), so the
        # counts use the same union, not just dials + pending
        p = self.profile
        pend = self.ses.changes.get(p.guid, {})
        return sorted(set(p.dials) | set(pend) | set(self.ses.proj.defaults))

    def _refresh_categories(self):
        """Rebuild the category labels in place, keeping the selection."""
        pend = self.ses.changes.get(self.profile.guid, {})
        paths = self._dial_paths()
        counts = {}
        for path in paths:
            c = path.split("/")[0]
            counts[c] = counts.get(c, 0) + 1
        keys = [None] + sorted(counts)
        labels = [f"ALL ({len(paths)})" + (f"   • {len(pend)}" if pend else "")]
        for c in keys[1:]:
            npend = sum(1 for path in pend if path.split("/")[0] == c)
            labels.append(f"{c} ({counts[c]})" + (f"   • {npend}" if npend else ""))
        if self._cat_sel not in keys:
            self._cat_sel = None
        self._cat_keys = keys
        self.cat.delete(0, "end")
        for lab in labels:
            self.cat.insert("end", lab)
        idx = keys.index(self._cat_sel)
        self.cat.selection_set(idx)
        self.cat.see(idx)

    def _on_cat(self, _ev=None):
        sel = self.cat.curselection()
        if not sel:
            return
        key = self._cat_keys[sel[0]]
        if key == self._cat_sel and self.table.profile is not None:
            return
        self._cat_sel = key
        self.table.load(self.profile, key)

    def _selected_cat(self):
        return self._cat_sel

    def refresh(self, paths=None):
        """Re-read the session (after any change, from here or elsewhere)."""
        fresh = self.ses.proj.by_guid.get(self.profile.guid) \
            if self.ses.proj else None
        if fresh is None:            # archive closed / re-opened elsewhere
            self.destroy()
            return
        self.profile = fresh
        self._refresh_categories()
        if self.table.profile is None:
            self.table.load(self.profile, self._cat_sel)
        else:
            self.table.refresh_paths(paths)
        n = len(self.ses.changes.get(self.profile.guid, {}))
        nrel = sum(len(v) for v in self.ses.rels.get(self.profile.guid, {}).values())
        mode = self.ses.modes.get(self.profile.guid)
        bits = [f"{n} pending dial edits"]
        if nrel:
            bits.append(f"{nrel} relations")
        if mode and mode != "custom":
            bits.append(f"preset: {mode}")
        self.badge.config(text=" · ".join(bits))

    # backwards-compatible name
    def _refresh(self, _ev=None):
        self.refresh()

    def _table_changed(self, profile, paths):
        self.refresh(paths)
        if self.on_change:
            self.on_change(profile, paths)

    def _changed_all(self):
        """A bulk change (preset / reset / relations): refresh + notify."""
        self.refresh()
        if self.on_change:
            self.on_change(self.profile, None)

    def clear_pending(self):
        """Drop all pending edits for this character (set_mode vanilla)."""
        pend = self.ses.changes.get(self.profile.guid, {})
        rels = self.ses.rels.get(self.profile.guid, {})
        # Say what will ACTUALLY happen — with a stored
        # vanilla copy, set_mode(vanilla) queues edits that bring every
        # dial BACK to its vanilla value (a visible, revertible change
        # set); without one it just drops the pending edits.
        has_base = self.ses.vanilla_baseline is not None \
            and self.ses.vanilla_baseline.by_guid.get(self.profile.guid)
        if has_base:
            # Honest counts from the change plan — how many REAL
            # changes the reset would queue (no-op rule rows are not
            # changes; the raw record count showed every key in scope).
            try:
                hc = self.ses.pending_counts()["_by_guid"].get(
                    self.profile.guid, {})
                n_real = hc.get("dials", 0) + hc.get("rels", 0)
            except Exception:
                n_real = len(pend) + sum(len(v) for v in rels.values())
            msg = (f"Queue edits that set every dial of "
                   f"{self.profile.name} to its stored VANILLA value? "
                   f"({n_real} real change(s) — no-op edits drop out at "
                   "review time; your current pending edits are replaced — "
                   "visible in the review window, revertible)")
        else:
            msg = (f"Drop all {len(pend)} pending dial edits"
                   + (" and relations edits" if rels else "")
                   + f" for {self.profile.name}? (no vanilla copy stored — "
                   "edits are simply cleared)")
        # Always confirm: the Vanilla click queues a reset for every key
        # in scope, replacing whatever is pending. A no-op reset (nothing
        # pending and nothing would change) is still reported below.
        if not messagebox.askyesno(
                "Reset to vanilla", msg, parent=self):
            return
        # The old call had NO try/except — a
        # SessionError (broken datasets.xml, bad reference) escaped to the
        # Tk callback and the click silently did nothing.
        try:
            self.ses.set_mode(self.profile, "vanilla")
        except (SessionError, ChangeSetError) as exc:
            messagebox.showerror(
                "Reset to vanilla", f"Could not reset {self.profile.name} "
                f"to vanilla:\n\n{exc}", parent=self)
            return
        # Leaves the opened (modded) archive ADDED
        # that vanilla lacks with no schema default cannot be reverted
        # by a value edit — say so instead of silently leaving them.
        unrev = getattr(self.ses, "_last_unrevertable", [])
        if unrev:
            messagebox.showwarning(
                "Not fully revertible",
                f"Queued vanilla reverts for {self.profile.name}.\n\n"
                f"{len(unrev)} dial(s) this archive ADDED (absent from "
                "vanilla, no schema default) cannot be removed by a "
                "value edit — the engine has no delete-leaf operation. "
                "They stay as they are:\n  "
                + "\n  ".join(unrev[:10])
                + ("\n  …" if len(unrev) > 10 else ""),
                parent=self)
        # 'Pending edits cleared' described pre-2.17; now they are
        # queued as resets (dropping out only at review/build time).
        self._status("reset to vanilla — vanilla values queued as pending edits"
                     + (f" ({len(unrev)} un-revertable dials left)" if unrev else ""))
        self._changed_all()

    # ---------------------------------------------------------------- relations

    def edit_relations(self):
        """Open the Relations dialog (War/Ally/Trade/AvoidWar list editing)."""
        RelationsDialog(self, self.ses, self.profile,
                        on_change=self._changed_all)

    # ---------------------------------------------------------------- presets

    def save_preset(self):
        """Prompt for a name and save this character's pending edits as a preset."""
        pend = self.ses.changes.get(self.profile.guid, {})
        # Relations-only edits can be saved as a preset too.
        if not pend and not self.ses.rels.get(self.profile.guid):
            messagebox.showinfo("Nothing to save",
                                "No pending edits for this character.",
                                parent=self)
            return
        name = simpledialog.askstring(
            "Save preset", "Preset name:", parent=self)
        if not name or not name.strip():
            return
        try:
            path = self.ses.save_named_preset(self.profile, name.strip())
        except SessionError as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        self._status(f"preset saved: {path}")

    def load_preset(self):
        """Pick a saved preset or persona from a list and apply it to this character."""
        presets = self.ses.named_presets()
        personas = self.ses.personas_for(self.profile)
        if not presets and not personas:
            messagebox.showinfo(
                "No presets",
                "No saved presets yet (and no persona fits this "
                "character). Save one first.", parent=self)
            return
        names = [f"[persona] {p}" for p in personas] + sorted(presets)
        pick = _pick_from_list(self, "Load preset", names)
        if not pick:
            return
        try:
            if pick.startswith("[persona] "):
                dials = self.ses.set_mode(self.profile,
                                          pick[len("[persona] "):])
            else:
                dials = self.ses.load_named_preset(self.profile, pick)
        except SessionError as e:
            messagebox.showerror("Load failed", str(e), parent=self)
            return
        self._status(f"loaded: {pick} ({len(dials)} dials)")
        self._changed_all()


class RelationsDialog(tk.Toplevel):
    """Modal War/Ally/Trade/AvoidWar list editor for one character.

    Shows the four kind lists (pending if queued, else current) with the
    other characters' names; every change is committed immediately through
    Session.set_relations (validated + dry-run before acceptance), so
    closing the dialog never loses or half-applies anything.
    """

    KINDS = ("War", "Ally", "Trade", "AvoidWar")

    def __init__(self, parent, ses, profile, on_change=None):
        super().__init__(parent)
        self.ses = ses
        self.profile = profile
        self.on_change = on_change
        self.title(f"Relations — {profile.name} ({profile.guid})")
        self.geometry("560x420")
        self.transient(parent)
        self._build_widgets()
        self._refresh()
        self.bind("<Escape>", lambda _e: self.destroy())
        grab_when_mapped(self)

    def _build_widgets(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text=(f"{self.profile.name} — each list REPLACES the "
                             f"character's vanilla list (absent = untouched)")
                  ).pack(side="left")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=6, pady=4)
        self.lists = {}
        for kind in self.KINDS:
            row = ttk.Frame(self.body)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=kind, width=10).pack(side="left")
            lb = tk.Listbox(row, height=4, exportselection=False)
            lb.pack(side="left", fill="x", expand=True)
            btns = ttk.Frame(row)
            btns.pack(side="left", padx=4)
            ttk.Button(btns, text="+", width=3,
                       command=lambda k=kind: self._add(k)).pack(side="top")
            ttk.Button(btns, text="−", width=3,
                       command=lambda k=kind: self._remove(k)).pack(side="top")
            ttk.Button(btns, text="clear", width=6,
                       command=lambda k=kind: self._clear_kind(k)).pack(side="top")
            self.lists[kind] = lb
        bot = ttk.Frame(self)
        bot.pack(fill="x", padx=6, pady=4)
        ttk.Button(bot, text="Reset (drop pending)",
                   command=self._reset).pack(side="right")
        self.status = ttk.Label(self, text="", anchor="w")
        self.status.pack(fill="x", padx=6)

    def _names(self):
        return [q for q in self.ses.roster if q.guid != self.profile.guid]

    def _kind_names(self, kind):
        guids = self.ses.relations_row(self.profile, kind)
        by_guid = {q.guid: q for q in self.ses.roster}
        return [f"{by_guid[g].name} ({g})" if g in by_guid else f"{g} (?)"
                for g in guids]

    def _refresh(self):
        for kind in self.KINDS:
            lb = self.lists[kind]
            lb.delete(0, "end")
            for n in self._kind_names(kind):
                lb.insert("end", n)
        nrel = len(self.ses.rels.get(self.profile.guid, {}))
        self.status.config(text=f"{nrel} kind(s) with pending edits")

    def _guid_of(self, shown):
        return shown.rsplit("(", 1)[1].rstrip(")")

    def _add(self, kind):
        current = set(self.ses.relations_row(self.profile, kind))
        candidates = [q for q in self._names()
                      if q.guid not in current]
        if not candidates:
            messagebox.showinfo("Nothing to add", "Every other character is "
                                "already on this list.", parent=self)
            return
        pick = _pick_from_list(self, f"Add to {kind}",
                               [f"{q.name} ({q.guid})" for q in candidates])
        if not pick:
            return
        try:
            self.ses.set_relations(self.profile, **{kind.lower():
                               self.ses.relations_row(self.profile, kind) +
                               [self._guid_of(pick)]})
        except SessionError as e:
            messagebox.showerror("Relations refused", str(e), parent=self)
            return
        self.status.config(text=f"{kind}: added {pick}")
        self._refresh()
        if self.on_change:
            self.on_change()

    def _remove(self, kind):
        lb = self.lists[kind]
        sel = lb.curselection()
        if not sel:
            return
        shown = lb.get(sel[0])
        guid = self._guid_of(shown)
        try:
            self.ses.set_relations(self.profile, **{kind.lower():
                   [g for g in self.ses.relations_row(self.profile, kind)
                    if g != guid]})
        except SessionError as e:
            messagebox.showerror("Relations refused", str(e), parent=self)
            return
        self.status.config(text=f"{kind}: removed {shown}")
        self._refresh()
        if self.on_change:
            self.on_change()

    def _clear_kind(self, kind):
        try:
            self.ses.set_relations(self.profile, **{kind.lower(): []})
        except SessionError as e:
            messagebox.showerror("Relations refused", str(e), parent=self)
            return
        self.status.config(text=f"{kind}: cleared (empty list kept)")
        self._refresh()
        if self.on_change:
            self.on_change()

    def _reset(self):
        self.ses.clear_relations(self.profile)
        self.status.config(text="pending relations edits dropped")
        self._refresh()
        if self.on_change:
            self.on_change()


def _pick_from_list(parent, title, names):
    """Minimal modal picker (no extra dependency). -> chosen name or None."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    ttk.Label(win, text="Choose (double-click or Enter):").pack(
        anchor="w", padx=10, pady=(8, 4))
    lb = tk.Listbox(win, height=min(14, max(4, len(names))), width=48,
                    exportselection=False)
    lb.pack(fill="both", expand=True, padx=10)
    for n in names:
        lb.insert("end", n)
    if names:
        lb.selection_set(0)
        lb.activate(0)
    out = {"v": None}

    def ok(_ev=None):
        """Modal picker confirm handler: record the chosen name and close."""
        sel = lb.curselection()
        if sel:
            out["v"] = names[sel[0]]
        win.destroy()

    lb.bind("<Double-1>", ok)
    lb.bind("<Return>", ok)
    win.bind("<Escape>", lambda _e: win.destroy())
    btns = ttk.Frame(win)
    btns.pack(fill="x", padx=10, pady=8)
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
    ttk.Button(btns, text="OK", command=ok).pack(side="right", padx=4)
    grab_when_mapped(win)
    lb.focus_set()
    win.wait_window()
    return out["v"]
