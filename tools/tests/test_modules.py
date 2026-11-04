"""Every module's generated dom0 scripts, and the all-in-one, against mocked Qubes
tools: run from scratch, re-run, and check that what module.toml asks for is
what the qubes end up with. Test classes are made for whatever modules this
repository holds."""
import json
import os
import sys
import tomllib
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dom0_harness import D, HAVE_USER, MOCK, ROOT, Harness, dvm, vm  # noqa: E402

MODULES = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "module.toml")))


def load(folder):
    with open(os.path.join(ROOT, folder, "module.toml"), "rb") as f:
        return tomllib.load(f)


def firewall(rules):
    out = []
    for r in rules:
        w = r.split()
        out.append("action=accept specialtarget=dns" if w == ["dns"] else f"action=accept proto={w[0]} dstports={w[1]}")
    return out + ["action=drop"]


class MakerChecks:
    """Checks for a module with [[qube]] entries; PREFIX is its template prefix."""
    PREFIX = None

    def check_end_state(self):
        q = self.qubes()
        for e in self.M["qube"]:
            n = e["name"]
            self.assertIn(n, q, n)
            got = q[n]
            if e["kind"] == "named-disposable":
                d = q[e["dvm"]]
                self.assertEqual((d["klass"], d["template"], d["prefs"].get("template_for_dispvms")),
                                 ("AppVM", self.PREFIX + n, "True"), e["dvm"])
                self.assertEqual(d["prefs"].get("label"), e.get("dvm_label", "black"))
                self.assertFalse(d["running"], f"{e['dvm']} left running")
                self.assertEqual((got["klass"], got["template"]), ("DispVM", e["dvm"]))
            else:
                self.assertEqual((got["klass"], got["template"]), ("AppVM", self.PREFIX + n))
            self.assertEqual(q[self.PREFIX + n]["klass"], "TemplateVM")
            if "label" in e:
                self.assertEqual(got["prefs"]["label"], e["label"], n)
            if "memory" in e:
                self.assertEqual(got["prefs"]["memory"], str(e["memory"]))
                self.assertNotIn("maxmem", got["prefs"], "maxmem stays at the default")
            if "netvm" in e:
                self.assertEqual(got["prefs"]["netvm"], "" if e["netvm"] == "none" else e["netvm"])
            if "firewall" in e:
                self.assertEqual(got["firewall"], firewall(e["firewall"]))
            if "shutdown_timeout" in e:
                self.assertEqual(got["prefs"]["shutdown_timeout"], str(e["shutdown_timeout"]))
            if "menu" in e:
                self.assertEqual(got["features"]["menu-items"], " ".join(e["menu"]))
        if "policy" in self.M:
            text = self.policy(self.M["policy"]["file"])
            self.assertIsNotNone(text, "policy written")
            for line in self.M["policy"]["lines"]:
                self.assertIn(line.replace("{", "").replace("}", ""), text)
            for old in self.M["policy"].get("replaces", []):
                self.assertIsNone(self.policy(old), f"{old} removed")
        ran = self.roles()
        for e in self.M["qube"]:
            if e.get("dvm_role"):
                self.assertIn((e["dvm"], e["dvm_role"].replace("{", "").replace("}", "")), ran)
            if e.get("role"):
                self.assertIn((e["name"], e["role"]), ran)

    def test_fresh(self):
        rc, out = self.run_setup("--yes")
        self.assertGood(rc, out)
        self.check_end_state()

    def test_rerun(self):
        self.assertGood(*self.run_setup("--yes"))
        kept = {}

        def customise(q):
            for e in self.M["qube"]:
                holder = e.get("dvm") or e["name"]
                for p in e.get("keep", []):
                    q[holder]["files"][p] = kept[p] = "# yours\n.example.org\n"
                if e["kind"] == "named-disposable":
                    q[e["dvm"]]["files"]["/rw/leftover"] = "x"
                else:
                    q[e["name"]]["files"]["/home/user/data"] = "data"
                    q[e["name"]]["prefs"]["label"] = "purple"
                    q[e["name"]]["running"] = True
        self.edit(customise)
        os.unlink(self.log)
        rc, out = self.run_setup("--yes")
        self.assertGood(rc, out)
        self.check_end_state()
        q = self.qubes()
        for e in self.M["qube"]:
            if e["kind"] == "named-disposable":
                self.assertNotIn("/rw/leftover", q[e["dvm"]]["files"], "made again from scratch")
                for p in e.get("keep", []):
                    self.assertEqual(q[e["dvm"]]["files"][p].strip(), kept[p].strip(), "kept file carried over")
            else:
                self.assertEqual(q[e["name"]]["files"].get("/home/user/data"), "data", "app qube data kept")
        self.assertFalse([n for n in q if "-old" in n], "nothing set aside on a plain re-run")

    def test_wrong_kinds_kept_as_old(self):
        def wrong(q):
            for e in self.M["qube"]:
                if e["kind"] == "app":
                    q[e["name"]] = vm("StandaloneVM", files={"/home/user/x": "precious"})
                else:
                    q[e["name"]] = vm("AppVM", "fedora-44-minimal", prefs={"autostart": "True"})
                    q[e["name"] + "-old"] = vm("AppVM", "fedora-44-minimal")
        self.edit(wrong)
        rc, out = self.run_setup("--yes")
        self.assertGood(rc, out)
        q = self.qubes()
        for e in self.M["qube"]:
            if e["kind"] == "app":
                self.assertEqual(q[e["name"] + "-old"]["files"]["/home/user/x"], "precious")
            else:
                self.assertEqual(q[e["name"] + "-old-2"]["prefs"]["autostart"], "False")
        self.check_end_state()

    def test_in_use_stops_with_explanation(self):
        self.assertGood(*self.run_setup("--yes"))
        disp = [e for e in self.M["qube"] if e["kind"] == "named-disposable"]
        if not disp:
            self.skipTest("no named disposable")
        n = disp[0]["name"]
        self.edit(lambda q: q.update({"user-of-it": vm("AppVM", "fedora-44-minimal", prefs={"netvm": n})}))
        rc, out = self.run_setup("--yes")
        self.assertEqual(rc, 1)
        self.assertIn(f"couldn't remove {n}", out)
        self.assertIn("netvm for user-of-it", out)

    def test_cancel_changes_nothing(self):
        rc, out = self.run_setup(stdin="n\n")
        self.assertEqual(rc, 1)
        self.assertIn("cancelled, nothing changed", out)
        self.assertEqual(self.changing_calls(), [])

    def test_refuses_root(self):
        rc, out = self.run_setup("--yes", user="root")
        self.assertEqual(rc, 1)
        self.assertIn("not as root", out)


