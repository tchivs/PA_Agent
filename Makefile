.PHONY: run test lint setup-secrets

# 启动 GUI
run:
	uv run --frozen pa-agent

# 运行测试
test:
	uv run --frozen pytest -q

# 代码检查
lint:
	uv run --frozen ruff check . && uv run --frozen black --check .

# 启用 pre-commit，防止 settings / 日志 / 记录被提交
setup-secrets:
	powershell -ExecutionPolicy Bypass -File tools/setup_git_secrets.ps1
