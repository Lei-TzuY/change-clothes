# app/__init__.py
from flask import Flask

def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates"
    )

    # 載入 config，讓 current_app.config[...] 可以用
    app.config.from_object('config')

    # 在這裡 import 並註冊各個 Blueprint
    from .routes.upload import bp as upload_bp
    app.register_blueprint(upload_bp)

    from .routes.main import bp as main_bp
    app.register_blueprint(main_bp)

    return app

