"""浏览器配置文件（登录态）管理。

设计约束：
- profile 目录放在**仓库之外**的用户目录（``~/.agentmart/browser-profiles``），
  从结构上保证它不可能被提交进 Git；
- 每个平台一个隔离目录；淘宝与天猫共用同一登录关系，因此共用同一目录，
  但结果仍按平台分别归属（见 recipes.PROFILE_GROUP）；
- 提供 ``delete_profile`` 删除入口，删除即清除该平台登录态；
- 只在本地磁盘保存浏览器自身的 cookie/localStorage，Agent 代码不读取、
  不记录、不上传这些内容；发给模型的内容不含 cookie 与认证状态。
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from ..domain.enums import Platform

AGENTMART_HOME = Path(
    os.environ.get("AGENTMART_HOME") or (Path.home() / ".agentmart")
).expanduser()
PROFILE_ROOT = AGENTMART_HOME / "browser-profiles"


@dataclass(frozen=True)
class ProfileInfo:
    group: str
    directory: Path
    platforms: tuple
    exists: bool

    def to_dict(self) -> dict:
        return {
            "group": self.group,
            "directory": str(self.directory),
            "platforms": [p.value for p in self.platforms],
            "exists": self.exists,
        }


# 平台 → profile 组。同组共用同一浏览器目录（即同一登录关系）。
_PROFILE_GROUP: Dict[Platform, str] = {
    Platform.JD: "jd",
    Platform.TAOBAO: "taobao",   # 淘宝与天猫共用登录关系
    Platform.TMALL: "taobao",
    Platform.PDD: "pdd",
    Platform.DOUYIN: "douyin",
}


def profile_group(platform: Platform) -> str:
    return _PROFILE_GROUP[platform]


def platforms_for_group(group: str) -> List[Platform]:
    """组内平台（淘宝/天猫同组）。组名不认识时抛 KeyError。"""
    members = [p for p, g in _PROFILE_GROUP.items() if g == group]
    if not members:
        raise KeyError(group)
    return members


def profile_dir(group: str) -> Path:
    return PROFILE_ROOT / group


def profile_info(platform: Platform) -> ProfileInfo:
    group = profile_group(platform)
    directory = profile_dir(group)
    members = tuple(p for p, g in _PROFILE_GROUP.items() if g == group)
    return ProfileInfo(
        group=group,
        directory=directory,
        platforms=members,
        exists=directory.is_dir(),
    )


def all_profiles() -> list[ProfileInfo]:
    seen: Dict[str, ProfileInfo] = {}
    for platform in Platform:
        info = profile_info(platform)
        seen.setdefault(info.group, info)
    return [seen[g] for g in sorted(seen)]


def ensure_profile_dir(platform: Platform) -> Path:
    directory = profile_dir(profile_group(platform))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def delete_profile(group: str) -> bool:
    """删除某个登录态目录。返回是否真的删除了内容。"""
    directory = profile_dir(group)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    clear_verified(group)
    return not directory.exists()


# ---- 「本机验证过已登录」的标记 ----
# 只记一个时间戳，不记任何账号信息。用来把「目录存在」和「真的登进去过」
# 区分开：目录存在只说明开过浏览器，之前界面据此显示"已登录"会误导人；
# 但这个标记也说明不了 cookie 现在还有效，所以文案必须带时间，
# 并且任务真跑起来时仍会重新探测。
_VERIFIED_FILE = "verified-login.json"


def _verified_path() -> Path:
    return PROFILE_ROOT / _VERIFIED_FILE


def _read_verified() -> Dict[str, str]:
    path = _verified_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        # 文件损坏就当没有标记，不影响使用
        return {}


def mark_verified(group: str) -> None:
    """记录某登录组在本机被探测到已登录的时间。"""
    data = _read_verified()
    data[group] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = _verified_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # 写不出去也不该影响登录本身
        logger.warning(f"写入登录验证标记失败[{group}]: {exc}")


def verified_at(group: str) -> Optional[str]:
    return _read_verified().get(group)


def clear_verified(group: str) -> None:
    data = _read_verified()
    if group not in data:
        return
    del data[group]
    path = _verified_path()
    try:
        if data:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif path.is_file():
            path.unlink()
    except Exception as exc:
        logger.warning(f"清除登录验证标记失败[{group}]: {exc}")


def describe_storage() -> dict:
    return {
        "root": str(PROFILE_ROOT),
        "note": (
            "浏览器登录态（cookie/localStorage）只保存在这个目录，位于仓库之外，"
            "不会被 Git 跟踪。删除对应目录即可清除该平台登录状态。"
        ),
        "inside_repo": False,
    }
