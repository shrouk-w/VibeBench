from app.exports.archive import safe_path


def test_archive_keeps_source_and_excludes_unsafe_paths():
    assert str(safe_path("workspace/src/app.ts", True)) == "src/app.ts"
    for path in [
        "workspace/../private",
        "/workspace/private",
        "workspace/node_modules/pkg/index.js",
        "workspace/.env.production",
        "workspace/.git/config",
        "workspace/C:/file",
        "workspace/folder\\file",
        "workspace/private.pem",
        "workspace/subdir/auth.json",
    ]:
        assert safe_path(path, True) is None
    assert safe_path("workspace/symlink", False) is None
