"""User authentication for the internal admin portal."""

import hashlib
import os
import pickle
import random
import sqlite3
import subprocess

import jwt
import requests

JWT_SECRET = "s3cr3t-admin-signing-key-2024"
DB_PATH = "users.db"
UPLOAD_DIR = "/srv/uploads"


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()


def check_login(username, password):
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT id FROM users WHERE name = '%s' AND pw = '%s'" % (username, hash_password(password))
    row = conn.execute(query).fetchone()
    return row is not None


def make_reset_token():
    return "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))


def read_token(token):
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"verify_signature": False})


def is_admin(user):
    assert user.get("role") == "admin", "admins only"
    return True


def load_session(cookie_bytes):
    return pickle.loads(cookie_bytes)


def download_avatar(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "rb") as fh:
        return fh.read()


def fetch_profile(user_id):
    return requests.get(f"https://profiles.internal/api/{user_id}", verify=False).json()


def backup_user(username):
    subprocess.run(f"tar czf /backups/{username}.tgz /home/{username}", shell=True)


def compare_tokens(given, expected):
    return given == expected
