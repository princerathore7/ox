import os
import uuid
import secrets
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify
from pymongo import MongoClient, ASCENDING, DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# OX GAME BLUEPRINT
# ============================================================

ox_bp = Blueprint("ox", __name__, url_prefix="/api/ox")


# ============================================================
# MONGODB
# ============================================================

OX_MONGO_URI = os.getenv("OX_MONGO_URI")

if not OX_MONGO_URI:
    raise RuntimeError(
        "OX_MONGO_URI environment variable is missing."
    )

OX_DB_NAME = os.getenv("OX_MONGO_DB_NAME", "ox_game")

ox_client = MongoClient(
    OX_MONGO_URI,
    serverSelectionTimeoutMS=10000
)

ox_db = ox_client[OX_DB_NAME]


# ============================================================
# COLLECTIONS
# ============================================================

players_col = ox_db["players"]
games_col = ox_db["games"]
rooms_col = ox_db["rooms"]
queue_col = ox_db["matchmaking"]
groups_col = ox_db["groups"]
requests_col = ox_db["requests"]
sessions_col = ox_db["sessions"]


# ============================================================
# SETTINGS
# ============================================================

BOARD_SIZE = 5
WIN_LENGTH = 5

MAX_NAME_LENGTH = 40
MAX_USERNAME_LENGTH = 30
MIN_USERNAME_LENGTH = 3

MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 6

MAX_GROUP_NAME_LENGTH = 60
MAX_ROOM_ID_LENGTH = 30

VALID_SYMBOLS = {"X", "O"}

SESSION_DAYS = 30


# ============================================================
# ADMIN SETTINGS
# ============================================================

