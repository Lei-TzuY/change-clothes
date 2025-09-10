from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()

login_manager = LoginManager()
login_manager.login_view = "auth.login_form"

csrf = CSRFProtect()

# In-memory limiter; switch storage in prod (e.g. redis://)
limiter = Limiter(get_remote_address, storage_uri="memory://")
