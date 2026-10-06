#!/usr/bin/env python3
"""picker — a friendlier file picker for tkinter.

tkinter's askopenfilename is awkward: some platforms only allow going UP
directories then clicking back down, and there is no way to paste a path
directly. This module provides a small in-app browser:

  * breadcrumb bar of the current directory (click any ancestor)
  * a plain list of subdirectories and .rda files
  * a manual path Entry — paste or type an absolute path and press Enter
    (directories open; files with the wanted suffix are selected)
  * a "System dialog…" button falling back to filedialog.askopenfilename
  * remembered last directory (persisted via the app settings store)

ask_path(parent, title, suffixes, settings) -> chosen path or None.
The dialog is display-free testable: pass a stubbed _sys_dialog.
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk

from .logic import wanted_file


class PathPicker(tk.Toplevel):
    """In-app file browser with manual path entry and breadcrumbs."""

    def __init__(self, parent, title="Select file", suffixes=(".rda",),
                 settings=None, _sys_dialog=None):
        from .widgets import grab_when_mapped
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        # Grabbing before the window is mapped can raise "grab failed:
        # window not viewable" on some X11 window managers; see
        # grab_when_mapped.
        grab_when_mapped(self)
        self.settings = settings
        self._sys_dialog = _sys_dialog or filedialog.askopenfilename
        self.suffixes = tuple(s.lower() for s in suffixes) or (".rda",)
        self.result = None
        self.resizable(True, True)
        self.geometry("720x420")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Path:").pack(side="left")
        self.path_var = tk.StringVar()
        self.path_entry = ttk.Entry(top, textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.path_entry.bind("<Return>", self._on_path_enter)
        ttk.Button(top, text="Open", command=self._on_path_enter).pack(
            side="left", padx=2)
        ttk.Button(top, text="System dialog…",
                   command=self._use_system_dialog).pack(side="left", padx=2)

        self.crumbs = ttk.Frame(self)
        self.crumbs.pack(fill="x", padx=6, pady=(0, 2))

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=6, pady=2)
        sb = ttk.Scrollbar(mid, orient="vertical")
        self.listbox = tk.Listbox(mid, activestyle="dotbox",
                                  exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        sb.pack(side="left", fill="y")
        self.listbox.bind("<Double-1>", self._on_double)
        self.listbox.bind("<Return>", self._on_double)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        self.status = ttk.Label(self, text="", anchor="w")
        self.status.pack(fill="x", padx=6, pady=2)
        ttk.Button(self, text="Cancel", command=self.destroy).pack(
            side="right", padx=6, pady=(0, 6))
        self.ok_btn = ttk.Button(self, text="OK", state="disabled",
                                 command=self._confirm)
        self.ok_btn.pack(side="right", padx=6, pady=(0, 6))

        start = None
        if settings is not None:
            try:
                start = settings.get("last_picker_dir")
            except Exception:
                start = None
        self._load_dir(start if start and os.path.isdir(start)
                       else os.path.expanduser("~"))
        self.path_entry.focus_set()

    # ------------------------------------------------------------- actions

    def _load_dir(self, d):
        """List directory d: subdirs first (with [/] marker), then files."""
        try:
            entries = sorted(os.listdir(d), key=str.lower)
        except OSError as e:
            self.status.config(text=f"cannot open directory: {e}")
            return
        self.current = d
        self.path_var.set(d)
        self.listbox.delete(0, "end")
        self._entries = []
        for n in entries:
            p = os.path.join(d, n)
            try:
                if os.path.isdir(p):
                    self._entries.append(("dir", p))
                    self.listbox.insert("end", "\U0001F4C1 " + n + "  [/]")
                elif self._wanted(p):
                    self._entries.append(("file", p))
                    self.listbox.insert("end", "\U0001F4C4 " + n)
            except OSError:
                continue
        self._render_crumbs()
        self.status.config(
            text="double-click a directory to open; select a file, or "
                 "type/paste a full path above and press Enter")
        self.ok_btn.config(state="disabled")

    def _wanted(self, p):
        # The export store writes data1.rda_<name> files (the vanilla
        # copy is data1.rda_vanilla), whose "extension" is .rda_<name>.
        # Accept .rda-suffixed names and any data1.rda_* name.
        return wanted_file(p, self.suffixes)

    def _ask_open_anyway(self, path):
        """Confirm opening a typed path the filter would hide."""
        from tkinter import messagebox
        return messagebox.askyesno(
            self.title(), f"{path}\n"
            "does not look like an RDA archive — open it anyway?")

    def _render_crumbs(self):
        """Breadcrumbs: one clickable button per ancestor directory."""
        for w in self.crumbs.winfo_children():
            w.destroy()
        parts = self.current.replace("\\", "/").split("/")
        if parts and parts[0] == "":
            parts[0] = "/"
        acc = ""
        for i, part in enumerate(parts):
            if i == 0 and part == "/":
                acc = "/"
            elif part:
                acc = (acc.rstrip("/") + "/" + part) if acc else part
            label = part or os.path.abspath("/").split(os.sep)[0] or "/"
            ttk.Button(self.crumbs, text=label,
                       command=lambda a=acc: self._load_dir(a)).pack(
                           side="left", padx=1)
            if i < len(parts) - 1:
                ttk.Label(self.crumbs, text="›").pack(side="left")

    def _on_select(self, _ev=None):
        """Listbox selection handler: enable OK only when a file is selected."""
        sel = self.listbox.curselection()
        if sel and self._entries[sel[0]][0] == "file":
            self.ok_btn.config(state="normal")
            self.status.config(text=f"selected: {self._entries[sel[0]][1]}")
        else:
            self.ok_btn.config(state="disabled")

    def _on_double(self, _ev=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        kind, p = self._entries[sel[0]]
        if kind == "dir":
            self._load_dir(p)
        else:
            self.result = p
            self._remember(p)
            self.destroy()

    def _on_path_enter(self, _ev=None):
        raw = self.path_var.get().strip()
        if not raw:
            return
        raw = os.path.expanduser(raw)
        if os.path.isdir(raw):
            self._load_dir(raw)
        elif os.path.isfile(raw) and self._wanted(raw):
            self.result = raw
            self._remember(raw)
            self.destroy()
        elif os.path.isfile(raw):
            # A typed path that fails the filter can still be opened
            # after an explicit confirm (the suffix check is a hint, not
            # a hard refusal)
            if self._ask_open_anyway(raw):
                self.result = raw
                self._remember(raw)
                self.destroy()
        else:
            self.status.config(text=f"no such file or directory: {raw}")
        if raw and os.path.isdir(raw):
            try:
                if self.settings is not None:
                    self.settings.set("last_picker_dir", raw)
            except Exception:
                pass

    def _use_system_dialog(self):
        # Tk wants (LABEL, PATTERN) pairs, in that order.
        p = self._sys_dialog(title=self.title(),
                             filetypes=[("RDA archive", "*" + s) for s in
                                        self.suffixes] +
                                       [("All files", "*.*")])
        if p:
            self.result = p
            self._remember(p)
            self.destroy()

    def _remember(self, path):
        d = os.path.dirname(os.path.abspath(path))
        if self.settings is not None:
            try:
                self.settings.set("last_picker_dir", d)
            except Exception:
                pass

    def _confirm(self):
        sel = self.listbox.curselection()
        if sel and self._entries[sel[0]][0] == "file":
            self.result = self._entries[sel[0]][1]
            self._remember(self.result)
            self.destroy()


def ask_path(parent, title="Select file", suffixes=(".rda",),
             settings=None, _sys_dialog=None):
    """Open PathPicker modally; return the chosen path or None."""
    win = PathPicker(parent, title=title, suffixes=suffixes,
                     settings=settings, _sys_dialog=_sys_dialog)
    parent.wait_window(win)
    return win.result
