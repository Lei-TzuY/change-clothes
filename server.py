from app import create_app

# Export WSGI app for Flask/Gunicorn
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5020, debug=True, use_reloader=True)

