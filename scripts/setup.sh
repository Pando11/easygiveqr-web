#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d "node_modules" ]]; then
  echo "Installing dependencies..."
  npm install
else
  echo "Dependencies already installed (node_modules present)."
fi

if [[ ! -f ".env.local" ]]; then
  echo "Creating .env.local from .env.example..."
  cp ".env.example" ".env.local"
else
  echo ".env.local already exists; leaving it unchanged."
fi

echo "Setup complete."
echo "Next: update .env.local values, then run: npm run dev"
