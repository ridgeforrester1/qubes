# Qubes configuration scripts

Scripts for my [Qubes OS](https://www.qubes-os.org/) Set-up published here on the off chance they help others. 
The main one, **minimal templating**, builds one stripped-down template
per qube from a single base template, so each qube carries only the packages it
needs while updates are downloaded once, into the base. Three smaller modules
make disposable sys- qubes practical, and each works on its own:

1. **Minimal templating**: one minimal template per qube, rebuilt automatically after every base update.
2. **sys-net Wi-Fi persistence**: a disposable sys-net that remembers your Wi-Fi networks.
3. **sys-vpn WireGuard autoconnect**: a disposable sys-vpn that brings up your WireGuard VPN at boot.
4. **Flatpak integration**: Flatpak apps in templates, updated by the Qubes updater.

Written for **Qubes OS 4.3** with **fedora-44-minimal** as the base template.

> These scripts run as root in dom0 and in your templates. Read them before
> running them; that is what this repository is for. They have been used on one
> system; treat them as a starting point, not a finished product.

> **AI disclosure:** these scripts and this documentation were written with
> substantial help from a large language model, then tested and adjusted by the
> maintainer on their own Qubes system. That makes reviewing them before use all
> the more important.

## Contents

| Part | Runs in | What it does |
| --- | --- | --- |
| [`templating/`](templating) | dom0 + base template | Minimal templating: the main part of this repository |
| [`sys-net-wifi/`](sys-net-wifi) | net qube's disposable template | Restores saved Wi-Fi networks in a disposable sys-net at boot |
| [`sys-vpn-wireguard/`](sys-vpn-wireguard) | VPN qube's disposable template | Imports WireGuard configs into a disposable sys-vpn at boot |
| [`flatpak/`](flatpak) | any template | Flatpak, Flathub, automatic app updates, updates-proxy settings |
| [`setup-all-in-one.sh`](setup-all-in-one.sh) | dom0 | Minimal templating plus any of the three modules in one run |
| [`tools/build.py`](tools/build.py) | anywhere | Regenerates every installer from the plain source files |

## 1. Minimal templating

![Updates go into the base once; every qube gets a stripped copy. The Qubes updater updates fedora-44-minimal, the base; when it shuts down, the watcher in dom0 rebuilds. Each f44-* template is a thin clone of the base with its own list removed, each disposable template sits on its f44-* template, and each sys- qube is a named disposable on its disposable template.](docs/templating.svg)

- **One base, updated once.** Every package you add goes into the base and is
  listed in `master.dnf`.
- **One template per qube.** Each `f44-*` template is a thin LVM snapshot of the
  base (near-zero extra disk), with every `master.dnf` package its own
  `<qube>.dnf` list does not keep removed, along with dependencies nothing else
  needs. Packages that came with the base itself are never removed.
- **Automatic rebuilds.** A small dom0 watcher listens for the base shutting
  down after an update and rebuilds every `f44-*` template from it, two at a
  time by default (see [Parallel builds](#parallel-builds)). Running qubes keep
  their version until restarted.
- **No traces.** After stripping, each `f44-*` template has the mechanism, the
  lists, the dnf log and its journal deleted.
- **dom0 stays in charge.** Which templates and qubes exist is decided only by
  `templates.conf` in dom0; output from templates is treated as untrusted text.

### Install

```sh
# in an app qube: get the repository, then in dom0:
qvm-run --pass-io <qube> 'cat ~/qubes/templating/install.sh' > ~/install.sh
less ~/install.sh
bash ~/install.sh
```

It asks one question first (whether to do the switch-over), then runs to the
end on its own:

1. Downloads `fedora-44-minimal` if missing, runs `dnf upgrade`, installs `master.dnf`.
2. Writes the scripts and lists into the base.
3. Builds every `f44-*` template and disposable template. Your qubes keep running.
4. Switch-over, if chosen: **shuts down all qubes**, points each disposable
   template at its `f44-*` template, and replaces each app-qube sys- qube with a
   named disposable of the same name (the old one is kept as `<name>-old`, with
   netvm, provides-network, autostart, memory, services, firewall rules and PCI
   devices copied across), then starts them again.
5. Enables the watcher.

Save your work in every qube before answering yes to the switch-over. Re-running
is safe; your `templates.conf` is never overwritten.

### Configuration

`~/.config/minimal-templating/templates.conf` (dom0) lists the stacks to build;
its header documents every option, including how to add a qube and how to share
one template between identical stacks. The default:

```ini
[general]
base = fedora-44-minimal
parallel = 2

[f44-sys-net]
dvm = sys-net-dvm
qube = sys-net
# ... sys-firewall, sys-killswitch, sys-vpn, sys-usb
```

| `dvm` | `qube` | Result |
| --- | --- | --- |
| set | set | `qube` is a named disposable on `dvm` |
| blank | set | `qube` is a normal app qube on the template |
| set | blank | `dvm` is for unnamed disposables (`dispNNNN`) |

The package lists live in the base, in `/etc/minimal-templating/`:
`master.dnf` (everything added on top of the base), `<qube>.dnf` (what that qube
keeps) and optionally `<qube>.flatpak` (Flatpak apps it keeps). The defaults are
in [`templating/lists/`](templating/lists). They include Intel Wi-Fi firmware
(`iwlwifi-mvm-firmware`, `iwlbluetooth-firmware`) for sys-net: swap these for
your own hardware's firmware (`lspci`, then `dnf search firmware`).

### Parallel builds

`parallel` in `[general]` sets how many templates build at once (1 to 4;
default 2, also used when the line is missing):

- **Staggered:** only one template starts up at a time, so one boots while
  another runs dnf. A rebuild of five templates takes about a third less time.
- **Memory-safe:** Qubes only starts a qube if it can give it memory while every
  running qube keeps what it needs. If it can't for a second build, that build
  waits for the first to finish, and the rest continue one at a time.
- **Readable logs:** each template's lines are collected in memory while it
  builds and written to the log as one block when it finishes; the journal
  shows a one-line "building" note when each starts.
- **Independent:** each template is its own clone and the base stays shut down,
  so a failure in one build can't affect another. The summary and the single
  notification come once every build has finished.

Set `parallel = 1` to never run two building templates at once: rebuilds take
longer, but use at most one template's worth of memory (a few hundred MB) and
the log reads strictly in order as it happens. Above 2 gains little.

### Commands (dom0)

| Command | What it does |
| --- | --- |
| `minimal-templating --status` | Every stack and its state, and the parallel setting; starts nothing |
| `minimal-templating --preview [--only f44-x]` | Dry run in the base: what each list would remove |
| `minimal-templating [--only f44-x]` | Rebuild now |
| `minimal-templating --switch` | Move everything onto its stack (shuts down all qubes; asks first) |
| `systemctl --user disable --now minimal-templating-listen.service` | Turn automatic rebuilds off |

The watcher only reacts to the Qubes updater changing the base. After editing the
base by hand, run `minimal-templating` yourself.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| Base updated, nothing rebuilt | `systemctl --user enable --now minimal-templating-listen.service` (`preset: enabled` does not mean it is on) |
| `apply: FAIL allowlisted packages were removed as dependents: X` | Add the package dnf removed (shown above that line) to the qube's `.dnf` |
| A qube works on the base but not on its `f44-*` template | `minimal-templating --preview --only f44-x` shows exactly what was removed |
| A boot script works on the base but not on `f44-*` | It uses `sudo`; the derived templates have no passwordless root. Boot scripts already run as root |
| Templates can't download (curl error 56) | The updates-proxy policy points at a qube not running `qubes-updates-proxy`; check `grep -h UpdatesProxy /etc/qubes/policy.d/*.policy` |
| dom0 updates fail through sys-firewall | Keep `qubes-core-agent-dom0-updates` in `sys-firewall.dnf` (in the defaults) |

## 2. sys-net Wi-Fi persistence

A disposable sys-net forgets every network at shutdown. This module keeps
`.nmconnection` files in the disposable template and restores them early in
each boot, before NetworkManager starts. It does not need minimal templating.

Run as root in the **disposable template** (e.g. `sys-net-dvm`), not the disposable:

```sh
sudo bash sys-net-wifi/setup.sh [--qube sys-net]
# or from dom0, after copying setup.sh into the disposable template:
qvm-run -u root -p sys-net-dvm 'bash /home/user/QubesIncoming/<qube>/setup.sh'
```

It installs `/rw/config/rc.local-early.d/wifi-persistence.rc` and creates
`/usr/local/etc/nm-connections/` (root only, 0700). To save a network after
joining it in sys-net, run in dom0 (the file is piped through, never shown):

```sh
f='HomeWiFi.nmconnection'
qvm-run -u root --pass-io sys-net "cat '/etc/NetworkManager/system-connections/$f'" |
  qvm-run -u root --pass-io sys-net-dvm "umask 077; cat > '/usr/local/etc/nm-connections/$f'"
```

Only the qube named by `--qube` loads the networks; any other disposable based
on the same template has the files deleted at boot.

## 3. sys-vpn WireGuard autoconnect

Keeps WireGuard configs in the VPN qube's disposable template; at each boot the
disposable imports them with `nmcli`, deletes its copies, and keeps one
connection up. It does not need minimal templating.

```sh
sudo bash sys-vpn-wireguard/setup.sh [--qube sys-vpn] [--default wg-nl1]
```

It installs `/rw/config/rc.local.d/vpn-autoconnect.rc` and creates
`/usr/local/etc/wg-configs/` (root only, 0700). Add a config from dom0:

```sh
qvm-run --pass-io <source qube> 'cat ~/wg-nl1.conf' |
  qvm-run -u root --pass-io sys-vpn-dvm 'umask 077; cat > /usr/local/etc/wg-configs/wg-nl1.conf'
```

File names become interface names, so keep them to 15 characters. `--default`
picks the config to bring up; without it, one is chosen at random each boot.
If you use a killswitch qube, allow each config's endpoint there.

## 4. Flatpak integration

Run as root in a **template**:

```sh
sudo bash flatpak/setup.sh
```

It installs `flatpak`, adds Flathub system-wide through the updates proxy, and
adds two files:

- `/etc/qubes/post-install.d/05-flatpak-update.sh`, which runs `flatpak upgrade`
  after each dnf transaction in the template, so the Qubes updater updates
  Flatpak apps too (only when dnf actually changed something).
- `/etc/profile.d/flatpak-proxy.sh`, which points shells in the template at the
  updates proxy.

Install apps system-wide afterwards:

```sh
sudo env http_proxy=http://127.0.0.1:8082 https_proxy=http://127.0.0.1:8082 \
  flatpak install --system -y flathub org.signal.Signal
```

With minimal templating, `setup.sh` also adds `flatpak` to `master.dnf`. A qube
that keeps Flatpak apps lists `flatpak` in its `<qube>.dnf` and its app IDs in
`<qube>.flatpak`; every other `f44-*` template has the apps, runtimes and
Flatpak itself removed. The update hook is deleted from derived templates before
they are stripped, so Flatpak downloads only ever happen in the base.

Both files check `qubesdb-read /type`; if that prints nothing in your template
(it should print `TemplateVM`), use `/qubes-vm-type` instead.

## All-in-one setup

[`setup-all-in-one.sh`](setup-all-in-one.sh) does minimal templating and any of
the three modules in one run, from dom0:

```sh
qvm-run --pass-io <qube> 'cat ~/qubes/setup-all-in-one.sh' > ~/setup-all-in-one.sh
less ~/setup-all-in-one.sh
bash ~/setup-all-in-one.sh
```

It asks four questions first (Wi-Fi, WireGuard, Flatpak, switch-over), then does
the templating install above, running `flatpak/setup.sh` in the base and the
chosen module `setup.sh` scripts in `sys-net-dvm` and `sys-vpn-dvm`. It runs the
modules' own setup scripts unchanged, so there is one code path to audit.

## Auditing

The `setup.sh` scripts and the two dom0 installers are **generated**: each
embeds the plain files beside it verbatim. Audit the plain files, then confirm
the generated scripts contain exactly those:

```sh
python3 tools/build.py --check     # exit 1 if any generated script differs from its sources
```

CI runs the same check on every push and pull request, plus a syntax check of
every script.

## Layout

```
templating/
  install.sh                   generated: minimal templating installer (dom0)
  minimal-templating           dom0: build, status, preview, switch-over
  minimal-templating-listen    dom0: the watcher
  minimal-templating-listen.service
  templates.conf               dom0: default config, documented in its header
  apply                        base: strips a cloned template (run by dom0)
  lists/*.dnf                  base: master.dnf and one list per qube
sys-net-wifi/
  setup.sh                     generated
  wifi-persistence.rc
sys-vpn-wireguard/
  setup.sh                     generated
  vpn-autoconnect.rc
flatpak/
  setup.sh                     generated
  05-flatpak-update.sh
  flatpak-proxy.sh
setup-all-in-one.sh            generated: templating + modules (dom0)
tools/build.py                 regenerates the generated scripts
docs/templating.svg            the diagram above
```

## Licence

[MIT](LICENSE), © 2026 ridgeforrester1. Provided as is, with no warranty of any
kind: these scripts change templates, qubes and dom0 settings, and you use them
entirely at your own risk. Back up anything you care about first.
