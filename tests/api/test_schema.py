import pytest
from django.core.management import call_command


def test_openapi_schema_is_valid_and_warning_free(tmp_path):
    """Undocumented or ambiguous endpoints fail the build, so the docs can't rot."""
    call_command(
        "spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "schema.yml")
    )


@pytest.mark.django_db
def test_docs_and_schema_are_public(client):
    assert client.get("/api/docs/").status_code == 200
    assert client.get("/api/schema/").status_code == 200
