# mylib

可独立构建和安装的 Python 工具库，使用 `src` 布局、`uv_build` 构建后端，要求 Python 3.14+。目前提供最小的 `hello()` API，用于验证开发、打包与安装链路。

```python
from mylib import hello

print(hello())  # Hello from mylib!
```

## 开发

仓库内使用根目录的 `uv.lock`；`mylib` 自己声明运行时依赖和开发依赖。安装后的库不依赖 API、Rust 扩展或仓库根目录。

以下命令在 `mylib/` 下执行。单独指定虚拟环境，避免 `uv sync` 清理仓库根目录 `.venv` 中其他项目的依赖：

```bash
cd mylib
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
export UV_PYTHON=3.14
uv sync --locked
uv run --locked python -c 'from mylib import hello; print(hello())'
```

日常检查与格式化：

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest

# 自动修复可修复的问题，并格式化代码
uv run --locked ruff check --fix .
uv run --locked ruff format .
```

Ruff 配置放在本包的 `pyproject.toml`，覆盖基础错误、未使用导入、导入排序、现代 Python 写法、常见缺陷和类型注解。测试通过安装后的包导入，未把 `src` 手动加入搜索路径。`py.typed` 会随 wheel 分发。

新增运行时依赖使用 `uv add <package>`，开发工具使用 `uv add --dev <package>`；提交本包配置和更新后的根目录 `uv.lock`。

## 一键验证与构建

在仓库根目录执行：

```bash
bash mylib/scripts/check.sh
```

脚本会安装锁定的开发依赖，执行 Ruff 和 pytest，清理本包 `dist/` 后构建 sdist 与 wheel，使用 Twine 严格检查元数据和 README，再分别在独立环境中安装两个产物。安装检查包含公开 API、版本、Python 要求、子包和类型标记，且使用 `python -I` 避免误导入工作区源码。

产物位于 `mylib/dist/`：

```text
mylib-0.1.0.tar.gz
mylib-0.1.0-py3-none-any.whl
```

只构建时，在 `mylib/` 下运行：

```bash
uv build --no-sources --clear --out-dir dist
```

默认构建流程先生成 sdist，再从 sdist 构建 wheel。`--no-sources` 验证构建不依赖 workspace 的本地来源覆盖，`--clear` 避免输出目录混入旧版本。工作流 `.github/workflows/mylib.yml` 在相关 PR、`main` 推送和手动触发时执行同一检查脚本，并上传构建产物。

将 `mylib/` 单独复制到另一个仓库后，也可以直接 `uv build --no-sources`；首次开发时先 `uv lock` 生成该仓库自己的锁文件，再运行上述检查。

## 在其他项目中使用

在目标项目中安装本地源码或构建产物（替换为真实路径）：

```bash
# 开发期间，源码修改立即生效
uv add --editable /absolute/path/to/project-template/mylib

# 验证分发给使用者的 wheel
uv add /absolute/path/to/project-template/mylib/dist/mylib-0.1.0-py3-none-any.whl
```

在当前 workspace 的其他包中声明依赖，可从仓库根目录运行 `uv add --package api ./mylib`；仅成为 workspace member 不会自动成为 API 的依赖。

## 发布到 TestPyPI / PyPI

当前配置已支持生成分发包，但尚未上传。公开发布前需要确定发行名、许可证和项目描述，并准备相应平台的 API token 或 Trusted Publisher。

**PyPI 上的 [`mylib`](https://pypi.org/project/mylib/) 已被占用。** 如果不拥有该项目，先将 `[project].name` 改为你可使用的发行名，然后运行 `uv lock` 并重新检查。已显式设置 `module-name = "mylib"`，修改发行名后仍使用 `import mylib`，源码目录无需改名。以下发布命令使用 `dist/*`，会自动匹配新发行名的产物。

许可证尚未替你选择。确定后在本目录添加 `LICENSE`，在 `[project]` 中填写对应 SPDX `license` 表达式和 `license-files = ["LICENSE"]`；重新构建会将许可证纳入产物。

在 `mylib/` 下更新版本并验证：

```bash
# --no-sync 避免更新版本时同步其他开发环境
uv version --bump patch --no-sync
bash scripts/check.sh
```

通过环境变量 `UV_PUBLISH_TOKEN` 提供所选平台的 token，不要写进仓库。TestPyPI 与正式 PyPI 使用独立账号/凭证；先向 TestPyPI 上传：

```bash
uv publish --publish-url https://test.pypi.org/legacy/ \
  --check-url https://test.pypi.org/simple/ dist/*
```

确认测试包可安装后，切换为正式 PyPI token，上传同一批已检查的产物：

```bash
uv publish dist/*
```

发布后可在仓库外用实际发行名和版本验证（替换占位值）：

```bash
# TestPyPI；当前库没有运行时第三方依赖
uv run --no-project --isolated --python 3.14 \
  --default-index https://test.pypi.org/simple/ \
  --with 'your-distribution-name==0.1.1' \
  python -I -c 'from mylib import hello; print(hello())'

# 正式 PyPI
uv run --no-project --isolated --python 3.14 \
  --with 'your-distribution-name==0.1.1' \
  python -I -c 'from mylib import hello; print(hello())'
```

发布新内容需要新版本号；不要覆盖已上传的同版本文件。版本以 `pyproject.toml` 为准，运行时可使用 `importlib.metadata.version("发行名")` 查询。

参考：[uv 构建与发布](https://docs.astral.sh/uv/guides/package/)、[uv_build 配置](https://docs.astral.sh/uv/concepts/build-backend/)、[Ruff 配置](https://docs.astral.sh/ruff/configuration/)。