class StandaloneChecks(MakerChecks):
    PREFIX = "fedora-44-"

    def test_base_downloaded_once(self):
        self.assertGood(*self.run_setup("--yes"))
        self.assertGood(*self.run_setup("--yes"))
        self.assertEqual([c["args"] for c in self.calls("qvm-template")], [["install", "fedora-44-minimal"]])
        q = self.qubes()
        for e in self.M["qube"]:
            t = q[self.PREFIX + e["name"]]
            self.assertEqual(t["prefs"]["label"], "black")
            for p in e.get("packages", []):
                self.assertIn(p, t["installed"])


class TemplatingChecks(MakerChecks):
    PREFIX = "f44-"
    TEMPLATING = True

    def test_base_lists_and_conf(self):
        self.assertGood(*self.run_setup("--yes"))
        self.assertGood(*self.run_setup("--yes"))
        base = self.qubes()["fedora-44-minimal"]
        master = base["files"][f"{D}/master.dnf"]
        conf = self.read_conf()
        for e in self.M["qube"]:
            lst = [ln for ln in base["files"][f"{D}/{e['name']}.dnf"].splitlines() if not ln.startswith("#")]
            self.assertEqual(lst, e.get("packages", []))
            for p in e.get("packages", []):
                self.assertIn(p, base["installed"])
                self.assertEqual([w for w in master.replace("\n", " ").split() if w == p], [p],
                                 f"{p} in master.dnf exactly once")
            dv = f"dvm = {e['dvm']}" if e.get("dvm") else "dvm ="
            self.assertEqual(conf.count(f"[{self.PREFIX}{e['name']}]\n{dv}\nqube = {e['name']}\n"), 1)
        self.assertIn("[f44-sys-net]\ndvm = sys-net-dvm\nqube = sys-net", conf, "other sections kept")
        mt = self.calls("minimal-templating")[-1]
        self.assertFalse(mt["at"]["watcher"], "watcher paused during the build")
        self.assertNotIn("fedora-44-minimal", mt["at"]["running"], "base shut down before the build")
        self.assertTrue(self.full_state()["watcher"], "watcher enabled again")

    def test_build_failure_reenables_watcher(self):
        rc, out = self.run_setup("--yes", env={"MOCK_MT_RC": "1"})
        self.assertEqual(rc, 1)
        self.assertIn("build failed", out)
        self.assertTrue(self.full_state()["watcher"])

    def test_needs_minimal_templating(self):
        os.unlink(os.path.join(self.t, ".local/bin/minimal-templating"))
        rc, out = self.run_setup("--yes")
        self.assertEqual(rc, 1)
        self.assertIn("minimal templating is not set up", out)
        self.assertEqual(self.changing_calls(), [])


