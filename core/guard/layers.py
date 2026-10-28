"""Layers of ai-setup: core (generic) plus any layer you add (personal, work...). Shared by the installer and the guard.

A layer has the shape of core/: agents/, skills/, notes/, policy.json, AGENTS.md. Layers only add: a layer never
removes a rule another layer gave. Core is always installed."""
import json, os, re

# A layer is any top-level folder with layer content; no code lists them. Order decides who wins in AGENTS.md:
# core first, personal second, the rest alphabetically.
PRIORITY = ("core", "personal")
RESERVED = {"adapters", "docs", "tests", "build", "node_modules"}
CONTENT = ("policy.json", "AGENTS.md", "skills", "agents", "notes")


EXTRA_ROOTS = []  # more folders that hold layers (--layers-dir); the engine's own root always comes first


def set_extra_roots(paths):
    EXTRA_ROOTS[:] = [os.path.realpath(p) for p in paths]


def use_layers_dirs(given, home):
    """Set the extra roots: the folders given now plus the ones the profile in `home` remembers (a vanished one is dropped).
    Exits with a clear message if a given folder does not exist."""
    given = [os.path.abspath(os.path.expanduser(d)) for d in given]
    missing = [d for d in given if not os.path.isdir(d)]
    if missing:
        raise SystemExit(f"--layers-dir: not a folder: {', '.join(missing)}")
    try:
        with open(os.path.join(home, ".ai-setup-profile")) as f:
            saved = [d for d in json.load(f).get("layers_dirs", []) if os.path.isdir(d)]
    except (OSError, ValueError):
        saved = []
    set_extra_roots(list(dict.fromkeys(given + saved)))


def roots(root):
    return [root] + [r for r in EXTRA_ROOTS if r != os.path.realpath(root)]


def layer_dir(root, layer):
    """Folder of a layer: the engine's own root wins over --layers-dir, and core never comes from outside."""
    for base in roots(root):
        path = os.path.join(base, layer)
        if layer == "core" or os.path.isdir(path) and _has_content(path):
            return path
    return os.path.join(root, layer)


def _has_content(path):
    return any(os.path.exists(os.path.join(path, c)) for c in CONTENT)


def valid_name(name):
    return bool(re.fullmatch(r"[a-z][a-z0-9_-]*", name)) and name not in RESERVED


def is_layer(root, name):
    path = layer_dir(root, name)
    return valid_name(name) and os.path.isdir(path) and _has_content(path)


def present(root):
    names = {n for base in roots(root) if os.path.isdir(base) for n in os.listdir(base) if is_layer(root, n)}
    return sorted(names, key=lambda n: (PRIORITY.index(n) if n in PRIORITY else len(PRIORITY), n))


def _merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for key, value in b.items():
            out[key] = _merge(a[key], value) if key in a else value
        return out
    if isinstance(a, list) and isinstance(b, list):
        return a + [x for x in b if x not in a]
    if isinstance(a, bool) and isinstance(b, bool):
        return a or b
    return a  # strings (comments): the first layer wins


def merge_policies(parts):
    result = {}
    for part in parts:
        result = _merge(result, part)
    return result


def read_policy(root, layer):
    path = os.path.join(layer_dir(root, layer), "policy.json")
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def compose_policy(root, layers):
    """The merged policy of the layers. A layer kept outside this repo adds permissions too, so its policy.json is
    protected like the ones inside: editing it asks for OK."""
    policy = merge_policies([read_policy(root, l) for l in layers])
    outside = [os.path.join(r, "*", "policy.json") for r in roots(root)[1:]]
    if outside:
        policy["protected_paths"] = policy.get("protected_paths", []) + [p for p in outside if p not in policy.get("protected_paths", [])]
    return policy


def compose_agents_md(root, layers):
    parts = []
    for layer in layers:
        path = os.path.join(layer_dir(root, layer), "AGENTS.md")
        if os.path.isfile(path):
            with open(path) as f:
                parts.append(f"<!-- ai-setup: layer {layer}; if it clashes with an earlier layer, this one wins -->\n"
                             + f.read().strip().replace("{{LAYER}}", layer_dir(root, layer)))  # a layer's own folder
    return "\n\n".join(parts).replace("{{AI_SETUP}}", root) + "\n"
