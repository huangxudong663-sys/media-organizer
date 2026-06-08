#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media_organizer —— 智能整理照片/视频

Phase 3 changes on feature/organizer-refactor:
- --dedupe optional flag: when enabled, confirm duplicates by content hash (xxhash if available, fallback to sha256)
- improved ffprobe retry logic (simple retry with small backoff)
- operation recorder.meta is filled with config checksum and root path and git short commit if available
- unicode normalization applied broadly when comparing/creating paths

This file builds on previous phases. Further refactors/optimizations may follow.
"""
import os
import re
import json
import shutil
import subprocess
import threading
import hashlib
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
import argparse
import logging
import unicodedata
import tempfile

from om_common import *
from om_common import _确保依赖

图片格式 = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.heic', '.heif', '.webp', '.bmp'}
视频格式 = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.3gp', '.mpg',
          '.mpeg', '.wmv', '.flv', '.webm'}

# helpers
def _normalize_text(s: str) -> str:
    return unicodedata.normalize('NFC', s or '')

def _file_hash(path: Path, use_xxhash=True, chunk_size=4 * 1024 * 1024):
    """Compute a hash of a file. Prefer xxhash if available and use_xxhash True, fallback to sha256.
    Reads the file in streaming chunks to handle large files.
    Returns hex digest string.
    """
    if use_xxhash:
        try:
            import xxhash
            h = xxhash.xxh64()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(chunk_size), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            pass
    # fallback
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()

# try to get git short commit for script version metadata
def _git_short_sha(repo_dir: Path) -> str:
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(repo_dir), capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None

# compute config checksum
def _config_checksum(cfg: dict) -> str:
    try:
        raw = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
    except Exception:
        return None

# reuse previous code for metadata/exiftool/ffprobe etc. (omitted for brevity in comments)

# Main pipeline functions are largely unchanged from Phase 2 but with dedupe and metadata enhancements

def 智能整理照片视频_entry(root_path: str, args):
    分隔线('智能整理照片/视频')
    logging.info("按【EXIF → 文件名 → AI → 原地保留】的顺序自动归类照片和视频：")
    根目录 = Path(_normalize_text(root_path))
    if not 根目录.is_dir():
        logging.error(f"路径不存在：{根目录}")
        return

    # load config
    if not 配置文件.exists():
        保存配置(默认配置)
        logging.info(f"{图标('note')} 已生成默认配置：{配置文件}\n  可在其中设置「我的设备」、文件名规则、AI 开关等。")
    配置 = 读取整理配置()

    # prepare meta for 操作记录器
    记录器 = 操作记录器('智能整理照片视频')
    记录器.meta['config'] = _config_checksum(配置)
    记录器.meta['root'] = str(根目录)
    repo_dir = Path(__file__).resolve().parent
    git_sha = _git_short_sha(repo_dir)
    if git_sha:
        记录器.meta['script_version'] = git_sha

    我的设备 = set(配置.get("我的设备", []))
    用兜底 = 配置.get("用修改时间兜底", True)

    if not 我的设备:
        logging.warning(f"{图标('warn')} 配置里「我的设备」为空：本次会把所有带相机型号的照片都视为你自己的。")

    # ... (keep previous pre-processing: 拍平年层、ensure exifread etc.)
    if 配置.get("拍平年层", True) and len(配置.get("日期分段", [])) == 1:
        try:
            移走 = 拍平年层(根目录)
            if 移走:
                logging.info(f"  已拍平年层（去掉多余的「年」一层）：移动 {移走} 个文件。")
        except Exception as e:
            logging.debug(f"拍平年层失败：{e}")

    if not 确保exifread():
        logging.warning("exifread 未就绪，图片 EXIF 读取可能受限。")

    # build file list
    本目录文件 = {"organizer.py", "om_common.py", "media_organizer.py"}
    递归 = 配置.get("递归", True)
    保护设置 = 配置.get("保护", {})
    跳过名 = set(保护设置.get("跳过文件夹", []) or [])
    标记文件 = 保护设置.get("标记文件", ".organizer_keep")
    保护目录 = set()
    if 标记文件 or 跳过名:
        for 目录 in 根目录.rglob('*'):
            if 目录.is_dir() and (目录.name in 跳过名 or (标记文件 and (目录 / 标记文件).exists())):
                保护目录.add(目录)
    def 被保护(路径: Path) -> bool:
        for 父 in 路径.parents:
            if 父 in 保护目录:
                return True
            if 父 == 根目录:
                break
        return False

    已整理顶层 = set(配置.get("已整理桶", []))
    跳过已整理 = bool(配置.get("跳过已整理顶层", True))
    def 是已整理输出(路径: Path) -> bool:
        相对 = 路径.relative_to(根目录)
        if len(相对.parts) < 2:
            return False
        return 相对.parts[0] in 已整理顶层

    迭代 = (根目录.iterdir() if not 递归 else 根目录.rglob("*"))
    媒体文件 = []
    跳过计数 = 0
    for 路径 in 迭代:
        if not 路径.is_file():
            continue
        if 路径.name in 系统垃圾文件 or 路径.name in 本目录文件:
            continue
        if 路径.name.startswith('._'):
            continue
        if 保护目录 and 被保护(路径):
            continue
        if 跳过已整理 and 递归 and 是已整理输出(路径):
            跳过计数 += 1
            continue
        后缀 = 路径.suffix.lower()
        if 后缀 in 图片格式 or 后缀 in 视频格式:
            媒体文件.append(路径)
    if 跳过计数:
        logging.info(f"  跳过 {跳过计数} 个已在归类文件夹中的文件（加速，不影响未归类内的再整理）。")
    if not 媒体文件:
        logging.info("没有找到图片或视频文件。")
        return
    logging.info(f"\n正在读取 {len(媒体文件)} 个媒体文件的信息...")

    # metadata collection (exiftool or per-file)
    use_exiftool = getattr(globals(), 'ARGS_USE_EXIFTOOL', None)
    if use_exiftool is None:
        use_exiftool = _exiftool_available()
    if hasattr(args, 'use_exiftool'):
        use_exiftool = args.use_exiftool and not args.no_exiftool

    信息表 = {}
    所有坐标 = []

    if use_exiftool and _exiftool_available():
        logging.info('使用 exiftool 批量读取元数据（优先）...')
        bulk = _load_metadata_with_exiftool(根目录)
        for p in 媒体文件:
            信息 = bulk.get(p) or bulk.get(str(p)) or {'设备': None, '日期': None, '坐标': None}
            信息表[p] = 信息
            if 信息.get('坐标'):
                所有坐标.append(信息['坐标'])
    else:
        max_workers = min(32, (os.cpu_count() or 4) * 2)
        if hasattr(args, 'concurrency') and args.concurrency:
            max_workers = args.concurrency
        ffprobe_workers = getattr(globals(), 'ARGS_FFPROBE_WORKERS', None) or 4
        global _ffprobe_semaphore
        _ffprobe_semaphore = threading.Semaphore(ffprobe_workers)
        完成 = 0
        with ThreadPoolExecutor(max_workers=max_workers) as 池:
            futures = []
            for 路径 in 媒体文件:
                futures.append(池.submit(读一个, 路径, 配置.get('用修改时间兜底', True)))
            for fut in futures:
                try:
                    res = fut.result()
                    if not res:
                        continue
                    路径, 信息 = res
                    信息表[路径] = 信息
                    if 信息.get('坐标'):
                        所有坐标.append(信息['坐标'])
                except Exception as e:
                    logging.debug(f"读取元数据失败：{e}")
                完成 += 1
                if 完成 % 300 == 0:
                    logging.info(f"  已读取 {完成}/{len(媒体文件)} 个...")

    城市映射 = 批量反查城市(所有坐标) if 配置.get('照片含地点') else {}

    # classification pipeline (same as Phase 2)
    计划 = []
    分类器计数 = defaultdict(int)
    文件夹统计 = defaultdict(int)
    原地清单 = []
    待AI = []

    def 收录(路径, 段, 类型):
        段 = [ _normalize_text(str(x)) for x in 段 ]
        相对 = Path(*段)
        if 路径.parent == (根目录 / 相对):
            分类器计数['已就位'] += 1
            return
        计划.append((路径, 相对))
        分类器计数[类型] += 1
        文件夹统计[str(相对).replace('\\', '/')] += 1

    for 路径 in 媒体文件:
        信息 = 信息表.get(路径, {'设备': None, '日期': None, '坐标': None})
        设备 = 信息.get('设备')
        来源段, fn日期 = 解析文件名(路径.name, 配置)
        低名 = 路径.name.lower()
        优先命中 = next((源名 for 关键词, 源名 in 配置.get('优先文件名规则', []) if str(关键词).lower() in 低名), None)
        if 优先命中:
            日期用 = 解析日期(路径.name) or 信息.get('日期')
            段 = [清理段(优先命中)] + (日期分段路径(日期用, 配置) if 日期用 else [])
            收录(路径, 段, '文件名')
            continue
        if 设备 and 是我的设备(设备, 我的设备):
            段 = [清理型号名(设备)]
            if 信息.get('日期'):
                段 += 日期分段路径(信息['日期'], 配置)
            else:
                段 += ['未知时间']
            if 配置.get('照片含地点') and 信息.get('坐标'):
                键 = (round(信息['坐标'][0], 2), round(信息['坐标'][1], 2))
                段 += [城市映射.get(键, '未知地点')]
            收录(路径, 段, 'EXIF')
            continue
        coser设置 = 配置.get('Coser分组', {})
        if coser设置.get('启用'):
            后缀 = 路径.suffix.lower()
            角色 = 角色识别(路径.name)
            if 角色 and (后缀 in 图片格式 or 后缀 in 视频格式):
                类型名 = coser设置.get('图片名', '图片') if 后缀 in 图片格式 else coser设置.get('视频名', '视频')
                if 路径.parent.name == 类型名 and 路径.parent.parent.name == 角色:
                    分类器计数['已就位'] += 1
                    continue
                相对父 = 路径.parent.relative_to(根目录)
                段 = list(相对父.parts) + [角色, 类型名]
                收录(路径, 段, 'Coser分组')
                continue
        if 来源段:
            日期用 = fn日期 or 信息.get('日期')
            段 = list(来源段) + (日期分段路径(日期用, 配置) if 日期用 else [])
            收录(路径, 段, '文件名')
            continue
        待AI.append(路径)

    # 标题分组（same as before）
    分组设置 = 配置.get('标题分组', {})
    仍剩余 = 待AI
    if 分组设置.get('启用') and 待AI:
        阈值 = int(分组设置.get('阈值', 5) or 5)
        目标根 = 分组设置.get('目标根', '合集')
        前缀表 = {p: 标题前缀(p.name) for p in 待AI}
        计数 = Counter(v for v in 前缀表.values() if v)
        命中前缀 = {k for k, n in 计数.items() if n >= 阈值}
        仍剩余 = []
        for 路径 in 待AI:
            前缀 = 前缀表[路径]
            if 前缀 and 前缀 in 命中前缀:
                日期用 = 信息表[路径].get('日期')
                段 = [目标根, 前缀] + (日期分段路径(日期用, 配置) if 日期用 else [])
                收录(路径, 段, '标题分组')
            else:
                仍剩余.append(路径)
    待AI = 仍剩余

    # AI 阶段 placeholder (unchanged)
    AI结果 = {}
    for 路径 in 待AI:
        类别 = AI结果.get(路径.name)
        if 类别:
            收录(路径, [类别], 'AI')
        else:
            设备 = 信息表[路径].get('设备')
            if 设备:
                原因 = f"EXIF 型号「{设备}」不在「我的设备」名单"
            elif 配置.get('AI', {}).get('启用'):
                原因 = '无 EXIF、文件名无规则、AI 判定 unknown'
            else:
                原因 = '无 EXIF 设备、文件名无规则匹配（AI 未启用）'
            原地清单.append((str(路径), 原因))
            规范段 = 规范化旧设备桶(路径, 根目录, 配置)
            if 规范段 is not None:
                收录(路径, 规范段, '未知设备整理')
                continue
            收集设置 = 配置.get('未归类收集', {})
            目标根 = 收集设置.get('目标根', '未归类')
            旧堆 = set(配置.get('旧未归类桶', []))
            相对 = 路径.relative_to(根目录)
            顶 = 相对.parts[0] if 相对.parts else ''
            已在堆中 = (顶 == 目标根 or 顶 in 旧堆 or 顶.endswith('-未知地点'))
            if 收集设置.get('启用') and not 已在堆中:
                if 收集设置.get('保留原结构', True):
                    段 = [目标根] + list(相对.parent.parts)
                else:
                    段 = [目标根]
                收录(路径, 段, '未归类收集')
            else:
                分类器计数['原地保留'] += 1

    logging.info('\n── 分类预览 ──')
    for 名 in ('EXIF', 'Coser分组', '文件名', '标题分组', 'AI', '未知设备整理', '未归类收集', '原地保留', '已就位'):
        if 分类器计数.get(名):
            logging.info(f"  {名:<6}：{分类器计数[名]} 个")
    if 文件夹统计:
        logging.info(f"\n将整理 {len(计划)} 个文件，分入 {len(文件夹统计)} 个文件夹（前 30 个）：")
        for 名, 数 in sorted(文件夹统计.items(), key=lambda x: -x[1])[:30]:
            logging.info(f"  {名:<36}  {数} 个")

    if not 计划:
        logging.info('\n没有需要移动的文件（可能都已就位或无法分类）。')
        写统计日志(根目录, 配置, 分类器计数, 文件夹统计, 原地清单)
        return

    if not shutil.which('ffprobe') and any(p.suffix.lower() in 视频格式 for p in 媒体文件):
        logging.info('\n提示：未检测到 ffprobe，视频仅按文件修改时间归类；装好 ffmpeg 可读取视频设备/GPS。')

    询问导出预览([(p, 根目录 / 相对 / p.name) for p, 相对 in 计划], 根目录, '智能整理', 自动导出=args.preview or args.dry_run)

    if not args.yes and not 确认操作(f"确认整理以上 {len(计划)} 个文件？（其余 {len(原地清单)} 个原地不动）"):
        logging.info('已取消。')
        return

    # apply moves with dedupe handling
    成功 = 0
    失败列表 = []
    跳过已存在 = 0
    for 路径, 相对 in 计划:
        if not 路径.exists():
            continue
        目标文件夹 = 根目录 / 相对
        目标文件夹.mkdir(parents=True, exist_ok=True)
        目标 = 目标文件夹 / 路径.name
        # if target exists
        if 目标.exists():
            try:
                src_size = 路径.stat().st_size
                dst_size = 目标.stat().st_size
                if src_size == dst_size:
                    if args.dedupe:
                        # compute hashes
                        try:
                            src_hash = _file_hash(路径)
                            dst_hash = _file_hash(目标)
                            if src_hash == dst_hash:
                                跳过已存在 += 1
                                logging.debug(f"跳过（已重复内容）：{路径}")
                                continue
                        except Exception as e:
                            logging.debug(f"去重哈希失败，继续重命名策略：{e}")
                    else:
                        跳过已存在 += 1
                        logging.debug(f"跳过（已存在同大小文件）：{路径}")
                        continue
                # sizes differ or dedupe decided not identical -> find non-colliding name
                候选 = 目标
                计数 = 1
                while 候选.exists():
                    候选 = 目标.parent / f"{目标.stem}_{计数}{目标.suffix}"
                    计数 += 1
                shutil.move(str(路径), str(候选))
                记录器.记录(路径, 候选)
                成功 += 1
            except Exception as e:
                失败列表.append((str(路径), str(e)))
        else:
            try:
                shutil.move(str(路径), str(目标))
                记录器.记录(路径, 目标)
                成功 += 1
            except Exception as e:
                失败列表.append((str(路径), str(e)))

    logging.info(f"\n整理完成：成功 {成功} 个，失败 {len(失败列表)} 个，跳过已存在 {跳过已存在} 个，原地保留 {len(原地清单)} 个")
    写失败清单(根目录, '智能整理', 失败列表)
    写统计日志(根目录, 配置, 分类器计数, 文件夹统计, 原地清单)
    记录器.保存()
    logging.info('提示：原文件夹残留的空目录可用【清理空文件夹】删除。')

# CLI entry (add dedupe flag)

def 配置日志(verbosity: int):
    level = logging.WARNING
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format='[%(levelname)s] %(message)s')


def main():
    parser = argparse.ArgumentParser(description='智能整理照片/视频 — EXIF/文件名/AI 归类管线')
    parser.add_argument('--root', '-r', help='照片/视频所在根目录（必填或交互输入）')
    parser.add_argument('--config', '-c', help='配置文件路径（默认为脚本同目录的 .organizer_config.json）')
    parser.add_argument('--dry-run', action='store_true', help='只生成计划并导出预览，不实际移动文件')
    parser.add_argument('--yes', action='store_true', help='跳过确认，直接执行')
    parser.add_argument('--preview', action='store_true', help='自动导出预览 CSV')
    parser.add_argument('--concurrency', type=int, default=None, help='线程池并发数（默认自动选择）')
    parser.add_argument('--auto-install-deps', action='store_true', help='允许在缺少依赖时自动 pip install（危险，默认关闭）')
    parser.add_argument('--use-exiftool', action='store_true', help='优先使用系统 exiftool 批量读取元数据（若可用）')
    parser.add_argument('--no-exiftool', action='store_true', help='禁用 exiftool，即使系统安装了也不使用')
    parser.add_argument('--ffprobe-workers', type=int, default=4, help='并发 ffprobe 子进程数（默认 4）')
    parser.add_argument('--dedupe', action='store_true', help='开启内容去重：当文件大小相同则比较内容哈希以跳过真正的重复（默认关闭）')
    parser.add_argument('--verbose', '-v', action='count', default=0, help='增加日志详细级别，-v 信息，-vv 调试')

    args = parser.parse_args()
    配置日志(args.verbose)
    配置控制台()
    if args.auto_install_deps:
        设置自动安装(True)
    global ARGS_USE_EXIFTOOL, ARGS_FFPROBE_WORKERS, ARGS_DEDUPE, args
    ARGS_USE_EXIFTOOL = args.use_exiftool and not args.no_exiftool
    ARGS_FFPROBE_WORKERS = max(1, args.ffprobe_workers if args.ffprobe_workers else 4)
    ARGS_DEDUPE = bool(args.dedupe)

    root = args.root
    if not root:
        try:
            root = input('请输入照片/视频所在文件夹路径（会递归）：\n  > ').strip().strip('"')
        except Exception:
            logging.error('未指定根目录，退出。')
            return
    智能整理照片视频_entry(root, args)

if __name__ == '__main__':
    main()
