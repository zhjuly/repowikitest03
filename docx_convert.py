"""批量将 DOCX 转换为 Markdown（基于 pypandoc）。

默认行为：
1. 从 `规范文档源文件` 目录递归读取 docx 文件；
2. 转换为 Markdown 并输出到 `pandoc` 目录；
3. 通过 pandoc 参数尽量保留标题层级，并优先输出 fenced code block。
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

import pypandoc


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = BASE_DIR / "规范文档源文件"
DEFAULT_OUTPUT_DIR = BASE_DIR / "pandoc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量将 docx 文档转换为 markdown 文档。"
    )
    parser.add_argument(
        "-s",
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"源目录（默认：{DEFAULT_SOURCE_DIR}）",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认：{DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--pattern",
        default="*.docx",
        help="文件匹配模式（默认：*.docx）",
    )
    parser.add_argument(
        "--download-pandoc",
        action="store_true",
        help="本机未安装 pandoc 时，尝试自动下载。",
    )
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="保留文档中的图片（默认忽略图片）。",
    )
    parser.add_argument(
        "--keep-html-comments",
        action="store_true",
        help="保留 HTML 注释（默认移除 <!-- -->）。",
    )
    return parser.parse_args()


def ensure_pandoc(download_if_missing: bool) -> None:
    try:
        version = pypandoc.get_pandoc_version()
        print(f"[INFO] pandoc 版本: {version}")
        return
    except OSError as exc:
        if not download_if_missing:
            raise RuntimeError(
                "未找到 pandoc。请先安装 pandoc，或使用 --download-pandoc 自动下载。"
            ) from exc

    try:
        from pypandoc.pandoc_download import download_pandoc
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("无法加载 pandoc 下载器，请检查 pypandoc 安装。") from exc

    print("[INFO] 未检测到 pandoc，开始自动下载...")
    download_pandoc()
    version = pypandoc.get_pandoc_version()
    print(f"[INFO] pandoc 下载完成，版本: {version}")


def iter_docx_files(source_dir: Path, pattern: str) -> list[Path]:
    files = sorted(
        p
        for p in source_dir.rglob(pattern)
        if p.is_file() and not p.name.startswith("~$")
    )
    return files


def output_md_path(source_file: Path, source_dir: Path, output_dir: Path) -> Path:
    rel = source_file.relative_to(source_dir)
    return (output_dir / rel).with_suffix(".md")


def create_drop_images_filter() -> Path:
    """生成临时 pandoc lua filter：移除 Image/Figure 元素。"""
    lua_content = """function Image(_)
  return {}
end

function Figure(_)
  return {}
end
"""
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".lua",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(lua_content)
        return Path(tmp.name)


def strip_html_comments(md_path: Path) -> int:
    """移除 Markdown 中的 HTML 注释 <!-- ... -->。"""
    content = md_path.read_text(encoding="utf-8")
    cleaned, removed = re.subn(r"<!--[\s\S]*?-->", "", content)
    if removed > 0:
        md_path.write_text(cleaned, encoding="utf-8")
    return removed


def convert_one_docx(
    source_file: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    keep_images: bool,
    keep_html_comments: bool,
) -> Path:
    output_md = output_md_path(source_file, source_dir, output_dir)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    # 参数说明：
    # - markdown-headings=atx: 标题输出为 # 形式，尽量保留层级；
    # - wrap=none: 避免自动折行，减少内容错位；
    # - to=gfm: 倾向输出 fenced code block，更利于代码块阅读。
    extra_args = [
        "--markdown-headings=atx",
        "--wrap=none",
        "--standalone",
    ]
    drop_images_filter: Path | None = None
    if not keep_images:
        drop_images_filter = create_drop_images_filter()
        extra_args.extend(["--lua-filter", str(drop_images_filter)])
    try:
        pypandoc.convert_file(
            source_file,
            to="gfm",
            outputfile=output_md,
            extra_args=extra_args,
        )
    finally:
        if drop_images_filter is not None:
            drop_images_filter.unlink(missing_ok=True)

    if not keep_html_comments:
        strip_html_comments(output_md)
    return output_md


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        print(f"[ERROR] 源目录不存在或不是目录: {source_dir}", file=sys.stderr)
        return 1

    try:
        ensure_pandoc(download_if_missing=args.download_pandoc)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    docx_files = iter_docx_files(source_dir, args.pattern)
    if not docx_files:
        print(f"[WARN] 未找到匹配文件: {source_dir} / {args.pattern}")
        return 0

    print(f"[INFO] 图片处理: {'保留' if args.keep_images else '忽略'}")
    print(f"[INFO] 注释处理: {'保留' if args.keep_html_comments else '移除'}")
    print(f"[INFO] 待转换文件数: {len(docx_files)}")
    converted = 0
    failed = 0

    for source_file in docx_files:
        try:
            md_path = convert_one_docx(
                source_file,
                source_dir,
                output_dir,
                keep_images=args.keep_images,
                keep_html_comments=args.keep_html_comments,
            )
            print(f"[OK] {source_file.name} -> {md_path}")
            converted += 1
        except RuntimeError as exc:
            print(f"[FAIL] {source_file} -> {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:  # pragma: no cover
            print(f"[FAIL] {source_file} -> {exc}", file=sys.stderr)
            failed += 1

    print(
        f"[DONE] 总数={len(docx_files)} 成功={converted} 失败={failed} 输出目录={output_dir}"
    )
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
