#!/usr/bin/env bash
#
# run_server.sh — Start the Virtual Fitting Room Flask server with one click

# 1. Navigate to the project folder (please change the path to your own)
cd /home/st426/change-clothes

# 2. Enable virtualenv (if not already present, skip this step or change the name of your environment)
if [ -f venv/bin/activate ]; then
source venv/bin/activate
fi

# 3. Configure Flask parameters (development mode, auto-reload)
export FLASK_APP=server.py
export FLASK_ENV=development
export FLASK_DEBUG=1

# 4. Run Flask (you can also use python server.py)
python -m flask run --host=0.0.0.0 --port=5020

# Press Ctrl+C to stop when finished