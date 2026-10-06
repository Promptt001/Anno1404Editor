#!/usr/bin/env python3
"""annoedit.gui.tabs — EXTRAS + FERTILITY tab widgets.

The EXTRAS tab edits global assets.xml dials, the FERTILITY tab edits island crop generation
rates in randommapgenerator.xml. Both are THIN pending-changes layers
over the Session (session.py), which validates every edit via an engine
dry-run and applies them at Export/Flash on a fresh project.

EXTRAS are GLOBAL: no owner flag exists in assets.xml — every change is
symmetric (the AI benefits identically). Fertility applies to NEW
islands only (endless/continuous games).
"""
import re
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..extras import EXTRA_FAMILIES, ExtrasError, display_names, parse_assets
from ..extras import set_extra as set_extra_edit
from ..session import SessionError  # Queue via session methods
from ..fertility import (FERT_TIERS, NORTH_CROPS, SOUTH_CROPS)
from .logic import (differs_from_vanilla, fertility_row_differs,
                    sort_key)  # sortable + non-vanilla rows


class ExtrasTab(ttk.Frame):
    """Global assets.xml dials: section/dial dropdowns, filter, asset table."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app          # the App (provides .ses + refresh hooks)
        self._rows = []
        self._sort_col = None
        self._sort_desc = False
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Section:").pack(side="left")
        self.section_var = tk.StringVar(value=next(iter(EXTRA_FAMILIES)))
        self.section_box = ttk.Combobox(top, textvariable=self.section_var,
                                        values=list(EXTRA_FAMILIES),
                                        state="readonly", width=14)
        self.section_box.pack(side="left", padx=(2, 10))
        self.section_box.bind("<<ComboboxSelected>>", self._on_section)
        ttk.Label(top, text="Dial:").pack(side="left")
        self.tag_var = tk.StringVar()
        self.tag_box = ttk.Combobox(top, textvariable=self.tag_var,
                                    state="readonly", width=26)
        self.tag_box.pack(side="left", padx=(2, 10))
        self.tag_box.bind("<<ComboboxSelected>>", self._refresh_table)
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.filter_var, width=16)
        ent.pack(side="left", padx=(2, 10))
        ent.bind("<KeyRelease>", lambda e: self._refresh_table(e))
        ttk.Button(top, text="Add asset (insert dial)",
                   command=self._add_asset).pack(side="left", padx=2)
        ttk.Button(top, text="Reset all extras",
                   command=self._reset_all).pack(side="left", padx=2)
        ttk.Button(top, text="Revert to vanilla (global)",
                   command=self._revert_globals).pack(side="left", padx=2)
        # Filter to rows whose current value differs from the vanilla
        # reference (requires a stored vanilla copy).
        self.nonvanilla_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Non-vanilla only",
                        variable=self.nonvanilla_only,
                        command=self._refresh_table).pack(side="left", padx=2)
        self.count = ttk.Label(top, text="no archive loaded")
        self.count.pack(side="left", padx=8)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        # TWO reference columns — 'current' = what the
        # OPENED archive actually contains (what an edit replaces),
        # 'vanilla' = the stock value (provided vanilla copy, else the
        # opened archive). Headings are click-to-sort.
        cols = ("asset", "current", "vanilla", "pending")
        self._heads = {"asset": "Asset", "current": "Current value(s) — opened archive",
                       "vanilla": "Vanilla value(s)", "pending": "Pending change(s)"}
        widths = {"asset": 300, "current": 200, "vanilla": 200, "pending": 230}
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=20)
        for c in cols:
            self.tree.heading(c, text=self._heads[c],
                              command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        vs.pack(side="left", fill="y", pady=4)
        self.tree.bind("<Double-1>", self._on_edit)
        self.tree.bind("<Return>", self._on_edit)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # non-vanilla rows stand out
        from .widgets import NONVANILLA_BG, PENDING_BG
        self.tree.tag_configure("nonvanilla", background=NONVANILLA_BG)
        self.tree.tag_configure("pending", background=PENDING_BG)

        self.doc = tk.Text(self, height=6, wrap="word", state="disabled",
                           bg="#f4f4f4")
        self.doc.pack(fill="x", padx=6, pady=4)

    # -- data plumbing (all through the Session; engine = authority) --

    def reload_catalog(self):
        """Called after open/restore: recompute the catalogs from the source."""
        ses = self.app.ses
        if not ses.proj:
            return
        self._catalog = ses.extras_catalog()          # reference (vanilla)
        self._current = ses.extras_current() or {}    # opened archive
        parsed = parse_assets(ses.proj.assets_text)
        disp = display_names(parsed)   # id(asset) -> display (both copies)
        self._names = {a["name"] for a in parsed} | set(disp.values())
        if self.section_var.get() not in EXTRA_FAMILIES:
            self.section_var.set(next(iter(EXTRA_FAMILIES)))
        self._refresh_dials()
        self._refresh_table()

    def _refresh_dials(self):
        section = self.section_var.get()
        tags = list(EXTRA_FAMILIES.get(section, {}))
        self.tag_box.configure(values=tags)
        if self.tag_var.get() not in tags:
            self.tag_var.set(tags[0] if tags else "")

    def _on_section(self, _ev=None):
        self._refresh_dials()
        self._refresh_table(True)

    def _sorted_extras(self):
        ses = self.app.ses
        return sorted(ses.extras.items(),
                      key=lambda kv: (kv[0][0], kv[0][1],
                                      kv[0][2] if kv[0][2] is not None else -1))

    def _pending_display(self, asset, tag):
        pend = [(occ, v) for (a, t, occ), v in self.app.ses.extras.items()
                if a == asset and t == tag]
        if not pend:
            return ""
        parts = []
        for occ, val in sorted(pend, key=lambda x: (x[0] is not None,
                                                    x[0] if x[0] is not None else -1)):
            parts.append(f"{'insert' if occ is None else f'#{occ + 1}'}={val}")
        return "  ".join(parts)

    def _refresh_table(self, _ev=None):
        # keep the user's place: selection index + scroll survive an edit
        sel = self.tree.selection()
        sel_idx = self.tree.index(sel[0]) if sel else None
        top = self.tree.yview()[0]
        self._rebuild_table()
        kids = self.tree.get_children()
        if sel_idx is not None and sel_idx < len(kids) and _ev is None:
            self.tree.selection_set(kids[sel_idx])
            self.tree.focus(kids[sel_idx])
        if _ev is None:
            self.tree.yview_moveto(top)

    def _rebuild_table(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = []
        ses = self.app.ses
        if not ses.proj:
            self.count.config(text="no archive loaded")
            return
        section = self.section_var.get()
        tag = self.tag_var.get()
        vals_map = self._catalog.get(section, {}).get(tag, {}) if tag else {}
        filt = self.filter_var.get().strip().lower()
        rows = list(vals_map.items())
        # UNION with the opened archive's catalog
        # an asset that carries the tag only in the OPENED (modded)
        # archive must be listed and editable, not invisible.
        cur_map = self._current.get(section, {}).get(tag, {}) if tag else {}
        for a in cur_map:
            if a not in vals_map:
                rows.append((a, None))
        for (a, t, _occ), _v in self._sorted_extras():
            if t == tag and a not in vals_map and a not in cur_map:
                rows.append((a, None))
        shown = 0
        out = []
        # The highlight needs a trustworthy reference: a stored vanilla
        # copy. Without one (ses.vanilla_baseline is None) the reference
        # is the opened archive itself and nothing can be classified;
        # the count line says so instead of silently highlighting nothing.
        has_ref = ses.vanilla_baseline is not None
        for asset, vals in rows:
            cur_vals = self._current.get(section, {}).get(tag, {}).get(asset)
            # Non-vanilla: the current occurrence list differs from the
            # reference list.
            nv = (has_ref and vals is not None
                  and differs_from_vanilla(cur_vals, vals))
            if self.nonvanilla_only.get() and not nv:
                continue
            if filt and filt not in asset.lower():
                continue
            van = "/".join(vals) if vals else "(no vanilla tag — INSERT)"
            # no tag in the OPENED archive = the edit INSERTs one
            cur = "/".join(cur_vals) if cur_vals else "(absent — INSERT)"
            out.append((asset, cur, van, self._pending_display(asset, tag),
                        {"asset": asset, "vals": vals, "cur": cur_vals,
                         "nonvanilla": nv}))
            shown += 1
        # heading sort (click-to-sort): reorders the displayed rows
        if self._sort_col:
            idx = ("asset", "current", "vanilla", "pending").index(self._sort_col)
            out.sort(key=lambda r: sort_key(r[idx]), reverse=self._sort_desc)
        for asset, cur, van, pend, rowd in out:
            tags = ()
            if pend:
                tags = tags + ("pending",)
            if rowd.get("nonvanilla"):
                tags = tags + ("nonvanilla",)
            self.tree.insert("", "end", values=(asset, cur, van, pend),
                             tags=tags)
            self._rows.append(rowd)
        note = ("" if has_ref else
                " · no vanilla copy stored — highlight/filter off "
                "(provide one: 'Store vanilla copy')")
        self.count.config(text=f"{shown} assets — "
                                f"{len(ses.extras)} pending extras total{note}")

    def _sort_by(self, col):
        """Heading click: sort by that column, toggling direction."""
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._update_headings()
        self._refresh_table()

    def _update_headings(self):
        for c, head in self._heads.items():
            arrow = ""
            if c == self._sort_col:
                arrow = " \u25bc" if self._sort_desc else " \u25b2"
            self.tree.heading(c, text=head + arrow)

    def _on_select(self, _ev=None):
        if not self.tree.selection():
            return
        idx = self.tree.index(self.tree.selection()[0])
        row = self._rows[idx]
        section = self.section_var.get()
        tag = self.tag_var.get()
        desc = EXTRA_FAMILIES.get(section, {}).get(tag, "")
        self.doc.config(state="normal")
        self.doc.delete("1.0", "end")
        self.doc.insert("1.0", f"{section} / {tag} — {row['asset']}\n{desc}\n"
                        "Double-click a row to edit. EXTRAS are GLOBAL: every change "
                        "is symmetric (the AI benefits identically — assets.xml has "
                        "no owner flag) and is applied at Export/Flash alongside any "
                        "AI preset. Multi-instance tags (e.g. noria per-level radii) "
                        "are edited per occurrence, never duplicated.")
        self.doc.config(state="disabled")

    def _validate(self, asset, tag, occ, value):
        sval = str(value).strip()
        if not sval:
            return "empty value"
        try:
            int(sval)
        except ValueError:
            return (f"{sval!r} is not a whole number — extras dials are "
                    "integers (ms times / radii / counts).")
        try:
            set_extra_edit(self.app.ses.proj.assets_text, asset, tag, sval, occ)
        except ExtrasError as e:
            return str(e)
        return None

    def _on_edit(self, _ev=None):
        ses = self.app.ses
        if not ses.proj or not self.tree.selection():
            return
        idx = self.tree.index(self.tree.selection()[0])
        row = self._rows[idx]
        asset, vals = row["asset"], row["vals"]
        tag = self.tag_var.get()
        pend = self._pending_display(asset, tag) or "(none)"
        cur = row.get("cur") or vals   # shown values: current, else reference
        shown_vals = "/".join(cur) if cur else None
        # Decide single- vs multi-occurrence from the CURRENT (opened
        # archive) values: the edit applies to the current file, and a
        # modded archive may have a different occurrence count than
        # vanilla.
        if cur and len(cur) > 1:
            # Show the PARENT PATH of each occurrence: the real-data
            # census found multi-instance noria tags under DIFFERENT
            # parents (Green/Moisture/Saturated ground states, not
            # 'levels') - plain 'values 1/2/3' mislabels the field.
            ppaths = self._parent_paths(asset, tag)
            shown = " / ".join(
                (f"{i + 1}={v} ({ppaths[i].split('/')[-1]})"
                 if ppaths and i < len(ppaths) and len(set(ppaths)) > 1
                 else f"{i + 1}={v}")
                for i, v in enumerate(cur))
            note = ("")
            if ppaths and len(set(ppaths)) > 1:
                note = ("\nNOTE: these occurrences live under DIFFERENT"
                        " parents - check you are editing the intended"
                        " one:\n  "
                        + "\n  ".join(f"{i + 1}: {p}"
                                       for i, p in enumerate(ppaths)))
            prompt = simpledialog.askstring(
                "Edit extra (multi-instance)",
                f"{asset} / {tag}\n\n"
                "current values (file order): " + shown
                + f"\nvanilla: {'/'.join(vals)}\npending: {pend}\n\n"
                "New value as 'occurrence:value' (1-based), e.g. 2:5000\n"
                "(blank = cancel, 'reset' = drop ALL pending for this asset):"
                + note,
                parent=self)
        else:
            prompt = simpledialog.askstring(
                "Edit extra",
                f"{asset} / {tag}\n\n"
                f"current: {shown_vals if shown_vals else '(no tag — INSERT)'}\n"
                f"vanilla: {'/'.join(vals) if vals else '(no vanilla tag — INSERT)'}\n"
                f"pending: {pend}\n\n"
                "New value (blank = cancel, 'reset' = drop pending):",
                parent=self)
        if prompt is None or not prompt.strip():
            return
        s = prompt.strip()
        if s.lower() == "reset":
            ses.clear_extra(asset, tag)
            self._refresh_table()
            return
        occ = 0 if (cur and len(cur) == 1) else None
        if cur and len(cur) > 1:
            m = re.match(r"^(\d+)\s*[:=]\s*(.+)$", s)
            if not m:
                messagebox.showwarning(
                    "Invalid input",
                    "Multi-instance tag — use 'occurrence:value' (1-based), "
                    "e.g. 2:5000", parent=self)
                return
            occ, s = int(m.group(1)) - 1, m.group(2).strip()
        err = self._validate(asset, tag, occ, s)
        if err:
            messagebox.showwarning("Invalid extra", f"{asset}/{tag}\n\n{err}",
                                   parent=self)
            return
        # Queue through the SESSION (typed validation
        # canonical keys) — never a direct pending-dict write
        try:
            ses.set_extra(asset, tag, s, occ)
        except SessionError as e:
            messagebox.showwarning("Invalid extra", str(e), parent=self)
            return
        self._refresh_table()
        self.app._after_tab_change()

    def _add_asset(self):
        ses = self.app.ses
        if not ses.proj:
            messagebox.showinfo("No archive", "Open a data1.rda first.",
                                parent=self)
            return
        tag = self.tag_var.get()
        if not tag:
            return
        name = simpledialog.askstring(
            "Add asset (insert dial)",
            f"Dial: {tag}\n\nAsset name exactly as in assets.xml\n"
            f"(e.g. PrintingHouse — it gains a new <{tag}>):", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name not in self._names:
            messagebox.showwarning(
                "Unknown asset",
                f"{name!r}: not an asset name in assets.xml.", parent=self)
            return
        # Check the OPENED archive (where the tag would be inserted
        # a modded archive may already carry it even when vanilla doesn't)
        if name in self._current.get(self.section_var.get(), {}).get(tag, {}):
            messagebox.showwarning(
                "Already present",
                f"{name} already has {tag} in the opened archive — "
                "edit its row instead.", parent=self)
            return
        val = simpledialog.askstring(
            "Insert value",
            f"{name} / {tag}  (new tag, INSERT shape)\n\nValue:", parent=self)
        if val is None or not val.strip():
            return
        err = self._validate(name, tag, None, val.strip())
        if err:
            messagebox.showwarning("Invalid extra", f"{name}/{tag}\n\n{err}",
                                   parent=self)
            return
        # Queue through the SESSION — never a direct write
        try:
            ses.set_extra(name, tag, val.strip())
        except SessionError as e:
            messagebox.showwarning("Invalid extra", str(e), parent=self)
            return
        self._refresh_table()
        self.app._after_tab_change()

    def _reset_all(self):
        ses = self.app.ses
        if not ses.extras:
            return
        if messagebox.askyesno(
                "Reset extras",
                f"Drop all {len(ses.extras)} pending extras changes?",
                parent=self):
            ses.clear_extras()   # never assign to the read-only view
            self._refresh_table()
            self.app._after_tab_change()

    def _parent_paths(self, asset, tag):
        """Distinct-parent info for one (asset, tag): the parent
        element path of each occurrence (real-data census: noria
        per-ground-state tags live under Green/Moisture/Saturated).
        -> [path str] in file order, [] when unavailable.
