from optopus_studio.schema import SCHEMA_DIR, render


def test_the_schema_files_are_up_to_date():
    for name, text in render().items():
        path = SCHEMA_DIR / name
        assert path.is_file(), f"run `uv run python -m optopus_studio.schema` to write {name}"
        assert path.read_text() == text, (
            f"schema/{name} is out of date: run `uv run python -m optopus_studio.schema` and "
            "`npm run gen:types` in frontend/"
        )