class TargetChecks:
    """A module that runs its setup.sh in an existing qube ([target])."""

    def target(self):
        t = self.M["target"]
        return "fedora-44-minimal" if t["qube"] == "@base" else t["qube"]

    def initial(self):
        t = self.M["target"]
        return {self.target(): vm("TemplateVM") if t["kind"] == "TemplateVM" else dvm("fedora-44-minimal")}

    def test_runs_in_target(self):
        rc, out = self.run_setup("--yes")
        self.assertGood(rc, out)
        self.assertEqual(self.roles(), [(self.target(), self.M["target"].get("args", ""))])
        self.assertFalse(self.qubes()[self.target()]["running"])

    def test_missing_target(self):
        self.edit(lambda q: q.pop(self.target()))
        rc, out = self.run_setup("--yes")
        self.assertEqual(rc, 1)
        self.assertIn("not found", out)

    def test_wrong_kind_target(self):
        self.edit(lambda q: q.update({self.target(): vm("StandaloneVM")}))
        rc, out = self.run_setup("--yes")
        self.assertEqual(rc, 1)
        self.assertEqual(self.roles(), [])


def make_classes():
    for folder in MODULES:
        m = load(folder)
        versions = m.get("versions", ["setup"])
        base = (unittest.skipUnless(HAVE_USER, "needs a 'user' account"),)
        if "dom0" in versions:
            mixin = TargetChecks if "target" in m else StandaloneChecks
            name = f"Dom0_{folder.replace('-', '_')}"
            cls = type(name, (mixin, Harness, unittest.TestCase),
                       {"SCRIPT": f"{folder}/setup-dom0.sh", "M": m})
            globals()[name] = base[0](cls)
        if "dom0-templating" in versions:
            name = f"Dom0Templating_{folder.replace('-', '_')}"
            cls = type(name, (TemplatingChecks, Harness, unittest.TestCase),
                       {"SCRIPT": f"{folder}/setup-dom0-templating.sh", "M": m})
            globals()[name] = base[0](cls)


make_classes()


@unittest.skipUnless(HAVE_USER and os.path.isdir(os.path.join(ROOT, "templating")),
                     "needs a 'user' account and templating/")
class AllInOne(Harness, unittest.TestCase):
    """setup-all-in-one.sh with every module answered yes."""
    SCRIPT = "setup-all-in-one.sh"
    TEMPLATING = True

    def patch(self, text):
        text = text.replace('[ "$(hostname)" = dom0 ]', "true").replace("[ -t 0 ]", "true")
        a = '''printf '%s\\n' "$F_MAIN"   > "$BIN/minimal-templating"'''
        assert a in text
        text = text.replace(a, f'ln -sf {MOCK} "$BIN/minimal-templating"')
        a = 'chmod 0755 "$BIN/minimal-templating" "$BIN/minimal-templating-listen"'
        assert a in text
        return text.replace(a, 'chmod 0755 "$BIN/minimal-templating-listen"')

    def setUp(self):
        super().setUp()
        os.unlink(os.path.join(self.t, ".local/bin/minimal-templating"))   # the script installs it
        os.unlink(self.conf)                                                # and writes the default

    def modules(self):
        return [(f, load(f)) for f in MODULES if load(f).get("question")]

    def answers(self, yes):
        return "".join("y\n" if yes else "n\n" for _ in self.modules()) + "n\n"

    def test_everything_yes(self):
        rc, out = self.run_setup(stdin=self.answers(True))
        self.assertEqual(rc, 0, out)
        q = self.qubes()
        ran = self.roles()
        base = q["fedora-44-minimal"]
        conf = self.read_conf()
        for folder, m in self.modules():
            if "target" in m:
                t = "fedora-44-minimal" if m["target"]["qube"] == "@base" else m["target"]["qube"]
                self.assertIn((t, m["target"].get("args", "")), ran, folder)
            for e in m.get("qube", []):
                self.assertIn(f"[f44-{e['name']}]", conf)
                self.assertIn(f"{D}/{e['name']}.dnf", base["files"])
                self.assertIn(e["name"], q)
                if "label" in e:
                    self.assertEqual(q[e["name"]]["prefs"]["label"], e["label"])
                if e.get("role"):
                    self.assertIn((e["name"], e["role"]), ran)
            for e in m.get("qube", []):
                for p in e.get("packages", []):
                    self.assertIn(p, base["files"][f"{D}/master.dnf"].split(), "module packages in master.dnf")
        self.assertTrue(self.full_state()["watcher"])

    def test_everything_no(self):
        rc, out = self.run_setup(stdin=self.answers(False))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.roles(), [])

    def test_rerun_offers_yes_for_modules_already_set_up(self):
        makers = [f for f, m in self.modules() if m.get("qube")]
        if not makers:
            self.skipTest("no module makes its own qubes")
        self.assertEqual(self.run_setup(stdin=self.answers(True))[0], 0)
        rc, out = self.run_setup(stdin="\n" * (len(self.modules()) + 1))   # Enter to every question
        self.assertEqual(rc, 0, out)
        for f, m in self.modules():
            self.assertIn(f"{f}={1 if m.get('qube') else 0}", out, "Enter keeps what is set up already")


if __name__ == "__main__":
    unittest.main(verbosity=2)
