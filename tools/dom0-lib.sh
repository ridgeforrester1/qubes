# ------------------------------------------------------------------ shared dom0 helpers
# (tools/dom0-lib.sh: the same in every dom0 script built by tools/build.py)
#
# How a qube a module defines is treated when one of that name already exists:
#   wrong kind (e.g. 'files' exists as a disposable)
#       -> kept as <name>-old (or -old-2, ...), never deleted: it may hold data.
#          A fresh one of the right kind is made.
#   right kind, holds nothing of yours (disposable templates, named disposables)
#       -> removed and made again, so it is exactly what the module defines.
#          Files the module lists as yours (e.g. an allow-list) are carried over.
#   right kind, holds your data (app qubes such as 'files') or is a template
#       -> kept; its settings are set to what the module defines.
# Files the modules install inside qubes are overwritten; your own config files
# are kept.

say()  { echo "$*"; }
warn() { echo "   WARN $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }
ask() {       # ask "question" -> 0 for yes (default no)
    local a
    read -r -p "$1 [y/N] " a
    [[ $a =~ ^[Yy]([Ee][Ss])?$ ]]
}
ask_yes() {   # ask_yes "question" -> 0 for yes (default yes)
    local a
    read -r -p "$1 [Y/n] " a
    ! [[ $a =~ ^[Nn]([Oo])?$ ]]
}
in_vm() { qvm-run --user root --pass-io --no-gui "$1" "$2"; }
push() {   # push <qube> <path> <mode>   (content on stdin; written atomically, owned by root)
    in_vm "$1" "mkdir -p \"\$(dirname '$2')\" && cat > '$2.new' && chown root:root '$2.new' && chmod $3 '$2.new' && mv -f '$2.new' '$2'"
}
exists()  { qvm-check --quiet "$1" 2>/dev/null; }
running() { qvm-check --quiet --running "$1" 2>/dev/null; }
klass()   { qvm-prefs "$1" klass; }
halt() { if exists "$1" && running "$1"; then say "   shutting down $1"; qvm-shutdown --wait "$1"; fi; }
kind() {   # kind <qube> -> TemplateVM | dvm | DispVM | AppVM | StandaloneVM | ...
    local k; k=$(klass "$1")
    if [ "$k" = AppVM ] && [ "$(qvm-prefs "$1" template_for_dispvms)" = True ]; then echo dvm; else echo "$k"; fi
}
describe() { case $1 in dvm) echo "disposable template" ;; DispVM) echo "named disposable" ;;
                        AppVM) echo "app qube" ;; TemplateVM) echo "template" ;; *) echo "$1" ;; esac; }
