# Use from WSL2

On WSL2, VS Code runs on Windows and stores debug logs in the Windows filesystem.
Point the tool at the Windows path via `/mnt/c/`.

## Basic usage

```bash
copilot-session-usage latest \
  --workspace-storage "/mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage"
```

## Make it permanent

Add an alias to `~/.bashrc` or `~/.zshrc`:

```bash
alias copilot-session-usage='copilot-session-usage \
  --workspace-storage "/mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage"'
```

## Verify the path

If the Windows username differs from your WSL username, substitute it directly:

```bash
ls "/mnt/c/Users/MyWindowsName/AppData/Roaming/Code/User/workspaceStorage"
```

You should see directories named with long hex hashes.

## VS Code Server (Remote - WSL extension)

When using the VS Code Remote - WSL extension, VS Code runs in WSL and stores
logs in the Linux filesystem at the default location
(`~/.config/Code/User/workspaceStorage/`). No `--workspace-storage` override
is needed in this case.
