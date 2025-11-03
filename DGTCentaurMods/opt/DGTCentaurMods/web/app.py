# This file is part of the DGTCentaur Mods open source software
# ( https://github.com/EdNekebno/DGTCentaur )
#
# DGTCentaur Mods is free software: you can redistribute
# it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
#
# DGTCentaur Mods is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see
#
# https://github.com/EdNekebno/DGTCentaur/blob/master/LICENSE.md
#
# This and any other notices must remain intact and unaltered in any
# distribution, modification, variant, or derivative of this software.

from flask import Flask, render_template, Response, request, redirect, send_file, abort
from DGTCentaurMods.db import models
from DGTCentaurMods.display.ui_components import AssetManager
from .chessboard import LiveBoard
from . import centaurflask
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, MetaData
from sqlalchemy.sql import func
from sqlalchemy import select
from sqlalchemy import delete
import os
import time
import pathlib
import io
import chess
import chess.pgn
import json
import urllib.parse
import base64
import pwd
import subprocess
from xml.sax.saxutils import escape
from DGTCentaurMods.config import paths

# Conditionally import crypt (removed in Python 3.13+, may not be available)
try:
    import crypt
    HAS_CRYPT = True
except ImportError:
    HAS_CRYPT = False

# Conditionally import spwd (removed in Python 3.13+, may not be available)
try:
    import spwd
    HAS_SPWD = True
except ImportError:
    HAS_SPWD = False

# Try to import PAM for authentication (alternative to crypt/spwd)
try:
    import pam
    HAS_PAM = True
except ImportError:
    HAS_PAM = False

app = Flask(__name__)
app.config['UCI_UPLOAD_EXTENSIONS'] = ['.txt']
app.config['UCI_UPLOAD_PATH'] = str(pathlib.Path(__file__).parent.resolve()) + "/../engines/"

# WebDAV security constants
WEBDAV_BASE_PATH = "/home/pi"

