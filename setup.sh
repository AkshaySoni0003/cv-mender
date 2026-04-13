#!/bin/bash
set -e

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright Chromium browser..."
playwright install chromium

echo ""
echo "Setup complete."
echo "Copy .env.example to .env and add your ANTHROPIC_API_KEY, then run:"
echo "  streamlit run app.py"