ADMIN_USERNAME = os.getenv("OX_ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("OX_ADMIN_PASSWORD")

if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    print(
        "WARNING: OX_ADMIN_USERNAME / OX_ADMIN_PASSWORD "
        "environment variables are not configured."
    )


# ============================================================
# DATABASE CONNECTION TEST
# ============================================================

try:
    ox_client.admin.command("ping")

    print("=" * 44)
    print("OX GAME MONGODB CONNECTED")
    print("=" * 44)
    print(f"Database: {OX_DB_NAME}")
    print("Collections:")
    print(" - players")
    print(" - games")
    print(" - rooms")
    print(" - matchmaking")
    print(" - groups")
    print(" - requests")
    print(" - sessions")
    print("=" * 44)

except Exception as e:
    print("OX MongoDB connection error:", e)


# ============================================================
# INDEXES
# ============================================================

try:
    players_col.create_index(
        [("username", ASCENDING)],
        unique=True,
        name="unique_username"
    )

    players_col.create_index(
        [("playerId", ASCENDING)],
        unique=True,
        name="unique_player_id"
    )

    players_col.create_index(
        [("blocked", ASCENDING)]
    )

    players_col.create_index(
        [("suspended", ASCENDING)]
    )

    games_col.create_index(
        [("gameId", ASCENDING)],
        unique=True
    )

    games_col.create_index(
        [("players.playerId", ASCENDING)]
    )

    games_col.create_index(
        [("createdAt", DESCENDING)]
    )

    rooms_col.create_index(
        [("roomId", ASCENDING)],
        unique=True
    )

    queue_col.create_index(
        [("playerId", ASCENDING)],
        unique=True
    )

    groups_col.create_index(
        [("groupId", ASCENDING)],
        unique=True
    )

    requests_col.create_index(
        [("requestId", ASCENDING)],
        unique=True
    )

    sessions_col.create_index(
        [("token", ASCENDING)],
        unique=True
    )

    sessions_col.create_index(
        [("expiresAt", ASCENDING)],
        expireAfterSeconds=0
    )

except Exception as e:
    print("Index creation warning:", e)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_date(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    return value


def clean_string(value):
    if value is None:
        return ""

    return str(value).strip()


def generate_player_id():
    return "OX" + uuid.uuid4().hex[:10].upper()


def generate_game_id():
    return "GAME-" + uuid.uuid4().hex[:12].upper()


def generate_room_id():
    return uuid.uuid4().hex[:8].upper()


def generate_group_id():
    return "GRP-" + uuid.uuid4().hex[:10].upper()


def generate_request_id():
    return "REQ-" + uuid.uuid4().hex[:12].upper()


def valid_username(username):
    if not username:
        return False

    if len(username) < MIN_USERNAME_LENGTH:
        return False

    if len(username) > MAX_USERNAME_LENGTH:
        return False

    allowed = (
        username.replace("_", "")
        .replace("-", "")
        .isalnum()
    )

    return allowed


def sanitize_player(player):
    if not player:
        return None

    return {
        "playerId": player.get("playerId"),
        "name": player.get("name"),
        "username": player.get("username"),
        "wins": int(player.get("wins", 0)),
        "losses": int(player.get("losses", 0)),
        "draws": int(player.get("draws", 0)),
        "gamesPlayed": int(player.get("gamesPlayed", 0)),
        "winRate": calculate_win_rate(player),
        "blocked": bool(player.get("blocked", False)),
        "suspended": bool(player.get("suspended", False)),
        "createdAt": iso_date(player.get("createdAt")),
        "lastLogin": iso_date(player.get("lastLogin")),
    }


def calculate_win_rate(player):
    wins = int(player.get("wins", 0))
    losses = int(player.get("losses", 0))
    draws = int(player.get("draws", 0))

    total = wins + losses + draws

    if total <= 0:
        return 0

    return round((wins / total) * 100, 2)


def create_empty_board():
    return [
        [None for _ in range(BOARD_SIZE)]
        for _ in range(BOARD_SIZE)
    ]


def create_session(player_id, is_admin=False):
    token = secrets.token_urlsafe(48)

    expires = now_utc() + timedelta(days=SESSION_DAYS)

    sessions_col.insert_one({
        "token": token,
        "playerId": player_id,
        "isAdmin": bool(is_admin),
        "createdAt": now_utc(),
        "expiresAt": expires
    })

    return token


def get_token():
    auth = request.headers.get("Authorization", "")

    if auth.startswith("Bearer "):
        return auth[7:].strip()

    token = request.headers.get("X-OX-Token")

    if token:
        return token.strip()

    return None


def get_session():
    token = get_token()

    if not token:
        return None

    session = sessions_col.find_one({
        "token": token,
        "expiresAt": {"$gt": now_utc()}
    })

    return session


def get_current_player():
    session = get_session()

    if not session:
        return None

    if session.get("isAdmin"):
        return None

    player = players_col.find_one({
        "playerId": session.get("playerId")
    })

    return player


def require_player():
    player = get_current_player()

    if not player:
        return None, (
            jsonify({
                "success": False,
                "message": "Login required."
            }),
            401
        )

    if player.get("blocked"):
        return None, (
            jsonify({
                "success": False,
                "message": "Your account has been blocked."
            }),
            403
        )

    if player.get("suspended"):
        return None, (
            jsonify({
                "success": False,
                "message": "Your account has been suspended."
            }),
            403
        )

    return player, None


def require_admin():
    session = get_session()

    if not session or not session.get("isAdmin"):
        return None, (
            jsonify({
                "success": False,
                "message": "Admin authentication required."
            }),
            401
        )

    return session, None


def find_game_for_player(game_id, player_id):
    return games_col.find_one({
        "gameId": game_id,
        "players.playerId": player_id
    })


def player_in_game(game, player_id):
    for p in game.get("players", []):
        if p.get("playerId") == player_id:
            return p

    return None


def find_winning_line(board, symbol):
    directions = [
        (0, 1),    # horizontal
        (1, 0),    # vertical
        (1, 1),    # diagonal
        (1, -1)    # reverse diagonal
    ]

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):

            if board[r][c] != symbol:
                continue

            for dr, dc in directions:

                cells = []

                for i in range(WIN_LENGTH):
                    nr = r + dr * i
                    nc = c + dc * i

                    if (
                        nr < 0 or
                        nr >= BOARD_SIZE or
                        nc < 0 or
                        nc >= BOARD_SIZE
                    ):
                        break

                    if board[nr][nc] != symbol:
                        break

                    cells.append([nr, nc])

                if len(cells) == WIN_LENGTH:
                    return cells

    return None


def board_full(board):
    for row in board:
        for cell in row:
            if cell is None:
                return False

    return True


def game_public(game):
    if not game:
        return None

    result = {
        "gameId": game.get("gameId"),
        "board": game.get("board"),
        "players": game.get("players"),
        "status": game.get("status"),
        "currentTurn": game.get("currentTurn"),
        "winner": game.get("winner"),
        "winningLine": game.get("winningLine"),
        "result": game.get("result"),
        "createdAt": iso_date(game.get("createdAt")),
        "updatedAt": iso_date(game.get("updatedAt")),
        "finishedAt": iso_date(game.get("finishedAt")),
        "rematchOf": game.get("rematchOf")
    }

    return result


def make_game(player1, player2):
    game_id = generate_game_id()

    first = secrets.choice([
        player1,
        player2
    ])

    second = player2 if first["playerId"] == player1["playerId"] else player1

    players = [
        {
            "playerId": first["playerId"],
            "name": first["name"],
            "username": first["username"],
            "symbol": "X"
        },
        {
            "playerId": second["playerId"],
            "name": second["name"],
            "username": second["username"],
            "symbol": "O"
        }
    ]

    game = {
        "gameId": game_id,
        "board": create_empty_board(),
        "players": players,
        "currentTurn": first["playerId"],
        "status": "active",
        "winner": None,
        "winningLine": None,
        "result": None,
        "createdAt": now_utc(),
        "updatedAt": now_utc(),
        "finishedAt": None,
        "rematchOf": None
    }

    games_col.insert_one(game)

    return game


def update_finished_stats(game):
    winner_id = game.get("winner")

    if winner_id:
        loser_id = None

        for player in game.get("players", []):
            if player["playerId"] != winner_id:
                loser_id = player["playerId"]
                break

        if loser_id:
            players_col.update_one(
                {"playerId": winner_id},
                {
                    "$inc": {
                        "wins": 1,
                        "gamesPlayed": 1
                    }
                }
            )

            players_col.update_one(
                {"playerId": loser_id},
                {
                    "$inc": {
                        "losses": 1,
                        "gamesPlayed": 1
                    }
                }
            )

    elif game.get("result") == "draw":
        for player in game.get("players", []):
            players_col.update_one(
                {"playerId": player["playerId"]},
                {
                    "$inc": {
                        "draws": 1,
                        "gamesPlayed": 1
                    }
                }
            )


# ============================================================
# AUTH — SIGNUP
# ============================================================

@ox_bp.route("/auth/signup", methods=["POST"])
def signup():

    data = request.get_json(silent=True) or {}

    name = clean_string(data.get("name"))
    username = clean_string(data.get("username")).lower()
    password = data.get("password", "")

    if not name:
        return jsonify({
            "success": False,
            "message": "Name is required."
        }), 400

    if len(name) > MAX_NAME_LENGTH:
        return jsonify({
            "success": False,
            "message": "Name is too long."
        }), 400

    if not valid_username(username):
        return jsonify({
            "success": False,
            "message": (
                f"Username must be {MIN_USERNAME_LENGTH}-"
                f"{MAX_USERNAME_LENGTH} characters and contain "
                "only letters, numbers, _ or -."
            )
        }), 400

    if not isinstance(password, str):
        return jsonify({
            "success": False,
            "message": "Password must be text."
        }), 400

    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": (
                f"Password must be at least "
                f"{MIN_PASSWORD_LENGTH} characters."
            )
        }), 400

    if len(password) > MAX_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": "Password is too long."
        }), 400

    existing = players_col.find_one({
        "username": username
    })

    if existing:
        return jsonify({
            "success": False,
            "message": "Username already exists."
        }), 409

    player_id = generate_player_id()

    player = {
        "playerId": player_id,
        "name": name,
        "username": username,
        "passwordHash": generate_password_hash(password),

        "wins": 0,
        "losses": 0,
        "draws": 0,
        "gamesPlayed": 0,

        "blocked": False,
        "suspended": False,

        "createdAt": now_utc(),
        "lastLogin": None
    }

    try:
        players_col.insert_one(player)

    except Exception as e:

        if "duplicate" in str(e).lower():
            return jsonify({
                "success": False,
                "message": "Username already exists."
            }), 409

        print("Signup error:", e)

        return jsonify({
            "success": False,
            "message": "Unable to create account."
        }), 500

    token = create_session(player_id)

    return jsonify({
        "success": True,
        "message": "Signup successful.",
        "token": token,
        "player": sanitize_player(player)
    }), 201