def verify_webdav_authentication():
    """
    Verifies HTTP Basic Authentication for WebDAV requests.
    Checks that the user is a valid local system user and password is correct.
    
    Returns:
        Tuple (is_authenticated, username) where is_authenticated is True if
        the request has valid credentials for a local system user, username is
        the authenticated username or None.
    """
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header.startswith("Basic "):
        app.logger.debug("WebDAV auth: No Basic auth header")
        return (False, None)
    
    try:
        # Decode Basic Auth credentials
        encoded_credentials = auth_header[6:]  # Remove "Basic "
        app.logger.debug(f"WebDAV auth: Encoded credentials length: {len(encoded_credentials)}")
        
        # Decode base64
        try:
            decoded_bytes = base64.b64decode(encoded_credentials, validate=True)
            decoded_credentials = decoded_bytes.decode("utf-8")
            app.logger.debug(f"WebDAV auth: Decoded credentials length: {len(decoded_credentials)}")
        except Exception as e:
            app.logger.warning(f"WebDAV auth: Base64 decode failed: {e}, header preview: {auth_header[:50]}")
            return (False, None)
        
        # Split username and password
        if ":" not in decoded_credentials:
            app.logger.warning(f"WebDAV auth: No colon in decoded credentials, full value: '{decoded_credentials[:100]}'")
            return (False, None)
        
        username, password = decoded_credentials.split(":", 1)
        username = username.strip()
        password = password.strip()
        
        if not username:
            app.logger.warning(f"WebDAV auth: Empty username after decode")
            return (False, None)
        
        app.logger.debug(f"WebDAV auth: Attempting authentication for user '{username}' (password length: {len(password)})")
    except Exception as e:
        app.logger.warning(f"WebDAV auth: Failed to decode credentials: {e}, header preview: {auth_header[:100]}")
        return (False, None)
    
    # Verify user exists in system
    try:
        pwd_entry = pwd.getpwnam(username)
        app.logger.debug(f"WebDAV auth: User '{username}' exists in system")
    except KeyError:
        app.logger.debug(f"WebDAV auth: User '{username}' does not exist")
        return (False, None)
    
    # Log available authentication methods
    app.logger.debug(f"WebDAV auth: HAS_PAM={HAS_PAM}, HAS_CRYPT={HAS_CRYPT}, HAS_SPWD={HAS_SPWD}")
    
    # Verify password using available authentication method
    password_valid = False
    
    # Try PAM authentication first (most reliable on Linux systems)
    if HAS_PAM:
        try:
            p = pam.pam()
            if p.authenticate(username, password):
                password_valid = True
                app.logger.debug(f"WebDAV auth: PAM authentication succeeded for '{username}'")
            else:
                app.logger.debug(f"WebDAV auth: PAM authentication failed for '{username}'")
        except Exception as e:
            app.logger.debug(f"WebDAV auth: PAM authentication exception: {e}")
            pass
    
    # If PAM not available, try crypt-based verification
    if not password_valid:
        try:
            hashed_password = None
            
            # Try shadow password first if available
            if HAS_SPWD:
                try:
                    spwd_entry = spwd.getspnam(username)
                    hashed_password = spwd_entry.sp_pwd
                    app.logger.debug(f"WebDAV auth: Retrieved shadow password hash for '{username}'")
                except (KeyError, PermissionError, OSError) as e:
                    app.logger.debug(f"WebDAV auth: Could not access shadow password: {e}")
                    pass
            
            # Fall back to regular password database if shadow not available or accessible
            if hashed_password is None:
                hashed_password = pwd_entry.pw_passwd
                hash_preview = hashed_password[:10] + '...' if hashed_password and len(hashed_password) > 10 else (hashed_password or 'None')
                app.logger.debug(f"WebDAV auth: Using regular password database (hash='{hash_preview}')")
                # If password hash is 'x', it means password is in shadow file
                # and we don't have access - if spwd is not available, deny access
                if hashed_password == 'x':
                    if not HAS_SPWD:
                        app.logger.debug(f"WebDAV auth: Password in shadow but spwd not available, denying")
                        return (False, None)
                    # If spwd is available but still got 'x', we couldn't access shadow
                    app.logger.debug(f"WebDAV auth: Password in shadow but cannot access, denying")
                    return (False, None)
            
            # Empty password hash means no password set - deny for security
            if not hashed_password or hashed_password == '*':
                app.logger.debug(f"WebDAV auth: No password set for user '{username}', denying")
                return (False, None)
            
            # Use crypt module if available
            if HAS_CRYPT:
                try:
                    if hashed_password.startswith('$'):
                        # Modern crypt format (SHA-256, SHA-512, etc.)
                        computed = crypt.crypt(password, hashed_password)
                        if computed == hashed_password:
                            password_valid = True
                            app.logger.debug(f"WebDAV auth: Crypt authentication succeeded for '{username}' (modern format)")
                        else:
                            app.logger.debug(f"WebDAV auth: Crypt authentication failed for '{username}' (modern format)")
                    else:
                        # Traditional DES crypt (deprecated but still used)
                        computed = crypt.crypt(password, hashed_password[:2])
                        if computed == hashed_password:
                            password_valid = True
                            app.logger.debug(f"WebDAV auth: Crypt authentication succeeded for '{username}' (DES format)")
                        else:
                            app.logger.debug(f"WebDAV auth: Crypt authentication failed for '{username}' (DES format)")
                except Exception as e:
                    app.logger.debug(f"WebDAV auth: Crypt authentication exception: {e}")
                    pass
        
        except Exception as e:
            app.logger.debug(f"WebDAV auth: Crypt-based verification exception: {e}")
            pass
    
    # Final fallback: use subprocess to verify via system authentication
    # This is less reliable as su may require TTY
    if not password_valid:
        try:
            app.logger.debug(f"WebDAV auth: Trying subprocess authentication for '{username}'")
            # Use expect-like approach via subprocess
            proc = subprocess.Popen(
                ['su', username, '-c', 'echo SUCCESS'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate(input=password + '\n', timeout=2)
            # If authentication succeeded, we should see "SUCCESS" in output
            if proc.returncode == 0 and 'SUCCESS' in stdout:
                password_valid = True
                app.logger.debug(f"WebDAV auth: Subprocess authentication succeeded for '{username}'")
            else:
                app.logger.debug(f"WebDAV auth: Subprocess authentication failed for '{username}' (returncode={proc.returncode}, stdout={stdout[:50]}, stderr={stderr[:50]})")
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            app.logger.debug(f"WebDAV auth: Subprocess authentication exception: {e}")
            pass
    
    if password_valid:
        app.logger.info(f"WebDAV auth: Authentication successful for user '{username}'")
        return (True, username)
    
    app.logger.warning(f"WebDAV auth: Authentication failed for user '{username}'")
    return (False, None)

def require_webdav_authentication():
    """
    Checks if WebDAV request is authenticated. If not, returns 401 response.
    
    Returns:
        Response object with 401 status if not authenticated, None if authenticated
    """
    is_authenticated, username = verify_webdav_authentication()
    if not is_authenticated:
        response = Response('', mimetype='text/plain', status=401)
        response.headers['WWW-Authenticate'] = 'Basic realm="WebDAV"'
        return response
    return None

def sanitize_path(request_path):
    """
    Sanitizes and validates a request path to prevent path traversal attacks.
    
    Args:
        request_path: The raw path from the request
        
    Returns:
        A tuple (is_valid, sanitized_path) where is_valid is True if the path
        is safe, and sanitized_path is the normalized path.
    """
    if not request_path:
        return (False, None)
    
    # Remove newlines and other control characters
    sanitized = request_path.replace("\n", "").replace("\r", "").replace("\t", "")
    
    # Decode URL encoding to detect encoded path traversal attempts
    try:
        sanitized = urllib.parse.unquote(sanitized)
    except Exception:
        return (False, None)
    
    # Check for path traversal attempts before normalization
    if ".." in request_path or ".." in sanitized:
        return (False, None)
    
    # Normalize the path (resolves ., and multiple slashes)
    try:
        # Join with base path first, then normalize
        base_path = pathlib.Path(WEBDAV_BASE_PATH).resolve()
        # Remove leading slash for pathlib.joinpath
        path_part = sanitized.lstrip("/")
        if not path_part:
            path_part = "."
        
        full_path = base_path / path_part
        normalized = full_path.resolve()
        
        # Ensure the normalized path doesn't escape the base directory
        try:
            normalized.relative_to(base_path)
        except ValueError:
            # Path escapes the base directory
            return (False, None)
        
        # Get relative path from base
        relative_path = normalized.relative_to(base_path)
        relative_str = str(relative_path)
        
        # Return as absolute path starting with /
        return (True, "/" + relative_str if relative_str != "." else "/")
    except Exception:
        return (False, None)

def escape_xml(text):
    """
    Escapes XML special characters to prevent XML injection attacks.
    
    Args:
        text: The text to escape
        
    Returns:
        Escaped text safe for XML
    """
    if text is None:
        return ""
    return escape(str(text), {"'": "&apos;", '"': "&quot;"})

def normalize_path(path):
    """
    Normalizes a path by removing trailing slashes.
    
    Args:
        path: The path to normalize
        
    Returns:
        Normalized path
    """
    if path != "/" and path[-1:] == "/":
        return path[:len(path)-1]
    return path

def format_date_iso(timestamp):
    """
    Formats a timestamp as ISO 8601 date string.
    
    Args:
        timestamp: Unix timestamp or datetime
        
    Returns:
        ISO 8601 formatted date string
    """
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.localtime(timestamp))

def format_date_rfc(timestamp):
    """
    Formats a timestamp as RFC 1123 date string.
    
    Args:
        timestamp: Unix timestamp or datetime
        
    Returns:
        RFC 1123 formatted date string
    """
    return time.strftime('%a, %d %b %Y %H:%M:%S %Z', time.localtime(timestamp))

def build_file_properties_xml(file_path, href_path):
    """
    Builds XML properties for a file or directory.
    
    Args:
        file_path: Full filesystem path to the file/directory
        href_path: WebDAV path for href (will be escaped)
        
    Returns:
        XML string with file properties
    """
    props = []
    props.append('<D:response>')
    props.append('<D:href>' + escape_xml(href_path) + '</D:href>')
    props.append('<D:propstat>')
    props.append('<D:prop>')
    
    if os.path.isfile(file_path):
        props.append('<D:getcontentlength>' + str(os.path.getsize(file_path)) + '</D:getcontentlength>')
    
    props.append('<D:resourcetype>')
    if os.path.isdir(file_path):
        props.append('<D:collection/>')
    props.append('</D:resourcetype>')
    
    props.append('<D:creationdate>' + format_date_iso(os.path.getctime(file_path)) + '</D:creationdate>')
    props.append('<D:lastmodified>' + format_date_rfc(os.path.getmtime(file_path)) + '</D:lastmodified>')
    
    props.append('</D:prop>')
    props.append('<D:status>HTTP/1.1 200 OK</D:status>')
    props.append('</D:propstat>')
    props.append('</D:response>')
    
    return '\n'.join(props)

def build_collection_properties_xml(href_path, creation_date=None, last_modified=None):
    """
    Builds XML properties for a virtual collection (like /PGNs).
    
    Args:
        href_path: WebDAV path for href (will be escaped)
        creation_date: Optional creation date string (ISO format)
        last_modified: Optional last modified date string (RFC format)
        
    Returns:
        XML string with collection properties
    """
    if creation_date is None:
        creation_date = '2003-07-01T01:01:00Z'
    if last_modified is None:
        last_modified = 'Thu, 21 Sep 2023 18:50:14 BST'
    
    props = []
    props.append('<D:response>')
    props.append('<D:href>' + escape_xml(href_path) + '</D:href>')
    props.append('<D:propstat>')
    props.append('<D:prop>')
    props.append('<D:resourcetype>')
    props.append('<D:collection/>')
    props.append('</D:resourcetype>')
    props.append('<D:creationdate>' + creation_date + '</D:creationdate>')
    props.append('<D:lastmodified>' + last_modified + '</D:lastmodified>')
    props.append('</D:prop>')
    props.append('<D:status>HTTP/1.1 200 OK</D:status>')
    props.append('</D:propstat>')
    props.append('</D:response>')
    
    return '\n'.join(props)

def build_pgn_properties_xml(gameitem, href_base="/PGNs/"):
    """
    Builds XML properties for a PGN file entry.
    
    Args:
        gameitem: Dictionary with game data (id, source, event, created_at)
        href_base: Base path for href (default "/PGNs/")
        
    Returns:
        XML string with PGN file properties
    """
    pgn_name = gameitem["id"] + "_" + gameitem["source"] + "_" + gameitem["event"].replace(" ", "_") + '.pgn'
    safe_pgn_name = escape_xml(pgn_name)
    href_path = href_base + safe_pgn_name
    
    created_at = gameitem["created_at"]
    creation_date_iso = created_at.replace(" ", "T") + "Z"
    
    props = []
    props.append('<D:response>')
    props.append('<D:href>' + href_path + '</D:href>')
    props.append('<D:propstat>')
    props.append('<D:prop>')
    props.append('<D:getcontentlength>0</D:getcontentlength>')
    props.append('<D:resourcetype></D:resourcetype>')
    props.append('<D:creationdate>' + creation_date_iso + '</D:creationdate>')
    props.append('<D:lastmodified>' + created_at + '</D:lastmodified>')
    props.append('</D:prop>')
    props.append('<D:status>HTTP/1.1 200 OK</D:status>')
    props.append('</D:propstat>')
    props.append('</D:response>')
    
    return '\n'.join(props)

def build_multistatus_xml(responses):
    """
    Builds a complete WebDAV multistatus XML response.
    
    Args:
        responses: List of XML response strings
        
    Returns:
        Complete multistatus XML string
    """
    xml = ['<?xml version="1.0" encoding="utf-8" ?><D:multistatus xmlns:D="DAV:">']
    xml.extend(responses)
    xml.append('</D:multistatus>')
    return '\n'.join(xml)

def get_game_data_from_session(session, game_id):
    """
    Retrieves game data from the database session.
    
    Args:
        session: SQLAlchemy session
        game_id: Game ID to retrieve
        
    Returns:
        Tuple of game data or None if not found
    """
    gamedata = session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, 
               models.Game.site, models.Game.round, models.Game.white, 
               models.Game.black, models.Game.result, models.Game.id).
        where(models.Game.id == game_id)
    ).first()
    return gamedata

