from careos.db.repositories.store import InMemoryStore
from careos.db.repositories.store import PostgresStore
from careos.domain.enums.core import Role
from careos.domain.models.api import ParticipantCreate, PersonIdentityCreate, TenantCreate, TenantMembershipCreate


def test_store_creates_global_identity_once_per_phone() -> None:
    store = InMemoryStore()

    first = store.create_person_identity(
        PersonIdentityCreate(
            phone_number="whatsapp:+15551112222",
            display_name="Same Human",
        )
    )
    second = store.create_person_identity(
        PersonIdentityCreate(
            phone_number="+15551112222",
            display_name="Same Human Again",
        )
    )

    assert first["id"] == second["id"]
    assert first["normalized_phone_number"] == "+15551112222"


def test_store_allows_same_person_to_join_multiple_tenants() -> None:
    store = InMemoryStore()
    tenant_a = store.create_tenant(TenantCreate(name="Family A"))
    tenant_b = store.create_tenant(TenantCreate(name="Family B"))
    identity = store.create_person_identity(
        PersonIdentityCreate(
            phone_number="whatsapp:+15553334444",
            display_name="Shared Caregiver",
        )
    )

    membership_a = store.create_tenant_membership(
        TenantMembershipCreate(
            tenant_id=tenant_a["id"],
            person_identity_id=identity["id"],
            membership_type="caregiver_member",
            display_name="Shared Caregiver",
        )
    )
    membership_b = store.create_tenant_membership(
        TenantMembershipCreate(
            tenant_id=tenant_b["id"],
            person_identity_id=identity["id"],
            membership_type="caregiver_member",
            display_name="Shared Caregiver",
        )
    )

    assert membership_a["tenant_id"] != membership_b["tenant_id"]
    memberships = store.list_tenant_memberships_for_person(identity["id"])
    assert len(memberships) == 2


def test_store_deduplicates_membership_within_same_tenant() -> None:
    store = InMemoryStore()
    tenant = store.create_tenant(TenantCreate(name="Family"))
    identity = store.create_person_identity(
        PersonIdentityCreate(
            phone_number="whatsapp:+15556667777",
            display_name="Existing Member",
        )
    )

    first = store.create_tenant_membership(
        TenantMembershipCreate(
            tenant_id=tenant["id"],
            person_identity_id=identity["id"],
            membership_type="mixed_member",
            display_name="Existing Member",
        )
    )
    second = store.create_tenant_membership(
        TenantMembershipCreate(
            tenant_id=tenant["id"],
            person_identity_id=identity["id"],
            membership_type="caregiver_member",
            display_name="Existing Member Changed",
        )
    )

    assert first["id"] == second["id"]


def test_store_backfills_identity_membership_for_existing_participant() -> None:
    store = InMemoryStore()
    tenant = store.create_tenant(TenantCreate(name="Family"))
    participant = store.create_participant(
        ParticipantCreate(
            tenant_id=tenant["id"],
            role=Role.CAREGIVER,
            display_name="Existing Caregiver",
            phone_number="whatsapp:+15559990000",
        )
    )

    result = store.ensure_identity_membership_for_participant(participant["id"])

    assert result["participant"]["person_identity_id"] == result["person_identity"]["id"]
    assert result["participant"]["tenant_membership_id"] == result["tenant_membership"]["id"]
    assert result["tenant_membership"]["tenant_id"] == tenant["id"]


def test_postgres_store_get_participant_record_tolerates_old_schema(monkeypatch) -> None:
    rollback_called = False

    class FakeCursor:
        def __init__(self) -> None:
            self.description = None
            self._row = None
            self._executed = 0

        def execute(self, sql: str, params: dict) -> None:  # noqa: ARG002
            self._executed += 1
            if self._executed == 1:
                raise Exception('column "person_identity_id" does not exist')
            self.description = [
                ("id",),
                ("tenant_id",),
                ("role",),
                ("display_name",),
                ("phone_number",),
                ("preferred_channel",),
                ("preferred_language",),
                ("active",),
            ]
            self._row = (
                "participant-1",
                "tenant-1",
                "caregiver",
                "Fallback User",
                "whatsapp:+15550000001",
                "whatsapp",
                "en",
                True,
            )

        def fetchone(self):
            return self._row

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    class FakeConnection:
        def rollback(self) -> None:
            nonlocal rollback_called
            rollback_called = True

        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    monkeypatch.setattr("careos.db.repositories.store.get_connection", lambda _: FakeConnection())
    store = PostgresStore("postgresql://unused")

    record = store.get_participant_record("participant-1")

    assert record is not None
    assert record["id"] == "participant-1"
    assert record["person_identity_id"] is None
    assert record["tenant_membership_id"] is None
    assert rollback_called is True
