"""Runs a generated dom0 script against mocked Qubes tools (tools/tests/mock-qvm).
Shared by tools/tests/test_modules.py and any module's own dom0 tests."""
import json
import os
import pwd
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MOCK = os.path.join(HERE, "mock-qvm")
TOOLS = ["qvm-check", "qvm-prefs", "qvm-run", "qvm-create", "qvm-clone", "qvm-remove",
         "qvm-template", "qvm-shutdown", "qvm-firewall", "qvm-features", "qvm-appmenus",
         "systemctl", "sudo"]
D = "/etc/minimal-templating"
HAVE_USER = any(p.pw_name == "user" for p in pwd.getpwall())

MASTER = """# packages added on top of fedora-44-minimal
xfce4-terminal
qubes-core-agent-passwordless-root
Thunar
qubes-core-agent-networking
"""
CONF = """# templates.conf - header comments
[general]
base = fedora-44-minimal
parallel = 2

[f44-sys-net]
dvm = sys-net-dvm
qube = sys-net
"""


def vm(klass, template=None, **extra):
    return {"klass": klass, "template": template, "prefs": extra.pop("prefs", {}), "features": {},
            "firewall": [], "running": False, "files": extra.pop("files", {}), "installed": [], **extra}


def dvm(template, **extra):
    prefs = extra.pop("prefs", {})
    prefs["template_for_dispvms"] = "True"
    return vm("AppVM", template, prefs=prefs, **extra)


class Harness:
    """Mixin for unittest.TestCase. Set SCRIPT (path from the repo root) and
    define initial() -> {qube: state}. TEMPLATING = True also sets up a mocked
    minimal templating (templates.conf, minimal-templating, master.dnf)."""
    SCRIPT = None
    TEMPLATING = False
    ENV = {}

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="dom0-test.")
        os.chmod(self.t, 0o777)
        self.bindir = os.path.join(self.t, "bin")
        os.makedirs(self.bindir)
        # a copy inside the test folder: the repository itself may be somewhere
        # the 'user' account can't reach (as on GitHub's runners)
        self.mock = os.path.join(self.t, "mock-qvm")
        shutil.copy(MOCK, self.mock)
        os.chmod(self.mock, 0o755)
        for tool in TOOLS:
            os.symlink(self.mock, os.path.join(self.bindir, tool))
        self.policy_dir = os.path.join(self.t, "etc/qubes/policy.d")
        os.makedirs(self.policy_dir)
        os.chmod(self.policy_dir, 0o777)
        with open(os.path.join(ROOT, self.SCRIPT)) as f:
            text = f.read().replace("/etc/qubes/policy.d", self.policy_dir)
        self.script = os.path.join(self.t, os.path.basename(self.SCRIPT))
        with open(self.script, "w") as f:
            f.write(self.patch(text))
        os.chmod(self.script, 0o755)
        self.state = os.path.join(self.t, "state.json")
        self.log = os.path.join(self.t, "calls.log")
        qubes = {"sys-firewall": vm("AppVM", "fedora-44-minimal")}
        if self.TEMPLATING:
            conf_dir = os.path.join(self.t, ".config/minimal-templating")
            os.makedirs(conf_dir)
            self.conf = os.path.join(conf_dir, "templates.conf")
            with open(self.conf, "w") as f:
                f.write(CONF)
            mtbin = os.path.join(self.t, ".local/bin")
            os.makedirs(mtbin)
            os.symlink(self.mock, os.path.join(mtbin, "minimal-templating"))
            qubes["fedora-44-minimal"] = vm("TemplateVM", files={f"{D}/master.dnf": MASTER})
        qubes.update(self.initial())
        self.set_state(qubes, watcher=self.TEMPLATING)
        if HAVE_USER:
            uid = pwd.getpwnam("user").pw_uid
            for root, dirs, files in os.walk(self.t):
                for n in dirs + files:
                    os.lchown(os.path.join(root, n), uid, -1)

    def patch(self, text):
        return text

    def initial(self):
        return {}

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    # ------------------------------------------------------------- state
    def set_state(self, qubes, **extra):
        with open(self.state, "w") as f:
            json.dump({"qubes": qubes, **extra}, f)
        os.chmod(self.state, 0o666)

    def full_state(self):
        with open(self.state) as f:
            return json.load(f)

    def qubes(self):
        return self.full_state()["qubes"]

    def edit(self, fn):
        st = self.full_state()
        fn(st["qubes"])
        self.set_state(st.pop("qubes"), **st)

    def calls(self, tool=None):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            cs = [json.loads(line) for line in f]
        return [c for c in cs if tool is None or c["tool"] == tool]

    def roles(self):
        return [(c["name"], " ".join(c["role"])) for c in self.calls("qvm-run") if "role" in c]

    def policy(self, name):
        p = os.path.join(self.policy_dir, name)
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read()

    def read_conf(self):
        with open(self.conf) as f:
            return f.read()

    # ------------------------------------------------------------- running
    def run_setup(self, *args, user="user", stdin=None, env=None):
        e = {"PATH": self.bindir + ":/usr/bin:/bin", "MOCK_STATE": self.state, "MOCK_LOG": self.log,
             "HOME": self.t, **self.ENV}
        e.update(env or {})
        cmd = ["bash", self.script, *args]
        if user != "root":
            cmd = [shutil.which("runuser") or "/usr/sbin/runuser", "-u", user, "--", "env",
                   *[f"{k}={v}" for k, v in e.items()], *cmd]
        if os.path.exists(self.log):
            os.chmod(self.log, 0o666)
        r = subprocess.run(cmd, env=e, input=stdin, capture_output=True, text=True, timeout=180)
        return r.returncode, r.stdout + r.stderr

    def assertGood(self, rc, out):
        self.assertEqual(rc, 0, out)
        self.assertIn("Done.", out)

    def changing_calls(self):
        return [c for c in self.calls() if c["tool"] not in ("qvm-check", "qvm-prefs")
                or (c["tool"] == "qvm-prefs" and len(c["args"]) == 3)]
