from app.core.config import Settings, Sub2APIDatabaseSettings, load_config_file
from app.services.sub2api_database import safe_database_config


def test_external_config_loads_sub2api_database(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
sub2api:
  database:
    host: "sub2api-postgres"
    port: 5432
    user: "newapi"
    password: "secret-password"
    dbname: "newapi"
    sslmode: "disable"
    connect_timeout_seconds: 7
""",
        encoding="utf-8",
    )

    settings = Settings(**load_config_file(str(config_file)))

    assert settings.sub2api.database.is_configured is True
    assert settings.sub2api.database.host == "sub2api-postgres"
    assert settings.sub2api.database.user == "newapi"
    assert settings.sub2api.database.dbname == "newapi"
    assert settings.sub2api.database.connect_timeout_seconds == 7


def test_sub2api_database_dsn_is_masked() -> None:
    database = Sub2APIDatabaseSettings(
        host="sub2api-postgres",
        user="newapi",
        password="secret-password",
        dbname="newapi",
    )

    safe_config = safe_database_config(database)

    assert safe_config["configured"] is True
    assert safe_config["has_password"] is True
    assert safe_config["dsn"] == (
        "postgresql://newapi:<masked>@sub2api-postgres:5432/newapi?sslmode=disable"
    )
    assert "secret-password" not in safe_config["dsn"]
