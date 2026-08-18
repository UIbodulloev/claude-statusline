*[Русская версия](README.md) · English*

# claude-statusline

A status line for [Claude Code](https://claude.com/claude-code): two rows split into
columns — project, subscription limits, context with a breakdown of what fills it,
and the cost of the session.

```
📁 kad_reserv_v2        ⏳ 5h █░░░░░░░░░ 8% (2h 17m)         🧠 ctx █████████░░░░░░░░░░░░░░░░░░░░░ 45% (134k/300k)   💰 $1.23
⚡ Opus 5 (1M · high)   (cache 99% · in 0% · out 1%)         | base 10% · 30k | hist 35% · 104k | free 55% · 166k
```

Every column is a top/bottom pair, and both rows are padded to the column width:

| Top | Bottom |
| --- | --- |
| project | model, context window, effort level |
| 5-hour limit | 7-day limit |
| context | breakdown of the context bar |
| session cost | — |

## What makes the context bar different

Status lines usually measure context against the model's window. This one measures it
against the **autocompact threshold** (`autoCompactWindow` from `settings.json`) — the
point where the conversation actually starts being compacted, rather than the model's
formal ceiling.

The bar is split into three colored parts:

- **base** (blue) — the incompressible part: system prompt, tool definitions, `CLAUDE.md`,
  skills. Estimated from the first assistant reply in the current transcript and cached
  under `~/.claude/cache/`, because a transcript can run to tens of megabytes.
- **hist** (green → yellow → red as it fills up) — the conversation itself.
- **free** (grey) — what is left before autocompact kicks in.

Percentages are green below 50%, yellow at 50–79%, red at 80% and above. Time until a
limit resets is cyan, so it does not read as another percentage.

## Installation

Requires `python3` and nothing else — the script only uses the standard library.

```bash
git clone git@github.com:UIbodulloev/claude-statusline.git
cp claude-statusline/statusline.py claude-statusline/statusline-command.sh ~/.claude/
chmod +x ~/.claude/statusline-command.sh
```

Then, in `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash \"$HOME/.claude/statusline-command.sh\""
  }
}
```

The path is written relative to `$HOME`, so the same `settings.json` works locally and
on a server under a different user.

For the context bar to account for the autocompact threshold, the same file needs:

```json
{
  "autoCompactEnabled": true,
  "autoCompactWindow": 300000
}
```

If `autoCompactEnabled` is `false`, the bar falls back to measuring against the full
model window.

## Configuration

Everything worth changing sits at the top of `statusline.py`:

- `BAR_W` — width of the limit bars (20 by default);
- `CTX_BAR_W` — width of the context bar (30);
- `SEP` — spacing between columns;
- the `C_*` constants — colors, written as truecolor escapes (`fg(r, g, b)`), so a
  terminal with 24-bit color support is required.

A column disappears when there is no data for it: without subscription limits there is
no `5h`/`7d` block, and at zero cost there is no money block.

## How it works

Claude Code feeds the script a JSON payload on stdin (model, working directory, limits,
context counters, transcript path, cost), and whatever the script writes to stdout is
rendered under the input box. The script writes nothing outside `~/.claude/cache/` and
makes no network calls.

## License

MIT — see [LICENSE](LICENSE).
