import server

app = server.create_app()
print("APP_OK", bool(app))

