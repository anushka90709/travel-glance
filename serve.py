"""Production entry point - waitress instead of Flask's dev server, debug off.

Flask's dev server (app.run(debug=True)) enables an interactive debugger on
error pages that lets anyone who triggers one run arbitrary code - fine on
localhost, not once this is reachable from outside your own machine.

For local development, keep using: python app.py
For production, use:               python serve.py
"""
from waitress import serve

from app import app

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=5000)