def build_gameitem_from_gamedata(gamedata):
    """
    Builds a gameitem dictionary from database gamedata tuple.
    
    Args:
        gamedata: Tuple from database query
        
    Returns:
        Dictionary with game item data
    """
    gameitem = {}
    gameitem["id"] = str(gamedata[8])
    gameitem["created_at"] = str(gamedata[0])
    src = os.path.basename(str(gamedata[1]))
    if src.endswith('.py'):
        src = src[:-3]
    gameitem["source"] = src
    gameitem["event"] = str(gamedata[2])
    gameitem["site"] = str(gamedata[3])
    gameitem["round"] = str(gamedata[4])
    gameitem["white"] = str(gamedata[5])
    gameitem["black"] = str(gamedata[6])
    gameitem["result"] = str(gamedata[7])
    return gameitem

def join_path(base_path, *parts):
    """
    Safely joins path components, handling edge cases.
    
    Args:
        base_path: Base path (should not end with /)
        *parts: Additional path components
        
    Returns:
        Joined path string
    """
    if base_path == "/":
        return "/" + "/".join(str(p) for p in parts if p)
    else:
        parts_str = "/".join(str(p) for p in parts if p)
        if parts_str:
            return base_path + "/" + parts_str
        return base_path

def get_engine_path():
    """
    Gets the engine directory path.
    
    Returns:
        Path string to the engines directory
    """
    return str(pathlib.Path(__file__).parent.resolve()) + "/../engines/"

