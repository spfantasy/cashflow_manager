"""现金流管理系统（Flask 应用工厂）。"""

from __future__ import annotations

import os

from flask import Flask

from . import db as database
from .config import Config
from .resources import resource_path


def create_app(config_object=Config) -> Flask:
    app = Flask(
        __name__,
        template_folder=resource_path("cashflow", "templates"),
        static_folder=resource_path("cashflow", "static"),
    )
    app.config.from_object(config_object)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DB_PATH"])), exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    database.init_db(app.config["DB_PATH"])
    database.init_app(app)

    from .blueprints.details import bp as details_bp
    from .blueprints.flows import bp as flows_bp
    from .blueprints.imports import bp as imports_bp
    from .blueprints.listings import bp as listings_bp
    from .blueprints.manual import bp as manual_bp
    from .blueprints.settings import bp as settings_bp

    app.register_blueprint(flows_bp)
    app.register_blueprint(details_bp)
    app.register_blueprint(imports_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(manual_bp)
    app.register_blueprint(settings_bp)

    @app.template_filter("datefmt")
    def _datefmt(value):
        from .money import fmt_date

        return fmt_date(value)

    @app.template_filter("money2")
    def _money2(value):
        from .money import fmt2

        return fmt2(value)

    return app
