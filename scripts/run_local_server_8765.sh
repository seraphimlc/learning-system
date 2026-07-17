#!/bin/zsh
cd /Users/liuchang/Documents/gitproject/son-ai-learning-system || exit 1
if [[ -f .env.local ]]; then
  set -a
  source .env.local
  set +a
fi
exec /opt/homebrew/opt/python@3.13/bin/python3.13 -m learning_system.server --db data/local_learning_system.sqlite --port 8765 >> logs/server-8765.log 2>&1
