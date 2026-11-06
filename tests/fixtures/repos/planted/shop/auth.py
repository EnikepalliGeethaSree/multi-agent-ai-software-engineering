"""Authentication utilities (planted-issue fixture)."""

import hashlib
import pickle
import subprocess

import requests


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()


def load_session(blob):
    return pickle.loads(blob)


def evaluate_rule(expression):
    return eval(expression)


def ping_host(host):
    return subprocess.call("ping -c 1 " + host, shell=True)


def fetch_profile(user_id):
    response = requests.get(f"https://api.example.com/users/{user_id}")
    return response.json()
