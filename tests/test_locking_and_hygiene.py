"""Locking and hygiene.

- _Flock's depth counter is thread-guarded.
- Settings writes use a unique temp name.
- text_span raises on unclosed fragment nodes.
- Pruning removes .md5 sidecars together with their archives.
- release_keystream_cache frees the decrypt keystream.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fixture  # noqa: F401  (pins ANN0140_HOME isolation on import)


class FlockThreadSafetyTests(unittest.TestCase):

    def test_flock_depth_counter_is_thread_guarded(self):
        from annoedit.backup import _Flock
        fl = _Flock(os.path.join(tempfile.mkdtemp(), "session.lock"))
        self.assertIsNotNone(getattr(fl, "_mu", None),
                             "_Flock must guard its depth counter with an "
                             "internal RLock (background load vs Tk-thread "
                             "close raced the plain counter)")
        # nested enter/exit still tracks depth correctly
        with fl:
            with fl:
                self.assertEqual(fl.depth, 2)
            self.assertEqual(fl.depth, 1)
        self.assertEqual(fl.depth, 0)
        # concurrent enters from many threads: depth returns to 0
        import threading
        def hammer():
            for _ in range(20):
                with fl:
                    pass
        ts = [threading.Thread(target=hammer) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(fl.depth, 0)


class SettingsTmpTests(unittest.TestCase):

    def test_save_uses_unique_tmp(self):
        import shutil
        from annoedit.appsettings import Settings
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        st = Settings(root=tmp)
        st.set("live_path", "/x/y.rda")
        # no fixed settings.json.tmp is left behind or raced
        self.assertFalse(os.path.exists(
            os.path.join(tmp, "settings.json.tmp")))
        # the data landed
        st2 = Settings(root=tmp)
        self.assertEqual(st2.get("live_path"), "/x/y.rda")


class TextSpanTests(unittest.TestCase):

    def test_text_span_raises_on_unclosed(self):
        from annoedit.spans import index, text_span, SpanError
        # fragment mode: an unclosed top element carries
        # close_start == -1 (never sliced silently)
        root = index("<a><b>1</b><c>2", fragment=True)
        node = [c for c in root.children if c.tag == "a"][0]
        self.assertEqual(node.close_start, -1)
        with self.assertRaises(SpanError):
            text_span(node)
        # a closed node still works
        root2 = index("<a><b>1</b><c>2</c></a>")
        node2 = [c for c in root2.children if c.tag == "a"][0]
        s, e = text_span(node2)
        self.assertEqual(s, e - len("<b>1</b><c>2</c>"))


class SidecarPruneTests(unittest.TestCase):

    def test_prune_removes_sidecar_with_archive(self):
        import shutil
        from annoedit.backup import BackupStore
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        bs = BackupStore(tmp)
        # an orphan archive + its sidecar
        orphan = os.path.join(tmp, "vanilla-deadbeef.rda")
        open(orphan, "wb").write(b"x")
        open(orphan + ".md5", "w").write("deadbeef")
        removed = bs.prune_orphans()
        self.assertIn("vanilla-deadbeef.rda", removed)
        self.assertFalse(os.path.exists(orphan))
        self.assertFalse(os.path.exists(orphan + ".md5"),
                         "the .md5 sidecar must go with its archive")


class KeystreamCacheTests(unittest.TestCase):

    def test_release_keystream_cache(self):
        from annoedit import rda
        # generate a small keystream, then release
        ks = rda._keystream(1024, 0xA2C2A)
        self.assertTrue(len(rda._KEYSTREAM_CACHE) >= 1)
        rda.release_keystream_cache()
        self.assertEqual(len(rda._KEYSTREAM_CACHE), 0)


if __name__ == "__main__":
    unittest.main()