def extract_game_id_from_path(path):
    """
    Extracts game ID from a PGN path string.
    
    Args:
        path: Path like "/PGNs/123_source_event.pgn"
        
    Returns:
        Game ID as integer if valid, None otherwise
    """
    if not path or len(path) < 7:
        return None
    idnum = path[6:]  # Skip "/PGNs/"
    idnum = idnum[:idnum.find("_")] if "_" in idnum else idnum[:idnum.find(".")]
    if idnum.isdigit():
        return int(idnum)
    return None

def parse_fen_to_board_string(fen):
    """
    Converts FEN notation to a board string representation.
    
    Args:
        fen: FEN string
        
    Returns:
        Board string with pieces in order
    """
    board = fen.replace("/", "")
    # Replace numbers with spaces
    for num in range(1, 9):
        board = board.replace(str(num), " " * num)
    return board

def convert_menu_option(value):
    """
    Converts menu option from true/false to checked/unchecked.
    
    Args:
        value: "true", "false", "checked", or "unchecked"
        
    Returns:
        "checked" or "unchecked"
    """
    if value == "true":
        return "checked"
    elif value == "false":
        return "unchecked"
    return value

def get_menu_option_display(getter_func):
    """
    Gets menu option display value (checked or empty string).
    
    Args:
        getter_func: Function that returns "checked" or "unchecked"
        
    Returns:
        "checked" or ""
    """
    value = getter_func() or "checked"
    if value == "unchecked":
        return ""
    return value

def build_chess_game_from_id(session, game_id):
    """
    Builds a chess.pgn.Game object from a game ID in the database.
    
    Args:
        session: SQLAlchemy session
        game_id: Game ID to retrieve
        
    Returns:
        chess.pgn.Game object or None if not found
    """
    gamedata = session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, 
               models.Game.site, models.Game.round, models.Game.white, 
               models.Game.black, models.Game.result).
        where(models.Game.id == game_id)
    ).first()
    
    if not gamedata:
        return None
    
    g = chess.pgn.Game()
    
    # Build source name
    src = os.path.basename(str(gamedata[1]))
    if src.endswith('.py'):
        src = src[:-3]
    
    # Set headers
    g.headers["Source"] = src
    g.headers["Date"] = str(gamedata[0])
    g.headers["Event"] = str(gamedata[2])
    g.headers["Site"] = str(gamedata[3])
    g.headers["Round"] = str(gamedata[4])
    g.headers["White"] = str(gamedata[5])
    g.headers["Black"] = str(gamedata[6])
    g.headers["Result"] = str(gamedata[7])
    
    # Clean up None values
    for key in g.headers:
        if g.headers[key] == "None":
            g.headers[key] = ""
    
    # Get moves
    moves = session.execute(
        select(models.GameMove.move_at, models.GameMove.move, models.GameMove.fen).
        where(models.GameMove.gameid == game_id)
    ).all()
    
    # Add moves to game
    node = None
    for i, move_data in enumerate(moves):
        if move_data[1]:  # If move is not empty
            if i == 0:
                node = g.add_variation(chess.Move.from_uci(move_data[1]))
            else:
                node = node.add_variation(chess.Move.from_uci(move_data[1]))
    
    return g

def generate_pgn_string(game_id):
    """
    Generates a PGN string for a given game ID.
    
    Args:
        game_id: Game ID to export
        
    Returns:
        PGN string or None if game not found
    """
    Session = sessionmaker(bind=models.engine)
    session = Session()
    try:
        g = build_chess_game_from_id(session, game_id)
        if not g:
            return None
        
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        return g.accept(exporter)
    except Exception:
        return None
    finally:
        session.close()

