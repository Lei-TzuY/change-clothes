# app/__init__.py
from flask import Flask
from .extensions import db, login_manager
from .models import User


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    # Load config
    app.config.from_object('config')

    # Init DB/Login
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            return None

    # Register Blueprints
    from .routes.upload import bp as upload_bp
    app.register_blueprint(upload_bp)

    from .routes.main import bp as main_bp
    app.register_blueprint(main_bp)

    try:
        from .routes.features import bp as features_bp
        app.register_blueprint(features_bp)
    except Exception:
        pass

    try:
        from .routes.pages import bp as pages_bp
        app.register_blueprint(pages_bp)
    except Exception:
        pass

    try:
        from .routes.auth import bp as auth_bp
        app.register_blueprint(auth_bp, url_prefix='/auth')
    except Exception as e:
        print(f"Auth blueprint failed to load: {e}")

    # Ensure tables
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

    return app