valid_name() { [[ $1 =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "invalid qube name: $1"; }

set_aside() {   # set_aside <qube>: keep it as <qube>-old (clone, then remove the original)
    local q=$1 n=$1-old i=2 err
    while exists "$n"; do n=$q-old-$i; i=$((i + 1)); done
    halt "$q"
    qvm-clone "$q" "$n" >/dev/null
    qvm-prefs "$n" autostart False 2>/dev/null || true
    if ! err=$(qvm-remove --force "$q" 2>&1); then
        die "kept a copy of $q as $n, but couldn't remove $q itself: $err
Something still uses it (as its template, netvm or default disposable). Change that in
Qube Manager, run 'qvm-remove $q', then run this script again."
    fi
    say "   $q was a $(describe "$(kind "$n")"): kept as $n (autostart off; delete it once you don't need it)"
}

remove_qube() {   # remove_qube <qube>: for qubes that hold nothing of yours
    local err
    halt "$1"
    err=$(qvm-remove --force "$1" 2>&1) || die "couldn't remove $1 to make it again: $err
Something still uses it (as its template, netvm or default disposable). Change that in
Qube Manager, then run this script again."
    say "   removed the old $1 (made again below)"
}

make_way() {   # make_way <qube> <kind> recreate|keep
    # Gets an existing <qube> out of the way, or not, by the rules at the top.
    exists "$1" || return 0
    local k; k=$(kind "$1")
    if [ "$k" != "$2" ]; then
        set_aside "$1"
    elif [ "$3" = recreate ]; then
        remove_qube "$1"
    else
        halt "$1"
    fi
}

save_file() {   # save_file <qube> <path>: print that file from an existing AppVM/dvm, if it has it
    exists "$1" && [ "$(klass "$1")" = AppVM ] || return 0
    in_vm "$1" "cat $2" 2>/dev/null || true
    halt "$1" >/dev/null
}

restore_file() {   # restore_file <qube> <path> <content>: put a saved file back (if there was one)
    [ -n "$3" ] || return 0
    printf '%s\n' "$3" | push "$1" "$2" 0644
    say "   kept your $2 in $1"
}

make_template() {   # make_template <template> [packages...]: clone from $BASE if missing, install
    local t=$1; shift
    if exists "$t"; then
        say "   $t: exists, updating"
    else
        qvm-clone "$BASE" "$t" >/dev/null
        qvm-prefs "$t" label black
        say "   $t: cloned from $BASE"
    fi
    if [ $# -gt 0 ]; then in_vm "$t" "dnf -y install $*"; fi
    qvm-shutdown --wait "$t"
}

write_policy() {   # write_policy <path> <line>...   (sudo; replaces the file)
    local p=$1; shift
    printf '%s\n' "$@" | sudo tee "$p" >/dev/null
    sudo chmod 0644 "$p"
    say "   wrote $p"
    local others
    others=$(grep -lF -- "${*: -1}" /etc/qubes/policy.d/*.policy 2>/dev/null | grep -vx "$p" || true)
    [ -z "$others" ] || warn "other policy files have the same line (check them): $others"
}

remove_old_policy() {   # remove_old_policy <path>: a file an earlier version wrote
    if [ -e "$1" ]; then sudo rm -f "$1"; say "   removed $1 (earlier name of the same policy)"; fi
}

set_menu() {   # set_menu <qube> <desktop files...>
    local q=$1; shift
    if qvm-features "$q" menu-items "$*" && qvm-appmenus --update --force "$q" >/dev/null 2>&1; then
        say "   $q: app menu $*"
    else
        warn "couldn't set $q's app menu: add the apps in Qube Settings > Applications"
    fi
}

set_firewall() {   # set_firewall <qube> <rule>...: allow these, drop everything else
    local q=$1 r; shift
    qvm-firewall "$q" reset
    qvm-firewall "$q" del --rule-no 0
    for r in "$@"; do
        # shellcheck disable=SC2086
        qvm-firewall "$q" add action=accept $r
    done
    qvm-firewall "$q" add action=drop
}

run_setup() {   # run_setup <script text> <qube> [args...]: a module's setup.sh, as root (starts the qube)
    local s=$1 q=$2; shift 2
    printf '%s\n' "$s" | in_vm "$q" "cat > /tmp/module-setup.sh && chmod 0700 /tmp/module-setup.sh"
    in_vm "$q" "bash /tmp/module-setup.sh $*"
}

# ---- minimal templating
conf_base() { awk -F'=' '/^[[:space:]]*base[[:space:]]*=/{gsub(/[[:space:]]/,"",$2); print $2; exit}' "$CONF"; }

pause_watcher() {   # pause the rebuild watcher until this script exits (even after an error)
    if systemctl --user is-enabled --quiet "$UNIT" 2>/dev/null; then
        systemctl --user disable --now "$UNIT" 2>/dev/null || true
        trap 'systemctl --user enable --now "$UNIT" && echo "== watcher enabled again"' EXIT
        say "== watcher paused"
    fi
}

add_to_master() {   # add_to_master <why> <packages...>: append the ones master.dnf lacks (base running)
    local why=$1 master p added=""; shift
    master=$(in_vm "$BASE" "cat $D/master.dnf") || die "$BASE has no $D/master.dnf: run setup-all-in-one.sh first"
    for p in "$@"; do
        printf '%s\n' "$master" | sed 's/#.*//' | tr -s '[:space:]' '\n' | grep -qxF -- "$p" || added="$added $p"
    done
    [ -n "$added" ] || return 0
    # shellcheck disable=SC2086
    { printf '%s\n' "$master"; printf '\n# %s\n' "$why"; printf '%s\n' $added; } | push "$BASE" "$D/master.dnf" 0644
    say "   added to master.dnf:$added"
}

write_list() {   # write_list <qube> <why> <packages...>: its whitelist in the base (replaced)
    local q=$1 why=$2; shift 2
    { echo "# $q: $why"; printf '%s\n' "$@"; } | push "$BASE" "$D/$q.dnf" 0644
    say "   wrote $q.dnf: $*"
}

set_section() {   # set_section <template> <dvm> <qube>: replace that section of templates.conf
    local tmp; tmp=$(mktemp)
    # drop the old section's header and settings (comments stay), then append the new one
    awk -v s="[$1]" '
        { h = $0; gsub(/[[:space:]]/, "", h) }
        /^[[:space:]]*\[/ { inside = (h == s); if (inside) next }
        inside && !/^[[:space:]]*#/ { next }
        { print }' "$CONF" > "$tmp"
    sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$tmp"     # no trailing blank lines
    printf '\n[%s]\n%s\nqube = %s\n' "$1" "dvm =${2:+ $2}" "$3" >> "$tmp"
    cat "$tmp" > "$CONF"; rm -f "$tmp"
    say "   [$1] dvm = ${2:-(blank)}, qube = $3"
}
