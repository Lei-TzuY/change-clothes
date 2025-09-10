# app/__init__.py
from flask import Flask
from .extensions import db, login_manager, csrf, limiter
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge
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
    csrf.init_app(app)
    limiter.init_app(app)

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

    try:
        from .routes.gallery import bp as gallery_bp
        app.register_blueprint(gallery_bp)
    except Exception:
        pass

    try:
        from .routes.settings import bp as settings_bp
        app.register_blueprint(settings_bp)
    except Exception:
        pass

    # Optional prompt helper endpoints
    try:
        from .routes.prompt import bp as prompt_bp
        app.register_blueprint(prompt_bp)
    except Exception:
        pass

    # Floating assistant (LLM navigator)
    try:
        from .routes.assistant import bp as assistant_bp
        app.register_blueprint(assistant_bp)
    except Exception:
        pass

    # Image -> Video (local generator)
    try:
        from .routes.video import bp as video_bp
        app.register_blueprint(video_bp)
    except Exception:
        pass

    # Feedback (survey + ratings)
    try:
        from .routes.feedback import bp as feedback_bp
        app.register_blueprint(feedback_bp)
    except Exception:
        pass

    # Billing pages
    try:
        from .routes.billing import bp as billing_bp
        app.register_blueprint(billing_bp)
    except Exception:
        pass

    # Ensure tables
    with app.app_context():
        try:
            db.create_all()
            try:
                from backend.db_migrate import ensure_user_columns, ensure_image_columns
                ensure_user_columns(db)
                ensure_image_columns(db)
            except Exception:
                pass
        except Exception:
            pass

    @app.errorhandler(CSRFError)
    def handle_csrf(err):
        from flask import request, jsonify, redirect, url_for, flash
        if request.accept_mimetypes.accept_json:
            return jsonify(error="CSRF token missing or invalid"), 400
        flash("表單驗證逾時或無效，請重試", "error")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_large_file(err):
        from flask import request, jsonify
        if request.accept_mimetypes.accept_json or request.path.startswith(("/upload", "/text2image", "/img2img", "/inpaint")):
            return jsonify(error="上傳檔案過大", max_bytes=app.config.get("MAX_CONTENT_LENGTH")), 413
        return ("File too large", 413)

    # Lightweight health check
    @app.get("/healthz")
    def healthz():
        return "ok"

    return app
