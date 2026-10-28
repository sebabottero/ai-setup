#!/usr/bin/env python3
"""Add (or update) a skill from a git repository into core/skills, record where it came from, and reinstall.

  ./add-skill.sh https://github.com/owner/repo                 # repo with one SKILL.md
  ./add-skill.sh https://github.com/owner/repo skills/foo      # repo with several: give the folder
  ./add-skill.sh --update foo                                  # pull the recorded source again
  ./add-skill.sh --list                                        # where every skill came from

Nothing from the download is executed: files are only copied. Read the SKILL.md (and any scripts
it ships) before relying on it — a skill is instructions your agents will follow.
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import layers as layerlib

SKILLS = os.path.join(ROOT, "core", "skills")
SOURCES = os.path.join(SKILLS, "sources.json")


def use_profile_layers(home=None):
    """Layers kept outside this repo (--layers-dir of install.py) are remembered in the profile: add skills there too."""
    layerlib.use_layers_dirs([], home or os.path.expanduser("~"))


def set_layer(layer):
    global SKILLS, SOURCES
    SKILLS = os.path.join(layerlib.layer_dir(ROOT, layer), "skills")
    SOURCES = os.path.join(SKILLS, "sources.json")


def load_sources():
    if not os.path.isfile(SOURCES):
        return {}
    with open(SOURCES) as f:
        return json.load(f)


def save_sources(sources):
    with open(SOURCES, "w") as f:
        json.dump(dict(sorted(sources.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")


def skill_name(folder):
    text = open(os.path.join(folder, "SKILL.md"), errors="ignore").read()
    m = re.search(r"^name:\s*['\"]?([A-Za-z0-9._-]+)", text, re.M)
    return m.group(1) if m else os.path.basename(os.path.normpath(folder))


def find_skill_dirs(repo):
    found = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if "SKILL.md" in filenames:
            found.append(dirpath)
    return found


def fetch(url, subpath, existing_name=None):
    with tempfile.TemporaryDirectory(prefix="ai-setup-skill-") as tmp:
        repo = os.path.join(tmp, "repo")
        subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, repo], check=True)
        commit = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        if subpath:
            candidates = [os.path.join(repo, subpath)]
            if not os.path.isfile(os.path.join(candidates[0], "SKILL.md")):
                sys.exit(f"No SKILL.md in '{subpath}' of {url}")
        else:
            candidates = find_skill_dirs(repo)
        if not candidates:
            sys.exit(f"{url} contains no SKILL.md")
        if len(candidates) > 1:
            listing = "\n".join("  " + os.path.relpath(c, repo) for c in candidates)
            sys.exit(f"{url} has several skills; pick a folder as the second argument:\n{listing}")
        src = candidates[0]
        name = existing_name or skill_name(src)
        dest = os.path.join(SKILLS, name)
        if os.path.exists(dest):
            backup = os.path.join(os.path.expanduser("~"), ".ai-setup-backups",
                                  datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), "skills", name)
            shutil.copytree(dest, backup, symlinks=True)
            shutil.rmtree(dest)
            print(f"previous version saved in {backup}")
        shutil.copytree(src, dest, symlinks=False, ignore=shutil.ignore_patterns(".git", ".github"))
        rel = os.path.relpath(src, repo)
        return name, {"url": url, "path": "" if rel == "." else rel, "commit": commit,
                      "added": datetime.date.today().isoformat()}


def report(name):
    folder = os.path.join(SKILLS, name)
    files = sorted(os.path.relpath(os.path.join(d, f), folder) for d, _, fs in os.walk(folder) for f in fs)
    scripts = [f for f in files if f.endswith((".sh", ".py", ".js", ".ts", ".rb", ".ps1")) or "/bin/" in f]
    print(f"\nskill '{name}' in {os.path.relpath(folder, ROOT)}: {len(files)} files")
    if scripts:
        print("⚠ it ships scripts; read them before using it:\n  " + "\n  ".join(scripts))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", help="git URL of the skill's repo")
    p.add_argument("path", nargs="?", help="folder of the skill inside the repo, if there are several")
    p.add_argument("--update", metavar="NAME", help="download a skill again from its recorded source")
    p.add_argument("--list", action="store_true", help="show where each skill comes from")
    p.add_argument("--no-install", action="store_true", help="do not run install.sh at the end")
    p.add_argument("--layer", default="core", help="layer the skill is added to: a folder of ai-setup, new or existing (--update finds it by itself)")
    args = p.parse_args()
    use_profile_layers()
    if not layerlib.valid_name(args.layer):
        sys.exit(f"--layer {args.layer}: invalid name (lowercase letters, digits, - and _; not 'adapters', 'docs', 'tests', 'build').")

    if args.list:
        for layer in layerlib.present(ROOT):
            set_layer(layer)
            sources = load_sources()
            for name in sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, "SKILL.md"))) if os.path.isdir(SKILLS) else []:
                s = sources.get(name)
                print(f"{layer:9} {name:22} " + (f"{s['url']} {s['path']} @ {s['commit'][:8]} ({s['added']})" if s else "local"))
        return
    if args.update:
        for layer in layerlib.present(ROOT):  # the skill lives in the layer whose sources.json registers it
            set_layer(layer)
            if args.update in load_sources():
                break
    else:
        set_layer(args.layer)
    sources = load_sources()
    if args.update:
        s = sources.get(args.update) or sys.exit(f"'{args.update}' has no recorded source (is it local?)")
        name, info = fetch(s["url"], s["path"], existing_name=args.update)
    elif args.url:
        name, info = fetch(args.url, args.path)
    else:
        p.print_help()
        return
    sources[name] = info
    save_sources(sources)
    report(name)
    if not args.no_install:
        subprocess.run([sys.executable, "-I", os.path.join(ROOT, "install.py")], check=True)


if __name__ == "__main__":
    main()