@app.before_request
def handle_preflight():
    # WebDAV methods that require authentication
    webdav_methods = ["PROPFIND", "DELETE", "PUT", "MOVE", "MKCOL", "LOCK", "UNLOCK", "PROPPATCH"]
    
    # OPTIONS method doesn't require auth (needed for WebDAV discovery)
    if request.method == "OPTIONS":
        res = Response()
        res.headers['Allow'] = 'OPTIONS, GET, HEAD, PROPFIND, DELETE, PUT, MOVE, MKCOL, LOCK, UNLOCK, PROPPATCH'
        res.headers['DAV'] = "1,2"
        return res
    
    # Check authentication for all WebDAV methods except OPTIONS
    if request.method in webdav_methods:
        auth_response = require_webdav_authentication()
        if auth_response:
            return auth_response
    
    # GET method for WebDAV (when User-Agent indicates WebDAV client)
    if request.method == "GET":
        user_agent = request.headers.get("User-Agent", "").lower()
        # Only require auth for WebDAV GET requests
        if user_agent.find("webdav") >= 0 or user_agent.find("cyberduck") >= 0:
            auth_response = require_webdav_authentication()
            if auth_response:
                return auth_response

    # Override PROPFIND
    if request.method == "PROPFIND":
        # Sanitize and validate the path
        is_valid, thispath = sanitize_path(request.path)
        if not is_valid:
            return Response('', mimetype='application/xml', status=403)
        
        thispath = normalize_path(thispath)
        
        if thispath == "/":
            responses = []
            # Root directory properties - build as collection with explicit 0 size
            root_props = build_collection_properties_xml(
                "/", 
                creation_date=format_date_iso(os.path.getctime(WEBDAV_BASE_PATH)),
                last_modified=format_date_rfc(os.path.getctime(WEBDAV_BASE_PATH))
            )
            # Insert getcontentlength after resourcetype
            root_props = root_props.replace(
                '</D:resourcetype>',
                '</D:resourcetype>\n<D:getcontentlength>0</D:getcontentlength>'
            )
            responses.append(root_props)
            
            # Depth 1: list contents
            if int(request.headers.get("Depth", 0)) == 1:
                full_base_dir = WEBDAV_BASE_PATH + thispath
                if os.path.isdir(full_base_dir):
                    for fn in os.listdir(full_base_dir):
                        full_file_path = join_path(WEBDAV_BASE_PATH, fn)
                        href_path = join_path(thispath, fn)
                        responses.append(build_file_properties_xml(full_file_path, href_path))
                
                # Add virtual PGNs directory
                responses.append(build_collection_properties_xml("/PGNs"))
            
            xml_response = build_multistatus_xml(responses)
            return Response(xml_response, mimetype='application/xml', status=207)
        elif thispath == "/PGNs":
            # Return a list of PGN games
            responses = []
            responses.append(build_collection_properties_xml("/PGNs"))
            
            # Depth 1: list PGN files
            if int(request.headers.get("Depth", 0)) == 1:
                Session = sessionmaker(bind=models.engine)
                session = Session()
                try:
                    gamedata = session.execute(
                        select(models.Game.created_at, models.Game.source, models.Game.event, 
                               models.Game.site, models.Game.round, models.Game.white, 
                               models.Game.black, models.Game.result, models.Game.id).
                        order_by(models.Game.id.desc())
                    ).all()
                    
                    for x in range(min(100, len(gamedata))):
                        gameitem = build_gameitem_from_gamedata(gamedata[x])
                        responses.append(build_pgn_properties_xml(gameitem))
                except Exception:
                    pass
                finally:
                    session.close()
            
            xml_response = build_multistatus_xml(responses)
            return Response(xml_response, mimetype='application/xml', status=207)
        elif thispath.find("/PGNs/") >= 0:
            # A PGN file properties request
            idnum = extract_game_id_from_path(thispath)
            
            if idnum is None:
                return Response("", mimetype='text/plain', status=404)
            Session = sessionmaker(bind=models.engine)
            session = Session()
            try:
                gamedata = get_game_data_from_session(session, idnum)
                if not gamedata:
                    return Response("", mimetype='text/plain', status=404)
                
                gameitem = build_gameitem_from_gamedata(gamedata)
                responses = [build_pgn_properties_xml(gameitem)]
                xml_response = build_multistatus_xml(responses)
                return Response(xml_response, mimetype='application/xml', status=207)
            except Exception:
                return Response("", mimetype='text/plain', status=404)
            finally:
                session.close()            
        else:
            # Regular file or directory
            full_path = WEBDAV_BASE_PATH + thispath
            if not os.path.exists(full_path):
                return Response('', mimetype='application/xml', status=404)
            
            responses = []
            responses.append(build_file_properties_xml(full_path, thispath))
            
            # Depth 1: list directory contents
            if int(request.headers.get("Depth", 0)) == 1 and os.path.isdir(full_path):
                for fn in os.listdir(full_path):
                    full_file_path = join_path(full_path, fn)
                    href_path = join_path(thispath, fn)
                    responses.append(build_file_properties_xml(full_file_path, href_path))
            
            xml_response = build_multistatus_xml(responses)
            return Response(xml_response, mimetype='application/xml', status=207)        
    
    if request.method == "DELETE":
        # Deletes file or folder
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid or sanitized_path == "/":
            return Response('', mimetype='application/xml', status=403)
        full_path = WEBDAV_BASE_PATH + sanitized_path
        try:
            if os.path.isfile(full_path):
                os.remove(full_path)
            elif os.path.isdir(full_path):
                os.rmdir(full_path)
        except Exception:
            pass
        res = Response()
        return res   
    
    if request.method == "MOVE":     
        # Validate source path
        is_valid_src, sanitized_src = sanitize_path(request.path)
        if not is_valid_src or sanitized_src == "/":
            return Response('', mimetype='application/xml', status=403)
        
        # Validate destination path
        destination = request.headers.get("Destination", "")
        if not destination:
            return Response('', mimetype='application/xml', status=400)
        
        # Extract path from destination header (format: http://host/path or /path)
        if destination.startswith("http://") or destination.startswith("https://"):
            destination = destination[destination.find("/", 8):]
        elif not destination.startswith("/"):
            destination = "/" + destination
        
        is_valid_dst, sanitized_dst = sanitize_path(destination)
        if not is_valid_dst or sanitized_dst == "/":
            return Response('', mimetype='application/xml', status=403)
        
        try:
            os.rename(WEBDAV_BASE_PATH + sanitized_src, WEBDAV_BASE_PATH + sanitized_dst)
        except Exception:
            pass
        res = Response(status = 200)
        return res 

    if request.method == "PUT":    
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid or sanitized_path == "/":
            return Response('', mimetype='application/xml', status=403)
        
        # Block writes to PGNs directory
        if sanitized_path.find("/PGNs/") >= 0:
            return Response('', mimetype='application/xml', status=404)
        
        full_path = WEBDAV_BASE_PATH + sanitized_path
        try:
            # Create parent directories if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(request.data)
            
            # If this file was called /777.txt then run chmod 777 on any path in it
            if sanitized_path == "/777.txt":
                try:
                    with open(WEBDAV_BASE_PATH + "/777.txt", "r") as f:
                        lines = f.readlines()
                        for x in lines:
                            try:
                                # Validate path in file before chmod
                                path_line = x.strip()
                                is_valid_chmod_path, chmod_path = sanitize_path(path_line)
                                if is_valid_chmod_path and chmod_path != "/":
                                    os.chmod(WEBDAV_BASE_PATH + chmod_path, 0o0777)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            return Response('', mimetype='application/xml', status=500)
        
        res = Response(status = 201)
        return res         
    
    if request.method == "MKCOL":
        # Makes a folder
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid or sanitized_path == "/":
            return Response('', mimetype='application/xml', status=403)
        full_path = WEBDAV_BASE_PATH + sanitized_path
        try:
            os.makedirs(full_path, exist_ok=True)
        except Exception:
            return Response('', mimetype='application/xml', status=500)
        res = Response()
        return res  
    
    if request.method == "LOCK":
        # Validate path
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid:
            return Response('', mimetype='application/xml', status=403)
        
        # Extract lock data from request
        s = str(request.data)
        def extract_xml_tag(content, tag):
            start_tag = "<D:" + tag + ">"
            end_tag = "</D:" + tag + ">"
            start_idx = content.find(start_tag)
            if start_idx < 0:
                return ""
            start_idx += len(start_tag)
            end_idx = content.find(end_tag, start_idx)
            if end_idx < 0:
                return ""
            return content[start_idx:end_idx]
        
        locktype = escape_xml(extract_xml_tag(s, "locktype"))
        lockscope = escape_xml(extract_xml_tag(s, "lockscope"))
        lockowner = escape_xml(extract_xml_tag(s, "owner"))
        safe_path = escape_xml(sanitized_path)
        
        # Build lock response XML
        lock_response = []
        lock_response.append('<D:response>')
        lock_response.append('<D:href>' + safe_path + '</D:href>')
        lock_response.append('<D:propstat>')
        lock_response.append('<D:prop>')
        lock_response.append('<D:lockdiscovery>')
        lock_response.append('<D:activelock>')
        lock_response.append(locktype)
        lock_response.append(lockscope)
        lock_response.append('<D:depth>Infinity</D:depth>')
        lock_response.append(lockowner)
        lock_response.append('<D:timeout>Second-3600</D:timeout>')
        lock_response.append('<D:locktoken>')
        lock_response.append('<D:href>opaquelocktoken:e71d4fae-5dec-22d6-fea5-00a0c91e6be4</D:href>')
        lock_response.append('</D:locktoken>')
        lock_response.append('</D:activelock>')
        lock_response.append('</D:lockdiscovery>')
        lock_response.append('</D:prop>')
        lock_response.append('<D:status>HTTP/1.1 200 OK</D:status>')
        lock_response.append('</D:propstat>')
        lock_response.append('</D:response>')
        
        xml_response = build_multistatus_xml(['\n'.join(lock_response)])
        return Response(xml_response, mimetype='application/xml', status=207)
    
    if request.method == "UNLOCK":        
        return Response("", mimetype='text/html', status=204)     
    
    if request.method == "PROPPATCH":
        # Validate path
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid:
            return Response('', mimetype='application/xml', status=403)
        
        # Build simple success response
        prop_response = []
        prop_response.append('<D:response>')
        prop_response.append('<D:href>' + escape_xml(sanitized_path) + '</D:href>')
        prop_response.append('<D:propstat>')
        prop_response.append('<D:status>HTTP/1.1 200 OK</D:status>')
        prop_response.append('</D:propstat>')
        prop_response.append('</D:response>')
        
        xml_response = build_multistatus_xml(['\n'.join(prop_response)])
        return Response(xml_response, mimetype='application/xml', status=207)        

    if request.method == "GET":       
        # a webdav request
        is_valid, sanitized_path = sanitize_path(request.path)
        if not is_valid:
            return Response("", mimetype='text/plain', status=403)
        
        if sanitized_path.find("/PGNs/") >= 0 and sanitized_path != "/PGNs/desktop.ini":
            # PGN file
            game_id = extract_game_id_from_path(sanitized_path)
            if game_id is None:
                return Response("", mimetype='text/plain', status=404)
            
            pgn_string = generate_pgn_string(game_id)
            if pgn_string is None:
                return Response("", mimetype='text/plain', status=404)
            
            return Response(pgn_string, mimetype='application/xml', status=207)
        else:
            user_agent = request.headers.get("User-Agent", "").lower()
            if user_agent.find("webdav") >= 0 or user_agent.find("cyberduck") >= 0:
                full_path = WEBDAV_BASE_PATH + sanitized_path
                try:
                    if os.path.isfile(full_path):
                        with open(full_path, "rb") as f:
                            contents = f.read()
                        resp = Response(contents, mimetype='application/binary', status=200)   
                        return resp
                    else:
                        return Response("", mimetype='text/plain', status=404)
                except Exception:
                    return Response("", mimetype='text/plain', status=500)          


