# ============================================================
# OX GAME BACKEND
# File: routes/ox.py
#
# COMPLETELY SEPARATE OX GAME BACKEND
#
# Flask + MongoDB
#
# Features:
#   1. Player registration
#   2. Persistent playerId
#   3. Random matchmaking
#   4. 5x5 OX board
#   5. Five consecutive X/O = WIN
#   6. Horizontal / Vertical / Diagonal wins
#   7. Draw support
#   8. Private rooms
#   9. Groups
#  10. Direct game requests
#  11. Group game requests
#  12. Accept / reject / cancel requests
#  13. Leaderboard
#  14. Player statistics
#  15. Game history
#  16. Rematch
#  17. Resign
#  18. Matchmaking cleanup
#  19. Request cleanup
#  20. Health check
#
# Blueprint prefix:
#
#       /api/ox
#
# Example:
#
#       POST /api/ox/player/register
#       POST /api/ox/matchmaking/join
#       POST /api/ox/move
#       GET  /api/ox/game/<game_id>
#       GET  /api/ox/leaderboard
#
# ============================================================

from flask import Blueprint, request, jsonify

from pymongo import (
    MongoClient,
    ASCENDING,
    DESCENDING
)

from datetime import datetime, timezone, timedelta

import os
import uuid
import random
import string
import re


# ============================================================
# BLUEPRINT
# ============================================================

ox_bp = Blueprint(
    "ox",
    __name__,
    url_prefix="/api/ox"
)


# ============================================================
# OX MONGODB CONFIGURATION
#
# THIS DATABASE IS COMPLETELY SEPARATE.
#
# REQUIRED RENDER ENV:
#
# MONGO_URI=mongodb+srv://...
#
# OPTIONAL:
#
# MONGO_DB_NAME=ox_game
#
# ============================================================

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise RuntimeError(
        "MONGO_URI environment variable is not configured for OX Game."
    )


OX_DB_NAME = os.getenv(
    "MONGO_DB_NAME",
    "ox_game"
)


# ============================================================
# MONGODB CLIENT
# ============================================================

ox_client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000
)


# ============================================================
# OX DATABASE
# ============================================================

ox_db = ox_client[OX_DB_NAME]


# ============================================================
# COLLECTIONS
#
# ALL COLLECTIONS BELONG ONLY TO OX GAME DATABASE.
# ============================================================

players_col = ox_db["players"]

games_col = ox_db["games"]

rooms_col = ox_db["rooms"]

queue_col = ox_db["matchmaking"]

groups_col = ox_db["groups"]

requests_col = ox_db["requests"]


# ============================================================
# CONSTANTS
# ============================================================

BOARD_SIZE = 5

WIN_LENGTH = 5

MAX_NAME_LENGTH = 40

MAX_GROUP_NAME_LENGTH = 60

MAX_ROOM_ID_LENGTH = 30

VALID_SYMBOLS = {
    "X",
    "O"
}


# ============================================================
# MONGODB CONNECTION TEST
# ============================================================

try:

    ox_client.admin.command("ping")

    print("============================================")
    print("OX GAME MONGODB CONNECTED")
    print("============================================")
    print(f"Database: {OX_DB_NAME}")
    print("Collections:")
    print(" - players")
    print(" - games")
    print(" - rooms")
    print(" - matchmaking")
    print(" - groups")
    print(" - requests")
    print("============================================")

except Exception as e:

    print("============================================")
    print("OX GAME MONGODB CONNECTION FAILED")
    print("============================================")
    print(str(e))
    print("============================================")


# ============================================================
# DATABASE INDEXES
# ============================================================

