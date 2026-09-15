import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask_wtf import CSRFProtect

from . import auth, dashboard, files, reviews, rules, users
from .db import close_db, init_db

csrf = CSRFProtect()


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )
    app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

    csrf.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(reviews.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(users.bp)
    app.register_blueprint(rules.bp)

    app.teardown_appcontext(close_db)

    init_db()

    return app
