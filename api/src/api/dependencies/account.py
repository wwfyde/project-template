from typing import Annotated

from fastapi import Depends, HTTPException

from api.repositories.user_security import AccountError, AccountStore
from api.core.db import AsyncSessionLocal


def get_account_store() -> AccountStore:
    return AccountStore(AsyncSessionLocal)


AccountStoreDep = Annotated[AccountStore, Depends(get_account_store)]


def account_http_error(error: AccountError) -> HTTPException:
    return HTTPException(error.status, {"code": error.code, "message": error.message})