try:

    players_col.create_index(
        [("playerId", ASCENDING)],
        unique=True
    )

    players_col.create_index(
        [("nameLower", ASCENDING)]
    )

    games_col.create_index(
        [("gameId", ASCENDING)],
        unique=True
    )

    games_col.create_index(
        [("status", ASCENDING)]
    )

    games_col.create_index(
        [("players.playerId", ASCENDING)]
    )

    rooms_col.create_index(
        [("roomId", ASCENDING)],
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

    requests_col.create_index(
        [
            ("toPlayerId", ASCENDING),
            ("status", ASCENDING)
        ]
    )

    requests_col.create_index(
        [
            ("fromPlayerId", ASCENDING),
            ("status", ASCENDING)
        ]
    )

    queue_col.create_index(
        [("playerId", ASCENDING)],
        unique=True
    )

    queue_col.create_index(
        [("joinedAt", ASCENDING)]
    )

except Exception as e:

    print("OX index creation warning:", str(e))


# ============================================================
# GENERAL HELPERS
# ============================================================

def now():
    return datetime.now(timezone.utc)


def make_id(prefix=""):
    return prefix + uuid.uuid4().hex


# ============================================================
# NAME CLEANING
# ============================================================

def clean_name(name):

    if not isinstance(name, str):
        return ""

    name = name.strip()

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name[:MAX_NAME_LENGTH]


def clean_group_name(name):

    if not isinstance(name, str):
        return ""

    name = name.strip()

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name[:MAX_GROUP_NAME_LENGTH]


def clean_room_id(room_id):

    if not isinstance(room_id, str):
        return ""

    room_id = room_id.strip().upper()

    room_id = re.sub(
        r"[^A-Z0-9_-]",
        "",
        room_id
    )

    return room_id[:MAX_ROOM_ID_LENGTH]


# ============================================================
# PLAYER PUBLIC DATA
# ============================================================

def player_public(player):

    if not player:
        return None

    return {
        "playerId": player.get("playerId"),
        "name": player.get("name"),

        "wins": int(
            player.get("wins", 0)
        ),

        "losses": int(
            player.get("losses", 0)
        ),

        "draws": int(
            player.get("draws", 0)
        ),

        "games": int(
            player.get("games", 0)
        )
    }


# ============================================================
# GET PLAYER
# ============================================================

def get_player(player_id):

    if not player_id:
        return None

    return players_col.find_one({
        "playerId": str(player_id)
    })


# ============================================================
# REQUIRE PLAYER
# ============================================================

def require_player(data):

    player_id = data.get("playerId")

    if not player_id:

        return None, jsonify({
            "success": False,
            "error": "playerId is required."
        }), 400

    player = get_player(player_id)

    if not player:

        return None, jsonify({
            "success": False,
            "error": "Player not found. Register first."
        }), 404

    return player, None, None


# ============================================================
# ENSURE PLAYER
# ============================================================

def ensure_player(
    player_id=None,
    name=None
):

    if not player_id:

        player_id = make_id("p_")

    player_id = str(player_id).strip()

    player = get_player(player_id)

    if player:

        if name:

            clean = clean_name(name)

            if clean and clean != player.get("name"):

                players_col.update_one(
                    {
                        "playerId": player_id
                    },
                    {
                        "$set": {
                            "name": clean,
                            "nameLower": clean.lower(),
                            "updatedAt": now()
                        }
                    }
                )

        return get_player(player_id)

    clean = clean_name(
        name or "Player"
    )

    if not clean:
        clean = "Player"

    document = {

        "playerId": player_id,

        "name": clean,

        "nameLower": clean.lower(),

        "wins": 0,

        "losses": 0,

        "draws": 0,

        "games": 0,

        "createdAt": now(),

        "updatedAt": now(),

        "lastSeen": now()
    }

    try:

        players_col.insert_one(
            document
        )

    except Exception:

        existing = get_player(
            player_id
        )

        if existing:
            return existing

        raise

    return document


# ============================================================
# TOUCH PLAYER
# ============================================================

def touch_player(player_id):

    try:

        players_col.update_one(
            {
                "playerId": player_id
            },
            {
                "$set": {
                    "lastSeen": now(),
                    "updatedAt": now()
                }
            }
        )

    except Exception:
        pass


# ============================================================
# BOARD
# ============================================================

def empty_board():

    return [
        [
            None
            for _ in range(BOARD_SIZE)
        ]
        for _ in range(BOARD_SIZE)
    ]


def valid_cell(row, col):

    return (
        isinstance(row, int)
        and isinstance(col, int)
        and 0 <= row < BOARD_SIZE
        and 0 <= col < BOARD_SIZE
    )


def board_full(board):

    for row in board:

        for cell in row:

            if cell is None:
                return False

    return True


# ============================================================
# WIN CHECK
# ============================================================

def find_winning_line(
    board,
    row,
    col,
    symbol
):

    directions = [

        (0, 1),

        (1, 0),

        (1, 1),

        (1, -1)
    ]

    for dr, dc in directions:

        cells = []

        r = row
        c = col

        # --------------------------------------------
        # MOVE BACKWARDS
        # --------------------------------------------

        while (

            0 <= r - dr < BOARD_SIZE

            and

            0 <= c - dc < BOARD_SIZE

            and

            board[r - dr][c - dc] == symbol
        ):

            r -= dr
            c -= dc

        # --------------------------------------------
        # MOVE FORWARD
        # --------------------------------------------

        while (

            0 <= r < BOARD_SIZE

            and

            0 <= c < BOARD_SIZE

            and

            board[r][c] == symbol
        ):

            cells.append([
                r,
                c
            ])

            r += dr
            c += dc

        if len(cells) >= WIN_LENGTH:

            return cells

    return None


def check_winner(
    board,
    row,
    col,
    symbol
):

    return find_winning_line(
        board,
        row,
        col,
        symbol
    )


# ============================================================
# SERIALIZE GAME
# ============================================================

def serialize_game(game):

    if not game:
        return None

    return {

        "gameId": game.get(
            "gameId"
        ),

        "board": game.get(
            "board"
        ),

        "boardSize": BOARD_SIZE,

        "winLength": WIN_LENGTH,

        "players": game.get(
            "players",
            []
        ),

        "currentTurn": game.get(
            "currentTurn"
        ),

        "status": game.get(
            "status"
        ),

        "winner": game.get(
            "winner"
        ),

        "winnerSymbol": game.get(
            "winnerSymbol"
        ),

        "loser": game.get(
            "loser"
        ),

        "draw": bool(
            game.get(
                "draw",
                False
            )
        ),

        "winningCells": game.get(
            "winningCells",
            []
        ),

        "roomId": game.get(
            "roomId"
        ),

        "groupId": game.get(
            "groupId"
        ),

        "createdAt": game.get(
            "createdAt"
        ),

        "updatedAt": game.get(
            "updatedAt"
        )
    }


# ============================================================
# CREATE GAME
# ============================================================

def create_game(
    player1_id,
    player2_id,
    room_id=None,
    group_id=None
):

    if player1_id == player2_id:

        raise ValueError(
            "A player cannot play against themselves."
        )

    p1 = get_player(
        player1_id
    )

    p2 = get_player(
        player2_id
    )

    if not p1 or not p2:

        raise ValueError(
            "Both players must exist."
        )

    # --------------------------------------------
    # RANDOM X / O
    # --------------------------------------------

    if random.choice(
        [True, False]
    ):

        x_player = player1_id
        o_player = player2_id

    else:

        x_player = player2_id
        o_player = player1_id

    x_name = (
        p1["name"]
        if p1["playerId"] == x_player
        else p2["name"]
    )

    o_name = (
        p1["name"]
        if p1["playerId"] == o_player
        else p2["name"]
    )

    game_id = make_id(
        "game_"
    )

    game = {

        "gameId": game_id,

        "board": empty_board(),

        "players": [

            {
                "playerId": x_player,
                "name": x_name,
                "symbol": "X"
            },

            {
                "playerId": o_player,
                "name": o_name,
                "symbol": "O"
            }
        ],

        # X always starts.
        "currentTurn": x_player,

        "status": "playing",

        "winner": None,

        "winnerSymbol": None,

        "loser": None,

        "draw": False,

        "winningCells": [],

        "roomId": room_id,

        "groupId": group_id,

        "createdAt": now(),

        "updatedAt": now()
    }

    games_col.insert_one(
        game
    )

    # Remove players from queue.
    queue_col.delete_many({
        "playerId": {
            "$in": [
                player1_id,
                player2_id
            ]
        }
    })

    return game


# ============================================================
# GET PLAYER SYMBOL
# ============================================================

def get_player_symbol(
    game,
    player_id
):

    for player in game.get(
        "players",
        []
    ):

        if player.get(
            "playerId"
        ) == player_id:

            return player.get(
                "symbol"
            )

    return None


# ============================================================
# GET OPPONENT
# ============================================================

def get_opponent(
    game,
    player_id
):

    for player in game.get(
        "players",
        []
    ):

        if player.get(
            "playerId"
        ) != player_id:

            return player

    return None


# ============================================================
# PLAYER REGISTER
# ============================================================

@ox_bp.route(
    "/player/register",
    methods=["POST"]
)
def register_player():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        name = clean_name(
            data.get(
                "name",
                ""
            )
        )

        player_id = data.get(
            "playerId"
        )

        if not name:

            return jsonify({
                "success": False,
                "error": "Name is required."
            }), 400

        if len(name) < 2:

            return jsonify({
                "success": False,
                "error": "Name must contain at least 2 characters."
            }), 400

        if player_id:

            player_id = str(
                player_id
            ).strip()

        player = ensure_player(
            player_id,
            name
        )

        touch_player(
            player["playerId"]
        )

        return jsonify({

            "success": True,

            "message":
                "Player registered successfully.",

            "player":
                player_public(
                    get_player(
                        player["playerId"]
                    )
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GET PLAYER
# ============================================================

@ox_bp.route(
    "/player/<player_id>",
    methods=["GET"]
)
def get_player_route(
    player_id
):

    try:

        player = get_player(
            player_id
        )

        if not player:

            return jsonify({
                "success": False,
                "error": "Player not found."
            }), 404

        return jsonify({

            "success": True,

            "player":
                player_public(
                    player
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# RANDOM MATCHMAKING JOIN
# ============================================================

@ox_bp.route(
    "/matchmaking/join",
    methods=["POST"]
)
def join_matchmaking():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        player_id = player[
            "playerId"
        ]

        touch_player(
            player_id
        )

        # --------------------------------------------
        # CHECK ACTIVE GAME
        # --------------------------------------------

        existing_game = games_col.find_one({

            "players.playerId":
                player_id,

            "status":
                "playing"
        })

        if existing_game:

            return jsonify({

                "success": True,

                "matched": True,

                "waiting": False,

                "message":
                    "You already have an active game.",

                "game":
                    serialize_game(
                        existing_game
                    )
            })

        # --------------------------------------------
        # REMOVE OLD QUEUE ENTRY
        # --------------------------------------------

        queue_col.delete_many({
            "playerId":
                player_id
        })

        # --------------------------------------------
        # FIND OLDEST WAITING PLAYER
        # --------------------------------------------

        opponent_entry = queue_col.find_one(
            {
                "playerId": {
                    "$ne":
                        player_id
                }
            },
            sort=[
                (
                    "joinedAt",
                    ASCENDING
                )
            ]
        )

        if opponent_entry:

            opponent_id = opponent_entry[
                "playerId"
            ]

            opponent = get_player(
                opponent_id
            )

            if not opponent:

                queue_col.delete_one({
                    "_id":
                        opponent_entry["_id"]
                })

                return jsonify({

                    "success": True,

                    "matched": False,

                    "waiting": True,

                    "message":
                        "Waiting for another player."
                })

            # ----------------------------------------
            # CHECK OPPONENT ACTIVE GAME
            # ----------------------------------------

            active_opponent_game = games_col.find_one({

                "players.playerId":
                    opponent_id,

                "status":
                    "playing"
            })

            if active_opponent_game:

                queue_col.delete_one({
                    "_id":
                        opponent_entry["_id"]
                })

                return jsonify({

                    "success": True,

                    "matched": False,

                    "waiting": True,

                    "message":
                        "Waiting for another player."
                })

            # ----------------------------------------
            # CREATE GAME
            # ----------------------------------------

            game = create_game(
                player_id,
                opponent_id
            )

            return jsonify({

                "success": True,

                "matched": True,

                "waiting": False,

                "message":
                    "Opponent found!",

                "game":
                    serialize_game(
                        game
                    )
            })

        # --------------------------------------------
        # NOBODY WAITING
        # --------------------------------------------

        queue_col.insert_one({

            "playerId":
                player_id,

            "name":
                player["name"],

            "joinedAt":
                now()
        })

        return jsonify({

            "success": True,

            "matched": False,

            "waiting": True,

            "message":
                "Waiting for an opponent..."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# LEAVE MATCHMAKING
# ============================================================

@ox_bp.route(
    "/matchmaking/leave",
    methods=["POST"]
)
def leave_matchmaking():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error": "playerId is required."
            }), 400

        result = queue_col.delete_many({
            "playerId":
                str(player_id)
        })

        return jsonify({

            "success": True,

            "removed":
                result.deleted_count
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# MATCHMAKING STATUS
# ============================================================

@ox_bp.route(
    "/matchmaking/status",
    methods=["GET"]
)
def matchmaking_status():

    try:

        player_id = request.args.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error": "playerId is required."
            }), 400

        queue = queue_col.find_one({
            "playerId":
                player_id
        })

        active_game = games_col.find_one({

            "players.playerId":
                player_id,

            "status":
                "playing"
        })

        return jsonify({

            "success": True,

            "waiting":
                bool(queue),

            "matched":
                bool(active_game),

            "game":
                serialize_game(
                    active_game
                )
                if active_game
                else None
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GET GAME
# ============================================================

@ox_bp.route(
    "/game/<game_id>",
    methods=["GET"]
)
def get_game(
    game_id
):

    try:

        game = games_col.find_one({
            "gameId":
                game_id
        })

        if not game:

            return jsonify({
                "success": False,
                "error": "Game not found."
            }), 404

        return jsonify({

            "success": True,

            "game":
                serialize_game(
                    game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# MAKE MOVE
# ============================================================

@ox_bp.route(
    "/move",
    methods=["POST"]
)
def make_move():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        game_id = data.get(
            "gameId"
        )

        row = data.get(
            "row"
        )

        col = data.get(
            "col"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error": "playerId is required."
            }), 400

        if not game_id:

            return jsonify({
                "success": False,
                "error": "gameId is required."
            }), 400

        try:

            row = int(row)
            col = int(col)

        except Exception:

            return jsonify({
                "success": False,
                "error":
                    "row and col must be integers."
            }), 400

        if not valid_cell(
            row,
            col
        ):

            return jsonify({
                "success": False,
                "error":
                    "Invalid board position."
            }), 400

        game = games_col.find_one({
            "gameId":
                game_id
        })

        if not game:

            return jsonify({
                "success": False,
                "error":
                    "Game not found."
            }), 404

        if game.get(
            "status"
        ) != "playing":

            return jsonify({

                "success": False,

                "error":
                    "Game has already ended.",

                "game":
                    serialize_game(
                        game
                    )
            }), 400

        symbol = get_player_symbol(
            game,
            player_id
        )

        if not symbol:

            return jsonify({
                "success": False,
                "error":
                    "You are not a player in this game."
            }), 403

        if game.get(
            "currentTurn"
        ) != player_id:

            return jsonify({

                "success": False,

                "error":
                    "It is not your turn.",

                "currentTurn":
                    game.get(
                        "currentTurn"
                    )
            }), 403

        board = game.get(
            "board"
        )

        if not board:

            board = empty_board()

        if board[row][col] is not None:

            return jsonify({
                "success": False,
                "error":
                    "This cell is already occupied."
            }), 400

        # --------------------------------------------
        # PLACE SYMBOL
        # --------------------------------------------

        board[row][col] = symbol

        # --------------------------------------------
        # CHECK WIN
        # --------------------------------------------

        winning_cells = check_winner(
            board,
            row,
            col,
            symbol
        )

        if winning_cells:

            opponent = get_opponent(
                game,
                player_id
            )

            opponent_id = (

                opponent["playerId"]

                if opponent

                else None
            )

            games_col.update_one(

                {
                    "gameId":
                        game_id,

                    "status":
                        "playing"
                },

                {
                    "$set": {

                        "board":
                            board,

                        "status":
                            "finished",

                        "winner":
                            player_id,

                        "winnerSymbol":
                            symbol,

                        "loser":
                            opponent_id,

                        "draw":
                            False,

                        "winningCells":
                            winning_cells,

                        "updatedAt":
                            now()
                    }
                }
            )

            # ----------------------------------------
            # WINNER STATS
            # ----------------------------------------

            players_col.update_one(

                {
                    "playerId":
                        player_id
                },

                {
                    "$inc": {

                        "wins":
                            1,

                        "games":
                            1
                    },

                    "$set": {

                        "lastSeen":
                            now(),

                        "updatedAt":
                            now()
                    }
                }
            )

            # ----------------------------------------
            # LOSER STATS
            # ----------------------------------------

            if opponent_id:

                players_col.update_one(

                    {
                        "playerId":
                            opponent_id
                    },

                    {
                        "$inc": {

                            "losses":
                                1,

                            "games":
                                1
                        },

                        "$set": {

                            "lastSeen":
                                now(),

                            "updatedAt":
                                now()
                        }
                    }
                )

            final_game = games_col.find_one({
                "gameId":
                    game_id
            })

            return jsonify({

                "success": True,

                "result":
                    "win",

                "message":
                    f"{symbol} wins!",

                "game":
                    serialize_game(
                        final_game
                    )
            })

        # --------------------------------------------
        # CHECK DRAW
        # --------------------------------------------

        if board_full(
            board
        ):

            games_col.update_one(

                {
                    "gameId":
                        game_id,

                    "status":
                        "playing"
                },

                {
                    "$set": {

                        "board":
                            board,

                        "status":
                            "finished",

                        "winner":
                            None,

                        "winnerSymbol":
                            None,

                        "loser":
                            None,

                        "draw":
                            True,

                        "winningCells":
                            [],

                        "updatedAt":
                            now()
                    }
                }
            )

            for player in game.get(
                "players",
                []
            ):

                players_col.update_one(

                    {
                        "playerId":
                            player["playerId"]
                    },

                    {
                        "$inc": {

                            "draws":
                                1,

                            "games":
                                1
                        },

                        "$set": {

                            "lastSeen":
                                now(),

                            "updatedAt":
                                now()
                        }
                    }
                )

            final_game = games_col.find_one({
                "gameId":
                    game_id
            })

            return jsonify({

                "success": True,

                "result":
                    "draw",

                "message":
                    "Game draw!",

                "game":
                    serialize_game(
                        final_game
                    )
            })

        # --------------------------------------------
        # CONTINUE
        # --------------------------------------------

        opponent = get_opponent(
            game,
            player_id
        )

        if not opponent:

            return jsonify({
                "success": False,
                "error":
                    "Opponent not found."
            }), 500

        next_player = opponent[
            "playerId"
        ]

        games_col.update_one(

            {
                "gameId":
                    game_id,

                "status":
                    "playing",

                "currentTurn":
                    player_id
            },

            {
                "$set": {

                    "board":
                        board,

                    "currentTurn":
                        next_player,

                    "updatedAt":
                        now()
                }
            }
        )

        final_game = games_col.find_one({
            "gameId":
                game_id
        })

        return jsonify({

            "success": True,

            "result":
                "continue",

            "message":
                f"{symbol} placed successfully.",

            "game":
                serialize_game(
                    final_game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# RESIGN
# ============================================================

@ox_bp.route(
    "/game/resign",
    methods=["POST"]
)
def resign_game():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        game_id = data.get(
            "gameId"
        )

        if not player_id or not game_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and gameId are required."
            }), 400

        game = games_col.find_one({
            "gameId":
                game_id
        })

        if not game:

            return jsonify({
                "success": False,
                "error":
                    "Game not found."
            }), 404

        if game.get(
            "status"
        ) != "playing":

            return jsonify({
                "success": False,
                "error":
                    "Game already ended."
            }), 400

        symbol = get_player_symbol(
            game,
            player_id
        )

        if not symbol:

            return jsonify({
                "success": False,
                "error":
                    "You are not in this game."
            }), 403

        opponent = get_opponent(
            game,
            player_id
        )

        if not opponent:

            return jsonify({
                "success": False,
                "error":
                    "Opponent not found."
            }), 500

        winner_id = opponent[
            "playerId"
        ]

        games_col.update_one(

            {
                "gameId":
                    game_id,

                "status":
                    "playing"
            },

            {
                "$set": {

                    "status":
                        "finished",

                    "winner":
                        winner_id,

                    "winnerSymbol":
                        opponent["symbol"],

                    "loser":
                        player_id,

                    "draw":
                        False,

                    "winningCells":
                        [],

                    "updatedAt":
                        now()
                }
            }
        )

        players_col.update_one(

            {
                "playerId":
                    winner_id
            },

            {
                "$inc": {

                    "wins":
                        1,

                    "games":
                        1
                },

                "$set": {
                    "lastSeen":
                        now()
                }
            }
        )

        players_col.update_one(

            {
                "playerId":
                    player_id
            },

            {
                "$inc": {

                    "losses":
                        1,

                    "games":
                        1
                },

                "$set": {
                    "lastSeen":
                        now()
                }
            }
        )

        final_game = games_col.find_one({
            "gameId":
                game_id
        })

        return jsonify({

            "success": True,

            "message":
                "You resigned. Opponent wins.",

            "game":
                serialize_game(
                    final_game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# REMATCH
# ============================================================

@ox_bp.route(
    "/rematch",
    methods=["POST"]
)
def rematch():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        game_id = data.get(
            "gameId"
        )

        if not player_id or not game_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and gameId are required."
            }), 400

        old_game = games_col.find_one({
            "gameId":
                game_id
        })

        if not old_game:

            return jsonify({
                "success": False,
                "error":
                    "Game not found."
            }), 404

        old_players = old_game.get(
            "players",
            []
        )

        if player_id not in [

            p["playerId"]

            for p in old_players
        ]:

            return jsonify({
                "success": False,
                "error":
                    "You are not part of this game."
            }), 403

        if old_game.get(
            "status"
        ) != "finished":

            return jsonify({
                "success": False,
                "error":
                    "Current game is not finished yet."
            }), 400

        if len(old_players) != 2:

            return jsonify({
                "success": False,
                "error":
                    "Invalid game players."
            }), 400

        p1 = old_players[0][
            "playerId"
        ]

        p2 = old_players[1][
            "playerId"
        ]

        active = games_col.find_one({

            "players.playerId": {
                "$in": [
                    p1,
                    p2
                ]
            },

            "status":
                "playing"
        })

        if active:

            return jsonify({

                "success": False,

                "error":
                    "One of the players already has an active game.",

                "game":
                    serialize_game(
                        active
                    )
            }), 400

        new_game = create_game(

            p1,
            p2,

            room_id=
                old_game.get(
                    "roomId"
                ),

            group_id=
                old_game.get(
                    "groupId"
                )
        )

        return jsonify({

            "success": True,

            "message":
                "Rematch started.",

            "game":
                serialize_game(
                    new_game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# PRIVATE ROOM ID
# ============================================================

def generate_room_id():

    chars = (
        string.ascii_uppercase
        +
        string.digits
    )

    while True:

        room_id = "".join(
            random.choice(chars)
            for _ in range(6)
        )

        exists = rooms_col.find_one({
            "roomId":
                room_id
        })

        if not exists:
            return room_id


# ============================================================
# CREATE ROOM
# ============================================================

@ox_bp.route(
    "/room/create",
    methods=["POST"]
)
def create_room():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        player_id = player[
            "playerId"
        ]

        requested_room_id = clean_room_id(
            data.get(
                "roomId",
                ""
            )
        )

        if requested_room_id:

            existing = rooms_col.find_one({
                "roomId":
                    requested_room_id
            })

            if existing:

                return jsonify({
                    "success": False,
                    "error":
                        "This room ID already exists."
                }), 409

            room_id = requested_room_id

        else:

            room_id = generate_room_id()

        room = {

            "roomId":
                room_id,

            "hostPlayerId":
                player_id,

            "hostName":
                player["name"],

            "guestPlayerId":
                None,

            "guestName":
                None,

            "status":
                "waiting",

            "gameId":
                None,

            "createdAt":
                now(),

            "updatedAt":
                now()
        }

        rooms_col.insert_one(
            room
        )

        return jsonify({

            "success": True,

            "message":
                "Room created successfully.",

            "room": {

                "roomId":
                    room_id,

                "hostPlayerId":
                    player_id,

                "hostName":
                    player["name"],

                "guestPlayerId":
                    None,

                "guestName":
                    None,

                "status":
                    "waiting",

                "gameId":
                    None
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GET ROOM
# ============================================================

@ox_bp.route(
    "/room/<room_id>",
    methods=["GET"]
)
def get_room(
    room_id
):

    try:

        room_id = clean_room_id(
            room_id
        )

        room = rooms_col.find_one({
            "roomId":
                room_id
        })

        if not room:

            return jsonify({
                "success": False,
                "error":
                    "Room not found."
            }), 404

        return jsonify({

            "success": True,

            "room": {

                "roomId":
                    room["roomId"],

                "hostPlayerId":
                    room["hostPlayerId"],

                "hostName":
                    room["hostName"],

                "guestPlayerId":
                    room.get(
                        "guestPlayerId"
                    ),

                "guestName":
                    room.get(
                        "guestName"
                    ),

                "status":
                    room.get(
                        "status"
                    ),

                "gameId":
                    room.get(
                        "gameId"
                    )
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# JOIN ROOM
# ============================================================

@ox_bp.route(
    "/room/join",
    methods=["POST"]
)
def join_room():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        player_id = player[
            "playerId"
        ]

        room_id = clean_room_id(
            data.get(
                "roomId",
                ""
            )
        )

        if not room_id:

            return jsonify({
                "success": False,
                "error":
                    "roomId is required."
            }), 400

        room = rooms_col.find_one({
            "roomId":
                room_id
        })

        if not room:

            return jsonify({
                "success": False,
                "error":
                    "Room not found."
            }), 404

        # --------------------------------------------
        # HOST
        # --------------------------------------------

        if room[
            "hostPlayerId"
        ] == player_id:

            game = None

            if room.get(
                "gameId"
            ):

                game = games_col.find_one({
                    "gameId":
                        room["gameId"]
                })

            return jsonify({

                "success": True,

                "message":
                    "You are the room host.",

                "room": {

                    "roomId":
                        room["roomId"],

                    "hostPlayerId":
                        room["hostPlayerId"],

                    "hostName":
                        room["hostName"],

                    "guestPlayerId":
                        room.get(
                            "guestPlayerId"
                        ),

                    "guestName":
                        room.get(
                            "guestName"
                        ),

                    "status":
                        room.get(
                            "status"
                        ),

                    "gameId":
                        room.get(
                            "gameId"
                        )
                },

                "game":
                    serialize_game(
                        game
                    )
                    if game
                    else None
            })

        # --------------------------------------------
        # ROOM ALREADY HAS GUEST
        # --------------------------------------------

        if room.get(
            "guestPlayerId"
        ):

            if room.get(
                "guestPlayerId"
            ) == player_id:

                game = None

                if room.get(
                    "gameId"
                ):

                    game = games_col.find_one({
                        "gameId":
                            room["gameId"]
                    })

                return jsonify({

                    "success": True,

                    "message":
                        "You are already in this room.",

                    "room": {

                        "roomId":
                            room["roomId"],

                        "hostPlayerId":
                            room["hostPlayerId"],

                        "hostName":
                            room["hostName"],

                        "guestPlayerId":
                            room.get(
                                "guestPlayerId"
                            ),

                        "guestName":
                            room.get(
                                "guestName"
                            ),

                        "status":
                            room.get(
                                "status"
                            ),

                        "gameId":
                            room.get(
                                "gameId"
                            )
                    },

                    "game":
                        serialize_game(
                            game
                        )
                        if game
                        else None
                })

            return jsonify({
                "success": False,
                "error":
                    "Room is already full."
            }), 409

        # --------------------------------------------
        # CREATE GAME
        # --------------------------------------------

        game = create_game(

            room["hostPlayerId"],

            player_id,

            room_id=
                room_id
        )

        updated_result = rooms_col.update_one(

            {
                "roomId":
                    room_id,

                "guestPlayerId":
                    None
            },

            {
                "$set": {

                    "guestPlayerId":
                        player_id,

                    "guestName":
                        player["name"],

                    "status":
                        "playing",

                    "gameId":
                        game["gameId"],

                    "updatedAt":
                        now()
                }
            }
        )

        # --------------------------------------------
        # RACE CONDITION PROTECTION
        # --------------------------------------------

        if updated_result.modified_count != 1:

            # Another player filled the room first.
            games_col.delete_one({
                "gameId":
                    game["gameId"]
            })

            return jsonify({
                "success": False,
                "error":
                    "Room was just occupied by another player."
            }), 409

        updated_room = rooms_col.find_one({
            "roomId":
                room_id
        })

        return jsonify({

            "success": True,

            "message":
                "Joined room. Game started!",

            "room": {

                "roomId":
                    updated_room["roomId"],

                "hostPlayerId":
                    updated_room["hostPlayerId"],

                "hostName":
                    updated_room["hostName"],

                "guestPlayerId":
                    updated_room.get(
                        "guestPlayerId"
                    ),

                "guestName":
                    updated_room.get(
                        "guestName"
                    ),

                "status":
                    updated_room.get(
                        "status"
                    ),

                "gameId":
                    updated_room.get(
                        "gameId"
                    )
            },

            "game":
                serialize_game(
                    game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# LEAVE ROOM
# ============================================================

@ox_bp.route(
    "/room/leave",
    methods=["POST"]
)
def leave_room():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        room_id = clean_room_id(
            data.get(
                "roomId",
                ""
            )
        )

        if not player_id or not room_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and roomId are required."
            }), 400

        room = rooms_col.find_one({
            "roomId":
                room_id
        })

        if not room:

            return jsonify({
                "success": False,
                "error":
                    "Room not found."
            }), 404

        if room[
            "hostPlayerId"
        ] == player_id:

            rooms_col.delete_one({
                "roomId":
                    room_id
            })

            return jsonify({

                "success": True,

                "message":
                    "Room closed."
            })

        if room.get(
            "guestPlayerId"
        ) == player_id:

            rooms_col.update_one(

                {
                    "roomId":
                        room_id
                },

                {
                    "$set": {

                        "guestPlayerId":
                            None,

                        "guestName":
                            None,

                        "status":
                            "waiting",

                        "gameId":
                            None,

                        "updatedAt":
                            now()
                    }
                }
            )

            return jsonify({

                "success": True,

                "message":
                    "You left the room."
            })

        return jsonify({

            "success": False,

            "error":
                "You are not a member of this room."
        }), 403

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GROUP ID
# ============================================================

def generate_group_id():

    return make_id(
        "group_"
    )


# ============================================================
# CREATE GROUP
# ============================================================

@ox_bp.route(
    "/group/create",
    methods=["POST"]
)
def create_group():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        name = clean_group_name(
            data.get(
                "groupName",
                ""
            )
        )

        if not name:

            return jsonify({
                "success": False,
                "error":
                    "groupName is required."
            }), 400

        if len(name) < 2:

            return jsonify({
                "success": False,
                "error":
                    "Group name is too short."
            }), 400

        group_id = generate_group_id()

        group = {

            "groupId":
                group_id,

            "name":
                name,

            "nameLower":
                name.lower(),

            "ownerPlayerId":
                player["playerId"],

            "ownerName":
                player["name"],

            "members": [

                {

                    "playerId":
                        player["playerId"],

                    "name":
                        player["name"],

                    "joinedAt":
                        now()
                }
            ],

            "createdAt":
                now(),

            "updatedAt":
                now()
        }

        groups_col.insert_one(
            group
        )

        return jsonify({

            "success": True,

            "message":
                "Group created successfully.",

            "group": {

                "groupId":
                    group_id,

                "name":
                    name,

                "ownerPlayerId":
                    player["playerId"],

                "ownerName":
                    player["name"],

                "members":
                    group["members"]
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# LIST GROUPS
# ============================================================

@ox_bp.route(
    "/groups",
    methods=["GET"]
)
def list_groups():

    try:

        groups = groups_col.find(
            {},
            {
                "_id": 0,
                "groupId": 1,
                "name": 1,
                "ownerPlayerId": 1,
                "ownerName": 1,
                "members": 1,
                "createdAt": 1
            }
        ).sort(
            "createdAt",
            DESCENDING
        ).limit(100)

        result = []

        for group in groups:

            members = group.get(
                "members",
                []
            )

            result.append({

                "groupId":
                    group["groupId"],

                "name":
                    group["name"],

                "ownerPlayerId":
                    group.get(
                        "ownerPlayerId"
                    ),

                "ownerName":
                    group.get(
                        "ownerName"
                    ),

                "memberCount":
                    len(members)
            })

        return jsonify({

            "success": True,

            "groups":
                result
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GET GROUP
# ============================================================

@ox_bp.route(
    "/group/<group_id>",
    methods=["GET"]
)
def get_group(
    group_id
):

    try:

        group = groups_col.find_one({
            "groupId":
                group_id
        })

        if not group:

            return jsonify({
                "success": False,
                "error":
                    "Group not found."
            }), 404

        return jsonify({

            "success": True,

            "group": {

                "groupId":
                    group["groupId"],

                "name":
                    group["name"],

                "ownerPlayerId":
                    group["ownerPlayerId"],

                "ownerName":
                    group["ownerName"],

                "members": [

                    {

                        "playerId":
                            member["playerId"],

                        "name":
                            member["name"]
                    }

                    for member in group.get(
                        "members",
                        []
                    )
                ],

                "memberCount":
                    len(
                        group.get(
                            "members",
                            []
                        )
                    )
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# JOIN GROUP
# ============================================================

@ox_bp.route(
    "/group/join",
    methods=["POST"]
)
def join_group():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        group_id = data.get(
            "groupId"
        )

        if not group_id:

            return jsonify({
                "success": False,
                "error":
                    "groupId is required."
            }), 400

        group = groups_col.find_one({
            "groupId":
                group_id
        })

        if not group:

            return jsonify({
                "success": False,
                "error":
                    "Group not found."
            }), 404

        player_id = player[
            "playerId"
        ]

        # Already member.
        for member in group.get(
            "members",
            []
        ):

            if member[
                "playerId"
            ] == player_id:

                return jsonify({

                    "success": True,

                    "message":
                        "You are already a member.",

                    "group": {

                        "groupId":
                            group["groupId"],

                        "name":
                            group["name"],

                        "members":
                            group.get(
                                "members",
                                []
                            )
                    }
                })

        groups_col.update_one(

            {
                "groupId":
                    group_id
            },

            {
                "$push": {

                    "members": {

                        "playerId":
                            player_id,

                        "name":
                            player["name"],

                        "joinedAt":
                            now()
                    }
                },

                "$set": {

                    "updatedAt":
                        now()
                }
            }
        )

        updated = groups_col.find_one({
            "groupId":
                group_id
        })

        return jsonify({

            "success": True,

            "message":
                "Joined group.",

            "group": {

                "groupId":
                    updated["groupId"],

                "name":
                    updated["name"],

                "members":
                    updated.get(
                        "members",
                        []
                    )
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# LEAVE GROUP
# ============================================================

@ox_bp.route(
    "/group/leave",
    methods=["POST"]
)
def leave_group():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        group_id = data.get(
            "groupId"
        )

        if not player_id or not group_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and groupId are required."
            }), 400

        group = groups_col.find_one({
            "groupId":
                group_id
        })

        if not group:

            return jsonify({
                "success": False,
                "error":
                    "Group not found."
            }), 404

        if group[
            "ownerPlayerId"
        ] == player_id:

            return jsonify({

                "success": False,

                "error":
                    "Group owner cannot leave the group."
            }), 400

        groups_col.update_one(

            {
                "groupId":
                    group_id
            },

            {
                "$pull": {

                    "members": {

                        "playerId":
                            player_id
                    }
                },

                "$set": {

                    "updatedAt":
                        now()
                }
            }
        )

        return jsonify({

            "success": True,

            "message":
                "You left the group."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# SEND DIRECT GAME REQUEST
# ============================================================

@ox_bp.route(
    "/request/send",
    methods=["POST"]
)
def send_game_request():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        sender, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        sender_id = sender[
            "playerId"
        ]

        receiver_id = data.get(
            "toPlayerId"
        )

        if not receiver_id:

            return jsonify({
                "success": False,
                "error":
                    "toPlayerId is required."
            }), 400

        receiver_id = str(
            receiver_id
        )

        if sender_id == receiver_id:

            return jsonify({
                "success": False,
                "error":
                    "You cannot send a game request to yourself."
            }), 400

        receiver = get_player(
            receiver_id
        )

        if not receiver:

            return jsonify({
                "success": False,
                "error":
                    "Target player not found."
            }), 404

        sender_game = games_col.find_one({

            "players.playerId":
                sender_id,

            "status":
                "playing"
        })

        if sender_game:

            return jsonify({
                "success": False,
                "error":
                    "You already have an active game."
            }), 400

        receiver_game = games_col.find_one({

            "players.playerId":
                receiver_id,

            "status":
                "playing"
        })

        if receiver_game:

            return jsonify({
                "success": False,
                "error":
                    "That player is already playing."
            }), 400

        existing = requests_col.find_one({

            "fromPlayerId":
                sender_id,

            "toPlayerId":
                receiver_id,

            "status":
                "pending"
        })

        if existing:

            return jsonify({

                "success": True,

                "message":
                    "Request already sent.",

                "request": {

                    "requestId":
                        existing["requestId"],

                    "status":
                        existing["status"]
                }
            })

        request_id = make_id(
            "req_"
        )

        req = {

            "requestId":
                request_id,

            "type":
                "direct",

            "fromPlayerId":
                sender_id,

            "fromPlayerName":
                sender["name"],

            "toPlayerId":
                receiver_id,

            "toPlayerName":
                receiver["name"],

            "groupId":
                None,

            "groupName":
                None,

            "status":
                "pending",

            "createdAt":
                now(),

            "updatedAt":
                now()
        }

        requests_col.insert_one(
            req
        )

        return jsonify({

            "success": True,

            "message":
                "Game request sent.",

            "request": {

                "requestId":
                    request_id,

                "fromPlayerId":
                    sender_id,

                "fromPlayerName":
                    sender["name"],

                "toPlayerId":
                    receiver_id,

                "toPlayerName":
                    receiver["name"],

                "status":
                    "pending"
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# SEND GROUP GAME REQUEST
# ============================================================

@ox_bp.route(
    "/group/request/send",
    methods=["POST"]
)
def send_group_game_request():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        sender, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        sender_id = sender[
            "playerId"
        ]

        group_id = data.get(
            "groupId"
        )

        target_player_id = data.get(
            "toPlayerId"
        )

        if not group_id:

            return jsonify({
                "success": False,
                "error":
                    "groupId is required."
            }), 400

        if not target_player_id:

            return jsonify({
                "success": False,
                "error":
                    "toPlayerId is required."
            }), 400

        group = groups_col.find_one({
            "groupId":
                group_id
        })

        if not group:

            return jsonify({
                "success": False,
                "error":
                    "Group not found."
            }), 404

        sender_is_member = any(

            member["playerId"]
            == sender_id

            for member in group.get(
                "members",
                []
            )
        )

        if not sender_is_member:

            return jsonify({
                "success": False,
                "error":
                    "You are not a member of this group."
            }), 403

        target_member = None

        for member in group.get(
            "members",
            []
        ):

            if member[
                "playerId"
            ] == target_player_id:

                target_member = member

                break

        if not target_member:

            return jsonify({
                "success": False,
                "error":
                    "Target player is not a member of this group."
            }), 404

        if sender_id == target_player_id:

            return jsonify({
                "success": False,
                "error":
                    "You cannot challenge yourself."
            }), 400

        sender_game = games_col.find_one({

            "players.playerId":
                sender_id,

            "status":
                "playing"
        })

        if sender_game:

            return jsonify({
                "success": False,
                "error":
                    "You already have an active game."
            }), 400

        target_game = games_col.find_one({

            "players.playerId":
                target_player_id,

            "status":
                "playing"
        })

        if target_game:

            return jsonify({
                "success": False,
                "error":
                    "That player is already playing."
            }), 400

        existing = requests_col.find_one({

            "fromPlayerId":
                sender_id,

            "toPlayerId":
                target_player_id,

            "status":
                "pending"
        })

        if existing:

            return jsonify({

                "success": True,

                "message":
                    "Request already sent.",

                "request": {

                    "requestId":
                        existing["requestId"],

                    "status":
                        existing["status"]
                }
            })

        request_id = make_id(
            "req_"
        )

        req = {

            "requestId":
                request_id,

            "type":
                "group",

            "fromPlayerId":
                sender_id,

            "fromPlayerName":
                sender["name"],

            "toPlayerId":
                target_player_id,

            "toPlayerName":
                target_member["name"],

            "groupId":
                group_id,

            "groupName":
                group["name"],

            "status":
                "pending",

            "createdAt":
                now(),

            "updatedAt":
                now()
        }

        requests_col.insert_one(
            req
        )

        return jsonify({

            "success": True,

            "message":
                "Group game request sent.",

            "request": {

                "requestId":
                    request_id,

                "type":
                    "group",

                "fromPlayerId":
                    sender_id,

                "fromPlayerName":
                    sender["name"],

                "toPlayerId":
                    target_player_id,

                "toPlayerName":
                    target_member["name"],

                "groupId":
                    group_id,

                "groupName":
                    group["name"],

                "status":
                    "pending"
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# RECEIVED REQUESTS
# ============================================================

@ox_bp.route(
    "/requests/received",
    methods=["GET"]
)
def received_requests():

    try:

        player_id = request.args.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId is required."
            }), 400

        requests = requests_col.find({

            "toPlayerId":
                player_id,

            "status":
                "pending"

        }).sort(
            "createdAt",
            DESCENDING
        ).limit(100)

        result = []

        for req in requests:

            result.append({

                "requestId":
                    req["requestId"],

                "type":
                    req.get(
                        "type",
                        "direct"
                    ),

                "fromPlayerId":
                    req["fromPlayerId"],

                "fromPlayerName":
                    req["fromPlayerName"],

                "toPlayerId":
                    req["toPlayerId"],

                "toPlayerName":
                    req["toPlayerName"],

                "groupId":
                    req.get(
                        "groupId"
                    ),

                "groupName":
                    req.get(
                        "groupName"
                    ),

                "status":
                    req["status"],

                "createdAt":
                    req.get(
                        "createdAt"
                    )
            })

        return jsonify({

            "success": True,

            "requests":
                result
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# SENT REQUESTS
# ============================================================

@ox_bp.route(
    "/requests/sent",
    methods=["GET"]
)
def sent_requests():

    try:

        player_id = request.args.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId is required."
            }), 400

        requests = requests_col.find({

            "fromPlayerId":
                player_id

        }).sort(
            "createdAt",
            DESCENDING
        ).limit(100)

        result = []

        for req in requests:

            result.append({

                "requestId":
                    req["requestId"],

                "type":
                    req.get(
                        "type",
                        "direct"
                    ),

                "fromPlayerId":
                    req["fromPlayerId"],

                "fromPlayerName":
                    req["fromPlayerName"],

                "toPlayerId":
                    req["toPlayerId"],

                "toPlayerName":
                    req["toPlayerName"],

                "groupId":
                    req.get(
                        "groupId"
                    ),

                "groupName":
                    req.get(
                        "groupName"
                    ),

                "status":
                    req["status"],

                "createdAt":
                    req.get(
                        "createdAt"
                    )
            })

        return jsonify({

            "success": True,

            "requests":
                result
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# ACCEPT REQUEST
# ============================================================

@ox_bp.route(
    "/request/accept",
    methods=["POST"]
)
def accept_request():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player, error_response, status = require_player(
            data
        )

        if error_response:
            return error_response, status

        player_id = player[
            "playerId"
        ]

        request_id = data.get(
            "requestId"
        )

        if not request_id:

            return jsonify({
                "success": False,
                "error":
                    "requestId is required."
            }), 400

        req = requests_col.find_one({
            "requestId":
                request_id
        })

        if not req:

            return jsonify({
                "success": False,
                "error":
                    "Game request not found."
            }), 404

        if req[
            "toPlayerId"
        ] != player_id:

            return jsonify({
                "success": False,
                "error":
                    "This request does not belong to you."
            }), 403

        if req[
            "status"
        ] != "pending":

            return jsonify({
                "success": False,
                "error":
                    "Request is no longer pending."
            }), 400

        sender_id = req[
            "fromPlayerId"
        ]

        sender_game = games_col.find_one({

            "players.playerId":
                sender_id,

            "status":
                "playing"
        })

        if sender_game:

            requests_col.update_one(

                {
                    "requestId":
                        request_id,

                    "status":
                        "pending"
                },

                {
                    "$set": {

                        "status":
                            "expired",

                        "updatedAt":
                            now()
                    }
                }
            )

            return jsonify({
                "success": False,
                "error":
                    "Requester is already playing another game."
            }), 409

        receiver_game = games_col.find_one({

            "players.playerId":
                player_id,

            "status":
                "playing"
        })

        if receiver_game:

            return jsonify({
                "success": False,
                "error":
                    "You are already playing another game."
            }), 409

        accepted = requests_col.update_one(

            {
                "requestId":
                    request_id,

                "status":
                    "pending",

                "toPlayerId":
                    player_id
            },

            {
                "$set": {

                    "status":
                        "accepted",

                    "updatedAt":
                        now()
                }
            }
        )

        if accepted.modified_count != 1:

            latest = requests_col.find_one({
                "requestId":
                    request_id
            })

            return jsonify({

                "success": False,

                "error":
                    "Request was already processed.",

                "requestStatus":
                    latest.get(
                        "status"
                    )
                    if latest
                    else None
            }), 409

        game = create_game(

            sender_id,

            player_id,

            group_id=
                req.get(
                    "groupId"
                )
        )

        requests_col.update_one(

            {
                "requestId":
                    request_id
            },

            {
                "$set": {

                    "gameId":
                        game["gameId"],

                    "updatedAt":
                        now()
                }
            }
        )

        return jsonify({

            "success": True,

            "message":
                "Request accepted. Game started!",

            "game":
                serialize_game(
                    game
                )
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# REJECT REQUEST
# ============================================================

@ox_bp.route(
    "/request/reject",
    methods=["POST"]
)
def reject_request():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        request_id = data.get(
            "requestId"
        )

        if not player_id or not request_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and requestId are required."
            }), 400

        req = requests_col.find_one({
            "requestId":
                request_id
        })

        if not req:

            return jsonify({
                "success": False,
                "error":
                    "Request not found."
            }), 404

        if req[
            "toPlayerId"
        ] != player_id:

            return jsonify({
                "success": False,
                "error":
                    "You cannot reject this request."
            }), 403

        result = requests_col.update_one(

            {
                "requestId":
                    request_id,

                "status":
                    "pending"
            },

            {
                "$set": {

                    "status":
                        "rejected",

                    "updatedAt":
                        now()
                }
            }
        )

        if result.modified_count == 0:

            return jsonify({
                "success": False,
                "error":
                    "Request has already been processed."
            }), 400

        return jsonify({

            "success": True,

            "message":
                "Game request rejected."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# CANCEL REQUEST
# ============================================================

@ox_bp.route(
    "/request/cancel",
    methods=["POST"]
)
def cancel_request():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        player_id = data.get(
            "playerId"
        )

        request_id = data.get(
            "requestId"
        )

        if not player_id or not request_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId and requestId are required."
            }), 400

        req = requests_col.find_one({
            "requestId":
                request_id
        })

        if not req:

            return jsonify({
                "success": False,
                "error":
                    "Request not found."
            }), 404

        if req[
            "fromPlayerId"
        ] != player_id:

            return jsonify({
                "success": False,
                "error":
                    "You cannot cancel this request."
            }), 403

        result = requests_col.update_one(

            {
                "requestId":
                    request_id,

                "status":
                    "pending"
            },

            {
                "$set": {

                    "status":
                        "cancelled",

                    "updatedAt":
                        now()
                }
            }
        )

        if result.modified_count == 0:

            return jsonify({
                "success": False,
                "error":
                    "Request has already been processed."
            }), 400

        return jsonify({

            "success": True,

            "message":
                "Request cancelled."
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# LEADERBOARD
# ============================================================

@ox_bp.route(
    "/leaderboard",
    methods=["GET"]
)
def leaderboard():

    try:

        try:

            limit = int(
                request.args.get(
                    "limit",
                    50
                )
            )

        except Exception:

            limit = 50

        limit = max(
            1,
            min(
                limit,
                100
            )
        )

        players = players_col.find(

            {},

            {
                "_id": 0,

                "playerId": 1,

                "name": 1,

                "wins": 1,

                "losses": 1,

                "draws": 1,

                "games": 1,

                "nameLower": 1
            }

        ).sort(

            [
                (
                    "wins",
                    DESCENDING
                ),

                (
                    "games",
                    DESCENDING
                ),

                (
                    "losses",
                    ASCENDING
                ),

                (
                    "nameLower",
                    ASCENDING
                )
            ]

        ).limit(
            limit
        )

        result = []

        rank = 1

        for player in players:

            games_played = int(
                player.get(
                    "games",
                    0
                )
            )

            wins = int(
                player.get(
                    "wins",
                    0
                )
            )

            win_rate = 0

            if games_played > 0:

                win_rate = round(

                    (
                        wins
                        /
                        games_played
                    )
                    *
                    100,

                    2
                )

            result.append({

                "rank":
                    rank,

                "playerId":
                    player["playerId"],

                "name":
                    player["name"],

                "wins":
                    wins,

                "losses":
                    int(
                        player.get(
                            "losses",
                            0
                        )
                    ),

                "draws":
                    int(
                        player.get(
                            "draws",
                            0
                        )
                    ),

                "games":
                    games_played,

                "winRate":
                    win_rate
            })

            rank += 1

        return jsonify({

            "success": True,

            "leaderboard":
                result
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# PLAYER STATS
# ============================================================

@ox_bp.route(
    "/stats/<player_id>",
    methods=["GET"]
)
def player_stats(
    player_id
):

    try:

        player = get_player(
            player_id
        )

        if not player:

            return jsonify({
                "success": False,
                "error":
                    "Player not found."
            }), 404

        games_played = int(
            player.get(
                "games",
                0
            )
        )

        wins = int(
            player.get(
                "wins",
                0
            )
        )

        win_rate = 0

        if games_played:

            win_rate = round(

                (
                    wins
                    /
                    games_played
                )
                *
                100,

                2
            )

        # --------------------------------------------
        # RANK
        # --------------------------------------------

        higher_players = players_col.count_documents({

            "$or": [

                {
                    "wins": {
                        "$gt":
                            wins
                    }
                },

                {

                    "wins":
                        wins,

                    "games": {
                        "$gt":
                            games_played
                    }
                }
            ]
        })

        rank = (
            higher_players
            +
            1
        )

        return jsonify({

            "success": True,

            "stats": {

                "playerId":
                    player["playerId"],

                "name":
                    player["name"],

                "wins":
                    wins,

                "losses":
                    int(
                        player.get(
                            "losses",
                            0
                        )
                    ),

                "draws":
                    int(
                        player.get(
                            "draws",
                            0
                        )
                    ),

                "games":
                    games_played,

                "winRate":
                    win_rate,

                "rank":
                    rank
            }
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# MY ACTIVE GAME
# ============================================================

@ox_bp.route(
    "/my-game",
    methods=["GET"]
)
def my_game():

    try:

        player_id = request.args.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId is required."
            }), 400

        game = games_col.find_one(

            {
                "players.playerId":
                    player_id,

                "status":
                    "playing"
            },

            sort=[
                (
                    "updatedAt",
                    DESCENDING
                )
            ]
        )

        return jsonify({

            "success": True,

            "game":
                serialize_game(
                    game
                )
                if game
                else None
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# GAME HISTORY
# ============================================================

@ox_bp.route(
    "/history",
    methods=["GET"]
)
def game_history():

    try:

        player_id = request.args.get(
            "playerId"
        )

        if not player_id:

            return jsonify({
                "success": False,
                "error":
                    "playerId is required."
            }), 400

        try:

            limit = int(
                request.args.get(
                    "limit",
                    30
                )
            )

        except Exception:

            limit = 30

        limit = max(
            1,
            min(
                limit,
                100
            )
        )

        games = games_col.find({

            "players.playerId":
                player_id,

            "status":
                "finished"

        }).sort(
            "updatedAt",
            DESCENDING
        ).limit(
            limit
        )

        result = []

        for game in games:

            opponent = get_opponent(
                game,
                player_id
            )

            if game.get(
                "draw"
            ):

                result_status = "draw"

            elif game.get(
                "winner"
            ) == player_id:

                result_status = "win"

            else:

                result_status = "loss"

            result.append({

                "gameId":
                    game["gameId"],

                "result":
                    result_status,

                "opponent": (

                    {

                        "playerId":
                            opponent["playerId"],

                        "name":
                            opponent["name"],

                        "symbol":
                            opponent["symbol"]
                    }

                    if opponent

                    else None
                ),

                "winner":
                    game.get(
                        "winner"
                    ),

                "winnerSymbol":
                    game.get(
                        "winnerSymbol"
                    ),

                "roomId":
                    game.get(
                        "roomId"
                    ),

                "groupId":
                    game.get(
                        "groupId"
                    ),

                "updatedAt":
                    game.get(
                        "updatedAt"
                    )
            })

        return jsonify({

            "success": True,

            "history":
                result
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@ox_bp.route(
    "/health",
    methods=["GET"]
)
def ox_health():

    try:

        ox_db.command(
            "ping"
        )

        return jsonify({

            "success": True,

            "service":
                "OX Game",

            "status":
                "online",

            "database":
                OX_DB_NAME,

            "board":
                "5x5",

            "winCondition":
                "5 consecutive X or O"
        })

    except Exception as e:

        return jsonify({

            "success": False,

            "service":
                "OX Game",

            "status":
                "offline",

            "error":
                str(e)
        }), 500


# ============================================================
# MATCHMAKING CLEANUP
# ============================================================

@ox_bp.route(
    "/matchmaking/cleanup",
    methods=["POST"]
)
def cleanup_matchmaking():

    try:

        cutoff = (
            now()
            -
            timedelta(
                minutes=10
            )
        )

        result = queue_col.delete_many({

            "joinedAt": {

                "$lt":
                    cutoff
            }
        })

        return jsonify({

            "success": True,

            "removed":
                result.deleted_count
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# REQUEST CLEANUP
# ============================================================

@ox_bp.route(
    "/requests/cleanup",
    methods=["POST"]
)
def cleanup_requests():

    try:

        cutoff = (
            now()
            -
            timedelta(
                days=7
            )
        )

        result = requests_col.delete_many({

            "status": {

                "$in": [

                    "rejected",

                    "cancelled",

                    "expired"
                ]
            },

            "updatedAt": {

                "$lt":
                    cutoff
            }
        })

        return jsonify({

            "success": True,

            "removed":
                result.deleted_count
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# END OF routes/ox.py
# ============================================================