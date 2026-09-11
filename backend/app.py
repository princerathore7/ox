import os

from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()

# ============================================================
# CREATE FLASK APP
# ============================================================
app = Flask(__name__)

# Production secret
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "change-this-secret-key-in-production"
)

# ============================================================
# CORS
# ============================================================
cors_origins = os.getenv("CORS_ORIGINS", "*")

if cors_origins == "*":
    CORS(app)
else:
    origins = [
        origin.strip()
        for origin in cors_origins.split(",")
        if origin.strip()
    ]

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": origins
            }
        },
        supports_credentials=True
    )

# ============================================================
# IMPORT OX BLUEPRINT
# ============================================================
from ox import ox_bp

# ============================================================
# REGISTER OX BLUEPRINT
# ============================================================
app.register_blueprint(ox_bp)

# ============================================================
# HEALTH CHECK
# ============================================================
@app.route("/")
def home():
    return {
        "success": True,
        "service": "OX Game API",
        "status": "online"
    }


@app.route("/health")
def health():
    return {
        "success": True,
        "service": "OX Game",
        "status": "healthy"
    }


# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(404)
def not_found(error):
    return {
        "success": False,
        "error": "Route not found"
    }, 404


@app.errorhandler(500)
def internal_error(error):
    return {
        "success": False,
        "error": "Internal server error"
    }, 500


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )