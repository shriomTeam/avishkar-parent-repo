import asyncio

from clinic_api import main as api_main
from clinic_core.features import Feature
from clinic_core.settings import Settings


def _feature(key, hook):
    return Feature(key=key, name=key, description="", on_startup=hook)


async def test_a_features_startup_work_runs_without_holding_up_the_app(monkeypatch):
    ran, release = [], asyncio.Event()

    async def slow(app):
        await release.wait()  # would block startup if it were awaited before serving
        ran.append("slow")

    monkeypatch.setattr(api_main, "load_features", lambda: {"slow": _feature("slow", slow)})
    app = api_main.create_app(Settings(allow_dev_auth=True))
    async with api_main.lifespan(app):
        assert ran == []  # the app is up while the hook is still working
        release.set()
        await asyncio.sleep(0.05)
        assert ran == ["slow"]


async def test_a_failing_startup_hook_does_not_stop_the_app_or_the_other_hooks(monkeypatch, caplog):
    ran = []

    async def broken(app):
        raise RuntimeError("boom")

    async def fine(app):
        ran.append("fine")

    monkeypatch.setattr(
        api_main,
        "load_features",
        lambda: {"a": _feature("a", broken), "b": _feature("b", fine), "c": Feature("c", "c", "")},
    )
    app = api_main.create_app(Settings(allow_dev_auth=True))
    async with api_main.lifespan(app):
        await asyncio.sleep(0.05)
    assert ran == ["fine"] and "startup work of feature a failed" in caplog.text


async def test_a_hook_still_running_at_shutdown_is_cancelled(monkeypatch):
    cancelled = []

    async def forever(app):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(api_main, "load_features", lambda: {"x": _feature("x", forever)})
    app = api_main.create_app(Settings(allow_dev_auth=True))
    async with api_main.lifespan(app):
        await asyncio.sleep(0.02)
    assert cancelled == [True]
