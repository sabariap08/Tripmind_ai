"""Development seed: creates ONLY the Main Admin account.

All providers and normal users must register through the public registration
flow (role-specific forms, Admin approval for providers). No test/demo
accounts and no hardcoded sample catalogue are created.

Main Admin (development environment):
    Email:    admin@tripmind.com
    Password: admin@123
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash
from services.mongodb import get_collection
from services.auth import new_user_id
from datetime import datetime

ADMIN_EMAIL = "admin@tripmind.com"
LEGACY_ADMIN_EMAIL = "admin"
ADMIN_PASSWORD = "admin@123"


def seed_admin():
    users = get_collection("users")
    existing = users.find_one({"email": ADMIN_EMAIL})
    if existing:
        print("Main Admin already exists (email=%r)." % ADMIN_EMAIL)
        return 0
    legacy = users.find_one({"email": LEGACY_ADMIN_EMAIL})
    if legacy:
        users.update_one({"_id": legacy["_id"]}, {"$set": {"email": ADMIN_EMAIL}})
        print("Migrated legacy Main Admin (email=%r -> %r)." % (LEGACY_ADMIN_EMAIL, ADMIN_EMAIL))
        return 1
    users.insert_one({
        "_id": new_user_id(),
        "name": "Main Admin",
        "email": ADMIN_EMAIL,
        "passwordHash": generate_password_hash(ADMIN_PASSWORD),
        "role": "ADMIN",
        "status": "ACTIVE",
        "approved": True,
        "approvalStatus": "APPROVED",
        "approvalReason": "",
        "profile": {"scope": "all"},
        "createdAt": datetime.utcnow().isoformat(),
    })
    print("Created Main Admin (email=%r)." % ADMIN_EMAIL)
    return 1


def seed_all():
    return seed_admin()


if __name__ == "__main__":
    seed_all()