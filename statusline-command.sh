#!/usr/bin/env bash
# Обёртка над statusline.py. Путь относительный от $HOME, чтобы один и тот же
# settings.json работал и в WSL, и на сервере под другим пользователем.
exec python3 "$HOME/.claude/statusline.py"
