#!/usr/bin/env python3
import os
import sys
import base64
import subprocess
import uuid

sid_file = os.path.expanduser("~/.claude/session_id")
if not os.path.exists(sid_file):
    with open(sid_file, 'w') as f:
        f.write(str(uuid.uuid4()))

with open(sid_file, 'r') as f:
    sid = f.read().strip()

msg_b64 = os.environ.get('CLAUDE_MSG', '')
msg = base64.b64decode(msg_b64).decode('utf-8')

env = os.environ.copy()
env['ANTHROPIC_DISABLE_PREFLIGHT'] = '1' 

subprocess.run([
    'claude',
    '--dangerously-skip-permissions',
    f'--session-id={sid}',
    '--print',
    msg
])
