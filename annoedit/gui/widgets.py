#!/usr/bin/env python3
"""annoedit.gui.widgets — the shared dial table (main window + editor).

One widget, used by both the main window's AI tab and the per-character
editor window, so editing behaves identically everywhere:

  * rows are keyed by dial path; an edit updates ONLY the affected rows
    in place, so selection, scroll position and the chosen character are
    never lost;
  * an edit bar under the table: select a row -> its pending value is
    shown; type and press Enter (or 'Set') to queue, 'Reset dial' drops
    the pending edit, Esc reverts. Double-click / Enter on a row jumps
    into the entry. The value is always committed to the row it was
    loaded for — never to whichever row happens to be selected when
    focus leaves the entry;
  * rows with a pending edit are highlighted; a filter box narrows the
    ~980 dials by name;
  * the developers' dial documentation for the selected row below.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from ..model import schema_doc  # Full-path doc lookup
from ..session import SessionError

PENDING_BG = "#fff3c4"      # a queued edit (yellow)
NONVANILLA_BG = "#fde0dc"  # current value differs from vanilla (red)


# Sort_key is pure logic and now lives in .logic (no
# tkinter import) so headless/tk-less test imports work; re-exported here
# for existing callers.
from .logic import sort_key  # noqa: (re-export)
from .logic import differs_from_vanilla  # noqa: (re-export)


def to_num(x):
    """float(x) or None (non-numeric / missing)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def out_of_range(raw, doc):
    """True when raw is numeric and outside the schema's min..max."""
    num = to_num(raw)
    if num is None:
        return False
    lo, hi = to_num(doc.get("min")), to_num(doc.get("max"))
    return (lo is not None and num < lo) or (hi is not None and num > hi)


def grab_when_mapped(win, tries=40):
    """Make win modal once it is actually on screen.

    Never call wait_visibility() from an idle callback: the window's own
    map happens in an idle handler too, so the nested wait blocks it and
    the dialog never appears. Poll with after() instead.
    """
    try:
        if not win.winfo_exists():
            return
        if win.winfo_ismapped():
            win.grab_set()
            return
    except tk.TclError:
        pass
    if tries > 0:
        win.after(30, lambda: grab_when_mapped(win, tries - 1))


