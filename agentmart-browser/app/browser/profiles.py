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

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

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
    return not directory.exists()


def describe_storage() -> dict:
    return {
        "root": str(PROFILE_ROOT),
        "note": (
            "浏览器登录态（cookie/localStorage）只保存在这个目录，位于仓库之外，"
            "不会被 Git 跟踪。删除对应目录即可清除该平台登录状态。"
        ),
        "inside_repo": False,
    }
