"""Templates and skills that Write follows. The user keeps them in ComfyUI's user/h3c_templates folder; the repo's
examples/templates are listed too, read-only, under example: ids. A .md file is one template. A folder holding a
SKILL.md is one skill, which sends its SKILL.md and the text files it names. Only ids found in a fresh listing load,
so the browser never names a path."""

import dataclasses
import os
import re
from pathlib import Path

import folder_paths
import yaml

LIMIT = 100_000
DEPTH = 8
TEXT = (".md", ".txt", ".json", ".yaml", ".yml")
EXAMPLES = str(Path(__file__).resolve().parent.parent / "examples" / "templates")
EXAMPLE = "example:"
SKILL = "skill.md"
ADDRESS_PREFIX = "skill://"

TOO_LONG = "It has {characters:,} characters; a template can have up to 100,000."
NOT_TEXT = "It isn't UTF-8 text."
NOTE = {"file": "Its front matter couldn't be read, so it goes by its file name.",
        "skill": "Its front matter couldn't be read, so it goes by its folder's name."}
FOLDER = "H3 can't open the template folder: {error}"

LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
CODE = re.compile(r"`([^`\s]+\.[A-Za-z][A-Za-z0-9]{0,7})`")
ADDRESS = re.compile(r"skill://[^\s`)\]>\"']+")
SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]+:")
DRIVE = re.compile(r"[A-Za-z]:")

_RULE = "The template is the video the user wants this one to resemble. "
_EXAMPLES = "its characters, names, places, titles and words are examples; "
_WITHOUT_BIBLE = "use the idea's instead. The Guide and the idea win over it."
EDIT_RULE = ("The payload's template is the video the user wants this one to resemble: keep revised boxes in its "
             "style, and treat its characters, names and words as examples.")


@dataclasses.dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str
    kind: str
    text: str
    characters: int
    files: tuple = ()
    skipped: tuple = ()
    note: str = ""
    problem: str = ""

    def public(self):
        """The template as the listing shows it, without its text."""
        item = {"id": self.id, "name": self.name, "description": self.description, "kind": self.kind,
                "characters": self.characters, "files": list(self.files), "skipped": list(self.skipped)}
        return {**item, **({"note": self.note} if self.note else {}),
                **({"problem": self.problem} if self.problem else {})}


def folder():
    return os.path.join(folder_paths.get_user_directory(), "h3c_templates")


def plan_rule(bible):
    return ("- " + _RULE + "Shape the plan after it: spread its sequence over the boxes in order, stretching or "
            "repeating it to fill them, and start each beat with the part of the template that box plays. Its own "
            "length is not the film's. Take its style and rules, not its content: " + _EXAMPLES
            + ("use the idea's and the bible's instead." if bible else _WITHOUT_BIBLE))


def write_rule(bible):
    return (_RULE + "Stage this box's part of it in its style: its look, camera, editing rhythm, transitions, "
            "typography and sound. " + _EXAMPLES[0].upper() + _EXAMPLES[1:]
            + ("use the bible's and the idea's instead." if bible else _WITHOUT_BIBLE))


def block(template):
    return f"Template: {template.name}\n{template.text}"


def listing(root=None, examples=EXAMPLES):
    """The template folder, its templates and the examples, as the Story page lists them. The folder is created when
    missing; when it can't be created or read, the listing says so and lists only the examples."""
    root = folder() if root is None else root
    result = {"folder": root, "templates": []}
    try:
        os.makedirs(root, exist_ok=True)
        result["templates"] = [template.public() for template in scan(root)]
    except OSError as error:
        result["problem"] = FOLDER.format(error=error)
    try:
        result["examples"] = [template.public() for template in scan(examples, EXAMPLE)]
    except OSError:
        result["examples"] = []
    return result


def find(template_id, root=None, examples=EXAMPLES):
    """The template whose id is `template_id` in a fresh listing, or None."""
    if not isinstance(template_id, str) or not template_id:
        return None
    try:
        found = (scan(examples, EXAMPLE) if template_id.startswith(EXAMPLE)
                 else scan(folder() if root is None else root))
    except OSError:
        return None
    return next((template for template in found if template.id == template_id), None)


def scan(root, prefix=""):
    """The templates in `root`, sorted by id: every .md file, and every folder holding a SKILL.md, in folders up to
    DEPTH levels below it. Links are followed, each real folder is searched once, and names starting with . are
    skipped. An id is `prefix` and the path from `root` joined with /. Raises OSError when `root` can't be read."""
    found, seen = [], {_real(root)}

    def search(path, parts):
        with os.scandir(path) as entries:
            entries = sorted(entries, key=lambda entry: entry.name)
        for entry in entries:
            if entry.name.startswith("."):
                continue
            here = parts + [entry.name]
            try:
                if entry.is_dir():
                    real = _real(entry.path)
                    if len(here) > DEPTH or real in seen:
                        continue
                    seen.add(real)
                    skill = _skill_file(entry.path)
                    if skill is None:
                        search(entry.path, here)
                    else:
                        found.append(_skill(entry.path, skill, prefix + "/".join(here)))
                elif entry.name.lower().endswith(".md"):
                    found.append(_file(entry.path, prefix + "/".join(here), entry.name[:-3]))
            except OSError:
                continue

    search(root, [])
    return sorted(found, key=lambda template: (template.id.casefold(), template.id))


