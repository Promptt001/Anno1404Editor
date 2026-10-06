#!/usr/bin/env python3
"""Guitest — shared GUI-test harness helpers.

A modal messagebox.showerror/showinfo/askyesno that nobody can dismiss
makes a failing GUI test HANG forever instead of failing (that is how
shipped green under xvfb: the export failed, _bg_failed opened an
error box, the suite hung and was killed, and the release gate passed
on the truncated output).

Usage in a GUI test setUp:

    from guitest import patch_messagebox

    self.mb = patch_messagebox(self)     # records calls, returns defaults

Then assert on the recorded calls (self.mb.errors, .infos, .yes_no) or
at least that no error box was shown:

    self.assertEqual(self.mb.errors, [])   # nothing failed silently
"""
import unittest.mock as mock


def patch_messagebox(testcase):
    """Patch tkinter.messagebox for the lifetime of `testcase`.

    Every showerror/showinfo/showwarning call is recorded (message
    first). askyesno/askokcancel return the `answer` attribute (True by
    default — set self.mb.answer = False to test refusal paths).
    -> the recording object (attrs: errors, infos, warnings, yes_no,
    answer).
    """
    import tkinter.messagebox as mb

    rec = type("MBRecorder", (), {})()
    rec.errors, rec.infos, rec.warnings, rec.yes_no = [], [], [], []
    rec.answer = True

    def _mk(kind, store):
        def _fn(title, message=None, **kw):
            store.append((title, message))
            return rec.answer
        return _fn

    # patch where the GUI LOOKS IT UP: annoedit.gui.app / .editor /
    # .widgets import `from tkinter import messagebox` — patch the
    # tkinter.messagebox module itself (all importers share it)
    patchers = []
    for name, store in (("showerror", rec.errors),
                        ("showinfo", rec.infos),
                        ("showwarning", rec.warnings),
                        ("askyesno", rec.yes_no)):
        patchers.append(mock.patch.object(mb, name, _mk(name, store)))
    for p in patchers:
        p.start()
        testcase.addCleanup(p.stop)
    return rec
