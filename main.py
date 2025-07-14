"""Entry point"""
import datetime
import os
import re
from datetime import datetime, timezone

import flask
import securescaffold

from flask_talisman import Talisman
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
load_dotenv()

import models

app = securescaffold.create_app(__name__)
talisman = Talisman(app)
oauth = OAuth(app)

#Register google outh
GOOGLE_AUTH_CLIENT_ID=os.getenv("GOOGLE_AUTH_CLIENT_ID")
GOOGLE_AUTH_CLIENT_SECRET=os.getenv("GOOGLE_AUTH_CLIENT_SECRET")
GOOGLE_AUTH_METADATA_CONF_URL=os.getenv("GOOGLE_AUTH_METADATA_CONF_URL")

google = oauth.register(
    name = "google",
    server_metadata_url = GOOGLE_AUTH_METADATA_CONF_URL,
    client_id = GOOGLE_AUTH_CLIENT_ID,
    client_secret = GOOGLE_AUTH_CLIENT_SECRET,
    client_kwargs = {
        "scope": "openid email profile"
    }
)

@app.route("/")
def dashboard():
    ghostnames = models.get_ghost_all_names()
    context = {
        "page_title": "Secure Scaffold",
        "ghostnames": ghostnames,
        "user": flask.session.get("user", None),
    }

    return flask.render_template("dashboard.html", **context)


@app.route("/account", methods=["GET", "POST"])
def account():
    """User Account gated by Google Auth"""
    if "user" not in flask.session:
        # TODO: Make a decorator out of it
        redirect_uri = flask.url_for("authorize", _external=True)
        client = oauth.create_client("google")
        return client.authorize_redirect(redirect_uri)
    else:
        email = flask.session["user"].get("email", "")
        first_name = flask.session["user"].get("first_name", "")
        last_name = flask.session["user"].get("last_name", "")
        if email:
            error_message = ""
            if flask.request.method == "POST":
                first_name = flask.request.form.get("first_name")
                last_name = flask.request.form.get("last_name")
                pattern = r"^[A-Za-z\s'\-]+$"
                if (not first_name or
                    not last_name or
                    not re.match(pattern, first_name) or
                    not re.match(pattern, last_name)
                ):
                    error_message = (
                        "First name and last name are required."
                        "Only letters, spaces, apostrophes, and hyphens "
                        "are allowed."
                    )
                if not error_message:
                    # check if the names have changed
                    if (flask.session["user"].get("first_name") != first_name or
                        flask.session["user"].get("last_name") != last_name):
                        # Update session with new names
                        flask.session["user"]["first_name"] = first_name
                        flask.session["user"]["last_name"] = last_name
                        # TODO: Update user document in the database
                        if models.update_user(
                            email, first_name, last_name
                        ) is None:
                            error_message = "Failed to update user information."
                            # TODO: Handle error, redirect to error page
                            return flask.redirect(flask.url_for("dashboard"))
                    # Next to the ghost name picker page
                    return flask.redirect(flask.url_for("ghostname"))
                else:
                    # sanitize input
                    first_name = re.sub(r"[^A-Za-z\s'\-]", "", first_name)
                    last_name = re.sub(r"[^A-Za-z\s'\-]", "", last_name)
            context = {
                "page_title": "Account",
                "email": "",
                "error_message": error_message,
            }
            context["email"] = f"Hello {email}!"
            context["first_name"] = first_name
            context["last_name"] = last_name
            return flask.render_template("account.html", **context)
        else:
            flask.session.pop("user", None)
            return flask.redirect(flask.url_for("dashboard"))


@app.route("/authorize")
def authorize():
    """Authorize user with Google OAuth"""
    response = google.authorize_access_token()
    user_info = google.parse_id_token(
        response,
        nonce=flask.session.get("nonce")
    )
    if not user_info:
        # TODO: Handle error, redirect to error page
        return flask.redirect(flask.url_for("dashboard"))

    the_user = models.create_or_get_user(email=user_info.get("email", ""))
    if the_user is None:
        # TODO: Handle error, redirect to error page
        return flask.redirect(flask.url_for("dashboard"))

    flask.session["user"] = {
        "email": the_user.email,
        "first_name": the_user.first_name,
        "last_name": the_user.last_name,
    }
    flask.session.permanent = True

    return flask.redirect(flask.url_for("account"))

@app.route("/logout")
def logout():
    """Logout user by nuking the session"""
    flask.session.pop("user", None)
    return flask.redirect(flask.url_for("dashboard"))

@app.route("/ghostname", methods=["GET", "POST"])
def ghostname():
    """Ghost Name Picker Page"""
    if "user" not in flask.session:
        # TODO: Make a decorator out of it
        redirect_uri = flask.url_for("authorize", _external=True)
        client = oauth.create_client("google")
        return client.authorize_redirect(redirect_uri)
    else:
        if flask.request.method == "POST":
            ghost_unique_hash = flask.request.form.get("ghost_unique_hash")
            reserved_at_str = flask.request.form.get("reserved_at")
            reserved_at = (
                datetime.fromisoformat(reserved_at_str).astimezone(timezone.utc).replace(tzinfo=None)
            )
            models.select_ghost_name(
                ghost_unique_hash,
                reserved_at,
                flask.session["user"]["email"]
            )
            return flask.redirect(flask.url_for("dashboard"))
        else:
            free_ghost_names = models.reserve_three_ghost_names()
            if not free_ghost_names:
                # TODO: Handle error, redirect to error page
                return flask.redirect(flask.url_for("dashboard"))
            context = {
                "page_title": "Choose Your Ghost Name",
                "free_ghost_names": free_ghost_names,
            }
            return flask.render_template("ghostname.html", **context)
