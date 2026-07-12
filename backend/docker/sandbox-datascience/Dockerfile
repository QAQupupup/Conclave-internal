# ===== Conclave 数据科学沙箱镜像 =====
# 基于 python:3.12-slim，预装数据分析 / 科学计算库
# 供 code_analysis / tested_system 等模板按需调用（见 sandbox.py 的 SANDBOX_IMAGE_DATASCIENCE）
#
# 安全约束保持与标准沙箱一致：运行时由 sandbox.py 传入
#   --network none --read-only --cap-drop ALL --user 65534:65534 --security-opt no-new-privileges
# 因此本镜像只负责“装包 + 配后端 + 非 root 兼容”，不放宽任何运行期安全策略。

FROM docker.m.daocloud.io/library/python:3.12-slim

# pip 镜像源（清华，国内加速）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# apt 镜像源（清华，国内加速；兼容 Debian Bookworm DEB822 格式）
RUN rm -f /etc/apt/sources.list.d/*.sources /etc/apt/sources.list && \
    { echo "Types: deb"; \
      echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian"; \
      echo "Suites: $(. /etc/os-release && echo $VERSION_CODENAME) $(. /etc/os-release && echo $VERSION_CODENAME)-updates"; \
      echo "Components: main"; \
      echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg"; \
      echo ""; \
      echo "Types: deb"; \
      echo "URIs: https://mirrors.tuna.tsinghua.edu.cn/debian-security"; \
      echo "Suites: $(. /etc/os-release && echo $VERSION_CODENAME)-security"; \
      echo "Components: main"; \
      echo "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg"; \
    } > /etc/apt/sources.list.d/tuna.sources && \
    apt-get update

# 预装数据科学库：
#   pandas / numpy          数据处理
#   matplotlib              绘图（后端 Agg，无显示环境）
#   scikit-learn (sklearn)  机器学习
#   seaborn                 统计可视化（依赖 pandas/matplotlib）
#   scipy                   科学计算
# 全部使用 manylinux 预编译 wheel，安装快、无需本地编译。
RUN pip install --no-cache-dir \
        pandas \
        numpy \
        matplotlib \
        scikit-learn \
        seaborn \
        scipy

# matplotlib 后端设为 Agg（无显示环境，避免 GUI / tkinter 依赖）
# MPLCONFIGDIR 指向 /tmp：运行期 --read-only 下只有 /tmp（tmpfs）可写，
# 让以非 root（65534）运行时写 matplotlib 配置目录不致失败。
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONUNBUFFERED=1

# 工作目录：与 sandbox.py 的 -v <host>:/workspace -w /workspace 对应
# 挂载卷会覆盖此目录，但仍创建并以 1777 授权，便于独立验证时写入。
RUN mkdir -p /workspace && chmod 1777 /workspace
WORKDIR /workspace

# 非 root 用户运行：UID/GID 65534 在 Debian 下即 nobody:nogroup，
# 与 sandbox.py 的 --user 65534:65534 完全兼容。
# 注意：USER 必须放在 pip install 之后，否则无法写入 /usr/local。
USER 65534:65534

# 默认保持 python 入口，便于直接验证：docker run --rm <img> python -c "..."
CMD ["python"]
