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
import webbrowser


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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