# ============================================================
# AUTH — LOGIN
# ============================================================

@ox_bp.route("/auth/login", methods=["POST"])
def login():

    data = request.get_json(silent=True) or {}

    username = clean_string(data.get("username")).lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Username and password are required."
        }), 400

    player = players_col.find_one({
        "username": username
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Invalid username or password."
        }), 401

    if player.get("blocked"):
        return jsonify({
            "success": False,
            "message": "Your account has been blocked."
        }), 403

    if player.get("suspended"):
        return jsonify({
            "success": False,
            "message": "Your account has been suspended."
        }), 403

    password_hash = player.get("passwordHash")

    if not password_hash or not check_password_hash(
        password_hash,
        password
    ):
        return jsonify({
            "success": False,
            "message": "Invalid username or password."
        }), 401

    players_col.update_one(
        {
            "playerId": player["playerId"]
        },
        {
            "$set": {
                "lastLogin": now_utc()
            }
        }
    )

    player["lastLogin"] = now_utc()

    token = create_session(player["playerId"])

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "token": token,
        "player": sanitize_player(player)
    })


# ============================================================
# AUTH — LOGOUT
# ============================================================

@ox_bp.route("/auth/logout", methods=["POST"])
def logout():

    token = get_token()

    if token:
        sessions_col.delete_one({
            "token": token
        })

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })


# ============================================================
# CURRENT PLAYER
# ============================================================

@ox_bp.route("/auth/me", methods=["GET"])
def auth_me():

    player, error = require_player()

    if error:
        return error

    return jsonify({
        "success": True,
        "player": sanitize_player(player)
    })


# ============================================================
# PLAYER PROFILE
# ============================================================

@ox_bp.route("/player/<player_id>", methods=["GET"])
def get_player(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    return jsonify({
        "success": True,
        "player": sanitize_player(player)
    })


# ============================================================
# OLD PLAYER REGISTER COMPATIBILITY ROUTE
# ============================================================

@ox_bp.route("/player/register", methods=["POST"])
def player_register():

    data = request.get_json(silent=True) or {}

    name = clean_string(data.get("name"))
    username = clean_string(data.get("username")).lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "success": False,
            "message": (
                "Username and password are now required. "
                "Use /api/ox/auth/signup."
            )
        }), 400

    data["name"] = name

    # Reuse signup logic internally
    if not name:
        data["name"] = username

    existing = players_col.find_one({
        "username": username
    })

    if existing:
        return jsonify({
            "success": False,
            "message": "Username already exists."
        }), 409

    if not valid_username(username):
        return jsonify({
            "success": False,
            "message": "Invalid username."
        }), 400

    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": "Password is too short."
        }), 400

    player_id = generate_player_id()

    player = {
        "playerId": player_id,
        "name": data["name"][:MAX_NAME_LENGTH],
        "username": username,
        "passwordHash": generate_password_hash(password),

        "wins": 0,
        "losses": 0,
        "draws": 0,
        "gamesPlayed": 0,

        "blocked": False,
        "suspended": False,

        "createdAt": now_utc(),
        "lastLogin": None
    }

    try:
        players_col.insert_one(player)
    except Exception as e:
        print("Register error:", e)

        return jsonify({
            "success": False,
            "message": "Unable to create account."
        }), 500

    token = create_session(player_id)

    return jsonify({
        "success": True,
        "message": "Player registered successfully.",
        "token": token,
        "player": sanitize_player(player)
    }), 201


# ============================================================
# RANDOM MATCHMAKING — JOIN
# ============================================================

@ox_bp.route("/matchmaking/join", methods=["POST"])
def matchmaking_join():

    player, error = require_player()

    if error:
        return error

    player_id = player["playerId"]

    existing_game = games_col.find_one({
        "players.playerId": player_id,
        "status": "active"
    })

    if existing_game:
        return jsonify({
            "success": True,
            "matched": True,
            "game": game_public(existing_game)
        })

    existing_queue = queue_col.find_one({
        "playerId": player_id
    })

    if existing_queue:
        return jsonify({
            "success": True,
            "matched": False,
            "message": "Already waiting for an opponent."
        })

    opponent_queue = queue_col.find_one({
        "playerId": {
            "$ne": player_id
        }
    })

    if opponent_queue:

        opponent = players_col.find_one({
            "playerId": opponent_queue["playerId"]
        })

        if opponent and not opponent.get("blocked") and not opponent.get("suspended"):

            queue_col.delete_one({
                "_id": opponent_queue["_id"]
            })

            game = make_game(
                player,
                opponent
            )

            return jsonify({
                "success": True,
                "matched": True,
                "game": game_public(game)
            })

    queue_col.insert_one({
        "playerId": player_id,
        "name": player["name"],
        "username": player["username"],
        "joinedAt": now_utc()
    })

    return jsonify({
        "success": True,
        "matched": False,
        "message": "Waiting for opponent."
    })


# ============================================================
# MATCHMAKING — LEAVE
# ============================================================

@ox_bp.route("/matchmaking/leave", methods=["POST"])
def matchmaking_leave():

    player, error = require_player()

    if error:
        return error

    queue_col.delete_one({
        "playerId": player["playerId"]
    })

    return jsonify({
        "success": True,
        "message": "Removed from matchmaking queue."
    })


# ============================================================
# MATCHMAKING — STATUS
# ============================================================

@ox_bp.route("/matchmaking/status", methods=["GET"])
def matchmaking_status():

    player, error = require_player()

    if error:
        return error

    queued = queue_col.find_one({
        "playerId": player["playerId"]
    })

    active_game = games_col.find_one({
        "players.playerId": player["playerId"],
        "status": "active"
    })

    return jsonify({
        "success": True,
        "waiting": bool(queued),
        "game": game_public(active_game) if active_game else None
    })


# ============================================================
# GET GAME
# ============================================================

@ox_bp.route("/game/<game_id>", methods=["GET"])
def get_game(game_id):

    player, error = require_player()

    if error:
        return error

    game = find_game_for_player(
        game_id,
        player["playerId"]
    )

    if not game:
        return jsonify({
            "success": False,
            "message": "Game not found."
        }), 404

    return jsonify({
        "success": True,
        "game": game_public(game)
    })