class DialTable(ttk.Frame):
    """Dial table + filter + edit bar + doc pane for one character."""

    def __init__(self, parent, ses, show_category=True, on_change=None,
                 on_status=None):
        super().__init__(parent)
        self.ses = ses
        self.show_category = show_category
        self.on_change = on_change    # callback(profile, [paths])
        self.on_status = on_status    # callback(text)
        self.profile = None
        self.category = None          # None = all categories
        self._editing_path = None
        self._loaded_value = ""
        self._committing = False      # suppress focus-out while a dialog is up
        self._sort_col = None        # click-to-sort heading state
        self._sort_desc = False
        self._build()

    # ------------------------------------------------------------ layout

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 2))
        ttk.Label(bar, text="Find dial:").pack(side="left")
        self.filter_var = tk.StringVar()
        fent = ttk.Entry(bar, textvariable=self.filter_var, width=24)
        fent.pack(side="left", padx=4)
        self.filter_var.trace_add("write", lambda *_a: self.reload())
        self.pending_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Pending only", variable=self.pending_only,
                        command=self.reload).pack(side="left", padx=6)
        # Filter for rows whose current value differs from the vanilla
        # reference (pending edits not required).
        self.nonvanilla_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Non-vanilla only",
                        variable=self.nonvanilla_only,
                        command=self.reload).pack(side="left", padx=6)
        self.count_lbl = ttk.Label(bar, text="")
        self.count_lbl.pack(side="right")

        # Table + scrollbar side by side (grid layout).
        tf = ttk.Frame(self)
        tf.pack(fill="both", expand=True)
        cols = (("category",) if self.show_category else ()) + \
            ("dial", "value", "vanilla", "new", "source")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings",
                                 height=18, selectmode="browse")
        widths = {"category": 90, "dial": 320, "value": 70, "vanilla": 70,
                  "new": 80, "source": 64}
        heads = {"category": "Category", "dial": "Dial", "value": "Value",
                 "vanilla": "Vanilla", "new": "New value", "source": "Source"}
        self._cols = cols            # sortable headings
        self._heads = heads
        for c in cols:
            self.tree.heading(c, text=heads[c],
                              command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=widths[c], anchor="w",
                             stretch=(c == "dial"))
        vs = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        self.tree.tag_configure("pending", background=PENDING_BG)
        # non-vanilla rows stand out: red background + bold dial text
        self.tree.tag_configure("nonvanilla", background=NONVANILLA_BG)
        try:
            import tkinter.font as tkfont
            f = tkfont.nametofont("TkDefaultFont")
            self.tree.tag_configure(
                "nonvanilla",
                font=(f.actual("family"), f.actual("size"), "bold"))
        except tk.TclError:
            pass  # font lookup can fail on exotic platforms — bg still applies
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._focus_entry)
        self.tree.bind("<Return>", self._focus_entry)

        # edit bar
        eb = ttk.Frame(self)
        eb.pack(fill="x", pady=(4, 0))
        self.edit_lbl = ttk.Label(eb, text="Select a dial to edit", width=34,
                                  anchor="w")
        self.edit_lbl.pack(side="left")
        ttk.Label(eb, text="New value:").pack(side="left", padx=(6, 2))
        self.entry = ttk.Entry(eb, width=14, state="disabled")
        self.entry.pack(side="left")
        self.entry.bind("<Return>", self._commit)
        self.entry.bind("<KP_Enter>", self._commit)
        self.entry.bind("<Escape>", self._revert)
        self.entry.bind("<FocusOut>", self._on_entry_focus_out)
        self.set_btn = ttk.Button(eb, text="Set", width=6, state="disabled",
                                  command=self._commit)
        self.set_btn.pack(side="left", padx=(4, 0))
        self.reset_btn = ttk.Button(eb, text="Reset dial", state="disabled",
                                    command=self._reset_dial)
        self.reset_btn.pack(side="left", padx=4)
        self.range_lbl = ttk.Label(eb, text="", foreground="#666")
        self.range_lbl.pack(side="left", padx=6)

        self.doc = tk.Text(self, height=5, wrap="word", state="disabled",
                           bg="#f4f4f4", relief="flat")
        self.doc.pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------ data

    def _paths(self):
        p = self.profile
        if p is None or not self.ses.proj:
            return []
        pend = self.ses.changes.get(p.guid, {})
        # The table shows the profile's dials ∪ the
        # PENDING edits ∪ the SCHEMA's dial paths for the category — the
        # schema's default-valued dials become visible and EDITABLE (the
        # engine inserts missing leaves on edit); the source column keeps
        # profile/"(schema)" distinct.
        schema_paths = set()
        if self.category and self.category in self.ses.proj.defaults_by_cat():
            schema_paths = set(self.ses.proj.defaults_by_cat()[self.category])
        elif not self.category:
            schema_paths = set(self.ses.proj.defaults)
        # NOTE: default view order stays alphabetical (sorted() below); an
        # ACTIVE heading sort reorders via _sorted() at insert time
        paths = sorted(set(p.dials) | set(pend) | schema_paths)
        if self.category:
            paths = [x for x in paths if x.split("/")[0] == self.category]
        filt = self.filter_var.get().strip().lower()
        if filt:
            paths = [x for x in paths if filt in x.lower()]
        if self.pending_only.get():
            paths = [x for x in paths if x in pend]
        if self.nonvanilla_only.get():
            # non-vanilla = the CURRENT (opened archive) value differs
            # from the vanilla REFERENCE (a stored vanilla copy — without
            # one every row classifies False and the filter shows nothing)
            paths = [x for x in paths
                     if self._is_nonvanilla(x)]
        return paths

    def _is_nonvanilla(self, path):
        """True when the row's current value differs from the vanilla
        reference (the classifier is pure logic in .logic)."""
        if self.profile is None or not self.ses.proj:
            return False
        row = self.ses.dial_row(self.profile, path)
        return differs_from_vanilla(row["value"], row["vanilla"])

    def _row_values(self, path):
        row = self.ses.dial_row(self.profile, path)
        van = row.get("vanilla")
        vals = (path,
                row["value"] if row["value"] is not None else "",
                van if van is not None else "—",
                row["pending"] if row["pending"] is not None else "",
                row["source"])
        if self.show_category:
            vals = (path.split("/")[0],) + vals
        tags = ()
        if row["pending"] is not None:
            tags = tags + ("pending",)
        # Non-vanilla highlight: a row whose current value differs from
        # the vanilla reference. Pending wins
        # the background when both apply (a pending edit on a non-vanilla
        # row keeps the pending-yellow; the tag list records both).
        if differs_from_vanilla(row["value"], row["vanilla"]):
            tags = tags + ("nonvanilla",)
        return vals, tags

    def load(self, profile, category=None):
        """Show profile's dials (optionally one category).

        Same profile + category = in-place refresh that keeps selection
        and scroll; a different one starts at the top.
        """
        same = (self.profile is not None and profile is not None
                and profile.guid == self.profile.guid
                and category == self.category)
        self.profile = profile
        self.category = category
        self.reload(keep_view=same)

    def reload(self, keep_view=True):
        """Rebuild all rows (keeping selection + scroll when keep_view)."""
        sel = self.tree.selection()
        sel = sel[0] if sel else None
        top = self.tree.yview()[0] if keep_view else 0.0
        self.tree.delete(*self.tree.get_children())
        paths = self._sorted(self._paths())
        for path in paths:
            vals, tags = self._row_values(path)
            self.tree.insert("", "end", iid=path, values=vals, tags=tags)
        self._update_count(len(paths))
        if keep_view and sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
            self.tree.focus(sel)
        else:
            self._clear_editor()
        self.tree.yview_moveto(top)

    def refresh_paths(self, paths=None):
        """Update rows for paths in place (None = every visible row).

        If the set of rows changed (a persona inserted dials the profile
        did not carry), falls back to a view-preserving full reload.
        """
        if self.profile is None:
            return
        # the session may have reloaded the project (flash/restore): pick
        # up the fresh Profile object for the same character
        if self.ses.proj is not None:
            fresh = self.ses.proj.by_guid.get(self.profile.guid)
            if fresh is not None:
                self.profile = fresh
        wanted = self._sorted(self._paths())
        if list(self.tree.get_children()) != wanted:
            self.reload(keep_view=True)
            return
        for path in (wanted if paths is None else paths):
            if self.tree.exists(path):
                vals, tags = self._row_values(path)
                self.tree.item(path, values=vals, tags=tags)
        self._update_count(len(wanted))
        sel = self.tree.selection()
        if sel and (paths is None or sel[0] in paths):
            self._load_editor(sel[0])

    def clear(self):
        """Empty the table (no archive / no character)."""
        self.profile = None
        self.tree.delete(*self.tree.get_children())
        self._clear_editor()
        self._update_count(0)
        self._set_doc("")

    def _update_count(self, shown):
        if self.profile is None:
            self.count_lbl.config(text="")
            return
        npend = len(self.ses.changes.get(self.profile.guid, {}))
        self.count_lbl.config(text=f"{shown} dials shown · {npend} pending")

    # ------------------------------------------------------------ sorting

    def _sort_by(self, col):
        """Heading click: sort by that column, toggling direction."""
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._update_headings()
        self.reload(keep_view=True)

    def _update_headings(self):
        for c in self._cols:
            arrow = ""
            if c == self._sort_col:
                arrow = " \u25bc" if self._sort_desc else " \u25b2"
            self.tree.heading(c, text=self._heads[c] + arrow)

    def _sorted(self, paths):
        """Apply the active heading sort to the row paths (None = the
        default alphabetical order)."""
        if not self._sort_col or self.profile is None:
            return paths
        idx = self._cols.index(self._sort_col)

        def key(path):
            vals, _tags = self._row_values(path)
            return sort_key(vals[idx])

        return sorted(paths, key=key, reverse=self._sort_desc)

    # ------------------------------------------------------------ editing

    def _doc_for(self, path):
        # Full-path doc lookup (nested dials never inherit another
        # dial's doc/range)
        return schema_doc(self.ses.proj.docs, path) if self.ses.proj else {}

    def _set_doc(self, text):
        self.doc.config(state="normal")
        self.doc.delete("1.0", "end")
        self.doc.insert("1.0", text)
        self.doc.config(state="disabled")

    def _on_select(self, _ev=None):
        sel = self.tree.selection()
        if not sel or self.profile is None:
            return
        path = sel[0]
        doc = self._doc_for(path)
        if doc:
            self._set_doc(f"{path}  [{doc.get('type', '')}  "
                          f"{doc.get('min', '—')}..{doc.get('max', '—')}]\n"
                          f"{doc.get('desc', '')}")
        else:
            self._set_doc(f"{path}: no schema documentation")
        self._load_editor(path)

    def _load_editor(self, path):
        row = self.ses.dial_row(self.profile, path)
        cur = row["pending"] if row["pending"] is not None else \
            (row["value"] if row["value"] is not None else "")
        self._editing_path = path
        self._loaded_value = str(cur)
        self.entry.config(state="normal")
        self.entry.delete(0, "end")
        self.entry.insert(0, self._loaded_value)
        self.set_btn.config(state="normal")
        self.reset_btn.config(state="normal" if row["pending"] is not None
                              else "disabled")
        self.edit_lbl.config(text=path if len(path) <= 34 else "…" + path[-33:])
        doc = self._doc_for(path)
        rng = ""
        if doc.get("min") is not None or doc.get("max") is not None:
            rng = f"range {doc.get('min', '—')}..{doc.get('max', '—')}"
        self.range_lbl.config(text=rng)

    def _clear_editor(self):
        self._editing_path = None
        self._loaded_value = ""
        self.entry.delete(0, "end")
        self.entry.config(state="disabled")
        self.set_btn.config(state="disabled")
        self.reset_btn.config(state="disabled")
        self.edit_lbl.config(text="Select a dial to edit")
        self.range_lbl.config(text="")

    def _focus_entry(self, _ev=None):
        if self._editing_path is None:
            return
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.entry.icursor("end")
        return "break"

    def _revert(self, _ev=None):
        if self._editing_path is not None:
            self.entry.delete(0, "end")
            self.entry.insert(0, self._loaded_value)
        self.tree.focus_set()
        return "break"

    def _on_entry_focus_out(self, _ev=None):
        # Typed something and clicked away: never show a dialog from a
        # focus change. An in-range value is queued; an out-of-range
        # value reverts with a note (press Enter to get the confirmation
        # prompt for an out-of-range value).
        if self._editing_path is None or self._committing:
            return
        raw = self.entry.get().strip()
        if raw and raw != self._loaded_value:
            if out_of_range(raw, self._doc_for(self._editing_path)):
                self._notify(
                    f"note: {self._editing_path} = {raw} is outside the "
                    "schema range — reverted (press Enter to confirm it)")
                self._revert()
            else:
                self._apply(self._editing_path, raw, confirm=False)

    def _commit(self, _ev=None):
        if self._editing_path is None:
            return "break"
        raw = self.entry.get().strip()
        if not raw:
            self._notify(f"{self._editing_path}: empty value ignored — use "
                         "'Reset dial' to drop a pending edit")
            return "break"
        if raw == self._loaded_value:
            self.tree.focus_set()
            return "break"
        self._committing = True
        try:
            self._apply(self._editing_path, raw, confirm=True)
        finally:
            self._committing = False
        self.tree.focus_set()
        return "break"

    def _apply(self, path, raw, confirm=True):
        p = self.profile
        doc = self._doc_for(path)
        if out_of_range(raw, doc):
            if confirm:
                if not messagebox.askyesno(
                        "Out of schema range",
                        f"{path}: {raw} is outside the schema range "
                        f"{doc.get('min')}..{doc.get('max')}.\n\n"
                        "The in-game-verified personas use out-of-range values "
                        "successfully (SpyDetectValue 85), but this is at "
                        "your own risk. Apply anyway?",
                        parent=self.winfo_toplevel()):
                    self._revert()
                    return False
            else:
                self._notify(f"note: {path} = {raw} is outside the schema "
                             f"range {doc.get('min')}..{doc.get('max')}")
        try:
            self.ses.set_dial(p, path, raw)
        except SessionError as e:
            # _Apply(confirm=False) is also the
            # FOCUS-OUT path — a dialog from a focus change is forbidden
            # . Refused values notify on the status line instead.
            if confirm:
                messagebox.showerror("Edit refused", str(e),
                                     parent=self.winfo_toplevel())
            else:
                self._notify(f"edit refused: {e}")
                self._revert()
            return False
        self._loaded_value = raw
        self.refresh_paths([path])
        self._notify(f"{p.name}: {path} → {raw} (pending)")
        if self.on_change:
            self.on_change(p, [path])
        return True

    def _reset_dial(self):
        path = self._editing_path
        if path is None or self.profile is None:
            return
        self.ses.set_dial(self.profile, path, None)
        self.refresh_paths([path])
        self._notify(f"{self.profile.name}: {path} — pending edit dropped")
        if self.on_change:
            self.on_change(self.profile, [path])

    def _notify(self, text):
        if self.on_status:
            self.on_status(text)
