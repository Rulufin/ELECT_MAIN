from __future__ import annotations

import os
from pathlib import Path


# 除外したいディレクトリ
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}


# 除外したいファイル拡張子
EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".log",
}


def should_skip(path: Path) -> bool:
    if path.name in EXCLUDE_DIRS:
        return True

    if path.suffix in EXCLUDE_EXTENSIONS:
        return True

    return False


def print_tree(
    root: Path,
    *,
    prefix: str = "",
    is_last: bool = True,
    only_python: bool = False,
) -> None:
    connector = "└── " if is_last else "├── "
    print(prefix + connector + root.name)

    if root.is_dir():
        children = sorted(
            [p for p in root.iterdir() if not should_skip(p)],
            key=lambda x: (not x.is_dir(), x.name.lower()),
        )

        if only_python:
            children = [
                p for p in children
                if p.is_dir() or p.suffix == ".py"
            ]

        new_prefix = prefix + ("    " if is_last else "│   ")

        for i, child in enumerate(children):
            last = i == len(children) - 1
            print_tree(
                child,
                prefix=new_prefix,
                is_last=last,
                only_python=only_python,
            )


def main() -> None:
    project_root = Path.cwd()

    print(f"\nProject Tree: {project_root}\n")

    children = sorted(
        [p for p in project_root.iterdir() if not should_skip(p)],
        key=lambda x: (not x.is_dir(), x.name.lower()),
    )

    for i, child in enumerate(children):
        print_tree(
            child,
            prefix="",
            is_last=(i == len(children) - 1),
            only_python=True,  # ← False にすると全ファイル表示
        )


if __name__ == "__main__":
    main()