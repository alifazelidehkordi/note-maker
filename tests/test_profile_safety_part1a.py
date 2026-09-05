from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_common  # noqa: E402
import process_liveness  # noqa: E402
from browser_runtime import (  # noqa: E402
    ActiveProfileError,
    CleanupOutcome,
    CleanupStatus,
    OwnershipState,
    ProfileActivity,
    ProfileLease,
    ProfileManager,
    RetentionPolicy,
)
from browser_runtime.login_bootstrap import LoginBootstrapper  # noqa: E402
from parallel_runtime.coordinator import CoordinatorResult, ParallelCoordinator  # noqa: E402
from parallel_runtime.executors import _BrowserExecutorBase  # noqa: E402


def create_minimal_profile(root: Path, name: str = "profile") -> Path:
    profile = root / name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "Local State").write_text("{}", encoding="utf-8")
    return profile


class OwnershipSafetyTests(unittest.TestCase):
    def build_manager(
        self,
        root: Path,
        *,
        retention: RetentionPolicy = RetentionPolicy.DELETE_ALL,
        snapshot_root: Path | None = None,
    ) -> ProfileManager:
        return ProfileManager(
            runtime_root=root / "runtime",
            snapshot_root=snapshot_root or root / "snapshots",
            retention_policy=retention,
        )

    def write_owner(self, profile: Path, **payload: object) -> Path:
        owner = profile / ".note-maker-profile-owner.json"
        owner.parent.mkdir(parents=True, exist_ok=True)
        owner.write_text(json.dumps(payload), encoding="utf-8")
        return owner

    def test_owner_states_distinguish_active_stale_and_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = create_minimal_profile(root)
            manager = self.build_manager(root / "manager")
            owner = self.write_owner(
                profile,
                pid=4321,
                hostname=socket.gethostname(),
                process_start_identity="identity-a",
            )

            with (
                mock.patch("browser_runtime.profile_safety._pid_alive", return_value=True),
                mock.patch(
                    "browser_runtime.profile_safety._process_start_identity",
                    return_value="identity-a",
                ),
            ):
                self.assertEqual(
                    manager.inspect_activity(profile).ownership_state,
                    OwnershipState.ACTIVE,
                )

            with (
                mock.patch("browser_runtime.profile_safety._pid_alive", return_value=True),
                mock.patch(
                    "browser_runtime.profile_safety._process_start_identity",
                    return_value="identity-b",
                ),
            ):
                self.assertEqual(
                    manager.inspect_activity(profile).ownership_state,
                    OwnershipState.STALE,
                )

            owner.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "hostname": "remote-host.example",
                        "process_start_identity": "identity-a",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                manager.inspect_activity(profile).ownership_state,
                OwnershipState.UNCERTAIN,
            )

    def test_pid_reuse_allows_only_proven_stale_local_lease_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = create_minimal_profile(Path(tmp))
            owner = self.write_owner(
                profile,
                pid=4321,
                hostname=socket.gethostname(),
                process_start_identity="old-start",
            )
            with (
                mock.patch("browser_runtime.profile_safety._pid_alive", return_value=True),
                mock.patch(
                    "browser_runtime.profile_safety._process_start_identity",
                    return_value="new-start",
                ),
            ):
                lease = ProfileLease(profile, run_id="run", worker_id="worker").acquire()
                try:
                    payload = json.loads(owner.read_text(encoding="utf-8"))
                    self.assertEqual(payload["process_start_identity"], "new-start")
                finally:
                    lease.release()
            self.assertFalse(owner.exists())

    def test_active_profile_cannot_be_copied_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            source = create_minimal_profile(root, "source")
            context = manager.prepare_worker(run_id="run", worker_id="worker")
            identity = "stable-process-start"
            with (
                mock.patch(
                    "browser_runtime.profile_safety._process_start_identity",
                    return_value=identity,
                ),
                mock.patch("browser_runtime.profile_safety.time.sleep"),
            ):
                source_lease = ProfileLease(source, run_id="login", worker_id="owner").acquire()
                worker_lease = ProfileLease(
                    context.profile_dir,
                    run_id=context.run_id,
                    worker_id=context.worker_id,
                ).acquire()
                try:
                    with self.assertRaises(ActiveProfileError):
                        manager.create_snapshot(source, require_auth=False)
                    outcome = manager.cleanup_worker(context, success=True)
                    self.assertEqual(outcome.status, CleanupStatus.STILL_ACTIVE)
                    self.assertTrue(context.root.exists())
                finally:
                    worker_lease.release()
                    source_lease.release()

    def test_proven_stale_chromium_singleton_is_recovered_for_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            source = create_minimal_profile(root, "source")
            marker = source / "SingletonLock"
            try:
                marker.symlink_to(f"{socket.gethostname()}-987654321")
            except OSError:
                self.skipTest("Symlinks are unavailable in this environment")

            with mock.patch("browser_runtime.profile_safety._pid_alive", return_value=False):
                snapshot = manager.create_snapshot(source, name="stale", require_auth=False)

            self.assertFalse(marker.exists())
            self.assertTrue(snapshot.path.exists())
            self.assertTrue((snapshot.path / "Local State").exists())

    def test_remote_or_unverifiable_ownership_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = self.build_manager(root)
            context = manager.prepare_worker(run_id="run", worker_id="worker")
            self.write_owner(
                context.profile_dir,
                pid=1234,
                hostname="remote-host.example",
                process_start_identity="remote-start",
            )
            with mock.patch("browser_runtime.profile_safety.time.sleep"):
                outcome = manager.cleanup_worker(context, success=True)

            self.assertEqual(outcome.status, CleanupStatus.RETAINED_BY_POLICY)
            self.assertEqual(outcome.ownership_state, OwnershipState.UNCERTAIN)
            self.assertTrue(context.root.exists())

    def test_run_cleanup_preserves_reusable_snapshot_when_layouts_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root = root / "runtime"
            snapshot_root = runtime_root / "runs" / "run-1" / "snapshots"
            manager = ProfileManager(
                runtime_root=runtime_root,
                snapshot_root=snapshot_root,
                retention_policy=RetentionPolicy.DELETE_ALL,
            )
            source = create_minimal_profile(root, "source")
            snapshot = manager.create_snapshot(source, name="golden", require_auth=False)
            manager.prepare_worker(run_id="run-1", worker_id="worker-001", snapshot=snapshot)

            outcome = manager.cleanup_run("run-1", success=True)

            self.assertEqual(outcome.status, CleanupStatus.DELETED)
            self.assertTrue(snapshot.path.exists())
            self.assertEqual(manager.load_snapshot(snapshot.path).snapshot_id, snapshot.snapshot_id)
            self.assertFalse((runtime_root / "runs" / "run-1" / "workers").exists())


