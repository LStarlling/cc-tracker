"""python -m server —— 启动 cc-tracker 收集器（固定 127.0.0.1:8765）。"""
import uvicorn

from .app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