"""
        try:
            from ..extras import find_asset, parse_assets, asset_text, parent_paths
            assets = parse_assets(self.app.ses.proj.assets_text)
            a = find_asset(assets, asset)
            return parent_paths(asset_text(self.app.ses.proj.assets_text, a), tag)
        except Exception:
            return []

    def _revert_globals(self):
        # The explicit global revert action — no more
        # per-character Vanilla side effects
        ses = self.app.ses
        try:
            ses.revert_globals_to_reference()
        except Exception as e:
            messagebox.showerror("Revert globals", str(e), parent=self)
            return
        self._refresh_table()
        self.app._after_tab_change()
        # Allow-listed INSERTS the tool itself made (e.g.
        # ProductionTime on the four donor buildings) cannot be
        # removed by a value revert (no delete op exists) - say so
        # instead of silently keeping them.
        unrev = getattr(ses, "_last_unrevertable_extras", [])
        if unrev:
            messagebox.showwarning(
                "Not fully revertible",
                "Queued global reverts to the vanilla reference.\n\n"
                f"{len(unrev)} EXTRAS leaf/leaves this tool INSERTED "
                "(absent from the vanilla reference) cannot be "
                "removed by a value revert - no delete operation "
                "exists. They stay as they are:\n  "
                + "\n  ".join(unrev[:8]), parent=self)
        self.app._set_status(
            "extras+fertility: queued reverts to the vanilla reference")


class FertilityTab(ttk.Frame):
    """Island crop generation rates: tier dropdown, crop table, N/S edits."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._rows = []
        self._sort_col = None
        self._sort_desc = False
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Tier:").pack(side="left")
        self.tier_var = tk.StringVar(value=FERT_TIERS[0])
        self.tier_box = ttk.Combobox(top, textvariable=self.tier_var,
                                     values=list(FERT_TIERS),
                                     state="readonly", width=10)
        self.tier_box.pack(side="left", padx=(2, 10))
        self.tier_box.bind("<<ComboboxSelected>>", self._refresh_table)
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.filter_var, width=14)
        ent.pack(side="left", padx=(2, 10))
        ent.bind("<KeyRelease>", lambda e: self._refresh_table(e))
        ttk.Button(top, text="All crops both hemispheres",
                   command=self._both_hemispheres).pack(side="left", padx=2)
        ttk.Button(top, text="Reset fertility",
                   command=self._reset_all).pack(side="left", padx=2)
        ttk.Button(top, text="Revert to vanilla (global)",
                   command=self._revert_globals).pack(side="left", padx=2)
        # Filter to rows whose current N/S differs from the vanilla
        # reference (requires a stored vanilla copy).
        self.nonvanilla_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Non-vanilla only",
                        variable=self.nonvanilla_only,
                        command=self._refresh_table).pack(side="left", padx=2)
        self.count = ttk.Label(top, text="no archive loaded")
        self.count.pack(side="left", padx=8)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        # Current (opened archive) + vanilla (reference) columns
        # headings are click-to-sort
        cols = ("crop", "current", "vanilla", "pending")
        self._heads = {"crop": "Crop", "current": "Current N/S (%) — opened archive",
                       "vanilla": "Vanilla N/S (%)", "pending": "Pending change(s)"}
        widths = {"crop": 140, "current": 170, "vanilla": 150, "pending": 230}
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=20)
        for c in cols:
            self.tree.heading(c, text=self._heads[c],
                              command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True,
                       padx=(6, 0), pady=4)
        vs.pack(side="left", fill="y", pady=4)
        self.tree.bind("<Double-1>", self._on_edit)
        self.tree.bind("<Return>", self._on_edit)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # non-vanilla rows stand out
        from .widgets import NONVANILLA_BG, PENDING_BG
        self.tree.tag_configure("nonvanilla", background=NONVANILLA_BG)
        self.tree.tag_configure("pending", background=PENDING_BG)

        self.doc = tk.Text(self, height=6, wrap="word", state="disabled",
                           bg="#f4f4f4")
        self.doc.pack(fill="x", padx=6, pady=4)

    def reload_catalog(self):
        """Called after open/restore: rebuild the fertility catalogs + table."""
        ses = self.app.ses
        if not ses.proj:
            return
        self._catalog = ses.fertility_catalog()          # reference (vanilla)
        self._current = ses.fertility_current() or []    # opened archive
        self._refresh_table()

    def _pending_display(self, tier, crop):
        pend = self.app.ses.fert.get((tier, crop))
        if not pend:
            return ""
        parts = []
        if pend[0] is not None:
            parts.append(f"N={pend[0]}")
        if pend[1] is not None:
            parts.append(f"S={pend[1]}")
        return " ".join(parts)

    def _refresh_table(self, _ev=None):
        # keep the user's place: selection index + scroll survive an edit
        sel = self.tree.selection()
        sel_idx = self.tree.index(sel[0]) if sel else None
        top = self.tree.yview()[0]
        self._rebuild_table()
        kids = self.tree.get_children()
        if sel_idx is not None and sel_idx < len(kids) and _ev is None:
            self.tree.selection_set(kids[sel_idx])
            self.tree.focus(kids[sel_idx])
        if _ev is None:
            self.tree.yview_moveto(top)

    def _rebuild_table(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = []
        ses = self.app.ses
        if not ses.proj:
            self.count.config(text="no archive loaded")
            return
        tier = self.tier_var.get()
        filt = self.filter_var.get().strip().lower()
        cur_by_key = {(r["tier"], r["crop"]): r for r in self._current}
        shown = 0
        out = []
        # The highlight needs a trustworthy reference (see the EXTRAS tab).
        has_ref = ses.vanilla_baseline is not None
        for row in self._catalog:
            if row["tier"] != tier:
                continue
            crop = row["crop"]
            if filt and filt not in crop.lower():
                continue
            c = cur_by_key.get((row["tier"], crop), {})
            van = f"N={row['north']}  S={row['south']}"
            cur = f"N={c.get('north')}  S={c.get('south')}" \
                if ("north" in c or "south" in c) else ""
            # Non-vanilla: the current N/S differs from the vanilla N/S,
            # or the opened archive lacks a crop row vanilla has (a mod
            # removed it). Pure helper, tested in tests/test_nonvanilla.py.
            nv = has_ref and fertility_row_differs(c, row)
            if self.nonvanilla_only.get() and not nv:
                continue
            out.append((crop, cur, van, self._pending_display(tier, crop),
                        row, nv))
            shown += 1
        if self._sort_col:
            idx = ("crop", "current", "vanilla", "pending").index(self._sort_col)
            out.sort(key=lambda r: sort_key(r[idx]), reverse=self._sort_desc)
        for crop, cur, van, pend, row, nv in out:
            tags = ()
            if pend:
                tags = tags + ("pending",)
            if nv:
                tags = tags + ("nonvanilla",)
            self.tree.insert("", "end", values=(crop, cur, van, pend),
                             tags=tags)
            self._rows.append(row)
        note = ("" if has_ref else
                " · no vanilla copy stored — highlight/filter off "
                "(provide one: 'Store vanilla copy')")
        self.count.config(text=f"{shown} crops — "
                                f"{len(ses.fert)} pending fertility changes{note}")

    def _sort_by(self, col):
        """Heading click: sort by that column, toggling direction."""
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        self._update_headings()
        self._refresh_table()

    def _update_headings(self):
        for c, head in self._heads.items():
            arrow = ""
            if c == self._sort_col:
                arrow = " \u25bc" if self._sort_desc else " \u25b2"
            self.tree.heading(c, text=head + arrow)

    def _on_select(self, _ev=None):
        if not self.tree.selection():
            return
        idx = self.tree.index(self.tree.selection()[0])
        row = self._rows[idx]
        hemi = "northern" if row["crop"] in NORTH_CROPS else (
            "southern" if row["crop"] in SOUTH_CROPS else "wild")
        self.doc.config(state="normal")
        self.doc.delete("1.0", "end")
        self.doc.insert("1.0",
                        f"{row['tier']} tier / {row['crop']} ({hemi} crop)\n"
                        f"Vanilla: North={row['north']}%, South={row['south']}%.\n"
                        "Percentage chance that a NEW island generated at that "
                        "resource-amount tier can grow this crop in that "
                        "hemisphere. Set North>0 on a southern crop (or "
                        "South>0 on a northern one) to make it generatable "
                        "in both hemispheres. Applies only to newly "
                        "generated islands (endless/continuous games).\n"
                        "Double-click a row to edit (N and S, blank = keep).")
        self.doc.config(state="disabled")

    def _on_edit(self, _ev=None):
        ses = self.app.ses
        if not ses.proj or not self.tree.selection():
            return
        idx = self.tree.index(self.tree.selection()[0])
        row = self._rows[idx]
        tier, crop = row["tier"], row["crop"]
        pend = self._pending_display(tier, crop) or "(none)"
        prompt = simpledialog.askstring(
            "Edit fertility",
            f"{tier} / {crop}\n\n"
            f"vanilla: N={row['north']}  S={row['south']}\n"
            f"current: {self._current_ns(tier, crop)}\n"
            f"pending: {pend}\n\n"
            "New values as 'N:S' (e.g. 40:60), single value = N only\n"
            "(blank = cancel, 'reset' = drop pending for this crop):",
            parent=self)
        if prompt is None or not prompt.strip():
            return
        s = prompt.strip()
        if s.lower() == "reset":
            ses.clear_fertility(tier, crop)
            self._refresh_table()
            self.app._after_tab_change()
            return
        m = re.match(r"^([0-9]+)?\s*[:=]?\s*([0-9]+)?$", s)
        if not m or (m.group(1) is None and m.group(2) is None):
            messagebox.showwarning(
                "Invalid input",
                "Use 'N:S' (e.g. 40:60) or a single N value (0-100).",
                parent=self)
            return
        north = m.group(1)
        sep = ":" in s or "=" in s
        south = m.group(2) if sep else None
        try:
            ses.set_fertility(tier, crop, north, south)
        except Exception as e:
            messagebox.showwarning("Invalid fertility",
                                   f"{tier}/{crop}\n\n{e}", parent=self)
            return
        self._refresh_table()
        self.app._after_tab_change()

    def _current_ns(self, tier, crop):
        """Current (opened archive) N/S string for the edit prompt."""
        for r in self._current:
            if r["tier"] == tier and r["crop"] == crop:
                return f"N={r['north']}  S={r['south']}"
        return "(absent)"

    def _both_hemispheres(self):
        """One-click: every crop in the SELECTED tier gets its OTHER
        hemisphere's vanilla rate for the missing hemisphere, so every crop
        is generatable in both hemispheres. Existing pending values kept."""
        ses = self.app.ses
        if not ses.proj:
            messagebox.showinfo("No archive", "Open a data1.rda first.",
                                parent=self)
            return
        tier = self.tier_var.get()
        added = 0
        # One-click multi-edits are transactional
        # — a mid-loop failure leaves the fertility tab's pending state
        # exactly as it was.
        with ses._txn():
            for row in self._catalog:
                if row["tier"] != tier:
                    continue
                cur = ses.fert.get((tier, row["crop"]), (None, None))
                north, south = cur
                if north is None and row["north"] == 0 and row["south"] > 0:
                    north = row["south"]
                if south is None and row["south"] == 0 and row["north"] > 0:
                    south = row["north"]
                if (north, south) != cur:
                    # NO per-row swallow — a mid-loop
                    # failure rolls the WHOLE batch back via _txn (
                    # semantics); the status line then tells the truth.
                    ses.set_fertility(tier, row["crop"], north, south)
                    added += 1
            self._refresh_table()
            self.app._after_tab_change()
            self.app._set_status(
                f"fertility: {added} crops in tier {tier!r} set to both hemispheres "
                f"({len(ses.fert)} pending total)")

    def _reset_all(self):
        ses = self.app.ses
        if not ses.fert:
            return
        if messagebox.askyesno(
                "Reset fertility",
                f"Drop all {len(ses.fert)} pending fertility changes?",
                parent=self):
            ses.clear_fertility()
            self._refresh_table()
            self.app._after_tab_change()

    def _revert_globals(self):
        # Same explicit action, reachable from the
        # fertility tab too
        ses = self.app.ses
        try:
            ses.revert_globals_to_reference()
        except Exception as e:
            messagebox.showerror("Revert globals", str(e), parent=self)
            return
        self._refresh_table()
        self.app._after_tab_change()
        # Allow-listed INSERTS the tool itself made (e.g.
        # ProductionTime on the four donor buildings) cannot be
        # removed by a value revert (no delete op exists) - say so
        # instead of silently keeping them.
        unrev = getattr(ses, "_last_unrevertable_extras", [])
        if unrev:
            messagebox.showwarning(
                "Not fully revertible",
                "Queued global reverts to the vanilla reference.\n\n"
                f"{len(unrev)} EXTRAS leaf/leaves this tool INSERTED "
                "(absent from the vanilla reference) cannot be "
                "removed by a value revert - no delete operation "
                "exists. They stay as they are:\n  "
                + "\n  ".join(unrev[:8]), parent=self)
        self.app._set_status(
            "extras+fertility: queued reverts to the vanilla reference")
