"""Settings for the PHQ application"""
import os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

CSP_POLICY = {
    "default-src": "'none'",
    "script-src": "",
    "style-src": "",
}
CSP_POLICY_NONCE_IN = ["script-src", "style-src"]
SESSION_COOKIE_NAME = "phq_session"
SECRET_KEY = os.getenv("FLASK_SESSION_SECRET_KEY")
PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