# ============================================================
# MAKE MOVE
# ============================================================

@ox_bp.route("/move", methods=["POST"])
def make_move():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    game_id = clean_string(data.get("gameId"))

    if not game_id:
        return jsonify({
            "success": False,
            "message": "Game ID is required."
        }), 400

    # --------------------------------------------------------
    # ROW / COLUMN
    # --------------------------------------------------------
    # The game is a fixed 5x5 board.
    # There are NO gameplay restrictions based on position.
    # Any EMPTY box can be played.
    # --------------------------------------------------------

    try:
        row = int(data.get("row"))
        col = int(data.get("col"))
    except (TypeError, ValueError):
        # Do not expose any "invalid board position" message.
        return jsonify({
            "success": False,
            "message": "Move could not be completed."
        }), 400

    game = find_game_for_player(
        game_id,
        player["playerId"]
    )

    if not game:
        return jsonify({
            "success": False,
            "message": "Game not found."
        }), 404

    if game.get("status") != "active":
        return jsonify({
            "success": False,
            "message": "Game has already ended."
        }), 400

    current_player = player_in_game(
        game,
        player["playerId"]
    )

    if not current_player:
        return jsonify({
            "success": False,
            "message": "Player is not part of this game."
        }), 403

    if game.get("currentTurn") != player["playerId"]:
        return jsonify({
            "success": False,
            "message": "It is not your turn."
        }), 400

    board = game.get("board")

    if not isinstance(board, list) or len(board) != BOARD_SIZE:
        return jsonify({
            "success": False,
            "message": "Move could not be completed."
        }), 500

    # --------------------------------------------------------
    # SAFE POSITION ACCESS
    # --------------------------------------------------------
    # No "Board position does not exist" error is ever returned.
    # The only user/gameplay invalid move is an occupied box.
    # --------------------------------------------------------

    try:
        cell = board[row][col]
    except (IndexError, TypeError):
        return jsonify({
            "success": False,
            "message": "Move could not be completed."
        }), 400

    if cell in ["X", "O"]:
        return jsonify({
            "success": False,
            "message": "This box is already occupied."
        }), 400

    symbol = current_player.get("symbol")

    if symbol not in ["X", "O"]:
        return jsonify({
            "success": False,
            "message": "Move could not be completed."
        }), 400

    # --------------------------------------------------------
    # PLACE SYMBOL
    # --------------------------------------------------------

    board[row][col] = symbol

    winning_line = find_winning_line(
        board,
        symbol
    )

    update_data = {
        "board": board,
        "updatedAt": now_utc()
    }

    # ========================================================
    # WIN
    # ========================================================

    if winning_line:

        update_data.update({
            "status": "finished",
            "winner": player["playerId"],
            "winningLine": winning_line,
            "result": "win",
            "finishedAt": now_utc()
        })

        updated = games_col.find_one_and_update(
            {
                "gameId": game_id,
                "status": "active",
                "currentTurn": player["playerId"]
            },
            {
                "$set": update_data
            },
            return_document=True
        )

        if not updated:
            return jsonify({
                "success": False,
                "message": "Move could not be completed. Reload the game."
            }), 409

        update_finished_stats(updated)

        return jsonify({
            "success": True,
            "game": game_public(updated)
        })

    # ========================================================
    # DRAW
    # ========================================================

    if board_full(board):

        update_data.update({
            "status": "finished",
            "winner": None,
            "winningLine": None,
            "result": "draw",
            "finishedAt": now_utc()
        })

        updated = games_col.find_one_and_update(
            {
                "gameId": game_id,
                "status": "active",
                "currentTurn": player["playerId"]
            },
            {
                "$set": update_data
            },
            return_document=True
        )

        if not updated:
            return jsonify({
                "success": False,
                "message": "Move could not be completed. Reload the game."
            }), 409

        update_finished_stats(updated)

        return jsonify({
            "success": True,
            "game": game_public(updated)
        })

    # ========================================================
    # SWITCH TURN
    # ========================================================

    opponent = None

    for p in game.get("players", []):
        if p.get("playerId") != player["playerId"]:
            opponent = p
            break

    if not opponent:
        return jsonify({
            "success": False,
            "message": "Opponent not found."
        }), 400

    opponent_id = opponent.get("playerId")

    if not opponent_id:
        return jsonify({
            "success": False,
            "message": "Move could not be completed."
        }), 400

    update_data["currentTurn"] = opponent_id

    # ========================================================
    # SAVE MOVE
    # ========================================================

    updated = games_col.find_one_and_update(
        {
            "gameId": game_id,
            "status": "active",
            "currentTurn": player["playerId"]
        },
        {
            "$set": update_data
        },
        return_document=True
    )

    if not updated:
        return jsonify({
            "success": False,
            "message": "Move could not be completed. Reload the game."
        }), 409

    return jsonify({
        "success": True,
        "message": "Move successful.",
        "game": game_public(updated)
    })


# RESIGN
# ============================================================

@ox_bp.route("/game/resign", methods=["POST"])
def resign():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    game_id = clean_string(data.get("gameId"))

    game = find_game_for_player(
        game_id,
        player["playerId"]
    )

    if not game:
        return jsonify({
            "success": False,
            "message": "Game not found."
        }), 404

    if game.get("status") != "active":
        return jsonify({
            "success": False,
            "message": "Game already ended."
        }), 400

    opponent = None

    for p in game.get("players", []):
        if p["playerId"] != player["playerId"]:
            opponent = p
            break

    if not opponent:
        return jsonify({
            "success": False,
            "message": "Opponent not found."
        }), 400

    updated = games_col.find_one_and_update(
        {
            "gameId": game_id,
            "status": "active"
        },
        {
            "$set": {
                "status": "finished",
                "winner": opponent["playerId"],
                "winningLine": None,
                "result": "resignation",
                "finishedAt": now_utc(),
                "updatedAt": now_utc()
            }
        },
        return_document=True
    )

    if not updated:
        return jsonify({
            "success": False,
            "message": "Game already changed."
        }), 409

    update_finished_stats(updated)

    return jsonify({
        "success": True,
        "game": game_public(updated)
    })


# ============================================================
# REMATCH
# ============================================================

