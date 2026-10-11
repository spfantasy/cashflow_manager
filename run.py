#!/usr/bin/env python3
"""现金流管理系统启动入口。

开发环境：
    python run.py --debug

打包后（Windows exe）：双击运行即可，会自动打开浏览器。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
import webbrowser


def configure_output() -> None:
    """让中文输出永远不会把程序打挂。

    Windows 控制台默认不是 UTF-8（英文系统是 cp1252），此时直接 print 中文会抛
    UnicodeEncodeError 并让进程以非 0 退出——打包成 exe 后就是「双击没反应」。
    这里保留控制台自身的编码（中文 Windows 控制台显示中文仍然正常），
    只把编码错误降级为替换字符；配合 PYTHONIOENCODING=utf-8 也可输出完整日志。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # 某些环境下没有 reconfigure（如被重定向为其它对象）
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="订单-现金流管理系统")
    parser.add_argument("--host", default=os.environ.get("CASHFLOW_HOST", "127.0.0.1"),
                        help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CASHFLOW_PORT", "5000")),
                        help="监听端口，默认 5000")
    parser.add_argument("--debug", action="store_true", help="开启调试模式（自动重载）")
    parser.add_argument("--init-db", action="store_true", help="只初始化数据库后退出")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    return parser


def run(args) -> int:
    from cashflow import create_app
    from cashflow.config import Config

    app = create_app()

    if args.init_db:
        print(f"数据库已初始化：{Config.DB_PATH}")
        return 0

    url = f"http://{args.host}:{args.port}/"
    print(f"现金流管理系统已启动：{url}")
    print(f"数据库文件：{Config.DB_PATH}")
    print("按 Ctrl+C 退出")

    if not args.debug and not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)
    return 0


def main(argv=None) -> int:
    configure_output()
    try:
        return run(build_parser().parse_args(argv))
    except KeyboardInterrupt:
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
