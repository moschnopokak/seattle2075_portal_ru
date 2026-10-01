"""Отпечатки файлов портала: чтобы update.sh заметил, что вы правили код на сервере вручную, прежде чем заменять его.

    python deploy/filehash.py ПАПКА_ПОРТАЛА                    печатает отпечатки файлов app/ и static/ (так пишется .installed-files.sha256)
    python deploy/filehash.py ПАПКА_ПОРТАЛА --unknown СПИСОК   печатает файлы, которых нет в СПИСКЕ известных версий
    python deploy/filehash.py --from-git                       собирает СПИСОК из всей истории git и текущей папки (запускать перед выпуском: deploy/known-files.txt)

Строка списка: первые 16 символов sha256, два пробела, путь. Файл считается известным, если его отпечаток встречается в СПИСКЕ
для этого пути в любой из прежних версий.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

PARTS = ("app", "static")


def digest(data):
    return hashlib.sha256(data).hexdigest()[:16]


def files(root):
    for part in PARTS:
        base = Path(root) / part
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                yield p.relative_to(root).as_posix(), p


def manifest(root):
    return [f"{digest(p.read_bytes())}  {rel}" for rel, p in files(root)]


def load(path):
    known = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        h, _, rel = line.partition("  ")
        if h and rel:
            known.setdefault(rel, set()).add(h)
    return known


def unknown(root, known_file):
    known = load(known_file)
    return [rel for rel, p in files(root) if digest(p.read_bytes()) not in known.get(rel, set())]


def from_git():
    out = subprocess.run(["git", "log", "--format=%H"], capture_output=True, text=True, check=True).stdout.split()
    seen, lines = {}, set()
    for commit in out:
        tree = subprocess.run(["git", "ls-tree", "-r", commit, *PARTS], capture_output=True, text=True, check=True).stdout
        for row in tree.splitlines():
            meta, rel = row.split("\t", 1)
            blob = meta.split()[2]
            if blob not in seen:
                seen[blob] = digest(subprocess.run(["git", "cat-file", "blob", blob], capture_output=True, check=True).stdout)
            lines.add(f"{seen[blob]}  {rel}")
    lines.update(manifest("."))                                                   # и версия, которая выпускается сейчас (рабочая папка)
    return sorted(lines, key=lambda l: (l.split("  ", 1)[1], l))


def main(argv):
    if argv == ["--from-git"]:
        lines = from_git()
    elif len(argv) == 1:
        lines = manifest(argv[0])
    elif len(argv) == 3 and argv[1] == "--unknown":
        lines = unknown(argv[0], argv[2])
    else:
        print(__doc__)
        return 2
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