@ox_bp.route("/rematch", methods=["POST"])
def rematch():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    old_game_id = clean_string(data.get("gameId"))

    old_game = find_game_for_player(
        old_game_id,
        player["playerId"]
    )

    if not old_game:
        return jsonify({
            "success": False,
            "message": "Game not found."
        }), 404

    if old_game.get("status") != "finished":
        return jsonify({
            "success": False,
            "message": "Game is not finished yet."
        }), 400

    opponent_data = None

    for p in old_game.get("players", []):
        if p["playerId"] != player["playerId"]:
            opponent_data = p
            break

    if not opponent_data:
        return jsonify({
            "success": False,
            "message": "Opponent not found."
        }), 400

    opponent = players_col.find_one({
        "playerId": opponent_data["playerId"]
    })

    if not opponent:
        return jsonify({
            "success": False,
            "message": "Opponent account no longer exists."
        }), 404

    if opponent.get("blocked") or opponent.get("suspended"):
        return jsonify({
            "success": False,
            "message": "Opponent is unavailable."
        }), 400

    existing = games_col.find_one({
        "rematchOf": old_game_id,
        "status": "active"
    })

    if existing:
        if player_in_game(
            existing,
            player["playerId"]
        ):
            return jsonify({
                "success": True,
                "game": game_public(existing)
            })

    new_game = make_game(
        player,
        opponent
    )

    games_col.update_one(
        {
            "gameId": new_game["gameId"]
        },
        {
            "$set": {
                "rematchOf": old_game_id
            }
        }
    )

    new_game["rematchOf"] = old_game_id

    return jsonify({
        "success": True,
        "game": game_public(new_game)
    })


# ============================================================
# PRIVATE ROOM — CREATE
# ============================================================

@ox_bp.route("/room/create", methods=["POST"])
def create_room():

    player, error = require_player()

    if error:
        return error

    room_id = generate_room_id()

    room = {
        "roomId": room_id,
        "hostPlayerId": player["playerId"],
        "players": [
            {
                "playerId": player["playerId"],
                "name": player["name"],
                "username": player["username"]
            }
        ],
        "status": "waiting",
        "gameId": None,
        "createdAt": now_utc()
    }

    rooms_col.insert_one(room)

    return jsonify({
        "success": True,
        "room": {
            **room,
            "createdAt": iso_date(room["createdAt"])
        }
    }), 201


# ============================================================
# PRIVATE ROOM — GET
# ============================================================

@ox_bp.route("/room/<room_id>", methods=["GET"])
def get_room(room_id):

    player, error = require_player()

    if error:
        return error

    room = rooms_col.find_one({
        "roomId": room_id.upper()
    })

    if not room:
        return jsonify({
            "success": False,
            "message": "Room not found."
        }), 404

    return jsonify({
        "success": True,
        "room": {
            "roomId": room.get("roomId"),
            "hostPlayerId": room.get("hostPlayerId"),
            "players": room.get("players", []),
            "status": room.get("status"),
            "gameId": room.get("gameId"),
            "createdAt": iso_date(room.get("createdAt"))
        }
    })


# ============================================================
# PRIVATE ROOM — JOIN
# ============================================================

@ox_bp.route("/room/join", methods=["POST"])
def join_room():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    room_id = clean_string(
        data.get("roomId")
    ).upper()

    if not room_id:
        return jsonify({
            "success": False,
            "message": "Room ID is required."
        }), 400

    room = rooms_col.find_one({
        "roomId": room_id
    })

    if not room:
        return jsonify({
            "success": False,
            "message": "Room not found."
        }), 404

    for p in room.get("players", []):
        if p["playerId"] == player["playerId"]:

            if room.get("gameId"):
                game = games_col.find_one({
                    "gameId": room["gameId"]
                })

                return jsonify({
                    "success": True,
                    "room": room,
                    "game": game_public(game) if game else None
                })

            return jsonify({
                "success": True,
                "room": room,
                "game": None
            })

    if len(room.get("players", [])) >= 2:
        return jsonify({
            "success": False,
            "message": "Room is already full."
        }), 400

    updated = rooms_col.find_one_and_update(
        {
            "roomId": room_id,
            "status": "waiting",
            "players.1": {
                "$exists": False
            }
        },
        {
            "$push": {
                "players": {
                    "playerId": player["playerId"],
                    "name": player["name"],
                    "username": player["username"]
                }
            }
        },
        return_document=True
    )

    if not updated:
        return jsonify({
            "success": False,
            "message": "Unable to join room."
        }), 409

    host = players_col.find_one({
        "playerId": updated["hostPlayerId"]
    })

    if not host:
        return jsonify({
            "success": False,
            "message": "Room host not found."
        }), 500

    joined_players = updated["players"]

    second_player = players_col.find_one({
        "playerId": joined_players[1]["playerId"]
    })

    game = make_game(
        host,
        second_player
    )

    rooms_col.update_one(
        {
            "roomId": room_id
        },
        {
            "$set": {
                "status": "active",
                "gameId": game["gameId"]
            }
        }
    )

    return jsonify({
        "success": True,
        "room": {
            **updated,
            "status": "active",
            "gameId": game["gameId"],
            "createdAt": iso_date(updated.get("createdAt"))
        },
        "game": game_public(game)
    })


# ============================================================
# ROOM — LEAVE
# ============================================================

@ox_bp.route("/room/leave", methods=["POST"])
def leave_room():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    room_id = clean_string(
        data.get("roomId")
    ).upper()

    room = rooms_col.find_one({
        "roomId": room_id
    })

    if not room:
        return jsonify({
            "success": False,
            "message": "Room not found."
        }), 404

    if room.get("hostPlayerId") == player["playerId"]:
        return jsonify({
            "success": False,
            "message": "Room owner cannot leave the room."
        }), 400

    rooms_col.update_one(
        {
            "roomId": room_id
        },
        {
            "$pull": {
                "players": {
                    "playerId": player["playerId"]
                }
            }
        }
    )

    return jsonify({
        "success": True,
        "message": "Left room."
    })


# ============================================================
# GROUP CREATE
# ============================================================

