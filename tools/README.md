# tools: how the setup scripts are made

Every script you download from this repository and run (`setup.sh`,
`setup-dom0.sh`, `setup-dom0-templating.sh`, `templating/install.sh`,
`setup-all-in-one.sh`) is **generated** by `tools/build.py` from plain source
files, which it copies in unchanged. So:

- to audit a script, read its sources (or check that the generated script
  contains them: `python3 tools/build.py --check`);
- to change one, change its sources and rebuild; never edit a generated script.

The same `tools/` folder is used in every repository that holds modules, so a
module can move from one to another as it is.

| File | |
| --- | --- |
| `build.py` | makes every generated script (`--check`: only compare) |
| `dom0-lib.sh` | the helpers every generated dom0 script includes, with the rules for qubes that already exist |
| `run-tests.sh` | every check: build up to date, syntax, the tests below, each module's own tests |
| `tests/mock-qvm` | stand-ins for dom0's tools (`qvm-*`, `minimal-templating`, `systemctl --user`, `sudo`) |
| `tests/test_modules.py` | runs every module's dom0 scripts and the all-in-one against the stand-ins, and checks the result matches each `module.toml` |

## A module

A module is a top-level folder with a `module.toml`:

```
<module>/
  module.toml          what the module makes or changes (its spec sheet)
  src/setup.sh.in      the script that runs inside qubes, one part ("role") per qube
  src/*                files installed inside qubes, embedded in setup.sh verbatim
  setup.sh                     generated: run inside a qube
  setup-dom0.sh                generated: dom0, everything, no minimal templating needed
  setup-dom0-templating.sh     generated: dom0, for a system with minimal templating
  tests/run-tests.sh           optional: the module's own tests
```

`setup-all-in-one.sh` (in the repository that holds `templating/`) asks one
question for every module that has a `question`.

## module.toml

[TOML](https://toml.io): `key = value` lines, `[sections]`, and `[[qube]]`
for each entry of a list. Two kinds of module:

**A module that sets something up in a qube that already exists** (Wi-Fi,
WireGuard, Flatpak):

```toml
title = "sys-net Wi-Fi persistence"
description = "a disposable sys-net that remembers your Wi-Fi networks"
question = "Wi-Fi login persistence for sys-net (installed in sys-net-dvm)?"   # all-in-one
order = 10                       # where its question comes in the all-in-one
versions = ["setup", "dom0"]     # which scripts to make
done = """                       # printed at the end ({qube} = that qube's name)
To save a network ...
"""

[target]
qube = "sys-net-dvm"             # "@base" = the base template
kind = "dvm"                     # dvm (disposable template) or TemplateVM
args = "--qube sys-net"          # passed to setup.sh
```

**A module that makes its own qubes** (Proton Drive sync):

```toml
title = "..."
description = "..."
question = "..."
order = 40
versions = ["setup", "dom0", "dom0-templating"]
done = """..."""

[[qube]]
name = "sys-proxy"
kind = "named-disposable"        # or "app"
dvm = "sys-proxy-dvm"            # named disposables only: its disposable template
packages = ["squid", "qubes-core-agent-networking"]   # what its template needs
label = "black"
dvm_label = "black"              # default black
memory = 300                     # MB at start
netvm = "none"                   # or a qube name; leave out for the Qubes default
firewall = ["dns", "tcp 443"]    # allow these, drop the rest; leave out for none
shutdown_timeout = 1800
menu = ["xfce4-terminal.desktop", "thunar.desktop"]
dvm_role = "proxy-dvm --proxy-qube {sys-proxy}"   # setup.sh role run in the dvm
role = "files"                   # setup.sh role run in the qube (app qubes)
keep = ["/rw/config/squid/domains.txt"]   # files in the dvm carried over when it's made again

[policy]
file = "50-files-proxy.policy"
lines = ["qubes.ConnectTCP +3128 {files} @default allow target={sys-proxy}"]
replaces = ["50-proton-drive-sync.policy"]   # earlier names, removed if found
```

`{name}` anywhere in `done`, `role`, `dvm_role` or `lines` becomes that qube's
name, so renaming a qube in a generated script's CONFIG block carries through.
In `src/setup.sh.in`, `@@PACKAGES:<qube>@@` becomes that qube's `packages`.

From this, the build makes:

| Script | What it does with the qube entries |
| --- | --- |
| `setup.sh` | the module's own script; the roles do the work inside each qube |
| `setup-dom0.sh` | clones `fedora-44-minimal` into `fedora-44-<qube>` templates and installs `packages`, makes the qubes, applies the settings, runs the roles, writes the policy |
| `setup-dom0-templating.sh` | installs `packages` in the base, adds them to `master.dnf`, writes `<qube>.dnf`, adds `[f44-<qube>]` to `templates.conf`, builds with `minimal-templating --only`, then the same settings, roles and policy |
| `setup-all-in-one.sh` | the same as `setup-dom0-templating.sh`, inside the one big run, so the packages stay in `master.dnf` every time |

A role that exits with code 3 means "done, with a warning it has printed";
the dom0 script carries on and says so at the end. Any other non-zero exit
stops it.

## Qubes that already exist

Every dom0 script follows the same rules (in `dom0-lib.sh`):

| Already there | What happens |
| --- | --- |
| the wrong kind of qube (say, `files` is a disposable) | kept as `<name>-old` (or `-old-2`, ...), never deleted; a new one is made |
| a named disposable or disposable template | removed and made again (nothing of yours is in them; `keep` files are carried over) |
| an app qube | kept with your data; its template and settings are set again |
| a template | kept and updated |
| a qube something else still uses (as netvm, template, ...) | the script stops and names what uses it |

The sys- qubes of minimal templating itself (`sys-net`, `sys-firewall`, ...)
are other qubes' network, so they can't simply be removed: the switch-over in
`minimal-templating` copies them aside and re-points what used them instead.

## Adding a module

1. Copy a module folder of the same kind and rename it.
2. Edit `module.toml`, `src/setup.sh.in` and the files in `src/`.
3. `python3 tools/build.py`, then `bash tools/run-tests.sh`.
