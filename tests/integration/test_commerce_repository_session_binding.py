import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.quota_repository import QuotaRepository
from AssetsManager.repositories.shop_repository import ShopRepository


@pytest.mark.parametrize(
    "repository_type",
    [ShopRepository, OrderRepository, QuotaRepository],
    ids=["shop", "order", "quota"],
)
def test_commerce_repository_is_bound_to_library_session(repository_type, tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        repository = repository_type.for_session(first)
        assert repository._library_root_key == first.context.root_identity.map_key

        foreign_connection = first.connection_for(first.root)
        with pytest.raises(ValueError, match=r"(?i)(different|belong|root|connection)"):
            repository_type(foreign_connection, session=second)

        first.close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            repository.init_tables()
    finally:
        bootstrap.library_service.close()