@ox_bp.route("/group/create", methods=["POST"])
def create_group():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    group_name = clean_string(
        data.get("name")
    )

    if not group_name:
        return jsonify({
            "success": False,
            "message": "Group name is required."
        }), 400

    if len(group_name) > MAX_GROUP_NAME_LENGTH:
        return jsonify({
            "success": False,
            "message": "Group name is too long."
        }), 400

    group_id = generate_group_id()

    group = {
        "groupId": group_id,
        "name": group_name,
        "ownerId": player["playerId"],
        "members": [
            {
                "playerId": player["playerId"],
                "name": player["name"],
                "username": player["username"]
            }
        ],
        "createdAt": now_utc()
    }

    groups_col.insert_one(group)

    return jsonify({
        "success": True,
        "group": {
            **group,
            "createdAt": iso_date(group["createdAt"])
        }
    }), 201


# ============================================================
# LIST GROUPS
# ============================================================

@ox_bp.route("/groups", methods=["GET"])
def list_groups():

    groups = []

    for group in groups_col.find().sort(
        "createdAt",
        DESCENDING
    ):

        groups.append({
            "groupId": group.get("groupId"),
            "name": group.get("name"),
            "ownerId": group.get("ownerId"),
            "members": group.get("members", []),
            "createdAt": iso_date(group.get("createdAt"))
        })

    return jsonify({
        "success": True,
        "groups": groups
    })


# ============================================================
# GET GROUP
# ============================================================

@ox_bp.route("/group/<group_id>", methods=["GET"])
def get_group(group_id):

    group = groups_col.find_one({
        "groupId": group_id
    })

    if not group:
        return jsonify({
            "success": False,
            "message": "Group not found."
        }), 404

    return jsonify({
        "success": True,
        "group": {
            "groupId": group.get("groupId"),
            "name": group.get("name"),
            "ownerId": group.get("ownerId"),
            "members": group.get("members", []),
            "createdAt": iso_date(group.get("createdAt"))
        }
    })


# ============================================================
# GROUP JOIN
# ============================================================

@ox_bp.route("/group/join", methods=["POST"])
def join_group():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    group_id = clean_string(
        data.get("groupId")
    )

    group = groups_col.find_one({
        "groupId": group_id
    })

    if not group:
        return jsonify({
            "success": False,
            "message": "Group not found."
        }), 404

    for member in group.get("members", []):

        if member["playerId"] == player["playerId"]:

            return jsonify({
                "success": True,
                "message": "Already a member.",
                "group": group
            })

    groups_col.update_one(
        {
            "groupId": group_id
        },
        {
            "$push": {
                "members": {
                    "playerId": player["playerId"],
                    "name": player["name"],
                    "username": player["username"]
                }
            }
        }
    )

    group = groups_col.find_one({
        "groupId": group_id
    })

    return jsonify({
        "success": True,
        "message": "Joined group.",
        "group": group
    })


# ============================================================
# GROUP LEAVE
# ============================================================

@ox_bp.route("/group/leave", methods=["POST"])
def leave_group():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    group_id = clean_string(
        data.get("groupId")
    )

    group = groups_col.find_one({
        "groupId": group_id
    })

    if not group:
        return jsonify({
            "success": False,
            "message": "Group not found."
        }), 404

    if group.get("ownerId") == player["playerId"]:
        return jsonify({
            "success": False,
            "message": "Group owner cannot leave the group."
        }), 400

    groups_col.update_one(
        {
            "groupId": group_id
        },
        {
            "$pull": {
                "members": {
                    "playerId": player["playerId"]
                }
            }
        }
    )

    return jsonify({
        "success": True,
        "message": "Left group."
    })


# ============================================================
# DIRECT PLAYER REQUEST
# ============================================================

@ox_bp.route("/request/send", methods=["POST"])
def send_request():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    receiver_id = clean_string(
        data.get("receiverId")
    )

    if not receiver_id:
        return jsonify({
            "success": False,
            "message": "receiverId is required."
        }), 400

    if receiver_id == player["playerId"]:
        return jsonify({
            "success": False,
            "message": "You cannot send a request to yourself."
        }), 400

    receiver = players_col.find_one({
        "playerId": receiver_id
    })

    if not receiver:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    existing = requests_col.find_one({
        "type": "player",
        "senderId": player["playerId"],
        "receiverId": receiver_id,
        "status": "pending"
    })

    if existing:
        return jsonify({
            "success": False,
            "message": "Request already pending."
        }), 409

    req = {
        "requestId": generate_request_id(),
        "type": "player",
        "senderId": player["playerId"],
        "receiverId": receiver_id,
        "status": "pending",
        "createdAt": now_utc()
    }

    requests_col.insert_one(req)

    return jsonify({
        "success": True,
        "request": {
            **req,
            "createdAt": iso_date(req["createdAt"])
        }
    }), 201


# ============================================================
# GROUP GAME REQUEST
# ============================================================

@ox_bp.route("/group/request/send", methods=["POST"])
def send_group_request():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    group_id = clean_string(
        data.get("groupId")
    )

    group = groups_col.find_one({
        "groupId": group_id
    })

    if not group:
        return jsonify({
            "success": False,
            "message": "Group not found."
        }), 404

    if not any(
        m["playerId"] == player["playerId"]
        for m in group.get("members", [])
    ):
        return jsonify({
            "success": False,
            "message": "You are not a member of this group."
        }), 403

    requests_created = 0

    for member in group.get("members", []):

        member_id = member["playerId"]

        if member_id == player["playerId"]:
            continue

        existing = requests_col.find_one({
            "type": "player",
            "senderId": player["playerId"],
            "receiverId": member_id,
            "status": "pending"
        })

        if existing:
            continue

        requests_col.insert_one({
            "requestId": generate_request_id(),
            "type": "player",
            "senderId": player["playerId"],
            "receiverId": member_id,
            "status": "pending",
            "groupId": group_id,
            "createdAt": now_utc()
        })

        requests_created += 1

    return jsonify({
        "success": True,
        "message": "Group requests sent.",
        "count": requests_created
    })


# ============================================================
# RECEIVED REQUESTS
# ============================================================

@ox_bp.route("/requests/received", methods=["GET"])
def received_requests():

    player, error = require_player()

    if error:
        return error

    requests = []

    for req in requests_col.find({
        "receiverId": player["playerId"],
        "status": "pending"
    }).sort(
        "createdAt",
        DESCENDING
    ):

        requests.append({
            **req,
            "_id": str(req["_id"]),
            "createdAt": iso_date(req.get("createdAt"))
        })

    return jsonify({
        "success": True,
        "requests": requests
    })


# ============================================================
# SENT REQUESTS
# ============================================================