class PlatformIdentityTests(unittest.TestCase):
    def test_linux_process_start_identity_uses_boot_and_start_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = Path(tmp)
            process_dir = proc_root / "123"
            process_dir.mkdir(parents=True)
            fields = ["S", *(["0"] * 18), "4242"]
            (process_dir / "stat").write_text(
                f"123 (worker with spaces) {' '.join(fields)}\n",
                encoding="utf-8",
            )
            boot = proc_root / "sys" / "kernel" / "random"
            boot.mkdir(parents=True)
            (boot / "boot_id").write_text("boot-abc\n", encoding="utf-8")

            identity = process_liveness._linux_process_start_identity(123, proc_root=proc_root)

            self.assertEqual(identity, "linux:boot-abc:4242")

    def test_windows_identity_dispatch_is_simulated_without_windows_host(self):
        with mock.patch.object(
            process_liveness,
            "_windows_process_start_identity",
            return_value="windows-filetime:99",
        ) as windows_identity:
            identity = process_liveness.process_start_identity(77, platform_name="nt")

        self.assertEqual(identity, "windows-filetime:99")
        windows_identity.assert_called_once_with(77)


class LoginShutdownTests(unittest.TestCase):
    def test_login_browser_waits_for_process_then_profile_release(self):
        manager = mock.Mock(spec=ProfileManager)
        events: list[str] = []
        process = mock.Mock()
        process.wait.side_effect = lambda: events.append("process-exit")
        manager.wait_for_profile_release.side_effect = lambda *args, **kwargs: (
            events.append("profile-release")
            or ProfileActivity(ownership_state=OwnershipState.INACTIVE)
        )
        bootstrapper = LoginBootstrapper(profile_manager=manager)

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch(
                "browser_runtime.login_bootstrap.find_chromium_binary",
                return_value=Path("/fake/chromium"),
            ),
            mock.patch("browser_runtime.login_bootstrap.subprocess.Popen", return_value=process),
        ):
            returned = bootstrapper.open_login_browser(Path(tmp) / "login", wait=True)

        self.assertIs(returned, process)
        self.assertEqual(events, ["process-exit", "profile-release"])
        manager.wait_for_profile_release.assert_called_once()


