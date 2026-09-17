from src.application.exceptions import UserNotFoundError
from src.application.ports.uow import UnitOfWork
from src.application.ports.usecases import DeleteUserPort


class DeleteUser(DeleteUserPort):
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, user_id: int) -> None:
        async with self._uow as uow:
            deleted = await uow.users.delete(user_id)
            if deleted:
                await uow.commit()
            else:
                raise UserNotFoundError
