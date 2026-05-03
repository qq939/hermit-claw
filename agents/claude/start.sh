#!/bin/sh
GW="${SSH_GATEWAY_HOST:-172.30.0.10}"
WP="/home/agent/.claude/workspace/project"
mkdir -p "$HOME/.claude" "$WP/logs"

CURL="curl -s --max-time 10"
FLIST=$($CURL "http://$GW:8080/rules" 2>/dev/null)
if [ -n "$FLIST" ]; then
    echo "$FLIST" | sed 's/,/\n/g' | sed 's/.*"\([^"]*\)".*/\1/' | while read fn; do
        case "$fn" in *[![:space:]]*) $CURL "http://$GW:8080/rules/$fn" -o "$WP/$fn" 2>/dev/null;; esac
    done
fi

if [ -d /agent-config ]; then
    for f in /agent-config/*; do
        case "$f" in */workspace) continue;; esac
        cp -R "$f" "$HOME/.claude/" 2>/dev/null || cp -f "$f" "$HOME/.claude/" 2>/dev/null
    done
fi

/usr/sbin/sshd

node -e "
var fs=require('fs');
var p=process.env.HOME+'/.claude/settings.json';
var j={};
if(fs.existsSync(p)){j=JSON.parse(fs.readFileSync(p,'utf8'));}
j.trustedProjects=['/home/agent/.claude/workspace/project'];
j.hasCompletedOnboarding=true;
j.hasTrustDialogAccepted=true;
j.hasCompletedProjectOnboarding=true;
fs.writeFileSync(p,JSON.stringify(j));
fs.writeFileSync(process.env.HOME+'/.claude.json',JSON.stringify({hasCompletedOnboarding:true,hasTrustDialogAccepted:true,hasCompletedProjectOnboarding:true}));
"

if [ -f "$WP/start.sh" ] && [ -s "$WP/start.sh" ]; then
    chmod +x "$WP/start.sh"
    nohup bash "$WP/start.sh" >> "$WP/logs/start.log" 2>&1 &
fi

exec tail -f /dev/null