class CoordinatedCleanupTests(unittest.TestCase):
    def test_workers_only_cleanup_their_own_runtime(self):
        manager = mock.Mock()
        manager.cleanup_worker.return_value = CleanupOutcome(
            CleanupStatus.DELETED,
            "worker",
            Path("/tmp/worker"),
            "deleted",
        )
        manager.cleanup_run = mock.Mock()
        executors = []
        for index in (1, 2):
            context = SimpleNamespace(run_id="run", worker_id=f"worker-{index:03d}")
            driver = SimpleNamespace(profile_manager=manager, profile_context=context)
            executor = _BrowserExecutorBase(
                config={},
                run_id="run",
                worker_id=context.worker_id,
                emit=lambda *args, **kwargs: None,
            )
            executor.driver = driver
            executors.append(executor)

        with (
            mock.patch.object(batch_common, "quit_driver"),
            mock.patch.object(batch_common, "batch_log") as log,
        ):
            for executor in executors:
                executor.close()

        self.assertEqual(manager.cleanup_worker.call_count, 2)
        manager.cleanup_run.assert_not_called()
        self.assertEqual(log.call_count, 2)

    def test_coordinator_runs_whole_run_cleanup_after_all_workers_stop(self):
        coordinator = ParallelCoordinator.__new__(ParallelCoordinator)
        coordinator.config = SimpleNamespace(run_id="run", shutdown_grace=0.0)
        coordinator.manifest = mock.Mock()
        coordinator.claims = mock.Mock()
        coordinator.event_queue = mock.Mock()
        coordinator.result = CoordinatorResult()
        coordinator._shutting_down = False

        slots = {}
        for worker_id in ("worker-001", "worker-002"):
            process = mock.Mock()
            process.is_alive.return_value = False
            slots[worker_id] = SimpleNamespace(
                worker_id=worker_id,
                process=process,
                command_queue=mock.Mock(),
                current_job=None,
                claim=None,
            )
        coordinator.slots = slots

        order: list[str] = []
        coordinator._stop_process = mock.Mock(
            side_effect=lambda slot, **kwargs: order.append(f"stop:{slot.worker_id}")
        )
        coordinator._cleanup_runtime_profiles = mock.Mock(
            side_effect=lambda **kwargs: order.append("cleanup:run")
        )
        coordinator._close_queue = mock.Mock()

        coordinator._shutdown(interrupted=False)

        self.assertEqual(order, ["stop:worker-001", "stop:worker-002", "cleanup:run"])
        coordinator._cleanup_runtime_profiles.assert_called_once_with(success=True)
        coordinator.claims.release_run.assert_called_once_with("run")


if __name__ == "__main__":
    unittest.main()