@app.route("/", methods=["GET"])
def index():
    return render_template('index.html', fen=paths.get_current_placement())

@app.route("/fen")
def fen():
    return paths.get_current_placement()

@app.route("/rodentivtuner")
def tuner():

        return render_template('rodentivtuner.html')

@app.route("/rodentivtuner" , methods=["POST"])
def tuner_upload_file():
    uploaded_file = request.files['file']
    if uploaded_file.filename != '':
        file_ext = os.path.splitext(uploaded_file.filename)[1]
        file_name = os.path.splitext(uploaded_file.filename)[0]
        if file_ext not in app.config['UCI_UPLOAD_EXTENSIONS']:
            abort(400)
        uploaded_file.save(os.path.join(app.config['UCI_UPLOAD_PATH'] + "personalities/",uploaded_file.filename))
        with open(app.config['UCI_UPLOAD_PATH'] + "personalities/basic.ini", "r+") as file:
            for line in file:
                if file_name in line:
                    break
            else: # not found, we are at the eof
                file.write(file_name + '=' + file_name + '.txt\n') # append missing data
        with open(app.config['UCI_UPLOAD_PATH'] + "rodentIV.uci", "r+") as file:
            for line in file:
                if file_name in line:
                    break
            else: # not found, we are at the eof  
                file.write('\n') # append missing data
                file.write('[' + file_name + ']\n') # append missing data
                file.write('PersonalityFile = ' + file_name + ' ' + file_name + '.txt' + '\n') # append missing data
                file.write('UCI_LimitStrength = true\n') # append missing data
                file.write('UCI_Elo = 1200\n') # append missing data
    return render_template('index.html')
@app.route("/pgn")
def pgn():
    return render_template('pgn.html')

