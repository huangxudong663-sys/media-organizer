#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""om_common —— 文件夹整理工具的公共基础模块
包含：常量、配置读写、控制台适配、撤销日志/记录器、日志清理、失败清单、
     预览导出、确认/分隔线/安全改名、依赖自动安装。

已改进（feature/organizer-refactor）：
- 增加 logging 支持（替代部分 print），保留图标函数
- 增加自动安装依赖开关（默认关闭）。使用 设置自动安装(True) 开启
- 写文件（失败清单、记录器）使用原子写入（临时文件 + os.replace）以降低中断风险
"""
import os
import re
import csv
import sys
import json
import shutil
import platform
import tempfile
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import logging

系统垃圾文件 = {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.localized'}

_脚本目录 = Path(__file__).resolve().parent
# 操作日志目录（放在脚本同级，便于撤销）
日志目录 = _脚本目录 / ".organizer_logs"
# 配置文件（记住"我的设备"、自定义城市名等）
配置文件 = _脚本目录 / ".organizer_config.json"

# 撤销日志保留策略
日志保留条数 = 30
日志保留天数 = 60

# 是否允许脚本在运行时自动 pip install（默认 False，需由外部显式开启）
_AUTO_INSTALL_DEPS = False

# 控制台花哨输出（emoji）
_花哨 = True

# logging 配置（外部可在入口设置基本配置）
logger = logging.getLogger("organizer")


def 设置自动安装(值: bool):
    """设置是否允许在运行时自动安装缺失的 Python 包。默认 False。"""
    global _AUTO_INSTALL_DEPS
    _AUTO_INSTALL_DEPS = bool(值)


def 配置控制台():
    """在 Windows 上尽量把控制台切到 UTF-8，避免中文/emoji 报错。"""
    global _花哨
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
        try:
            os.system("chcp 65001 >nul 2>&1")
        except Exception:
            pass
        # 老版 Windows 终端对 emoji 支持差，统一降级
        try:
            版本 = int(platform.release())
        except Exception:
            版本 = 0
        if 版本 < 10:
            _花哨 = False


def 图标(名称: str) -> str:
    """返回带降级的状态符号。"""
    表 = {"ok": ("✅", "[OK]"), "err": ("❌", "[X]"),
          "note": ("📝", "[记录]"), "warn": ("⚠️", "[注意]")}
    花, 朴 = 表.get(名称, ("", ""))
    return 花 if _花哨 else 朴


def 读取配置() -> dict:
    if 配置文件.exists():
        try:
            with open(配置文件, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def 保存配置(配置: dict):
    try:
        with open(配置文件, "w", encoding="utf-8") as f:
            json.dump(配置, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"配置保存失败，不影响本次操作：{e}")


def 清理旧日志():
    """按保留条数 + 保留天数清理 .organizer_logs，避免无限堆积。"""
    if not 日志目录.is_dir():
        return
    日志列表 = sorted(日志目录.glob("*.json"), reverse=True)  # 新→旧
    现在 = datetime.now().timestamp()
    待删 = []
    for i, 日志 in enumerate(日志列表):
        过期 = (现在 - 日志.stat().st_mtime) > 日志保留天数 * 86400
        超量 = i >= 日志保留条数
        if 过期 or 超量:
            待删.append(日志)
    for 日志 in 待删:
        try:
            日志.unlink()
        except Exception:
            pass


def _atomic_write(path: Path, 内容: str, encoding="utf-8") -> bool:
    """把 内容 原子性写入 path（写入临时文件再 os.replace）。返回 True/False。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(内容)
        os.replace(tmp, str(path))
        return True
    except Exception as e:
        logger.exception(f"原子写入失败 {path}: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def 写失败清单(目录: Path, 操作名: str, 失败列表):
    """失败列表为 [(名称, 原因), ...]；非空则写一份 txt 并返回路径。"""
    if not 失败列表:
        return None
    时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
    清单 = 目录 / f"失败清单_{操作名}_{时间戳}.txt"
    内容 = []
    内容.append(f"操作：{操作名}\n时间：{时间戳}\n失败 {len(失败列表)} 项：\n\n")
    for 名称, 原因 in 失败列表:
        内容.append(f"  {名称}\n    原因：{原因}\n")
    文本 = "".join(内容)
    if _atomic_write(清单, 文本):
        logger.warning(f"有 {len(失败列表)} 项失败，明细已写入：{清单}")
        return 清单
    else:
        # 写不出文件就直接打印前 20 项
        logger.warning(f"有 {len(失败列表)} 项失败（无法写入文件）：")
        for 名称, 原因 in 失败列表[:20]:
            logger.warning(f"  {名称} —— {原因}")
    return None


def 询问导出预览(计划行, 目录: Path, 操作名: str, 自动导出=False):
    """计划行为 [(源路径, 目标描述), ...]；询问用户是否先导出 CSV 预览。
    如果 自动导出=True 则直接导出且不再询问。
    返回导出路径或 None
    """
    if not 自动导出:
        try:
            回答 = input("\n执行前是否先导出一份预览表格（CSV）供核对？[y/n]（默认n）：").strip().lower()
        except Exception:
            回答 = "n"
        if 回答 not in ("y", "yes", "是"):
            return None
    时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
    报告 = 目录 / f"整理预览_{操作名}_{时间戳}.csv"
    try:
        with open(报告, "w", encoding="utf-8-sig", newline="") as f:
            写 = csv.writer(f)
            写.writerow(["序号", "源文件", "目标位置"])
            for i, (源, 目标) in enumerate(计划行, 1):
                写.writerow([i, str(源), str(目标)])
        logger.info(f"预览已导出：{报告}")
        logger.info("  用 Excel/表格软件打开核对，确认无误后回来继续。")
        return 报告
    except Exception as e:
        logger.exception(f"预览导出失败：{e}")
        return None


def _确保依赖(模块名: str, 包名: str = None, 友好名: str = None) -> bool:
    """确保某个第三方库可用。默认不自动安装，除非通过 设置自动安装(True) 显式允许。
    返回 True 如果模块可导入或成功安装，False 否则。
    """
    包名 = 包名 or 模块名
    友好名 = 友好名 or 包名
    import importlib, site
    try:
        importlib.import_module(模块名)
        return True
    except ImportError:
        pass
    if not _AUTO_INSTALL_DEPS:
        logger.warning(f"缺少依赖 {友好名}（模块 {模块名}）。若需自动安装, 请使用 --auto-install-deps 或 调用 设置自动安装(True)。")
        return False
    print(f"正在安装必要的库 {友好名}，请稍候...")
    命令 = [sys.executable, "-m", "pip", "install", 包名, "--quiet"]
    result = subprocess.run(命令, capture_output=True, text=True)
    if result.returncode != 0:
        # 某些系统需要 --break-system-packages
        result = subprocess.run(命令 + ["--break-system-packages"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"安装失败，请手动运行：pip install {包名}\n{result.stderr}")
        return False
    # 刷新用户 site-packages 与导入缓存，确保当前进程内能立即导入
    try:
        site.main()
    except Exception:
        pass
    importlib.invalidate_caches()
    try:
        importlib.import_module(模块名)
        logger.info("安装成功！")
        return True
    except ImportError:
        logger.warning(f"已安装 {友好名}，但需要重新运行本程序后才能生效。请重新启动脚本。")
        return False


def 确保exifread():
    return _确保依赖("exifread", 友好名="exifread")


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def 分隔线(标题=""):
    if 标题:
        logger.info(f"\n{'─'*20} {标题} {'─'*20}")
    else:
        logger.info("─" * 46)


def 确认操作(提示="确认执行？"):
    while True:
        try:
            回答 = input(f"\n{提示} (y/n): ").strip().lower()
        except Exception:
            return False
        if 回答 in ("y", "yes", "是", "确认"):
            return True
        if 回答 in ("n", "no", "否", "取消"):
            return False
        print("  请输入 y（确认）或 n（取消)")


def 安全重命名(旧路径: Path, 新路径: Path):
    """重命名文件/文件夹，自动处理重名冲突。返回实际新路径或 None"""
    if 旧路径 == 新路径:
        return None
    候选 = 新路径
    计数 = 1
    while 候选.exists():
        候选 = 新路径.parent / f"{新路径.stem}_{计数}{新路径.suffix}"
        计数 += 1
    旧路径.rename(候选)
    return 候选


# ─────────────────────────────────────────────
# 操作日志 / 撤销系统
# ─────────────────────────────────────────────

class 操作记录器:
    """
    记录一次会话中的所有 移动/改名 操作（源路径 → 目标路径）。
    操作完成后写入 JSON 日志，供【撤销上次操作】回滚。
    仅记录可逆的移动/改名；删除（如清理空文件夹）不可逆，不记录。
    """
    def __init__(self, 操作名称: str):
        self.操作名称 = 操作名称
        self.条目 = []  # [{"from": 目标, "to": 源}]  撤销时把 from 移回 to
        self.meta = {
            "script_time": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "script_version": None,
            "config": None,
            "root": None,
        }

    def 记录(self, 源: Path, 目标: Path):
        self.条目.append({"from": str(目标), "to": str(源)})

    def 保存(self):
        if not self.条目:
            return None
        日志目录.mkdir(exist_ok=True)
        时间戳 = datetime.now().strftime("%Y%m%d_%H%M%S")
        日志文件 = 日志目录 / f"{时间戳}_{self.操作名称}.json"
        内容 = json.dumps({
            "操作": self.操作名称,
            "时间": 时间戳,
            "数量": len(self.条目),
            "条目": self.条目,
            "meta": self.meta,
        }, ensure_ascii=False, indent=2)
        if _atomic_write(日志文件, 内容):
            logger.info(f"已记录操作日志（共 {len(self.条目)} 项），如需回滚请用菜单【6 撤销上次操作】")
            清理旧日志()
            return 日志文件
        else:
            logger.warning("操作日志写入失败")
            return None


def 撤销上次操作():
    分隔线("撤销上次操作")
    if not 日志目录.is_dir():
        logger.info("没有任何可撤销的操作记录。")
        return
    日志列表 = sorted(日志目录.glob("*.json"), reverse=True)
    if not 日志列表:
        logger.info("没有任何可撤销的操作记录。")
        return

    logger.info("最近的操作记录（最新在上）：")
    for i, 日志 in enumerate(日志列表[:10], 1):
        try:
            with open(日志, encoding="utf-8") as f:
                数据 = json.load(f)
            logger.info(f"  {i}. {数据['时间']}  {数据['操作']}  （{数据['数量']} 项）")
        except Exception:
            logger.info(f"  {i}. {日志.name}  （无法读取）")

    选择 = input("\n输入要撤销的编号（默认 1=最近一次，回车取消）：").strip()
    if not 选择:
        logger.info("已取消。")
        return
    try:
        索引 = int(选择) - 1
        目标日志 = 日志列表[索引]
    except (ValueError, IndexError):
        logger.info("编号无效。")
        return

    with open(目标日志, encoding="utf-8") as f:
        数据 = json.load(f)

    logger.info(f"\n将回滚操作【{数据['操作']} @ {数据['时间']}】，共 {数据['数量']} 项。")
    if not 确认操作("确认撤销？（把文件移回原位）"):
        logger.info("已取消。")
        return

    成功 = 失败 = 0
    for 条目 in reversed(数据["条目"]):
        源 = Path(条目["from"])   # 当前位置
        目标 = Path(条目["to"])   # 原始位置
        try:
            if not 源.exists():
                logger.info(f"  跳过（文件已不在）：{源.name}")
                失败 += 1
                continue
            目标.parent.mkdir(parents=True, exist_ok=True)
            候选 = 目标
            计数 = 1
            while 候选.exists():
                候选 = 目标.parent / f"{目标.stem}_还原{计数}{目标.suffix}"
                计数 += 1
            shutil.move(str(源), str(候选))
            成功 += 1
        except Exception as e:
            logger.exception(f"撤销失败：{源.name}  原因：{e}")
            失败 += 1

    logger.info(f"\n撤销完成：成功 {成功} 项，失败 {失败} 项")
    if 失败 == 0:
        目标日志.unlink()
        logger.info("该操作已完全撤销，日志已清除。")
