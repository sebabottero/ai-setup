#!/usr/bin/env python3
"""Leave a clean Mac working like this one: tools first, then ./install.sh.

Each layer lists what it needs in <layer>/bootstrap.json (brew, steps, path, logins, manual). Only the chosen layers
are installed, so `--only core` skips the toolchain of any other layer. Safe to repeat: what is there is skipped.
Needs Homebrew first (https://brew.sh) and python3 (xcode-select --install). Secrets are never stored: logins are a checklist.
Usage: ./bootstrap.py [--dry-run | --check] [--only core | --with <layer>] [--layers-dir DIR]
  --dry-run  show what would be installed, change nothing
  --check    compare this Mac with the manifests (also lists brew leaves nobody registered); exit 1 if something is missing
"""
import argparse, json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import layers as layerlib

MARK = "# ai-setup bootstrap"
BREW = next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(p)), shutil.which("brew"))


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def choose_layers(args, home):
    present = layerlib.present(ROOT)
    for name in (args.only or "").split(",") + (args.with_ or "").split(","):
        if name.strip() and name.strip() not in present:
            sys.exit(f"unknown layer or no folder for it: {name.strip()}. Layers: {', '.join(present)}")
    if args.only:
        chosen = [n.strip() for n in args.only.split(",") if n.strip()]
    else:
        saved = read_json(os.path.join(home, ".ai-setup-profile")).get("layers")
        chosen = [l for l in present if saved is None or l in saved]
        chosen += [n.strip() for n in (args.with_ or "").split(",") if n.strip()]
    return [l for l in present if l in ["core"] + chosen]


def manifest(chosen):
    """The manifests of the chosen layers merged: lists are concatenated without repeats, expect is a dict."""
    out = {"taps": [], "formulas": [], "steps": [], "path": [], "logins": [], "manual": [], "expect": {}}
    for layer in chosen:
        m = read_json(os.path.join(layerlib.layer_dir(ROOT, layer), "bootstrap.json"))
        brew = m.get("brew", {})
        for key, items in (("taps", brew.get("taps", [])), ("formulas", brew.get("formulas", [])),
                           ("steps", m.get("steps", [])), ("path", m.get("path", [])),
                           ("logins", m.get("logins", [])), ("manual", m.get("manual", []))):
            out[key] += [i for i in items if i not in out[key]]
        out["expect"].update(m.get("expect", {}))
    return out


def brew_installed():
    r = sh(f"'{BREW}' list --formula") if BREW else None
    return set(r.stdout.split()) if r and r.returncode == 0 else set()


def brew_taps():
    r = sh(f"'{BREW}' tap") if BREW else None
    return set(r.stdout.split()) if r and r.returncode == 0 else set()


def short(formula):
    return formula.rsplit("/", 1)[-1]


def path_block(entries):
    return "\n".join([MARK] + [f'export PATH="{e}:$PATH"' for e in entries])


def path_missing(entries, home):
    try:
        with open(os.path.join(home, ".zprofile")) as f:
            text = f.read()
    except OSError:
        text = ""
    return [e for e in entries if f'export PATH="{e}:$PATH"' not in text]


def report(manifest_, home):
    """[(label, ok)] for every item of the manifest, without changing anything."""
    rows = []
    if not BREW:
        rows.append(("Homebrew (https://brew.sh)", False))
    have, taps = brew_installed(), brew_taps()
    rows += [(f"brew tap {t}", t in taps) for t in manifest_["taps"]]
    rows += [(f"brew {f}", short(f) in have) for f in manifest_["formulas"]]
    rows += [(s["name"], sh(s["check"], env={**os.environ, "HOME": home}).returncode == 0) for s in manifest_["steps"]]
    rows += [(f"PATH en ~/.zprofile: {e}", e not in path_missing([e], home)) for e in manifest_["path"]]
    return rows