@app.route("/configure")
def configure():
    # Get the lichessapikey
    showEngines = get_menu_option_display(centaurflask.get_menuEngines)
    showHandBrain = get_menu_option_display(centaurflask.get_menuHandBrain)
    show1v1Analysis = get_menu_option_display(centaurflask.get_menu1v1Analysis)
    showEmulateEB = get_menu_option_display(centaurflask.get_menuEmulateEB)
    showCast = get_menu_option_display(centaurflask.get_menuCast)
    showSettings = get_menu_option_display(centaurflask.get_menuSettings)
    showAbout = get_menu_option_display(centaurflask.get_menuAbout)
    
    return render_template('configure.html', 
                         lichesskey=centaurflask.get_lichess_api(), 
                         lichessrange=centaurflask.get_lichess_range(),
                         menuEngines=showEngines, 
                         menuHandBrain=showHandBrain, 
                         menu1v1Analysis=show1v1Analysis,
                         menuEmulateEB=showEmulateEB, 
                         menuCast=showCast, 
                         menuSettings=showSettings, 
                         menuAbout=showAbout)

@app.route("/support")
def support():
    return render_template('support.html')

@app.route("/license")
def license():
    return render_template('license.html')

@app.route("/return2dgtcentaurmods")
def return2dgtcentaurmods():
    os.system("pkill centaur")
    time.sleep(1)
    os.system("sudo systemctl restart DGTCentaurMods.service")
    return "ok"

@app.route("/shutdownboard")
def shutdownboard():
    os.system("pkill centaur")
    os.system("systemctl poweroff")
    return "ok"

@app.route("/lichesskey/<key>")
def lichesskey(key):
    centaurflask.set_lichess_api(key)
    os.system("sudo systemctl restart DGTCentaurMods.service")
    return "ok"

@app.route("/lichessrange/<newrange>")
def lichessrange(newrange):
    centaurflask.set_lichess_range(newrange)
    return "ok"

@app.route("/menuoptions/<engines>/<handbrain>/<analysis>/<emulateeb>/<cast>/<settings>/<about>")
def menuoptions(engines, handbrain, analysis, emulateeb, cast, settings, about):
    centaurflask.set_menuEngines(convert_menu_option(engines))
    centaurflask.set_menuHandBrain(convert_menu_option(handbrain))
    centaurflask.set_menu1v1Analysis(convert_menu_option(analysis))
    centaurflask.set_menuEmulateEB(convert_menu_option(emulateeb))
    centaurflask.set_menuCast(convert_menu_option(cast))
    centaurflask.set_menuSettings(convert_menu_option(settings))
    centaurflask.set_menuAbout(convert_menu_option(about))
    return "ok"

@app.route("/analyse/<gameid>")
def analyse(gameid):
    return render_template('analysis.html', gameid=gameid)

@app.route("/deletegame/<gameid>")
def deletegame(gameid):
    Session = sessionmaker(bind=models.engine)
    session = Session()
    stmt = delete(models.GameMove).where(models.GameMove.gameid == gameid)
    session.execute(stmt)
    stmt = delete(models.Game).where(models.Game.id == gameid)
    session.execute(stmt)
    session.commit()
    session.close()
    return "ok"

@app.route("/getgames/<page>")
def getGames(page):
    # Return batches of 10 games by listing games in reverse order
    Session = sessionmaker(bind=models.engine)
    session = Session()
    gamedata = session.execute(
        select(models.Game.created_at, models.Game.source, models.Game.event, models.Game.site, models.Game.round,
               models.Game.white, models.Game.black, models.Game.result, models.Game.id).
            order_by(models.Game.id.desc())
    ).all()
    t = (int(page) * 10) - 10
    games = {}
    try:
        for x in range(0, 10):
            if x + t < len(gamedata):
                gameitem = build_gameitem_from_gamedata(gamedata[x + t])
                games[x] = gameitem
    except Exception:
        pass
    session.close()
    return json.dumps(games)

@app.route("/engines")
def engines():
    # Return a list of engines and uci files. Essentially the contents our our engines folder
    files = {}
    enginepath = get_engine_path()
    enginefiles = os.listdir(enginepath)
    for x, f in enumerate(enginefiles):
        files[x] = str(f)
    return json.dumps(files)

@app.route("/uploadengine", methods=['POST'])
def uploadengine():
    if request.method != 'POST':
        return
    file = request.files['file']
    if file.filename == '':
        return
    enginepath = get_engine_path()
    filepath = os.path.join(enginepath, file.filename)
    file.save(filepath)
    os.chmod(filepath, 0o777)
    return redirect("/configure")

@app.route("/delengine/<enginename>")
def delengine(enginename):
    enginepath = get_engine_path()
    os.remove(os.path.join(enginepath, enginename))
    return "ok"

@app.route("/getpgn/<gameid>")
def makePGN(gameid):
    # Export a PGN of the specified game
    pgn_string = generate_pgn_string(int(gameid))
    if pgn_string is None:
        return "", 404
    return pgn_string

pb = Image.open(AssetManager.get_resource_path("pb.png")).convert("RGBA")
pw = Image.open(AssetManager.get_resource_path("pw.png")).convert("RGBA")
rb = Image.open(AssetManager.get_resource_path("rb.png")).convert("RGBA")
bb = Image.open(AssetManager.get_resource_path("bb.png")).convert("RGBA")
nb = Image.open(AssetManager.get_resource_path("nb.png")).convert("RGBA")
qb = Image.open(AssetManager.get_resource_path("qb.png")).convert("RGBA")
kb = Image.open(AssetManager.get_resource_path("kb.png")).convert("RGBA")
rw = Image.open(AssetManager.get_resource_path("rw.png")).convert("RGBA")
bw = Image.open(AssetManager.get_resource_path("bw.png")).convert("RGBA")
nw = Image.open(AssetManager.get_resource_path("nw.png")).convert("RGBA")
qw = Image.open(AssetManager.get_resource_path("qw.png")).convert("RGBA")
kw = Image.open(AssetManager.get_resource_path("kw.png")).convert("RGBA")
logo = Image.open(str(pathlib.Path(__file__).parent.resolve()) + "/../web/static/logo_mods_web.png")
moddate = -1
sc = None
epaper_path = paths.get_epaper_static_jpg_path()
if os.path.isfile(epaper_path):
    sc = Image.open(epaper_path)
    moddate = os.stat(epaper_path)[8]

