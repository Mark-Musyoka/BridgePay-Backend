from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.modules.auth.service import issue_verification_token, revoke_all_for_user
from app.modules.auth.tasks import send_verification_email
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import notify
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


class EmailAlreadyTaken(Exception):
    pass


class IncorrectCurrentPassword(Exception):
    pass


async def update_profile(
    db: AsyncSession,
    *,
    user: User,
    full_name: str | None,
    email: str | None,
    country: str | None,
) -> User:
    """
    Updates whichever fields were provided. Changing the email is treated
    as a meaningful security/trust event: it resets is_verified (a new
    email address hasn't been proven to belong to this person yet) and
    triggers the same verification flow as registration — issuing a
    fresh token and queuing the mocked verification email to the NEW
    address, not the old one.
    """
    user_repo = UserRepository(db)

    if full_name is not None:
        user.full_name = full_name

    if country is not None:
        user.country = country

    email_changed = False
    if email is not None and email != user.email:
        existing = await user_repo.get_by_email(email)
        if existing is not None and existing.id != user.id:
            raise EmailAlreadyTaken(f"{email} is already registered to another account")

        user.email = email
        user.is_verified = False
        email_changed = True

    await db.flush()

    if email_changed:
        raw_token = await issue_verification_token(db, user.id)
        await notify(
            db,
            user_id=user.id,
            user_email=user.email,
            type=NotificationType.account_update,
            title="Email address changed",
            body=f"Your account email was changed to {user.email}. Please verify it to keep sending money.",
        )
        try:
            send_verification_email.delay(to_email=user.email, raw_token=raw_token)
        except Exception:
            pass

    return user


async def change_password(db: AsyncSession, *, user: User, current_password: str, new_password: str) -> None:
    """
    Requires the current password (unlike the forgot-password reset flow,
    which deliberately doesn't, since that's for when you can't log in at
    all). Revokes every refresh token for the user afterward — same
    reasoning as password-reset-confirm: a password change is a signal
    worth treating as "kill existing sessions," whether the change was
    the user's own doing or evidence their account was compromised and
    they're locking it down.
    """
    if not verify_password(current_password, user.hashed_password):
        raise IncorrectCurrentPassword("Current password is incorrect")

    user.hashed_password = hash_password(new_password)
    await revoke_all_for_user(db, user.id)

    await notify(
        db,
        user_id=user.id,
        user_email=user.email,
        type=NotificationType.security_alert,
        title="Password changed",
        body="Your password was changed. If this wasn't you, reset your password immediately.",
    )
