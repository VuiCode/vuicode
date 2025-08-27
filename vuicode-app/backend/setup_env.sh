#!/usr/bin/env bash
echo "Creating Python 3.11 virtual environment..."

# Make sure python3.11 is installed and accessible as python3.11
python -m venv .venv

echo "Activating virtual environment..."
source .venv/Scripts/activate

echo "Upgrading pip..."
python -m pip install --upgrade pip

echo "Installing requirements..."
pip install -r requirements.txt

echo "==============================="
echo "Venv setup complete!"
echo "To activate later, run:"
echo "  source .venv/Scripts/activate"
echo "==============================="

# How to run: bash setup_env.sh