"""The review Function ships with the site (D29): `site deploy` uploads web/functions with the
static site, a Function change redeploys, and takes the full path of a run."""

from pathlib import Path

import pytest

from escapadinha import pipeline, run_path
from escapadinha.website import build_site
from escapadinha.website import deploy as site_deploy
from test_pipeline import ctx  # noqa: F401

REPO = Path(__file__).parent.parent


def web(root: Path) -> Path:
    """A small web package: two routes, a shared lib module, and a lib file nobody imports."""
    w = root / "web"
    files = {
        "functions/review/index.ts": 'import { serve } from "../_lib/review/serve";\nexport const onRequest = serve;\n',
        "functions/review/[[path]].ts": 'import { serve } from "../_lib/review/serve";\nexport const onRequest = serve;\n',
        "functions/_lib/review/serve.ts": ('import { eur } from "../../../src/lib/format";\n'
                                           'import type { X } from "./types";\nexport const serve = () => eur(1);\n'),
        "functions/_lib/review/types.ts": "export type X = number;\n",
        "src/lib/format.ts": "export const eur = (n: number) => `${n} €`;\n",
        "src/lib/site-data.ts": 'import { readFileSync } from "node:fs";\n',
        "src/pages/index.astro": "<p>site</p>\n",
    }
    for rel, text in files.items():
        (w / rel).parent.mkdir(parents=True, exist_ok=True)
        (w / rel).write_bytes(text.encode("utf-8"))     # LF, as git checks out on the runner
    return w


@pytest.fixture
def wrangler(monkeypatch):
    """Records each wrangler call with the files its working directory holds at that moment."""
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = "Deployment complete! https://abc123.ondestaanocas.pages.dev"

    def fake(ctx, *args, cwd=None):
        cwd = Path(cwd) if cwd else ctx.site_dir          # _wrangler's default
        calls.append({"args": args, "cwd": cwd,
                      "files": sorted(p.relative_to(cwd).as_posix() for p in cwd.rglob("*") if p.is_file())})
        return Done()

    monkeypatch.setattr(site_deploy, "_wrangler", fake)
    return calls


def test_function_files_are_the_functions_and_what_they_import(tmp_path):
    w = web(tmp_path)
    assert [p.relative_to(w).as_posix() for p in site_deploy.function_files(w)] == [
        "functions/_lib/review/serve.ts", "functions/_lib/review/types.ts",
        "functions/review/[[path]].ts", "functions/review/index.ts", "src/lib/format.ts"]
    assert site_deploy.function_files(tmp_path / "nowhere") == []


def test_side_effect_and_dynamic_imports_are_staged_too(tmp_path):
    w = web(tmp_path)
    (w / "functions/_lib/review/types.ts").write_text(
        'import "../../../src/lib/polyfill";\n'
        "export type X = number;\n"
        'export const later = () => import("../../../src/lib/lazy");\n'
        "export const again = async () => await import ( './more' );\n", "utf-8")
    for rel in ("src/lib/polyfill.ts", "src/lib/lazy.ts", "functions/_lib/review/more.ts"):
        (w / rel).write_text("export {};\n", "utf-8")
    files = [p.relative_to(w).as_posix() for p in site_deploy.function_files(w)]
    assert {"src/lib/polyfill.ts", "src/lib/lazy.ts", "functions/_lib/review/more.ts"} <= set(files)
    assert "src/lib/site-data.ts" not in files


@pytest.mark.parametrize("source", ['import "node:crypto";\n', 'const m = await import("zod");\n'])
def test_package_side_effect_or_dynamic_imports_stop_the_deploy(tmp_path, source):
    w = web(tmp_path)
    (w / "functions/_lib/review/types.ts").write_text(source, "utf-8")
    with pytest.raises(site_deploy.DeployError, match="imports the package"):
        site_deploy.function_files(w)


def test_deploy_lists_the_function_files_once(ctx, wrangler, monkeypatch):
    web(ctx.root)
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    calls = []
    real = site_deploy.function_files
    monkeypatch.setattr(site_deploy, "function_files", lambda w: calls.append(w) or real(w))
    assert site_deploy.deploy(ctx, conn)[0]
    assert len(calls) == 1 and len(wrangler) == 1


def test_a_missing_import_stops_the_deploy(tmp_path):
    w = web(tmp_path)
    (w / "functions/_lib/review/types.ts").write_text('import { y } from "./gone";\n', "utf-8")
    with pytest.raises(site_deploy.DeployError, match="gone"):
        site_deploy.function_files(w)


def test_the_repositorys_functions_bundle_from_the_staged_files_only():
    """The real web/functions: every import resolves inside the staged set, no npm package."""
    files = {p.relative_to(REPO / "web").as_posix() for p in site_deploy.function_files(REPO / "web")}
    assert {"functions/review/index.ts", "functions/review/[[path]].ts",
            "functions/_lib/review/handler.ts", "src/lib/format.ts"} <= files
    assert all(f.startswith(("functions/", "src/lib/")) for f in files)


def test_deploy_uploads_the_functions_with_the_site(ctx, wrangler):
    web(ctx.root)
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    assert site_deploy.deploy(ctx, conn)[0]
    [call] = wrangler
    assert call["args"][:2] == ("pages", "deploy")
    assert Path(call["args"][2]) == ctx.site_dir.resolve()             # the site, by absolute path
    # wrangler runs in a staging folder holding only functions/ and the modules they import:
    # it compiles <cwd>/functions and never scans the repository (D15).
    assert call["files"] == ["functions/_lib/review/serve.ts", "functions/_lib/review/types.ts",
                             "functions/review/[[path]].ts", "functions/review/index.ts",
                             "src/lib/format.ts"]
    assert call["cwd"] != ctx.site_dir and not call["cwd"].exists()   # removed afterwards


def test_a_function_change_redeploys_an_unchanged_site(ctx, wrangler):
    w = web(ctx.root)
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    assert site_deploy.deploy(ctx, conn)[0]
    assert site_deploy.deploy(ctx, conn) == (False, "site unchanged since last deploy, skipped")
    (w / "src/lib/format.ts").write_text("export const eur = (n: number) => `${n} €`;\n", "utf-8")
    assert site_deploy.deploy(ctx, conn)[0]
    # Line endings don't count: a Windows checkout and the runner's agree.
    serve = w / "functions/_lib/review/serve.ts"
    serve.write_bytes(serve.read_bytes().replace(b"\n", b"\r\n"))
    assert not site_deploy.deploy(ctx, conn)[0]
    assert len(wrangler) == 2


def test_without_functions_wrangler_runs_inside_the_site(ctx, wrangler):
    conn = pipeline.open_db(ctx)
    build_site(ctx, conn)
    site_deploy.deploy(ctx, conn)
    assert wrangler[0]["cwd"] == ctx.site_dir


def test_a_function_change_takes_the_full_path(ctx):
    w = web(ctx.root)
    conn = pipeline.open_db(ctx)
    run_path.record_full_path(ctx, conn)
    assert not run_path.decide(ctx, conn).full
    (w / "functions/review/index.ts").write_text("export const onRequest = () => new Response('x');\n", "utf-8")
    decision = run_path.decide(ctx, conn)
    assert decision.full and "code" in decision.reason
    run_path.record_full_path(ctx, conn)
    (w / "src/lib/site-data.ts").write_text("// not part of the Function\n", "utf-8")
    assert not run_path.decide(ctx, conn).full
