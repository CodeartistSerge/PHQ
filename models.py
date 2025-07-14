"""Client library that provides a way to interact with Google Cloud Datastore"""
from datetime import datetime, timedelta, timezone
import os
import flask
from google.cloud import ndb
from dotenv import load_dotenv
load_dotenv()
PROJECT_ID = os.getenv("GOOGLE_AUTH_PROJECT_ID", "")
JSON_PATH  = os.getenv("DATA_GHOSTS_FILE", "")
if not PROJECT_ID or not JSON_PATH or not os.path.exists(JSON_PATH):
    raise ValueError((
        "Please set GOOGLE_AUTH_PROJECT_ID and "
        "DATA_GHOSTS_FILE environment variables correctly."
    ))
client = ndb.Client(project=PROJECT_ID)

class User(ndb.Model):
    """User names model definition"""

    # Indexed for the sake of unique checks upon registrations
    email = ndb.StringProperty(required=True)
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    ghost_name = ndb.StringProperty(default="")
    ghost_description = ndb.TextProperty(default="")
    # Refers back to the GhostNames model unique hash
    ghost_unique_hash = ndb.StringProperty(default="")

    # QOL misc fields
    created_at = ndb.DateTimeProperty(indexed=False, auto_now_add=True)
    updated_at = ndb.DateTimeProperty(indexed=False, auto_now_add=True)

class GhostNames(ndb.Model):
    """Ghost names model definition"""
    # Idexed so we can pass it around the front and query by it
    ghost_unique_hash = ndb.StringProperty(required=True, indexed=True)
    ghost_name = ndb.StringProperty(required=True)
    ghost_description = ndb.TextProperty(default="")
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    # Indexed so we can query free and taken names
    email = ndb.StringProperty()
    # We need this one indexed, so we can show the same choice upon page refresh
    # Potential TODO: implement frontend caching to decrease number of reads
    reserved_by_email = ndb.StringProperty()
    # Indexed so we can check if a name is reserved as a choice of three names
    reserved_at = ndb.DateTimeProperty(auto_now_add=True)

    # QOL misc fields
    created_at = ndb.DateTimeProperty(indexed=False, auto_now_add=True)
    updated_at = ndb.DateTimeProperty(indexed=False, auto_now_add=True)

def create_or_get_user(email):
    """Create a new user in the datastore"""
    with client.context():
        # Check if the user already exists
        try:
            existing_user = User.query(User.email == email).get()
            if existing_user:
                return existing_user
            # Create a new user
            user = User(email=email)
            user.put()
            return user
        except ndb.exceptions.Error as e:
            print(f"Error creating user: {e}")
            return None

def update_user(email, first_name, last_name):
    """Update user information in the datastore"""
    # TODO: Fan out to the ghost names
    with client.context():
        try:
            @ndb.transactional(retries=0)
            def _trx(ghost_name):
                if ghost_name:
                    ghost_name.first_name = first_name
                    ghost_name.last_name = last_name
                    ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    ghost_name.put()

            user = User.query(User.email == email).get()
            if user:
                user.first_name = first_name
                user.last_name = last_name
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                user.put()
                ghost_name = GhostNames.query(
                    GhostNames.email == email
                ).get()
                _trx(ghost_name)
                return user
            else:
                print(f"User with email {email} not found.")
                return None
        except ndb.exceptions.Error as e:
            print(f"Error updating user: {e}")
            return None

def get_ghost_all_names():
    """Get all ghost names from the datastore"""
    with client.context():
        try:
            return GhostNames.query(
                # NOTE: Legacy datastore quirk, don't want to switch emulator rn
                GhostNames.email > "",
            ).fetch()
        except ndb.exceptions.Error as e:
            print(f"Error fetching ghost names: {e}")
            return []