@ox_bp.route("/requests/sent", methods=["GET"])
def sent_requests():

    player, error = require_player()

    if error:
        return error

    requests = []

    for req in requests_col.find({
        "senderId": player["playerId"]
    }).sort(
        "createdAt",
        DESCENDING
    ):

        requests.append({
            **req,
            "_id": str(req["_id"]),
            "createdAt": iso_date(req.get("createdAt"))
        })

    return jsonify({
        "success": True,
        "requests": requests
    })


# ============================================================
# ACCEPT REQUEST
# ============================================================

@ox_bp.route("/request/accept", methods=["POST"])
def accept_request():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    request_id = clean_string(
        data.get("requestId")
    )

    req = requests_col.find_one({
        "requestId": request_id,
        "receiverId": player["playerId"],
        "status": "pending"
    })

    if not req:
        return jsonify({
            "success": False,
            "message": "Request not found."
        }), 404

    sender = players_col.find_one({
        "playerId": req["senderId"]
    })

    if not sender:
        return jsonify({
            "success": False,
            "message": "Sender not found."
        }), 404

    if sender.get("blocked") or sender.get("suspended"):
        return jsonify({
            "success": False,
            "message": "Sender is unavailable."
        }), 400

    requests_col.update_one(
        {
            "requestId": request_id,
            "status": "pending"
        },
        {
            "$set": {
                "status": "accepted",
                "respondedAt": now_utc()
            }
        }
    )

    game = make_game(
        player,
        sender
    )

    return jsonify({
        "success": True,
        "message": "Request accepted.",
        "game": game_public(game)
    })


# ============================================================
# REJECT REQUEST
# ============================================================

@ox_bp.route("/request/reject", methods=["POST"])
def reject_request():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    request_id = clean_string(
        data.get("requestId")
    )

    updated = requests_col.update_one(
        {
            "requestId": request_id,
            "receiverId": player["playerId"],
            "status": "pending"
        },
        {
            "$set": {
                "status": "rejected",
                "respondedAt": now_utc()
            }
        }
    )

    if updated.matched_count == 0:
        return jsonify({
            "success": False,
            "message": "Request not found."
        }), 404

    return jsonify({
        "success": True,
        "message": "Request rejected."
    })


# ============================================================
# CANCEL REQUEST
# ============================================================

@ox_bp.route("/request/cancel", methods=["POST"])
def cancel_request():

    player, error = require_player()

    if error:
        return error

    data = request.get_json(silent=True) or {}

    request_id = clean_string(
        data.get("requestId")
    )

    updated = requests_col.update_one(
        {
            "requestId": request_id,
            "senderId": player["playerId"],
            "status": "pending"
        },
        {
            "$set": {
                "status": "cancelled",
                "respondedAt": now_utc()
            }
        }
    )

    if updated.matched_count == 0:
        return jsonify({
            "success": False,
            "message": "Request not found."
        }), 404

    return jsonify({
        "success": True,
        "message": "Request cancelled."
    })


# ============================================================
# LEADERBOARD
# ============================================================

@ox_bp.route("/leaderboard", methods=["GET"])
def leaderboard():

    limit = request.args.get(
        "limit",
        default=100,
        type=int
    )

    limit = max(
        1,
        min(limit, 500)
    )

    players = list(
        players_col.find({
            "blocked": {
                "$ne": True
            }
        })
        .sort([
            ("wins", DESCENDING),
            ("winRate", DESCENDING)
        ])
        .limit(limit)
    )

    result = []

    for index, player in enumerate(players, start=1):

        result.append({
            "rank": index,
            **sanitize_player(player)
        })

    return jsonify({
        "success": True,
        "leaderboard": result
    })


# ============================================================
# STATS
# ============================================================

