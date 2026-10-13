"""Do not silently count missing case dependencies or unexpected skips as coverage."""
import pytest


class SkipAudit:
    def __init__(self):
        self.unexpected = []

    def pytest_runtest_logreport(self, report):
        if not report.skipped:
            return
        reason = str(report.longrepr[2]).removeprefix('Skipped: ')
        if (report.nodeid.endswith('test_harness_artifacts.py::test_inventory_rejects_link_and_does_not_follow_outside')
                and reason == 'ordinary symlink creation is unavailable; junction coverage is separate'):
            return
        self.unexpected.append(report.nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        if self.unexpected and exitstatus in (0, 1, 5):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        if self.unexpected:
            terminalreporter.write_sep('=', 'Unverified unexpected harness skips')
            for node in self.unexpected:
                terminalreporter.write_line(node)


def pytest_configure(config):
    config.pluginmanager.register(SkipAudit(), 'harness-skip-audit')