def _real(path):
    return os.path.normcase(os.path.realpath(path))


def _skill_file(path):
    with os.scandir(path) as entries:
        return next((entry.path for entry in entries if entry.name.lower() == SKILL and entry.is_file()), None)


def _decode(path):
    """The text of the file at `path` with \\n line ends, or None when it isn't UTF-8."""
    with open(path, "rb") as file:
        data = file.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _front(text):
    """`text`'s front matter as a dict, or None when it can't be read, and the text after it."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}, text
    body = "\n".join(lines[end + 1:])
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return None, body
    if data is None:
        return {}, body
    return (data if isinstance(data, dict) else None), body


def _labels(data, fallback):
    name = (data or {}).get("name")
    description = (data or {}).get("description")
    name = " ".join(name.split()) if isinstance(name, str) else ""
    return name or fallback, " ".join(description.split()) if isinstance(description, str) else ""


def _measured(template):
    characters = len(template.text)
    if characters > LIMIT:
        return dataclasses.replace(template, text="", characters=characters,
                                   problem=TOO_LONG.format(characters=characters))
    return dataclasses.replace(template, characters=characters)


def _file(path, template_id, stem):
    text = _decode(path)
    if text is None:
        return Template(template_id, stem, "", "file", "", 0, problem=NOT_TEXT)
    data, body = _front(text)
    name, description = _labels(data, stem)
    return _measured(Template(template_id, name, description, "file", body.strip(), 0,
                              note="" if data is not None else NOTE["file"]))


def _skill(path, skill, template_id):
    """The skill in folder `path`: its SKILL.md text, then each text file it names, in the order first named."""
    own = os.path.basename(path)
    text = _decode(skill)
    if text is None:
        return Template(template_id, own, "", "skill", "", 0, problem=NOT_TEXT)
    data, body = _front(text)
    name, description = _labels(data, own)
    names = {own} | ({data["name"]} if isinstance((data or {}).get("name"), str) else set())
    parts, files, skipped, seen = [body.strip()], [], [], {_real(skill)}
    for target in _targets(parts[0]):
        resolved = _resolve(target, path, names)
        content = None
        if resolved is not None:
            label, file = resolved
            if _real(file) in seen:
                continue
            try:
                content = _decode(file)
            except OSError:
                pass
        if content is None:
            if target not in skipped:
                skipped.append(target)
            continue
        seen.add(_real(file))
        files.append(label)
        parts.append(f"File {label}:\n{content.strip()}")
    return _measured(Template(template_id, name, description, "skill", "\n\n".join(parts), 0, tuple(files),
                              tuple(skipped), "" if data is not None else NOTE["skill"]))


def _targets(text):
    """The files `text` names, in the order first named: markdown link targets, backticked file names and skill://
    addresses, without web links, anchors or #fragments."""
    found = []
    for pattern in (LINK, CODE):
        found += [(match.start(), match.group(1)) for match in pattern.finditer(text)]
    found += [(match.start(), match.group(0).rstrip(".,;:!?")) for match in ADDRESS.finditer(text)]
    targets = []
    for _, target in sorted(found, key=lambda item: item[0]):
        if not target.startswith(ADDRESS_PREFIX) and (target.startswith("#") or SCHEME.match(target)):
            continue
        target = target.split("#", 1)[0]
        if target and target not in targets:
            targets.append(target)
    return targets


def _resolve(target, path, names):
    """The label and path of the file `target` names from the skill in folder `path`, or None when it may not
    load: absolute, outside the skill, missing, or not a text file."""
    relative, base, sibling = target.replace("\\", "/"), path, ""
    if relative.startswith(ADDRESS_PREFIX):
        name, _, relative = relative[len(ADDRESS_PREFIX):].partition("/")
        if name not in names:
            if name in ("", ".", "..") or ":" in name:
                return None
            base, sibling = os.path.join(os.path.dirname(path), name), ADDRESS_PREFIX + name + "/"
            try:
                if _skill_file(base) is None:
                    return None
            except OSError:
                return None
    parts = relative.split("/")
    if not relative or relative.startswith("/") or DRIVE.match(relative) or ".." in parts:
        return None
    file = os.path.join(base, *parts)
    if not os.path.isfile(file) or os.path.splitext(file)[1].lower() not in TEXT:
        return None
    return sibling + "/".join(part for part in parts if part not in ("", ".")), file