@ox_bp.route("/stats/<player_id>", methods=["GET"])
def player_stats(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    return jsonify({
        "success": True,
        "stats": sanitize_player(player)
    })


# ============================================================
# CURRENT ACTIVE GAME
# ============================================================

@ox_bp.route("/my-game", methods=["GET"])
def my_game():

    player, error = require_player()

    if error:
        return error

    game = games_col.find_one(
        {
            "players.playerId": player["playerId"],
            "status": "active"
        },
        sort=[
            ("updatedAt", DESCENDING)
        ]
    )

    return jsonify({
        "success": True,
        "game": game_public(game) if game else None
    })


# ============================================================
# GAME HISTORY
# ============================================================

@ox_bp.route("/history", methods=["GET"])
def history():

    player, error = require_player()

    if error:
        return error

    limit = request.args.get(
        "limit",
        default=50,
        type=int
    )

    limit = max(
        1,
        min(limit, 200)
    )

    games = games_col.find({
        "players.playerId": player["playerId"],
        "status": "finished"
    }).sort(
        "finishedAt",
        DESCENDING
    ).limit(limit)

    result = [
        game_public(game)
        for game in games
    ]

    return jsonify({
        "success": True,
        "history": result
    })

# ============================================================
# ADMIN — ALL USERS
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users", methods=["GET"])
def admin_users():

    search = clean_string(
        request.args.get("search")
    )

    query = {}

    if search:
        query = {
            "$or": [
                {
                    "playerId": {
                        "$regex": search,
                        "$options": "i"
                    }
                },
                {
                    "username": {
                        "$regex": search,
                        "$options": "i"
                    }
                },
                {
                    "name": {
                        "$regex": search,
                        "$options": "i"
                    }
                }
            ]
        }

    players = players_col.find(
        query
    ).sort(
        "createdAt",
        DESCENDING
    )

    result = []

    for player in players:
        result.append(
            sanitize_player(player)
        )

    return jsonify({
        "success": True,
        "count": len(result),
        "users": result
    })


# ============================================================
# ADMIN — SINGLE USER
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>", methods=["GET"])
def admin_get_user(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    return jsonify({
        "success": True,
        "user": sanitize_player(player)
    })


# ============================================================
# ADMIN — EDIT WINS / LOSSES / DRAWS
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>/stats", methods=["PUT"])
def admin_edit_stats(player_id):

    data = request.get_json(silent=True) or {}

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    update = {}

    for field in [
        "wins",
        "losses",
        "draws"
    ]:

        if field in data:

            try:
                value = int(data[field])
            except Exception:
                return jsonify({
                    "success": False,
                    "message": f"{field} must be a number."
                }), 400

            if value < 0:
                return jsonify({
                    "success": False,
                    "message": f"{field} cannot be negative."
                }), 400

            update[field] = value

    if not update:
        return jsonify({
            "success": False,
            "message": "No statistics supplied."
        }), 400

    current_wins = update.get(
        "wins",
        int(player.get("wins", 0))
    )

    current_losses = update.get(
        "losses",
        int(player.get("losses", 0))
    )

    current_draws = update.get(
        "draws",
        int(player.get("draws", 0))
    )

    update["gamesPlayed"] = (
        current_wins +
        current_losses +
        current_draws
    )

    players_col.update_one(
        {
            "playerId": player_id
        },
        {
            "$set": update
        }
    )

    updated_player = players_col.find_one({
        "playerId": player_id
    })

    return jsonify({
        "success": True,
        "message": "Player statistics updated.",
        "user": sanitize_player(updated_player)
    })


# ============================================================
# ADMIN — BLOCK
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>/block", methods=["POST"])
def admin_block_user(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    players_col.update_one(
        {
            "playerId": player_id
        },
        {
            "$set": {
                "blocked": True,
                "blockedAt": now_utc()
            }
        }
    )

    # Remove from matchmaking
    queue_col.delete_one({
        "playerId": player_id
    })

    # Invalidate sessions
    sessions_col.delete_many({
        "playerId": player_id
    })

    return jsonify({
        "success": True,
        "message": "Player blocked successfully."
    })


# ============================================================
# ADMIN — UNBLOCK
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>/unblock", methods=["POST"])
def admin_unblock_user(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    players_col.update_one(
        {
            "playerId": player_id
        },
        {
            "$set": {
                "blocked": False
            },
            "$unset": {
                "blockedAt": ""
            }
        }
    )

    return jsonify({
        "success": True,
        "message": "Player unblocked successfully."
    })


# ============================================================
# ADMIN — SUSPEND
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>/suspend", methods=["POST"])
def admin_suspend_user(player_id):

    data = request.get_json(silent=True) or {}

    reason = clean_string(
        data.get("reason")
    )

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    players_col.update_one(
        {
            "playerId": player_id
        },
        {
            "$set": {
                "suspended": True,
                "suspensionReason": reason,
                "suspendedAt": now_utc()
            }
        }
    )

    queue_col.delete_one({
        "playerId": player_id
    })

    sessions_col.delete_many({
        "playerId": player_id
    })

    return jsonify({
        "success": True,
        "message": "Player suspended successfully."
    })


# ============================================================
# ADMIN — UNSUSPEND
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>/unsuspend", methods=["POST"])
def admin_unsuspend_user(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    players_col.update_one(
        {
            "playerId": player_id
        },
        {
            "$set": {
                "suspended": False
            },
            "$unset": {
                "suspensionReason": "",
                "suspendedAt": ""
            }
        }
    )

    return jsonify({
        "success": True,
        "message": "Player suspension removed."
    })


# ============================================================
# ADMIN — DELETE USER
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/users/<player_id>", methods=["DELETE"])
def admin_delete_user(player_id):

    player = players_col.find_one({
        "playerId": player_id
    })

    if not player:
        return jsonify({
            "success": False,
            "message": "Player not found."
        }), 404

    players_col.delete_one({
        "playerId": player_id
    })

    queue_col.delete_one({
        "playerId": player_id
    })

    sessions_col.delete_many({
        "playerId": player_id
    })

    return jsonify({
        "success": True,
        "message": "Player deleted."
    })


# ============================================================
# ADMIN — DASHBOARD STATS
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():

    total_users = players_col.count_documents({})

    active_users = players_col.count_documents({
        "blocked": {
            "$ne": True
        },
        "suspended": {
            "$ne": True
        }
    })

    blocked_users = players_col.count_documents({
        "blocked": True
    })

    suspended_users = players_col.count_documents({
        "suspended": True
    })

    active_games = games_col.count_documents({
        "status": "active"
    })

    finished_games = games_col.count_documents({
        "status": "finished"
    })

    waiting_players = queue_col.count_documents({})

    return jsonify({
        "success": True,
        "dashboard": {
            "totalUsers": total_users,
            "activeUsers": active_users,
            "blockedUsers": blocked_users,
            "suspendedUsers": suspended_users,
            "activeGames": active_games,
            "finishedGames": finished_games,
            "waitingPlayers": waiting_players
        }
    })


# ============================================================
# ADMIN — GAME LIST
# NO AUTHENTICATION
# ============================================================

@ox_bp.route("/admin/games", methods=["GET"])
def admin_games():

    limit = request.args.get(
        "limit",
        default=100,
        type=int
    )

    limit = max(
        1,
        min(limit, 500)
    )

    games = games_col.find().sort(
        "createdAt",
        DESCENDING
    ).limit(limit)

    result = [
        game_public(game)
        for game in games
    ]

    return jsonify({
        "success": True,
        "count": len(result),
        "games": result
    })
# ============================================================
# HEALTH
# ============================================================

@ox_bp.route("/health", methods=["GET"])
def health():

    mongo_ok = False

    try:
        ox_client.admin.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False

    return jsonify({
        "success": True,
        "service": "OX Game API",
        "database": OX_DB_NAME,
        "mongodb": "connected" if mongo_ok else "disconnected",
        "status": "online" if mongo_ok else "degraded",
        "timestamp": now_utc().isoformat()
    })


# ============================================================
# MATCHMAKING CLEANUP
# ============================================================

@ox_bp.route("/matchmaking/cleanup", methods=["POST"])
def matchmaking_cleanup():

    cutoff = now_utc() - timedelta(
        minutes=10
    )

    result = queue_col.delete_many({
        "joinedAt": {
            "$lt": cutoff
        }
    })

    return jsonify({
        "success": True,
        "removed": result.deleted_count
    })


# ============================================================
# REQUEST CLEANUP
# ============================================================

@ox_bp.route("/requests/cleanup", methods=["POST"])
def requests_cleanup():

    cutoff = now_utc() - timedelta(
        days=30
    )

    result = requests_col.delete_many({
        "createdAt": {
            "$lt": cutoff
        },
        "status": {
            "$ne": "pending"
        }
    })

    return jsonify({
        "success": True,
        "removed": result.deleted_count
    })


# ============================================================
# END OF OX ROUTES
# ============================================================