def select_ghost_name(ghost_unique_hash, reserved_at, email):
    """Select a ghost name by its unique hash and reserve it for the user"""
    with client.context():
        # All transactions pass or fail alltogether,
        # everything is rolled back in case of an error
        # This is to cover for the optimistic concurrency
        # No need to try more than once, as if it fails,
        # it means we can safely bail out and retry
        @ndb.transactional(retries=0)
        def _trx(reserved_at, email, user, selected_ghost_name, reserved_ghost_names, old_selected_ghost_name):
            for ghost_name in reserved_ghost_names:
                ghost_name.reserved_by_email = ""
                ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) # pylint: disable=line-too-long
                ghost_name.put()
            if old_selected_ghost_name:
                old_selected_ghost_name.email = ""
                old_selected_ghost_name.first_name = ""
                old_selected_ghost_name.last_name = ""
                old_selected_ghost_name.reserved_by_email = ""
                old_selected_ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                old_selected_ghost_name.put()

            # Select the ghost name for the user
            # taking into account optimistic concurrency
            selected_ghost_name.email = email
            selected_ghost_name.first_name = flask.session["user"].get("first_name", "")
            selected_ghost_name.last_name = flask.session["user"].get("last_name", "")
            selected_ghost_name.reserved_by_email = email
            selected_ghost_name.reserved_at = reserved_at
            selected_ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) # pylint: disable=line-too-long
            selected_ghost_name.put()

            # Update the user with the selected ghost name
            if user:
                user.ghost_name = selected_ghost_name.ghost_name
                user.ghost_description = selected_ghost_name.ghost_description
                user.ghost_unique_hash = selected_ghost_name.ghost_unique_hash
                user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                user.put()
                flask.session["user"]["ghost_name"] = selected_ghost_name.ghost_name
                flask.session["user"]["ghost_description"] = selected_ghost_name.ghost_description
                flask.session["user"]["ghost_unique_hash"] = selected_ghost_name.ghost_unique_hash
            else:
                print(f"User with email {email} not found.")
                return None
            return selected_ghost_name
        try:
            selected_ghost_name = GhostNames.query(
                GhostNames.ghost_unique_hash == ghost_unique_hash
            ).get()
            if not selected_ghost_name:
                print(f"Ghost name with hash {ghost_unique_hash} not found.")
                return None
            # Free up reserved and selected ghost names
            reserved_ghost_names = GhostNames.query(
                (GhostNames.reserved_by_email == email)
            ).fetch(3)
            old_selected_ghost_name = GhostNames.query(
                (GhostNames.email == email)
            ).get()
            user = User.query(User.email == email).get()
            return _trx(reserved_at, email, user, selected_ghost_name, reserved_ghost_names, old_selected_ghost_name)
        except ndb.exceptions.Error as e:
            print(f"Error reserving ghost name: {e}")
            return None

def reserve_three_ghost_names():
    """Get all free ghost names from the datastore"""
    # NOTE: it re-reserves three ghost names upon every refresh,
    # so there's a place for a reasonable debounce and caching improvement
    with client.context():
        try:
            # Again, all or nothing transaction
            # This is to cover for the optimistic concurrency
            @ndb.transactional(retries=0)
            def _trx(free_ghost_names, reserved_ghost_names, email):
                # Since it is possible edge case that
                # your reserved ghost name could expire
                # and get picked up by another user, we need to ensure
                # that we filetr out any picked up ghost names
                reserved_ghost_names_filtered = [
                    ghost for ghost in reserved_ghost_names
                    if ghost.email == email or ghost.email == ""
                ]
                # Since we can only have 3 reserved ghost names at any time,
                # clean out free_ghost_names off the potentially reserved ones
                # by the current user, but expired
                # Querying 6 of them, should be enough to cover for every case
                free_ghost_names = [
                    ghost for ghost in free_ghost_names
                        if ghost.email != email
                ]
                ghost_names = reserved_ghost_names_filtered + free_ghost_names
                # trim to max 3 names
                ghost_names = ghost_names[:3]
                if not ghost_names or len(ghost_names) < 1:
                    print("No free ghost names available.")
                    return []
                # Free previously reserved ghost names
                for ghost_name in free_ghost_names:
                    ghost_name.reserved_by_email = ""
                    ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) # pylint: disable=line-too-long
                    ghost_name.put()
                # Reserve the ghost names for the user
                for ghost_name in ghost_names:
                    ghost_name.reserved_by_email = email
                    ghost_name.reserved_at = datetime.now(timezone.utc).replace(tzinfo=None) # pylint: disable=line-too-long
                    ghost_name.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) # pylint: disable=line-too-long
                    ghost_name.put()
                return ghost_names

            # Fetch ghost names that are not reserved
            # or reserved by current user
            # or reservation time is more than 1h ago
            # limit to first 3
            # prioritize current user's reserved names
            email = flask.session["user"].get("email", "")
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None) # pylint: disable=line-too-long
            if not email:
                print("No user email found in session.")
                return []
            # Fetch ghost names that are not reserved
            # or reserved more than 1 hour ago
            reserved_ghost_names = GhostNames.query(
                (GhostNames.reserved_by_email == email)
            ).fetch(3)
            free_ghost_names = GhostNames.query(
                ndb.AND(
                    GhostNames.email == "",
                    ndb.OR(
                        (GhostNames.reserved_by_email == ""),
                        (GhostNames.reserved_at < cutoff)
                    )
                )
            ).fetch(6)
            return _trx(free_ghost_names, reserved_ghost_names, email)
        except ndb.exceptions.Error as e:
            print(f"Error fetching free ghost names: {e}")
            return []