def warn_versions(manifest_):
    for formula, want in manifest_["expect"].items():
        r = sh(f"'{BREW}' list --versions {formula}") if BREW else None
        got = r.stdout.split()[-1] if r and r.returncode == 0 and r.stdout.split() else None
        if got and got != want:
            print(f"⚠ {formula}: tested with {want}, installed {got}. brew cannot install old versions: "
                  f"if something breaks, check the guard plugin.")


def run_step(label, cmd, dry):
    print(f"  → {label}")
    if dry:
        return True
    r = subprocess.run(cmd, shell=True)
    if r.returncode != 0:
        print(f"  ✗ failed: {label} (command: {cmd})")
    return r.returncode == 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--only")
    p.add_argument("--with", dest="with_")
    p.add_argument("--layers-dir", action="append", default=[], metavar="DIR",
                   help="folder that holds more layers (e.g. a private repo); passed on to install.sh, repeatable")
    p.add_argument("--home", default=os.path.expanduser("~"), help="another home (for testing)")
    args = p.parse_args()
    home = args.home
    layerlib.use_layers_dirs(args.layers_dir, home)
    chosen = choose_layers(args, home)
    m = manifest(chosen)
    print(f"layers: {', '.join(chosen)}")
    rows = report(m, home)

    if args.check:
        for label, ok in rows:
            print(f"  {'✓' if ok else '✗ missing'}  {label}")
        registered = {short(f) for f in m["formulas"]}
        known = {short(f) for l in layerlib.present(ROOT) for f in manifest([l])["formulas"]}
        r = sh(f"'{BREW}' leaves") if BREW else None
        extra = sorted({short(l) for l in (r.stdout.split() if r and r.returncode == 0 else [])} - registered - known)
        if extra:
            print(f"\nInstalled with brew and not listed in any bootstrap.json: {', '.join(extra)}")
        warn_versions(m)
        sys.exit(0 if all(ok for _, ok in rows) else 1)

    if not BREW:
        print("✗ Homebrew is missing. Install it from https://brew.sh and run ./bootstrap.py again")
        if not args.dry_run:
            sys.exit(1)
    for label, ok in rows:
        print(f"  {'✓' if ok else '·'} {label}")
    failed = False
    pending = {label for label, ok in rows if not ok}
    for t in m["taps"]:
        if f"brew tap {t}" in pending:
            failed |= not run_step(f"brew tap {t}", f"'{BREW}' tap {t}", args.dry_run)
    for f in m["formulas"]:
        if f"brew {f}" in pending:
            failed |= not run_step(f"brew install {f}", f"'{BREW}' install {f}", args.dry_run)
    for s in m["steps"]:
        if s["name"] in pending:
            failed |= not run_step(s["name"], s["run"], args.dry_run)
    missing = path_missing(m["path"], home)
    if missing:
        print(f"  → add to PATH in ~/.zprofile: {', '.join(missing)}")
        if not args.dry_run:
            with open(os.path.join(home, ".zprofile"), "a") as f:
                f.write("\n" + path_block(missing) + "\n")
    if failed:
        sys.exit("Something failed above: fix it and run ./bootstrap.py again (what is already installed is skipped).")

    flags = ["--only", ",".join(chosen)] if args.only else []
    flags += [x for d in args.layers_dir for x in ("--layers-dir", d)]
    install = [os.path.join(ROOT, "install.sh")] + flags + (["--dry-run"] if args.dry_run else [])
    print("\n→ ./install.sh " + " ".join(install[1:]))
    if not args.dry_run and subprocess.run(install).returncode != 0:
        sys.exit("install.sh failed: the tests or the installation did not pass (see above).")

    warn_versions(m)
    print("\nBy hand now (this script never stores or touches secrets):")
    for i, item in enumerate(m["logins"] + m["manual"], 1):
        print(f"  {i}. {item}")
    print("\nOpen a new terminal so the PATH takes effect.")


if __name__ == "__main__":
    main()
