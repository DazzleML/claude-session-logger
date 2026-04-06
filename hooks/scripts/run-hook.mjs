#!/usr/bin/env node
/**
 * Cross-platform Python hook bootstrapper for Claude Code plugins.
 *
 * Claude Code guarantees Node.js is available (it's a Node.js app).
 * This script detects the platform, finds the correct Python binary,
 * and spawns the actual Python hook script with stdin passthrough.
 *
 * Why Node.js instead of `python3 || python` in hooks.json:
 *   - `||` is a shell operator, not guaranteed in all hook execution contexts
 *   - Claude Code issue #6453: sometimes uses PowerShell instead of bash on Windows
 *   - Node.js works identically on every platform without shell dependency
 *   - Provides clear error reporting with bug report URL
 *
 * Issues: https://github.com/DazzleML/claude-session-logger/issues
 */

import { execFileSync, spawnSync } from 'child_process';
import { existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PYTHON_SCRIPT = join(__dirname, 'log-command.py');
const ISSUES_URL = 'https://github.com/DazzleML/claude-session-logger/issues';

/**
 * Find a working Python 3 binary on this system.
 * Tries platform-appropriate order: python3 first on Unix, python first on Windows.
 */
function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const result = spawnSync(cmd, ['--version'], {
        stdio: 'pipe',
        timeout: 5000,
      });
      if (result.status === 0) {
        // Verify it's Python 3, not Python 2
        const version = (result.stdout || result.stderr || '').toString();
        if (version.includes('Python 3') || version.includes('python 3')) {
          return cmd;
        }
      }
    } catch {
      continue;
    }
  }
  return null;
}

// ── Main ──────────────────────────────────────────────────────────

// Warn if CLAUDE_PLUGIN_ROOT env var is missing -- likely npm-installed Claude Code
// which doesn't expand ${CLAUDE_PLUGIN_ROOT} in hook commands.
if (!process.env.CLAUDE_PLUGIN_ROOT) {
  process.stderr.write(
    '[claude-session-logger] Warning: CLAUDE_PLUGIN_ROOT environment variable is not set.\n' +
    'This usually means Claude Code was installed via npm, which does not expand\n' +
    'plugin variables in hook commands. To fix this:\n' +
    '  1. Run: curl -fsSL https://claude.ai/install.sh | bash\n' +
    '  2. Restart Claude Code\n' +
    'See: https://github.com/DazzleML/claude-session-logger/blob/main/docs/installation.md\n'
  );
}

const python = findPython();

if (!python) {
  process.stderr.write(
    '[claude-session-logger] Python 3 not found.\n' +
    'Install Python 3.10+ and ensure python3 (or python) is on PATH.\n' +
    `Report issues: ${ISSUES_URL}\n`
  );
  // Exit 0 so Claude Code continues (non-blocking error)
  process.exit(0);
}

if (!existsSync(PYTHON_SCRIPT)) {
  process.stderr.write(
    `[claude-session-logger] Hook script not found: ${PYTHON_SCRIPT}\n` +
    `Report issues: ${ISSUES_URL}\n`
  );
  process.exit(0);
}

// Spawn Python with stdin passthrough (Claude Code sends JSON on stdin)
const result = spawnSync(python, [PYTHON_SCRIPT], {
  stdio: 'inherit',
  timeout: 60000, // 60 second timeout
});

process.exit(result.status || 0);
