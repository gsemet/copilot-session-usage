---
type: Playbook
title: WSL2 Setup Guide
description: Configure copilot-session-usage when running VS Code on Windows
  with WSL2, including path resolution and troubleshooting.
tags: [wsl2, windows, setup, paths, troubleshooting]
timestamp: 2026-06-30T22:00:00Z
links: []
backlinks: []
---

# WSL2 Setup Guide

When running VS Code on Windows with WSL2, the workspaceStorage directory lives on the Windows host filesystem. You must point the tool to the correct path.

## Finding Your Workspace Storage

1. Open PowerShell on Windows:
   ```powershell
   Get-ChildItem "$env:APPDATA\Code\User\workspaceStorage"
   ```

2. In WSL2, mount the Windows path:
   ```bash
   ls /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage
   ```

## Usage

```bash
# Point to Windows host workspaceStorage
copilot-session-usage latest \
  --workspace-storage /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage

# Or set an alias in your shell profile
alias csu='copilot-session-usage --workspace-storage /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage'
```

## Troubleshooting

### "No workspaceStorage directory found"

- Verify the path exists: `ls /mnt/c/Users/$USER/AppData/Roaming/Code/User/workspaceStorage`
- Check that VS Code has created sessions (open Copilot chat and send a message)
- Ensure the Windows drive is mounted in WSL2: `ls /mnt/c`

### Permission denied

- WSL2 should have read access to Windows files by default
- If not, check WSL2 mount options in `/etc/wsl.conf`