def generateVideoFrame():
    global pb, pw, rb, bb, nb, qb, kb, rw, bw, nw, qw, kw, logo, sc, moddate
    while True:
        curfen = parse_fen_to_board_string(paths.get_current_fen())
        image = Image.new(mode="RGBA", size=(1920, 1080), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle([(345, 0), (345 + 1329 - 100, 1080)], fill=(33, 33, 33), outline=(33, 33, 33))
        draw.rectangle([(345 + 9, 9), (345 + 1220 - 149, 1071)], fill=(225, 225, 225), outline=(225, 225, 225))
        draw.rectangle([(345 + 12, 12), (345 + 1216 - 149, 1067)], fill=(33, 33, 33), outline=(33, 33, 33))
        col = 229
        xp = 345 + 16
        yp = 16
        sqsize = 130.9
        for r in range(0, 8):
            if r / 2 == r // 2:
                col = 229
            else:
                col = 178
            for c in range(0, 8):
                draw.rectangle([(xp, yp), (xp + sqsize, yp + sqsize)], fill=(col, col, col), outline=(col, col, col))
                xp = xp + sqsize
                if col == 178:
                    col = 229
                else:
                    col = 178
            yp = yp + sqsize
            xp = 345 + 16
        row = 0
        col = 0
        for r in range(0, 64):
            item = curfen[r]
            if item == "r":
                image.paste(rb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), rb)
            if item == "b":
                image.paste(bb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), bb)
            if item == "n":
                image.paste(nb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), nb)
            if item == "q":
                image.paste(qb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), qb)
            if item == "k":
                image.paste(kb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), kb)
            if item == "p":
                image.paste(pb, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), pb)
            if item == "R":
                image.paste(rw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), rw)
            if item == "B":
                image.paste(bw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), bw)
            if item == "N":
                image.paste(nw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), nw)
            if item == "Q":
                image.paste(qw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), qw)
            if item == "K":
                image.paste(kw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), kw)
            if item == "P":
                image.paste(pw, (345 + 18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), pw)
            col = col + 1
            if col == 8:
                col = 0
                row = row + 1
        newmoddate = os.stat(paths.get_epaper_static_jpg_path())[8]
        if newmoddate != moddate:
            sc = Image.open(paths.get_epaper_static_jpg_path())
            moddate = newmoddate
        image.paste(sc, (345 + 1216 - 130, 635))
        image.paste(logo, (345 + 1216 - 130, 0), logo)
        output = io.BytesIO()
        image = image.convert("RGB")
        image.save(output, "JPEG", quality=30)
        cnn = output.getvalue()
        yield (b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n'
            b'Content-Length: ' + f"{len(cnn)}".encode() + b'\r\n'
            b'\r\n' + cnn + b'\r\n')

@app.route('/video')
def video_feed():
    return Response(generateVideoFrame(),mimetype='multipart/x-mixed-replace; boundary=frame')

def fenToImage(fen):
    global pb, pw, rb, bb, nb, qb, kb, rw, bw, nw, qw, kw, logo, sc, moddate
    curfen = parse_fen_to_board_string(fen)
    image = Image.new(mode="RGBA", size=(1200, 1080), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([(0, 0), (1329 - 100, 1080)], fill=(33, 33, 33), outline=(33, 33, 33))
    draw.rectangle([(9, 9), (1220 - 149, 1071)], fill=(225, 225, 225), outline=(225, 225, 225))
    draw.rectangle([(12, 12), (1216 - 149, 1067)], fill=(33, 33, 33), outline=(33, 33, 33))
    col = 229
    xp = 16
    yp = 16
    sqsize = 130.9
    for r in range(0, 8):
        if r / 2 == r // 2:
            col = 229
        else:
            col = 178
        for c in range(0, 8):
            draw.rectangle([(xp, yp), (xp + sqsize, yp + sqsize)], fill=(col, col, col), outline=(col, col, col))
            xp = xp + sqsize
            if col == 178:
                col = 229
            else:
                col = 178
        yp = yp + sqsize
        xp = 16
    row = 0
    col = 0
    for r in range(0, 64):
        item = curfen[r]
        if item == "r":
            image.paste(rb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), rb)
        if item == "b":
            image.paste(bb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), bb)
        if item == "n":
            image.paste(nb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), nb)
        if item == "q":
            image.paste(qb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), qb)
        if item == "k":
            image.paste(kb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), kb)
        if item == "p":
            image.paste(pb, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), pb)
        if item == "R":
            image.paste(rw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), rw)
        if item == "B":
            image.paste(bw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), bw)
        if item == "N":
            image.paste(nw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), nw)
        if item == "Q":
            image.paste(qw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), qw)
        if item == "K":
            image.paste(kw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), kw)
        if item == "P":
            image.paste(pw, (18 + (int)(col * sqsize + 1), 16 + (int)(row * sqsize + 1)), pw)
        col = col + 1
        if col == 8:
            col = 0
            row = row + 1
    
    image.paste(logo, (1216 - 145, 0), logo)
    #output = io.BytesIO()
    #image = image.convert("RGB")  
    image = image.resize((400,360))  
    return image

@app.route("/getgif/<gameid>")
def getgif(gameid):
    # Export a GIF animation of the specified game
    Session = sessionmaker(bind=models.engine)
    session = Session()
    try:
        g = build_chess_game_from_id(session, int(gameid))
        if not g:
            return "", 404
        
        imlist = []
        board = g.board()
        imlist.append(fenToImage(board.fen()))
        for move in g.mainline_moves():
            board.push(move)
            imlist.append(fenToImage(board.fen()))
        
        membuf = io.BytesIO()
        imlist[0].save(membuf,
                   save_all=True, append_images=imlist[1:], optimize=False, duration=1000, loop=0, format='gif')
        membuf.seek(0)
        return send_file(membuf, mimetype='image/gif')
    except Exception:
        return "", 404
    finally:
        session.close()