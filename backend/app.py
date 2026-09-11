import os

from flask import Flask, request
from flask_cors import CORS

from routes.ox import ox_bp


app = Flask(__name__)


# =========================================================
# CORS
# =========================================================

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "https://oxfighterjets.netlify.app",
                "http://localhost:3000",
                "http://localhost:5173",
                "http://127.0.0.1:5500",
                "http://localhost:5500"
            ],
            "methods": [
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "OPTIONS"
            ],
            "allow_headers": [
                "Content-Type",
                "Authorization",
                "X-OX-Token"
            ],
            "supports_credentials": False
        }
    }
)


# =========================================================
# REGISTER OX BLUEPRINT
# =========================================================

app.register_blueprint(ox_bp)


# =========================================================
# HOME / HEALTH
# =========================================================

@app.route("/")
def home():
    return {
        "success": True,
        "service": "OX Game API",
        "status": "online"
    }


# =========================================================
# GLOBAL OPTIONS HANDLER
# =========================================================
# This makes sure browser preflight requests get HTTP 200.
# =========================================================

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return "", 200


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )