"""登录态标记：登好了不该被说成"没登录"。

用户真实遇到的困惑：明明在弹出来的窗口里登进去了，界面却一直显示
「有登录态，未验证」，首页还弹"这些平台还没登录"的警告。

原因是登录窗口探到「已登录」之后没有留下任何痕迹——窗口一关、
服务一重启，`_login_state` 只能看到"目录存在"，又退回未验证。

这里覆盖：
- 探到已登录时落一个只含时间戳的本机标记；
- 窗口关闭 / 服务重启后，状态变成"之前验证过已登录"并带上时间；
- 清除登录态会连标记一起删掉；
- 标记文件损坏时按"没有标记"处理，不影响使用。
"""
from __future__ import annotations

import pytest

from app.browser import profiles
from app.browser.login import LoginManager
from app.browser.profiles import (
    clear_verified,
    delete_profile,
    mark_verified,
    verified_at,
)
from app.browser.service import _login_state
from app.domain.enums import Platform


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """把 profile 根目录指到临时目录，避免碰用户真实的登录态。"""
    root = tmp_path / "agentmart-home"
    root.mkdir()
    monkeypatch.setattr(profiles, "PROFILE_ROOT", root)
    return root


def test_marking_and_reading_verified(isolated_home):
    assert verified_at("jd") is None
    mark_verified("jd")
    stamp = verified_at("jd")
    assert stamp
    # 只存时间戳，不存任何账号信息
    assert stamp.count("-") >= 2 and ":" in stamp


def test_clear_verified_removes_only_that_group(isolated_home):
    mark_verified("jd")
    mark_verified("pdd")
    clear_verified("jd")
    assert verified_at("jd") is None
    assert verified_at("pdd")


def test_delete_profile_also_clears_the_marker(isolated_home, monkeypatch):
    directory = isolated_home / "jd"
    directory.mkdir()
    (directory / "Cookies").write_text("x", encoding="utf-8")
    mark_verified("jd")
    assert verified_at("jd")
    assert delete_profile("jd") is True
    assert verified_at("jd") is None


def test_corrupt_marker_file_is_treated_as_absent(isolated_home):
    (isolated_home / "verified-login.json").write_text("{ 不是 json", encoding="utf-8")
    assert verified_at("jd") is None
    # 损坏不该影响后续写入
    mark_verified("jd")
    assert verified_at("jd")


def test_login_state_reports_verified_before_with_timestamp(isolated_home):
    mark_verified("taobao")
    state, label = _login_state(True, {"group": "taobao", "status": "closed"})
    assert state == "verified_before"
    assert verified_at("taobao") in label


def test_login_state_falls_back_to_unverified_without_marker(isolated_home):
    state, label = _login_state(True, {"group": "taobao", "status": "closed"})
    assert state == "saved_unverified"
    assert "未验证" in label


def test_login_state_reports_none_without_directory(isolated_home):
    state, _ = _login_state(False, {"group": "taobao", "status": "closed"})
    assert state == "none"


def test_open_login_window_still_wins(isolated_home):
    state, label = _login_state(True, {"group": "taobao", "status": "waiting_login"})
    assert state == "waiting_login"
    state, label = _login_state(True, {"group": "taobao", "status": "logged_in"})
    assert state == "logged_in"


async def test_login_manager_marks_verified_on_detection(isolated_home):
    """探测到已登录的那一刻，标记必须落盘。"""

    class _Driver:
        async def evaluate(self, script):
            return {"looksLoggedIn": True}

        async def stop(self):
            return None

    manager = LoginManager()

    from app.browser.login import LoginSession

    session = LoginSession(group="jd", platform=Platform.JD, driver=_Driver())
    session.status = "opening"
    manager._sessions["jd"] = session
    # 直接跑一轮探测逻辑（不等轮询间隔）
    await manager._poll(session)
    assert verified_at("jd")
