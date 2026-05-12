# -*- coding: utf-8 -*-
"""
Flask API 入口。
"""
import os, sys

# 项目根目录（小程序/）加入 path，使 "src" 可作为顶级包导入
_SYS_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SYS_PATH not in sys.path:
    sys.path.insert(0, _SYS_PATH)

from flask import Flask


def create_app():
    app = Flask(__name__)

    # 注册蓝图
    from src.api.routes import players, analysis, upload
    app.register_blueprint(players.bp)
    app.register_blueprint(analysis.bp)
    app.register_blueprint(upload.bp)

    # 健康检查
    @app.route("/api/health")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=True)
