from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime import (  # noqa: E402
    BrowserHealth,
    BrowserHealthStatus,
    BrowserLaunchOptions,
    ManagedBrowserSession,
    ProfileManager,
    SessionBootstrapper,
)


class StubSession:
    provider_name = "stub"

    def __init__(self) -> None:
        self.closed = False
        self.logged_in = False

    @property
    def raw_handle(self):
        return self

    def is_alive(self):
        return not self.closed

    def health(self):
        return BrowserHealth(BrowserHealthStatus.HEALTHY)

    def recover(self, reason=""):
        return not self.closed

    def close(self):
        self.closed = True

    def set_window_size(self, width, height):
        pass

    def navigate(self, url):
        pass

    def wait_until_logged_in(self, timeout=600):
        self.logged_in = True

    def start_new_chat(self):
        pass

    def select_model(self, model):
        pass

    def assistant_message_count(self):
        return 0

    def upload(self, request):
        pass

    def send_message(self, text):
        pass

    def wait_for_response(self, request):
        pass

    def snapshot_downloads(self):
        return {}

    def resolve_download(self, request):
        return None

    def latest_assistant_text(self):
        return ""

    def save_screenshot(self, path):
        return False

    def get_page_source(self):
        return ""

    def get_cookies(self):
        return ()

    def delete_cookie(self, name):
        pass


class StubProvider:
    name = "stub"

    def __init__(self) -> None:
        self.options = []
        self.sessions = []

    def open_session(self, options=None):
        self.options.append(options)
        session = StubSession()
        self.sessions.append(session)
        return session

    def wrap_handle(self, handle):
        return handle


class FailingProvider(StubProvider):
    def open_session(self, options=None):
        raise RuntimeError("startup failed")


class SessionBootstrapTests(unittest.TestCase):
    def test_bootstrap_injects_isolated_paths_validates_login_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ProfileManager(runtime_root=root / "runtime", snapshot_root=root / "snapshots")
            first_context = manager.prepare_worker(run_id="run", worker_id="worker-1")
            second_context = manager.prepare_worker(run_id="run", worker_id="worker-2")
            provider = StubProvider()
            bootstrapper = SessionBootstrapper(profile_manager=manager)

            first = bootstrapper.open_session(
                provider=provider,
                context=first_context,
                options=BrowserLaunchOptions(url="about:blank"),
                validate_login=True,
            )
            second = bootstrapper.open_session(
                provider=provider,
                context=second_context,
                options=BrowserLaunchOptions(url="about:blank"),
                validate_login=True,
            )

            self.assertIsInstance(first, ManagedBrowserSession)
            self.assertTrue(provider.sessions[0].logged_in)
            self.assertTrue(provider.sessions[1].logged_in)
            self.assertEqual(provider.options[0].profile_dir, first_context.profile_dir)
            self.assertEqual(provider.options[1].profile_dir, second_context.profile_dir)
            self.assertNotEqual(provider.options[0].profile_dir, provider.options[1].profile_dir)
            self.assertTrue((first_context.profile_dir / ".note-maker-profile-owner.json").exists())
            self.assertTrue((second_context.profile_dir / ".note-maker-profile-owner.json").exists())

            first.close()
            self.assertFalse((first_context.profile_dir / ".note-maker-profile-owner.json").exists())
            self.assertTrue((second_context.profile_dir / ".note-maker-profile-owner.json").exists())
            self.assertTrue(second.is_alive())
            second.close()


    def test_before_open_runs_while_profile_lease_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ProfileManager(runtime_root=root / "runtime", snapshot_root=root / "snapshots")
            context = manager.prepare_worker(run_id="run", worker_id="worker-1")
            provider = StubProvider()
            observed = []

            session = SessionBootstrapper(profile_manager=manager).open_session(
                provider=provider,
                context=context,
                options=BrowserLaunchOptions(),
                validate_login=False,
                before_open=lambda worker: observed.append(
                    (worker.worker_id, (worker.profile_dir / ".note-maker-profile-owner.json").exists())
                ),
            )
            try:
                self.assertEqual(observed, [("worker-1", True)])
            finally:
                session.close()

    def test_startup_failure_releases_profile_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ProfileManager(runtime_root=root / "runtime", snapshot_root=root / "snapshots")
            context = manager.prepare_worker(run_id="run", worker_id="worker-1")
            bootstrapper = SessionBootstrapper(profile_manager=manager)

            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                bootstrapper.open_session(
                    provider=FailingProvider(),
                    context=context,
                    options=BrowserLaunchOptions(),
                )
            self.assertFalse((context.profile_dir / ".note-maker-profile-owner.json").exists())


if __name__ == "__main__":
    unittest.main()
